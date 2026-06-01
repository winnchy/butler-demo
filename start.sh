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

# 写入 OpenClaw 配置
cat > ~/.openclaw/openclaw.json << 'EOF'
{
  "workspace": "/app/butler",
  "gateway": {
    "mode": "local",
    "port": 18789,
    "host": "0.0.0.0"
  },
  "models": {
    "default": "deepseek-chat",
    "provider": "openai",
    "baseURL": "https://api.deepseek.com/v1"
  }
}
EOF

echo ">>> Starting OpenClaw Gateway on :18789..."
openclaw gateway --port 18789 --allow-unconfigured --verbose &
sleep 3

echo ">>> All services started!"
echo "    mock_backend: http://localhost:8000"
echo "    OpenClaw:     http://localhost:18789"

wait
