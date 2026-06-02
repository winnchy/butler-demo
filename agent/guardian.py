"""
Guardian — 事件驱动自主响应引擎
持续监听 WorldState 变化，检测到异常事件时主动调 LLM 生成管家推送
"""

import time
import threading
import requests
import json
import os

BACKEND_URL = "http://localhost:8000"
OPENAI_API_KEY = ""
OPENAI_BASE_URL = "https://api.deepseek.com/v1"

# 上一次快照（用于检测变化）
_last_snapshot = {}
_running = False


def init_config(backend_url: str, api_key: str, base_url: str):
    global BACKEND_URL, OPENAI_API_KEY, OPENAI_BASE_URL
    BACKEND_URL = backend_url
    OPENAI_API_KEY = api_key
    OPENAI_BASE_URL = base_url


def _snapshot() -> dict:
    """获取当前 WorldState 快照"""
    try:
        r = requests.get(f"{BACKEND_URL}/admin/state", timeout=5)
        return r.json()
    except:
        return {}


def _detect_changes(old: dict, new: dict) -> list:
    """对比快照，返回检测到的事件列表"""
    events = []
    if not old or not new:
        return events

    # 1. 天气预警变化
    old_alerts = old.get("weather", {}).get("alerts", [])
    new_alerts = new.get("weather", {}).get("alerts", [])
    for a in new_alerts:
        a_type = a.get("type", "") if isinstance(a, dict) else str(a)
        if a_type not in str(old_alerts):
            events.append({
                "type": "weather_alert",
                "severity": "high",
                "data": {"alert": a_type, "weather": new.get("weather", {})},
                "prompt": f"突发{a_type}预警！北京当前{new['weather'].get('condition','?')} {new['weather'].get('temperature','?')}°C AQI{new['weather'].get('aqi','?')}。请以管家身份，给用户推送：1)穿搭建议（需要带什么）2)出行建议（改什么方式）3)饮食建议（是否改外卖）4)居家提醒（关窗等）。输出要结构化、有人情味，不超过200字。"
            })

    # 2. 健康事件
    old_health = set(old.get("health_events", {}).keys())
    new_health = set(new.get("health_events", {}).keys())
    added_health = new_health - old_health
    for hk in added_health:
        he = new["health_events"][hk]
        events.append({
            "type": "health_event",
            "severity": "critical",
            "data": he,
            "prompt": f"健康事件：{he.get('person','家人')}{he.get('event_type','不适')}（严重程度：{he.get('severity','')}）。请以管家身份，给用户推送：1)最近的医疗资源 2)出行方式（叫车）3)需要准备什么 4)需要通知谁。语气温暖但果断，不超过200字。"
        })

    # 3. 航班变化
    old_flights = {k: v.get("status") for k, v in old.get("flights", {}).items()}
    new_flights = {k: v.get("status") for k, v in new.get("flights", {}).items()}
    for fid, status in new_flights.items():
        if old_flights.get(fid) != status and status == "delayed":
            f = new["flights"][fid]
            events.append({
                "type": "flight_delay",
                "severity": "high",
                "data": f,
                "prompt": f"航班{f.get('flight_id','')} {f.get('route','')} 延误{f.get('delay_minutes','?')}分钟（原因：{f.get('reason','')}）。请以管家身份，给用户推送：1)延误险能否理赔 2)高铁替代方案 3)接机酒店通知 4)时间重新规划。结构化分点，有人情味，不超过200字。"
            })

    # 4. 餐厅关门
    old_closure = old.get("scenario_override_active", False) and old.get("restaurant_closure_override", False)
    new_closure = new.get("scenario_override_active", False) and new.get("scenario_override", {}).get("restaurant_closure", False)
    if new_closure and not old_closure:
        events.append({
            "type": "restaurant_closure",
            "severity": "medium",
            "data": {},
            "prompt": "用户约好的餐厅临时关门了。请以管家身份，推送：1)同商圈同菜系备选 2)帮用户取号 3)道歉语气 4)步行范围内的优先。不超过200字。"
        })

    # 5. 极端拥堵 / 地铁故障
    metro_disruption = new.get("traffic", {}).get("metro_disruption")
    old_metro = old.get("traffic", {}).get("metro_disruption")
    if metro_disruption and not old_metro:
        events.append({
            "type": "metro_disruption",
            "severity": "high",
            "data": metro_disruption,
            "prompt": f"地铁{metro_disruption.get('line','')} {metro_disruption.get('station','')}站 {metro_disruption.get('reason','')}，延误{metro_disruption.get('delay_min','?')}分钟。请以管家身份，给用户推送替代出行方案：打车/共享单车/换乘其他线路，评估迟到风险，给出建议。不超过200字。"
        })

    return events


def _ask_llm(prompt: str) -> str:
    """用 DeepSeek 生成管家推送文案"""
    if not OPENAI_API_KEY:
        return _fallback_response(prompt)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

        sys = "你是全天候私人管家。用自然中文回复，结构化emoji分行，有人情味。不要暴露工具名或代码。不超过200字。"

        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=300,
            timeout=15,
        )
        return resp.choices[0].message.content or ""
    except:
        return _fallback_response(prompt)


def _fallback_response(prompt: str) -> str:
    """LLM 不可用时的降级推送"""
    if "暴雨" in prompt:
        return "⚠️ 暴雨预警！\n👔 出门带伞，穿防水鞋\n🚇 建议地铁出行\n🥡 午餐可改外卖\n🪟 记得关好门窗"
    elif "沙尘暴" in prompt:
        return "⚠️ 沙尘暴预警！AQI爆表\n😷 出门必戴N95口罩\n🚇 改地铁，别骑车\n🪟 关紧门窗"
    elif "延误" in prompt:
        return "⚠️ 航班延误！\n📋 记得开延误证明\n🚄 可查高铁替代\n🏨 通知酒店改入住时间"
    elif "发烧" in prompt:
        return "🚨 别急，我帮你：\n🏥 最近儿科急诊2.3km\n🚕 帮你叫车\n💊 物理降温: 温水擦身\n👨‍👩‍👧 提醒家人请假"
    elif "关门" in prompt:
        return "😔 餐厅临时歇业了\n🔍 帮你找同商圈替代\n🥡 步行3分钟有家评分不错的\n要帮你取号吗？"
    elif "地铁" in prompt:
        return "🚇 地铁故障！\n🚕 建议打车（等12分钟）\n🚲 骑行+换乘也是选项\n⏰ 迟到约15分钟"
    elif "宠物" in prompt:
        return "🐕 别慌！\n🏥 最近宠物医院2.3km\n🚕 帮你叫车\n👵 让公婆帮忙看下乐乐\n📞 通知阿彬"
    return "检测到异常，但AI暂不可用。请查看管理面板了解详情。"


def guardian_loop():
    """主循环：每分钟对比快照，检测事件 → 调 LLM → 推送"""
    global _last_snapshot, _running
    print("[GUARDIAN] Event monitor started (tick every 60s)")

    # 导入 heartbeat 模块来推送通知
    import heartbeat as hb

    _last_snapshot = _snapshot()
    _running = True

    while _running:
        try:
            time.sleep(60)
            new_snap = _snapshot()
            if not new_snap:
                continue

            events = _detect_changes(_last_snapshot, new_snap)
            for evt in events:
                print(f"[GUARDIAN] Detected: {evt['type']} (severity: {evt['severity']})")
                llm_response = _ask_llm(evt["prompt"])
                hb.add_notification(
                    "alert" if evt["severity"] in ("critical", "high") else "schedule",
                    llm_response,
                    "white_collar",  # default; could be context-aware
                    "cross-skill"
                )

            _last_snapshot = new_snap
        except Exception as e:
            print(f"[GUARDIAN] Error: {e}")
            time.sleep(10)


def start_guardian(backend_url: str = "http://localhost:8000", api_key: str = "", base_url: str = "https://api.deepseek.com/v1"):
    """启动事件守护线程"""
    init_config(backend_url, api_key, base_url)
    t = threading.Thread(target=guardian_loop, daemon=True)
    t.start()
    print(f"[GUARDIAN] Thread started (monitoring {backend_url})")
    return t
