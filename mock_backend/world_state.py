"""
WorldState 动态引擎：管理所有随时间变化的数据

核心动态数据：
  - 天气：每小时更新，季节模式 + 随机降雨/预警
  - 路况：每15分钟更新，时段拥堵 + 随机事件
  - 排队：每2分钟随机游走，饭点偏向增长
  - 商场/公园拥挤度：受天气联动影响
  - 健康事件：随机触发 + 自动过期
  - 航班状态：随机延误
  - 优惠有效期：到期自动清理
  - 场景触发器：精确控制演示状态
"""

import json
import random
import threading
import time
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

from config import (
    congestion_by_hour, is_meal_time, is_rush_hour, is_weekend,
    get_seasonal_weather_base, SCENARIO_TRIGGERS,
)

# ============================================================
# 状态数据结构
# ============================================================

@dataclass
class WeatherState:
    current_temp: float = 25.0
    feels_like: float = 26.0
    temp_high: float = 30.0
    temp_low: float = 18.0
    humidity: int = 50
    condition: str = "晴"
    wind_direction: str = "南风"
    wind_level: int = 2
    uv_index: int = 5
    aqi: int = 80
    aqi_level: str = "良"
    rain_probability: int = 10
    hourly: List[dict] = field(default_factory=list)
    daily: List[dict] = field(default_factory=list)
    alerts: List[dict] = field(default_factory=list)
    last_updated: str = ""

@dataclass
class TrafficState:
    citywide_congestion: float = 0.4
    hotspots: List[dict] = field(default_factory=list)
    incidents: List[dict] = field(default_factory=list)
    metro_crowdedness: Dict[str, str] = field(default_factory=dict)
    last_updated: str = ""

@dataclass
class QueueState:
    restaurant_id: int
    current_queue: int = 0
    estimated_wait_min: int = 0
    status: str = "有位"
    last_updated: str = ""

@dataclass
class HealthEvent:
    user_id: str
    event_type: str       # "fever", "menstrual_pain", "allergy", "insomnia"
    person: str
    severity: str = "moderate"
    temp_curve: List[tuple] = field(default_factory=list)
    started_at: str = ""
    expires_at: str = ""

@dataclass
class FlightStatus:
    flight_id: str
    route: str
    scheduled_time: str
    actual_time: str
    delay_minutes: int = 0
    status: str = "on_time"
    reason: str = ""

@dataclass
class PromotionState:
    restaurant_id: int
    promo_id: int
    type: str
    discount: str
    valid_until: str
    is_active: bool = True


# ============================================================
# WorldState 引擎
# ============================================================

class WorldState:
    """全局单例，管理所有动态数据"""

    def __init__(self):
        self._lock = threading.Lock()

        # === 环境级 ===
        self.weather = WeatherState()
        self.traffic = TrafficState()

        # === POI 级 ===
        self.restaurant_queues: Dict[int, QueueState] = {}
        self.mall_crowdedness: Dict[int, str] = {}
        self.park_crowdedness: Dict[int, str] = {}
        self.active_promotions: Dict[int, list] = {}

        # === 用户级 ===
        self.health_events: Dict[str, HealthEvent] = {}
        self.flights: Dict[str, FlightStatus] = {}
        self.user_schedules: Dict[str, list] = {}

        # === 覆盖 ===
        self.scenario_override: Optional[dict] = None

        # === 控制 ===
        self._running = False
        self._thread = None
        self._tick_counters = {"2min": 0, "15min": 0, "30min": 0, "60min": 0}

    # ---- 初始化 ----

    def init_from_enriched(self, enriched_dir: str = "data/enriched"):
        """从丰富化数据初始化 POI 级动态数据"""
        rest_path = os.path.join(enriched_dir, "restaurants.json")
        if os.path.exists(rest_path):
            with open(rest_path, "r", encoding="utf-8") as f:
                rests = json.load(f)
            for r in rests:
                rid = r["id"]
                dyn = r.get("dynamic", {})
                self.restaurant_queues[rid] = QueueState(
                    restaurant_id=rid,
                    current_queue=dyn.get("current_queue", 0),
                    estimated_wait_min=dyn.get("estimated_wait_min", 0),
                    status=dyn.get("status", "有位"),
                    last_updated=datetime.now().isoformat(),
                )
                promos = []
                for deal in r.get("group_deals", []):
                    if deal.get("valid_until"):
                        promos.append(PromotionState(
                            restaurant_id=rid, promo_id=random.randint(10000, 99999),
                            type="group_deal", discount=deal.get("name", ""),
                            valid_until=deal.get("valid_until", ""),
                        ))
                for v in r.get("vouchers", []):
                    if v.get("valid_until"):
                        promos.append(PromotionState(
                            restaurant_id=rid, promo_id=random.randint(10000, 99999),
                            type="voucher", discount=v.get("name", ""),
                            valid_until=v.get("valid_until", ""),
                        ))
                if promos:
                    self.active_promotions[rid] = promos

        mall_path = os.path.join(enriched_dir, "malls.json")
        if os.path.exists(mall_path):
            with open(mall_path, "r", encoding="utf-8") as f:
                malls = json.load(f)
            for m in malls:
                self.mall_crowdedness[m["id"]] = m.get("dynamic", {}).get("crowdedness", "正常")

        park_path = os.path.join(enriched_dir, "parks.json")
        if os.path.exists(park_path):
            with open(park_path, "r", encoding="utf-8") as f:
                parks = json.load(f)
            for p in parks:
                self.park_crowdedness[p["id"]] = p.get("dynamic", {}).get("crowdedness", "正常")

        # 预置航班
        self.flights["CA1234"] = FlightStatus(
            flight_id="CA1234", route="北京→上海",
            scheduled_time="2026-06-02T10:00:00",
            actual_time="2026-06-02T10:00:00",
        )
        self.flights["CA1831"] = FlightStatus(
            flight_id="CA1831", route="北京→广州",
            scheduled_time="2026-06-03T08:30:00",
            actual_time="2026-06-03T08:30:00",
        )

        # 初始化天气 + 路况
        self._init_weather()
        self._update_traffic()

        print(f"[WorldState] Initialized: {len(self.restaurant_queues)} restaurants, "
              f"{len(self.mall_crowdedness)} malls, {len(self.flights)} flights")

    def _init_weather(self):
        now = datetime.now()
        base = get_seasonal_weather_base(now.month)
        self.weather.current_temp = round(random.uniform(base["temp_low"] + 2, base["temp_high"] - 2), 1)
        self.weather.temp_high = base["temp_high"]
        self.weather.temp_low = base["temp_low"]
        self.weather.humidity = base["humidity"] + random.randint(-10, 10)
        self.weather.condition = base["condition"]
        self.weather.feels_like = round(self.weather.current_temp + random.uniform(-2, 3), 1)
        self.weather.rain_probability = base["rain_prob"]
        self.weather.aqi = random.randint(40, 150)
        self.weather.aqi_level = self._aqi_level(self.weather.aqi)
        self.weather.last_updated = now.isoformat()

        # 逐小时预报
        self.weather.hourly = []
        for h in range(24):
            hour_temp = base["temp_low"] + (base["temp_high"] - base["temp_low"]) * (
                0.3 + 0.7 * (1 - abs(h - 14) / 14)
            )
            self.weather.hourly.append({
                "hour": h, "temp": round(hour_temp + random.uniform(-2, 2), 1),
                "condition": base["condition"], "rain_prob": base["rain_prob"],
            })
        # 逐日预报
        self.weather.daily = []
        for d in range(7):
            date = (now + timedelta(days=d)).strftime("%Y-%m-%d")
            self.weather.daily.append({
                "date": date,
                "temp_high": base["temp_high"] + random.randint(-3, 3),
                "temp_low": base["temp_low"] + random.randint(-2, 2),
                "condition": random.choice(["晴", "晴", "多云", "多云", "阴", "小雨"]),
                "rain_prob": base["rain_prob"] + random.randint(-15, 15),
            })

    # ---- 更新循环 ----

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        print("[WorldState] Background updater started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("[WorldState] Background updater stopped")

    def _update_loop(self):
        while self._running:
            time.sleep(60)
            with self._lock:
                self._tick_counters["2min"] += 1
                self._tick_counters["15min"] += 1
                self._tick_counters["30min"] += 1
                self._tick_counters["60min"] += 1

                if self._tick_counters["2min"] >= 2:
                    self._tick_counters["2min"] = 0
                    self._update_queues()

                if self._tick_counters["15min"] >= 15:
                    self._tick_counters["15min"] = 0
                    self._update_traffic()

                if self._tick_counters["30min"] >= 30:
                    self._tick_counters["30min"] = 0
                    self._check_promotion_expiry()
                    self._update_crowdedness()

                if self._tick_counters["60min"] >= 60:
                    self._tick_counters["60min"] = 0
                    self._update_weather()
                    self._check_random_events()

    # ---- 更新函数 ----

    def _update_weather(self):
        if self.scenario_override and "weather" in self.scenario_override:
            return
        now = datetime.now()
        base = get_seasonal_weather_base(now.month)

        if now.hour < 14:
            target = self.weather.temp_high
        else:
            target = self.weather.temp_low
        self.weather.current_temp = round(
            self.weather.current_temp * 0.85 + target * 0.15 + random.uniform(-1.5, 1.5), 1
        )
        self.weather.feels_like = round(
            self.weather.current_temp + random.uniform(-3, 2)
            + (5 if self.weather.humidity > 70 else 0), 1
        )

        if now.month in [6, 7, 8] and 14 <= now.hour <= 18:
            if random.random() < 0.10:
                self.weather.condition = "雷暴"
                self.weather.rain_probability = 90
                self.weather.alerts.append({
                    "type": "雷电黄色预警", "level": "黄色",
                    "issued_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=3)).isoformat(),
                })
        elif self.weather.rain_probability > 50:
            conditions = ["大雨", "暴雨", "中雨", "小雨"]
            self.weather.condition = random.choice(conditions)
            if self.weather.condition in ["暴雨", "大雨"] and not any(
                a["type"].startswith("暴雨") for a in self.weather.alerts
            ):
                self.weather.alerts.append({
                    "type": "暴雨黄色预警", "level": "黄色",
                    "issued_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=4)).isoformat(),
                })
        elif random.random() < 0.15:
            self.weather.condition = random.choice(["多云", "阴", "小雨"])
            self.weather.rain_probability = random.randint(20, 60)
        else:
            self.weather.condition = random.choice(["晴", "晴", "晴", "多云"])
            self.weather.rain_probability = random.randint(0, 20)

        self.weather.alerts = [
            a for a in self.weather.alerts
            if a.get("expires_at", "") > now.isoformat()
        ]
        # 沙尘暴（北京 3-5 月，AQI>200 + 大风）
        if now.month in [3, 4, 5] and self.weather.aqi > 200 and self.weather.wind_level >= 4:
            if random.random() < 0.08:
                self.weather.condition = "沙尘暴"
                self.weather.aqi = min(500, self.weather.aqi + random.randint(100, 250))
                self.weather.alerts.append({
                    "type": "沙尘暴黄色预警", "level": "黄色",
                    "issued_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=6)).isoformat(),
                })

        self.weather.aqi = max(20, min(500, self.weather.aqi + random.randint(-20, 25)))
        self.weather.aqi_level = self._aqi_level(self.weather.aqi)
        self.weather.last_updated = now.isoformat()

    def _update_traffic(self):
        if self.scenario_override and "traffic" in self.scenario_override:
            self.traffic.citywide_congestion = self.scenario_override["traffic"].get("citywide_congestion", 0.4)
            self.traffic.last_updated = datetime.now().isoformat()
            return

        now = datetime.now()
        base = congestion_by_hour(now.hour)
        weather_mult = 1.0
        if self.weather.condition in ["暴雨", "大雨", "雷暴"]:
            weather_mult = 1.35
        elif self.weather.condition in ["中雨", "小雪"]:
            weather_mult = 1.15
        elif self.weather.condition == "大雪":
            weather_mult = 1.6

        noise = random.uniform(0.9, 1.15)
        self.traffic.citywide_congestion = round(min(1.0, base * weather_mult * noise), 2)

        self.traffic.hotspots = []
        hotspot_roads = ["东三环北路", "东二环北路", "京通快速路", "建国门外大街",
                         "北四环东路", "西二环", "学院路"]
        for road in hotspot_roads:
            seg = self.traffic.citywide_congestion * random.uniform(0.8, 1.3)
            if seg > 0.65:
                self.traffic.hotspots.append({
                    "road": road, "direction": random.choice(["南向北", "北向南", "东向西", "西向东"]),
                    "level": "严重拥堵" if seg > 0.85 else "拥堵",
                    "delay_min": int(seg * random.randint(10, 30)),
                })

        if random.random() < 0.01:
            self.traffic.incidents.append({
                "road_name": random.choice(hotspot_roads),
                "incident_type": random.choice(["事故", "施工", "管制"]),
                "started_at": now.isoformat(),
                "estimated_clear_min": random.randint(30, 90),
            })

        # 地铁故障（随机线路，早高峰概率更高）
        metro_lines = ["6号线", "10号线", "1号线/八通线", "5号线", "14号线", "4号线/大兴线"]
        if random.random() < (0.02 if is_rush_hour(now.hour) else 0.005):
            line = random.choice(metro_lines)
            self.traffic.incidents.append({
                "road_name": f"{line}（{random.choice(['常营','国贸','望京','惠新西街南口','宋家庄'])}段）",
                "incident_type": "metro_disruption",
                "started_at": now.isoformat(),
                "estimated_clear_min": random.randint(20, 60),
                "detail": random.choice(["信号故障", "列车故障", "乘客晕倒救援", "轨道异物"]),
            })

        self.traffic.incidents = [
            inc for inc in self.traffic.incidents
            if (now - datetime.fromisoformat(inc["started_at"])).seconds / 60 < inc["estimated_clear_min"]
        ]

        rush = is_rush_hour(now.hour)
        for st in ["国贸", "西直门", "东单", "宋家庄", "十里河", "建国门", "复兴门"]:
            self.traffic.metro_crowdedness[st] = "极高" if rush else random.choice(["中", "高"])
        for st in ["常营", "五道口", "望京", "双井"]:
            self.traffic.metro_crowdedness[st] = "高" if rush else random.choice(["低", "中"])

        self.traffic.last_updated = now.isoformat()

    def _update_queues(self):
        now = datetime.now()
        meal_bias = 2 if is_meal_time(now.hour) else 0
        weather_effect = -1 if self.weather.condition in ["暴雨", "大雨", "雷暴"] else 0

        for rid, q in self.restaurant_queues.items():
            if self.scenario_override and self.scenario_override.get("restaurant_queues_override"):
                continue
            change = random.choices([-2, -1, 0, 1, 2, 3], weights=[0.08, 0.2, 0.35, 0.22, 0.1, 0.05])[0]
            change += meal_bias + weather_effect
            q.current_queue = max(0, q.current_queue + change)

            if q.current_queue == 0:
                q.status, q.estimated_wait_min = "有位", 0
            elif q.current_queue <= 3:
                q.status, q.estimated_wait_min = "等位", q.current_queue * random.randint(3, 8)
            elif q.current_queue <= 8:
                q.status, q.estimated_wait_min = "排队", q.current_queue * random.randint(5, 12)
            else:
                q.status, q.estimated_wait_min = "长队", q.current_queue * random.randint(8, 20)
            q.last_updated = now.isoformat()

        if random.random() < 0.05:
            target_rid = random.choice(list(self.restaurant_queues.keys()))
            self.restaurant_queues[target_rid].current_queue += random.randint(5, 20)
            self.restaurant_queues[target_rid].status = "长队"

    def _update_crowdedness(self):
        now = datetime.now()
        weather = self.weather.condition
        is_wknd = is_weekend(now)

        for mid in self.mall_crowdedness:
            if weather in ["暴雨", "大雨", "雷暴", "大雪"]:
                self.mall_crowdedness[mid] = random.choice(["较拥挤", "非常拥挤", "非常拥挤"])
            elif is_wknd and weather in ["晴", "多云"]:
                self.mall_crowdedness[mid] = random.choice(["正常", "较拥挤", "较拥挤"])
            elif weather in ["晴", "多云"]:
                self.mall_crowdedness[mid] = random.choice(["正常", "正常", "较拥挤"])
            else:
                self.mall_crowdedness[mid] = random.choice(["正常", "正常", "较空"])

        for pid in self.park_crowdedness:
            if weather in ["暴雨", "大雨", "雷暴", "大雪", "大风"]:
                self.park_crowdedness[pid] = "空"
            elif is_wknd and weather in ["晴", "多云"]:
                self.park_crowdedness[pid] = random.choice(["较拥挤", "拥挤", "非常拥挤"])
            elif weather in ["晴", "多云"]:
                self.park_crowdedness[pid] = random.choice(["较空", "正常", "较拥挤"])
            else:
                self.park_crowdedness[pid] = random.choice(["较空", "正常"])

    def _check_promotion_expiry(self):
        now = datetime.now()
        for rid, promos in list(self.active_promotions.items()):
            valid = []
            for p in promos:
                if isinstance(p, PromotionState):
                    p = asdict(p)
                if p.get("valid_until", "") >= now.strftime("%Y-%m-%d"):
                    valid.append(p)
            if valid:
                self.active_promotions[rid] = valid
            else:
                del self.active_promotions[rid]

    def _check_random_events(self):
        now = datetime.now()
        if now.hour == 2 and "parent" not in self.health_events:
            if random.random() < 0.03:
                self._trigger_health_event("parent", "fever", "乐乐", "severe",
                    temp_curve=[(2, 38.5), (4, 38.2), (7, 37.8), (12, 37.2)])
        if 13 <= now.day <= 17 and "student" not in self.health_events:
            if random.random() < 0.05:
                self._trigger_health_event("student", "menstrual_pain", "小晴", "severe", duration_hours=24)
        for fid, flight in list(self.flights.items()):
            if flight.status == "on_time" and random.random() < 0.02:
                delay = random.choice([30, 60, 90, 120, 180])
                flight.delay_minutes = delay
                flight.status = "delayed"
                flight.reason = random.choice(["天气原因", "航空管制", "机械故障"])
                sched = datetime.fromisoformat(flight.scheduled_time)
                flight.actual_time = (sched + timedelta(minutes=delay)).isoformat()
        # 宠物急诊（布丁 — 小冉的柯基），傍晚高发
        if "parent" not in self.health_events and random.random() < 0.01:
            if now.hour in [17, 18, 19, 20, 21]:
                self._trigger_health_event("parent", f"pet_emergency_{random.choice(['vomit','diarrhea','limp','chocolate'])}",
                    "布丁", "severe", duration_hours=6)
        # 餐厅临时歇业（随机一家，1-4小时后恢复）
        if random.random() < 0.03 and self.restaurant_queues:
            rid = random.choice(list(self.restaurant_queues.keys()))
            q = self.restaurant_queues[rid]
            if q.status not in ("closed", "歇业"):
                q.status = "歇业"
                q.estimated_wait_min = 0
                q.current_queue = 0
                reopen_hours = random.randint(1, 4)
                q.last_updated = (now + timedelta(hours=reopen_hours)).isoformat()  # 复用字段存恢复时间
        # 恢复已到期的歇业餐厅
        for rid, q in self.restaurant_queues.items():
            if q.status == "歇业" and q.last_updated < now.isoformat():
                q.status = "有位"
                q.last_updated = now.isoformat()
        # 外卖配送延迟（雨天概率翻倍）
        if random.random() < (0.05 if self.weather.condition in ["暴雨", "大雨", "雷暴", "中雨"] else 0.01):
            self.traffic.incidents.append({
                "road_name": "全城",
                "incident_type": "delivery_delay",
                "started_at": now.isoformat(),
                "estimated_clear_min": random.randint(30, 90),
                "detail": f"恶劣天气导致骑手不足，外卖配送预计延迟{random.randint(20, 40)}分钟",
            })
        for uid, evt in list(self.health_events.items()):
            if evt.expires_at and evt.expires_at < now.isoformat():
                del self.health_events[uid]

    def _trigger_health_event(self, user_id, event_type, person, severity, **kwargs):
        now = datetime.now()
        self.health_events[user_id] = HealthEvent(
            user_id=user_id, event_type=event_type, person=person, severity=severity,
            temp_curve=kwargs.get("temp_curve", []),
            started_at=now.isoformat(),
            expires_at=(now + timedelta(hours=kwargs.get("duration_hours", 24))).isoformat(),
        )
        print(f"[WorldState] Health event: {person} {event_type} (severity={severity})")

    def _aqi_level(self, aqi: int) -> str:
        if aqi <= 50: return "优"
        elif aqi <= 100: return "良"
        elif aqi <= 150: return "轻度污染"
        elif aqi <= 200: return "中度污染"
        elif aqi <= 300: return "重度污染"
        return "严重污染"

    # ---- 场景触发器 ----

    def trigger_scenario(self, scenario_id: str) -> dict:
        trigger = SCENARIO_TRIGGERS.get(scenario_id)
        if not trigger:
            return {"error": f"Unknown scenario: {scenario_id}"}
        with self._lock:
            self.scenario_override = trigger
            if "weather" in trigger:
                w = trigger["weather"]
                self.weather.condition = w.get("condition", self.weather.condition)
                if "current_temp" in w:
                    self.weather.current_temp = w["current_temp"]
                self.weather.alerts = w.get("alerts", [])
                if "hourly_rain" in w:
                    for h_str, cond in w["hourly_rain"]:
                        hour = int(h_str.split(":")[0])
                        for entry in self.weather.hourly:
                            if entry["hour"] == hour:
                                entry["condition"] = cond
                                entry["rain_prob"] = 90 if "雨" in cond else 30
            if "traffic" in trigger:
                self.traffic.citywide_congestion = trigger["traffic"].get("citywide_congestion", 0.4)
                self.traffic.hotspots = trigger["traffic"].get("hotspots", [])
            if "health_event" in trigger:
                he = trigger["health_event"]
                self._trigger_health_event(
                    he["user"], he["type"], he.get("person", he["user"]),
                    he.get("severity", "moderate"),
                    temp_curve=he.get("temp_curve", []),
                    duration_hours=he.get("duration_hours", 24),
                )
            if "flight_delay" in trigger:
                fd = trigger["flight_delay"]
                fid = fd["flight_id"]
                if fid in self.flights:
                    self.flights[fid].delay_minutes = fd["delay_min"]
                    self.flights[fid].status = "delayed"
                    self.flights[fid].reason = fd.get("reason", "天气原因")
        print(f"[WorldState] Scenario {scenario_id} activated: {trigger.get('description', '')}")
        return {"ok": True, "scenario": scenario_id, "description": trigger.get("description", "")}

    def reset_scenario(self):
        with self._lock:
            self.scenario_override = None
            self.health_events.clear()
            for fid, f in self.flights.items():
                f.delay_minutes = 0
                f.status = "on_time"
                f.reason = ""
                f.actual_time = f.scheduled_time
            self.weather.alerts.clear()
        print("[WorldState] Scenario reset - normal operation restored")
        return {"ok": True}

    # ---- 查询 API ----

    def get_weather(self) -> dict: return asdict(self.weather)
    def get_traffic(self) -> dict: return asdict(self.traffic)
    def get_queue(self, restaurant_id: int):
        q = self.restaurant_queues.get(restaurant_id)
        return asdict(q) if q else None
    def get_all_queues(self) -> dict:
        return {str(k): asdict(v) for k, v in self.restaurant_queues.items()}
    def get_health_event(self, user_id: str):
        evt = self.health_events.get(user_id)
        return asdict(evt) if evt else None
    def get_flight(self, flight_id: str):
        f = self.flights.get(flight_id)
        return asdict(f) if f else None
    def get_mall_crowdedness(self, mall_id: int) -> str:
        return self.mall_crowdedness.get(mall_id, "正常")
    def get_park_crowdedness(self, park_id: int) -> str:
        return self.park_crowdedness.get(park_id, "正常")
    def get_active_promotions(self, restaurant_id: int) -> list:
        promos = self.active_promotions.get(restaurant_id, [])
        return [asdict(p) if hasattr(p, '__dataclass_fields__') else p for p in promos]

    def save_state(self, path: str = "data/world_state_snapshot.json"):
        with self._lock:
            state = {
                "weather": asdict(self.weather),
                "traffic": asdict(self.traffic),
                "restaurant_queues": {str(k): asdict(v) for k, v in self.restaurant_queues.items()},
                "mall_crowdedness": self.mall_crowdedness,
                "park_crowdedness": self.park_crowdedness,
                "health_events": {k: asdict(v) for k, v in self.health_events.items()},
                "flights": {k: asdict(v) for k, v in self.flights.items()},
                "saved_at": datetime.now().isoformat(),
            }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return path


# ============================================================
# 全局单例
# ============================================================

_world_state_instance = None

def get_world_state() -> WorldState:
    global _world_state_instance
    if _world_state_instance is None:
        _world_state_instance = WorldState()
    return _world_state_instance
