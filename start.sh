#!/bin/bash

echo ">>> Starting mock_backend on :8000..."
cd /app/mock_backend && uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 3

echo ">>> Configuring OpenClaw with DeepSeek..."
mkdir -p ~/.openclaw
openclaw config set gateway.mode local 2>/dev/null
openclaw config set gateway.auth.token butler-demo-2026 2>/dev/null
openclaw config set workspace /app/butler 2>/dev/null
openclaw config set models.default "deepseek/deepseek-v4-pro[1m]" 2>/dev/null
openclaw config set auth.deepseek.apiKey "${OPENAI_API_KEY}" 2>/dev/null

echo ">>> Starting OpenClaw Gateway on :18789..."
openclaw gateway --port 18789 --allow-unconfigured --password butler-demo-2026 &
sleep 5

echo ">>> Done: mock_backend:8000 OpenClaw:18789"
wait
