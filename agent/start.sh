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
    # 注册 MCP 到 OpenClaw config，让 --local 模式也能调后端工具
    sleep 1
    openclaw mcp add butler-backend http://localhost:18790 2>/dev/null || true
    # 同时写入 openclaw.json 以确保持久化
    python3 -c "
import json, os
cfg_path = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = {}
if os.path.exists(cfg_path):
    with open(cfg_path) as f: cfg = json.load(f)
cfg.setdefault('mcp', {}).setdefault('servers', {})['butler-backend'] = {
    'type': 'http', 'url': 'http://localhost:18790', 'transport': 'http'
}
with open(cfg_path, 'w') as f: json.dump(cfg, f, indent=2)
print('[OK] MCP registered in openclaw.json')
" 2>/dev/null || echo "[WARN] MCP registration skipped"
else
    echo "[WARN] MCP Bridge failed to start"
fi
echo ""

# ================================================================
# 4. 确保 OpenClaw Agent 能读取 butler workspace 文件
#    多重策略：环境变量 + config + agent目录拷贝
# ================================================================
echo ">>> Configuring butler workspace for OpenClaw agent..."

# 策略1: 环境变量
export OPENCLAW_WORKSPACE=/app/butler
export OPENCLAW_WORKSPACE_DIR=/app/butler

# 策略2: config set (针对 Gateway 模式)
openclaw config set workspace /app/butler 2>/dev/null || true

# 策略3: 复制 butler 文件到 agent 目录 (针对 --local 模式)
#         openclaw agent --local 可能只读 ~/.openclaw/agents/main/ 或 CWD
mkdir -p /root/.openclaw/agents/main
for f in SOUL.md USER.md MEMORY.md HEARTBEAT.md wardrobe.md; do
    if [ -f "/app/butler/$f" ]; then
        cp "/app/butler/$f" "/root/.openclaw/agents/main/$f"
        echo "  [copy] $f -> ~/.openclaw/agents/main/"
    fi
done
# 也复制 skills 目录
if [ -d "/app/butler/skills" ]; then
    cp -r /app/butler/skills /root/.openclaw/agents/main/skills 2>/dev/null || true
    echo "  [copy] skills/ -> ~/.openclaw/agents/main/"
fi
# 也复制 profiles 目录
if [ -d "/app/butler/profiles" ]; then
    cp -r /app/butler/profiles /root/.openclaw/agents/main/profiles 2>/dev/null || true
    echo "  [copy] profiles/ -> ~/.openclaw/agents/main/"
fi
echo "[OK] Butler files mirrored to agent directory"

# ================================================================
# 5. 启动 OpenClaw Gateway (后台)
#    读取 /app/butler 下的 SOUL.md + SKILL.md + USER.md + MEMORY.md
#    可通过 MCP bridge 调用后端工具
# ================================================================
echo ">>> Starting OpenClaw Gateway on port 18789..."
# 关闭 WS 认证挑战（demo 环境）
export OPENCLAW_AUTH_ENABLED=false
export NODE_ENV=development
export DISABLE_CHALLENGE=true
export OPENCLAW_GATEWAY_PASSWORD=butler-demo-2026
export OPENCLAW_WORKSPACE=/app/butler
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

# 快速验证: --local 模式能否读到 butler 身份
echo ">>> Quick test: openclaw agent --local identity check..."
TEST_OUT=$(timeout 25 openclaw agent -m "你是谁" --json --agent main --local 2>&1 || true)
if echo "$TEST_OUT" | grep -qiE "管家|butler|小琴|全天候|私人管家|SOUL"; then
    echo "[OK] Agent knows its identity! (reads butler files)"
else
    echo "[WARN] Agent might not be reading butler files. First 300 chars:"
    echo "$TEST_OUT" | head -c 300
    echo ""
fi
echo ""

# ================================================================
# 6. 启动 Chat Proxy (前台 — Railway 通过 $PORT 路由)
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
