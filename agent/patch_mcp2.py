"""Add missing handlers to mcp_bridge.py"""

with open('agent/mcp_bridge.py', 'r', encoding='utf-8') as f:
    content = f.read()

NEW_HANDLERS = '''
        elif name == "restaurant_take_number":
            r = requests.post(f"{BACKEND_URL}/api/dining/take-number", params={
                "restaurant_id": args.get("restaurant_id", 0),
                "user_id": args.get("user_id", ""),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_reserve":
            r = requests.post(f"{BACKEND_URL}/api/dining/reserve", json={
                "restaurant_id": args.get("restaurant_id", 0),
                "user_id": args.get("user_id", ""),
                "date": args.get("date", ""),
                "time": args.get("time", ""),
                "people": args.get("people", 2),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_detail":
            r = requests.get(f"{BACKEND_URL}/api/dining/detail", params={
                "restaurant_id": args.get("restaurant_id", 0),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_monitor":
            r = requests.post(f"{BACKEND_URL}/api/dining/monitor", json={
                "restaurant_id": args.get("restaurant_id", 0),
                "user_id": args.get("user_id", ""),
                "alert_threshold": args.get("alert_threshold", 5),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_review":
            r = requests.post(f"{BACKEND_URL}/api/dining/review", json={
                "restaurant_id": args.get("restaurant_id", 0),
                "user_id": args.get("user_id", ""),
                "rating": args.get("rating", 4),
                "comment": args.get("comment", ""),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "restaurant_takeout":
            r = requests.get(f"{BACKEND_URL}/api/dining/takeout", params={
                "restaurant_id": args.get("restaurant_id", 0),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "call_taxi":
            r = requests.post(f"{BACKEND_URL}/api/mobility/call-taxi", json={
                "origin_lat": args.get("origin_lat", 39.925),
                "origin_lon": args.get("origin_lon", 116.59),
                "dest_lat": args.get("dest_lat"),
                "dest_lon": args.get("dest_lon"),
                "car_type": args.get("car_type", "comfort"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "get_traffic":
            r = requests.get(f"{BACKEND_URL}/api/mobility/traffic", timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "weather_forecast":
            r = requests.get(f"{BACKEND_URL}/api/weather/forecast", timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "weather_alerts":
            r = requests.get(f"{BACKEND_URL}/api/weather/alerts", timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "kids_activities":
            r = requests.get(f"{BACKEND_URL}/api/city/kids", params={
                "age_range": args.get("age_range", "0-3"),
                "user_id": args.get("user_id", ""),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "schedule_create":
            r = requests.post(f"{BACKEND_URL}/api/schedule/create", json={
                "user_id": args.get("user_id", ""),
                "title": args.get("title", ""),
                "date": args.get("date", ""),
                "time": args.get("time", ""),
                "location": args.get("location", ""),
                "notes": args.get("notes", ""),
                "reminder_minutes": args.get("reminder_minutes", 15),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()

        elif name == "memory_save":
            r = requests.post(f"{BACKEND_URL}/api/memory/save", json={
                "user_id": args.get("user_id", ""),
                "key": args.get("key", ""),
                "value": args.get("value", ""),
                "category": args.get("category", "preference"),
            }, timeout=REQUEST_TIMEOUT)
            return r.json()
'''

old_else = '        else:\n            return {"error": f"未知工具: {name}"}'
if old_else in content:
    content = content.replace(old_else, NEW_HANDLERS + '\n' + old_else, 1)
    print('HANDLERS: 13 added')
else:
    print('NOT FOUND - trying alternative match')
    # Show what's around line 428
    for i, line in enumerate(content.split('\n')[425:432], start=426):
        print(f'  {i}: {repr(line)}')

with open('agent/mcp_bridge.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
