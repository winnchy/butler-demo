"""
基于 beijing_seeds.json 分类型丰富化管道（重写版）

核心改进：
1. 菜系从店名推断而非 typecode
2. 交通用真实地铁站坐标计算距离
3. 评价菜系对口而非通用模板
4. 特殊服务用条件概率而非纯随机
5. 营业时间按菜系差异化
6. 连锁/品牌检测用真实品牌词库
"""

import json
import random
import os
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from config import *

# ============================================================
# 第0层：预加载种子数据中的参考坐标（用于算真实距离）
# ============================================================

def load_seed_references(seeds: dict) -> dict:
    """
    预加载种子中的地铁站和公交站坐标，用于后续计算真实交通距离
    """
    refs = {"metro": [], "bus": []}

    for item in seeds.get("metro_stations", []):
        lon, lat = parse_lonlat(item.get("location", ""))
        # 从 address 字段解析线路（种子数据：address="10号线;1号线/八通线"）
        addr = item.get("address", "")
        lines = [l.strip() for l in addr.split(";") if "号线" in l or "线" in l]
        if not lines:
            # 尝试匹配站名
            matched, _, _ = match_metro_station(item["name"].replace("(地铁站)", ""))
            lines = matched
        refs["metro"].append({
            "name": item["name"].replace("(地铁站)", "站"),
            "lines": lines if lines else ["未知线路"],
            "lon": lon, "lat": lat,
        })

    for item in seeds.get("bus_stations", []):
        lon, lat = parse_lonlat(item.get("location", ""))
        refs["bus"].append({
            "name": item["name"],
            "lon": lon, "lat": lat,
        })

    return refs

# ============================================================
# 第1层：通用工具（使用预加载的参考坐标）
# ============================================================

def generate_transport(lon: float, lat: float, refs: dict, address: str = "",
                       mall_list: List[str] = None) -> dict:
    """计算真实的最近地铁站和公交站距离"""
    transport = {
        "nearest_metro": None,
        "nearest_bus": None,
        "in_mall": False,
        "mall_name": None,
        "direct_metro_access": False,
    }

    # 最近地铁站（真实距离计算）
    metro_dists = []
    for m in refs["metro"]:
        dist = haversine(lon, lat, m["lon"], m["lat"])
        metro_dists.append((dist, m))
    metro_dists.sort(key=lambda x: x[0])

    if metro_dists and metro_dists[0][0] < 3000:  # 3km 内
        dist, st = metro_dists[0]
        walking_min = round(dist / 80)  # 80m/min 步行
        exit_letter = random.choice(["A", "B", "C", "D", "E", "F", "G"])
        transport["nearest_metro"] = {
            "station_name": st["name"],
            "lines": st["lines"],
            "exit": f"{exit_letter}口",
            "distance_meters": int(dist),
            "walking_minutes": walking_min,
        }
        # 判断是否地铁直通（地址含地铁站名）
        if st["name"].replace("站", "") in address:
            transport["direct_metro_access"] = True

    # 最近公交站
    bus_dists = []
    for b in refs["bus"]:
        dist = haversine(lon, lat, b["lon"], b["lat"])
        bus_dists.append((dist, b))
    bus_dists.sort(key=lambda x: x[0])

    if bus_dists and bus_dists[0][0] < 1000:
        dist, st = bus_dists[0]
        transport["nearest_bus"] = {
            "station_name": st["name"],
            "distance_meters": int(dist),
            "walking_minutes": round(dist / 80),
        }

    # 是否在商场内
    if mall_list and address:
        mall_name = is_in_mall(address, mall_list)
        if mall_name:
            transport["in_mall"] = True
            transport["mall_name"] = mall_name

    return transport


# ============================================================
# 第2层：各类型丰富化函数
# ============================================================

# --- 餐厅（最复杂） ---

def enrich_restaurant(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    name = item.get("name", "未知餐厅")
    address = item.get("address", "")
    district = item.get("adname", "朝阳区")
    biz_area = item.get("business_area", "")
    if isinstance(biz_area, list):
        biz_area = biz_area[0] if biz_area else ""
    typecode = item.get("typecode", "")
    seed_price = safe_float(item.get("avg_price"), None) or None
    seed_rating = safe_float(item.get("rating"), None) or None

    # 菜系：店名关键字匹配
    cuisine, sub_cuisine = match_cuisine(name, typecode)

    # 评分
    rating = seed_rating if seed_rating else round(random.uniform(3.5, 4.8), 1)

    # 人均价格
    avg_price, price_level = infer_price_level(name, biz_area, seed_price)

    # 连锁/本地独有
    brand = detect_chain(name)

    # 交通：真实坐标计算
    transport = generate_transport(lon, lat, refs, address, mall_names)

    # 营业时间：按菜系差异化
    bh = BUSINESS_HOURS_BY_CUISINE.get(cuisine, {"weekday": "10:00-21:30", "weekend": "10:00-22:00", "break_time": None})
    # 24小时营业的随机少数
    if random.random() < 0.03:
        bh = {"weekday": "00:00-24:00", "weekend": "00:00-24:00", "break_time": None}

    # 包厢：条件概率
    has_private_room = False
    if any(w in name for w in ["饭店", "大饭店", "酒店", "酒楼", "宴会"]):
        has_private_room = random.random() < 0.85
    elif cuisine in ["粤菜", "京菜", "川菜", "海鲜", "酒店餐饮"]:
        has_private_room = random.random() < 0.45
    elif cuisine in ["快餐/简餐", "饮品", "甜品/烘焙", "咖啡厅", "酒吧"]:
        has_private_room = random.random() < 0.05
    else:
        has_private_room = random.random() < 0.25

    pvt_room = {
        "available": has_private_room,
        "min_people": random.choice([4, 6, 8, 10]) if has_private_room else 0,
        "max_people": random.choice([12, 16, 20, 30]) if has_private_room else 0,
        "has_min_charge": random.random() < 0.5 if has_private_room else False,
        "min_charge_yuan": random.choice([500, 800, 1000, 1500, 2000]) if has_private_room else 0,
    }

    # 排队/预订
    queuing = {
        "online_queuing": random.random() < 0.6,
        "queuing_platform": random.choice(["美团", "大众点评", "美味不用等"]),
        "supports_reservation": random.random() < (0.75 if has_private_room else 0.45),
        "reservation_advance_days": random.choice([1, 3, 7, 14]),
    }

    # 团购（条件概率：中低端更可能有）
    has_deal = random.random() < (0.75 if price_level in ["中端", "经济实惠"] else 0.4)
    group_deals = []
    if has_deal:
        person_options = [2, 2, 3, 4, 4, 6]
        people = random.choice(person_options)
        orig = round(avg_price * people * random.uniform(1.0, 1.3))
        disc = round(avg_price * people * random.uniform(0.55, 0.8))
        group_deals.append({
            "name": f"{random.choice(['双人甄选','双人特惠','三人欢聚','四人超值','家庭'])}套餐",
            "people": people,
            "original_price": orig,
            "discount_price": disc,
            "valid_time": random.choice(["周一至周五 11:00-14:00", "周一至周日全天", "周末及节假日"]),
            "valid_until": (datetime.now() + timedelta(days=random.randint(7, 60))).strftime("%Y-%m-%d"),
        })

    # 代金券
    has_voucher = random.random() < (0.55 if price_level in ["中端", "中高端"] else 0.3)
    vouchers = []
    if has_voucher:
        thresholds = [100, 150, 200, 300, 500]
        th = random.choice(thresholds[:3]) if avg_price < 80 else random.choice(thresholds)
        vouchers.append({
            "name": f"满{th}减{random.choice([20,30,50,80])}",
            "threshold": th,
            "discount": random.choice([20, 30, 50, 80]),
            "valid_days": random.choice(["周一至周五", "周末", "全天"]),
            "stackable": False,
            "valid_until": (datetime.now() + timedelta(days=random.randint(14, 90))).strftime("%Y-%m-%d"),
        })

    # 优惠活动
    has_promo = random.random() < 0.45
    promotions = []
    if has_promo:
        promo_type = random.choice(["午市特惠", "晚市折扣", "新店立减", "会员日", "节日限定"])
        promotions.append({
            "type": promo_type,
            "discount": f"{random.choice([6.8, 7.8, 8.0, 8.5, 8.8, 9.0])}折",
            "time_slot": random.choice(["11:00-14:00", "17:00-20:00", "全天"]),
            "applicable_days": random.choice(["周一至周五", "周末", "全天"]),
            "valid_until": (datetime.now() + timedelta(days=random.randint(7, 60))).strftime("%Y-%m-%d"),
        })

    # 评价：菜系对口
    reviews = generate_cuisine_reviews(cuisine, rating)

    # 氛围：菜系关联
    style_pool = ATMOSPHERE_BY_CUISINE.get(cuisine, ATMOSPHERE_STYLES)
    atmosphere = {
        "style": random.choice(style_pool),
        "noise_level": random.choice(["安静", "适中"] if cuisine in ["日料", "粤菜", "西餐", "茶馆"] else NOISE_LEVELS),
        "lighting": random.choice(LIGHTING_TYPES),
        "suitable_for": random_pick(SUITABLE_FOR, random.randint(2, 4)),
        "highlights": random_pick(HIGHLIGHT_FEATURES, random.randint(1, 3)),
    }

    # 特殊服务：条件概率（非纯随机）
    # 生日服务：中高端 → 概率高
    bday_prob = 0.5 if price_level in ["高端", "中高端"] else 0.3
    if cuisine in ["快餐/简餐", "饮品"]:
        bday_prob = 0.05
    has_birthday = random.random() < bday_prob

    # 亲子设施：店名/菜系驱动
    kids_prob = 0.15  # 基础概率
    if any(w in name for w in ["亲子", "家庭", "儿童", "宝宝"]):
        kids_prob = 0.85
    elif cuisine in ["快餐/简餐", "粤菜"]:
        kids_prob = 0.4
    has_kids = random.random() < kids_prob

    # 宠物友好：户外/咖啡馆更高
    pet_prob = 0.08
    if cuisine in ["咖啡厅", "烧烤", "农家菜"]:
        pet_prob = 0.25
    if atmosphere.get("highlights") and "露台" in atmosphere["highlights"]:
        pet_prob = 0.4
    has_pets = random.random() < pet_prob

    # 停车：商场内 → 几乎都有
    if transport.get("in_mall"):
        parking_prob = 0.95
    elif district in ["东城区", "西城区"]:
        parking_prob = 0.15  # 老城区停车难
    else:
        parking_prob = 0.5
    has_parking = random.random() < parking_prob

    # 商务宴请
    biz_prob = 0.35 if (has_private_room and avg_price > 150) else 0.05
    has_biz = random.random() < biz_prob

    special_services = {
        "birthday": {
            "available": has_birthday,
            "services": random_pick(["免费长寿面", "生日歌", "果盘", "小蛋糕", "包厢布置"], random.randint(1, 3)) if has_birthday else [],
            "need_reservation": True,
        },
        "kids": {
            "baby_seat": random.random() < (0.8 if has_kids else 0.15),
            "kids_menu": random.random() < (0.6 if has_kids else 0.1),
            "play_area": random.random() < (0.3 if has_kids else 0.05),
            "kids_cutlery": random.random() < (0.6 if has_kids else 0.1),
        },
        "pets": {
            "pet_allowed": has_pets,
            "pet_rest_area": random.random() < (0.3 if has_pets else 0.03),
            "pet_menu": random.random() < (0.15 if has_pets else 0.01),
        },
        "parking": {
            "available": has_parking,
            "free_parking": random.random() < 0.25 if has_parking else False,
            "fee_per_hour": random.choice([4, 6, 8, 10, 12, 15]) if has_parking and not transport.get("in_mall") else None,
        },
        "business_dining": {
            "available": has_biz,
            "has_projector": random.random() < 0.25 if has_biz else False,
            "private_room_count": random.randint(1, 12) if has_biz else 0,
        },
    }

    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": name,
        "cuisine": cuisine,
        "sub_cuisine": sub_cuisine,
        "price_level": price_level,
        "rating": rating,
        "avg_price": avg_price,
        "address": address,
        "district": district,
        "business_circle": biz_area,
        "latitude": lat,
        "longitude": lon,
        "brand": brand,
        "transport": transport,
        "business_hours": bh,
        "queuing": queuing,
        "private_room": pvt_room,
        "group_deals": group_deals,
        "vouchers": vouchers,
        "promotions": promotions,
        "reviews": reviews,
        "atmosphere": atmosphere,
        "special_services": special_services,
        "dynamic": {
            "current_queue": random.randint(0, 12),
            "estimated_wait_min": 0,
            "status": "有位",
            "available_seats": random.randint(0, 30),
            "last_updated": datetime.now().isoformat(),
        }
    }


# --- 宠物服务 ---

def enrich_pet_service(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    name = item.get("name", "未知宠物服务")

    # 从店名推断子类型
    if any(w in name for w in ["医院", "诊所", "医疗", "兽医"]):
        svc_type = "宠物医院"
    elif any(w in name for w in ["美容", "造型", "洗澡"]):
        svc_type = "宠物美容"
    elif any(w in name for w in ["寄养", "托管", "酒店"]):
        svc_type = "宠物寄养"
    elif any(w in name for w in ["用品", "店", "商城", "荟聚", "超市"]):
        svc_type = "宠物用品店"
    elif any(w in name for w in ["训练", "学校", "培训"]):
        svc_type = "宠物训练"
    elif any(w in name for w in ["乐园", "公园", "游泳"]):
        svc_type = "宠物乐园"
    elif any(w in name for w in ["殡葬", "火化", "墓地", "纪念"]):
        svc_type = "宠物殡葬"
    else:
        svc_type = random.choice(PET_SERVICE_TYPES)

    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": name,
        "type": svc_type,
        "sub_types": random_pick(["体检", "疫苗", "驱虫", "绝育", "洗澡", "美容", "寄养", "训练", "SPA", "药浴"], random.randint(2, 5)),
        "rating": safe_float(item.get("rating"), round(random.uniform(3.5, 5.0), 1)),
        "address": item.get("address", ""),
        "district": item.get("adname", ""),
        "latitude": lat, "longitude": lon,
        "business_hours": f"{random.randint(8,10)}:00-{random.randint(19,22)}:00",
        "emergency_service": random.random() < 0.25 if svc_type == "宠物医院" else False,
        "pet_types_served": random_pick(PET_SPECIES, random.randint(1, 5)),
        "dog_size_limit": random.choice(["不限", "不限", "小型犬(<10kg)", "中小型犬(<25kg)"]),
        "transport": generate_transport(lon, lat, refs, item.get("address", ""), mall_names),
        "rating_count": random.randint(10, 600),
        "dynamic": {"current_queue": random.randint(0, 5), "status": "营业中"},
    }


# --- 加油站 ---

def enrich_gas_station(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    oil_types = random_pick(GAS_TYPES, random.randint(2, 4))
    oil_prices = {}
    for oil in oil_types:
        low, high = GAS_PRICE_RANGE.get(oil, (7.0, 8.5))
        oil_prices[oil] = round(random.uniform(low, high), 2)

    is_24h = random.random() < 0.7
    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": item["name"],
        "type": "加油站",
        "address": item.get("address", ""),
        "district": item.get("adname", ""),
        "latitude": lat, "longitude": lon,
        "oil_types": oil_types,
        "oil_prices": oil_prices,
        "is_24h": is_24h,
        "business_hours": "00:00-24:00" if is_24h else f"06:00-{random.randint(22,23)}:00",
        "services": random_pick(["便利店", "洗车", "加气", "卫生间", "ATM", "免费充气"], random.randint(1, 4)),
        "transport": generate_transport(lon, lat, refs, item.get("address", ""), mall_names),
        "dynamic": {"is_operational": True, "last_updated": datetime.now().isoformat()},
    }


# --- 商场 ---

def enrich_mall(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    name = item.get("name", "")
    floors = random.randint(3, 8)
    # 更大更知名的商场 → 更多停车位
    if any(w in name for w in ["天街", "大悦城", "太古里", "万象", "万达", "国贸", "金融街"]):
        floors = random.randint(5, 8)
        parking_spaces = random.randint(800, 3000)
    elif any(w in name for w in ["小商品", "步行街", "商厦"]):
        floors = random.randint(2, 5)
        parking_spaces = random.randint(50, 400)
    else:
        parking_spaces = random.randint(150, 1500)

    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": name,
        "type": "商场",
        "address": item.get("address", ""),
        "district": item.get("adname", ""),
        "business_circle": item.get("business_area", "") if not isinstance(item.get("business_area"), list) else "",
        "latitude": lat, "longitude": lon,
        "business_hours": f"{random.randint(9,10)}:00-{random.randint(21,22)}:00",
        "floors": floors,
        "has_supermarket": random.random() < 0.7,
        "has_cinema": random.random() < 0.6,
        "has_food_court": random.random() < 0.85,
        "pet_policy": random.choice(["宠物可寄存", "宠物可寄存", "宠物禁止入内", "宠物友好(可入内)", "小型犬可入(需装笼)"]),
        "parking": {"available": True, "total_spaces": parking_spaces, "fee_per_hour": random.choice([4, 6, 6, 8, 10, 12])},
        "transport": generate_transport(lon, lat, refs, item.get("address", ""), mall_names),
        "dynamic": {"crowdedness": random.choice(["较空", "正常", "正常", "较拥挤"])},
    }


# --- 医院 ---

def enrich_hospital(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    name = item.get("name", "")

    # 从名推断等级
    if any(w in name for w in ["人民", "协和", "附属", "大学", "中心", "总医院"]):
        level = "三级甲等"
    elif any(w in name for w in ["中医", "中西医", "儿童", "口腔", "肿瘤", "骨科"]):
        level = random.choice(["三级甲等", "三级乙等"])
    elif any(w in name for w in ["社区", "卫生服务", "卫生院"]):
        level = "社区卫生服务中心"
    else:
        level = random.choice(HOSPITAL_LEVELS)

    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": name,
        "type": "医院",
        "level": level,
        "address": item.get("address", ""),
        "district": item.get("adname", ""),
        "latitude": lat, "longitude": lon,
        "departments": random_pick(HOSPITAL_DEPARTMENTS, random.randint(4, 9)),
        "emergency": level in ["三级甲等", "三级乙等"] or random.random() < 0.5,
        "business_hours": "00:00-24:00" if level.startswith("三级") else f"08:00-{random.randint(17,20)}:00",
        "transport": generate_transport(lon, lat, refs, item.get("address", ""), mall_names),
        "dynamic": {"current_queue_estimate_min": random.randint(5, 90) if level.startswith("三级") else random.randint(5, 30)},
    }


# --- 酒店 ---

def enrich_hotel(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    name = item.get("name", "")

    # 从名推断星级
    if any(w in name for w in ["国际", "皇冠", "希尔顿", "万豪", "洲际", "喜来登", "威斯汀", "凯宾斯基", "半岛"]):
        star = "五星级"
    elif any(w in name for w in ["大饭店", "酒店大堂", "贵宾楼"]):
        star = "五星级"
    elif any(w in name for w in ["快捷", "青年", "青旅", "民宿", "客栈"]):
        star = random.choice(["经济型", "精品民宿"])
    elif any(w in name for w in ["商务", "花园"]):
        star = "四星级"
    else:
        star = random.choice(HOTEL_STARS)

    star_amenities = {
        "五星级": ["免费WiFi", "健身房", "游泳池", "餐厅", "停车场", "商务中心", "SPA", "行政酒廊"],
        "四星级": ["免费WiFi", "健身房", "餐厅", "停车场", "商务中心"],
        "三星级": ["免费WiFi", "餐厅", "停车场"],
        "经济型": ["免费WiFi", "停车场"],
        "精品民宿": ["免费WiFi", "早餐", "停车位有限"],
    }
    amenities = random_pick(star_amenities.get(star, ["免费WiFi"]), random.randint(3, 6))

    # 宠物政策
    if star == "精品民宿":
        pet_policy = random.choice(["宠物友好", "小型犬可(需押金)", "需提前沟通"])
    elif star in ["经济型", "三星级"]:
        pet_policy = random.choice(["小型犬可(需押金)", "禁止宠物", "禁止宠物"])
    else:
        pet_policy = random.choice(["禁止宠物", "禁止宠物", "小型犬可(需押金)"])

    price_map = {"五星级": (800, 3000), "四星级": (400, 1200), "三星级": (200, 600), "经济型": (100, 300), "精品民宿": (200, 800)}
    pl, ph = price_map.get(star, (150, 600))

    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": name,
        "type": "酒店",
        "star": star,
        "address": item.get("address", ""),
        "district": item.get("adname", ""),
        "latitude": lat, "longitude": lon,
        "price_range_yuan": f"{random.randint(pl, (pl+ph)//2)}-{random.randint((pl+ph)//2, ph)}",
        "pet_policy": pet_policy,
        "amenities": amenities,
        "check_in_time": "14:00",
        "check_out_time": "12:00",
        "transport": generate_transport(lon, lat, refs, item.get("address", ""), mall_names),
        "dynamic": {"available_rooms": random.randint(0, 60)},
    }


# --- 公园/景区 ---

def enrich_park(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    name = item.get("name", "")

    # 门票
    if any(w in name for w in ["广场", "街区", "胡同", "旧址", "遗址", "纪念亭"]):
        ticket = 0
    elif any(w in name for w in ["森林", "湿地", "植物园", "动物园", "长城"]):
        ticket = random.choice([10, 15, 20, 30, 40, 60])
    else:
        ticket = random.choice([0, 0, 0, 5, 10, 20])

    # 宠物政策
    if any(w in name for w in ["广场", "街区", "胡同", "步道"]):
        pet_policy = "允许(需牵绳)"
    elif "森林公园" in name or "湿地" in name:
        pet_policy = "允许(需牵绳)"
    else:
        pet_policy = random.choice(["允许(需牵绳)", "允许(需牵绳)", "允许(有宠物专区)", "禁止宠物"])

    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": name,
        "type": "公园/景区",
        "address": item.get("address", ""),
        "district": item.get("adname", ""),
        "latitude": lat, "longitude": lon,
        "ticket_price_yuan": ticket,
        "open_time": f"06:00-{random.randint(20,22)}:00",
        "pet_policy": pet_policy,
        "facilities": random_pick(["儿童游乐场", "健身器材", "跑道", "湖泊", "凉亭", "卫生间", "停车场", "游客中心"], random.randint(3, 6)),
        "best_season": random.choice(["春季赏花", "秋季赏叶", "夏季避暑", "冬季看雪", "四季皆宜"]),
        "transport": generate_transport(lon, lat, refs, item.get("address", ""), mall_names),
        "dynamic": {"crowdedness": random.choice(["较空", "正常", "较拥挤"])},
    }


# --- 地铁站 ---

def enrich_metro(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    name = item.get("name", "").replace("(地铁站)", "")

    # 从 address 获取真实线路（种子数据 = "10号线;1号线/八通线"）
    addr = item.get("address", "")
    lines = []
    if addr:
        lines = [l.strip() for l in addr.split(";") if "号线" in l or "线" in l]
    if not lines:
        matched, _, _ = match_metro_station(name)
        lines = matched if matched else ["未知线路"]

    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": name,
        "type": "地铁站",
        "lines": lines,
        "is_transfer_station": len(lines) >= 2,
        "exits": [f"{l}口" for l in random_pick(["A","B","C","D","E","F","G","H"], random.randint(2, 6))],
        "address": addr,
        "district": item.get("adname", ""),
        "latitude": lat, "longitude": lon,
        "dynamic": {"crowdedness": random.choice(["低", "中等", "高"])},
    }


# --- 教育/文化 ---

def enrich_education(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    name = item.get("name", "")

    # 子类型推断
    if any(w in name for w in ["大学", "学院", "研究生院"]):
        sub_type = "高等教育"
        ticket = 0
    elif any(w in name for w in ["小学", "中学", "学校", "幼儿园"]):
        sub_type = "基础教育"
        ticket = 0
    elif any(w in name for w in ["图书馆", "书房", "书院"]):
        sub_type = "图书馆"
        ticket = 0
    elif any(w in name for w in ["博物馆", "博物院"]):
        sub_type = "博物馆"
        ticket = random.choice([0, 0, 20, 30, 60])
    elif any(w in name for w in ["美术馆", "艺术馆", "画廊"]):
        sub_type = "美术馆"
        ticket = random.choice([0, 20, 30, 60, 100])
    else:
        sub_type = "文化场所"
        ticket = random.choice([0, 0, 0, 10, 20])

    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": name,
        "type": "教育/文化",
        "sub_type": sub_type,
        "address": item.get("address", ""),
        "district": item.get("adname", ""),
        "latitude": lat, "longitude": lon,
        "ticket_price_yuan": ticket,
        "business_hours": f"09:00-{random.randint(17,21)}:00",
        "transport": generate_transport(lon, lat, refs, item.get("address", ""), mall_names),
        "dynamic": {"is_open": True},
    }


# --- 运动休闲 ---

def enrich_sports(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    name = item.get("name", "")

    if any(w in name for w in ["健身", "gym", "运动中心", "体育"]):
        sub_type = "健身房"
    elif any(w in name for w in ["游泳", "泳池"]):
        sub_type = "游泳池"
    elif any(w in name for w in ["瑜伽", "普拉提", "冥想"]):
        sub_type = "瑜伽/普拉提"
    elif any(w in name for w in ["羽毛球", "网球", "篮球", "足球", "乒乓球"]):
        sub_type = "球类场馆"
    elif any(w in name for w in ["舞蹈", "街舞", "芭蕾"]):
        sub_type = "舞蹈工作室"
    elif any(w in name for w in ["滑雪", "滑冰", "冰场"]):
        sub_type = "冰雪运动"
    else:
        sub_type = "综合运动"

    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": name,
        "type": "运动休闲",
        "sub_type": sub_type,
        "address": item.get("address", ""),
        "district": item.get("adname", ""),
        "latitude": lat, "longitude": lon,
        "business_hours": f"0{random.randint(7,9)}:00-{random.randint(21,23)}:00",
        "has_membership": random.random() < 0.6,
        "single_session_price": random.choice([30, 50, 80, 100, 150, 200]),
        "student_discount": random.random() < 0.4,
        "transport": generate_transport(lon, lat, refs, item.get("address", ""), mall_names),
        "dynamic": {"crowdedness": random.choice(["较空", "正常", "较拥挤"])},
    }


# --- 充电站 ---

def enrich_charging_station(item: dict, idx: int, refs: dict, mall_names: List[str]) -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": item["name"],
        "type": "充电站",
        "address": item.get("address", ""),
        "district": item.get("adname", ""),
        "latitude": lat, "longitude": lon,
        "charger_types": random_pick(["快充", "快充", "慢充", "超充"], random.randint(1, 3)),
        "total_spots": random.randint(4, 30),
        "available_spots": random.randint(0, 30),
        "power_kw": random.choice([60, 120, 150, 250]),
        "compatible_standards": random_pick(["国标", "特斯拉", "欧标"], random.randint(1, 2)),
        "price_per_kwh": round(random.uniform(0.8, 1.8), 2),
        "business_hours": "00:00-24:00" if random.random() < 0.8 else f"06:00-{random.randint(22,23)}:00",
        "transport": generate_transport(lon, lat, refs, item.get("address", ""), mall_names),
        "dynamic": {"available_now": random.randint(0, 20), "last_updated": datetime.now().isoformat()},
    }


# --- 默认处理（不需要特殊逻辑的类型） ---

def enrich_default(item: dict, idx: int, refs: dict, mall_names: List[str], poi_type: str = "default") -> dict:
    lon, lat = parse_lonlat(item.get("location", ""))
    return {
        "id": generate_id(),
        "source": "amap_seed+enriched",
        "name": item["name"],
        "type": poi_type,
        "address": item.get("address", ""),
        "district": item.get("adname", ""),
        "latitude": lat,
        "longitude": lon,
        "business_hours": f"{random.randint(8,10)}:00-{random.randint(17,22)}:00",
        "transport": generate_transport(lon, lat, refs, item.get("address", ""), mall_names),
    }


# ============================================================
# 第3层：类型分发表
# ============================================================

TYPE_DISPATCH = {
    "restaurants":          ("restaurants.json",           enrich_restaurant),
    "pet_services":         ("pet_services.json",          enrich_pet_service),
    "gas_stations":         ("gas_stations.json",          enrich_gas_station),
    "charging_stations":    ("charging_stations.json",     enrich_charging_station),
    "malls":                ("malls.json",                 enrich_mall),
    "supermarkets":         ("supermarkets.json",          enrich_default),
    "convenience_stores":   ("convenience_stores.json",    enrich_default),
    "hospitals":            ("hospitals.json",             enrich_hospital),
    "clinics":              ("clinics.json",               enrich_default),
    "pharmacies":           ("pharmacies.json",            enrich_default),
    "hotels":               ("hotels.json",                enrich_hotel),
    "parks_scenic":         ("parks.json",                 enrich_park),
    "metro_stations":       ("metro_stations.json",        enrich_metro),
    "bus_stations":         ("bus_stations.json",          enrich_default),
    "train_stations":       ("train_stations.json",        enrich_default),
    "airports":             ("airports.json",              enrich_default),
    "parking_lots":         ("parking_lots.json",          enrich_default),
    "education_culture":    ("education_culture.json",     enrich_education),
    "life_services":        ("life_services.json",         enrich_default),
    "sports_leisure":       ("sports_leisure.json",        enrich_sports),
    "banks":                ("banks.json",                 enrich_default),
    "companies":            ("companies.json",             enrich_default),
    "government":           ("government.json",            enrich_default),
}


# ============================================================
# 第4层：主编排逻辑
# ============================================================

def main():
    print("=" * 60)
    print("Beijing POI Enrichment Pipeline")
    print("=" * 60)

    # 加载种子数据
    with open("data/beijing_seeds.json", "r", encoding="utf-8") as f:
        seeds = json.load(f)

    # 预加载参考坐标
    refs = load_seed_references(seeds)
    print(f"\n[*] 参考数据: {len(refs['metro'])} 个地铁站, {len(refs['bus'])} 个公交站")

    # 提取商场名列表（用于判断 "在商场内"）
    mall_names = [m["name"] for m in seeds.get("malls", [])]

    # 确保输出目录
    os.makedirs("data/enriched", exist_ok=True)

    # 统计
    total = 0

    for label, items in seeds.items():
        if not items:
            continue

        output_file, enrich_func = TYPE_DISPATCH.get(label, (None, None))
        if output_file is None:
            print(f"[!] 未定义的类别: {label}，跳过")
            continue

        # 用对应的 enrich 函数处理
        if enrich_func:
            func = lambda item, idx, f=enrich_func: f(item, idx, refs, mall_names)
        else:
            func = lambda item, idx: enrich_default(item, idx, refs, mall_names, label)
        enriched = [func(item, i) for i, item in enumerate(items)]

        # 写入
        path = f"data/enriched/{output_file}"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(enriched, f, ensure_ascii=False, indent=2)

        total += len(enriched)
        print(f"[OK] {label:25s} → {output_file:30s} ({len(enriched)} 条)")

    print(f"\n[DONE] 全部完成！共丰富化 {total} 条 POI，输出到 data/enriched/")

if __name__ == "__main__":
    main()
