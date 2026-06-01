#!/bin/bash
set -e

echo ">>> Starting mock_backend on :8000..."
cd /app/mock_backend && uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 3

echo ">>> Configuring OpenClaw..."
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com/v1}"

# 创建 OpenClaw 配置目录
mkdir -p ~/.openclaw

# 用 openclaw doctor 自动生成有效配置（不手写，避免格式错误）
rm -f ~/.openclaw/openclaw.json
openclaw doctor --fix 2>/dev/null || true

echo ">>> Starting OpenClaw Gateway on :18789..."
openclaw gateway --port 18789 --workspace /app/butler --allow-unconfigured --password butler-demo-2026 --verbose &
sleep 3

echo ">>> All services started!"
echo "    mock_backend: http://localhost:8000"
echo "    OpenClaw:     http://localhost:18789"

wait
