"""Add missing 13 tools to mcp_bridge.py"""

with open('agent/mcp_bridge.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Missing tools to add (after search_memory, before the closing ])
NEW_TOOLS = ''',
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
    }'''

# Insert before the closing ]
old_close = '\n]'
if old_close in content:
    # Only insert once
    content = content.replace(old_close, NEW_TOOLS + '\n]', 1)
    print('TOOLS: 13 new tools added')

# Now add the corresponding HTTP handlers
# Find the end of execute_tool (before the MCP server section)
NEW_HANDLERS = '''
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
'''

# Find the last elif before "else:" in execute_tool
old_else = '''
        else:
            return {"error": f"Unknown tool: {name}"}'''

if old_else in content:
    content = content.replace(old_else, NEW_HANDLERS + old_else, 1)
    print('HANDLERS: 13 new handlers added')

with open('agent/mcp_bridge.py', 'w', encoding='utf-8') as f:
    f.write(content)

# Verify
with open('agent/mcp_bridge.py', 'r', encoding='utf-8') as f:
    c = f.read()
import re
tools = re.findall(r'"name":\s*"(\w+)"', c)
print(f'Total tools after patch: {len(tools)}')
for t in tools:
    print(f'  {t}')
