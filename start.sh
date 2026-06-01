#!/bin/bash
set -e

# ⚠️ 必须先设置环境变量，再启动服务（Python 启动后才读到 Key）
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com/v1}"

echo ">>> Starting mock_backend on :8000..."
cd /app/mock_backend && uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 3

echo ">>> Configuring OpenClaw..."
mkdir -p ~/.openclaw
rm -f ~/.openclaw/openclaw.json
openclaw doctor --fix 2>/dev/null || true

echo ">>> Starting OpenClaw Gateway on :18789..."
openclaw config set workspace /app/butler 2>/dev/null || true
openclaw gateway --port 18789 --bind 0.0.0.0 --allow-unconfigured --password butler-demo-2026 &
sleep 3

echo ">>> All services started!"
echo "    mock_backend: http://localhost:8000"
echo "    OpenClaw:     http://localhost:18789"

wait
