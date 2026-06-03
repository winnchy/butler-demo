#!/bin/bash
set -e

echo "============================================"
echo " Butler Agent (Service 2) Starting..."
echo "============================================"
echo "PORT=${PORT:-8080}"
echo "BACKEND_URL=${BACKEND_URL:-http://localhost:8000}"
echo "BUTLER_DIR=/app/butler"
echo ""

# ================================================================
# 1. 配置 OpenClaw Gateway
# ================================================================
echo ">>> Configuring OpenClaw Gateway..."

# Gateway 模式
openclaw config set gateway.mode local 2>/dev/null || true

# 工作区 (butler 文件)
openclaw config set workspace /app/butler 2>/dev/null || true

# DeepSeek Provider 配置（官方文档格式）
if [ -n "$OPENAI_API_KEY" ]; then
    # 升级到最新版（DeepSeek需要>=2026.4.24）
    npm update -g openclaw@latest 2>/dev/null || true

    # 手动写入 openclaw.json 配置文件（config set 的 provider 格式对 Gateway 可能无效）
    mkdir -p /root/.openclaw
    cat > /root/.openclaw/openclaw.json << 'OCEOF'
{
  "models": {
    "mode": "merge",
    "providers": {
      "deepseek": {
        "baseUrl": "https://api.deepseek.com",
        "apiKey": "DEEPSEEK_KEY_PLACEHOLDER",
        "api": "openai-completions",
        "models": [
          {"id": "deepseek-chat", "name": "DeepSeek Chat", "reasoning": false,
           "input": ["text"], "contextWindow": 128000, "maxTokens": 8192,
           "cost": {"input": 0.00000028, "output": 0.00000042, "cacheRead": 0.000000028, "cacheWrite": 0.00000028}}
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {"primary": "deepseek/deepseek-chat"}
    }
  }
}
OCEOF
    # 替换占位符
    sed -i "s|DEEPSEEK_KEY_PLACEHOLDER|${OPENAI_API_KEY}|g" /root/.openclaw/openclaw.json
    echo "[OK] DeepSeek provider configured (deepseek/deepseek-chat)"
else
    echo "[WARN] OPENAI_API_KEY not set"
fi

echo ""

# ================================================================
# 2. 初始化用户文件 (默认白领小琴)
# ================================================================
if [ -f /app/butler/profiles/users/whitecollar.md ]; then
    cp /app/butler/profiles/users/whitecollar.md /app/butler/USER.md
    cp /app/butler/profiles/memories/whitecollar-memory.md /app/butler/MEMORY.md
    cp /app/butler/profiles/users/whitecollar-wardrobe.md /app/butler/wardrobe.md 2>/dev/null || true
    echo "[OK] Default user: 小琴 (白领)"
fi
echo ""

# ================================================================
# 3. 启动 MCP Bridge (后台)
#    OpenClaw 可通过 MCP 协议连接此 bridge 调用后端 API
# ================================================================
echo ">>> Starting MCP Bridge (port 18790)..."
cd /app/agent
python -u mcp_bridge.py &
MCP_PID=$!
sleep 1
if kill -0 $MCP_PID 2>/dev/null; then
    echo "[OK] MCP Bridge started (PID $MCP_PID)"
else
    echo "[WARN] MCP Bridge failed to start"
fi
echo ""

# ================================================================
# 4. 启动 OpenClaw Gateway (后台)
#    读取 /app/butler 下的 SOUL.md + SKILL.md + USER.md + MEMORY.md
#    可通过 MCP bridge 调用后端工具
# ================================================================
echo ">>> Starting OpenClaw Gateway on port 18789..."
# 关闭 WS 认证挑战（demo 环境）
export OPENCLAW_AUTH_ENABLED=false
export NODE_ENV=development
export DISABLE_CHALLENGE=true
export OPENCLAW_GATEWAY_PASSWORD=butler-demo-2026
# 配置 Gateway 密码供 CLI 使用
openclaw config set gateway.auth.password butler-demo-2026 2>/dev/null || true
openclaw config set gateway.auth.token butler-demo-2026 2>/dev/null || true
openclaw gateway --port 18789 --allow-unconfigured --password butler-demo-2026 &
OC_PID=$!
sleep 3
if kill -0 $OC_PID 2>/dev/null; then
    echo "[OK] OpenClaw Gateway started (PID $OC_PID)"
else
    echo "[WARN] Gateway failed to start"
fi
echo ""

# ================================================================
# 5. 启动 Chat Proxy (前台 — Railway 通过 $PORT 路由)
#    提供 H5 聊天界面 + /chat 端点
#    优先转发到 OpenClaw Gateway，不可用时降级直连 DeepSeek
# ================================================================
echo ">>> Starting Chat Proxy on port ${PORT:-8080}..."
echo "    OpenClaw Gateway → localhost:18789"
echo "    MCP Bridge       → localhost:18790"
echo "    Mock Backend     → ${BACKEND_URL}"
echo "    Fallback: Direct DeepSeek + 13 mock tools"
echo ""

cd /app/agent
exec uvicorn chat_proxy:app --host 0.0.0.0 --port ${PORT:-8080}
