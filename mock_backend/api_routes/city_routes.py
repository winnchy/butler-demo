"""本地活动与购物管家 API: 活动/促销/跳蚤市场/亲子"""

import random
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
import shared as main

router = APIRouter()


@router.get("/events")
def city_events(city: str = "北京", type: str = "all",
                date_range: str = "weekend", budget: int = None,
                user_id: str = None, weather: str = None):
    """活动推荐"""
    ws = main.world_state
    current_weather = ws.weather.condition if ws else "晴"

    base_events = [
        {"id": 601, "name": "印象莫奈沉浸艺术展", "type": "exhibition",
         "location": "朝阳大悦城5楼", "date": "6月1日-6月20日",
         "time": "10:00-21:00", "price": {"regular": 88, "student": 49},
         "is_indoor": True, "distance_km": 2.5, "match_reason": "热门艺术展"},
        {"id": 602, "name": "三里屯周末市集", "type": "market",
         "location": "三里屯太古里南区", "date": "6月6日-6月7日",
         "time": "14:00-21:00", "price": {"regular": 0, "student": 0},
         "is_indoor": False, "distance_km": 4.0, "match_reason": "免费活动"},
        {"id": 603, "name": "国家大剧院交响音乐会", "type": "show",
         "location": "国家大剧院", "date": "6月5日",
         "time": "19:30-21:30", "price": {"regular": 280, "student": 100},
         "is_indoor": True, "distance_km": 6.0, "match_reason": "文化演出"},
        {"id": 604, "name": "故宫博物院常设展", "type": "exhibition",
         "location": "故宫博物院", "date": "长期",
         "time": "08:30-17:00", "price": {"regular": 60, "student": 30},
         "is_indoor": True, "distance_km": 8.0, "match_reason": "经典必看"},
        {"id": 605, "name": "什刹海露天音乐会", "type": "show",
         "location": "什刹海", "date": "6月7日",
         "time": "18:00-21:00", "price": {"regular": 0, "student": 0},
         "is_indoor": False, "distance_km": 5.5, "match_reason": "夏夜户外"},
    ]

    # 天气影响户外活动
    if current_weather in ["暴雨", "大雨", "雷暴", "大风"]:
        for e in base_events:
            if not e["is_indoor"]:
                e["weather_note"] = f"天气{current_weather}，户外活动可能受影响"

    # 过滤
    results = base_events
    if type != "all":
        results = [e for e in results if e["type"] == type]
    if budget is not None:
        results = [e for e in results if e["price"].get("regular", 0) <= budget]

    weather_tip = "周末天气晴好，适合户外活动"
    if current_weather in ["暴雨", "大雨", "雷暴"]:
        weather_tip = f"周末{current_weather}，建议优先选择室内活动"

    return {
        "city": city, "date_range": "本周末",
        "events": results,
        "weather_tip": weather_tip,
        "note": "模拟活动数据",
    }


@router.get("/shopping")
def shopping_promotions(city: str = "北京", category: str = "all",
                        user_id: str = None):
    """商场促销"""
    return {
        "promotions": [
            {"id": 701, "mall": "国贸商城", "promotion": "周末换季特卖 全场5折起",
             "category": "clothing", "valid_until": "2026-06-30", "distance_km": 3.0},
            {"id": 702, "mall": "朝阳大悦城", "promotion": "618年中大促 满300减50",
             "category": "all", "valid_until": "2026-06-18", "distance_km": 4.5},
            {"id": 703, "mall": "蓝色港湾", "promotion": "夏季新品上市 8折尝鲜",
             "category": "clothing", "valid_until": "2026-06-15", "distance_km": 2.0},
            {"id": 704, "mall": "西单大悦城", "promotion": "运动品牌特卖 3折起",
             "category": "sports", "valid_until": "2026-06-10", "distance_km": 6.0},
        ],
        "note": "模拟促销数据",
    }


@router.get("/flea-market")
def flea_market(city: str = "北京", category: str = "all"):
    """二手/跳蚤市场"""
    return {
        "markets": [
            {"name": "高校旧物市集", "location": "海淀五道口", "date": "6月7日",
             "time": "10:00-17:00", "items": ["二手教材", "小家电", "自行车"],
             "note": "学生友好，价格实惠"},
            {"name": "潘家园旧货市场", "location": "朝阳潘家园", "date": "每周六日",
             "time": "06:00-17:00", "items": ["古玩", "旧书", "手串"],
             "note": "北京最大古玩市场"},
        ],
        "note": "模拟跳蚤市场数据",
    }


@router.get("/kids")
def kids_activities(city: str = "北京", age_range: str = "0-3"):
    """亲子活动"""
    return {
        "activities": [
            {"name": "亲子烘焙体验课", "location": "蓝色港湾", "age_range": "3-8岁",
             "price": 128, "date": "6月6日", "note": "需预约"},
            {"name": "小小科学家实验课", "location": "中国科技馆", "age_range": "5-12岁",
             "price": 88, "date": "6月7日", "note": "含材料费"},
            {"name": "儿童剧《三只小猪》", "location": "中国儿童艺术剧院", "age_range": "2-6岁",
             "price": 120, "date": "6月6日-6月7日", "note": "适合低龄宝宝"},
        ],
        "note": "模拟亲子活动数据",
    }
