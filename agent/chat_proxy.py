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
import threading
import time as _time

# ---- 实时监控（排队进度 / 叫车倒计时）----
MONITORS = {}

def _monitor_bg():
    while True:
        try:
            for uid, monitors in list(MONITORS.items()):
                for m in monitors:
                    now = _time.time()
                    if now - m.get("last_check", 0) < 30: continue
                    m["last_check"] = now
                    if m["type"] == "restaurant_queue":
                        try:
                            r = requests.get(f"{BACKEND_URL}/api/dining/queue?restaurant_id={m['restaurant_id']}", timeout=5)
                            q = r.json()
                            nq = q.get("current_queue", -1)
                            oq = m.get("current_queue", -1)
                            if nq != oq and nq >= 0:
                                m["current_queue"] = nq
                                m["wait_min"] = q.get("estimated_wait_min", 0)
                                if nq <= 3:
                                    heartbeat.add_notification("alert",
                                        f"📳 {m['restaurant_name']}快到了！前面{nq}桌，预计{nq*5}分钟，可以出发了～", uid, "dining")
                                else:
                                    heartbeat.add_notification("schedule",
                                        f"📊 {m['restaurant_name']}排队更新：前面{nq}桌（原{oq}桌），预计{nq*5}分钟", uid, "dining")
                        except: pass
                    elif m["type"] == "taxi":
                        m["wait_min"] = max(0, m.get("wait_min", 5) - 0.5)
                        if m["wait_min"] <= 2 and not m.get("arriving_notified"):
                            m["arriving_notified"] = True
                            heartbeat.add_notification("alert",
                                f"🚕 车快到啦！{m.get('car_info','')}预计{m['wait_min']:.0f}分后到达", uid, "mobility")
                MONITORS[uid] = [m for m in monitors if now - m.get("started_at", 0) < 7200]
        except: pass
        _time.sleep(30)

threading.Thread(target=_monitor_bg, daemon=True).start()

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


# ---- 用户语气模板 ----
USER_TONES = {
    "white_collar": "小琴是效率优先的白领，37岁，美团PM，已婚有女儿果果4岁，丈夫大刘。回复精简果断，用「收到」「已安排」「搞定」风格。",
    "parent": "小冉是安全优先的宝妈，29岁，自由插画师，儿子乐乐1.5岁+柯基布丁。回复温暖细致，多考虑宝宝和宠物安全。",
    "student": "小晴是预算优先的大学生，23岁，金融硕士研一，实习+秋招并行。回复亲切活泼，注意省钱提醒和成长陪伴。",
}

def build_system_prompt(user_id: str) -> str:
    """系统提示：SOUL灵魂 + USER画像 + 实时数据 + 输出模板 + 5条铁律"""
    parts = []
    nl = chr(10)

    # ===== 1. 管家灵魂 =====
    soul = read_file(os.path.join(BUTLER_DIR, "SOUL.md"), max_chars=1500)
    if soul:
        parts.append(soul)

    # ===== 2. 用户画像 =====
    user_md = read_file(os.path.join(BUTLER_DIR, "USER.md"), max_chars=1000)
    if user_md:
        parts.append(f"当前用户:\n{user_md}")

    tone = USER_TONES.get(user_id, "")
    if tone:
        parts.append(tone)
    parts.append(f"当前user_id={user_id}（所有工具调用必须使用此ID）")

    # ===== 3. 实时数据 =====
    ctx = []
    # 注入当前时间（场景时间或真实时间）
    from datetime import datetime as _dt
    effective_time = _scenario_time["time"] if _scenario_time else _dt.now().strftime("%m/%d %a %H:%M")
    ctx.append(f"现在: {effective_time}")
    try:
        w = requests.get(f"{BACKEND_URL}/api/weather/current", timeout=2).json()
        ctx.append(f"{w.get('condition','?')} {w.get('temperature','?')}°C AQI{w.get('aqi','?')}")
    except: pass
    try:
        t = requests.get(f"{BACKEND_URL}/api/mobility/traffic", timeout=2).json()
        ctx.append(f"拥堵指数{t.get('congestion_index','?')}")
    except: pass
    if ctx:
        parts.append(f"实时: {' | '.join(ctx)}")

    # ===== 4. 铁律（5条，违反=不合格）=====
    parts.append(f"""---
铁律:
① 有工具就调（天气/路线/排队/叫车/推荐等后端实时数据）。调完用人话呈现，不描述调用过程。
② 工具无数据或非实时信息（如航班时刻/高铁车次/酒店行情/保险规则）→用你的知识直接回答，给出精确数据，确保同一对话中前后一致不矛盾。你是有全网知识的管家，不需要每个数据都来自后端。
③ 禁止说"工具查不到""Mock连不上""后端没数据""暂时看不到班次""没法直接操作"等自曝短板的话——直接给答案。
④ 用户说的人就是那个人。"领导"≠王总。用户没给的数字（人数/预算）不要编——追问确认。可推断的信息（工作日=在办公室、用户画像里的偏好）标注"按常理…"后使用。
⑤ 每行emoji开头。禁**加粗**、禁```代码块、禁`行内码`、禁JSON。结尾给完整陈述，不挂问句。商务不提家人偏好。
⑥ 天气→调get_weather+weather_alerts再开口。"天黑了"≠下雨。暴雨→收衣+关窗+避远路。
⑦ 先人一步：下雨→天气+找伞+提醒+预报。航班延误→交通+酒店+理赔+提醒。用户说"X分钟后"→调schedule_create。把下一步也做了，不等用户追问。
⑧ 叫车：算时间，到点再叫；短距离(<1.5km)→建议步行。叫车后告知全部信息+自动查券+注册监控。
⑨ 千人千面：小琴精简果断，小冉温暖细致，小晴亲切省钱。AI边界——调工具能做的（查/订/叫车）直接做；涉及真人社交的（打听忌口/帮问/帮说）说"建议您问一下"，不替用户做人际沟通。

----
输出格式（每条推荐必须严格按模板，每行emoji开头，缺一项=不合格）:

▎推荐餐厅（排第一用🥇，第二用🥈，第三用🥉，必须区分）:
🥇 餐厅名（首选）
⭐ 评分X.X | 💰 人均¥X-¥X | 🍳 菜系
📍 地址全称 | 🅿️ 停车情况
🏷️ 商家服务: 列出可用标签（包厢·预订·停车·亲子·宠物·发票·WiFi）
🎫 优惠: 团购/代金券/时段特惠（有则展示，商务场景只提停车发票不提套餐）
💡 推荐理由: 结合场景+偏好+特殊需求+天气+路程（2-3句话）
✅ 我的建议: 为什么排第一——价格/场景/偏好理由
⚠️ 注意事项: 排队/历史教训/需确认（有则写）
（第二条🥈第三条🥉，严禁全部用🥇。每条✅建议必须与排名一致）

▎推荐路线时:
🚗 驾车X分 ¥X | 🚇 地铁X分 ¥X | 🚕 打车X分 ¥X | 🚲 骑行X分 ¥X | 🚶 步行X分
💡 最优: 推荐方式和原因

▎叫车后:
🚕 已叫车 | 🚘 车型·颜色·品牌 | 📋 车牌·司机·电话 | ⏱️ 预计X分钟到达 | 💰 预估¥X
🎫 优惠券(有则展示)

▎推荐活动时:
🎯 活动名 | 🕐 时间 | 📍 地点 | 💰 票价 | 👥 适合人群
💡 推荐理由

▎穿搭建议:
🌡️ X°C AQI X | 👔 上衣+下装+鞋 | 🎒 伞·口罩·防晒

▎外卖/替代:
🛵 外卖约X分钟 | 📦 配送费¥X | 🍜 推荐菜品
---

重要提醒:
- 取号后一定调 restaurant_monitor 注册排队监控（前端会自动显示排队进度）
- 叫车后一定在 MONITORS 注册叫车监控（前端会显示倒计时+车辆信息）
- 多轮对话中保持上下文：用户说的「4个人」要记住，「大领导」不是已知联系人
- 前置检查：推荐前确认用户没提到的人名=不存在，不要自行关联记忆中的名字
- 不编造不存在的折扣/优惠券/套餐——只展示工具返回的真实数据
""")

    result = nl.join(parts)
    # 安全清洗控制字符防止 JSON 序列化失败
    import re as _safe_re
    result = _safe_re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', result)
    return result


def build_skill_context() -> str:
    """精简技能摘要（不重复 function descriptions）"""
    skills_dir = os.path.join(BUTLER_DIR, "skills")
    if not os.path.isdir(skills_dir):
        return ""
    import re
    lines = []
    priority = ["dining-butler", "mobility-butler", "outfit-advisor", "city-explorer", "life-organizer"]
    for d in priority:
        sf = os.path.join(skills_dir, d, "SKILL.md")
        if os.path.isfile(sf):
            content = read_file(sf, max_chars=800)
            fm = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
            if fm:
                name = d; desc = ""
                for line in fm.group(1).split('\n'):
                    if line.startswith('name:'): name = line.split(':',1)[1].strip()
                    elif line.startswith('description:'): desc = line.split(':',1)[1].strip()
                lines.append(f"{name}: {desc}")
    return " | ".join(lines) if lines else ""


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
                return "API返回0条推荐(可能参数过严，请放宽条件重试)"
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
            uid = args.get('user_id','')
            MONITORS.setdefault(uid, []).append({
                "type": "restaurant_queue", "restaurant_id": args.get('restaurant_id',0),
                "restaurant_name": d.get('restaurant_name','餐厅'), "current_queue": d.get('current_queue',0),
                "wait_min": d.get('estimated_wait_min',0), "started_at": _time.time(), "last_check": 0,
            })
            return f"👀 已开启排队监控，当前{d.get('current_queue','?')}桌（预计{d.get('estimated_wait_min','?')}分钟），变化时通知你！"
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
            car_info = f"{d.get('car_color','')}{d.get('car_brand','')} {d.get('plate','')}"
            # 注册叫车监控
            MONITORS.setdefault(args.get('user_id',''), []).append({
                "type": "taxi", "car_info": car_info, "wait_min": d.get('wait_min',5),
                "started_at": _time.time(), "last_check": 0, "arriving_notified": False,
            })
            return f"🚕 已叫车！{car_info} {d.get('car_type','快车')} | 司机{d.get('driver_name','')} {d.get('driver_phone','')} | 预计{d.get('wait_min','?')}分钟到达 | 费用约¥{d.get('estimated_cost','?')}"
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
    """Agent Loop：多轮自主调工具，直到 LLM 认为完成（最多5轮）"""
    if not OPENAI_API_KEY:
        return ("⚠️ AI 服务未配置。请设置 OPENAI_API_KEY 环境变量。\n\n"
                "你可以尝试：\n"
                "🍽️ 「附近火锅」| 👔 「今天穿什么」| 🚇 「去国贸怎么走」| 🎯 「周末活动」")

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

        system_prompt = build_system_prompt(user_id)
        history = CHAT_HISTORY.get(user_id, [])[-16:]  # 最近8轮，防止多轮后丢上下文
        messages = [{"role": "system", "content": system_prompt}] + history + [
            {"role": "user", "content": message}
        ]

        MAX_ROUNDS = 8
        final_reply = ""
        tool_results_collected = []

        for round_num in range(MAX_ROUNDS):
            response = client.chat.completions.create(
                model="deepseek-chat", messages=messages, tools=TOOLS,
                tool_choice="auto", temperature=0.7, max_tokens=1500, timeout=30,
            )
            choice = response.choices[0]
            msg = choice.message
            tool_calls_to_execute = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try: args = json.loads(tc.function.arguments)
                    except: args = {}
                    tool_calls_to_execute.append((tc.id, tc.function.name, args))
            if not tool_calls_to_execute:
                if msg.content:
                    text_tools = _parse_text_tools(msg.content)
                    for tt in text_tools:
                        tool_calls_to_execute.append((f"text_{tt[0]}", tt[0], tt[1]))
                if not tool_calls_to_execute:
                    final_reply = _clean_reply(msg.content or "")
                    if final_reply and len(final_reply) > 3: break
                    else: final_reply = "收到，让我想想..."; break
            # 执行工具（中间文字不保留）
            has_thinking = any(kw in (msg.content or "") for kw in [
                "我先","帮你调","帮你查","让我","先看看","好的，",
                "扩大范围","未找到","让我再","等一下","先查","先帮","看看"])
            assistant_msg = {"role": "assistant"}
            if not has_thinking and msg.content:
                assistant_msg["content"] = _clean_reply(msg.content)
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [{"id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls]
            messages.append(assistant_msg)
            for tc_id, tc_name, tc_args in tool_calls_to_execute:
                tool_result = execute_tool(tc_name, tc_args)
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": tool_result})
                tool_results_collected.append(f"\n[{tc_name}]: {tool_result[:300]}")

        # 用完整消息历史生成最终回复（保留所有工具结果保证上下文连贯）
        if not final_reply:
            response_final = client.chat.completions.create(
                model="deepseek-chat", messages=messages, temperature=0.7,
                max_tokens=1500, timeout=30,
            )
            final_reply = _clean_reply(response_final.choices[0].message.content or "")
            # 二次强力清洗确保无泄露
            if _is_raw_data_leak(final_reply):
                final_reply = _clean_reply(final_reply)
                if _is_raw_data_leak(final_reply):
                    # 仍然泄露则尝试从纯工具结果重新生成
                    tool_summary = "\n".join(tool_results_collected[-5:]) if tool_results_collected else "无工具结果"
                    retry_msgs = [
                        {"role": "system", "content": build_system_prompt(user_id)},
                        {"role": "user", "content": message},
                        {"role": "user", "content": f"工具数据:\n{tool_summary}\n\n请基于以上数据，严格按输出模板生成回复。保留对话上下文，引用之前推荐过的餐厅。"}
                    ]
                    # 也保留最近历史
                    for h in history[-3:]:
                        retry_msgs.insert(1, {"role": h["role"], "content": _clean_reply(h.get("content", ""))})
                    response_retry = client.chat.completions.create(
                        model="deepseek-chat", messages=retry_msgs, temperature=0.7,
                        max_tokens=1500, timeout=30,
                    )
                    final_reply = _clean_reply(response_retry.choices[0].message.content or "")

        ## 保存历史
        hist = CHAT_HISTORY.setdefault(user_id, [])
        hist.append({"role": "user", "content": message})
        hist.append({"role": "assistant", "content": final_reply})
        if len(hist) > 24:
            hist[:] = hist[-24:]  # 保留12轮对话，防止早期推荐信息丢失

        return final_reply

    except Exception as e:
        import traceback
        _last_chat_diag.update({
            "mode": "standalone_error",
            "error": str(e)[:300],
            "traceback": traceback.format_exc()[-500:]
        })
        return f"小管暂时有点忙，请稍后再试～"

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


def _parse_text_tools(text: str) -> list:
    """从 LLM 文本输出中解析工具调用（兼容 DeepSeek XML/JSON 格式）"""
    import re
    tools = []
    pattern = r'<invoke\s+name="(\w+)"[^>]*>(.*?)</invoke>'
    for m in re.finditer(pattern, text, re.DOTALL):
        name = m.group(1)
        body = m.group(2)
        args = {}
        for pm in re.finditer(r'<parameter\s+name="(\w+)"[^>]*>(.*?)</parameter>', body, re.DOTALL):
            args[pm.group(1)] = pm.group(2).strip()
        if name: tools.append((name, args))
    json_pattern = r'\{"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{[^}]+\})\}'
    for m in re.finditer(json_pattern, text):
        try:
            name = m.group(1)
            args = json.loads(m.group(2))
            tools.append((name, args))
        except: pass
    return tools


def _clean_reply(text: str) -> str:
    """过滤 LLM 响应中的工具调用语法、Markdown、代码块、JSON、系统暴露"""
    import re
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = text.replace('**', '')
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'第[一二三四五]轮[：:]?\s*', '', text)
    text = re.sub(r'Step\s*\d+[：:]\s*', '', text)
    # 强力清除：裸工具参数（user_id/坐标/数字串）
    text = re.sub(r'^white_collar\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^parent\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^student\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^business\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^family\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^casual\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^date\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d{2}\.\d{4,6}\s*$', '', text, flags=re.MULTILINE)  # 坐标如 39.9959
    text = re.sub(r'^\d{2,4}\s*$', '', text, flags=re.MULTILINE)  # 纯数字如 3000
    text = re.sub(r'^\d{3}\.\d{4,6}\s*$', '', text, flags=re.MULTILINE)  # 坐标如 116.4721
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _is_raw_data_leak(text: str) -> bool:
    """检测回复是否包含系统内部数据泄露（工具参数、推理过程等）"""
    import re as _re
    if not text or len(text) < 3:
        return True  # 空/过短回复也是异常
    leak_patterns = [
        # JSON/工具参数泄露
        (r'\n"\w+":\s*"', 'json key-value'),
        (r'\n\[".+?"\]', 'json array'),
        (r'"\w+":\s*\[', 'json key with array'),
        # 内部推理文字
        (r'我先查', 'reasoning'),
        (r'帮你调', 'reasoning'),
        (r'让我看看', 'reasoning'),
        (r'等一下，让我', 'reasoning'),
        (r'好的，\d+:\d+叫车', 'reasoning'),
        (r'扩大范围再查', 'reasoning'),
        (r'未找到直接匹配', 'no result leak'),
        (r'数据查询后暂未找到', 'no result leak'),
        (r'暂未找到完全匹配', 'no result leak'),
        (r'结合您之前的用餐记录', 'reasoning leak'),
        (r'让我回顾一下刚刚的对话', 'reasoning leak'),
        (r'Mock.*后端.*连不上', 'backend leak'),
        (r'后端.*不可用', 'backend leak'),
        (r'系统.*暂时.*没拉', 'backend leak'),
        (r'系统这边.*没', 'backend leak'),
        (r'当前环境下.*没有.*API', 'backend leak'),
        (r'没有实时.*API.*可用', 'backend leak'),
        (r'系统推荐的.*有限', 'backend leak'),
        (r'凭知识给你推荐', 'backend leak'),
        (r'数据库.*记录', 'backend leak'),
        (r'让我再试', 'reasoning'),
        # 裸工具参数（多行短文本 = 可能是工具参数泄露）
        (r'^(?:white_collar|parent|student|business|family|casual|date)\s*$', 'user/type param', _re.MULTILINE),
        (r'^(?:economy|comfort|business|driving|transit|walking|cycling|taxi)\s*$', 'transport param', _re.MULTILINE),
        # 系统内部术语
        (r'\[chat\]\s*standalone', 'log leak'),
        (r'function.call|tool_call|tool_calls', 'api leak'),
        (r'execute_tool|chat_direct_deepseek', 'code leak'),
    ]
    for item in leak_patterns:
        pat = item[0]
        flags = item[2] if len(item) > 2 else 0
        if _re.search(pat, text, flags):
            return True
    # 检测过短的单字行（工具参数泄露特征）
    # 更完整的合法emoji列表，避免误杀正常回复
    VALID_STARTERS = ('🥇','🥈','🥉','⭐','📍','💰','🏷','💡','✅','⚠','🎫',
        '🚗','🚇','🚕','🚲','🚶','🚘','📋','⏱','🎯','👥',
        '🌡','👔','🎒','🛵','🍜','▎','🔔','📅','📢','🔑',
        '🌧','☀','☂','🌩','☔','🌤','⚡','❄','🍽','🏠',
        '👶','🐶','💊','🏥','🏪','🅿','🍴','👵','🧥','🛒',
        '☕','🍲','📌','📝','📊','🟢','🔴','🟡','💨','🩺',
        '🚪','🌂','🧹','🔎','📈','🏃','🎬','💳','🧾')
    lines = [l for l in text.split('\n') if l.strip()]
    short_lines = [l for l in lines if len(l.strip()) < 30 and not l.strip().startswith(VALID_STARTERS)]
    # 只有5行以上且>80%是短行才判定为泄露（防止误杀正常回复）
    if len(short_lines) >= 5 and len(short_lines) >= len(lines) * 0.8:
        return True
    return False

# 当前活跃用户（懒加载跟踪，避免重复文件复制）
_current_active_user = None

def _ensure_user_switched(user_id: str):
    """确保当前请求的用户文件已加载（懒切换）"""
    global _current_active_user
    if _current_active_user != user_id:
        switch_user_files(user_id)
        _current_active_user = user_id


# ---- H5 聊天界面 ----

CHAT_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LocalLife Butler — 全天候私人管家</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f4f0ff;color:#1a1a1a;height:100vh;display:flex}
.sidebar{width:260px;background:#fff;padding:16px;display:flex;flex-direction:column;gap:12px;border-right:1px solid #e0d8f0;overflow-y:auto}
.sidebar h2{font-size:16px;color:#5b21b6;margin-bottom:4px}
.user-btn{display:block;width:100%;padding:10px 14px;border:1px solid #ddd;border-radius:8px;background:#f8f6ff;color:#333;cursor:pointer;text-align:left;font-size:13px;margin-bottom:6px;transition:all .15s}
.user-btn:hover{border-color:#7c3aed;background:#ede9fe}
.user-btn.active{border-color:#7c3aed;background:#ede9fe;color:#059669}
.scene-btn{display:block;width:100%;padding:7px 12px;border:1px solid #ddd;border-radius:6px;background:#f8f6ff;color:#555;cursor:pointer;font-size:12px;margin-bottom:4px;transition:all .15s}
.scene-btn:hover{border-color:#7c3aed;color:#5b21b6}
.scene-btn.complex{border-left:3px solid #dc2626}
.scene-btn.active{border-color:#7c3aed;background:#ede9fe;color:#5b21b6}
.divider{border:none;border-top:1px solid #2a2a2a;margin:8px 0}
.main{flex:1;display:flex;flex-direction:column;max-width:calc(100% - 260px)}
.header{padding:14px 20px;background:#fff;border-bottom:1px solid #e0d8f0;display:flex;align-items:center;gap:12px}
.header .avatar{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#a78bfa);display:flex;align-items:center;justify-content:center;font-size:18px}
.header .title{font-size:15px;font-weight:600;color:#5b21b6}.header .subtitle{font-size:12px;color:#888}
.messages{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:16px;background:#fff}
.msg{display:flex;gap:10px;max-width:85%}
.msg.user{align-self:flex-end;flex-direction:row-reverse}
.msg.bot{align-self:flex-start}
.msg .bubble{padding:12px 16px;border-radius:16px;font-size:14px;line-height:1.5;white-space:pre-wrap}
.msg.user .bubble{background:#7c3aed;color:#1a1a1a;border-bottom-right-radius:4px}
.msg.bot .bubble{background:#f0ecff;color:#1a1a1a;border-bottom-left-radius:4px}
.msg .avatar-mini{width:30px;height:30px;border-radius:50%;background:#333;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
.input-area{padding:14px 20px;background:#fff;border-top:1px solid #e0d8f0;display:flex;gap:10px}
.input-area input{flex:1;padding:12px 16px;border:1px solid #ddd;border-radius:24px;background:#f8f6ff;color:#1a1a1a;font-size:14px;outline:none}
.input-area input:focus{border-color:#2563eb}
.input-area button{padding:10px 20px;border:none;border-radius:24px;background:#a78bfa;color:#fff;font-weight:600;cursor:pointer;font-size:14px}
.input-area button.mic{background:#a78bfa;color:#fff;font-size:18px;padding:10px 14px}
.input-area button:hover{opacity:.9}
.toast{position:fixed;top:16px;right:16px;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;z-index:999;opacity:0;transition:opacity .3s}
.toast.show{opacity:1}
.toast.ok{background:#ede9fe;color:#059669}
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
.hamburger{background:none;border:none;color:#555;font-size:18px;cursor:pointer;padding:4px 8px}
.user-switch select{padding:5px 8px;border:1px solid #ddd;border-radius:6px;background:#1a1a1a;color:#333;font-size:12px;cursor:pointer;outline:none}
</style>
</head>
<body>
<div class="app-container">

<div class="sidebar" id="sidebar-el">
  <h2>LocalLife Butler</h2>
  <div style="font-size:11px;color:#777;margin-bottom:8px">全天候私人管家 · 管理面板</div>
  <div class="divider"></div>
  <div style="font-size:11px;color:#777;margin-bottom:4px">👤 用户档案</div>
  <button class="user-btn active" onclick="showProfile('white_collar')" id="btn-wc">🏢 小琴 · 白领</button>
  <button class="user-btn" onclick="showProfile('parent')" id="btn-parent">👶 小冉 · 宝妈</button>
  <button class="user-btn" onclick="showProfile('student')" id="btn-student">🎓 小晴 · 大学生</button>
  <div id="user-profile-card" style="display:none;background:#f5f2ff;border-radius:8px;padding:12px;margin-top:8px;font-size:12px;color:#555;line-height:1.6"></div>
  <div class="divider"></div>
  <div style="font-size:11px;color:#777;margin-bottom:4px">🎬 场景触发（<span id="scene-count">0</span>个）</div>
  <div id="scene-list"></div>
  <div class="divider"></div>
  <button class="scene-btn" onclick="speedUp()" style="color:#f59e0b">⚡ 加速数据变化</button>
  <div style="display:flex;gap:4px">
    <button class="scene-btn" onclick="fastForward(10)" style="color:#60a5fa;flex:1">⏩ +10分钟</button>
    <button class="scene-btn" onclick="fastForward(30)" style="color:#818cf8;flex:1">⏩ +30分钟</button>
  </div>
  <button class="scene-btn" onclick="changeWeather()" style="color:#fbbf24">🌤️ 随机切换天气</button>
  <div style="display:flex;gap:4px">
    <button class="scene-btn" onclick="switchDayType('weekday')" style="color:#34d399;flex:1">📅 工作日</button>
    <button class="scene-btn" onclick="switchDayType('weekend')" style="color:#f472b6;flex:1">🏖️ 周末</button>
  </div>
  <button class="scene-btn" onclick="resetAll()" style="color:#fca5a5">重置所有场景</button>
  <div class="divider"></div>
  <div id="live-monitors" style="font-size:11px;color:#555">
    <div style="color:#555;margin-bottom:4px">📡 实时监控</div>
    <div id="monitor-content" style="color:#777">暂无活跃监控</div>
  </div>
  <div style="margin-top:auto;font-size:10px;color:#888">Powered by OpenClaw<br>Agent v2.0</div>
</div>

<div class="main">
  <div class="header">
    <button class="hamburger" onclick="document.getElementById('sidebar-el').classList.toggle('open')" title="管理面板">☰</button>
    <div class="avatar"></div>
    <div style="flex:1"><div class="title">全天候私人管家</div></div>
    <div class="user-switch">
      <select id="userSelect" onchange="switchUser(this.value)" style="background:#f0ecff;color:#5b21b6;border:1px solid #c4b5fd;border-radius:6px;padding:4px 8px;font-size:13px">
        <option value="white_collar">小琴</option>
        <option value="parent">小冉</option>
        <option value="student">小晴</option>
      </select>
    </div>
    <button id="notif-bell" onclick="toggleNotifications()" style="background:none;border:none;font-size:18px;cursor:pointer;position:relative">🔔<span id="notif-badge" style="display:none;position:absolute;top:-5px;right:-5px;background:#dc2626;color:#1a1a1a;border-radius:50%;width:18px;height:18px;font-size:10px;line-height:18px;text-align:center">0</span></button>
  </div>
  <div id="weather-bar" style="background:#f0ecff;border-bottom:1px solid #e0d8f0;padding:6px 20px;font-size:12px;color:#555;display:flex;gap:16px;align-items:center">
    <span id="wb-time">--</span>
    <span id="wb-weather">--</span>
    <span id="wb-temp">--</span>
    <span id="wb-aqi">--</span>
  </div>
  <div id="notif-panel" style="display:none;position:fixed;top:56px;right:10px;background:#f5f2ff;border:1px solid #ddd;border-radius:12px;padding:12px;max-height:300px;overflow-y:auto;z-index:200;width:300px;box-shadow:0 8px 24px rgba(0,0,0,0.5)">
    <div style="font-size:13px;font-weight:600;color:#1a1a1a;margin-bottom:8px">📬 管家提醒</div>
    <div id="notif-list" style="font-size:12px;color:#555">暂无新通知</div>
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
let activeSceneId = null;
let isListening = false;

// 从服务端加载场景列表
let allScenes = {};
async function loadScenes() {
  try {
    const r = await fetch('/api/scenes');
    allScenes = await r.json();
    renderSceneButtons();
  } catch(e) { console.log('Scene load error'); }
}
function renderSceneButtons() {
  const list = document.getElementById('scene-list');
  const userScenes = Object.entries(allScenes).filter(([id, s]) => s.user === currentUser);
  document.getElementById('scene-count').textContent = userScenes.length;
  list.innerHTML = userScenes.map(([id, s]) => {
    const isActive = id === activeSceneId;
    return '<button class="scene-btn' + (isActive ? ' active' : '') + '" onclick="triggerScene(\'' + id + '\')">' + s.title + '</button>';
  }).join('');
}
loadScenes();
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
  activeSceneId = null;
  renderSceneButtons();
  // 清空聊天+历史，隔离用户
  document.getElementById('messages').innerHTML = '';
  try { await fetch('/api/clear-history?user_id=' + uid, {method:'POST'}); } catch(e) {}
  try { await fetch('/switch-user/' + uid, {method:'POST'}); } catch(e) {}
  // 重置场景状态
  try { await fetch('/api/scenario-reset', {method:'POST'}); } catch(e) {}
  await updateWeatherBar();  // 等天气栏刷新完再取时间
  // 根据顶部时间和天气生成应景问候
  const timeEl = document.getElementById('wb-time');
  const weatherEl = document.getElementById('wb-weather');
  const tempEl = document.getElementById('wb-temp');
  const displayTime = timeEl ? timeEl.textContent : '';
  const weather = weatherEl ? weatherEl.textContent : '';
  const temp = tempEl ? tempEl.textContent : '';
  const hour = parseInt(displayTime.match(/(\d+):/)?.[1] || '12');
  const isMorning = hour >= 6 && hour < 11;
  const isNoon = hour >= 11 && hour < 14;
  const isAfternoon = hour >= 14 && hour < 18;
  const isEvening = hour >= 18 && hour < 22;
  const timeGreeting = isMorning ? '早上好' : isNoon ? '中午好' : isAfternoon ? '下午好' : isEvening ? '晚上好' : '夜深了';
  const weatherInfo = weather && temp ? ' 今天' + weather + temp : '';
  const g = {
    white_collar: '小琴' + timeGreeting + '！' + weatherInfo,
    parent: '小冉' + timeGreeting + '！' + weatherInfo,
    student: '小晴' + timeGreeting + '！' + weatherInfo
  };
  addMessage('bot', g[uid] || '已切换用户～');
}

let isAutoPlaying = false;

async function triggerScene(id) {
  activeSceneId = id;
  renderSceneButtons();  // 高亮当前按钮
  // 获取场景脚本
  let script;
  try {
    const r = await fetch('/api/scenario/' + id);
    const d = await r.json();
    if (!d.ok) { toast('场景不存在', 'err'); return; }
    script = d.scenario;
  } catch(e) { toast('获取场景失败', 'err'); return; }

  // 触发 WorldState 变化 + 同步场景时间到前端
  try { await fetch(BACKEND_URL + '/admin/trigger/scenario/' + id, {method:'POST'}); } catch(e) {}
  try { await fetch(BACKEND_URL + '/admin/reset', {method:'POST'}); } catch(e) {}
  // 同步场景时间上下文到天气栏
  try { await fetch('/api/scenario-time/' + id, {method:'POST'}); } catch(e) {}
  updateWeatherBar();  // 立即刷新顶部时间

  // 清空聊天+历史
  document.getElementById('messages').innerHTML = '';
  try { await fetch('/api/clear-history?user_id=' + script.user, {method:'POST'}); } catch(e) {}

  // 切换用户
  currentUser = script.user;
  document.getElementById('userSelect').value = script.user;
  try { await fetch('/switch-user/' + script.user, {method:'POST'}); } catch(e) {}
  document.querySelectorAll('.user-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + (script.user==='white_collar'?'wc':script.user==='parent'?'parent':'student'))?.classList.add('active');

  // v2 模式：使用 opener 开场白 → 用户自由对话
  if (script.opener) {
    addMessage('bot', '🎬 <b>沙盒场景：' + script.title + '</b><br><span style="font-size:11px;color:#555">场景已激活，下方是建议开场白，你可以修改或直接发送👇</span>');
    document.getElementById('userInput').value = script.opener;
    document.getElementById('userInput').disabled = false;
    document.getElementById('userInput').placeholder = '输入消息...';
    document.getElementById('userInput').focus();
    return;
  }
  // 无 opener → 管家主动发起第一句话
  if (script.opener === '') {
    addMessage('bot', '🎬 <b>沙盒场景：' + script.title + '</b><br><span style="font-size:11px;color:#555">管家正在根据场景信息主动联系你...</span>');
    try {
      const controller = new AbortController();
      const to = setTimeout(() => controller.abort(), 90000);
      const resp = await fetch('/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({message: '(场景触发：' + (script.description || script.title) + '。请管家主动发起对话，给出第一条消息)', user_id: script.user}), signal: controller.signal});
      clearTimeout(to);
      const data = await resp.json();
      addMessage('bot', data.reply || '管家正在思考...');
    } catch(e) { addMessage('bot', '管家正在准备...请稍后再发消息'); }
    document.getElementById('userInput').disabled = false;
    document.getElementById('userInput').placeholder = '输入消息...';
    return;
  }

  // v1 兼容：原多步自动播放模式
  if (script.steps) {
    isAutoPlaying = true;
    document.getElementById('userInput').disabled = true;
    document.getElementById('userInput').placeholder = '🔄 沙盒演示中...';
    addMessage('bot', '🎬 <b>沙盒演示：' + script.title + '</b><br><span style="font-size:11px;color:#555">场景已激活，开始自动对话...</span>');
    for (let i = 0; i < script.steps.length; i++) {
      const step = script.steps[i];
      await new Promise(r => setTimeout(r, step.delay || 2000));
      addMessage('user', step.msg);
      let reply = '';
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const controller = new AbortController();
          const to = setTimeout(() => controller.abort(), 60000);
          const resp = await fetch('/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({message: step.msg, user_id: script.user}), signal: controller.signal});
          clearTimeout(to);
          const data = await resp.json();
          reply = data.reply || data.response || '';
          if (reply) break;
        } catch(e) { reply = '...重试中...'; await new Promise(r => setTimeout(r, 1000)); }
      }
      addMessage('bot', reply || '管家正在思考...');
    }
    isAutoPlaying = false;
    document.getElementById('userInput').disabled = false;
    document.getElementById('userInput').placeholder = '输入消息...';
    addMessage('bot', '✅ <b>演示结束</b> — 你可以继续对话或选其他场景～');
  }
}

async function resetAll() {
  activeSceneId = null;
  renderSceneButtons();
  document.getElementById('messages').innerHTML = '';
  document.getElementById('notif-list').innerHTML = '<span style="color:#555">暂无新通知</span>';
  document.getElementById('notif-badge').style.display = 'none';
  document.getElementById('monitor-content').innerHTML = '<span style="color:#555">暂无活跃监控</span>';
  try { await fetch(BACKEND_URL + '/admin/reset', {method:'POST'}); } catch(e) {}
  try { await fetch('/api/scenario-reset', {method:'POST'}); } catch(e) {}
  try { await fetch('/api/notifications/read?user_id=' + currentUser, {method:'POST'}); } catch(e) {}
  toast('已重置', 'ok');
  updateWeatherBar();
}

async function speedUp() {
  try {
    await fetch(BACKEND_URL + '/admin/speed-up', {method:'POST'});
    toast('数据已刷新！', 'ok');
    await new Promise(r => setTimeout(r, 500));
    updateWeatherBar();
  } catch(e) { toast('加速失败', 'err'); }
}

async function fastForward(mins) {
  try {
    const r = await fetch('/api/fast-forward?minutes=' + mins, {method:'POST'});
    const d = await r.json();
    toast('时间快进' + mins + '分钟！', 'ok');
    updateWeatherBar();
    addMessage('bot', '⏩ 时间已快进' + mins + '分钟 → ' + (d.new_time || ''));
  } catch(e) { toast('快进失败', 'err'); }
}

async function switchDayType(type) {
  try {
    const r = await fetch('/api/switch-day?type=' + type, {method:'POST'});
    const d = await r.json();
    toast('已切换为' + (type === 'weekday' ? '工作日' : '周末') + '！', 'ok');
    updateWeatherBar();
    addMessage('bot', (type === 'weekday' ? '📅' : '🏖️') + ' 已切换为<b>' + (type === 'weekday' ? '工作日' : '周末') + '</b> → ' + (d.new_time || ''));
  } catch(e) { toast('切换失败', 'err'); }
}

async function changeWeather() {
  try {
    const r = await fetch(BACKEND_URL + '/admin/change-weather', {method:'POST'});
    const d = await r.json();
    toast('天气已切换！', 'ok');
    updateWeatherBar();
    addMessage('bot', '🌤️ 天气已切换 → ' + (d.condition || '') + ' ' + (d.temp || '') + '°C');
  } catch(e) { toast('切换失败', 'err'); }
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
        return '<div style="margin-bottom:6px;padding:6px;background:#f0ecff;border-radius:6px;border-left:3px solid ' + (n.type==='alert'?'#dc2626':'#2563eb') + '"><div style="color:#555;font-size:10px">' + icon + ' ' + n.time + '</div><div style="white-space:pre-wrap">' + n.message + '</div></div>';
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

// 实时监控轮询
async function pollMonitors() {
  try {
    const r = await fetch('/api/monitors?user_id=' + currentUser);
    const d = await r.json();
    const el = document.getElementById('monitor-content');
    if (!d.monitors || d.monitors.length === 0) {
      el.innerHTML = '<span style="color:#555">暂无活跃监控</span>';
      return;
    }
    el.innerHTML = d.monitors.map(m => {
      if (m.type === 'restaurant_queue') {
        return '<div style="margin:4px 0;padding:4px 6px;background:#1a2a1a;border-radius:4px;border-left:2px solid #10b981">🍽 ' + (m.restaurant_name||'餐厅') + '<br>🕐 排队: ' + m.current_queue + '桌 | ⏳约' + m.wait_min + '分</div>';
      } else if (m.type === 'taxi') {
        return '<div style="margin:4px 0;padding:4px 6px;background:#1a1a2a;border-radius:4px;border-left:2px solid #3b82f6">🚕 ' + (m.car_info||'叫车中') + '<br>⏱ 预计' + (m.wait_min||'?') + '分到达</div>';
      }
      return '';
    }).join('');
  } catch(e) {}
}
setInterval(pollMonitors, 15000);
pollMonitors();


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
    if (!d.ok) { card.innerHTML = '<div style="color:#555">档案加载失败</div>'; return; }
	    let rows = [];
	    rows.push('<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px"><div><span style="font-size:15px;font-weight:600;color:#1a1a1a">' + d.icon + ' ' + d.name + '</span><span style="color:#555;font-size:12px"> | ' + (d.age||'?') + '岁 | ' + (d.gender||'') + '</span></div><button onclick="closeProfileCard()" style="background:none;border:none;color:#777;cursor:pointer;font-size:16px">✕</button></div>');
	    rows.push('<div style="color:#555;font-size:11px;margin-bottom:4px">' + d.role + '</div>');
	    rows.push('<div style="border-top:1px solid #333;margin:4px 0"></div>');
	    if (d.city) rows.push('<div style="margin-bottom:2px"><span style="color:#555">常驻：</span><span style="color:#333">' + d.city + '</span></div>');
	    if (d.work) rows.push('<div style="margin-bottom:2px"><span style="color:#555">工作地址：</span><span style="color:#333">' + d.work + '</span></div>');
	    if (d.school) rows.push('<div style="margin-bottom:2px"><span style="color:#555">学校地址：</span><span style="color:#333">' + d.school + '</span></div>');
	    if (d.home) rows.push('<div style="margin-bottom:2px"><span style="color:#555">居住地址：</span><span style="color:#333">' + d.home + '</span></div>');
	    if (d.family) rows.push('<div style="margin-bottom:2px"><span style="color:#555">家庭：</span><span style="color:#333">' + d.family + '</span></div>');
	    if (d.taste) rows.push('<div style="margin-bottom:2px"><span style="color:#555">口味：</span><span style="color:#333">' + d.taste + '</span></div>');
	    if (d.avoid) rows.push('<div style="margin-bottom:2px"><span style="color:#555">忌口：</span><span style="color:#333">' + d.avoid + '</span></div>');
	    card.innerHTML = rows.join('');
  } catch(e) { card.innerHTML = '<div style="color:#555">加载失败: ' + e.message + '</div>'; }
}
const BACKEND_URL = '/backend';
// 实时天气栏
async function updateWeatherBar() {
  try {
    const [wr, tr] = await Promise.all([
      fetch(BACKEND_URL + '/api/weather/current'),
      fetch('/api/now')
    ]);
    const w = await wr.json();
    const t = await tr.json();
    document.getElementById('wb-time').textContent = t.time || new Date().toLocaleString('zh-CN', {month:'numeric',day:'numeric',weekday:'short',hour:'2-digit',minute:'2-digit'});
    document.getElementById('wb-weather').textContent = w.condition || '--';
    document.getElementById('wb-temp').textContent = (w.temperature||w.current_temp||'--') + '°C';
    document.getElementById('wb-aqi').textContent = 'AQI ' + (w.aqi||'--');
    if (t.is_scenario) document.getElementById('wb-time').style.color = '#7c3aed';
    else document.getElementById('wb-time').style.color = '#888';
  } catch(e) {}
}
updateWeatherBar();
setInterval(updateWeatherBar, 120000);
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


@app.get("/api/monitors")
def get_monitors(user_id: str = "white_collar"):
    """获取当前活跃的实时监控状态（排队进度/叫车倒计时）"""
    user_monitors = MONITORS.get(user_id, [])
    result = []
    for m in user_monitors:
        item = {"type": m["type"], "started_at": m.get("started_at", 0)}
        if m["type"] == "restaurant_queue":
            item.update({"restaurant_name": m.get("restaurant_name",""), "current_queue": m.get("current_queue",0), "wait_min": m.get("wait_min",0)})
        elif m["type"] == "taxi":
            item.update({"car_info": m.get("car_info",""), "wait_min": m.get("wait_min",5)})
        result.append(item)
    return {"monitors": result, "active_count": len(result)}


@app.get("/api/notifications")
def get_notifications(user_id: str = "white_collar"):
    """获取当前用户的推送通知"""
    import re as _nre
    user_notifs = [n for n in heartbeat.notifications if n["user_id"] == user_id]
    # 清洗通知中的 Markdown
    for n in user_notifs:
        n["message"] = _nre.sub(r'\*\*([^*]+)\*\*', r'\1', n.get("message", ""))
        n["message"] = _nre.sub(r'###+\s*', '', n["message"])
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



# ---- 诊断：上一次聊天使用的模式 ----
_last_chat_diag = {"mode": "unknown", "error": None, "rounds": 0}

@app.get("/debug/last-chat")
def debug_last_chat():
    """查看上一次 /chat 请求使用了哪个模式"""
    return _last_chat_diag

@app.post("/chat")
async def chat_endpoint(request: dict):
    """AI 对话端点：Standalone(全量butler+工具) → openclaw_local(降级) → Gateway(兜底)"""
    msg = request.get("message", "").strip()
    user_id = request.get("user_id", "white_collar")

    if not msg:
        return {"reply": "我在听～请说。", "user_id": user_id}

    # 🔄 确保当前用户文件已切换（懒加载：请求时检测并切换）
    _ensure_user_switched(user_id)

    # === 方案 1 (主力): Standalone — Agent Loop + 25 工具 ===
    try:
        reply = chat_direct_deepseek(msg, user_id)
        # 先强力清洗再检测泄露
        if reply:
            reply = _clean_reply(reply)
        leak = _is_raw_data_leak(reply) if reply else True
        if reply and len(reply) > 10 and not leak:
            _last_chat_diag.update({"mode": "standalone", "error": None, "len": len(reply)})
            return {"reply": reply, "user_id": user_id, "mode": "standalone"}
        elif leak and reply and len(reply) > 20:
            # 有泄露 → 尝试用 _clean_reply 强力清洗后重试一次
            cleaned = _clean_reply(reply)
            if not _is_raw_data_leak(cleaned) and len(cleaned) > 10:
                _last_chat_diag.update({"mode": "standalone_cleaned", "error": None, "len": len(cleaned)})
                return {"reply": cleaned, "user_id": user_id, "mode": "standalone"}
            else:
                _last_chat_diag.update({"mode": "standalone_rejected", "error": f"leak after clean", "preview": (reply or "")[:200]})
        else:
            _last_chat_diag.update({"mode": "standalone_rejected", "error": f"leak={leak} len={len(reply) if reply else 0}", "preview": (reply or "")[:200]})
    except Exception as e:
        _last_chat_diag.update({"mode": "standalone_error", "error": str(e)[:200]})
        print(f"[chat] standalone error: {str(e)[:100]}")

    # === 方案 2 (降级): openclaw agent --local — 读 butler 文件, 用 DeepSeek ===
    import subprocess, os as _os2
    try:
        _os2.environ["OPENCLAW_WORKSPACE"] = BUTLER_DIR
        _os2.environ["OPENCLAW_GATEWAY_PASSWORD"] = "butler-demo-2026"
        r = subprocess.run(
            ["openclaw", "agent", "-m", msg, "--json", "--agent", "main", "--local"],
            capture_output=True, text=True, timeout=25, cwd=BUTLER_DIR
        )
        if r.returncode == 0 and r.stdout:
            try:
                data = json.loads(r.stdout)
                payloads = data.get("payloads", [])
                parts = []
                for p in payloads:
                    t = p.get("text", "")
                    if t:
                        parts.append(t)
                oc_reply = "\n".join(parts)
                if oc_reply and len(oc_reply) > 3:
                    _last_chat_diag.update({"mode": "openclaw_local", "error": None, "len": len(oc_reply)})
                    return {"reply": _clean_reply(oc_reply), "user_id": user_id, "mode": "openclaw_local"}
            except json.JSONDecodeError:
                raw = r.stdout.strip()
                if raw and len(raw) > 3:
                    return {"reply": _clean_reply(raw), "user_id": user_id, "mode": "openclaw_local"}
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # === 方案 3 (兜底): OpenClaw Gateway REST ===
    gw_headers = {"Authorization": "Bearer butler-demo-2026",
                  "Content-Type": "application/json"}
    for endpoint in ["/api/v1/chat", "/api/chat", "/v1/chat/completions", "/chat"]:
        try:
            resp = requests.post(
                f"{OPENCLAW_GATEWAY}{endpoint}",
                json={"message": msg, "user_id": user_id},
                headers=gw_headers, timeout=2,
            )
            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("reply") or data.get("response") or data.get("content", "")
                if reply:
                    return {"reply": reply, "user_id": user_id, "mode": "openclaw"}
        except requests.exceptions.Timeout:
            continue
        except requests.exceptions.ConnectionError:
            break
        except Exception:
            continue

    # === 终极降级 ===
    return {"reply": "抱歉小管暂时无法回应，请稍后再试。", "user_id": user_id, "mode": "error"}


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
        "openclaw_cli": "available" if shutil.which("openclaw") else "not_found",
        "mock_backend": "connected" if backend_ok else "unreachable",
        "api_key_set": bool(OPENAI_API_KEY),
        "butler_dir": BUTLER_DIR,
        "butler_dir_exists": os.path.exists(BUTLER_DIR),
        "modes": ["openclaw_gateway", "openclaw_local", "standalone"],
    }


@app.get("/debug/ws-probe")
async def ws_probe():
    """探测 Gateway WebSocket + 尝试完成认证握手"""
    import asyncio, json as j, hmac, hashlib
    results = {}
    try:
        import websockets
    except:
        return {"error": "websockets not installed"}
    PASSWORD = "butler-demo-2026"
    uri = "ws://localhost:18789/ws?password=butler-demo-2026"
    try:
        async with websockets.connect(uri, open_timeout=3) as ws:
            # 1. 接收 challenge
            chal_raw = await asyncio.wait_for(ws.recv(), timeout=3)
            chal = j.loads(chal_raw)
            results["challenge"] = chal
            nonce = chal.get("payload",{}).get("nonce","")
            # 2. 尝试多种认证方式
            auth_attempts = [
                # HMAC-SHA256
                {"type":"connect","payload":{"nonce":nonce,"auth":hmac.new(PASSWORD.encode(),nonce.encode(),hashlib.sha256).hexdigest()}},
                # 直接发密码
                {"type":"connect","payload":{"nonce":nonce,"password":PASSWORD}},
                # Bearer token
                {"type":"connect","payload":{"nonce":nonce,"token":PASSWORD}},
                # 单发 nonce
                {"type":"connect","payload":{"nonce":nonce}},
            ]
            for i, auth in enumerate(auth_attempts):
                await ws.send(j.dumps(auth))
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=2)
                    results[f"auth_{i}"] = {"sent": j.dumps(auth)[:200], "received": resp[:500]}
                    if "connect" in resp and "ok" in resp.lower():
                        results["AUTH_SUCCESS"] = f"auth method {i} worked!"
                        # 发送测试消息
                        await ws.send(j.dumps({"message":"hi"}))
                        final = await asyncio.wait_for(ws.recv(), timeout=3)
                        results["chat_test"] = final[:500]
                        break
                except asyncio.TimeoutError:
                    results[f"auth_{i}"] = {"sent": j.dumps(auth)[:100], "status": "timeout"}
    except Exception as e:
        results["error"] = str(e)[:200]
    return {"gateway": uri, "results": results}


@app.get("/debug/openclaw-cli")
def openclaw_cli_help():
    """测试 openclaw agent 命令 — 核心：让 agent 读取 butler workspace 文件"""
    import subprocess, json as j, os as _os
    results = {}

    # 0. 先看 openclaw agent --help 有什么参数
    try:
        r = subprocess.run("openclaw agent --help".split(), capture_output=True, text=True, timeout=15, cwd="/app")
        results["--help"] = {"stdout": r.stdout[:800], "stderr": r.stderr[:300]}
    except Exception as e:
        results["--help"] = {"error": str(e)[:200]}

    # 1. 核心测试：--local 模式 + 不同方式指定 workspace
    _os.environ["OPENCLAW_GATEWAY_PASSWORD"] = "butler-demo-2026"
    _os.environ["OPENCLAW_WORKSPACE"] = "/app/butler"

    # workspace 目录内容先确认
    import os as _os2
    butler_files = _os2.listdir("/app/butler") if _os2.path.exists("/app/butler") else ["NOT FOUND"]
    results["butler_files"] = butler_files

    test_cases = [
        # --- A. --local + workspace 变体 ---
        ("local+cwd_butler",            "openclaw agent -m 你是谁 --json --agent main --local", "/app/butler"),
        ("local+cwd_app",               "openclaw agent -m 你是谁 --json --agent main --local", "/app"),
        ("local+workspace_flag",        "openclaw agent -m 你是谁 --json --agent main --local --workspace /app/butler", "/app"),
        ("local+workspace_short",       "openclaw agent -m 你是谁 --json --agent main --local -w /app/butler", "/app"),
        ("local+workspace_env",         "openclaw agent -m 你是谁 --json --agent main --local", "/app"),
        # --- B. Gateway 模式 + 认证变体 ---
        ("gateway+token_flag",          "openclaw agent -m 你是谁 --json --agent main --token butler-demo-2026", "/app/butler"),
        ("gateway+password_flag",       "openclaw agent -m 你是谁 --json --agent main --password butler-demo-2026", "/app/butler"),
        ("gateway+no_auth",             "openclaw agent -m 你是谁 --json --agent main", "/app/butler"),
        ("gateway+bearer_env",          "openclaw agent -m 你是谁 --json --agent main", "/app/butler"),
        # --- C. Gateway REST 探活 ---
        ("gateway_rest_probe",          "curl -s http://localhost:18789/health", "/app"),
        ("gateway_rest_probe2",         "curl -s -H 'Authorization: Bearer butler-demo-2026' -X POST http://localhost:18789/api/v1/chat -d '{\"message\":\"hi\"}' -H 'Content-Type: application/json'", "/app"),
    ]

    for label, cmd, cwd in test_cases:
        try:
            r = subprocess.run(cmd.split() if not cmd.startswith("curl") else ["bash", "-c", cmd],
                             capture_output=True, text=True, timeout=30, cwd=cwd)
            out = r.stdout[:600]
            # 检测是否知道自己是谁
            knows_identity = any(kw in out for kw in ["管家", "butler", "小琴", "butler", "SOUL", "全天候"])
            results[label] = {
                "stdout": out,
                "stderr": r.stderr[:200],
                "code": r.returncode,
                "knows_identity": knows_identity,
                "cwd": cwd,
            }
        except subprocess.TimeoutExpired:
            results[label] = {"error": "timeout", "cwd": cwd}
        except Exception as e:
            results[label] = {"error": str(e)[:200], "cwd": cwd}

    return results


@app.get("/debug/gateway")
def debug_gateway():
    """探测 OpenClaw Gateway 暴露的所有端点"""
    import requests as req
    results = {}
    # 探测 Gateway 暴露的所有端点
    results = {}
    # GET
    for path in ["/openapi.json", "/api/openapi.json", "/api/trpc/agent.chat",
                 "/api/trpc/agent.Chat", "/api/trpc/agent.send",
                 "/api/agent/chat", "/api/v1/agent/chat",
                 "/.well-known/openapi.json", "/api"]:
        try:
            r = req.get(f"http://localhost:18789{path}", timeout=3)
            ct = r.headers.get("content-type","")
            results[path] = {"status": r.status_code, "content_type": ct, "preview": r.text[:100]}
        except Exception as e:
            results[path] = {"error": str(e)[:80]}
    # POST
    for path in ["/api/trpc/agent.chat", "/api/trpc/agent.Chat",
                 "/api/agent/chat", "/api/v1/agent/chat", "/api/chat"]:
        try:
            r = req.post(f"http://localhost:18789{path}", json={"message": "test"}, timeout=3)
            ct = r.headers.get("content-type","")
            results[f"POST {path}"] = {"status": r.status_code, "content_type": ct, "preview": r.text[:150]}
        except Exception as e:
            results[f"POST {path}"] = {"error": str(e)[:80]}
    # 抓 Gateway 首页 HTML 解析 JS 中的 API 端点
    html = ""
    try:
        r = req.get("http://localhost:18789/", timeout=3)
        html = r.text
    except: pass
    import re
    api_hints = re.findall(r'["\x27](/[^"\x27\s]{2,40})["\x27]', html)[:20]
    ws_hints = re.findall(r'(wss?://[^\s"\'<>]+|WebSocket\(["\'][^"\']+["\'])', html)[:5]
    return {"gateway_url": "http://localhost:18789", "api_hints": api_hints, "ws_hints": ws_hints, "probes": results}


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


# ---- 场景时间上下文 ----
_scenario_time = None  # 场景激活时存储 {time, description}

@app.get("/api/now")
def get_current_time():
    """返回有效时间——场景激活时用场景时间，否则用真实时间"""
    from datetime import datetime
    if _scenario_time:
        return {"time": _scenario_time.get("time", ""), "description": _scenario_time.get("description", ""), "is_scenario": True}
    now = datetime.now()
    return {"time": now.strftime("%m/%d %a %H:%M"), "description": "", "is_scenario": False}

@app.post("/api/scenario-time/{scenario_id}")
def set_scenario_time(scenario_id: str):
    """前端触发场景时同步时间上下文"""
    global _scenario_time
    from datetime import datetime
    # 根据场景ID设定合理的时间
    time_map = {
        "1": "06/03 周三 10:30", "2": "06/06 周六 15:00", "3": "06/19 周五 20:00",
        "4": "06/05 周五 17:30", "5": "06/03 周三 19:00", "6": "06/06 周六 10:30",
        "7": "06/10 周三 02:00", "8": "06/13 周六 11:00", "9": "06/09 周二 14:00",
        "10": "06/10 周三 08:00", "11": "06/11 周四 07:00", "12": "06/30 周二 18:00",
        "13": "06/20 周六 15:00", "14": "06/11 周四 17:30", "15": "06/08 周一 09:00",
        "16": "06/12 周五 12:00", "17": "06/15 周一 20:30", "18": "06/13 周六 21:00",
        "19": "06/09 周二 19:00", "20": "06/18 周四 17:00", "21": "06/18 周四 11:30",
    }
    s = SCENARIO_SCRIPTS.get(scenario_id, {})
    _scenario_time = {
        "time": time_map.get(scenario_id, datetime.now().strftime("%m/%d %a %H:%M")),
        "description": s.get("title", ""),
    }
    return {"ok": True, "time": _scenario_time["time"]}

@app.post("/api/fast-forward")
def fast_forward_time(minutes: int = 10):
    """快进场景时间（无场景时自动创建基准时间）"""
    global _scenario_time
    from datetime import datetime, timedelta
    # 无场景时，以当前真实时间为基础创建一个
    if not _scenario_time:
        now = datetime.now()
        _scenario_time = {"time": now.strftime("%m/%d %a %H:%M"), "description": "自由模式"}
    # 解析并快进
    try:
        old = _scenario_time["time"]
        parts = old.split(" ")
        date_part = parts[0]
        time_part = parts[-1]
        month, day = date_part.split("/")
        hour, minute = time_part.split(":")
        dt = datetime(2026, int(month), int(day), int(hour), int(minute))
        dt = dt + timedelta(minutes=minutes)
        new_time = dt.strftime("%m/%d %a %H:%M")
        _scenario_time["time"] = new_time
        return {"ok": True, "new_time": new_time, "minutes": minutes}
    except:
        _scenario_time = None
        return {"ok": False, "error": "时间解析失败"}

@app.post("/api/switch-day")
def switch_day_type(type: str = "weekday"):
    """切换工作日/周末——日期和星期几跟着变"""
    global _scenario_time
    from datetime import datetime, timedelta
    if not _scenario_time:
        now = datetime.now()
        _scenario_time = {"time": now.strftime("%m/%d %a %H:%M"), "description": "自由模式"}
    try:
        old = _scenario_time["time"]
        parts = old.split(" ")
        date_part = parts[0]
        time_part = parts[-1]
        month, day = date_part.split("/")
        hour, minute = time_part.split(":")
        dt = datetime(2026, int(month), int(day), int(hour), int(minute))
        # 找到最近的工作日或周末
        current_weekday = dt.weekday()  # 0=Mon, 5=Sat, 6=Sun
        if type == "weekday":
            if current_weekday >= 5:  # 周末→调到周一
                dt = dt + timedelta(days=(7 - current_weekday))
        else:  # weekend
            if current_weekday < 5:  # 工作日→调到周六
                dt = dt + timedelta(days=(5 - current_weekday))
        new_time = dt.strftime("%m/%d %a %H:%M")
        _scenario_time["time"] = new_time
        return {"ok": True, "new_time": new_time, "type": type}
    except:
        return {"ok": False}

@app.post("/api/scenario-reset")
def reset_scenario_time():
    """重置场景时间"""
    global _scenario_time
    _scenario_time = None
    return {"ok": True}

@app.get("/api/scenes")
def list_all_scenes():
    """返回所有场景（供前端动态渲染）"""
    return {sid: {"title": s["title"], "user": s["user"], "opener": s["opener"]} for sid, s in SCENARIO_SCRIPTS.items()}

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
        # admin 路径（trigger/reset/speed-up）始终用 POST，其余用 GET
        if path.startswith("admin/") or request:
            r = requests.post(url, json=request if request else {}, timeout=8)
        else:
            r = requests.get(url, timeout=8)
        return r.json() if r.text else {"ok": True}
    except Exception as e:
        return {"error": f"Backend unreachable", "detail": str(e)[:100]}


if __name__ == "__main__":
    import uvicorn
    print(f"[chat_proxy] Starting on port {PORT}")
    print(f"[chat_proxy] BACKEND_URL = {BACKEND_URL}")
    print(f"[chat_proxy] BUTLER_DIR = {BUTLER_DIR}")
    print(f"[chat_proxy] OPENCLAW_GATEWAY = {OPENCLAW_GATEWAY}")
    uvicorn.run("chat_proxy:app", host="0.0.0.0", port=PORT, reload=True)
