"""穿搭管家 + 天气 API"""

import random
from datetime import datetime
from fastapi import APIRouter
import main
from config import get_seasonal_weather_base

router = APIRouter()


@router.get("/weather/current")
def current_weather():
    """当前天气"""
    ws = main.world_state
    if not ws:
        return {"error": "WorldState not initialized"}
    w = ws.get_weather()
    return {
        "temperature": w["current_temp"],
        "feels_like": w["feels_like"],
        "condition": w["condition"],
        "humidity": w["humidity"],
        "wind_direction": w["wind_direction"],
        "wind_level": w["wind_level"],
        "aqi": w["aqi"],
        "aqi_level": w["aqi_level"],
        "alerts": w.get("alerts", []),
        "updated_at": w["last_updated"],
    }


@router.get("/weather/forecast")
def weather_forecast():
    """天气预报"""
    ws = main.world_state
    if not ws:
        return {"error": "WorldState not initialized"}
    w = ws.get_weather()
    return {
        "hourly": w.get("hourly", []),
        "daily": w.get("daily", []),
        "updated_at": w["last_updated"],
    }


@router.get("/weather/alerts")
def weather_alerts():
    """天气预警"""
    ws = main.world_state
    if not ws:
        return {"alerts": []}
    return {"alerts": ws.weather.alerts}


@router.get("/outfit/suggest")
def outfit_suggest(user_id: str = "white_collar"):
    """穿搭建议（基于天气 + 用户身份）"""
    ws = main.world_state
    if not ws:
        return {"error": "WorldState not initialized"}

    temp = ws.weather.current_temp
    cond = ws.weather.condition

    # 基于温度的基础建议
    if temp >= 30:
        base = "轻薄透气夏装"
        items = ["短袖T恤", "短裤/短裙", "防晒衣", "墨镜"]
    elif temp >= 25:
        base = "清凉夏装"
        items = ["短袖/衬衫", "薄长裤/裙子", "防晒外套"]
    elif temp >= 18:
        base = "春秋过渡装"
        items = ["长袖薄衫", "薄外套", "长裤"]
    elif temp >= 10:
        base = "春秋装"
        items = ["卫衣/毛衣", "夹克", "长裤"]
    elif temp >= 0:
        base = "冬装"
        items = ["厚外套/羽绒服", "毛衣", "围巾"]
    else:
        base = "严冬装"
        items = ["羽绒服", "保暖内衣", "帽子围巾手套"]

    # 天气调整
    if cond in ["暴雨", "大雨", "雷暴", "中雨", "小雨"]:
        items.append("雨伞/雨衣")
        items.append("防水鞋")
    if cond in ["大风"]:
        items.append("防风外套")
    if cond == "晴" and temp > 25:
        items.append("防晒霜 SPF30+")

    return {
        "user_id": user_id,
        "current_temp": temp,
        "condition": cond,
        "base_suggestion": base,
        "recommended_items": items,
        "tip": f"今日{cond}，气温{temp}°C，" + ("注意防晒" if temp > 30 and cond == "晴" else "注意保暖" if temp < 10 else "祝您舒适"),
    }


@router.get("/outfit/alert")
def outfit_alert(user_id: str = "white_collar"):
    """突发天气穿搭预警"""
    ws = main.world_state
    if not ws:
        return {"alerts": []}

    alerts = []
    cond = ws.weather.condition
    temp = ws.weather.current_temp

    if cond in ["暴雨", "雷暴"]:
        alerts.append({"type": "rain", "message": "突发暴雨！建议穿防水鞋、带伞，避免浅色衣物"})
    if temp > 35:
        alerts.append({"type": "heat", "message": "高温预警！建议轻薄浅色衣物、佩戴遮阳帽"})
    if cond in ["大风"] and temp < 10:
        alerts.append({"type": "wind_chill", "message": "大风降温！建议添加防风外套"})

    return {"alerts": alerts, "updated_at": datetime.now().isoformat()}


@router.get("/weather/trend")
def weather_trend(city: str = "北京", days: int = 14):
    """长期天气趋势（换季检测用）"""
    ws = main.world_state
    if not ws:
        return {"error": "WorldState not initialized"}

    w = ws.get_weather()
    now = datetime.now()
    month = now.month
    base = get_seasonal_weather_base(month)

    # 模拟过去7天均温（略低于当前）
    past_7d_avg = round(w["current_temp"] - random.uniform(2, 6), 1)
    # 未来14天均温（略高于当前，5-6月趋势升温）
    future_14d_avg = round(w["current_temp"] + random.uniform(2, 8), 1)

    # 判断趋势
    diff = future_14d_avg - past_7d_avg
    if diff > 5:
        trend = "warming"
        is_shift = past_7d_avg < 22 <= future_14d_avg  # 入夏阈值
    elif diff < -5:
        trend = "cooling"
        is_shift = past_7d_avg > 10 >= future_14d_avg   # 入冬阈值
    else:
        trend = "stable"
        is_shift = False

    current_season = "春季" if month in [3, 4, 5] else "夏季" if month in [6, 7, 8] else "秋季" if month in [9, 10, 11] else "冬季"
    next_season = "夏季" if current_season == "春季" else "秋季" if current_season == "夏季" else "冬季" if current_season == "秋季" else "春季"

    return {
        "city": city,
        "past_7d_avg_temp": past_7d_avg,
        "future_14d_avg_temp": future_14d_avg,
        "temp_trend": trend,
        "is_season_shift": is_shift,
        "current_season": current_season,
        "next_season": next_season if is_shift else None,
        "confidence": round(random.uniform(0.7, 0.95), 2) if is_shift else 0.5,
        "detail": f"过去7天日均温{past_7d_avg}°C，未来14天预计{'升至' if trend == 'warming' else '降至'}{future_14d_avg}°C",
        "suggestion": "建议将厚棉服收纳，取出薄外套、防晒衣" if is_shift and trend == "warming" else "",
    }


@router.get("/wardrobe")
def wardrobe(user_id: str = "white_collar"):
    """用户衣橱查询（模拟）"""
    wardrobes = {
        "white_collar": {
            "tops": ["白衬衫x3", "条纹T恤x2", "针织开衫", "西装外套", "风衣", "羊绒大衣"],
            "bottoms": ["黑色西裤x2", "牛仔裤", "A字裙", "阔腿裤"],
            "dresses": ["小黑裙", "碎花连衣裙", "衬衫裙"],
            "shoes": ["黑色高跟鞋", "白色运动鞋", "平底乐福鞋", "踝靴"],
            "missing": ["夏季防晒衣", "薄围巾（换季防风）", "果果运动鞋（该换码了）"],
        },
        "parent": {
            "tops": ["纯棉T恤x5", "卫衣x3", "哺乳衫x2", "轻羽绒", "冲锋衣"],
            "bottoms": ["运动裤x3", "牛仔裤x2", "宽松休闲裤x2"],
            "dresses": ["宽松连衣裙x2", "针织裙"],
            "shoes": ["运动鞋x2", "平底鞋", "雪地靴"],
            "missing": ["亲子装（和乐乐配套）", "乐乐防晒帽", "布丁雨衣"],
        },
        "student": {
            "tops": ["卫衣x3", "格子衬衫", "牛仔外套", "基础款T恤x5"],
            "bottoms": ["牛仔裤x2", "运动裤", "百褶裙"],
            "dresses": [],
            "shoes": ["帆布鞋", "运动鞋", "马丁靴"],
            "missing": ["小白鞋替换（旧的那双底磨平了）", "第二件面试衬衫", "更厚的羽绒服（寒假回家用）", "风衣扣子需缝"],
        },
    }
    return wardrobes.get(user_id, wardrobes["white_collar"])
