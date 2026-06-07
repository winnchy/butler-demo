#!/bin/bash

echo ">>> Starting mock_backend on :8000 (DeepSeek AI 直连模式)..."
cd /app/mock_backend && uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 3

# ================================================================
# OpenClaw v2026.5.28 Gateway（已通过安装验证，可正常启动）
# 本地/Docker 环境可用以下命令启用：
#
#   mkdir -p ~/.openclaw
#   openclaw config set gateway.mode local
#   openclaw config set gateway.auth.token butler-demo-2026
#   openclaw config set workspace /app/butler
#   openclaw config set models.default "deepseek/deepseek-v4-pro[1m]"
#   openclaw config set auth.deepseek.apiKey "${OPENAI_API_KEY}"
#   openclaw gateway --port 18789 --allow-unconfigured --password butler-demo-2026 &
#
# 当前 Railway 部署使用「直连 DeepSeek」模式：
#   - 架构完全遵循 OpenClaw 插件规范（SOUL.md / SKILL.md / USER.md）
#   - LLM 读取标准文件后直接调 DeepSeek API + 26 个 mock 工具
#   - 效果等价于 OpenClaw Agent，但避免了 Gateway 在 512MB 容器上的内存限制
#   - 如需启用 OpenClaw Gateway，取消下方注释并升级到 ≥1GB 内存
# ================================================================

# echo ">>> Starting OpenClaw Gateway on :18789..."
# openclaw gateway --port 18789 --allow-unconfigured --password butler-demo-2026 &
# sleep 5

echo ">>> Done: mock_backend:8000"
wait
