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
    # dining-butler
    {"type":"function","function":{"name":"restaurant_recommend","description":"推荐餐厅，支持菜系/预算/设施/过敏过滤。用户画像自动过滤偏好。","parameters":{"type":"object","properties":{"user_id":{"type":"string","description":"用户ID"},"cuisine":{"type":"string"},"budget":{"type":"integer"},"people_count":{"type":"integer"},"scene":{"type":"string","description":"business/family/date/casual"},"must_have":{"type":"string","description":"baby_seat/parking/private_room/pet_allowed"},"latitude":{"type":"number"},"longitude":{"type":"number"}},"required":["user_id"]}}},
    {"type":"function","function":{"name":"restaurant_queue","description":"查询餐厅当前排队状态和预计等待时间","parameters":{"type":"object","properties":{"restaurant_id":{"type":"integer"}},"required":["restaurant_id"]}}},
    {"type":"function","function":{"name":"restaurant_emergency","description":"突发兜底：暴雨/满座/迟到/歇业时的替代方案","parameters":{"type":"object","properties":{"user_id":{"type":"string"},"emergency_type":{"type":"string","description":"weather/full/late/closure"},"current_lat":{"type":"number"},"current_lng":{"type":"number"},"has_child":{"type":"boolean"}},"required":["emergency_type","current_lat","current_lng"]}}},
    # mobility-butler
    {"type":"function","function":{"name":"plan_route","description":"多模式路径规划：驾车/地铁/骑行/步行/打车，考虑实时路况","parameters":{"type":"object","properties":{"origin_lat":{"type":"number"},"origin_lon":{"type":"number"},"dest_lat":{"type":"number"},"dest_lon":{"type":"number"},"user_type":{"type":"string"}},"required":["origin_lat","origin_lon","dest_lat","dest_lon"]}}},
    {"type":"function","function":{"name":"transport_search","description":"查机票/火车票(模拟)","parameters":{"type":"object","properties":{"origin_city":{"type":"string"},"dest_city":{"type":"string"},"transport_type":{"type":"string","description":"flight/train/all"}},"required":["origin_city","dest_city"]}}},
    {"type":"function","function":{"name":"nearby_facilities","description":"周边设施：加油站/充电桩/便利店/停车场/药店/宠物医院","parameters":{"type":"object","properties":{"lat":{"type":"number"},"lon":{"type":"number"},"facility_type":{"type":"string"}},"required":["lat","lon","facility_type"]}}},
    # outfit-advisor
    {"type":"function","function":{"name":"get_weather","description":"北京当前天气+AQI+预警","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"get_outfit","description":"基于天气+用户身份的穿搭建议","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
    {"type":"function","function":{"name":"get_wardrobe","description":"查询用户衣橱+缺失物品","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
    # city-explorer
    {"type":"function","function":{"name":"get_events","description":"周末/近期活动：展览/演出/市集/亲子/演唱会","parameters":{"type":"object","properties":{"type":{"type":"string","description":"exhibition/show/market/kids/concert/all"},"user_id":{"type":"string"}}}}},
    {"type":"function","function":{"name":"get_shopping","description":"商场促销信息","parameters":{"type":"object","properties":{"category":{"type":"string","description":"clothing/electronics/home/child/all"}}}}},
    # life-organizer
    {"type":"function","function":{"name":"get_schedule","description":"今日日程安排","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
    {"type":"function","function":{"name":"search_memory","description":"搜索用户偏好记忆","parameters":{"type":"object","properties":{"user_id":{"type":"string"},"keyword":{"type":"string"}},"required":["user_id"]}}},
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

    # 1. SOUL.md — 管家灵魂设定
    soul = read_file(os.path.join(BUTLER_DIR, "SOUL.md"), max_chars=2500)
    if soul:
        parts.append(soul)
    else:
        parts.append("你是全天候私人管家。")

    # 2. 五个 SKILL.md 的技能摘要
    skill_files = [
        ("dining-butler", "餐饮管家"),
        ("mobility-butler", "出行管家"),
        ("city-explorer", "活动管家"),
        ("outfit-advisor", "穿搭管家"),
        ("life-organizer", "日程管家"),
    ]
    parts.append("\n\n## 可用技能与工具\n")
    for skill_dir, skill_label in skill_files:
        skill_path = os.path.join(BUTLER_DIR, "skills", skill_dir, "SKILL.md")
        skill_content = read_file(skill_path, max_chars=600)
        if skill_content:
            # 只取关键段落：触发条件 + API + 决策规则
            parts.append(f"### {skill_label} ({skill_dir})\n{skill_content}\n")

    # 3. 当前用户画像
    parts.append("\n\n## 当前服务用户\n")
    user_md = read_file(os.path.join(BUTLER_DIR, "USER.md"), max_chars=1500)
    if user_md:
        parts.append(user_md)
    memory_md = read_file(os.path.join(BUTLER_DIR, "MEMORY.md"), max_chars=1000)
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
    """直连 DeepSeek API，读取所有 butler/ 文件作为 system prompt"""
    if not OPENAI_API_KEY:
        return ("⚠️ AI 服务未配置。请设置 OPENAI_API_KEY 环境变量。\n\n"
                "你可以尝试：\n"
                "🍽️ 「附近火锅」| 👔 「今天穿什么」| 🚇 「去国贸怎么走」| 🎯 「周末活动」")

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

        system_prompt = build_system_prompt(user_id)

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            tools=TOOLS,
            temperature=0.7,
            max_tokens=600,
            timeout=20,
        )

        choice = response.choices[0]
        reply = choice.message.content or ""

        # 处理工具调用
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                fn = tc.function
                try:
                    args = json.loads(fn.arguments)
                except:
                    args = {}
                tool_result = execute_tool(fn.name, args)
                reply += f"\n\n{fn.name}:\n{tool_result}"

        return reply or "收到，让我想想..."

    except Exception as e:
        return f"AI 服务异常: {str(e)[:200]}"


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
  <div style="font-size:11px;color:#666;margin-bottom:4px">切换用户</div>
  <button class="user-btn active" onclick="switchUser('white_collar')" id="btn-wc">小琴 · 白领</button>
  <button class="user-btn" onclick="switchUser('parent')" id="btn-parent">小冉 · 宝妈</button>
  <button class="user-btn" onclick="switchUser('student')" id="btn-student">小晴 · 大学生</button>
  <div class="divider"></div>
  <div style="font-size:11px;color:#666;margin-bottom:4px">场景触发</div>
  <button class="scene-btn" onclick="triggerScene('1')">1. 接待上级午餐</button>
  <button class="scene-btn" onclick="triggerScene('2')">2. 逛街突遇暴雨</button>
  <button class="scene-btn" onclick="triggerScene('7')">7. 乐乐凌晨发烧</button>
  <button class="scene-btn complex" onclick="triggerScene('9')">9. 航班延误</button>
  <button class="scene-btn" onclick="triggerScene('14')">14. 沙尘暴突袭</button>
  <button class="scene-btn complex" onclick="triggerScene('15')">15. 早高峰地铁故障</button>
  <button class="scene-btn complex" onclick="triggerScene('18')">18. 宠物急诊</button>
  <button class="scene-btn" onclick="triggerScene('19')">19. 餐厅临时歇业</button>
  <div class="divider"></div>
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
  document.querySelectorAll('.user-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + (uid==='white_collar'?'wc':uid==='parent'?'parent':'student'))?.classList.add('active');
  document.getElementById('userSelect').value = uid;
}

async function triggerScene(id) {
  const scenes = {
    '1':'接待上级午餐', '2':'逛街突遇暴雨', '7':'乐乐凌晨发烧', '9':'航班延误',
    '14':'沙尘暴突袭', '15':'早高峰地铁故障', '18':'宠物急诊', '19':'餐厅临时歇业'
  };
  try {
    await fetch(BACKEND_URL + '/admin/trigger/scenario/' + id, {method:'POST'});
    addMessage('bot', '<b>场景 ' + id + ' 已触发</b>: ' + (scenes[id]||''));
  } catch(e) { toast('触发失败（后端未连接）', 'err'); }
}

async function resetAll() {
  try { await fetch(BACKEND_URL + '/admin/reset', {method:'POST'}); toast('已重置', 'ok'); addMessage('bot','所有场景已重置。'); }
  catch(e) { toast('重置失败', 'err'); }
}

function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast ' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 2000);
}

const BACKEND_URL = '/backend';
</script>
</div>
</body>
</html>"""


# ---- FastAPI 端点 ----

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


@app.get("/backend/{path:path}")
def proxy_backend(path: str, request: dict = None):
    """代理后端请求（前端场景触发等需要）"""
    try:
        # 只代理 GET 请求
        r = requests.get(f"{BACKEND_URL}/{path}", timeout=5)
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
