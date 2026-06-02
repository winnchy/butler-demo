"""
Chat Proxy Server — Service 2 (OpenClaw Agent 入口)
- 提供 H5 聊天界面 (GET /)
- /chat → 转发到 OpenClaw Gateway (localhost:18789)
- 若 Gateway 不可用 → 降级直连 DeepSeek (读取全部 butler/ 文件 + 13 工具)
- 工具调用走 BACKEND_URL (Service 1)
"""

import json
import os
import shutil
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import heartbeat
import guardian
from scenario_scripts import SCENARIO_SCRIPTS

# ---- 对话历史（按用户存储，实现多轮上下文）----
CHAT_HISTORY = {}  # {user_id: [{role, content}, ...]}

# ---- 配置 ----
PORT = int(os.environ.get("PORT", 8080))
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
OPENCLAW_GATEWAY = os.environ.get("OPENCLAW_GATEWAY", "http://localhost:18789")
BUTLER_DIR = os.environ.get("BUTLER_DIR", "/app/butler")
# 本地开发时使用相对路径
if not os.path.exists(BUTLER_DIR):
    BUTLER_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "butler"))

app = FastAPI(
    title="Butler Agent Proxy",
    description="OpenClaw Agent 入口 — 转发到 Gateway 或降级直连 DeepSeek",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


# ---- 工具定义 (与 mcp_bridge 保持一致) ----

TOOLS = [
    # ===== dining-butler (9 tools) =====
    {"type":"function","function":{"name":"restaurant_recommend","description":"智能推荐餐厅。给定用户ID，综合偏好/天气/日程/场景推荐最合适的餐厅。用户说饿了/吃啥/推荐/附近美食时必调。","parameters":{"type":"object","properties":{"user_id":{"type":"string"},"cuisine":{"type":"string"},"budget":{"type":"integer"},"people_count":{"type":"integer"},"scene":{"type":"string","description":"business/family/date/casual"},"must_have":{"type":"string"},"latitude":{"type":"number"},"longitude":{"type":"number"}},"required":["user_id"]}}},
    {"type":"function","function":{"name":"restaurant_queue","description":"查餐厅当前排队状态","parameters":{"type":"object","properties":{"restaurant_id":{"type":"integer"}},"required":["restaurant_id"]}}},
    {"type":"function","function":{"name":"restaurant_take_number","description":"线上取号。用户选定餐厅后主动帮他取号，返回号牌和预计等待时间。","parameters":{"type":"object","properties":{"restaurant_id":{"type":"integer"},"user_id":{"type":"string"}},"required":["restaurant_id","user_id"]}}},
    {"type":"function","function":{"name":"restaurant_reserve","description":"预订餐厅包厢/座位。商务宴请或特殊场合时使用。","parameters":{"type":"object","properties":{"restaurant_id":{"type":"integer"},"user_id":{"type":"string"},"date":{"type":"string"},"time":{"type":"string"},"people":{"type":"integer"}},"required":["restaurant_id","user_id"]}}},
    {"type":"function","function":{"name":"restaurant_detail","description":"获取餐厅详细信息：地址、电话、特色菜、评分。","parameters":{"type":"object","properties":{"restaurant_id":{"type":"integer"}},"required":["restaurant_id"]}}},
    {"type":"function","function":{"name":"restaurant_emergency","description":"突发兜底：暴雨/满座/迟到/餐厅关门时找替代方案","parameters":{"type":"object","properties":{"user_id":{"type":"string"},"emergency_type":{"type":"string"},"current_lat":{"type":"number"},"current_lng":{"type":"number"},"has_child":{"type":"boolean"},"original_restaurant_id":{"type":"integer"}}}}},
    {"type":"function","function":{"name":"restaurant_monitor","description":"开启排队监控。用户取号后开启，排队到了自动提醒。","parameters":{"type":"object","properties":{"restaurant_id":{"type":"integer"},"user_id":{"type":"string"},"alert_threshold":{"type":"integer","description":"低于N桌时提醒"}},"required":["restaurant_id","user_id"]}}},
    {"type":"function","function":{"name":"restaurant_review","description":"提交用餐评价。吃完后收集用户反馈，闭环更新偏好。","parameters":{"type":"object","properties":{"restaurant_id":{"type":"integer"},"user_id":{"type":"string"},"rating":{"type":"integer","description":"1-5分"},"comment":{"type":"string"}},"required":["restaurant_id","user_id","rating"]}}},
    {"type":"function","function":{"name":"restaurant_takeout","description":"查外卖选项。下雨/生病/不想出门时推荐外卖。","parameters":{"type":"object","properties":{"restaurant_id":{"type":"integer"},"user_id":{"type":"string"}},"required":["user_id"]}}},
    # ===== mobility-butler (5 tools) =====
    {"type":"function","function":{"name":"plan_route","description":"多模式路径规划：驾车/地铁/骑行/步行/打车。用户问怎么去/多远/多久到的时候必调。","parameters":{"type":"object","properties":{"origin_lat":{"type":"number"},"origin_lon":{"type":"number"},"dest_lat":{"type":"number"},"dest_lon":{"type":"number"},"user_type":{"type":"string"},"mode":{"type":"string","description":"driving/transit/walking/cycling/taxi"}},"required":["origin_lat","origin_lon","dest_lat","dest_lon"]}}},
    {"type":"function","function":{"name":"call_taxi","description":"一键叫车。用户说要打车/叫车/滴滴时调此工具。","parameters":{"type":"object","properties":{"origin_lat":{"type":"number"},"origin_lon":{"type":"number"},"dest_lat":{"type":"number"},"dest_lon":{"type":"number"},"car_type":{"type":"string","description":"economy/comfort/business"}},"required":["origin_lat","origin_lon"]}}},
    {"type":"function","function":{"name":"transport_search","description":"查机票/火车票/高铁","parameters":{"type":"object","properties":{"origin_city":{"type":"string"},"dest_city":{"type":"string"},"transport_type":{"type":"string"}},"required":["origin_city","dest_city"]}}},
    {"type":"function","function":{"name":"nearby_facilities","description":"周边设施：加油站/充电桩/便利店/停车场/药店/宠物医院","parameters":{"type":"object","properties":{"lat":{"type":"number"},"lon":{"type":"number"},"facility_type":{"type":"string"}},"required":["lat","lon","facility_type"]}}},
    {"type":"function","function":{"name":"get_traffic","description":"当前北京路况：拥堵指数、热点堵车区域","parameters":{"type":"object","properties":{}}}},
    # ===== outfit-advisor (4 tools) =====
    {"type":"function","function":{"name":"get_weather","description":"北京当前天气+AQI","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"weather_forecast","description":"未来几天天气预报。用户问明天/周末天气时调。","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"get_outfit","description":"基于天气+用户身份+衣橱的穿搭建议。用户问穿什么/今天冷吗/带伞时调。","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
    {"type":"function","function":{"name":"get_wardrobe","description":"查询用户衣橱物品清单","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
    # ===== city-explorer (4 tools) =====
    {"type":"function","function":{"name":"get_events","description":"周末/近期活动：展览/演出/市集/亲子/演唱会。用户问去哪玩/有什么活动/周末安排时调。","parameters":{"type":"object","properties":{"type":{"type":"string","description":"exhibition/show/market/kids/concert/all"},"user_id":{"type":"string"}}}}},
    {"type":"function","function":{"name":"get_shopping","description":"商场促销信息","parameters":{"type":"object","properties":{"category":{"type":"string","description":"clothing/electronics/home/child/all"}}}}},
    {"type":"function","function":{"name":"kids_activities","description":"亲子活动推荐。带孩子的家庭用户专用。","parameters":{"type":"object","properties":{"age_range":{"type":"string","description":"0-3/4-6/7-12"},"user_id":{"type":"string"}}}}},
    {"type":"function","function":{"name":"weather_alerts","description":"当前天气预警。沙尘暴/暴雨/大风/高温时必调。","parameters":{"type":"object","properties":{}}}},
    # ===== life-organizer (4 tools) =====
    {"type":"function","function":{"name":"get_schedule","description":"今日日程安排","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
    {"type":"function","function":{"name":"schedule_create","description":"创建日程提醒。用户说提醒我/设闹钟/别忘了时调。","parameters":{"type":"object","properties":{"user_id":{"type":"string"},"title":{"type":"string"},"date":{"type":"string"},"time":{"type":"string"},"location":{"type":"string"},"notes":{"type":"string"},"reminder_minutes":{"type":"integer","description":"提前多少分钟提醒"}},"required":["user_id","title","date","time"]}}},
    {"type":"function","function":{"name":"search_memory","description":"搜索用户偏好记忆和长期档案","parameters":{"type":"object","properties":{"user_id":{"type":"string"},"keyword":{"type":"string"}},"required":["user_id"]}}},
    {"type":"function","function":{"name":"memory_save","description":"保存用户偏好/口味/习惯到长期记忆。必须调用以实现闭环。","parameters":{"type":"object","properties":{"user_id":{"type":"string"},"key":{"type":"string"},"value":{"type":"string"},"category":{"type":"string","description":"taste/health/preference/experience"}},"required":["user_id","key","value"]}}},
]


# ---- 文件读取 ----

def read_file(path: str, max_chars: int = 3000) -> str:
    """安全读取文件，返回内容或空字符串"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            if max_chars and len(content) > max_chars:
                content = content[:max_chars] + "\n...(truncated)"
            return content
    except:
        return ""


def build_system_prompt(user_id: str) -> str:
    """构建完整的 system prompt：SOUL.md + 5个SKILL.md 摘要 + USER.md + MEMORY.md + 实时状态"""
    parts = []

    # 1. SOUL.md — 管家灵魂设定（精简，只保留性格+语言风格）
    soul = read_file(os.path.join(BUTLER_DIR, "SOUL.md"), max_chars=800)
    if soul:
        parts.append(soul)
    else:
        parts.append("你是全天候私人管家。")

    # 2. 工具速查表 — 极简但精确，告诉 LLM 什么场景调什么工具
    parts.append("""
## 你的工作方式（超级管家模式）

你不是 chatbot。你是会自主推进流程的私人管家。每个用户请求背后，你应该主动拉多条线、推进到闭环。

### 核心行为准则

**1. 预判+并联**：一个请求同时拉多件事。
- 用户说"饿/吃"→ 同时调 restaurant_recommend + get_weather + get_schedule
- 用户说"出门/怎么去"→ 同时调 plan_route + get_traffic + get_weather
- 用户问"周末去哪"→ 同时调 get_events + weather_forecast + get_schedule

**2. 自主推进**：不等用户开口就推进下一步。
- 推荐了餐厅 → 主动问"要帮你取号吗？"然后调 restaurant_take_number
- 取号后 → 主动调 plan_route 给路线
- 定了出行 → 主动调 schedule_create 设出发提醒

**3. 闭环记忆**：每次交互结束都要存档。
- 吃完饭后 → 调 restaurant_review + memory_save 更新口味偏好
- 用户说"好吃/不好吃/太辣"→ 立即 memory_save

**4. 🚫 输出红线（违反即失败）**：
- 绝对禁止在回复中出现任何工具名、代码块、JSON、XML、函数调用语法
- 绝对禁止使用 Markdown 格式（**加粗**、`代码`、#标题等），纯文本回复即可
- 绝对禁止说"让我调XX工具"、"正在查询XX接口"之类的话
- 工具调用的结果你要理解后用自然语言重新表达

**5. 结构化输出**：回复必须清晰分层，用 emoji 标题分行展示，不要一大段文字。
- 推荐餐厅格式：
  🥇 餐厅名
  ⭐评分 | 💰人均 | 🥡菜系
  📍地址 | 🚶距离/出行方式
  📝 最近评价摘要
  🎯 推荐理由（1-2句）
- 推荐活动格式同上，给出时间/地点/票价/适合人群
- 路线推荐格式：列出每个选项（🚗驾车 🚇地铁 🚲骑行 🚕打车），标注时间和费用

**6. 记住上下文**：用户说"就第一家吧"→ 你知道是刚才推荐的第一个餐厅。

**7. 场景聚焦**：只在用户明确提到家人时才能提及家人。商务宴请时不要提孩子、宠物、公婆等家庭话题。讨论周末带娃时才能提果果/乐乐。保持管家专业性。
""")

    # 最后一道防线：输出格式约束
    parts.append("\n\n⚠️ 再次强调：你的回复必须是纯自然语言中文，不能包含任何代码、JSON、工具名、函数调用。如果你不确定有没有暴露，就想想你是在跟真人发微信。\n")

    # 3. 当前用户画像
    parts.append("\n\n## 当前服务用户\n")
    user_md = read_file(os.path.join(BUTLER_DIR, "USER.md"), max_chars=600)
    if user_md:
        parts.append(user_md)
    memory_md = read_file(os.path.join(BUTLER_DIR, "MEMORY.md"), max_chars=400)
    if memory_md:
        parts.append(f"\n### 用户记忆\n{memory_md}")

    # 4. 实时环境状态 (从 Service 1 获取)
    parts.append("\n\n## 实时环境\n")
    try:
        w = requests.get(f"{BACKEND_URL}/api/weather/current", timeout=3).json()
        parts.append(f"北京天气: {w.get('condition','?')} {w.get('temperature',w.get('current_temp','?'))}°C "
                     f"AQI {w.get('aqi','?')} ({w.get('aqi_level','?')})")
        if w.get('alerts'):
            for a in w['alerts']:
                parts.append(f"⚠️ 预警: {a.get('type','')} {a.get('level','')}")
    except:
        parts.append("天气数据暂不可用")

    try:
        t = requests.get(f"{BACKEND_URL}/api/mobility/traffic", timeout=3).json()
        parts.append(f"路况: 拥堵指数 {t.get('citywide_congestion','?')} | "
                     f"热点区域: {', '.join(t.get('hotspots',[])[:3])}")
    except:
        pass

    try:
        s = requests.get(f"{BACKEND_URL}/api/schedule/today?user_id={user_id}", timeout=3).json()
        schedules = s.get("schedules", [])
        if schedules:
            parts.append(f"今日日程: {len(schedules)}项 — {', '.join(s['title'][:15] for s in schedules[:5])}")
    except:
        pass

    return "\n".join(parts)


# ---- 工具执行 (转发到 Service 1) ----

def execute_tool(name: str, args: dict) -> str:
    """执行工具调用 → HTTP 请求到 Service 1"""
    try:
        if name == "restaurant_recommend":
            r = requests.post(f"{BACKEND_URL}/api/dining/recommend", json={
                "user_id": args.get("user_id"),
                "cuisine": args.get("cuisine"),
                "budget_per_person": args.get("budget"),
                "people_count": args.get("people_count"),
                "scene": args.get("scene"),
                "must_have": args.get("must_have","").split(",") if args.get("must_have") else None,
                "latitude": args.get("latitude", 39.925),
                "longitude": args.get("longitude", 116.59),
            }, timeout=10)
            recs = r.json().get("recommendations", [])[:3]
            if not recs:
                return "未找到匹配餐厅"
            lines = []
            for rec in recs:
                lines.append(f"🍽️ {rec['name']} | {rec['cuisine']} | ⭐{rec['rating']} | ¥{rec['avg_price']}/人 | {rec.get('status','')} | {', '.join(rec.get('match_reasons',[])[:2])}")
            return "\n".join(lines)

        elif name == "restaurant_queue":
            r = requests.get(f"{BACKEND_URL}/api/dining/queue?restaurant_id={args.get('restaurant_id',0)}", timeout=10)
            q = r.json()
            return f"当前排队{q.get('current_queue',0)}桌，预计等待{q.get('estimated_wait_min',0)}分钟"

        elif name == "restaurant_emergency":
            r = requests.post(f"{BACKEND_URL}/api/dining/emergency-plan", json={
                "user_id": args.get("user_id"), "emergency_type": args.get("emergency_type","weather"),
                "current_lat": args.get("current_lat",39.925), "current_lng": args.get("current_lng",116.59),
                "has_child": args.get("has_child",False),
            }, timeout=10)
            plan = r.json().get("priority_plan", {})
            return f"突发兜底：{plan.get('message','已找到替代方案')}"

        elif name == "plan_route":
            r = requests.post(f"{BACKEND_URL}/api/mobility/route", json={
                "origin_lat": args.get("origin_lat",39.925), "origin_lon": args.get("origin_lon",116.59),
                "dest_lat": args.get("dest_lat",39.91), "dest_lon": args.get("dest_lon",116.46),
                "user_type": args.get("user_type","white_collar"),
            }, timeout=10)
            opts = r.json().get("options", [])[:3]
            if not opts:
                return "未找到路线"
            emoji = {"driving":"🚗","transit":"🚇","cycling":"🚲","walking":"🚶","taxi":"🚕"}
            return "\n".join(f"{emoji.get(o['mode'],'📍')} {o['mode']} {o['time_min']}分钟 | ¥{o.get('cost_yuan',0)}" for o in opts)

        elif name == "transport_search":
            r = requests.get(f"{BACKEND_URL}/api/mobility/transport/search", params={
                "origin_city": args.get("origin_city","北京"), "dest_city": args.get("dest_city","上海"),
                "transport_type": args.get("transport_type","all"),
            }, timeout=10)
            results = r.json().get("results", [])[:3]
            if not results:
                return "未找到票务信息"
            return "\n".join(f"✈️🚄 {t['type']} {t.get('departure','')}-{t.get('arrival','')} | ¥{t.get('price','?')} | {t.get('seats_left','?')}座" for t in results)

        elif name == "nearby_facilities":
            r = requests.get(f"{BACKEND_URL}/api/mobility/nearby", params={
                "lat": args.get("lat",39.925), "lon": args.get("lon",116.59),
                "facility_type": args.get("facility_type","gas_station"),
            }, timeout=10)
            facs = r.json().get("facilities", [])[:3]
            if not facs:
                return "附近未找到该设施"
            return "\n".join(f"📍 {f['name']} | {f['distance_km']}km" for f in facs)

        elif name == "get_weather":
            r = requests.get(f"{BACKEND_URL}/api/weather/current", timeout=10)
            w = r.json()
            text = f"北京 {w.get('condition','?')} {w.get('temperature',w.get('current_temp','?'))}°C | 体感{w.get('feels_like','?')}°C | AQI{w.get('aqi','?')}({w.get('aqi_level','?')})"
            if w.get('alerts'):
                text += "\n" + "\n".join(f"⚠️ {a.get('type','')} {a.get('level','')}" for a in w['alerts'])
            return text

        elif name == "get_outfit":
            r = requests.get(f"{BACKEND_URL}/api/outfit/suggest?user_id={args.get('user_id')}", timeout=10)
            o = r.json()
            return f"👔 {o.get('base_suggestion','?')}：{', '.join(o.get('recommended_items',[])[:5])}"

        elif name == "get_wardrobe":
            r = requests.get(f"{BACKEND_URL}/api/wardrobe?user_id={args.get('user_id')}", timeout=10)
            wb = r.json()
            return f"衣橱：上装{wb.get('tops',[])[:3]} 下装{wb.get('bottoms',[])[:2]} 缺：{', '.join(wb.get('missing',[]))}"

        elif name == "get_events":
            r = requests.get(f"{BACKEND_URL}/api/city/events?type={args.get('type','all')}&user_id={args.get('user_id','')}", timeout=10)
            events = r.json().get("events", [])[:3]
            if not events:
                return "近期暂无活动"
            return "\n".join(f"🎯 {e['name']} | {e['location']} | {e.get('date','')} | ¥{e.get('price',{}).get('regular','?')}" for e in events)

        elif name == "get_shopping":
            r = requests.get(f"{BACKEND_URL}/api/city/shopping?category={args.get('category','all')}", timeout=10)
            promos = r.json().get("promotions", [])[:3]
            if not promos:
                return "暂无促销信息"
            return "\n".join(f"🛍️ {p['mall']}：{p['promotion']}（至{p.get('valid_until','?')}）" for p in promos)

        elif name == "get_schedule":
            r = requests.get(f"{BACKEND_URL}/api/schedule/today?user_id={args.get('user_id')}", timeout=10)
            scheds = r.json().get("schedules", [])
            if not scheds:
                return "今天没有日程安排"
            return "\n".join(f"📌 {s['time']} {s['title']} @{s.get('location','?')}" for s in scheds)

        elif name == "search_memory":
            r = requests.get(f"{BACKEND_URL}/api/memory/search?user_id={args.get('user_id')}&keyword={args.get('keyword','')}", timeout=10)
            mems = r.json().get("memories", [])[:5]
            if not mems:
                return "未找到相关记忆"
            return "\n".join(f"🧠 {m['key']}: {m['value']}" for m in mems)

        # ---- 新增 dining tools ----
        elif name == "restaurant_take_number":
            r = requests.post(f"{BACKEND_URL}/api/dining/take-number?restaurant_id={args.get('restaurant_id',0)}&user_id={args.get('user_id','')}", timeout=10)
            d = r.json()
            return f"已取号！🎫 号牌{d.get('ticket_number','?')}，当前等{d.get('current_queue',0)}桌，预计{d.get('estimated_wait_min',0)}分钟"
        elif name == "restaurant_reserve":
            r = requests.post(f"{BACKEND_URL}/api/dining/reserve", params={"restaurant_id": args.get("restaurant_id",0), "user_id": args.get("user_id",""), "date": args.get("date",""), "time": args.get("time",""), "people": args.get("people",2)}, timeout=10)
            d = r.json()
            return f"已预订！📋 {d.get('restaurant_name','')} {d.get('date','')} {d.get('time','')} {d.get('people',2)}人"
        elif name == "restaurant_detail":
            r = requests.get(f"{BACKEND_URL}/api/dining/detail?restaurant_id={args.get('restaurant_id',0)}", timeout=10)
            d = r.json(); detail = d.get("restaurant", d)
            return f"🏠 {detail.get('name','?')} | {detail.get('cuisine','?')} | ⭐{detail.get('rating','?')} | ¥{detail.get('avg_price','?')}/人\n📍 {detail.get('address','?')}\n📞 {detail.get('phone','?')}\n🍳 特色: {', '.join(detail.get('specialties',[])[:5])}"
        elif name == "restaurant_monitor":
            r = requests.post(f"{BACKEND_URL}/api/dining/monitor?restaurant_id={args.get('restaurant_id',0)}&user_id={args.get('user_id','')}&alert_threshold={args.get('alert_threshold',5)}", timeout=10)
            d = r.json()
            return f"👀 已开启排队监控，排到{d.get('alert_threshold',5)}桌以内通知你！当前{d.get('current_queue','?')}桌"
        elif name == "restaurant_review":
            r = requests.post(f"{BACKEND_URL}/api/dining/review", params={"restaurant_id": args.get("restaurant_id",0), "user_id": args.get("user_id",""), "rating": args.get("rating",4), "comment": args.get("comment","")}, timeout=10)
            d = r.json()
            return f"评价已记录：{'⭐'*args.get('rating',4)} {d.get('message','')}"
        elif name == "restaurant_takeout":
            r = requests.get(f"{BACKEND_URL}/api/dining/takeout?restaurant_id={args.get('restaurant_id',0)}&user_id={args.get('user_id','')}", timeout=10)
            d = r.json(); items = d.get("takeout_items", d.get("recommendations", []))[:5]
            if not items: return "该餐厅暂不提供外卖"
            return "\n".join(f"🥡 {t.get('name',t)} | ¥{t.get('price','?')}" for t in items)
        elif name == "call_taxi":
            r = requests.post(f"{BACKEND_URL}/api/mobility/call-taxi", params={"origin_lat": args.get("origin_lat",39.925), "origin_lon": args.get("origin_lon",116.59), "dest_lat": args.get("dest_lat",39.91), "dest_lon": args.get("dest_lon",116.46), "car_type": args.get("car_type","economy")}, timeout=10)
            d = r.json()
            return f"🚕 已叫车！{d.get('car_type','快车')} {d.get('driver_name','')} {d.get('plate','')} | 预计{d.get('wait_min',5)}分钟后到达 | 费用约¥{d.get('estimated_cost',15)}"
        elif name == "get_traffic":
            r = requests.get(f"{BACKEND_URL}/api/mobility/traffic", timeout=10)
            d = r.json()
            return f"拥堵指数: {d.get('citywide_congestion',0.3)} | 热点: {', '.join(d.get('hotspots',[]))}"
        elif name == "weather_forecast":
            r = requests.get(f"{BACKEND_URL}/api/weather/forecast", timeout=10)
            d = r.json(); days = d.get("forecast", d.get("daily", []))[:3]
            if not days: return "暂无天气预报"
            return "\n".join(f"📅 {day.get('date','?')}: {day.get('condition','?')} {day.get('temp_high','?')}/{day.get('temp_low','?')}°C" for day in days)
        elif name == "kids_activities":
            r = requests.get(f"{BACKEND_URL}/api/city/kids?age_range={args.get('age_range','')}&user_id={args.get('user_id','')}", timeout=10)
            d = r.json(); acts = d.get("activities", d.get("events", []))[:3]
            if not acts: return "暂无亲子活动"
            return "\n".join(f"👶 {a['name']} | {a.get('location','?')} | {a.get('age_range','?')} | ¥{a.get('price',0)}" for a in acts)
        elif name == "weather_alerts":
            r = requests.get(f"{BACKEND_URL}/api/weather/alerts", timeout=10)
            d = r.json(); alerts = d.get("alerts", [])
            if not alerts: return "当前无天气预警"
            return "\n".join(f"⚠️ {a.get('type','')} {a.get('level','')}: {a.get('description','')}" for a in alerts)
        elif name == "schedule_create":
            r = requests.post(f"{BACKEND_URL}/api/schedule/create", json={"user_id": args.get("user_id",""), "title": args.get("title",""), "date": args.get("date",""), "time": args.get("time",""), "location": args.get("location",""), "notes": args.get("notes",""), "reminder_minutes": args.get("reminder_minutes",15)}, timeout=10)
            d = r.json()
            return f"⏰ 已设提醒！{args.get('time','')} {args.get('title','')}（提前{args.get('reminder_minutes',15)}分钟提醒）"
        elif name == "memory_save":
            r = requests.post(f"{BACKEND_URL}/api/memory/save", json={"user_id": args.get("user_id",""), "key": args.get("key",""), "value": args.get("value",""), "category": args.get("category","preference")}, timeout=10)
            d = r.json()
            return f"已记住！🧠 {args.get('key','')}: {args.get('value','')}"

        else:
            return f"未知工具: {name}"

    except requests.exceptions.Timeout:
        return f"[{name}] 请求超时 — 后端 Service 1 可能负载过高"
    except requests.exceptions.ConnectionError:
        return f"[{name}] 无法连接后端 {BACKEND_URL} — 请确认 Service 1 已启动"
    except Exception as e:
        return f"[{name}] 异常: {str(e)[:100]}"


# ---- 降级模式：直连 DeepSeek ----

def chat_direct_deepseek(message: str, user_id: str) -> str:
    """直连 DeepSeek API，完整 function-calling 循环 + 对话历史"""
    if not OPENAI_API_KEY:
        return ("⚠️ AI 服务未配置。请设置 OPENAI_API_KEY 环境变量。\n\n"
                "你可以尝试：\n"
                "🍽️ 「附近火锅」| 👔 「今天穿什么」| 🚇 「去国贸怎么走」| 🎯 「周末活动」")

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

        system_prompt = build_system_prompt(user_id)

        # 获取对话历史（保留最近 10 轮）
        history = CHAT_HISTORY.get(user_id, [])[-6:]  # 最近3轮
        messages = [{"role": "system", "content": system_prompt}] + history + [
            {"role": "user", "content": message}
        ]

        # ---- 第一轮：LLM 决定调哪些工具 ----
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=800,
            timeout=20,
        )

        choice = response.choices[0]
        msg = choice.message

        # ---- 收集工具调用（API方式 + 文本解析双保险）----
        tool_calls_to_execute = []

        # 方式1：API 原生 tool_calls
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except:
                    args = {}
                tool_calls_to_execute.append((tc.id, tc.function.name, args))

        # 方式2：文本中嵌入的工具调用（兼容 DeepSeek 偶发的 XML 输出）
        if msg.content and not tool_calls_to_execute:
            text_tools = _parse_text_tools(msg.content)
            for tt in text_tools:
                tool_calls_to_execute.append((f"text_{tt[0]}", tt[0], tt[1]))

        # ---- 执行工具并让 LLM 生成自然回答 ----
        if tool_calls_to_execute:
            # 构建 assistant 消息
            assistant_msg = {"role": "assistant", "content": _clean_reply(msg.content or "")}
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)

            # 执行工具
            for tc_id, tc_name, tc_args in tool_calls_to_execute:
                tool_result = execute_tool(tc_name, tc_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_result
                })

            # 第二轮：生成自然回答
            response2 = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.7,
                max_tokens=800,
                timeout=20,
            )
            reply = _clean_reply(response2.choices[0].message.content or "")

        else:
            reply = _clean_reply(msg.content or "收到，让我想想...")

        # 保存历史 + 返回
        hist = CHAT_HISTORY.setdefault(user_id, [])
        hist.append({"role": "user", "content": message})
        hist.append({"role": "assistant", "content": reply})
        if len(hist) > 6: hist[:] = hist[-6:]
        return reply

    except Exception as e:
        return f"AI 服务异常: {str(e)[:200]}"


def _parse_text_tools(text: str) -> list:
    """从 LLM 文本输出中解析工具调用（兼容 DeepSeek XML 格式）"""
    import re
    tools = []
    # 匹配 <invoke name="tool_name">...</invoke> 格式
    pattern = r'<invoke\s+name="(\w+)"[^>]*>(.*?)</invoke>'
    for m in re.finditer(pattern, text, re.DOTALL):
        name = m.group(1)
        body = m.group(2)
        args = {}
        # 解析 <parameter name="key" string="true">value</parameter>
        for pm in re.finditer(r'<parameter\s+name="(\w+)"[^>]*>(.*?)</parameter>', body, re.DOTALL):
            args[pm.group(1)] = pm.group(2).strip()
        if name: tools.append((name, args))
    # 匹配 {"name": "xxx", "arguments": {...}} JSON 格式
    json_pattern = r'\{"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{[^}]+\})\}'
    for m in re.finditer(json_pattern, text):
        try:
            name = m.group(1)
            args = json.loads(m.group(2))
            tools.append((name, args))
        except: pass
    return tools


def _clean_reply(text: str) -> str:
    """过滤 LLM 响应中的原始工具调用语法和无关内容"""
    import re
    # 去掉任何 XML/HTML 风格标签（如 <invoke>, <parameter>, <function> 等）
    text = re.sub(r'<[^>]+>', '', text)
    # 去掉残留的工具调用 JSON/代码块
    text = re.sub(r'```[\s\S]*?```', '', text)
    # 合并多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ---- 用户切换 ----

USER_SWITCH_MAP = {
    "white_collar": {
        "profile": "users/whitecollar.md",
        "memory": "memories/whitecollar-memory.md",
        "wardrobe": "users/whitecollar-wardrobe.md",
    },
    "parent": {
        "profile": "users/parent.md",
        "memory": "memories/parent-memory.md",
        "wardrobe": "users/parent-wardrobe.md",
    },
    "student": {
        "profile": "users/student.md",
        "memory": "memories/student-memory.md",
        "wardrobe": "users/student-wardrobe.md",
    },
}

def switch_user_files(user_id: str) -> dict:
    """将 profiles/ 下的用户文件复制到 butler/ 根目录"""
    if user_id not in USER_SWITCH_MAP:
        return {"ok": False, "error": f"未知用户: {user_id}"}

    info = USER_SWITCH_MAP[user_id]
    profiles_dir = os.path.join(BUTLER_DIR, "profiles")
    results = []

    targets = {
        "USER.md": info["profile"],
        "MEMORY.md": info["memory"],
        "wardrobe.md": info["wardrobe"],
    }

    for target_name, src_rel in targets.items():
        src = os.path.join(profiles_dir, src_rel)
        dst = os.path.join(BUTLER_DIR, target_name)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            results.append({"file": target_name, "status": "ok"})
        else:
            results.append({"file": target_name, "status": "error", "reason": "源文件不存在"})

    return {"ok": True, "user_id": user_id, "files": results}


# ---- H5 聊天界面 ----

CHAT_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Butler — 全天候私人管家</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#111;color:#e0e0e0;height:100vh;display:flex}
.sidebar{width:260px;background:#1a1a1a;padding:16px;display:flex;flex-direction:column;gap:12px;border-right:1px solid #2a2a2a;overflow-y:auto}
.sidebar h2{font-size:16px;color:#fff;margin-bottom:4px}
.user-btn{display:block;width:100%;padding:10px 14px;border:1px solid #333;border-radius:8px;background:#222;color:#ccc;cursor:pointer;text-align:left;font-size:13px;margin-bottom:6px;transition:all .15s}
.user-btn:hover{border-color:#555;background:#2a2a2a}
.user-btn.active{border-color:#10b981;background:#064e3b;color:#6ee7b7}
.scene-btn{display:block;width:100%;padding:7px 12px;border:1px solid #333;border-radius:6px;background:#222;color:#999;cursor:pointer;font-size:12px;margin-bottom:4px;transition:all .15s}
.scene-btn:hover{border-color:#7c3aed;color:#c4b5fd}
.scene-btn.complex{border-left:3px solid #dc2626}
.divider{border:none;border-top:1px solid #2a2a2a;margin:8px 0}
.main{flex:1;display:flex;flex-direction:column;max-width:calc(100% - 260px)}
.header{padding:14px 20px;background:#1a1a1a;border-bottom:1px solid #2a2a2a;display:flex;align-items:center;gap:12px}
.header .avatar{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#2563eb,#7c3aed);display:flex;align-items:center;justify-content:center;font-size:18px}
.header .title{font-size:15px;font-weight:600;color:#fff}.header .subtitle{font-size:12px;color:#888}
.messages{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:16px}
.msg{display:flex;gap:10px;max-width:85%}
.msg.user{align-self:flex-end;flex-direction:row-reverse}
.msg.bot{align-self:flex-start}
.msg .bubble{padding:12px 16px;border-radius:16px;font-size:14px;line-height:1.5;white-space:pre-wrap}
.msg.user .bubble{background:#2563eb;color:#fff;border-bottom-right-radius:4px}
.msg.bot .bubble{background:#262626;color:#e0e0e0;border-bottom-left-radius:4px}
.msg .avatar-mini{width:30px;height:30px;border-radius:50%;background:#333;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
.input-area{padding:14px 20px;background:#1a1a1a;border-top:1px solid #2a2a2a;display:flex;gap:10px}
.input-area input{flex:1;padding:12px 16px;border:1px solid #333;border-radius:24px;background:#222;color:#fff;font-size:14px;outline:none}
.input-area input:focus{border-color:#2563eb}
.input-area button{padding:10px 20px;border:none;border-radius:24px;background:#2563eb;color:#fff;font-weight:600;cursor:pointer;font-size:14px}
.input-area button.mic{background:#333;font-size:18px;padding:10px 14px}
.input-area button:hover{opacity:.9}
.toast{position:fixed;top:16px;right:16px;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;z-index:999;opacity:0;transition:opacity .3s}
.toast.show{opacity:1}
.toast.ok{background:#064e3b;color:#6ee7b7}
.toast.err{background:#7f1d1d;color:#fca5a5}
.typing{display:flex;gap:4px;padding:4px 0}
.typing span{width:6px;height:6px;border-radius:50%;background:#666;animation:typing 1.4s infinite}
.typing span:nth-child(2){animation-delay:.2s}
.typing span:nth-child(3){animation-delay:.4s}
@keyframes typing{0%,60%,100%{opacity:.3}30%{opacity:1}}
@media(min-width:769px){
  body{justify-content:center;align-items:center;background:#1a1a1a}
  .app-container{max-width:480px;max-height:90vh;border-radius:20px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.5);display:flex;width:100%;height:90vh}
  .sidebar{display:none}
  .main{max-width:100%}
}
@media(max-width:768px){
  .sidebar{display:none}.main{max-width:100%}
}
.sidebar.open{display:flex;position:fixed;top:0;left:0;height:100%;z-index:100;overflow-y:auto}
.hamburger{background:none;border:none;color:#888;font-size:18px;cursor:pointer;padding:4px 8px}
.user-switch select{padding:5px 8px;border:1px solid #333;border-radius:6px;background:#1a1a1a;color:#ccc;font-size:12px;cursor:pointer;outline:none}
</style>
</head>
<body>
<div class="app-container">

<div class="sidebar" id="sidebar-el">
  <h2>Butler</h2>
  <div style="font-size:11px;color:#666;margin-bottom:8px">全天候私人管家 · 管理面板</div>
  <div class="divider"></div>
  <div style="font-size:11px;color:#666;margin-bottom:4px">👤 当前用户</div>
  <button class="user-btn active" onclick="showProfile('white_collar')" id="btn-wc">🏢 小琴 · 白领</button>
  <button class="user-btn" onclick="showProfile('parent')" id="btn-parent">👶 小冉 · 宝妈</button>
  <button class="user-btn" onclick="showProfile('student')" id="btn-student">🎓 小晴 · 大学生</button>
  <div id="user-profile-card" style="display:none;background:#1e1e1e;border-radius:8px;padding:12px;margin-top:8px;font-size:12px;color:#aaa;line-height:1.6"></div>
  <div class="divider"></div>
  <div style="font-size:11px;color:#666;margin-bottom:4px">🎬 场景触发</div>
  <button class="scene-btn" onclick="triggerScene('1')">1. 接待上级午餐</button>
  <button class="scene-btn" onclick="triggerScene('2')">2. 逛街突遇暴雨</button>
  <button class="scene-btn" onclick="triggerScene('7')">7. 乐乐凌晨发烧</button>
  <button class="scene-btn complex" onclick="triggerScene('9')">9. 航班延误</button>
  <button class="scene-btn" onclick="triggerScene('14')">14. 沙尘暴突袭</button>
  <button class="scene-btn complex" onclick="triggerScene('15')">15. 早高峰地铁故障</button>
  <button class="scene-btn complex" onclick="triggerScene('18')">18. 宠物急诊</button>
  <button class="scene-btn" onclick="triggerScene('19')">19. 餐厅临时歇业</button>
  <div class="divider"></div>
  <button class="scene-btn" onclick="speedUp()" style="color:#f59e0b">⚡ 加速测试（数据动态变化）</button>
  <button class="scene-btn" onclick="resetAll()" style="color:#fca5a5">重置所有场景</button>
  <div style="margin-top:auto;font-size:10px;color:#444">Powered by OpenClaw<br>Agent v2.0</div>
</div>

<div class="main">
  <div class="header">
    <button class="hamburger" onclick="document.getElementById('sidebar-el').classList.toggle('open')" title="管理面板">☰</button>
    <div class="avatar"></div>
    <div style="flex:1"><div class="title">全天候私人管家</div></div>
    <div class="user-switch">
      <select id="userSelect" onchange="switchUser(this.value)">
        <option value="white_collar">小琴</option>
        <option value="parent">小冉</option>
        <option value="student">小晴</option>
      </select>
    </div>
    <button id="notif-bell" onclick="toggleNotifications()" style="background:none;border:none;font-size:18px;cursor:pointer;position:relative">🔔<span id="notif-badge" style="display:none;position:absolute;top:-5px;right:-5px;background:#dc2626;color:#fff;border-radius:50%;width:18px;height:18px;font-size:10px;line-height:18px;text-align:center">0</span></button>
  </div>
  <div id="notif-panel" style="display:none;position:fixed;top:56px;right:10px;background:#1e1e1e;border:1px solid #333;border-radius:12px;padding:12px;max-height:300px;overflow-y:auto;z-index:200;width:300px;box-shadow:0 8px 24px rgba(0,0,0,0.5)">
    <div style="font-size:13px;font-weight:600;color:#fff;margin-bottom:8px">📬 管家提醒</div>
    <div id="notif-list" style="font-size:12px;color:#aaa">暂无新通知</div>
  </div>
  <div class="messages" id="messages">
    <div class="msg bot">
      <div class="avatar-mini"></div>
      <div class="bubble">早上好！我是你的全天候私人管家～<br>今天北京晴28°C。中午想吃什么？</div>
    </div>
  </div>
  <div class="input-area">
    <button class="mic" onclick="toggleVoice()" id="mic-btn">🎤</button>
    <input type="text" id="userInput" placeholder="输入消息，如：中午吃啥/今天穿什么/去国贸怎么走…" onkeydown="if(event.key==='Enter')send()">
    <button onclick="send()">发送</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let currentUser = 'white_collar';
let isListening = false;
let recognition = null;

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.lang = 'zh-CN';
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.onresult = e => {
    document.getElementById('userInput').value = e.results[0][0].transcript;
    send();
  };
  recognition.onend = () => { isListening = false; document.getElementById('mic-btn').textContent = '🎤'; };
}

function toggleVoice() {
  if (!recognition) { toast('浏览器不支持语音，请用 Chrome', 'err'); return; }
  if (isListening) { recognition.stop(); isListening = false; document.getElementById('mic-btn').textContent = '🎤'; }
  else { recognition.start(); isListening = true; document.getElementById('mic-btn').textContent = '🔴'; }
}

async function send() {
  if (isAutoPlaying) { toast('沙盒演示中，请等待结束', 'err'); return; }
  const input = document.getElementById('userInput');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  addMessage('user', msg);

  let thinkSec = 0;
  const thinkId = 'think-' + Date.now();
  addMessage('bot', '<div class="typing"><span></span><span></span><span></span></div> 思考中 (<span id="' + thinkId + '">0</span>秒)...', true);
  const timer = setInterval(() => {
    thinkSec++;
    const el = document.getElementById(thinkId);
    if (el) el.textContent = thinkSec;
  }, 1000);

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 75000);
    const r = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg, user_id: currentUser}),
      signal: controller.signal
    });
    clearTimeout(timeout);
    const d = await r.json();
    clearInterval(timer);
    document.getElementById('temp-msg')?.remove();
    addMessage('bot', d.reply || d.response || '抱歉，出了点问题...');
  } catch(e) {
    clearInterval(timer);
    document.getElementById('temp-msg')?.remove();
    addMessage('bot', '服务暂时不可用，请确认后端已启动');
  }
}

function addMessage(role, text, isTemp) {
  const div = document.createElement('div');
  div.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
  if (isTemp) div.id = 'temp-msg';
  div.innerHTML = '<div class="avatar-mini">' + (role === 'user' ? '' : '') + '</div><div class="bubble">' + text + '</div>';
  document.getElementById('messages').appendChild(div);
  document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
}

async function switchUser(uid) {
  currentUser = uid;
  try { await fetch('/switch-user/' + uid, {method:'POST'}); } catch(e) {}
  const greetings = {
    white_collar: '你好小琴！今天北京晴28°C。中午想吃什么？',
    parent: '早啊小冉！乐乐今天状态不错～需要帮你安排什么？',
    student: '嗨小晴！今天中关村阴转多云22°C。需要帮什么忙？'
  };
  addMessage('bot', greetings[uid] || '已切换用户～');
  // header dropdown is for functional switching, sidebar for profile cards
}

let isAutoPlaying = false;

async function triggerScene(id) {
  // 获取场景脚本
  let script;
  try {
    const r = await fetch('/api/scenario/' + id);
    const d = await r.json();
    if (!d.ok) { toast('场景不存在', 'err'); return; }
    script = d.scenario;
  } catch(e) { toast('获取场景失败', 'err'); return; }

  // 触发 WorldState 变化
  try { await fetch(BACKEND_URL + '/admin/trigger/scenario/' + id, {method:'POST'}); } catch(e) {}
  // 重置旧场景
  try { await fetch(BACKEND_URL + '/admin/reset', {method:'POST'}); } catch(e) {}

  // 清空聊天+历史
  document.getElementById('messages').innerHTML = '';
  try { await fetch('/api/clear-history?user_id=' + script.user, {method:'POST'}); } catch(e) {}

  // 切换用户
  currentUser = script.user;
  document.getElementById('userSelect').value = script.user;
  try { await fetch('/switch-user/' + script.user, {method:'POST'}); } catch(e) {}
  document.querySelectorAll('.user-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + (script.user==='white_collar'?'wc':script.user==='parent'?'parent':'student'))?.classList.add('active');

  // 锁定输入
  isAutoPlaying = true;
  document.getElementById('userInput').disabled = true;
  document.getElementById('userInput').placeholder = '🔄 沙盒演示中...';

  // 开场标识
  addMessage('bot', '🎬 <b>沙盒演示：' + script.title + '</b><br><span style="font-size:11px;color:#888">场景已激活，WorldState数据已更新，开始自动对话...</span>');

  // 自动播放
  for (let i = 0; i < script.steps.length; i++) {
    const step = script.steps[i];
    await new Promise(r => setTimeout(r, step.delay || 2000));
    addMessage('user', step.msg);
    // 发送真实请求，失败重试一次
    let reply = '';
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const controller = new AbortController();
        const to = setTimeout(() => controller.abort(), 60000);
        const resp = await fetch('/chat', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({message: step.msg, user_id: script.user}),
          signal: controller.signal
        });
        clearTimeout(to);
        const data = await resp.json();
        reply = data.reply || data.response || '';
        if (reply) break;
      } catch(e) { reply = '...重试中...'; await new Promise(r => setTimeout(r, 1000)); }
    }
    addMessage('bot', reply || '管家正在思考...');
  }

  // 解锁
  isAutoPlaying = false;
  document.getElementById('userInput').disabled = false;
  document.getElementById('userInput').placeholder = '输入消息...';
  addMessage('bot', '✅ <b>演示结束</b> — 你可以继续对话或选其他场景～');
}

async function resetAll() {
  try { await fetch(BACKEND_URL + '/admin/reset', {method:'POST'}); toast('已重置', 'ok'); addMessage('bot','所有场景已重置。'); }
  catch(e) { toast('重置失败', 'err'); }
}

async function speedUp() {
  try {
    const r = await fetch(BACKEND_URL + '/admin/speed-up', {method:'POST'});
    const d = await r.json();
    toast('数据已刷新！', 'ok');
    addMessage('bot', '⚡ <b>加速测试完成</b>：餐厅排队、天气、路况已随机变化～现在再去问问管家感受变化吧！');
  } catch(e) { toast('加速测试失败', 'err'); }
}

function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast ' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 2000);
}

// 通知轮询（每30秒）
async function pollNotifications() {
  try {
    const r = await fetch('/api/notifications?user_id=' + currentUser);
    const d = await r.json();
    const count = d.unread_count || 0;
    const badge = document.getElementById('notif-badge');
    if (count > 0) {
      badge.style.display = 'block';
      badge.textContent = count > 99 ? '99+' : count;
    } else {
      badge.style.display = 'none';
    }
    // 更新通知面板
    const list = document.getElementById('notif-list');
    if (d.notifications && d.notifications.length > 0) {
      list.innerHTML = d.notifications.map(n => {
        const icon = n.type === 'alert' ? '⚠️' : n.type === 'reminder' ? '📅' : '📬';
        return '<div style="margin-bottom:6px;padding:6px;background:#262626;border-radius:6px;border-left:3px solid ' + (n.type==='alert'?'#dc2626':'#2563eb') + '"><div style="color:#888;font-size:10px">' + icon + ' ' + n.time + '</div><div style="white-space:pre-wrap">' + n.message + '</div></div>';
      }).join('');
    } else {
      list.innerHTML = '<div style="color:#555">暂无新通知</div>';
    }
  } catch(e) {}
}
async function toggleNotifications() {
  const panel = document.getElementById('notif-panel');
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  if (panel.style.display === 'block') {
    await pollNotifications();
    await fetch('/api/notifications/read?user_id=' + currentUser, {method:'POST'});
  }
}
setInterval(pollNotifications, 30000);
pollNotifications();


function closeProfileCard() {
  document.getElementById('user-profile-card').style.display = 'none';
}

async function showProfile(uid) {
  // 按钮高亮
  document.querySelectorAll('.user-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + (uid==='white_collar'?'wc':uid==='parent'?'parent':'student'))?.classList.add('active');
  // 加载档案
  const card = document.getElementById('user-profile-card');
  card.style.display = 'block';
  card.innerHTML = '<div style="text-align:center;color:#555;padding:8px">加载中...</div>';
  try {
    const r = await fetch('/api/profile/' + uid);
    const d = await r.json();
    if (!d.ok) { card.innerHTML = '<div style="color:#888">档案加载失败</div>'; return; }
	    let rows = [];
	    rows.push('<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px"><div><span style="font-size:15px;font-weight:600;color:#fff">' + d.icon + ' ' + d.name + '</span><span style="color:#888;font-size:12px"> | ' + (d.age||'?') + '岁 | ' + (d.gender||'') + '</span></div><button onclick="closeProfileCard()" style="background:none;border:none;color:#666;cursor:pointer;font-size:16px">✕</button></div>');
	    rows.push('<div style="color:#888;font-size:11px;margin-bottom:4px">' + d.role + '</div>');
	    rows.push('<div style="border-top:1px solid #333;margin:4px 0"></div>');
	    if (d.city) rows.push('<div style="margin-bottom:2px"><span style="color:#888">常驻：</span><span style="color:#ccc">' + d.city + '</span></div>');
	    if (d.work) rows.push('<div style="margin-bottom:2px"><span style="color:#888">工作地址：</span><span style="color:#ccc">' + d.work + '</span></div>');
	    if (d.school) rows.push('<div style="margin-bottom:2px"><span style="color:#888">学校地址：</span><span style="color:#ccc">' + d.school + '</span></div>');
	    if (d.home) rows.push('<div style="margin-bottom:2px"><span style="color:#888">居住地址：</span><span style="color:#ccc">' + d.home + '</span></div>');
	    if (d.family) rows.push('<div style="margin-bottom:2px"><span style="color:#888">家庭：</span><span style="color:#ccc">' + d.family + '</span></div>');
	    if (d.taste) rows.push('<div style="margin-bottom:2px"><span style="color:#888">口味：</span><span style="color:#ccc">' + d.taste + '</span></div>');
	    if (d.avoid) rows.push('<div style="margin-bottom:2px"><span style="color:#888">忌口：</span><span style="color:#ccc">' + d.avoid + '</span></div>');
	    card.innerHTML = rows.join('');
  } catch(e) { card.innerHTML = '<div style="color:#888">加载失败: ' + e.message + '</div>'; }
}
const BACKEND_URL = '/backend';
</script>
</div>
</body>
</html>"""


# ---- FastAPI 端点 ----

# 启动 HEARTBEAT 后台调度
@app.on_event("startup")
async def start_heartbeat_scheduler():
    heartbeat.start_heartbeat(BACKEND_URL, BUTLER_DIR)
    guardian.start_guardian(BACKEND_URL, OPENAI_API_KEY, OPENAI_BASE_URL, BUTLER_DIR)
    print("[chat_proxy] HEARTBEAT + GUARDIAN started")


@app.get("/api/profile/{user_id}")
def get_user_profile(user_id: str):
    """获取用户档案信息（给侧边栏展示）—— 精确结构化数据"""
    PROFILES = {
        "white_collar": {
            "ok": True, "user_id": "white_collar",
            "name": "小琴", "icon": "🏢", "role": "白领 · 产品经理",
            "city": "北京", "age": "37", "gender": "女",
            "work": "朝阳区，望京",
            "home": "朝阳区，常营",
            "family": "已婚，丈夫大刘（40岁）、女儿果果（4岁），公婆（广东）、父母（广东）",
            "taste": "粤菜、日料、清淡火锅、东南亚菜",
            "avoid": "不吃香菜，果果花生过敏",
        },
        "parent": {
            "ok": True, "user_id": "parent",
            "name": "小冉", "icon": "👶", "role": "宝妈 · 自由插画师",
            "city": "北京", "age": "29", "gender": "女",
            "work": "居家办公",
            "home": "朝阳区，双井",
            "family": "已婚，丈夫阿彬（32岁）、儿子乐乐（1.5岁）、宠物狗（布丁），公婆（同住）、父母（上海）",
            "taste": "清淡家常菜、火锅、日料、面食",
            "avoid": "全家不吃辣，乐乐不吃蛋清，阿彬不吃香菜",
        },
        "student": {
            "ok": True, "user_id": "student",
            "name": "小晴", "icon": "🎓", "role": "大学生 · 某985研一",
            "city": "北京", "age": "23", "gender": "女",
            "school": "通州区（有宿舍）",
            "work": "海淀区，中关村",
            "home": "公司附近（实习期）",
            "family": "未婚，父母（广东）、弟弟小宇（13岁）",
            "taste": "东南亚菜、重口味、辣、奶茶",
            "avoid": "葱花香菜蒜、内脏、羊肉",
        },
    }
    p = PROFILES.get(user_id)
    if not p:
        return {"error": "Unknown user", "available": list(PROFILES.keys())}
    return p


@app.post("/api/clear-history")
def clear_chat_history(user_id: str = "white_collar"):
    """清空对话历史（场景切换时调用）"""
    if user_id in CHAT_HISTORY:
        CHAT_HISTORY[user_id] = []
    return {"ok": True, "message": f"History cleared for {user_id}"}


@app.get("/api/notifications")
def get_notifications(user_id: str = "white_collar"):
    """获取当前用户的推送通知"""
    user_notifs = [n for n in heartbeat.notifications if n["user_id"] == user_id]
    # 返回未读的 + 最近10条已读
    unread = [n for n in user_notifs if not n["read"]]
    recent = [n for n in user_notifs if n["read"]][:10]
    return {
        "notifications": (unread + recent)[:20],
        "unread_count": len(unread),
        "total": len(user_notifs),
    }


@app.post("/api/notifications/read")
def mark_notifications_read(user_id: str = "white_collar"):
    """标记所有通知为已读"""
    count = 0
    for n in heartbeat.notifications:
        if n["user_id"] == user_id and not n["read"]:
            n["read"] = True
            count += 1
    return {"ok": True, "marked_read": count}


@app.get("/", response_class=HTMLResponse)
def chat_ui():
    return CHAT_HTML


@app.post("/chat")
async def chat_endpoint(request: dict):
    """AI 对话端点：OpenClaw Gateway 优先 → 降级直连 DeepSeek"""
    msg = request.get("message", "").strip()
    user_id = request.get("user_id", "white_collar")

    if not msg:
        return {"reply": "我在听～请说。", "user_id": user_id}

    mode = "unknown"

    # === 方案 1: 转发到 OpenClaw Gateway ===
    try:
        resp = requests.post(
            f"{OPENCLAW_GATEWAY}/api/chat",
            json={"message": msg, "user_id": user_id},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            reply = data.get("reply") or data.get("response") or data.get("content", "")
            if reply:
                mode = "openclaw"
                return {"reply": reply, "user_id": user_id, "mode": mode}
    except requests.exceptions.Timeout:
        pass  # Gateway 超时 → 降级
    except requests.exceptions.ConnectionError:
        pass  # Gateway 未启动 → 降级
    except Exception:
        pass

    # === 方案 2: 降级直连 DeepSeek ===
    reply = chat_direct_deepseek(msg, user_id)
    mode = "standalone"
    return {"reply": reply, "user_id": user_id, "mode": mode}


@app.post("/switch-user/{user_id}")
def switch_user_endpoint(user_id: str):
    """切换当前用户"""
    return switch_user_files(user_id)


@app.get("/health")
def health():
    """健康检查"""
    gw_ok = False
    try:
        r = requests.get(f"{OPENCLAW_GATEWAY}/health", timeout=2)
        gw_ok = r.status_code == 200
    except:
        pass

    backend_ok = False
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=3)
        backend_ok = r.status_code == 200
    except:
        pass

    return {
        "status": "ok",
        "service": "butler-agent",
        "openclaw_gateway": "running" if gw_ok else "unreachable",
        "mock_backend": "connected" if backend_ok else "unreachable",
        "api_key_set": bool(OPENAI_API_KEY),
        "butler_dir": BUTLER_DIR,
        "butler_dir_exists": os.path.exists(BUTLER_DIR),
        "mode": "standalone (降级模式)" if not gw_ok else "openclaw",
    }


@app.get("/debug/env")
def debug_env():
    """诊断环境变量"""
    return {
        "port": PORT,
        "backend_url": BACKEND_URL,
        "openclaw_gateway": OPENCLAW_GATEWAY,
        "butler_dir": BUTLER_DIR,
        "butler_dir_exists": os.path.exists(BUTLER_DIR),
        "api_key_set": bool(OPENAI_API_KEY),
        "api_key_preview": (OPENAI_API_KEY[:8] + "..." + OPENAI_API_KEY[-4:]) if OPENAI_API_KEY else "NOT SET",
        "soyl_md_exists": os.path.exists(os.path.join(BUTLER_DIR, "SOUL.md")),
        "user_md_exists": os.path.exists(os.path.join(BUTLER_DIR, "USER.md")),
    }


@app.get("/api/scenario/{scenario_id}")
def get_scenario_script(scenario_id: str):
    """获取场景对话脚本"""
    script = SCENARIO_SCRIPTS.get(scenario_id)
    if not script:
        return {"error": f"Unknown scenario: {scenario_id}"}
    return {"ok": True, "scenario": script}


@app.api_route("/backend/{path:path}", methods=["GET", "POST"])
async def proxy_backend(path: str, request: dict = None):
    """代理后端请求 — 前端场景触发/加速测试等"""
    try:
        url = f"{BACKEND_URL}/{path}"
        if request:
            r = requests.post(url, json=request, timeout=8)
        else:
            r = requests.get(url, timeout=8)
        return r.json()
    except:
        return {"error": f"Cannot reach backend: {BACKEND_URL}"}


if __name__ == "__main__":
    import uvicorn
    print(f"[chat_proxy] Starting on port {PORT}")
    print(f"[chat_proxy] BACKEND_URL = {BACKEND_URL}")
    print(f"[chat_proxy] BUTLER_DIR = {BUTLER_DIR}")
    print(f"[chat_proxy] OPENCLAW_GATEWAY = {OPENCLAW_GATEWAY}")
    uvicorn.run("chat_proxy:app", host="0.0.0.0", port=PORT, reload=True)
