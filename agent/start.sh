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

# DeepSeek 作为 OpenAI 兼容 provider 配置
OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com/v1}"
if [ -n "$OPENAI_API_KEY" ]; then
    # 方案1: 注册 deepseek provider
    openclaw config set providers.deepseek.baseUrl "${OPENAI_BASE_URL}" 2>/dev/null || true
    openclaw config set providers.deepseek.apiKey "${OPENAI_API_KEY}" 2>/dev/null || true
    openclaw config set providers.deepseek.api "openai-completions" 2>/dev/null || true
    # 方案2: 覆盖默认 openai provider 指向 DeepSeek
    openclaw config set providers.openai.baseUrl "${OPENAI_BASE_URL}" 2>/dev/null || true
    openclaw config set providers.openai.apiKey "${OPENAI_API_KEY}" 2>/dev/null || true
    # 设置默认模型
    openclaw config set models.default "deepseek/deepseek-chat" 2>/dev/null || true
    echo "[OK] DeepSeek configured as provider (deepseek + openai override)"
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
echo ">>> Starting OpenClaw (Gateway + Agent) on port 18789..."
# 尝试 serve 模式（同时启动 Gateway + Agent Core）
openclaw serve --port 18789 --allow-unconfigured --password butler-demo-2026 &
OC_PID=$!
sleep 5

if kill -0 $OC_PID 2>/dev/null; then
    echo "[OK] OpenClaw started (PID $OC_PID)"
    # 探测可用端点
    for ep in /health /api/chat /v1/chat /api/v1/chat /chat; do
        if curl -s http://localhost:18789$ep -o /dev/null -w "%{http_code}" 2>/dev/null | grep -q '200\|201\|400\|401'; then
            echo "  Found endpoint: $ep"
        fi
    done
else
    echo "[WARN] openclaw serve failed, trying gateway mode..."
    openclaw gateway --port 18789 --allow-unconfigured --password butler-demo-2026 &
    OC_PID=$!
    sleep 3
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
