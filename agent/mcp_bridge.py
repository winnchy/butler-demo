"""
MCP Bridge Server — 将 mock_backend API 注册为 MCP 工具
OpenClaw Gateway 通过 MCP 协议 (JSON-RPC 2.0 over stdio) 连接此 bridge
工具调用被转发到 BACKEND_URL (Service 1)
"""

import sys
import json
import os
import threading
import requests

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "10"))

# ---- 工具定义 (13个, 对应 mock_backend 的全部 API) ----

TOOLS = [
    # === dining-butler ===
    {
        "name": "restaurant_recommend",
        "description": "推荐餐厅，支持菜系/预算/设施/过敏过滤。用户画像自动过滤偏好。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "用户ID: white_collar/parent/student"},
                "cuisine": {"type": "string", "description": "菜系: 川菜/粤菜/火锅/日料/西餐/快餐/湘菜/东北菜/烧烤/小吃 等"},
                "budget": {"type": "integer", "description": "人均预算上限(元)"},
                "people_count": {"type": "integer", "description": "用餐人数"},
                "scene": {"type": "string", "description": "场景: business/family/date/casual"},
                "must_have": {"type": "string", "description": "必备设施: baby_seat/parking/private_room/pet_allowed"},
                "avoid_ingredients": {"type": "string", "description": "忌口食材: 花生/海鲜/牛奶 等"},
                "latitude": {"type": "number", "description": "当前位置纬度"},
                "longitude": {"type": "number", "description": "当前位置经度"},
            },
            "required": ["user_id"]
        }
    },
    {
        "name": "restaurant_queue",
        "description": "查询餐厅当前排队状态和预计等待时间",
        "inputSchema": {
            "type": "object",
            "properties": {
                "restaurant_id": {"type": "integer", "description": "餐厅ID"}
            },
            "required": ["restaurant_id"]
        }
    },
    {
        "name": "restaurant_emergency",
        "description": "突发兜底方案：暴雨/满座/迟到/餐厅歇业时的替代餐厅推荐",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "emergency_type": {"type": "string", "description": "weather/full/late/closure"},
                "current_lat": {"type": "number"},
                "current_lng": {"type": "number"},
                "has_child": {"type": "boolean"}
            },
            "required": ["emergency_type", "current_lat", "current_lng"]
        }
    },
    # === mobility-butler ===
    {
        "name": "plan_route",
        "description": "多模式路径规划：驾车/地铁/骑行/步行/打车。考虑实时路况。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin_lat": {"type": "number"}, "origin_lon": {"type": "number"},
                "dest_lat": {"type": "number"}, "dest_lon": {"type": "number"},
                "user_type": {"type": "string", "description": "用户类型影响排序: white_collar按时间/parent按安全/student按费用"}
            },
            "required": ["origin_lat", "origin_lon", "dest_lat", "dest_lon"]
        }
    },
    {
        "name": "transport_search",
        "description": "查机票/火车票（模拟数据）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin_city": {"type": "string"}, "dest_city": {"type": "string"},
                "transport_type": {"type": "string", "description": "flight/train/all"}
            },
            "required": ["origin_city", "dest_city"]
        }
    },
    {
        "name": "nearby_facilities",
        "description": "周边设施：加油站/充电桩/便利店/停车场/药店/宠物医院",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "facility_type": {"type": "string", "description": "gas_station/charging/convenience/parking/pharmacy/pet_hospital"}
            },
            "required": ["lat", "lon", "facility_type"]
        }
    },
    # === outfit-advisor ===
    {
        "name": "get_weather",
        "description": "获取北京当前天气、AQI、预警信息",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_outfit",
        "description": "基于当前天气+用户身份+衣橱的穿搭建议",
        "inputSchema": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"]
        }
    },
    {
        "name": "get_wardrobe",
        "description": "查询用户衣橱物品清单和缺失物品",
        "inputSchema": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"]
        }
    },
    # === city-explorer ===
    {
        "name": "get_events",
        "description": "周末/近期活动：展览/演出/市集/亲子/演唱会",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "exhibition/show/market/kids/concert/all"},
                "user_id": {"type": "string"}
            }
        }
    },
    {
        "name": "get_shopping",
        "description": "商场促销信息",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "clothing/electronics/home/child/all"}
            }
        }
    },
    # === life-organizer ===
    {
        "name": "get_schedule",
        "description": "查询用户今日日程安排",
        "inputSchema": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"]
        }
    },
    {
        "name": "search_memory",
        "description": "搜索用户偏好记忆和长期档案",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "keyword": {"type": "string"}
            },
            "required": ["user_id"]
        }
    },
    # === dining-butler (补充) ===
    {
        "name": "restaurant_take_number",
        "description": "线上取号。用户选定餐厅后主动取号，返回号牌和预计等待时间",
        "inputSchema": {
            "type": "object",
            "properties": {
                "restaurant_id": {"type": "integer"},
                "user_id": {"type": "string"}
            },
            "required": ["restaurant_id", "user_id"]
        }
    },
    {
        "name": "restaurant_reserve",
        "description": "预订餐厅包厢/座位。商务宴请或特殊场合使用",
        "inputSchema": {
            "type": "object",
            "properties": {
                "restaurant_id": {"type": "integer"},
                "user_id": {"type": "string"},
                "date": {"type": "string"},
                "time": {"type": "string"},
                "people": {"type": "integer"}
            },
            "required": ["restaurant_id", "user_id"]
        }
    },
    {
        "name": "restaurant_detail",
        "description": "获取餐厅详细信息：地址、电话、特色菜、评分、停车、优惠等",
        "inputSchema": {
            "type": "object",
            "properties": {"restaurant_id": {"type": "integer"}},
            "required": ["restaurant_id"]
        }
    },
    {
        "name": "restaurant_monitor",
        "description": "开启排队监控。取号后开启，排队到了自动提醒",
        "inputSchema": {
            "type": "object",
            "properties": {
                "restaurant_id": {"type": "integer"},
                "user_id": {"type": "string"},
                "alert_threshold": {"type": "integer", "description": "低于N桌时提醒"}
            },
            "required": ["restaurant_id", "user_id"]
        }
    },
    {
        "name": "restaurant_review",
        "description": "提交用餐评价。吃完后收集反馈，闭环更新偏好",
        "inputSchema": {
            "type": "object",
            "properties": {
                "restaurant_id": {"type": "integer"},
                "user_id": {"type": "string"},
                "rating": {"type": "integer", "description": "1-5分"},
                "comment": {"type": "string"}
            },
            "required": ["restaurant_id", "user_id", "rating"]
        }
    },
    {
        "name": "restaurant_takeout",
        "description": "查外卖选项。下雨/生病/不想出门时推荐外卖",
        "inputSchema": {
            "type": "object",
            "properties": {
                "restaurant_id": {"type": "integer"},
                "user_id": {"type": "string"}
            },
            "required": ["user_id"]
        }
    },
    # === mobility-butler (补充) ===
    {
        "name": "call_taxi",
        "description": "一键叫车。返回车牌、车型、颜色、司机、电话、等待时间、预估费用",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin_lat": {"type": "number"},
                "origin_lon": {"type": "number"},
                "dest_lat": {"type": "number"},
                "dest_lon": {"type": "number"},
                "car_type": {"type": "string", "description": "economy/comfort/business"}
            },
            "required": ["origin_lat", "origin_lon"]
        }
    },
    {
        "name": "get_traffic",
        "description": "当前北京路况：拥堵指数、热点堵车区域",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # === outfit-advisor (补充) ===
    {
        "name": "weather_forecast",
        "description": "未来几天天气预报。用户问明天/周末天气时调",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "weather_alerts",
        "description": "当前天气预警：沙尘暴/暴雨/大风/高温。极端天气必调",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # === city-explorer (补充) ===
    {
        "name": "kids_activities",
        "description": "亲子活动推荐。带孩子的家庭用户专用",
        "inputSchema": {
            "type": "object",
            "properties": {
                "age_range": {"type": "string", "description": "0-3/4-6/7-12"},
                "user_id": {"type": "string"}
            }
        }
    },
    # === life-organizer (补充) ===
    {
        "name": "schedule_create",
        "description": "创建日程提醒。用户说提醒我/设闹钟/别忘了时调",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "title": {"type": "string"},
                "date": {"type": "string"},
                "time": {"type": "string"},
                "location": {"type": "string"},
                "notes": {"type": "string"},
                "reminder_minutes": {"type": "integer"}
            },
            "required": ["user_id", "title", "date", "time"]
        }
    },
    {
        "name": "memory_save",
        "description": "保存用户偏好/口味/习惯到长期记忆。闭环必须调用",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "key": {"type": "string"},
                "value": {"type": "string"},
                "category": {"type": "string", "description": "taste/health/preference/experience"}
            },
            "required": ["user_id", "key", "value"]
        }
    }
]

# ---- 工具 → API 映射 ----

def execute_tool(name: str, args: dict) -> dict:
    """执行工具调用：转发到 mock_backend (Service 1)"""
    try:
        if name == "restaurant_recommend":
            r = requests.post(f"{BACKEND_URL}/api/dining/recommend", json={
                "user_id": args.get("user_id"),
                "cuisine": args.get("cuisine"),
                "budget_per_person": args.get("budget"),
                "people_count": args.get("people_count"),
                "scene": args.get("scene"),
                "must_have": args.get("must_have", "").split(",") if args.get("must_have") else None,
                "avoid_ingredients": args.get("avoid_ingredients", "").split(",") if args.get("avoid_ingredients") else None,
                "latitude": args.get("latitude", 39.925),
                "longitude": args.get("longitude", 116.59),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_queue":
            r = requests.get(f"{BACKEND_URL}/api/dining/queue", params={
                "restaurant_id": args.get("restaurant_id", 0)
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_emergency":
            r = requests.post(f"{BACKEND_URL}/api/dining/emergency-plan", json={
                "user_id": args.get("user_id"),
                "emergency_type": args.get("emergency_type", "weather"),
                "current_lat": args.get("current_lat", 39.925),
                "current_lng": args.get("current_lng", 116.59),
                "has_child": args.get("has_child", False),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "plan_route":
            r = requests.post(f"{BACKEND_URL}/api/mobility/route", json={
                "origin_lat": args.get("origin_lat", 39.925),
                "origin_lon": args.get("origin_lon", 116.59),
                "dest_lat": args.get("dest_lat", 39.91),
                "dest_lon": args.get("dest_lon", 116.46),
                "user_type": args.get("user_type", "white_collar"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "transport_search":
            r = requests.get(f"{BACKEND_URL}/api/mobility/transport/search", params={
                "origin_city": args.get("origin_city", "北京"),
                "dest_city": args.get("dest_city", "上海"),
                "transport_type": args.get("transport_type", "all"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "nearby_facilities":
            r = requests.get(f"{BACKEND_URL}/api/mobility/nearby", params={
                "lat": args.get("lat", 39.925),
                "lon": args.get("lon", 116.59),
                "facility_type": args.get("facility_type", "gas_station"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "get_weather":
            r = requests.get(f"{BACKEND_URL}/api/weather/current", timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "get_outfit":
            r = requests.get(f"{BACKEND_URL}/api/outfit/suggest", params={
                "user_id": args.get("user_id"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "get_wardrobe":
            r = requests.get(f"{BACKEND_URL}/api/wardrobe", params={
                "user_id": args.get("user_id"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "get_events":
            r = requests.get(f"{BACKEND_URL}/api/city/events", params={
                "type": args.get("type", "all"),
                "user_id": args.get("user_id", ""),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "get_shopping":
            r = requests.get(f"{BACKEND_URL}/api/city/shopping", params={
                "category": args.get("category", "all"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "get_schedule":
            r = requests.get(f"{BACKEND_URL}/api/schedule/today", params={
                "user_id": args.get("user_id"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "search_memory":
            r = requests.get(f"{BACKEND_URL}/api/memory/search", params={
                "user_id": args.get("user_id"),
                "keyword": args.get("keyword", ""),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()


        elif name == "restaurant_take_number":
            r = requests.post(f"{BACKEND_URL}/api/dining/take-number", params={
                "restaurant_id": args.get("restaurant_id", 0),
                "user_id": args.get("user_id", ""),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_reserve":
            r = requests.post(f"{BACKEND_URL}/api/dining/reserve", json={
                "restaurant_id": args.get("restaurant_id", 0),
                "user_id": args.get("user_id", ""),
                "date": args.get("date", ""),
                "time": args.get("time", ""),
                "people": args.get("people", 2),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_detail":
            r = requests.get(f"{BACKEND_URL}/api/dining/detail", params={
                "restaurant_id": args.get("restaurant_id", 0),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_monitor":
            r = requests.post(f"{BACKEND_URL}/api/dining/monitor", json={
                "restaurant_id": args.get("restaurant_id", 0),
                "user_id": args.get("user_id", ""),
                "alert_threshold": args.get("alert_threshold", 5),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_review":
            r = requests.post(f"{BACKEND_URL}/api/dining/review", json={
                "restaurant_id": args.get("restaurant_id", 0),
                "user_id": args.get("user_id", ""),
                "rating": args.get("rating", 4),
                "comment": args.get("comment", ""),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_takeout":
            r = requests.get(f"{BACKEND_URL}/api/dining/takeout", params={
                "restaurant_id": args.get("restaurant_id", 0),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "call_taxi":
            r = requests.post(f"{BACKEND_URL}/api/mobility/call-taxi", json={
                "origin_lat": args.get("origin_lat", 39.925),
                "origin_lon": args.get("origin_lon", 116.59),
                "dest_lat": args.get("dest_lat"),
                "dest_lon": args.get("dest_lon"),
                "car_type": args.get("car_type", "comfort"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "get_traffic":
            r = requests.get(f"{BACKEND_URL}/api/mobility/traffic", timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "weather_forecast":
            r = requests.get(f"{BACKEND_URL}/api/weather/forecast", timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "weather_alerts":
            r = requests.get(f"{BACKEND_URL}/api/weather/alerts", timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "kids_activities":
            r = requests.get(f"{BACKEND_URL}/api/city/kids", params={
                "age_range": args.get("age_range", "0-3"),
                "user_id": args.get("user_id", ""),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "schedule_create":
            r = requests.post(f"{BACKEND_URL}/api/schedule/create", json={
                "user_id": args.get("user_id", ""),
                "title": args.get("title", ""),
                "date": args.get("date", ""),
                "time": args.get("time", ""),
                "location": args.get("location", ""),
                "notes": args.get("notes", ""),
                "reminder_minutes": args.get("reminder_minutes", 15),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "memory_save":
            r = requests.post(f"{BACKEND_URL}/api/memory/save", json={
                "user_id": args.get("user_id", ""),
                "key": args.get("key", ""),
                "value": args.get("value", ""),
                "category": args.get("category", "preference"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        else:
            return {"error": f"未知工具: {name}"}

    except requests.exceptions.Timeout:
        return {"error": f"请求超时: {BACKEND_URL}/api/* ({REQUEST_TIMEOUT}s)"}
    except requests.exceptions.ConnectionError:
        return {"error": f"无法连接后端: {BACKEND_URL} — 请确认 Service 1 已启动"}
    except Exception as e:
        return {"error": f"工具执行异常: {str(e)[:200]}"}


# ---- MCP JSON-RPC 2.0 处理 ----

def handle_request(req: dict) -> dict:
    """处理单个 JSON-RPC 请求"""
    req_id = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    # 1. initialize — 握手
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "butler-mcp-bridge",
                    "version": "1.0.0"
                },
                "capabilities": {
                    "tools": {}
                }
            }
        }

    # 2. notifications/initialized — 无需响应
    if method == "notifications/initialized":
        return None  # 通知无响应

    # 3. tools/list — 返回工具列表
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS
            }
        }

    # 4. tools/call — 执行工具
    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        result = execute_tool(tool_name, tool_args)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                ]
            }
        }

    # 未知方法
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


# ---- 主循环 (stdio) ----

def main():
    print(f"[mcp_bridge] Starting MCP Bridge (stdio mode)", file=sys.stderr)
    print(f"[mcp_bridge] BACKEND_URL = {BACKEND_URL}", file=sys.stderr)
    print(f"[mcp_bridge] Registered {len(TOOLS)} tools", file=sys.stderr)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as e:
            print(f"[mcp_bridge] JSON parse error: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[mcp_bridge] Unexpected error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
