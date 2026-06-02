FROM python:3.12-slim
WORKDIR /app

# Node.js 22 (OpenClaw 需要)
RUN apt-get update && apt-get install -y curl git && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && apt-get clean

# OpenClaw Gateway
RUN npm install -g openclaw@latest

# Python 依赖
COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY agent/ agent/
COPY butler/ butler/

# 预配置 OpenClaw
RUN mkdir -p /root/.openclaw && \
    openclaw config set gateway.mode local || true && \
    openclaw config set workspace /app/butler || true

EXPOSE 8080 18789 18790

CMD ["bash", "agent/start.sh"]
