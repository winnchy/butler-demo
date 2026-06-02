"""
Mock Backend API Server — Service 1 (纯 API，不含 AI 对话)
为 OpenClaw Agent (Service 2) 提供动态模拟数据
启动时加载丰富化数据 + 初始化 WorldState + 挂载 API 路由
"""

import json
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from world_state import WorldState
from route_generator import MetroNetwork, RoadNetwork, RoutePlanner
import global_state

# ---- 全局对象（通过 global_state 模块暴露给 api_routes）----
STATIC_DATA: dict = {}
metro_network: MetroNetwork = None
road_network: RoadNetwork = None
route_planner: RoutePlanner = None
world_state: WorldState = None


def load_static_data(enriched_dir: str = "data/enriched"):
    """加载所有丰富化 JSON 到内存"""
    global STATIC_DATA
    STATIC_DATA = {}
    for fname in os.listdir(enriched_dir):
        if fname.endswith(".json") and fname not in (
            "metro_network.json", "routes_index.json", "facility_index.json"
        ):
            path = os.path.join(enriched_dir, fname)
            with open(path, "r", encoding="utf-8") as f:
                key = fname.replace(".json", "")
                STATIC_DATA[key] = json.load(f)
    total = sum(len(v) for v in STATIC_DATA.values())
    print(f"[StaticData] Loaded {len(STATIC_DATA)} categories, {total} POIs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global metro_network, road_network, route_planner, world_state

    print("=" * 50, flush=True)
    print("Mock Backend API Server Starting (Service 1)...", flush=True)
    print("=" * 50, flush=True)

    try:
        load_static_data()
        print(f"[Server] Static data loaded: {len(STATIC_DATA)} categories", flush=True)
    except Exception as e:
        print(f"[Server] ERROR loading static data: {e}", flush=True)
        import traceback; traceback.print_exc()

    try:
        metro_path = "data/enriched/metro_stations.json"
        if os.path.exists(metro_path):
            with open(metro_path, "r", encoding="utf-8") as f:
                metro_stations = json.load(f)
            metro_network = MetroNetwork()
            metro_network.build(metro_stations)
            road_network = RoadNetwork()
            road_network.build()
            route_planner = RoutePlanner(metro_network, road_network)
            print("[Server] Route planner initialized", flush=True)
        else:
            print(f"[Server] WARN: metro_stations.json not found at {metro_path}", flush=True)
    except Exception as e:
        print(f"[Server] ERROR building route network: {e}", flush=True)
        import traceback; traceback.print_exc()

    try:
        world_state = WorldState()
        world_state.init_from_enriched("data/enriched")
        world_state.start()
        print("[Server] WorldState started", flush=True)
    except Exception as e:
        print(f"[Server] ERROR starting WorldState: {e}", flush=True)
        import traceback; traceback.print_exc()

    # 同步到 global_state 模块（供 api_routes 访问，避免循环导入）
    global_state.STATIC_DATA = STATIC_DATA
    global_state.metro_network = metro_network
    global_state.road_network = road_network
    global_state.route_planner = route_planner
    global_state.world_state = world_state

    port = os.environ.get("PORT", "8000")
    print(f"[Server] Mock Backend ready at http://0.0.0.0:{port}", flush=True)

    yield

    print("[Server] Shutting down...", flush=True)
    if world_state:
        world_state.stop()
        world_state.save_state("data/world_state_snapshot.json")


app = FastAPI(
    title="LocalLife Butler Mock Backend",
    description="动态模拟北京本地生活数据的 Mock 后端 — 为 OpenClaw Agent 提供 REST API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
async def startup_diagnostics():
    """启动后打印诊断信息（用 logging，确保在 Railway 日志中可见）"""
    import logging
    log = logging.getLogger("uvicorn")
    log.info(f"[DIAG] PORT env = {os.environ.get('PORT', 'NOT SET')}")
    log.info(f"[DIAG] STATIC_DATA keys = {len(STATIC_DATA)}")
    log.info(f"[DIAG] world_state = {world_state is not None}")
    log.info(f"[DIAG] metro_network = {metro_network is not None}")
    log.info(f"[DIAG] global_state.world_state = {global_state.world_state is not None}")
    log.info(f"[DIAG] data/enriched exists = {os.path.exists('data/enriched')}")
    log.info(f"[DIAG] cwd = {os.getcwd()}")


# ---- 基础端点 ----

@app.get("/")
def root():
    """服务入口 → 跳转到管理面板"""
    return {
        "service": "LocalLife Butler Mock Backend (Service 1)",
        "version": "2.0.0",
        "docs": "/docs",
        "dashboard": "/admin/dashboard",
        "health": "/health",
        "api_prefix": "/api",
    }


@app.get("/health")
def health():
    """健康检查"""
    return {
        "status": "ok",
        "service": "mock-backend",
        "ws_active": world_state._running if world_state else False,
        "static_data_categories": len(STATIC_DATA) if STATIC_DATA else 0,
    }


@app.get("/debug/env")
def debug_env():
    """诊断：检查环境变量"""
    import os
    key = os.environ.get("OPENAI_API_KEY", "")
    return {
        "openai_api_key_set": bool(key),
        "port": os.environ.get("PORT", "8000"),
        "backend_url": os.environ.get("BACKEND_URL", "not set"),
    }


# ---- 挂载子路由 ----

from api_routes.dining_routes import router as dining_router
from api_routes.mobility_routes import router as mobility_router
from api_routes.city_routes import router as city_router
from api_routes.outfit_routes import router as outfit_router
from api_routes.life_routes import router as life_router
from api_routes.admin_routes import router as admin_router

app.include_router(dining_router, prefix="/api/dining", tags=["Dining"])
app.include_router(mobility_router, prefix="/api/mobility", tags=["Mobility"])
app.include_router(city_router, prefix="/api/city", tags=["City"])
app.include_router(outfit_router, prefix="/api", tags=["Outfit & Weather"])
app.include_router(life_router, prefix="/api", tags=["Life & Schedule"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main_api:app", host="0.0.0.0", port=port)
