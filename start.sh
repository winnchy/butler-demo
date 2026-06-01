#!/bin/bash
set -e

DS_KEY="${OPENAI_API_KEY:-}"

echo ">>> Starting mock_backend on :8000..."
cd /app/mock_backend && uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 3

echo ">>> Configuring OpenClaw with DeepSeek..."
mkdir -p ~/.openclaw
openclaw doctor --fix 2>/dev/null || true
openclaw config set gateway.mode local 2>/dev/null || true
openclaw config set gateway.auth.token butler-demo-2026 2>/dev/null || true
openclaw config set workspace /app/butler 2>/dev/null || true

# 写入完整配置，注册 DeepSeek 为自定义 provider
cat > /tmp/oc_config.json << ENDJSON
{
  "workspace": "/app/butler",
  "gateway": {
    "mode": "local",
    "port": 18789,
    "bind": "0.0.0.0",
    "auth": { "token": "butler-demo-2026" }
  },
  "models": {
    "mode": "merge",
    "default": "deepseek/deepseek-v4-pro[1m]",
    "providers": {
      "deepseek": {
        "baseUrl": "https://api.deepseek.com/v1",
        "apiKey": "${DS_KEY}",
        "api": "openai-completions",
        "models": ["deepseek-v4-pro[1m]"]
      }
    }
  }
}
ENDJSON

cp /tmp/oc_config.json ~/.openclaw/openclaw.json

echo ">>> Starting OpenClaw Gateway on :18789..."
openclaw gateway --port 18789 --allow-unconfigured --password butler-demo-2026 &
sleep 5

echo ">>> All services started! mock_backend:8000 OpenClaw:18789"
wait
