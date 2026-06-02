"""出行管家 API: 路线规划/公交查询/叫车/周边设施/长途规划"""

import random
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Query
from pydantic import BaseModel

import shared as main
from config import haversine, congestion_by_hour, is_rush_hour

router = APIRouter()


class RouteRequest(BaseModel):
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    mode: Optional[str] = None        # driving, transit, walking, cycling, taxi
    user_type: str = "white_collar"   # white_collar, parent, college_student
    with_children: bool = False
    budget_level: str = "medium"


@router.post("/route")
def plan_route(req: RouteRequest):
    """多模式路径规划"""
    modes = [req.mode] if req.mode else ["driving", "transit", "walking", "cycling", "taxi"]

    planner = main.route_planner
    if planner:
        result = planner.plan_route(req.origin_lon, req.origin_lat,
                                    req.dest_lon, req.dest_lat, modes=modes)
    else:
        # 无路网数据时用直线距离估算
        result = _fallback_route(req)

    # 身份相关附加信息
    if req.user_type == "parent" or req.with_children:
        result["parent_notes"] = _parent_route_notes(result)
    if req.user_type == "college_student" or req.budget_level == "low":
        result["budget_notes"] = _budget_route_notes(result)

    result["weather_note"] = _weather_route_note()

    return result


def _fallback_route(req: RouteRequest) -> dict:
    """直线距离估算"""
    dist = haversine(req.origin_lon, req.origin_lat, req.dest_lon, req.dest_lat)
    dist_km = dist / 1000
    hour = datetime.now().hour
    cong = congestion_by_hour(hour)

    options = []
    # 驾车
    drive_speed = 35 * (1 - cong * 0.5)
    drive_time = round(dist / (drive_speed * 1000 / 60))
    options.append({
        "mode": "driving", "time_min": max(5, drive_time),
        "distance_km": round(dist_km * 1.3, 2),
        "cost_yuan": round(dist_km * 2.3, 1),
        "congestion_level": "拥堵" if cong > 0.7 else ("缓行" if cong > 0.4 else "畅通"),
    })
    # 公交/地铁
    transit_time = round(dist / (25000 / 60)) + 10
    options.append({
        "mode": "transit", "time_min": max(15, transit_time),
        "distance_km": round(dist_km, 2),
        "cost_yuan": 3 if dist_km <= 6 else (4 if dist_km <= 12 else 5),
    })
    # 步行
    walk_time = round(dist / 80)
    options.append({"mode": "walking", "time_min": walk_time,
                    "distance_km": round(dist_km, 2), "cost_yuan": 0})
    # 骑行
    cycle_time = round(dist / 250)
    options.append({"mode": "cycling", "time_min": cycle_time,
                    "distance_km": round(dist_km * 1.1, 2),
                    "cost_yuan": 1.5 if dist_km <= 3 else 3.0})
    # 打车
    taxi_time = drive_time + random.randint(2, 8)
    taxi_fare = 13 + max(0, dist_km - 3) * 2.3
    if hour >= 23 or hour <= 5:
        taxi_fare *= 1.2
    options.append({"mode": "taxi", "time_min": taxi_time,
                    "distance_km": round(dist_km, 2), "cost_yuan": round(taxi_fare, 1)})

    options.sort(key=lambda x: x["time_min"])
    recommended = options[0]["mode"]

    return {
        "origin": {"longitude": req.origin_lon, "latitude": req.origin_lat},
        "destination": {"longitude": req.dest_lon, "latitude": req.dest_lat},
        "straight_line_distance_km": round(dist_km, 2),
        "options": options,
        "recommended": recommended,
        "recommend_reason": f"预计最快{options[0]['time_min']}分钟",
        "traffic_note": f"当前路况{'拥堵' if cong > 0.7 else '正常'}",
        "generated_at": datetime.now().isoformat(),
        "simulated": True,
    }


def _parent_route_notes(result: dict) -> dict:
    """宝妈出行附加信息"""
    notes = {
        "stroller_friendly": random.choice([True, True, False]),
        "elevator_available": random.choice([True, True, True, False]),
    }
    if notes.get("stroller_friendly"):
        notes["tip"] = "路线适合推车"
    else:
        notes["tip"] = "部分路段有台阶，推车需注意"
    return notes


def _budget_route_notes(result: dict) -> dict:
    """学生预算建议"""
    transit = next((o for o in result.get("options", []) if o["mode"] == "transit"), None)
    cycling = next((o for o in result.get("options", []) if o["mode"] == "cycling"), None)
    return {
        "cheapest_option": "transit" if transit and transit.get("cost_yuan", 99) < 5 else "cycling",
        "student_discount_note": "北京公交学生卡2.5折",
        "tip": "预算友好方案已高亮" if cycling and cycling.get("time_min", 999) < 30 else "距离较远建议地铁",
    }


def _weather_route_note() -> str:
    ws = main.world_state
    if not ws:
        return ""
    cond = ws.weather.condition
    if cond in ["暴雨", "大雨", "雷暴"]:
        return "当前暴雨，建议打车或地铁，避免骑行和步行"
    elif cond in ["中雨", "小雪"]:
        return "有降水，建议携带雨具，优先地铁"
    elif cond in ["高温"]:
        return "天气炎热，建议地铁出行避免中暑"
    return ""


@router.get("/transport/search")
def transport_search(origin_city: str = "北京", dest_city: str = "上海",
                     date: str = None, transport_type: str = "all"):
    """长途交通班次查询（模拟数据）"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    flights = [
        {"id": "CA1234", "type": "flight", "departure": "10:00", "arrival": "12:15",
         "duration": "2h15m", "price": 850, "seats_left": random.randint(0, 20),
         "airline": "国航", "flight_no": "CA1234"},
        {"id": "MU5101", "type": "flight", "departure": "13:30", "arrival": "15:45",
         "duration": "2h15m", "price": 780, "seats_left": random.randint(0, 15),
         "airline": "东航", "flight_no": "MU5101"},
        {"id": "CZ8888", "type": "flight", "departure": "18:00", "arrival": "20:15",
         "duration": "2h15m", "price": 650, "seats_left": random.randint(5, 30),
         "airline": "南航", "flight_no": "CZ8888"},
    ]

    trains = [
        {"id": "G1", "type": "train", "departure": "07:00", "arrival": "11:29",
         "duration": "4h29m", "price": 553, "seats_left": random.randint(0, 100),
         "train_type": "高铁", "train_no": "G1"},
        {"id": "G7", "type": "train", "departure": "10:00", "arrival": "14:30",
         "duration": "4h30m", "price": 553, "seats_left": random.randint(0, 80),
         "train_type": "高铁", "train_no": "G7"},
        {"id": "G15", "type": "train", "departure": "15:00", "arrival": "19:32",
         "duration": "4h32m", "price": 526, "seats_left": random.randint(10, 200),
         "train_type": "高铁", "train_no": "G15"},
    ]

    results = []
    if transport_type in ("all", "flight"):
        results.extend(flights)
    if transport_type in ("all", "train"):
        results.extend(trains)

    # 如果场景中有航班延误，更新状态
    ws = main.world_state
    if ws:
        for r in results:
            if r["type"] == "flight" and r["id"] in ws.flights:
                f = ws.flights[r["id"]]
                if f.status == "delayed":
                    r["status"] = "delayed"
                    r["delay_min"] = f.delay_minutes
                    r["note"] = f"延误{f.delay_minutes}分钟（{f.reason}）"

    return {
        "origin": origin_city, "destination": dest_city,
        "date": date, "source": "mock_backend",
        "results": results,
        "note": "模拟票务数据，请自行购票",
    }


@router.post("/call-taxi")
def call_taxi(origin_lat: float, origin_lon: float,
              dest_lat: float = None, dest_lon: float = None,
              car_type: str = "快车"):
    """模拟叫车"""
    wait_time = random.randint(1, 8)
    return {
        "ok": True,
        "driver_name": f"张师傅{random.choice('ABCDEFG')}",
        "car_plate": f"京{random.choice('ABCDEFGH')}{random.randint(10000,99999)}",
        "car_type": car_type,
        "estimated_arrival_min": wait_time,
        "note": f"司机预计{wait_time}分钟后到达（模拟）",
    }


@router.get("/nearby")
def nearby_facilities(lat: float, lon: float,
                      facility_type: str = "gas_station",
                      radius_km: float = 3.0):
    """周边设施查询"""
    type_map = {
        "gas_station": "gas_stations",
        "charging": "charging_stations",
        "convenience_store": "convenience_stores",
        "parking": "parking_lots",
        "shelter": "malls",      # 避雨 = 商场
        "pharmacy": "pharmacies",
        "hospital": "hospitals",
    }
    key = type_map.get(facility_type, facility_type)
    pois = main.STATIC_DATA.get(key, [])

    results = []
    for p in pois:
        plon = p.get("longitude", 0)
        plat = p.get("latitude", 0)
        if plon and plat:
            dist = haversine(lon, lat, plon, plat)
            if dist <= radius_km * 1000:
                results.append({
                    "name": p["name"], "type": p.get("type", facility_type),
                    "distance_m": int(dist), "distance_km": round(dist / 1000, 2),
                    "address": p.get("address", ""), "id": p.get("id"),
                })

    results.sort(key=lambda x: x["distance_m"])
    return {"facilities": results[:10], "type": facility_type, "search_radius_km": radius_km}


@router.post("/long-distance/plan")
def long_distance_plan(origin: str = "北京", destination: str = "上海",
                       mode: str = "driving"):
    """长途出行规划（模拟）"""
    if mode == "driving":
        total_km = random.randint(1100, 1300)
        return {
            "origin": origin, "destination": destination,
            "total_distance_km": total_km,
            "estimated_drive_hours": round(total_km / 100, 1),
            "estimated_toll_yuan": random.randint(400, 600),
            "rest_stops": ["济南服务区", "徐州服务区", "南京服务区"],
            "fuel_stops": ["沧州", "济南", "徐州"],
            "weather_along_route": "沿途天气良好",
            "note": "模拟长途规划，请以实际导航为准",
        }
    return {"note": f"{mode} 规划暂不支持（模拟）"}
