"""
Guardian — 自主事件响应引擎 v2
WorldState 自然轮动到异常状态时，主动走完应对全流程：
检测→评估→规划→执行→跟进 → 效果不亚于预设场景脚本
"""

import time
import threading
import requests
import json
import os
from datetime import datetime

BACKEND_URL = "http://localhost:8000"
OPENAI_API_KEY = ""
OPENAI_BASE_URL = "https://api.deepseek.com/v1"
BUTLER_DIR = "/app/butler"

_last_snapshot = {}
_running = False
_event_history = {}  # 记录已处理的事件，避免重复


def init_config(backend_url: str, api_key: str, base_url: str, butler_dir: str = "/app/butler"):
    global BACKEND_URL, OPENAI_API_KEY, OPENAI_BASE_URL, BUTLER_DIR
    BACKEND_URL = backend_url
    OPENAI_API_KEY = api_key
    OPENAI_BASE_URL = base_url
    BUTLER_DIR = butler_dir


def _snapshot() -> dict:
    try:
        r = requests.get(f"{BACKEND_URL}/admin/state", timeout=5)
        return r.json()
    except:
        return {}


def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 400) -> str:
    """调 LLM 生成管家文案"""
    if not OPENAI_API_KEY:
        return ""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=max_tokens,
            timeout=15,
        )
        return resp.choices[0].message.content or ""
    except:
        return ""


def _tool_call(name: str, args: dict) -> dict:
    """调 Service 1 工具"""
    try:
        if name == "get_weather":
            return requests.get(f"{BACKEND_URL}/api/weather/current", timeout=5).json()
        elif name == "get_schedule":
            return requests.get(f"{BACKEND_URL}/api/schedule/today?user_id={args.get('user_id','')}", timeout=5).json()
        elif name == "get_traffic":
            return requests.get(f"{BACKEND_URL}/api/mobility/traffic", timeout=5).json()
        elif name == "restaurant_recommend":
            return requests.post(f"{BACKEND_URL}/api/dining/recommend", json={
                "user_id": args.get("user_id",""), "latitude": 39.925, "longitude": 116.59,
                "cuisine": args.get("cuisine"), "scene": args.get("scene"),
            }, timeout=8).json()
        elif name == "nearby_facilities":
            return requests.get(f"{BACKEND_URL}/api/mobility/nearby", params={
                "lat": args.get("lat",39.925), "lon": args.get("lon",116.59),
                "facility_type": args.get("facility_type","hospital"),
            }, timeout=5).json()
        elif name == "weather_alerts":
            return requests.get(f"{BACKEND_URL}/api/weather/alerts", timeout=5).json()
        elif name == "get_outfit":
            return requests.get(f"{BACKEND_URL}/api/outfit/suggest?user_id={args.get('user_id','')}", timeout=5).json()
        elif name == "weather_forecast":
            return requests.get(f"{BACKEND_URL}/api/weather/forecast", timeout=5).json()
        return {}
    except:
        return {}


def _detect_events(old: dict, new: dict) -> list:
    """检测 WorldState 变化，返回结构化事件列表"""
    events = []
    if not old or not new:
        return events

    # 天气预警
    old_alerts = [a.get('type','') if isinstance(a,dict) else str(a) for a in old.get("weather",{}).get("alerts",[])]
    new_alerts = [a.get('type','') if isinstance(a,dict) else str(a) for a in new.get("weather",{}).get("alerts",[])]
    added_alerts = [a for a in new_alerts if a not in old_alerts]
    if added_alerts:
        events.append({
            "id": f"alert_{'_'.join(added_alerts)}",
            "type": "weather_alert",
            "severity": "critical",
            "data": new.get("weather",{}),
            "users": ["white_collar","parent","student"],
        })

    # 健康事件
    old_health = set(old.get("health_events",{}).keys())
    new_health = set(new.get("health_events",{}).keys())
    for hk in (new_health - old_health):
        he = new["health_events"][hk]
        uid_map = {"parent": "parent", "student": "student", "white_collar": "white_collar"}
        events.append({
            "id": f"health_{hk}",
            "type": "health_event",
            "severity": "critical",
            "data": he,
            "users": [uid_map.get(he.get("user_id",""), "white_collar")],
        })

    # 航班延误
    for fid, f in new.get("flights",{}).items():
        old_status = old.get("flights",{}).get(fid,{}).get("status","")
        if f.get("status") == "delayed" and old_status != "delayed":
            events.append({
                "id": f"flight_{fid}",
                "type": "flight_delay",
                "severity": "high",
                "data": f,
                "users": ["student"],  # 小晴出行最多
            })

    # 极端天气（AQI>200 / 温度>38 / 温度<-10）
    w = new.get("weather",{})
    if w.get("aqi",0) > 200 and old.get("weather",{}).get("aqi",0) <= 200:
        events.append({
            "id": "aqi_high",
            "type": "bad_air",
            "severity": "high",
            "data": w,
            "users": ["white_collar","parent","student"],
        })
    if w.get("temperature",20) > 38 and old.get("weather",{}).get("temperature",20) <= 38:
        events.append({
            "id": "temp_high",
            "type": "extreme_heat",
            "severity": "high",
            "data": w,
            "users": ["white_collar","parent","student"],
        })

    # 路况极端拥堵
    t = new.get("traffic",{})
    if t.get("citywide_congestion",0) > 0.85 and old.get("traffic",{}).get("citywide_congestion",0) <= 0.85:
        events.append({
            "id": "traffic_extreme",
            "type": "traffic_crisis",
            "severity": "high",
            "data": t,
            "users": ["white_collar","parent","student"],
        })

    # 地铁故障
    metro = t.get("metro_disruption")
    if metro and not old.get("traffic",{}).get("metro_disruption"):
        events.append({
            "id": "metro_down",
            "type": "metro_disruption",
            "severity": "high",
            "data": metro,
            "users": ["white_collar","parent","student"],
        })

    return events


def _assess_and_respond(event: dict):
    """对一个事件：评估→规划→执行→通知"""
    etype = event["type"]

    # 选择主用户
    uid = event["users"][0] if event["users"] else "white_collar"

    # 1. 收集上下文
    ctx = {}
    ctx["weather"] = _tool_call("get_weather", {})
    ctx["schedule"] = _tool_call("get_schedule", {"user_id": uid})
    ctx["traffic"] = _tool_call("get_traffic", {})

    if etype in ("weather_alert", "bad_air", "extreme_heat"):
        ctx["outfit"] = _tool_call("get_outfit", {"user_id": uid})
        ctx["forecast"] = _tool_call("weather_forecast", {})
    if etype in ("weather_alert",):
        ctx["alerts"] = _tool_call("weather_alerts", {})
    if etype == "health_event":
        he = event["data"]
        facility = "pharmacy"
        if "fever" in str(he.get("event_type","")):
            facility = "hospital"
        elif "pet" in str(he.get("event_type","")):
            facility = "pet_hospital"
        ctx["nearby"] = _tool_call("nearby_facilities", {
            "lat": 39.925, "lon": 116.59, "facility_type": facility
        })

    # 2. 让 LLM 生成全流程应对方案
    prompt = _build_assessment_prompt(etype, event["data"], ctx, uid)
    plan = _call_llm(
        "你是全天候私人管家。你的用户正面临突发状况，请快速评估并给出全流程应对方案。"
        "必须覆盖：1)当务之急 2)并行处理线 3)后续跟进。"
        "每条用 emoji 分行，具体可操作，不超 300 字。绝不提工具名或代码。",
        prompt,
        max_tokens=500
    )
    if not plan:
        plan = _fallback_plan(etype, event["data"], ctx)

    # 3. 推送通知
    import heartbeat as hb
    hb.add_notification("alert", plan, uid, "cross-skill")

    # 4. 如果是严重事件，给其他用户也推送简化版
    if event["severity"] == "critical" and len(event["users"]) > 1:
        for other_uid in event["users"][1:]:
            brief = f"⚠️ {event['data'].get('condition','突发情况')}，请注意安全。需要帮助随时叫我。"
            hb.add_notification("alert", brief, other_uid, "cross-skill")


def _build_assessment_prompt(etype: str, data: dict, ctx: dict, uid: str) -> str:
    """构建 LLM 评估 prompt"""
    w = ctx.get("weather",{})
    t = ctx.get("traffic",{})
    s = ctx.get("schedule",{})

    base = f"当前用户：{uid}\n"
    if w: base += f"天气：{w.get('condition','?')} {w.get('temperature',20)}°C AQI{w.get('aqi','?')}\n"
    if t: base += f"路况：拥堵{t.get('citywide_congestion',0.3)}\n"
    if s: base += f"日程：{len(s.get('schedules',[]))}项\n"

    if etype == "weather_alert":
        alert_names = [a.get('type','') if isinstance(a,dict) else str(a) for a in w.get('alerts',[])]
        o = ctx.get("outfit",{})
        f = ctx.get("forecast",{})
        base += f"\n触发：{', '.join(alert_names)}预警！\n"
        if o: base += f"当前穿搭建议：{o.get('base_suggestion','')}\n"
        if f: base += f"未来天气：{json.dumps(f, ensure_ascii=False)[:200]}\n"
        base += "\n请给出全流程应对：1)穿搭调整 2)出行方式切换 3)是否改外卖 4)居家提醒（关窗收衣）5)如果有老人小孩特别注意"

    elif etype == "bad_air":
        o = ctx.get("outfit",{})
        base += f"\n触发：AQI爆表>{data.get('aqi',0)}\n"
        if o: base += f"穿搭建议：{o.get('base_suggestion','')}\n"
        base += "\n请给出：1)口罩防护 2)建议改地铁/取消户外 3)关窗+空气净化器 4)老人小孩特别提醒"

    elif etype == "extreme_heat":
        o = ctx.get("outfit",{})
        base += f"\n触发：极端高温{data.get('temperature',38)}°C\n"
        if o: base += f"穿搭建议：{o.get('base_suggestion','')}\n"
        base += "\n请给出：1)防暑降温 2)轻薄穿搭 3)多喝水提醒 4)避免户外暴晒"

    elif etype == "health_event":
        pe = data.get("person","")
        et = data.get("event_type","")
        nearby = ctx.get("nearby",{})
        base += f"\n触发：{pe}{et}\n"
        if nearby: base += f"最近医疗：{json.dumps(nearby, ensure_ascii=False)[:300]}\n"
        base += f"\n请给出：1)最近的医疗资源 2)叫车安排 3)需要准备什么 4)通知谁 5)后续恢复建议。语气温暖果断。"

    elif etype == "flight_delay":
        base += f"\n触发：{data.get('flight_id','')} {data.get('route','')} 延误{data.get('delay_minutes','?')}分钟\n"
        base += "\n请给出：1)延误险理赔 2)高铁替代 3)接机/酒店通知 4)时间重规划"

    elif etype == "traffic_crisis":
        base += f"\n触发：全城拥堵{data.get('citywide_congestion',0.9)}\n"
        base += "\n请给出：1)建议改地铁 2)评估迟到风险 3)通知相关人"

    elif etype == "metro_disruption":
        base += f"\n触发：{data.get('line','')} {data.get('station','')} {data.get('reason','')} 延误{data.get('delay_min','?')}分\n"
        base += "\n请给出：1)替代方案(打车/骑行/换乘) 2)迟到评估 3)通知公司和同事"

    return base


def _fallback_plan(etype: str, data: dict, ctx: dict) -> str:
    """LLM 不可用时的降级方案"""
    plans = {
        "weather_alert": "⚠️ 天气预警！\n👔 调整穿搭，带伞/口罩\n🚇 建议改地铁出行\n🥡 午餐考虑外卖\n🪟 关好门窗，收阳台衣物",
        "bad_air": "😷 AQI爆表！\n😷 出门必戴N95\n🚇 改地铁，别骑车\n🪟 关窗+空气净化器\n👶 老人小孩减少外出",
        "extreme_heat": "☀️ 极端高温！\n👕 轻薄透气穿搭\n💧 多喝水，注意防暑\n🚫 避免户外活动",
        "health_event": "🚨 健康事件！\n🏥 已查找最近医疗资源\n🚕 建议叫车前往\n💊 带上证件和医保卡\n👨‍👩‍👧 通知家人",
        "flight_delay": "✈️ 航班延误！\n📋 开延误证明\n🚄 查高铁替代\n🏨 通知酒店改时间\n💰 延误险理赔",
        "traffic_crisis": "🚗 全城拥堵！\n🚇 强烈建议地铁\n⏰ 预估至少多花30分钟\n📞 提前通知迟到",
        "metro_disruption": "🚇 地铁故障！\n🚕 打车替代方案\n🚲 骑行+换乘也可\n⏰ 评估迟到风险",
    }
    return plans.get(etype, "⚠️ 检测到异常，请查看详情。")


def guardian_loop():
    global _last_snapshot, _running, _event_history
    print("[GUARDIAN] v2 started — full autonomous event response (tick 60s)")
    _last_snapshot = _snapshot()
    _running = True

    while _running:
        try:
            time.sleep(60)
            new_snap = _snapshot()
            if not new_snap:
                continue

            events = _detect_events(_last_snapshot, new_snap)
            for evt in events:
                # 避免重复处理
                eid = evt["id"]
                if eid in _event_history:
                    if time.time() - _event_history[eid] < 3600:  # 1小时内不重复
                        continue
                _event_history[eid] = time.time()

                print(f"[GUARDIAN] Event: {evt['type']} ({evt['severity']}) → assessing...")
                _assess_and_respond(evt)

            _last_snapshot = new_snap

            # 清理过期历史
            cutoff = time.time() - 7200
            _event_history = {k: v for k, v in _event_history.items() if v > cutoff}

        except Exception as e:
            print(f"[GUARDIAN] Error: {e}")
            time.sleep(10)


def start_guardian(backend_url="http://localhost:8000", api_key="", base_url="https://api.deepseek.com/v1", butler_dir="/app/butler"):
    init_config(backend_url, api_key, base_url, butler_dir)
    t = threading.Thread(target=guardian_loop, daemon=True)
    t.start()
    print(f"[GUARDIAN] Thread started")
    return t
