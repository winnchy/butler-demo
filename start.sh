#!/bin/bash
set -e

echo ">>> Starting mock_backend on :8000..."
cd /app/mock_backend && uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 3

echo ">>> Configuring OpenClaw with DeepSeek..."
mkdir -p ~/.openclaw

# 用 DeepSeek 官方推荐的 onboard 流程，自动回答所有提示
printf 'y\ny\nDeepSeek\n%s\ndeepseek-v4-pro[1m]\n\n' "${OPENAI_API_KEY}" | openclaw onboard --install-daemon 2>/dev/null || true

# 确保 workspace 指向 butler
openclaw config set workspace /app/butler 2>/dev/null || true

echo ">>> Starting OpenClaw Gateway on :18789..."
openclaw gateway --port 18789 --allow-unconfigured --password butler-demo-2026 &
sleep 5

echo ">>> All services started! mock_backend:8000 OpenClaw:18789"
wait
