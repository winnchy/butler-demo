"""
交通路径数据生成器：地铁网络 + 模拟路网 + 路径规划

核心能力：
1. 从 40 个真实地铁站 + config.py 的线路数据构建完整地铁图
2. 构建北京模拟路网（关键走廊 + 环路）
3. 多模式路径规划（驾车/地铁/步行/骑行/组合/打车）
4. 沿途设施索引
"""

import json
import random
import math
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from config import (
    haversine, parse_lonlat, safe_float, congestion_by_hour,
    BEIJING_METRO_LINES, TRANSFER_STATIONS,
)

# ============================================================
# 第1部分：地铁网络构建
# ============================================================

class MetroNetwork:
    """北京地铁网络图"""

    def __init__(self):
        self.stations: Dict[str, dict] = {}   # station_name → {lon, lat, lines, is_transfer}
        self.edges: List[dict] = []           # [{from, to, line, distance_m, time_min}]
        self.adjacency: Dict[str, List[Tuple[str, dict]]] = {}  # station → [(neighbor, edge_info)]

    def build(self, enriched_metro_stations: List[dict]):
        """
        构建地铁网络：
        1. 从 enriched 地铁站获取 40 个真实坐标
        2. 按 config.py 的线路数据补充缺失站点的近似坐标
        3. 连接同线路相邻站
        """
        # 收集真实坐标
        real_coords = {}
        for st in enriched_metro_stations:
            name = st["name"]
            real_coords[name] = {
                "lon": st["longitude"], "lat": st["latitude"],
                "lines": st.get("lines", []),
                "district": st.get("district", ""),
            }

        # 为每条线路生成完整站点列表（含插值坐标）
        all_stations = {}  # name → {lon, lat, lines}
        station_line_count = {}  # name → count of lines

        for line_name, line_info in BEIJING_METRO_LINES.items():
            ordered_names = line_info["stations_ordered"]
            direction = line_info["direction"]

            # 找到这条线上有真实坐标的站
            known_positions = []
            for i, sname in enumerate(ordered_names):
                if sname in real_coords:
                    known_positions.append((i, sname, real_coords[sname]["lon"], real_coords[sname]["lat"]))

            # 对每个站生成坐标
            for i, sname in enumerate(ordered_names):
                if sname in real_coords:
                    coord_lon = real_coords[sname]["lon"]
                    coord_lat = real_coords[sname]["lat"]
                else:
                    # 在线性插值坐标
                    coord_lon, coord_lat = self._interpolate_position(
                        i, ordered_names, known_positions, direction
                    )

                if sname not in all_stations:
                    all_stations[sname] = {"lon": coord_lon, "lat": coord_lat, "lines": []}
                if line_name not in all_stations[sname]["lines"]:
                    all_stations[sname]["lines"].append(line_name)
                station_line_count[sname] = station_line_count.get(sname, 0) + 1

            # 连接相邻站
            for i in range(len(ordered_names) - 1):
                s1, s2 = ordered_names[i], ordered_names[i + 1]
                if s1 in all_stations and s2 in all_stations:
                    lon1, lat1 = all_stations[s1]["lon"], all_stations[s1]["lat"]
                    lon2, lat2 = all_stations[s2]["lon"], all_stations[s2]["lat"]
                    dist = haversine(lon1, lat1, lon2, lat2)
                    # 实际轨道距离 = 直线 × 1.15
                    track_dist = dist * 1.15
                    # 地铁平均速度 35km/h（含停站）= 583 m/min
                    time_min = max(1, round(track_dist / 583))

                    edge = {
                        "from": s1, "to": s2,
                        "line": line_name,
                        "distance_m": int(track_dist),
                        "time_min": time_min,
                    }
                    self.edges.append(edge)

                    # 邻接表
                    if s1 not in self.adjacency:
                        self.adjacency[s1] = []
                    if s2 not in self.adjacency:
                        self.adjacency[s2] = []
                    self.adjacency[s1].append((s2, edge))
                    self.adjacency[s2].append((s1, edge))

        # 标记换乘站
        for sname, count in station_line_count.items():
            if sname in all_stations:
                all_stations[sname]["is_transfer"] = count >= 2
                all_stations[sname]["line_count"] = count

        self.stations = all_stations
        print(f"[Metro] Built network: {len(all_stations)} stations, {len(self.edges)} edges")

    def _interpolate_position(self, idx: int, ordered_names: List[str],
                               known: List[Tuple[int, str, float, float]],
                               direction: str) -> Tuple[float, float]:
        """在两个已知坐标之间线性插值"""
        if not known:
            # 完全没有已知坐标 → 生成合理默认值
            if direction in ("east-west", "east-west-north"):
                return 116.2 + idx * 0.015, 39.92 + random.uniform(-0.02, 0.02)
            else:
                return 116.38 + random.uniform(-0.05, 0.05), 39.75 + idx * 0.02

        # 找前后最近的已知站
        before, after = None, None
        for i, name, lon, lat in known:
            if i <= idx:
                before = (i, lon, lat)
            if i >= idx and after is None:
                after = (i, lon, lat)

        if before and after:
            if before[0] == after[0]:
                return before[1], before[2]
            # 线性插值
            ratio = (idx - before[0]) / (after[0] - before[0])
            lon = before[1] + (after[1] - before[1]) * ratio
            lat = before[2] + (after[2] - before[2]) * ratio
            return lon, lat
        elif before:
            return before[1] + random.uniform(0.005, 0.02), before[2] + random.uniform(-0.01, 0.01)
        else:
            return after[1] - random.uniform(0.005, 0.02), after[2] + random.uniform(-0.01, 0.01)

    def find_nearest_station(self, lon: float, lat: float) -> Optional[Tuple[str, float]]:
        """找最近的地铁站，返回 (站名, 距离米)，若 >3km 则返回 None"""
        best_name, best_dist = None, float("inf")
        for name, info in self.stations.items():
            dist = haversine(lon, lat, info["lon"], info["lat"])
            if dist < best_dist:
                best_dist = dist
                best_name = name
        if best_dist > 3000:
            return None
        return (best_name, best_dist)

    def find_path(self, from_station: str, to_station: str) -> Optional[dict]:
        """Dijkstra 最短路径（按时间）"""
        if from_station not in self.stations or to_station not in self.stations:
            return None

        # Dijkstra
        import heapq
        dist = {s: float("inf") for s in self.stations}
        prev = {s: None for s in self.stations}
        prev_edge = {s: None for s in self.stations}
        dist[from_station] = 0
        pq = [(0, from_station)]

        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            if u == to_station:
                break
            for v, edge in self.adjacency.get(u, []):
                new_d = d + edge["time_min"]
                if new_d < dist[v]:
                    dist[v] = new_d
                    prev[v] = u
                    prev_edge[v] = edge
                    heapq.heappush(pq, (new_d, v))

        if dist[to_station] == float("inf"):
            return None

        # 回溯路径
        path = []
        cur = to_station
        while prev[cur] is not None:
            path.append({
                "from": prev[cur],
                "to": cur,
                "line": prev_edge[cur]["line"],
                "time_min": prev_edge[cur]["time_min"],
                "distance_m": prev_edge[cur]["distance_m"],
            })
            cur = prev[cur]
        path.reverse()

        # 计算换乘次数
        transfers = 0
        for i in range(1, len(path)):
            if path[i]["line"] != path[i-1]["line"]:
                transfers += 1

        # 票价（北京地铁：3元起步，按距离加价）
        total_dist = sum(e["distance_m"] for e in path)
        if total_dist <= 6000:
            fare = 3
        elif total_dist <= 12000:
            fare = 4
        elif total_dist <= 22000:
            fare = 5
        elif total_dist <= 32000:
            fare = 6
        else:
            fare = 6 + (total_dist - 32000) // 20000 + 1

        return {
            "stations": [from_station] + [e["to"] for e in path],
            "segments": path,
            "total_time_min": dist[to_station],
            "total_distance_m": total_dist,
            "transfers": transfers,
            "fare_yuan": fare,
        }

    def to_dict(self) -> dict:
        """导出可序列化的网络摘要"""
        return {
            "station_count": len(self.stations),
            "edge_count": len(self.edges),
            "transfer_stations": [s for s, info in self.stations.items() if info.get("is_transfer")],
            "stations": self.stations,
        }


# ============================================================
# 第2部分：模拟路网
# ============================================================

# 北京关键道路走廊（起终点 + 途径的近似坐标点）
BEIJING_ROAD_CORRIDORS = [
    # 环路（简化：只取关键弧段）
    {"id": "E2N", "name": "东二环北路", "points": [(116.436, 39.900), (116.438, 39.920), (116.440, 39.940)],
     "speed_limit": 80, "lanes": 6, "district": "东城/朝阳"},
    {"id": "E2S", "name": "东二环南路", "points": [(116.436, 39.900), (116.434, 39.880), (116.432, 39.870)],
     "speed_limit": 80, "lanes": 6, "district": "东城"},
    {"id": "E3N", "name": "东三环北路", "points": [(116.460, 39.935), (116.462, 39.950), (116.463, 39.965)],
     "speed_limit": 80, "lanes": 8, "district": "朝阳"},
    {"id": "E3M", "name": "东三环中路", "points": [(116.458, 39.910), (116.460, 39.925), (116.461, 39.935)],
     "speed_limit": 80, "lanes": 8, "district": "朝阳"},
    {"id": "E3S", "name": "东三环南路", "points": [(116.456, 39.880), (116.457, 39.895), (116.458, 39.910)],
     "speed_limit": 80, "lanes": 8, "district": "朝阳"},
    {"id": "E4N", "name": "北四环东路", "points": [(116.420, 39.985), (116.440, 39.985), (116.460, 39.985)],
     "speed_limit": 100, "lanes": 8, "district": "朝阳/海淀"},
    {"id": "E4E", "name": "东四环北路", "points": [(116.480, 39.965), (116.482, 39.940), (116.484, 39.920)],
     "speed_limit": 100, "lanes": 8, "district": "朝阳"},

    # 长安街轴线
    {"id": "CA_E", "name": "建国门外大街", "points": [(116.450, 39.908), (116.440, 39.908)], "speed_limit": 70, "lanes": 10, "district": "朝阳"},
    {"id": "CA_C1", "name": "建国门内大街", "points": [(116.440, 39.908), (116.430, 39.908)], "speed_limit": 70, "lanes": 8, "district": "东城"},
    {"id": "CA_C2", "name": "东长安街", "points": [(116.430, 39.908), (116.415, 39.907)], "speed_limit": 70, "lanes": 8, "district": "东城"},
    {"id": "CA_C3", "name": "西长安街", "points": [(116.415, 39.907), (116.390, 39.906)], "speed_limit": 70, "lanes": 8, "district": "西城"},
    {"id": "CA_W", "name": "复兴门外大街", "points": [(116.390, 39.906), (116.370, 39.906)], "speed_limit": 70, "lanes": 8, "district": "西城/海淀"},

    # 快速路/高速
    {"id": "JT", "name": "京通快速路", "points": [(116.465, 39.910), (116.510, 39.907), (116.560, 39.905), (116.610, 39.903), (116.660, 39.900)],
     "speed_limit": 100, "lanes": 6, "district": "朝阳→通州"},
    {"id": "JC_S", "name": "京藏高速(南段)", "points": [(116.375, 39.965), (116.365, 39.990), (116.360, 40.020), (116.355, 40.050)],
     "speed_limit": 120, "lanes": 6, "district": "海淀→昌平"},
    {"id": "AP", "name": "机场高速", "points": [(116.455, 39.955), (116.490, 39.980), (116.530, 40.010), (116.570, 40.050), (116.610, 40.080)],
     "speed_limit": 120, "lanes": 6, "district": "朝阳→顺义"},
    {"id": "JK", "name": "京开高速", "points": [(116.365, 39.855), (116.360, 39.830), (116.355, 39.800), (116.350, 39.770)],
     "speed_limit": 120, "lanes": 6, "district": "丰台→大兴"},
    {"id": "CY", "name": "朝阳北路", "points": [(116.465, 39.920), (116.490, 39.922), (116.520, 39.924), (116.550, 39.926), (116.580, 39.927)],
     "speed_limit": 60, "lanes": 4, "district": "朝阳"},
    {"id": "CY2", "name": "朝阳路", "points": [(116.460, 39.915), (116.485, 39.917), (116.515, 39.919), (116.545, 39.920)],
     "speed_limit": 60, "lanes": 4, "district": "朝阳"},

    # 南北干道
    {"id": "ZGC", "name": "中关村大街", "points": [(116.315, 39.975), (116.315, 39.960), (116.315, 39.945), (116.315, 39.930)],
     "speed_limit": 60, "lanes": 6, "district": "海淀"},
    {"id": "XYL", "name": "学院路", "points": [(116.350, 39.990), (116.350, 39.975), (116.350, 39.960)],
     "speed_limit": 60, "lanes": 6, "district": "海淀"},
    {"id": "FS", "name": "阜石路", "points": [(116.260, 39.920), (116.230, 39.925), (116.200, 39.930), (116.170, 39.935)],
     "speed_limit": 80, "lanes": 6, "district": "海淀→门头沟"},
]


class RoadNetwork:
    """模拟北京路网"""

    def __init__(self):
        self.nodes: Dict[str, Tuple[float, float]] = {}  # node_id → (lon, lat)
        self.edges: Dict[str, dict] = {}                  # edge_id → road_info
        self.road_adjacency: Dict[str, List[Tuple[str, dict]]] = {}  # node → [(neighbor_node, edge)]

    def build(self):
        """构建路网图"""
        node_idx = 0

        for corridor in BEIJING_ROAD_CORRIDORS:
            points = corridor["points"]
            prev_node = None
            for p in points:
                node_id = f"N{node_idx}"
                node_idx += 1
                self.nodes[node_id] = p
                if prev_node:
                    # 计算该段的实际距离
                    dist = haversine(prev_node[1], prev_node[2], p[0], p[1])
                    edge_id = f"{corridor['id']}_{node_idx}"
                    self.edges[edge_id] = {
                        "name": corridor["name"],
                        "from_node": prev_node[0],
                        "to_node": node_id,
                        "distance_m": int(dist),
                        "speed_limit": corridor["speed_limit"],
                        "lanes": corridor["lanes"],
                        "district": corridor["district"],
                        # 自由流时间（分钟）
                        "free_flow_time_min": round(dist / (corridor["speed_limit"] * 1000 / 60), 1),
                    }
                    # 邻接表
                    if prev_node[0] not in self.road_adjacency:
                        self.road_adjacency[prev_node[0]] = []
                    if node_id not in self.road_adjacency:
                        self.road_adjacency[node_id] = []
                    self.road_adjacency[prev_node[0]].append((node_id, edge_id))
                    self.road_adjacency[node_id].append((prev_node[0], edge_id))  # 双向
                prev_node = (node_id, p[0], p[1])

        print(f"[Road] Built network: {len(self.nodes)} nodes, {len(self.edges)} road segments")

    def find_nearest_node(self, lon: float, lat: float) -> Optional[Tuple[str, float]]:
        """找最近的路网节点"""
        best, best_dist = None, float("inf")
        for nid, (nlon, nlat) in self.nodes.items():
            dist = haversine(lon, lat, nlon, nlat)
            if dist < best_dist:
                best_dist = dist
                best = nid
        if best_dist > 5000:  # >5km 太远
            return None
        return (best, best_dist)

    def get_travel_time(self, edge_id: str, hour: int = None) -> float:
        """获取某路段的当前行驶时间（含拥堵）"""
        if hour is None:
            hour = datetime.now().hour
        edge = self.edges[edge_id]
        base_time = edge["free_flow_time_min"]
        congestion = congestion_by_hour(hour)
        # 添加天气影响（默认无）
        weather_mult = 1.0
        # 添加随机噪声
        noise = random.uniform(0.9, 1.15)
        return round(base_time * (1 + congestion * 0.8) * weather_mult * noise, 1)


# ============================================================
# 第3部分：多模式路径规划
# ============================================================

class RoutePlanner:
    """多模式路径规划器"""

    def __init__(self, metro_network: MetroNetwork, road_network: RoadNetwork):
        self.metro = metro_network
        self.road = road_network

    def plan_route(self, from_lon: float, from_lat: float,
                   to_lon: float, to_lat: float,
                   modes: List[str] = None,
                   hour: int = None) -> dict:
        """
        规划从 A 到 B 的多种交通方案

        返回格式：
        {
            "options": [
                {"mode": "driving", "time_min": ..., "distance_km": ..., "cost_yuan": ..., "steps": [...]},
                {"mode": "transit", ...},
                ...
            ],
            "recommended": "driving",
            "recommend_reason": "...",
            "traffic_note": "...",
        }
        """
        if modes is None:
            modes = ["driving", "transit", "walking", "cycling", "taxi"]
        if hour is None:
            hour = datetime.now().hour

        options = []
        direct_dist = haversine(from_lon, from_lat, to_lon, to_lat)
        direct_dist_km = direct_dist / 1000

        # === 驾车 ===
        if "driving" in modes:
            driving = self._plan_driving(from_lon, from_lat, to_lon, to_lat, hour)
            if driving:
                driving["mode"] = "driving"
                options.append(driving)

        # === 打车 ===
        if "taxi" in modes:
            taxi = self._plan_taxi(from_lon, from_lat, to_lon, to_lat, hour, direct_dist_km)
            if taxi:
                taxi["mode"] = "taxi"
                options.append(taxi)

        # === 公交/地铁 ===
        if "transit" in modes:
            transit = self._plan_transit(from_lon, from_lat, to_lon, to_lat)
            if transit:
                transit["mode"] = "transit"
                options.append(transit)

        # === 步行 ===
        if "walking" in modes:
            walk_time = round(direct_dist / 80)  # 80m/min
            options.append({
                "mode": "walking",
                "time_min": walk_time,
                "distance_km": round(direct_dist_km, 2),
                "cost_yuan": 0,
                "calories_kcal": round(direct_dist_km * 60),
                "steps": [f"步行约{walk_time}分钟 ({round(direct_dist_km, 1)}公里)"],
                "suitable": direct_dist_km <= 3,
                "note": "适合短距离" if direct_dist_km <= 3 else "距离较长，建议选择其他方式",
            })

        # === 骑行 ===
        if "cycling" in modes:
            cycle_time = round(direct_dist / 250)  # 15km/h = 250m/min
            options.append({
                "mode": "cycling",
                "time_min": cycle_time,
                "distance_km": round(direct_dist_km * 1.1, 2),
                "cost_yuan": 1.5 if direct_dist_km <= 3 else 3.0,  # 共享单车
                "calories_kcal": round(direct_dist_km * 30),
                "steps": [f"骑行约{cycle_time}分钟"],
                "suitable": direct_dist_km <= 8,
                "note": "适合中短距离" if direct_dist_km <= 8 else "距离较长，建议地铁",
            })

        # === 组合（驾车到地铁站 + 地铁）===
        if "combined" in modes and direct_dist_km > 10:
            combined = self._plan_combined(from_lon, from_lat, to_lon, to_lat, hour)
            if combined:
                combined["mode"] = "combined"
                options.append(combined)

        # 排序：按时间
        options.sort(key=lambda x: x.get("time_min", 999))

        # 推荐
        recommended = None
        if options:
            recommended = options[0]["mode"]
            reason = self._recommend_reason(options[0], direct_dist_km, hour)

        return {
            "origin": {"longitude": from_lon, "latitude": from_lat},
            "destination": {"longitude": to_lon, "latitude": to_lat},
            "straight_line_distance_km": round(direct_dist_km, 2),
            "options": options,
            "recommended": recommended,
            "recommend_reason": reason,
            "traffic_note": self._traffic_note(hour),
            "generated_at": datetime.now().isoformat(),
        }

    def _plan_driving(self, flon, flat, tlon, tlat, hour):
        """驾车路径规划"""
        from_node = self.road.find_nearest_node(flon, flat)
        to_node = self.road.find_nearest_node(tlon, tlat)

        if not from_node or not to_node:
            # 路网覆盖不到 → 直线距离估算
            direct_dist = haversine(flon, flat, tlon, tlat)
            avg_speed = 30 * (1 - congestion_by_hour(hour) * 0.5)  # km/h
            time_min = round(direct_dist / (avg_speed * 1000 / 60))
            return {
                "time_min": max(5, time_min),
                "distance_km": round(direct_dist / 1000, 2),
                "cost_yuan": round(direct_dist / 1000 * 2.3, 1),  # 燃油费
                "congestion_level": self._congestion_label(hour),
                "steps": [f"全程约{max(5, time_min)}分钟"],
                "note": "路网覆盖有限，为直线估算",
            }

        # Dijkstra 在路网上
        from_nid, from_dist = from_node
        to_nid, to_dist = to_node

        # 简化：用直线距离 + 路网系数
        direct_dist = haversine(flon, flat, tlon, tlat)
        # 步行到路网节点 + 路网驾驶 + 步行到目的地
        walk_to = from_dist / 80  # min
        walk_from = to_dist / 80
        road_dist = direct_dist * 1.3  # 路网比直线多 30%
        avg_speed = 35 * (1 - congestion_by_hour(hour) * 0.5)
        drive_time = road_dist / (avg_speed * 1000 / 60)
        total_time = round(walk_to + drive_time + walk_from)

        # 过路费（高速酌情）
        toll = 0
        if direct_dist > 20000:
            toll = random.choice([5, 10, 15])

        return {
            "time_min": max(5, total_time),
            "distance_km": round(road_dist / 1000, 2),
            "cost_yuan": round(road_dist / 1000 * 2.3 + toll, 1),
            "toll_yuan": toll,
            "congestion_level": self._congestion_label(hour),
            "parking_note": self._parking_suggestion(tlon, tlat),
            "steps": [
                f"步行{round(walk_to)}分钟至最近道路",
                f"驾车约{round(drive_time)}分钟 ({round(road_dist/1000,1)}公里)",
                f"步行{round(walk_from)}分钟至目的地",
            ],
        }

    def _plan_taxi(self, flon, flat, tlon, tlat, hour, direct_dist_km):
        """打车规划 = 驾车时间 + 等车时间 + 打车费用"""
        driving = self._plan_driving(flon, flat, tlon, tlat, hour)
        if not driving:
            return None
        wait_time = random.randint(2, 8)
        # 北京出租车价格：起步 13元/3km，后续 2.3元/km
        if direct_dist_km <= 3:
            fare = 13
        else:
            fare = 13 + (direct_dist_km - 3) * 2.3
        # 夜间加价 (23:00-05:00)
        if hour >= 23 or hour <= 5:
            fare *= 1.2
        # 拥堵加价
        if congestion_by_hour(hour) > 0.7:
            fare *= random.uniform(1.1, 1.3)

        return {
            "time_min": driving["time_min"] + wait_time,
            "distance_km": driving["distance_km"],
            "cost_yuan": round(fare, 1),
            "wait_time_min": wait_time,
            "congestion_level": self._congestion_label(hour),
            "steps": [
                f"预计等待{wait_time}分钟接驾",
                f"行程约{driving['time_min']}分钟",
                f"预计费用{round(fare)}元",
            ],
        }

    def _plan_transit(self, flon, flat, tlon, tlat):
        """地铁/公交路径规划"""
        from_st = self.metro.find_nearest_station(flon, flat)
        to_st = self.metro.find_nearest_station(tlon, tlat)

        if not from_st or not to_st:
            return self._fallback_transit(flon, flat, tlon, tlat)

        from_name, walk_to = from_st
        to_name, walk_from = to_st

        walk_to_min = round(walk_to / 80)
        walk_from_min = round(walk_from / 80)

        metro_path = self.metro.find_path(from_name, to_name)
        if not metro_path:
            return self._fallback_transit(flon, flat, tlon, tlat)

        total_time = walk_to_min + metro_path["total_time_min"] + walk_from_min
        total_dist = walk_to + metro_path["total_distance_m"] + walk_from

        steps = [
            f"步行{walk_to_min}分钟至{from_name} ({walk_to}m)",
        ]
        for seg in metro_path["segments"]:
            steps.append(f"{seg['from']} → {seg['to']} ({seg['line']}, {seg['time_min']}分钟)")
        steps.append(f"步行{walk_from_min}分钟至目的地 ({walk_from}m)")

        return {
            "time_min": total_time,
            "distance_km": round(total_dist / 1000, 2),
            "cost_yuan": metro_path["fare_yuan"],
            "metro_time_min": metro_path["total_time_min"],
            "walk_time_min": walk_to_min + walk_from_min,
            "transfers": metro_path["transfers"],
            "metro_stations_traversed": len(metro_path["stations"]),
            "steps": steps,
        }

    def _fallback_transit(self, flon, flat, tlon, tlat):
        """地铁不可用时的公交估算"""
        direct_dist = haversine(flon, flat, tlon, tlat)
        # 公交约 20km/h
        time_min = round(direct_dist / (20000 / 60)) + 10  # +10分钟等车
        return {
            "time_min": max(15, time_min),
            "distance_km": round(direct_dist / 1000, 2),
            "cost_yuan": 2,  # 公交基础价
            "metro_time_min": 0,
            "walk_time_min": 0,
            "transfers": random.randint(0, 2),
            "metro_stations_traversed": 0,
            "steps": [f"公交约{max(15, time_min)}分钟（无地铁直达方案）"],
            "note": "该区域地铁覆盖有限，建议公交或打车",
        }

    def _plan_combined(self, flon, flat, tlon, tlat, hour):
        """组合：驾车到地铁站 + 地铁"""
        from_st = self.metro.find_nearest_station(flon, flat)
        to_st = self.metro.find_nearest_station(tlon, tlat)
        if not from_st or not to_st:
            return None

        from_name, drive_to = from_st
        to_name, walk_from = to_st

        drive_time = round(drive_to / (40000 / 60))  # 40km/h local driving
        walk_from_min = round(walk_from / 80)

        metro_path = self.metro.find_path(from_name, to_name)
        if not metro_path:
            return None

        total_time = drive_time + metro_path["total_time_min"] + walk_from_min
        return {
            "time_min": total_time,
            "distance_km": round((drive_to + metro_path["total_distance_m"] + walk_from) / 1000, 2),
            "cost_yuan": metro_path["fare_yuan"] + round(drive_to / 1000 * 2.3, 1),
            "drive_time_min": drive_time,
            "metro_time_min": metro_path["total_time_min"],
            "transfers": metro_path["transfers"],
            "steps": [
                f"驾车{drive_time}分钟至{from_name}站",
                f"地铁约{metro_path['total_time_min']}分钟 ({len(metro_path['stations'])}站)",
                f"步行{walk_from_min}分钟至目的地",
            ],
            "note": "P+R 模式，避开市中心拥堵",
        }

    # --- 辅助 ---

    def _congestion_label(self, hour):
        c = congestion_by_hour(hour)
        if c < 0.2: return "畅通"
        if c < 0.5: return "缓行"
        if c < 0.75: return "拥堵"
        return "严重拥堵"

    def _traffic_note(self, hour):
        c = congestion_by_hour(hour)
        if c > 0.7:
            return f"当前{self._congestion_label(hour)}，建议考虑地铁出行"
        return f"当前路况{self._congestion_label(hour)}"

    def _parking_suggestion(self, lon, lat):
        """根据位置给出停车建议"""
        # 市区核心区停车贵且难
        if 116.35 < lon < 116.48 and 39.88 < lat < 39.95:
            return "市中心停车位紧张，建议使用商场停车场(8-15元/小时)"
        return "停车位较充足(4-8元/小时)"

    def _recommend_reason(self, best_option, distance_km, hour):
        mode = best_option.get("mode", "")
        time = best_option.get("time_min", 0)
        if mode == "transit" and distance_km > 5:
            return f"地铁最快，预计{time}分钟，避开地面拥堵"
        if mode == "driving" and distance_km < 5:
            return f"距离较近，驾车{time}分钟直达"
        if mode == "walking" and distance_km < 1.5:
            return f"步行仅需{time}分钟，健康环保"
        if mode == "cycling" and distance_km < 5:
            return f"骑行{time}分钟，灵活方便"
        return f"综合最优方案，预计{time}分钟"


# ============================================================
# 第4部分：预计算常用路线 + 设施索引
# ============================================================

def build_routes_index(planner: RoutePlanner):
    """预计算用户常用起终点路线（家↔公司、家↔学校等）"""
    # 从 butler 用户数据中的常用位置
    common_routes = [
        # (路线名, 起点lon, 起点lat, 终点lon, 终点lat)
        # 小琴
        ("家(常营)→公司(望京)", 116.59, 39.925, 116.48, 39.995),
        ("家(常营)→果果幼儿园", 116.59, 39.925, 116.58, 39.920),
        # 小冉
        ("家(东四环)→蓝色港湾", 116.48, 39.915, 116.472, 39.950),
        ("家(东四环)→朝阳大悦城", 116.48, 39.915, 116.515, 39.920),
        # 小晴
        ("宿舍(海淀)→实习公司", 116.32, 39.965, 116.315, 39.980),
        ("宿舍(海淀)→五道口", 116.32, 39.965, 116.342, 39.995),
        # 通用
        ("北京南站→国贸", 116.385, 39.865, 116.460, 39.910),
        ("国贸→首都机场T3", 116.460, 39.910, 116.615, 40.055),
        ("西单→北京西站", 116.380, 39.912, 116.330, 39.895),
    ]

    routes = {}
    for name, flon, flat, tlon, tlat in common_routes:
        result = planner.plan_route(flon, flat, tlon, tlat, hour=9)
        routes[name] = result

    return routes


def build_facility_index(enriched_dir: str, road_network: RoadNetwork):
    """
    为路网节点索引附近设施（加油站/充电站/便利店/卫生间/停车场）
    """
    facilities = {
        "gas_stations": [],
        "charging_stations": [],
        "convenience_stores": [],
        "parking_lots": [],
    }

    # 加载富化数据
    type_files = {
        "gas_stations": "gas_stations.json",
        "charging_stations": "charging_stations.json",
        "convenience_stores": "convenience_stores.json",
        "parking_lots": "parking_lots.json",
    }

    loaded = {}
    for ftype, fname in type_files.items():
        path = os.path.join(enriched_dir, fname)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                loaded[ftype] = json.load(f)
        else:
            loaded[ftype] = []

    # 为每个路网节点找最近设施
    facility_index = {}
    for node_id, (nlon, nlat) in road_network.nodes.items():
        node_facilities = {}
        for ftype, pois in loaded.items():
            nearby = []
            for poi in pois:
                plon = poi.get("longitude", 0)
                plat = poi.get("latitude", 0)
                if plon and plat:
                    dist = haversine(nlon, nlat, plon, plat)
                    if dist < 3000:  # 3km 内
                        nearby.append({
                            "name": poi["name"],
                            "distance_m": int(dist),
                            "address": poi.get("address", ""),
                            "id": poi.get("id"),
                        })
            nearby.sort(key=lambda x: x["distance_m"])
            node_facilities[ftype] = nearby[:3]  # 最多3个
        facility_index[node_id] = node_facilities

    return facility_index


# ============================================================
# 第5部分：主编排
# ============================================================

def main():
    print("=" * 60)
    print("Transport Network Builder")
    print("=" * 60)

    # 1. 加载富化的地铁站数据
    metro_path = "data/enriched/metro_stations.json"
    if not os.path.exists(metro_path):
        print("[!] 请先运行 data_generator.py 生成地铁站数据")
        return

    with open(metro_path, "r", encoding="utf-8") as f:
        enriched_metro = json.load(f)

    # 2. 构建地铁网络
    print("\n[1/4] Building metro network...")
    metro_net = MetroNetwork()
    metro_net.build(enriched_metro)

    # 3. 构建路网
    print("[2/4] Building road network...")
    road_net = RoadNetwork()
    road_net.build()

    # 4. 预计算常用路线
    print("[3/4] Pre-computing common routes...")
    planner = RoutePlanner(metro_net, road_net)
    routes_index = build_routes_index(planner)

    # 5. 设施索引
    print("[4/4] Indexing roadside facilities...")
    facility_index = build_facility_index("data/enriched", road_net)

    # 6. 保存
    os.makedirs("data/enriched", exist_ok=True)

    # 地铁网络摘要
    with open("data/enriched/metro_network.json", "w", encoding="utf-8") as f:
        json.dump(metro_net.to_dict(), f, ensure_ascii=False, indent=2)

    # 常用路线
    with open("data/enriched/routes_index.json", "w", encoding="utf-8") as f:
        json.dump(routes_index, f, ensure_ascii=False, indent=2)

    # 设施索引
    with open("data/enriched/facility_index.json", "w", encoding="utf-8") as f:
        json.dump(facility_index, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] Saved: metro_network.json, routes_index.json, facility_index.json")
    print(f"  Metro: {metro_net.to_dict()['station_count']} stations")
    print(f"  Roads: {len(road_net.edges)} road segments")
    print(f"  Routes: {len(routes_index)} pre-computed")


if __name__ == "__main__":
    main()
