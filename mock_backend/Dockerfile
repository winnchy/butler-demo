FROM python:3.12-slim
WORKDIR /app

# 只装 Python 依赖（不需要 Node.js/OpenClaw，那是 Service 2 的事）
COPY mock_backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY mock_backend/ .

# 生成模拟数据
RUN python data_generator.py && python route_generator.py

# Railway 通过 $PORT 注入端口
# Force cache miss — v2 diagnostic update
CMD ["python", "start_backend.py"]
