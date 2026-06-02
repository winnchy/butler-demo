"""餐饮管家 API: 推荐/排队/监控/紧急方案/评价"""

import random
import math
from typing import Optional, List
from fastapi import APIRouter, Query
from pydantic import BaseModel

import global_state as main
from config import haversine, match_cuisine, safe_float

router = APIRouter()

# ---- 请求模型 ----

class RecommendRequest(BaseModel):
    user_id: str
    companion_ids: Optional[List[str]] = None
    people_count: int = 1
    scene: Optional[str] = None
    date_type: Optional[str] = None
    budget_per_person: Optional[int] = None
    cuisine: Optional[str] = None
    taste_profiles: Optional[List[dict]] = None
    health_tags: Optional[List[str]] = None
    must_have: Optional[List[str]] = None
    avoid_ingredients: Optional[List[str]] = None
    allow_compromise: bool = True
    travel_mode: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class EmergencyRequest(BaseModel):
    user_id: str
    original_restaurant_id: Optional[int] = 0   # 可选，用于查找同品牌/同商圈备选
    emergency_type: str     # weather, full, late, closure
    current_lat: float
    current_lng: float
    people_count: int = 1
    has_child: bool = False
    time_buffer_min: int = 15


# ---- 路由 ----

@router.post("/recommend")
def dining_recommend(req: RecommendRequest):
    """智能餐厅推荐"""
    restaurants = main.STATIC_DATA.get("restaurants", [])

    # 过滤
    results = []
    for r in restaurants:
        score = 0
        reasons = []

        # 菜系匹配（模糊）
        if req.cuisine:
            if req.cuisine in r.get("cuisine", "") or req.cuisine in r.get("sub_cuisine", ""):
                score += 30
                reasons.append(f"符合菜系偏好({req.cuisine})")

        # 预算匹配
        price = r.get("avg_price", 100)
        if req.budget_per_person:
            if price <= req.budget_per_person * 1.2:
                score += 20
                reasons.append("在预算内")
            elif price <= req.budget_per_person * 1.5:
                score += 10
                reasons.append("略超预算但合理")

        # 距离评分
        if req.latitude and req.longitude:
            dist = haversine(req.longitude, req.latitude,
                            r.get("longitude", 0), r.get("latitude", 0))
            if dist < 1000:
                score += 25
                reasons.append("步行可达")
            elif dist < 3000:
                score += 15
                reasons.append("距离适中")
            elif dist < 8000:
                score += 5
        else:
            dist = random.randint(500, 8000)

        # 健康标签过滤
        if req.health_tags:
            if "上火" in req.health_tags or "咳嗽" in req.health_tags:
                if r["cuisine"] in ["烧烤", "火锅", "川菜"]:
                    continue  # 硬过滤
            if "痛风" in req.health_tags:
                if r["cuisine"] in ["海鲜", "火锅"]:
                    continue

        # 必需设施
        if req.must_have:
            facilities = r.get("special_services", {})
            if "wifi" in req.must_have:
                pass  # 几乎所有餐厅都有
            if "parking" in req.must_have:
                if facilities.get("parking", {}).get("available"):
                    score += 10
                    reasons.append("有停车位")
                else:
                    continue
            if "baby_seat" in req.must_have:
                if facilities.get("kids", {}).get("baby_seat"):
                    score += 10
                    reasons.append("有宝宝椅")
                else:
                    continue
            if "private_room" in req.must_have:
                if r.get("private_room", {}).get("available"):
                    score += 10
                    reasons.append("有包厢")
                else:
                    continue

        # 评分加成
        rating = r.get("rating", 4.0)
        score += (rating - 3.5) * 10

        # 动态覆盖
        ws = main.world_state
        queue_info = ws.get_queue(r["id"]) if ws else None
        if queue_info:
            r["dynamic"] = queue_info

        results.append({
            "id": r["id"],
            "name": r["name"],
            "cuisine": r["cuisine"],
            "sub_cuisine": r.get("sub_cuisine", ""),
            "rating": rating,
            "avg_price": price,
            "price_level": r.get("price_level", "中端"),
            "distance_km": round(dist / 1000, 2) if isinstance(dist, (int, float)) else dist,
            "travel_time": {"driving": round(dist / 400, 1) if isinstance(dist, (int, float)) else 10,
                           "walking": round(dist / 80, 1) if isinstance(dist, (int, float)) else 25},
            "current_queue": queue_info.get("current_queue", 0) if queue_info else 0,
            "status": queue_info.get("status", "有位") if queue_info else "有位",
            "services": {
                "baby_seat": r.get("special_services", {}).get("kids", {}).get("baby_seat", False),
                "private_room": r.get("private_room", {}).get("available", False),
                "parking": r.get("special_services", {}).get("parking", {}).get("available", False),
                "pet_allowed": r.get("special_services", {}).get("pets", {}).get("pet_allowed", False),
                "birthday": r.get("special_services", {}).get("birthday", {}).get("available", False),
            },
            "promotions": [p.get("discount") for p in r.get("promotions", [])],
            "match_reasons": reasons,
            "score": round(score, 1),
            "_dynamic": queue_info,
        })

    # 排序
    results.sort(key=lambda x: x["score"], reverse=True)

    # 折中逻辑
    compromise = False
    if req.taste_profiles and req.allow_compromise and len(req.taste_profiles) >= 2:
        spicy_vals = [p.get("spicy", "medium") for p in req.taste_profiles]
        if "high" in spicy_vals and "none" in spicy_vals:
            compromise = True
            for r in results:
                if r["cuisine"] in ["火锅"]:
                    r["compromise_feature"] = "鸳鸯锅满足辣与不辣双方"
                    r["match_reasons"].append("鸳鸯锅满足辣与不辣双方")

    return {
        "recommendations": results[:6],
        "compromise_applied": compromise,
        "total_candidates": len(results),
    }


@router.get("/queue")
def get_queue(restaurant_id: int):
    """实时排队查询"""
    ws = main.world_state
    queue = ws.get_queue(restaurant_id) if ws else None
    if not queue:
        return {"error": "restaurant not found"}
    return queue


@router.post("/take-number")
def take_number(restaurant_id: int, user_id: str = "guest"):
    """模拟线上取号"""
    ws = main.world_state
    q = ws.restaurant_queues.get(restaurant_id) if ws else None
    if not q:
        return {"error": "restaurant not found"}

    q.current_queue += 1
    number = random.randint(1, 99)
    return {
        "restaurant_id": restaurant_id,
        "queue_number": number,
        "current_queue": q.current_queue,
        "estimated_wait_min": q.estimated_wait_min,
        "status": "queuing",
        "note": "模拟取号成功，请留意排队变化",
    }


@router.post("/reserve")
def reserve(restaurant_id: int, user_id: str = "guest",
            date: str = "2026-06-01", time: str = "19:00",
            people: int = 2):
    """模拟预订"""
    rests = main.STATIC_DATA.get("restaurants", [])
    r = next((r for r in rests if r["id"] == restaurant_id), None)
    if not r:
        return {"error": "restaurant not found"}

    if not r.get("queuing", {}).get("supports_reservation", False):
        return {"error": "该餐厅不支持预订", "alternative": "可尝试线上取号"}

    return {
        "restaurant_id": restaurant_id,
        "restaurant_name": r["name"],
        "reservation_id": f"RES{random.randint(10000,99999)}",
        "date": date, "time": time, "people": people,
        "status": "confirmed",
        "note": "模拟预订成功，请按时到达",
    }


@router.post("/emergency-plan")
def emergency_plan(req: EmergencyRequest):
    """突发兜底方案"""
    rests = main.STATIC_DATA.get("restaurants", [])
    original = next((r for r in rests if r["id"] == req.original_restaurant_id), None)

    # 同商场备选
    same_mall = []
    nearby = []
    original_mall = original.get("transport", {}).get("mall_name") if original else None

    for r in rests:
        if r["id"] == req.original_restaurant_id:
            continue
        dist = haversine(req.current_lng, req.current_lat,
                        r.get("longitude", 0), r.get("latitude", 0))
        r_mall = r.get("transport", {}).get("mall_name")

        if req.emergency_type == "weather" and req.has_child:
            # 带娃雨天：优先同商场
            if original_mall and r_mall == original_mall and dist < 500:
                same_mall.append({**r, "distance_km": 0, "walking_min": dist // 80})
        elif req.emergency_type == "full":
            # 满座：同商场 > 500m内
            if original_mall and r_mall == original_mall:
                same_mall.append({**r, "distance_km": 0, "walking_min": 2})
            elif dist < 500:
                nearby.append({**r, "distance_km": round(dist/1000, 2), "walking_min": round(dist/80)})
        elif req.emergency_type == "late":
            # 迟到：外带/外卖建议
            pass

    # 构建响应
    priority = None
    if same_mall:
        best = same_mall[0]
        priority = {
            "type": "same_mall",
            "restaurant": {
                "id": best["id"], "name": best["name"],
                "cuisine": best["cuisine"], "rating": best["rating"],
                "distance_km": best["distance_km"],
                "walking_time": best.get("walking_min", 2),
                "current_queue": 0,
                "services": {
                    "baby_seat": best.get("special_services", {}).get("kids", {}).get("baby_seat", False),
                },
                "match_reasons": ["同商场室内步行可达"] + (
                    ["有宝宝椅"] if best.get("special_services", {}).get("kids", {}).get("baby_seat") else []
                ),
            },
            "message": f"同商场{best['name']}步行可达，建议就近用餐",
        }
    elif nearby:
        best = nearby[0]
        priority = {
            "type": "nearby",
            "restaurant": {"id": best["id"], "name": best["name"], "cuisine": best["cuisine"],
                          "distance_km": best["distance_km"], "walking_time": best.get("walking_min", 5)},
            "message": f"附近{best['name']}步行{best.get('walking_min', 5)}分钟可达",
        }
    else:
        priority = {
            "type": "takeout",
            "restaurant_name": original["name"] if original else "附近餐厅",
            "delivery_time": "35-45分钟",
            "note": "建议外卖，无需出门",
        }

    return {
        "priority_plan": priority,
        "alternatives": [
            {"type": "takeout", "restaurant_name": original["name"] if original else "原餐厅",
             "delivery_time": "30-40分钟", "note": "外卖免淋雨" if req.emergency_type == "weather" else "外卖可选"},
        ] + ([
            {"type": "nearby", "restaurant_name": n["name"], "distance_km": n["distance_km"]}
            for n in nearby[:2]
        ]),
    }


@router.get("/detail")
def restaurant_detail(restaurant_id: int):
    """餐厅详情"""
    rests = main.STATIC_DATA.get("restaurants", [])
    r = next((r for r in rests if r["id"] == restaurant_id), None)
    if not r:
        return {"error": "not found"}

    # 合并动态数据
    ws = main.world_state
    if ws:
        r["dynamic"] = ws.get_queue(restaurant_id)
        r["active_promotions"] = ws.get_active_promotions(restaurant_id)

    return r


@router.post("/review")
def submit_review(restaurant_id: int, user_id: str = "guest",
                  rating: float = 4.0, comment: str = ""):
    """餐后评价（模拟）"""
    review = {
        "user_name": user_id,
        "rating": rating,
        "comment": comment or "味道不错",
        "date": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
        "tags": ["模拟评价"],
    }
    return {"ok": True, "review": review, "note": "评价已记录（模拟）"}


@router.get("/special-dates")
def special_dates(user_id: str = "white_collar"):
    """特殊日期检查"""
    from datetime import datetime, timedelta
    today = datetime.now()
    # 预置特殊日期
    all_dates = {
        "white_collar": [
            {"date": (today + timedelta(days=18)).strftime("%Y-%m-%d"), "type": "anniversary",
             "person": "大刘", "suggest": "预订浪漫晚餐+蛋糕"},
        ],
        "parent": [
            {"date": (today + timedelta(days=10)).strftime("%Y-%m-%d"), "type": "birthday",
             "person": "小冉", "suggest": "预订亲子餐厅+生日布置"},
        ],
        "student": [],
    }
    upcoming = [d for d in all_dates.get(user_id, []) if d["date"] >= today.strftime("%Y-%m-%d")]
    return {
        "today": today.strftime("%Y-%m-%d"),
        "upcoming": upcoming,
        "today_special": None,
    }


@router.post("/monitor")
def start_monitor(restaurant_id: int, user_id: str = "guest",
                  alert_threshold: int = 5):
    """开启排队监控"""
    ws = main.world_state
    q = ws.restaurant_queues.get(restaurant_id) if ws else None
    if not q:
        return {"error": "restaurant not found"}

    return {
        "ok": True,
        "restaurant_id": restaurant_id,
        "current_queue": q.current_queue,
        "alert_threshold": alert_threshold,
        "check_interval_seconds": 120,
        "note": f"排队降至{alert_threshold}桌时提醒",
    }


@router.get("/monitor/check")
def check_monitor(user_id: str = "guest"):
    """轮询排队状态变化"""
    # 简化：返回所有活跃监控的变更
    ws = main.world_state
    changed = []
    for rid, q in ws.restaurant_queues.items():
        if q.current_queue <= 5 and q.status != "有位":
            changed.append({
                "restaurant_id": rid,
                "current_queue": q.current_queue,
                "estimated_wait_min": q.estimated_wait_min,
                "status": q.status,
                "alert": "排队降至5桌以内，建议出发",
            })
    return {"monitors": changed, "checked_at": __import__("datetime").datetime.now().isoformat()}


@router.get("/takeout")
def takeout_info(restaurant_id: int, user_id: str = "guest"):
    """外卖查询"""
    rests = main.STATIC_DATA.get("restaurants", [])
    r = next((r for r in rests if r["id"] == restaurant_id), None)
    if not r:
        return {"error": "not found"}

    return {
        "restaurant_id": restaurant_id,
        "restaurant_name": r["name"],
        "supports_takeout": True,
        "estimated_delivery_min": random.randint(25, 50),
        "delivery_fee_yuan": random.choice([0, 3, 5]),
        "min_order_yuan": 20,
        "note": "模拟外卖数据",
    }
