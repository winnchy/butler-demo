import requests
import json
import time

AMAP_KEY = " 高德地图API Key"  
CITY = "北京"

# 23 类 POI，覆盖所有 Skill 场景
POI_TYPES = [
    # 餐饮与购物
    {"types": "050000", "label": "restaurants", "desc": "餐饮"},
    {"types": "060100", "label": "malls", "desc": "商场"},
    {"types": "060200", "label": "supermarkets", "desc": "超市"},
    {"types": "060300", "label": "convenience_stores", "desc": "便利店"},

    # 生活与休闲
    {"types": "070000", "label": "life_services", "desc": "生活服务(洗衣/家政/快递)"},
    {"types": "080000", "label": "sports_leisure", "desc": "体育休闲(健身房/舞房)"},

    # 医疗
    {"types": "090100", "label": "hospitals", "desc": "医院"},
    {"types": "090200", "label": "clinics", "desc": "诊所"},
    {"types": "090400", "label": "pharmacies", "desc": "药店"},

    # 住宿与景点
    {"types": "100000", "label": "hotels", "desc": "酒店"},
    {"types": "110000", "label": "parks_scenic", "desc": "公园景点"},

    # 科教文化（学校/图书馆/博物馆/美术馆）
    {"types": "140000", "label": "education_culture", "desc": "学校/图书馆/博物馆"},

    # 交通设施
    {"types": "150500", "label": "metro_stations", "desc": "地铁站"},
    {"types": "150700", "label": "bus_stations", "desc": "公交站"},
    {"types": "010100", "label": "gas_stations", "desc": "加油站"},
    {"types": "010200", "label": "charging_stations", "desc": "充电站"},
    {"types": "150900", "label": "parking_lots", "desc": "停车场"},
    {"types": "150200", "label": "train_stations", "desc": "火车站"},
    {"types": "150100", "label": "airports", "desc": "机场"},

    # 金融与机构
    {"types": "160100", "label": "banks", "desc": "银行"},
    {"types": "170000", "label": "companies", "desc": "公司企业"},
    {"types": "180000", "label": "government", "desc": "政府机构"},

    # 宠物（小冉核心场景）
    {"types": "200000", "label": "pet_services", "desc": "宠物服务(医院/美容/寄养)"},
]

def fetch_pois(types, page=1):
    url = "https://restapi.amap.com/v3/place/text"
    params = {
        "key": AMAP_KEY,
        "types": types,
        "city": CITY,
        "offset": 20,
        "page": page,
        "extensions": "all"
    }
    resp = requests.get(url, params=params)
    return resp.json()

def build_all_seeds():
    all_data = {}
    for poi_type in POI_TYPES:
        label = poi_type["label"]
        print(f"正在抓取 {poi_type['desc']}...")
        items = []
        for page in range(1, 3):  # 每类2页
            data = fetch_pois(poi_type["types"], page)
            if data.get("status") == "1":
                for p in data.get("pois", []):
                    items.append({
                        "name": p["name"],
                        "location": p["location"],
                        "address": p.get("address", ""),
                        "adname": p.get("adname", ""),
                        "business_area": p.get("business_area", ""),
                        "typecode": p.get("typecode", ""),
                        "rating": p.get("biz_ext", {}).get("rating", ""),
                        "avg_price": p.get("biz_ext", {}).get("cost", ""),
                        "tel": p.get("tel", ""),
                    })
            time.sleep(0.15)
        # 去重
        seen = set()
        unique_items = []
        for item in items:
            if item["name"] not in seen:
                seen.add(item["name"])
                unique_items.append(item)
        all_data[label] = unique_items
        print(f"  → 获取 {len(unique_items)} 条")
        time.sleep(0.3)

    with open("data/beijing_seeds.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in all_data.values())
    print(f"\n✅ 抓取完成！共 {total} 条 POI 数据（23 个类别），已保存到 data/beijing_seeds.json")

if __name__ == "__main__":
    build_all_seeds()