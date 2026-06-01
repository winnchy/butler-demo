FROM python:3.12-slim
WORKDIR /app

# 装 Node.js 和 npm（OpenClaw 需要）
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean

# 装 Python 依赖
COPY mock_backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY mock_backend/ mock_backend/
COPY butler/ butler/

# 生成数据
RUN cd mock_backend && python enrich_pois.py && python route_generator.py

# 装 OpenClaw
RUN npm install -g openclaw@2026.4.15

EXPOSE 8000 3000
COPY start.sh .
CMD ["bash", "start.sh"]
