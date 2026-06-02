"""
HEARTBEAT 调度器 — 7x24 后台管家
按时间表主动推送 + 监听事件触发跨 Skill 联动
"""

import time
import threading
import requests
from datetime import datetime, timedelta

BACKEND_URL = "http://localhost:8000"
BUTLER_DIR = "/app/butler"

# 通知存储（内存，重启丢失）
notifications = []  # [{id, time, type, message, user_id, skill, read}]
MAX_NOTIFICATIONS = 50

# 上次触发记录（避免重复）
_last_triggered = {}


def init_config(backend_url: str, butler_dir: str):
    global BACKEND_URL, BUTLER_DIR
    BACKEND_URL = backend_url
    BUTLER_DIR = butler_dir


def add_notification(notif_type: str, message: str, user_id: str = "white_collar", skill: str = ""):
    """添加一条通知"""
    global notifications
    n = {
        "id": str(int(time.time() * 1000)),
        "time": datetime.now().strftime("%H:%M"),
        "type": notif_type,     # schedule / event / alert / reminder
        "message": message,
        "user_id": user_id,
        "skill": skill,
        "read": False,
    }
    notifications.insert(0, n)
    if len(notifications) > MAX_NOTIFICATIONS:
        notifications = notifications[:MAX_NOTIFICATIONS]
    print(f"[HEARTBEAT] Push: [{notif_type}] {message[:60]}")
    return n


def _should_trigger(key: str, cooldown_minutes: int = 5) -> bool:
    """检查是否过了冷却时间"""
    now = time.time()
    if key in _last_triggered:
        if now - _last_triggered[key] < cooldown_minutes * 60:
            return False
    _last_triggered[key] = now
    return True


def _get_weather():
    try:
        r = requests.get(f"{BACKEND_URL}/api/weather/current", timeout=5)
        return r.json()
    except:
        return {}


def _get_alerts():
    try:
        r = requests.get(f"{BACKEND_URL}/api/weather/alerts", timeout=5)
        return r.json().get("alerts", [])
    except:
        return []


def _get_traffic():
    try:
        r = requests.get(f"{BACKEND_URL}/api/mobility/traffic", timeout=5)
        return r.json()
    except:
        return {}


def _get_user_schedule(user_id: str):
    try:
        r = requests.get(f"{BACKEND_URL}/api/schedule/today?user_id={user_id}", timeout=5)
        return r.json().get("schedules", [])
    except:
        return []


def _get_restaurant_recommend(user_id: str):
    try:
        r = requests.post(f"{BACKEND_URL}/api/dining/recommend", json={
            "user_id": user_id, "latitude": 39.925, "longitude": 116.59
        }, timeout=8)
        return r.json().get("recommendations", [])[:3]
    except:
        return []


def _get_events(user_id: str):
    try:
        r = requests.get(f"{BACKEND_URL}/api/city/events?type=all&user_id={user_id}", timeout=5)
        return r.json().get("events", [])[:3]
    except:
        return []


def _get_outfit(user_id: str):
    try:
        r = requests.get(f"{BACKEND_URL}/api/outfit/suggest?user_id={user_id}", timeout=5)
        return r.json()
    except:
        return {}


def _check_special_dates(user_id: str):
    try:
        r = requests.get(f"{BACKEND_URL}/api/special-dates?user_id={user_id}", timeout=5)
        return r.json().get("dates", [])
    except:
        return []


# ================================================================
#  定时任务
# ================================================================

def run_scheduled_tasks(now: datetime, hour: int, minute: int, weekday: int):
    """按 HEARTBEAT.md 时间表执行定时任务"""
    users = ["white_collar", "parent", "student"]

    # 07:00 — 早安推送：天气 + 穿搭 + 通勤
    if hour == 7 and minute < 5 and _should_trigger("morning", 20):
        for uid in users:
            w = _get_weather()
            t = _get_traffic()
            o = _get_outfit(uid)
            s = _get_user_schedule(uid)
            lines = [f"☀️ 早上好！"]
            if w:
                lines.append(f"🌤 {w.get('condition','?')} {w.get('temperature',w.get('current_temp','?'))}°C AQI{w.get('aqi','?')}")
            if t:
                lines.append(f"🚗 路况：拥堵指数{t.get('citywide_congestion','?')}")
            if o:
                lines.append(f"👔 {o.get('base_suggestion','?')}: {', '.join(o.get('recommended_items',[])[:3])}")
            if s:
                lines.append(f"📌 今日{s[0]['time']} {s[0]['title']}")
            add_notification("schedule", "\n".join(lines), uid, "outfit+mobility")

    # 11:30 — 午餐推荐
    if hour == 11 and 28 <= minute <= 32 and _should_trigger("lunch", 20):
        for uid in users:
            recs = _get_restaurant_recommend(uid)
            if recs:
                r = recs[0]
                msg = f"🍽️ 午饭时间～推荐：{r['name']} ⭐{r.get('rating','?')} ¥{r.get('avg_price','?')} {r.get('cuisine','')} | {r.get('distance_km','?')}km | {r.get('status','')}"
                add_notification("schedule", msg, uid, "dining")

    # 17:30 — 晚高峰通勤 + 晚餐
    if hour == 17 and 28 <= minute <= 32 and _should_trigger("evening", 20):
        for uid in users:
            t = _get_traffic()
            msg_parts = ["🌆 下班时间到！"]
            if t:
                msg_parts.append(f"🚗 晚高峰拥堵{t.get('citywide_congestion','?')}")
            add_notification("schedule", "\n".join(msg_parts), uid, "mobility")

    # 21:00 — 明日天气 + 穿搭预告
    if hour == 21 and minute < 5 and _should_trigger("night", 20):
        for uid in users:
            o = _get_outfit(uid)
            if o:
                msg = f"🌙 明天穿搭建议：{o.get('base_suggestion','?')} — {', '.join(o.get('recommended_items',[])[:3])}"
                add_notification("schedule", msg, uid, "outfit")

    # 周五 18:00 — 周末活动推荐
    if weekday == 4 and hour == 18 and minute < 5 and _should_trigger("weekend", 40):
        for uid in users:
            events = _get_events(uid)
            if events:
                e = events[0]
                msg = f"🎉 周末啦！推荐：{e['name']} 📍{e.get('location','')} 📅{e.get('date','')} ¥{e.get('price',{}).get('regular','?') if isinstance(e.get('price'),dict) else e.get('price','?')}"
                add_notification("schedule", msg, uid, "city")

    # 特殊日期检测 — 每天 8:00 检查
    if hour == 8 and minute < 5 and _should_trigger("special_dates", 60):
        for uid in users:
            dates = _check_special_dates(uid)
            for d in dates:
                if d.get("days_left", 999) <= 3:
                    msg = f"📅 提醒：{d.get('name','')} 还有{d.get('days_left',0)}天！该准备了～"
                    add_notification("reminder", msg, uid, "life")


# ================================================================
#  事件驱动监听
# ================================================================

def run_event_monitors():
    """监听 WorldState 事件，跨 Skill 联动"""
    users = ["white_collar", "parent", "student"]

    # 1. 天气预警 → outfit + mobility + dining 联动
    alerts = _get_alerts()
    if alerts and _should_trigger("weather_alert", 15):
        for uid in users:
            for a in alerts[:2]:
                a_type = a.get('type', '')
                level = a.get('level', '')
                msg = f"⚠️ {a_type}{level}预警！"
                if a_type in ("暴雨", "大雨", "沙尘暴"):
                    msg += "\n👔 记得带伞/戴口罩 | 🚇 建议地铁出行 | 🥡 午餐可改外卖"
                elif a_type in ("高温",):
                    msg += "\n👔 建议轻薄透气 | 💧 多喝水 | 🚇 避免户外暴晒"
                elif a_type in ("大风",):
                    msg += "\n👔 注意防风 | 🚲 不建议骑行 | 🌬 关好门窗"
                add_notification("alert", msg, uid, "cross-skill")

    # 2. 路况异常 → mobility 告警
    t = _get_traffic()
    if t and t.get('citywide_congestion', 0) > 0.8 and _should_trigger("traffic_alert", 30):
        for uid in users:
            msg = f"🚨 全城严重拥堵（{t.get('citywide_congestion',0)}）！建议改地铁出行，预计比驾车快20分钟以上"
            add_notification("alert", msg, uid, "mobility")


# ================================================================
#  主循环
# ================================================================

def heartbeat_loop():
    """主循环：每分钟执行一次"""
    print("[HEARTBEAT] Scheduler started (tick every 60s)")
    while True:
        try:
            now = datetime.now()
            run_scheduled_tasks(now, now.hour, now.minute, now.weekday())
            run_event_monitors()
        except Exception as e:
            print(f"[HEARTBEAT] Error: {e}")
        time.sleep(60)


def start_heartbeat(backend_url: str = "http://localhost:8000", butler_dir: str = "/app/butler"):
    """启动后台心跳线程"""
    init_config(backend_url, butler_dir)
    t = threading.Thread(target=heartbeat_loop, daemon=True)
    t.start()
    print(f"[HEARTBEAT] Thread started (BACKEND_URL={backend_url})")
    return t
