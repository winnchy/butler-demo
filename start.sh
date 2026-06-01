#!/bin/bash
echo "Starting mock_backend on :8000..."
cd /app/mock_backend && uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 5
echo "Starting OpenClaw on :3000..."
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com/v1}"
export OPENCLAW_MODEL="${OPENCLAW_MODEL:-deepseek-chat}"
cd /app/butler && openclaw start --port 3000 &
wait
