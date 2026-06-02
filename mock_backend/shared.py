"""
共享全局状态 — 消除 main_api ↔ api_routes 之间的循环导入
main_api.py 在初始化时设置这些引用，api_routes 通过 import shared 访问
"""

STATIC_DATA: dict = {}
metro_network = None
road_network = None
route_planner = None
world_state = None
