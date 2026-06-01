FROM python:3.12-slim
WORKDIR /app
COPY mock_backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mock_backend/ .
RUN python enrich_pois.py && python route_generator.py
EXPOSE 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
