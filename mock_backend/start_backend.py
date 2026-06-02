"""Railway 启动脚本 — 读取 PORT 环境变量，启动 uvicorn"""
import os
import uvicorn

port = int(os.environ.get("PORT", "8000"))
print(f"[start_backend] Starting on port {port}")
uvicorn.run("main_api:app", host="0.0.0.0", port=port)
