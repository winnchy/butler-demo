#!/bin/bash
set -e
echo "========================================"
echo "  Butler - 全天候私人管家 一键部署"
echo "========================================"
echo ""

# 检查 .env
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "[!] 已创建 .env，请编辑填入 ANTHROPIC_API_KEY 后重新运行"
    echo "    nano .env"
    exit 1
  else
    echo "[!] 缺少 .env.example，请手动创建 .env"
    exit 1
  fi
fi

# 自动检测 Docker 或 Podman
if command -v docker &> /dev/null; then
  COMPOSE="docker compose"
  echo "[OK] 检测到 Docker"
elif command -v podman &> /dev/null; then
  COMPOSE="podman-compose"
  echo "[OK] 检测到 Podman"
else
  echo "[!] 未安装 Docker 或 Podman，请先安装"
  exit 1
fi

echo "[1/2] 构建镜像（首次可能需要几分钟）..."
$COMPOSE build

echo "[2/2] 启动服务..."
$COMPOSE up -d

echo ""
echo "========================================"
echo "  部署完成！"
echo "========================================"
echo "  H5 聊天界面: http://localhost:8000"
echo "  API 文档:    http://localhost:8000/docs"
echo "  管理面板:    http://localhost:8000/admin/dashboard"
echo "  OpenClaw:    http://localhost:3000"
echo ""
echo "  查看日志: $COMPOSE logs -f"
echo "  停止服务: $COMPOSE down"
