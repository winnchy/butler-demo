"""
Mock Backend for LocalLife Butler - FastAPI Server
启动时加载丰富化数据 + 初始化 WorldState + 挂载 API 路由
"""

import json
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import json as json_mod
from world_state import WorldState, get_world_state
from route_generator import MetroNetwork, RoadNetwork, RoutePlanner

# ---- 全局对象（各路由模块通过 import main 访问）----
STATIC_DATA: dict = {}
metro_network: MetroNetwork = None
road_network: RoadNetwork = None
route_planner: RoutePlanner = None
world_state: WorldState = None


def load_static_data(enriched_dir: str = "data/enriched"):
    """加载所有丰富化 JSON 到内存"""
    global STATIC_DATA
    STATIC_DATA = {}
    for fname in os.listdir(enriched_dir):
        if fname.endswith(".json") and fname not in (
            "metro_network.json", "routes_index.json", "facility_index.json"
        ):
            path = os.path.join(enriched_dir, fname)
            with open(path, "r", encoding="utf-8") as f:
                key = fname.replace(".json", "")
                STATIC_DATA[key] = json.load(f)
    total = sum(len(v) for v in STATIC_DATA.values())
    print(f"[StaticData] Loaded {len(STATIC_DATA)} categories, {total} POIs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global metro_network, road_network, route_planner, world_state

    print("=" * 50)
    print("LocalLife Butler Mock Backend Starting...")
    print("=" * 50)

    load_static_data()

    metro_path = "data/enriched/metro_stations.json"
    if os.path.exists(metro_path):
        with open(metro_path, "r", encoding="utf-8") as f:
            metro_stations = json.load(f)
        metro_network = MetroNetwork()
        metro_network.build(metro_stations)
        road_network = RoadNetwork()
        road_network.build()
        route_planner = RoutePlanner(metro_network, road_network)

    world_state = WorldState()
    world_state.init_from_enriched("data/enriched")
    world_state.start()

    print("[Server] All systems ready at http://localhost:8000")
    print("[Server] API docs at http://localhost:8000/docs")

    yield

    print("[Server] Shutting down...")
    world_state.stop()
    world_state.save_state("data/world_state_snapshot.json")


app = FastAPI(
    title="LocalLife Butler Mock Backend",
    description="动态模拟北京本地生活数据的 Mock 后端",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


CHAT_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Butler - 全天候私人管家</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#111;color:#e0e0e0;height:100vh;display:flex}
/* Sidebar */
.sidebar{width:260px;background:#1a1a1a;padding:16px;display:flex;flex-direction:column;gap:12px;border-right:1px solid #2a2a2a;overflow-y:auto}
.sidebar h2{font-size:16px;color:#fff;margin-bottom:4px}
.sidebar .desc{font-size:11px;color:#666;margin-bottom:8px}
.user-btn{display:block;width:100%;padding:10px 14px;border:1px solid #333;border-radius:8px;background:#222;color:#ccc;cursor:pointer;text-align:left;font-size:13px;margin-bottom:6px;transition:all .15s}
.user-btn:hover{border-color:#555;background:#2a2a2a}
.user-btn.active{border-color:#10b981;background:#064e3b;color:#6ee7b7}
.scene-btn{display:block;width:100%;padding:7px 12px;border:1px solid #333;border-radius:6px;background:#222;color:#999;cursor:pointer;font-size:12px;margin-bottom:4px;transition:all .15s}
.scene-btn:hover{border-color:#7c3aed;color:#c4b5fd}
.scene-btn.complex{border-left:3px solid #dc2626}
.divider{border:none;border-top:1px solid #2a2a2a;margin:8px 0}
/* Main chat */
.main{flex:1;display:flex;flex-direction:column;max-width:calc(100% - 260px)}
.header{padding:14px 20px;background:#1a1a1a;border-bottom:1px solid #2a2a2a;display:flex;align-items:center;gap:12px}
.header .avatar{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#2563eb,#7c3aed);display:flex;align-items:center;justify-content:center;font-size:18px}
.header .title{font-size:15px;font-weight:600;color:#fff}.header .subtitle{font-size:12px;color:#888}
.messages{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:16px}
.msg{display:flex;gap:10px;max-width:85%}
.msg.user{align-self:flex-end;flex-direction:row-reverse}
.msg.bot{align-self:flex-start}
.msg .bubble{padding:12px 16px;border-radius:16px;font-size:14px;line-height:1.5}
.msg.user .bubble{background:#2563eb;color:#fff;border-bottom-right-radius:4px}
.msg.bot .bubble{background:#262626;color:#e0e0e0;border-bottom-left-radius:4px}
.msg .avatar-mini{width:30px;height:30px;border-radius:50%;background:#333;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
/* Cards inside bot messages */
.card{background:#1e1e1e;border:1px solid #333;border-radius:10px;padding:14px;margin-top:10px;font-size:13px}
.card.restaurant{border-left:3px solid #f59e0b}
.card.weather{border-left:3px solid #3b82f6}
.card.route{border-left:3px solid #10b981}
.card.event{border-left:3px solid #8b5cf6}
.card-title{font-weight:600;font-size:14px;color:#fff;margin-bottom:6px}
.card-row{display:flex;gap:12px;flex-wrap:wrap;margin:4px 0;font-size:12px;color:#aaa}
.card-tag{display:inline-block;padding:2px 8px;border-radius:4px;background:#333;font-size:11px;color:#ccc}
.card-tag.green{background:#064e3b;color:#6ee7b7}
.card-tag.red{background:#7f1d1d;color:#fca5a5}
.card-tag.blue{background:#1e3a5f;color:#93c5fd}
/* Input */
.input-area{padding:14px 20px;background:#1a1a1a;border-top:1px solid #2a2a2a;display:flex;gap:10px}
.input-area input{flex:1;padding:12px 16px;border:1px solid #333;border-radius:24px;background:#222;color:#fff;font-size:14px;outline:none}
.input-area input:focus{border-color:#2563eb}
.input-area button{padding:10px 20px;border:none;border-radius:24px;background:#2563eb;color:#fff;font-weight:600;cursor:pointer;font-size:14px}
.input-area button.mic{background:#333;font-size:18px;padding:10px 14px}
.input-area button:hover{opacity:.9}
/* Toast */
.toast{position:fixed;top:16px;right:16px;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;z-index:999;opacity:0;transition:opacity .3s}
.toast.show{opacity:1}
.toast.ok{background:#064e3b;color:#6ee7b7}
.toast.err{background:#7f1d1d;color:#fca5a5}
/* Phone frame (desktop) */
@media(min-width:769px){
  body{justify-content:center;align-items:center;background:#1a1a1a}
  .app-container{max-width:480px;max-height:90vh;border-radius:20px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.5);display:flex;width:100%;height:90vh}
  .sidebar{display:none}
  .main{max-width:100%}
  .main .header{border-radius:20px 20px 0 0}
}
/* Mobile */
@media(max-width:768px){
  .sidebar{display:none}
  .main{max-width:100%}
}
/* Typing dots */
.typing{display:flex;gap:4px;padding:4px 0}
.typing span{width:6px;height:6px;border-radius:50%;background:#666;animation:typing 1.4s infinite}
.typing span:nth-child(2){animation-delay:.2s}
.typing span:nth-child(3){animation-delay:.4s}
@keyframes typing{0%,60%,100%{opacity:.3}30%{opacity:1}}
</style>
</head>
<body>
<div class="app-container">

<div class="sidebar">
  <h2>🛎️ Butler</h2>
  <div class="desc">全天候私人管家 · 管理面板</div>
  <div class="divider"></div>
  <div style="font-size:11px;color:#666;margin-bottom:4px">👤 切换用户</div>
  <button class="user-btn active" onclick="switchUser('white_collar')" id="btn-wc">🏢 小琴 · 白领</button>
  <button class="user-btn" onclick="switchUser('parent')" id="btn-parent">👶 小冉 · 宝妈</button>
  <button class="user-btn" onclick="switchUser('student')" id="btn-student">🎓 小晴 · 大学生</button>
  <div class="divider"></div>
  <div style="font-size:11px;color:#666;margin-bottom:4px">🎬 场景触发</div>
  <button class="scene-btn" onclick="triggerScene('1')">1. 接待上级午餐</button>
  <button class="scene-btn" onclick="triggerScene('2')">2. 逛街突遇暴雨</button>
  <button class="scene-btn" onclick="triggerScene('7')">7. 乐乐凌晨发烧</button>
  <button class="scene-btn complex" onclick="triggerScene('9')">9. 航班延误</button>
  <button class="scene-btn" onclick="triggerScene('14')">14. 沙尘暴突袭</button>
  <button class="scene-btn complex" onclick="triggerScene('15')">15. 早高峰地铁故障</button>
  <button class="scene-btn complex" onclick="triggerScene('18')">18. 宠物急诊</button>
  <button class="scene-btn" onclick="triggerScene('19')">19. 餐厅临时歇业</button>
  <div class="divider"></div>
  <button class="scene-btn" onclick="resetAll()" style="color:#fca5a5">🔄 重置所有场景</button>
  <div style="margin-top:auto;font-size:10px;color:#444">Powered by OpenClaw<br>Mock Backend v1.0</div>
</div>

<div class="main">
  <div class="header">
    <div class="avatar">🛎️</div>
    <div><div class="title">全天候私人管家</div><div class="subtitle" id="header-user">当前服务: 小琴 (白领)</div></div>
  </div>
  <div class="messages" id="messages">
    <div class="msg bot">
      <div class="avatar-mini">🛎️</div>
      <div class="bubble">
        早上好！☀️ 我是你的全天候私人管家～<br>
        今天北京晴，28°C，早高峰东三环有点堵。<br>
        果果的绘画班10:00开始，大刘已经在送她啦。<br>
        中午想吃什么？或者有其他需要随时告诉我～
      </div>
    </div>
  </div>
  <div class="input-area">
    <button class="mic" onclick="toggleVoice()" id="mic-btn">🎤</button>
    <input type="text" id="userInput" placeholder="输入消息，例如：中午吃啥、今天穿什么、周末有什么活动…" onkeydown="if(event.key==='Enter')send()">
    <button onclick="send()">发送</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const DEPLOY_MODE = 'standalone';  // 'standalone'=本地开发(意图匹配)  'openclaw'=生产模式(AI对话)
const OPENCLAW_CHAT_URL = '/openclaw/chat';  // 后端转发到 OpenClaw
let currentUser = 'white_collar';
let isListening = false;
let recognition = null;

// Init voice
if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.lang = 'zh-CN';
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.onresult = e => {
    document.getElementById('userInput').value = e.results[0][0].transcript;
    send();
  };
  recognition.onend = () => { isListening = false; document.getElementById('mic-btn').textContent = '🎤'; };
}

function toggleVoice() {
  if (!recognition) { toast('浏览器不支持语音输入，请用 Chrome', 'err'); return; }
  if (isListening) { recognition.stop(); isListening = false; document.getElementById('mic-btn').textContent = '🎤'; }
  else { recognition.start(); isListening = true; document.getElementById('mic-btn').textContent = '🔴'; }
}

async function send() {
  const input = document.getElementById('userInput');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  addMessage('user', msg);
  addMessage('bot', '<em>思考中...</em>', true);

  const chatUrl = DEPLOY_MODE === 'openclaw' ? OPENCLAW_CHAT_URL : '/chat';

  try {
    const r = await fetch(chatUrl, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg, user_id: currentUser})
    });
    const d = await r.json();
    document.getElementById('temp-msg')?.remove();
    addMessage('bot', d.reply || d.response || '抱歉，出了点问题...');
  } catch(e) {
    document.getElementById('temp-msg')?.remove();
    addMessage('bot', '服务暂时不可用，请确认后端已启动');
  }
}

function addMessage(role, text, isTemp) {
  const div = document.createElement('div');
  div.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
  if (isTemp) div.id = 'temp-msg';
  const avatarEmoji = role === 'user' ? '👤' : '🛎️';
  div.innerHTML = '<div class="avatar-mini">' + avatarEmoji + '</div><div class="bubble">' + text + '</div>';
  document.getElementById('messages').appendChild(div);
  document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
}

async function switchUser(uid) {
  currentUser = uid;
  const names = {white_collar:'小琴 (白领)',parent:'小冉 (宝妈)',student:'小晴 (大学生)'};
  const greetings = {
    white_collar: '早上好小琴！今天北京晴28°C，早高峰东三环有点堵。果果绘画班10:00。中午想吃什么？',
    parent: '早啊小冉！乐乐今天状态不错～布丁早上遛过了。阿彬今晚又要加班，要不要提前帮你安排晚餐？',
    student: '嗨小晴！今天中关村阴转多云22°C。昨晚睡得好吗？奶茶配额还剩5杯哦～'
  };
  document.getElementById('header-user').textContent = '当前服务: ' + names[uid];
  document.querySelectorAll('.user-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + (uid==='white_collar'?'wc':uid==='parent'?'parent':'student')).classList.add('active');
  try { await fetch('/admin/switch-user/' + uid, {method:'POST'}); } catch(e) {}
  addMessage('bot', greetings[uid] || '已切换用户～有什么可以帮你的？');
}

async function triggerScene(id) {
  try {
    const r = await fetch('/admin/trigger/scenario/' + id, {method:'POST'});
    const d = await r.json();
    toast('场景 ' + id + ' 已触发', 'ok');
    addMessage('bot', '🔔 <b>场景 ' + id + ' 已激活</b><br>' + (d.description || ''));
  } catch(e) { toast('触发失败', 'err'); }
}

async function resetAll() {
  try { await fetch('/admin/reset', {method:'POST'}); toast('已重置', 'ok'); addMessage('bot','✅ 所有场景已重置，恢复正常状态。'); }
  catch(e) { toast('重置失败', 'err'); }
}

function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast ' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 2000);
}
</script>
</div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def chat_ui():
    return CHAT_HTML


@app.post("/chat")
async def chat_endpoint(request: dict):
    """聊天接口：简单意图匹配 + API调用 + 卡片回复"""
    msg = request.get("message", "").strip()
    user_id = request.get("user_id", "white_collar")

    if not msg:
        return {"reply": "我在听～请说。"}

    # 简单意图匹配
    reply = ""
    msg_lower = msg.lower()

    try:
        # 吃饭/餐厅
        if any(w in msg for w in ["吃", "饭", "餐厅", "火锅", "日料", "粤菜", "川菜", "饿", "午餐", "晚餐", "午饭", "晚饭"]):
            cuisine = None
            for c in ["火锅", "日料", "粤菜", "川菜", "烧烤", "西餐", "海鲜", "东南亚"]:
                if c in msg: cuisine = c; break
            import requests
            r = requests.post("http://localhost:8000/api/dining/recommend", json={
                "user_id": user_id, "cuisine": cuisine, "latitude": 39.925, "longitude": 116.59
            })
            recs = r.json().get("recommendations", [])[:3]
            if recs:
                reply = f"帮你找了{'「'+cuisine+'」' if cuisine else '几家不错的'}，看看想吃哪个？\n\n"
                for rec in recs:
                    status_icon = {"有位":"🟢","等位":"🟡","排队":"🟠","长队":"🔴"}.get(rec.get("status",""),"")
                    reply += f"<div class='card restaurant'><div class='card-title'>{rec['name']}</div>"
                    reply += f"<div class='card-row'><span class='card-tag'>{rec['cuisine']}</span>"
                    reply += f"<span class='card-tag blue'>{rec['rating']}分</span>"
                    reply += f"<span class='card-tag green'>¥{rec['avg_price']}/人</span>"
                    reply += f"<span>{status_icon} {rec['status']} ({rec['current_queue']}桌)</span></div>"
                    reply += f"<div class='card-row'>距离{rec['distance_km']}km · {', '.join(rec.get('match_reasons',[])[:2])}</div></div>"
            else:
                reply = "暂时没找到匹配的餐厅，要不要换个菜系试试？"

        # 天气/穿搭
        elif any(w in msg for w in ["天气", "穿", "冷", "热", "下雨", "晴", "温度", "带伞"]):
            import requests
            w = requests.get("http://localhost:8000/api/weather/current").json()
            o = requests.get(f"http://localhost:8000/api/outfit/suggest?user_id={user_id}").json()
            reply = f"<div class='card weather'><div class='card-title'>🌤 北京当前天气</div>"
            reply += f"<div class='card-row'><span>{w.get('condition','?')} · {w.get('temperature','?')}°C</span>"
            reply += f"<span>体感 {w.get('feels_like','?')}°C</span><span>AQI {w.get('aqi','?')} ({w.get('aqi_level','?')})</span></div>"
            if w.get('alerts'):
                for a in w['alerts']:
                    reply += f"<div class='card-row'><span class='card-tag red'>⚠ {a.get('type','')}</span></div>"
            reply += f"</div>"
            reply += f"<div style='margin-top:8px'><b>今日穿搭建议：</b>{o.get('base_suggestion','')}<br>"
            reply += f"推荐单品：{', '.join(o.get('recommended_items',[]))}<br>"
            reply += f"💡 {o.get('tip','')}</div>"

        # 出行/路线
        elif any(w in msg for w in ["去", "走", "怎么", "路线", "地铁", "开车", "打车", "骑车", "多远"]):
            import requests
            r = requests.post("http://localhost:8000/api/mobility/route", json={
                "origin_lat": 39.925, "origin_lon": 116.59,
                "dest_lat": 39.91, "dest_lon": 116.46,
                "user_type": user_id
            })
            opts = r.json().get("options", [])
            if opts:
                reply = f"帮你规划了路线，{r.json().get('recommend_reason','')}：\n\n"
                for o in opts[:3]:
                    icon = {"driving":"🚗","transit":"🚇","cycling":"🚲","walking":"🚶","taxi":"🚕"}.get(o["mode"],"")
                    reply += f"<div class='card route'><div class='card-title'>{icon} {o['mode']} · {o['time_min']}分钟</div>"
                    reply += f"<div class='card-row'><span>距离 {o.get('distance_km','?')}km</span><span>约 ¥{o.get('cost_yuan',0)}</span></div></div>"
            else:
                reply = "暂时无法规划路线，请检查起终点。"

        # 活动/周末
        elif any(w in msg for w in ["活动", "周末", "展览", "市集", "玩", "逛", "演出", "亲子"]):
            import requests
            etype = "kids" if ("亲子" in msg or "带娃" in msg or "孩子" in msg) else "all"
            r = requests.get(f"http://localhost:8000/api/city/events?type={etype}&user_id={user_id}")
            events = r.json().get("events", [])[:3]
            if events:
                reply = f"这周末的活动来啦～{r.json().get('weather_tip','')}\n\n"
                for e in events:
                    reply += f"<div class='card event'><div class='card-title'>🎯 {e['name']}</div>"
                    reply += f"<div class='card-row'><span class='card-tag'>{e['type']}</span>"
                    price = e.get('price',{})
                    ptext = f"¥{price.get('regular',0)}" + (f"/学生¥{price.get('student')}" if price.get('student') else "")
                    reply += f"<span>{ptext}</span><span>{e['distance_km']}km</span></div>"
                    reply += f"<div class='card-row'>📍 {e['location']} · {e.get('date','')}</div></div>"
            else:
                reply = "暂时没找到合适的活动，换个关键词试试？"

        # 日程/提醒
        elif any(w in msg for w in ["日程", "提醒", "安排", "今天有什么", "明天有什么", "记一下"]):
            import requests
            r = requests.get(f"http://localhost:8000/api/schedule/today?user_id={user_id}")
            scheds = r.json().get("schedules", [])
            if scheds:
                reply = f"今天的安排：\n"
                for s in scheds:
                    reply += f"📌 {s['time']} {s['title']}" + (f" @ {s.get('location','')}" if s.get('location') else "") + "\n"
            else:
                reply = "今天没有日程安排。需要我帮你记什么吗？"

        else:
            reply = f"收到！作为你的私人管家，我可以帮你：\n\n🍽️ <b>找餐厅</b>——试试说「附近火锅」「人均100的粤菜」\n👔 <b>穿搭建议</b>——试试说「今天穿什么」「明天冷不冷」\n🚇 <b>出行规划</b>——试试说「去国贸怎么走」\n🎯 <b>周末活动</b>——试试说「周末有什么展览」\n📅 <b>日程管理</b>——试试说「今天有什么安排」"

    except Exception as e:
        reply = f"抱歉，查询时出了点问题：{str(e)[:100]}。请确认后端已启动。"

    return {"reply": reply, "user_id": user_id}


@app.post("/openclaw/chat")
async def openclaw_chat(request: dict):
    """生产模式：转发聊天请求到 OpenClaw 容器"""
    import requests as req
    try:
        resp = req.post(
            "http://openclaw:3000/api/chat",
            json={
                "message": request.get("message", ""),
                "user_id": request.get("user_id", "white_collar"),
            },
            timeout=30
        )
        return resp.json()
    except Exception as e:
        # OpenClaw 不可用时降级到本地意图匹配
        return await chat_endpoint(request)


# CHAT_HTML is defined above as a module-level constant



@app.get("/api")
def root():
    return {"service": "LocalLife Butler Mock Backend", "status": "running"}


@app.get("/health")
def health():
    return {"status": "ok", "ws_active": world_state._running if world_state else False}


# ---- 挂载子路由 ----

from api_routes.dining_routes import router as dining_router
from api_routes.mobility_routes import router as mobility_router
from api_routes.city_routes import router as city_router
from api_routes.outfit_routes import router as outfit_router
from api_routes.life_routes import router as life_router
from api_routes.admin_routes import router as admin_router

app.include_router(dining_router, prefix="/api/dining", tags=["Dining"])
app.include_router(mobility_router, prefix="/api/mobility", tags=["Mobility"])
app.include_router(city_router, prefix="/api/city", tags=["City"])
app.include_router(outfit_router, prefix="/api", tags=["Outfit & Weather"])
app.include_router(life_router, prefix="/api", tags=["Life & Schedule"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
