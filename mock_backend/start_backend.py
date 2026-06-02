"""Railway 启动脚本 — 读取 PORT 环境变量，启动 uvicorn，带完整诊断"""
import os
import sys
import traceback

print("=" * 50, flush=True)
print("[startup] begin", flush=True)
print(f"[startup] cwd = {os.getcwd()}", flush=True)
print(f"[startup] PORT = {os.environ.get('PORT', 'NOT SET')}", flush=True)
print(f"[startup] files in /app = {os.listdir('/app')[:20]}", flush=True)
print(f"[startup] data/enriched exists = {os.path.exists('data/enriched')}", flush=True)
if os.path.exists('data/enriched'):
    print(f"[startup] enriched files = {os.listdir('data/enriched')[:5]}", flush=True)
print(f"[startup] main_api.py exists = {os.path.exists('main_api.py')}", flush=True)
print(f"[startup] global_state.py exists = {os.path.exists('global_state.py')}", flush=True)
print("=" * 50, flush=True)

port = int(os.environ.get("PORT", "8000"))

try:
    import uvicorn
    print(f"[startup] Starting uvicorn on 0.0.0.0:{port}...", flush=True)
    uvicorn.run("main_api:app", host="0.0.0.0", port=port, log_level="info")
except Exception as e:
    print(f"[startup] FATAL: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)
