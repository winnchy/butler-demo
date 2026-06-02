"""日程管家 + 记忆管理 API"""

import random
from datetime import datetime, timedelta
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

import shared as main

router = APIRouter()


class ScheduleCreate(BaseModel):
    user_id: str
    title: str
    date: str          # YYYY-MM-DD
    time: str = "09:00"
    end_time: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    reminder_minutes: int = 30


class MemorySave(BaseModel):
    user_id: str
    key: str
    value: str
    category: str = "general"


# ---- 模拟数据存储 ----

_schedules: dict = {
    "white_collar": [
        {"id": 1, "title": "晨会", "date": "2026-06-01", "time": "09:00", "end_time": "10:00",
         "location": "公司会议室", "reminder_minutes": 15},
        {"id": 2, "title": "接待王总午餐", "date": "2026-06-01", "time": "12:00", "end_time": "13:30",
         "location": "金悦(金融街购物中心店)", "notes": "深圳合作方同行，需包厢", "reminder_minutes": 60},
    ],
    "parent": [
        {"id": 3, "title": "乐乐体检", "date": "2026-06-02", "time": "08:30", "end_time": "10:00",
         "location": "首都儿科研究所", "reminder_minutes": 60},
    ],
    "student": [
        {"id": 4, "title": "秋招笔试", "date": "2026-06-03", "time": "09:00", "end_time": "11:00",
         "location": "中关村软件园", "notes": "带身份证+2B铅笔", "reminder_minutes": 120},
    ],
}

_memories: dict = {
    "white_collar": [
        {"key": "favorite_cuisine", "value": "粤菜、日料、清淡火锅、东南亚菜", "category": "dining"},
        {"key": "spicy_level", "value": "medium", "category": "dining"},
        {"key": "dislike", "value": "不吃香菜", "category": "dining"},
        {"key": "commute_mode", "value": "地铁为主（45%），大刘顺路送（25%），自己开（20%），打车（10%）", "category": "mobility"},
        {"key": "car_plate", "value": "京N·模拟车牌（尾号5，周五限行）", "category": "mobility"},
        {"key": "energy_type", "value": "汽油", "category": "mobility"},
        {"key": "wedding_anniversary", "value": "6月18日", "category": "special_dates"},
        {"key": "guoguo_peanut_allergy", "value": "果果花生过敏（严格禁止）", "category": "health"},
        {"key": "allergic_rhinitis", "value": "小琴换季过敏性鼻炎+皮肤敏感", "category": "health"},
        {"key": "parents_visit", "value": "父母（广东）每年到京1-2次，父亲高血压母亲膝盖不好", "category": "family"},
    ],
    "parent": [
        {"key": "favorite_cuisine", "value": "清淡家常菜、面食、偶尔火锅和日料", "category": "dining"},
        {"key": "spicy_level", "value": "none", "category": "dining"},
        {"key": "family_dining", "value": "全家不吃辣，需儿童座椅+婴儿辅食可选+上菜快", "category": "dining"},
        {"key": "lele_egg_allergy", "value": "乐乐蛋清过敏（严格禁止，外出用餐必确认）", "category": "health"},
        {"key": "lele_schedule", "value": "午睡13:00-15:00，晚睡20:30前", "category": "family"},
        {"key": "buding_info", "value": "柯基犬布丁3岁公，早晚遛各20分钟，不能吃巧克力/洋葱/葡萄", "category": "pets"},
        {"key": "inlaws_hypertension", "value": "公婆二人血压偏高，饮食需少盐", "category": "health"},
        {"key": "abin_overtime", "value": "阿彬（丈夫）互联网算法工程师，经常加班到22点", "category": "family"},
        {"key": "solo_parent_mode", "value": "阿彬加班时小冉独自带娃+遛狗，需就近、快速方案", "category": "family"},
    ],
    "student": [
        {"key": "favorite_cuisine", "value": "火锅、东南亚菜、辣味菜系", "category": "dining"},
        {"key": "spicy_level", "value": "high", "category": "dining"},
        {"key": "intolerance", "value": "不吃葱/香菜/蒜、不吃内脏类、羊肉膻味敏感", "category": "dining"},
        {"key": "drink", "value": "奶茶控（少糖，月配额8杯，每月20号检查）", "category": "dining"},
        {"key": "budget", "value": "午餐25-40元，月均可支配5000-6000元", "category": "dining"},
        {"key": "insomnia", "value": "每周2-3天入睡困难，压力大时加重", "category": "health"},
        {"key": "period", "value": "每月15号前后，第一天腹痛需休息", "category": "health"},
        {"key": "hometown", "value": "广东佛山，暑假/寒假回家", "category": "family"},
        {"key": "brother", "value": "弟弟小宇13岁读初一，小晴极宠弟弟", "category": "family"},
        {"key": "dance_hobby", "value": "喜欢跳舞，脚踝有旧伤需注意热身", "category": "health"},
    ],
}


@router.get("/schedule/today")
def today_schedule(user_id: str = "white_collar"):
    """今日日程"""
    today = datetime.now().strftime("%Y-%m-%d")
    items = [s for s in _schedules.get(user_id, []) if s["date"] == today]
    return {"user_id": user_id, "date": today, "schedules": items}


@router.get("/schedule/week")
def week_schedule(user_id: str = "white_collar"):
    """本周日程"""
    today = datetime.now()
    items = _schedules.get(user_id, [])
    return {"user_id": user_id, "week_start": (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d"),
            "schedules": items}


@router.get("/schedule/upcoming")
def upcoming_schedule(user_id: str = "white_collar", hours: int = 24):
    """即将到来的日程"""
    now = datetime.now()
    upcoming = []
    for s in _schedules.get(user_id, []):
        s_dt = datetime.strptime(f"{s['date']} {s['time']}", "%Y-%m-%d %H:%M")
        diff = (s_dt - now).total_seconds() / 3600
        if 0 <= diff <= hours:
            upcoming.append({**s, "in_hours": round(diff, 1)})
    return {"user_id": user_id, "upcoming": upcoming}


@router.post("/schedule/create")
def create_schedule(req: ScheduleCreate):
    """创建日程"""
    s = {
        "id": random.randint(100, 999),
        "title": req.title, "date": req.date, "time": req.time,
        "end_time": req.end_time, "location": req.location,
        "notes": req.notes, "reminder_minutes": req.reminder_minutes,
    }
    if req.user_id not in _schedules:
        _schedules[req.user_id] = []
    _schedules[req.user_id].append(s)
    return {"ok": True, "schedule": s}


@router.post("/memory/save")
def save_memory(req: MemorySave):
    """保存记忆"""
    if req.user_id not in _memories:
        _memories[req.user_id] = []
    # 更新或新增
    for m in _memories[req.user_id]:
        if m["key"] == req.key:
            m["value"] = req.value
            m["category"] = req.category
            return {"ok": True, "memory": m, "action": "updated"}
    m = {"key": req.key, "value": req.value, "category": req.category}
    _memories[req.user_id].append(m)
    return {"ok": True, "memory": m, "action": "created"}


@router.get("/memory/search")
def search_memory(user_id: str = "white_collar", keyword: str = ""):
    """搜索记忆"""
    memories = _memories.get(user_id, [])
    if keyword:
        memories = [m for m in memories if keyword in m["key"] or keyword in m["value"]]
    return {"user_id": user_id, "memories": memories}


@router.get("/special-dates")
def life_special_dates(user_id: str = "white_collar"):
    """特殊日期（来自记忆）"""
    memories = _memories.get(user_id, [])
    special = [m for m in memories if m["category"] == "special_dates"]
    health = [m for m in memories if m["category"] == "health"]

    now = datetime.now()
    return {
        "user_id": user_id,
        "special_dates": special,
        "health_tags": [h["value"] for h in health],
        "checked_at": now.isoformat(),
        # 检查是否有活跃的健康事件
        "active_health_event": (
            main.world_state.get_health_event(user_id) if main.world_state else None
        ),
    }


@router.get("/health-reminder")
def health_reminder(user_id: str = "white_collar"):
    """健康提醒"""
    health_tags = {
        "white_collar": ["久坐提醒: 每小时站起来活动一下", "饮水提醒: 今日已饮 4/8 杯"],
        "parent": ["乐乐蛋清过敏: 今日饮食注意避开蛋清制品", "布丁驱虫提醒: 本月需体内外驱虫"],
        "student": ["失眠提醒: 睡前1小时避免屏幕", "奶茶配额: 本月剩余 3/8 杯"],
    }
    ws = main.world_state
    active_event = ws.get_health_event(user_id) if ws else None

    return {
        "user_id": user_id,
        "reminders": health_tags.get(user_id, []),
        "active_health_event": active_event,
    }
