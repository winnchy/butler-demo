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
/* Sidebar toggle */
.sidebar{display:none}.sidebar.open{display:flex;position:fixed;top:0;left:0;height:100%;z-index:100;overflow-y:auto}
.hamburger{background:none;border:none;color:#888;font-size:18px;cursor:pointer;padding:4px 8px}
.user-switch{display:flex;gap:6px;align-items:center}
.user-switch select{padding:5px 8px;border:1px solid #333;border-radius:6px;background:#1a1a1a;color:#ccc;font-size:12px;cursor:pointer;outline:none}
.user-switch select:focus{border-color:#2563eb}
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

<div class="sidebar" id="sidebar-el">
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
    <button class="hamburger" onclick="document.getElementById('sidebar-el').classList.toggle('open')" title="管理面板">☰</button>
    <div class="avatar">🛎️</div>
    <div style="flex:1"><div class="title">全天候私人管家</div></div>
    <div class="user-switch">
      <select id="userSelect" onchange="switchUser(this.value)">
        <option value="white_collar">🏢 小琴</option>
        <option value="parent">👶 小冉</option>
        <option value="student">🎓 小晴</option>
      </select>
    </div>
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
const DEPLOY_MODE = 'openclaw';  // 'standalone'=本地开发(意图匹配)  'openclaw'=生产模式(AI对话)
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
  // 通知后端切换用户资料文件
  try { await fetch('/admin/switch-user/' + uid, {method:'POST'}); } catch(e) {}
  const greetings = {
    white_collar: '你好小琴！今天北京晴28°C。中午想吃什么？',
    parent: '早啊小冉！乐乐今天状态不错～布丁早上遛过了。需要帮你安排什么？',
    student: '嗨小晴！今天中关村阴转多云22°C。需要帮什么忙？'
  };
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
    """AI 对话：DeepSeek + 工具调用（等价于 OpenClaw 核心能力）"""
    msg = request.get("message", "").strip()
    user_id = request.get("user_id", "white_collar")

    if not msg:
        return {"reply": "我在听～请说。"}

    try:
        # 读取当前用户画像和记忆
        user_profile = ""
        user_memory = ""
        try:
            with open("/app/butler/USER.md", "r", encoding="utf-8") as f:
                user_profile = f.read()[:3000]
        except: pass
        try:
            with open("/app/butler/MEMORY.md", "r", encoding="utf-8") as f:
                user_memory = f.read()[:3000]
        except: pass

        # 读取部分技能定义作为工具说明
        skills_summary = ""
        for skill in ["dining-butler","mobility-butler","city-explorer","outfit-advisor","life-organizer"]:
            try:
                with open(f"/app/butler/skills/{skill}/SKILL.md","r",encoding="utf-8") as f:
                    skills_summary += f.read()[:800] + "\n"
            except: pass

        # 构建 system prompt
        system_prompt = f"""你是小琴/小冉/小晴的私人管家，一位7x24小时全天候AI助理。

## 你的性格
温暖但不肉麻，细心但不啰嗦，高效但不冰冷。你预判用户需求，不等用户开口。

## 当前用户画像
{user_profile[:2000]}

## 当前用户记忆
{user_memory[:2000]}

## 你可以调用的工具
1. recommend_restaurant(cuisine, budget, user_id) - 推荐餐厅，返回菜系、评分、人均、排队状态
2. get_weather() - 获取北京当前天气，返回温度、AQI、预警
3. get_outfit(user_id) - 获取穿搭建议
4. plan_route(from_lat, from_lon, to_lat, to_lon, user_type) - 多模式路径规划
5. get_events(city, type) - 获取周末活动
6. get_schedule(user_id) - 查询今日日程

## 回复规范
- 用自然中文回复，保持简洁温暖
- 如果需要调工具，先说明你在做什么
- 餐厅推荐用卡片格式展示
- 如果用户切换了身份，根据画像调整语气和推荐"""

        # 调用 DeepSeek API
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return await _fallback_chat(msg, user_id)

        from openai import OpenAI
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1"
        )

        # 定义工具
        tools = [
            {"type":"function","function":{"name":"recommend_restaurant","description":"推荐餐厅","parameters":{"type":"object","properties":{"cuisine":{"type":"string","description":"菜系"},"budget":{"type":"integer","description":"人均预算"},"user_id":{"type":"string"}},"required":["user_id"]}}},
            {"type":"function","function":{"name":"get_weather","description":"获取北京当前天气","parameters":{"type":"object","properties":{}}}},
            {"type":"function","function":{"name":"get_outfit","description":"获取穿搭建议","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
            {"type":"function","function":{"name":"plan_route","description":"路径规划","parameters":{"type":"object","properties":{"origin":{"type":"string"},"destination":{"type":"string"},"user_type":{"type":"string"}},"required":["origin","destination"]}}},
            {"type":"function","function":{"name":"get_events","description":"获取周末活动","parameters":{"type":"object","properties":{"type":{"type":"string","description":"kids/market/exhibition/all"}},"required":[]}}},
            {"type":"function","function":{"name":"get_schedule","description":"查询今日日程","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
        ]

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role":"system","content":system_prompt},
                {"role":"user","content":msg}
            ],
            tools=tools,
            temperature=0.7,
            max_tokens=1000
        )

        # 处理 LLM 响应和工具调用
        choice = response.choices[0]
        reply = choice.message.content or ""

        # 如果 LLM 要调工具，执行并拼接结果
        if choice.message.tool_calls:
            import requests
            for tc in choice.message.tool_calls:
                fn = tc.function
                try:
                    args = json_mod.loads(fn.arguments)
                except:
                    args = {}

                if fn.name == "recommend_restaurant":
                    r = requests.post("http://localhost:8000/api/dining/recommend",json={"user_id":user_id,"cuisine":args.get("cuisine"),"budget_per_person":args.get("budget"),"latitude":39.925,"longitude":116.59})
                    recs = r.json().get("recommendations",[])[:3]
                    if recs:
                        reply += "\n\n"
                        for rec in recs:
                            reply += f"🍽️ **{rec['name']}** | {rec['cuisine']} | ⭐{rec['rating']} | ¥{rec['avg_price']}/人 | {rec.get('status','')}\n"

                elif fn.name == "get_weather":
                    r = requests.get("http://localhost:8000/api/weather/current")
                    w = r.json()
                    reply += f"\n\n🌤 北京 {w.get('condition','')} {w.get('temperature','')}°C | AQI {w.get('aqi','')}({w.get('aqi_level','')})"

                elif fn.name == "get_outfit":
                    r = requests.get(f"http://localhost:8000/api/outfit/suggest?user_id={user_id}")
                    o = r.json()
                    reply += f"\n\n👔 {o.get('base_suggestion','')}：{', '.join(o.get('recommended_items',[])[:5])}"

                elif fn.name == "plan_route":
                    # 使用默认起终点
                    r = requests.post("http://localhost:8000/api/mobility/route",json={"origin_lat":39.925,"origin_lon":116.59,"dest_lat":39.91,"dest_lon":116.46,"user_type":user_id})
                    opts = r.json().get("options",[])[:2]
                    if opts:
                        reply += "\n\n"
                        for o in opts:
                            reply += f"🚗 {o['mode']} {o['time_min']}分钟 | ¥{o.get('cost_yuan',0)}\n"

                elif fn.name == "get_events":
                    r = requests.get(f"http://localhost:8000/api/city/events?type={args.get('type','all')}&user_id={user_id}")
                    events = r.json().get("events",[])[:3]
                    if events:
                        reply += "\n\n"
                        for e in events:
                            reply += f"🎯 {e['name']} | {e['location']} | {e.get('date','')}\n"

                elif fn.name == "get_schedule":
                    r = requests.get(f"http://localhost:8000/api/schedule/today?user_id={user_id}")
                    scheds = r.json().get("schedules",[])
                    if scheds:
                        reply += "\n\n"
                        for s in scheds:
                            reply += f"📌 {s['time']} {s['title']}\n"
                    else:
                        reply += "\n\n今天没有日程安排。"

        return {"reply": reply or "收到，让我想想...", "user_id": user_id}

    except Exception as e:
        return await _fallback_chat(msg, user_id)


async def _fallback_chat(msg: str, user_id: str) -> dict:
    """当 AI 不可用时的降级回复"""
    reply = f"收到你的消息了～当前 AI 服务暂未配置（需要设置 OPENAI_API_KEY 环境变量）。\n\n你可以试试：\n🍽️ 「附近火锅」\n👔 「今天穿什么」\n🚇 「去国贸怎么走」\n🎯 「周末有什么活动」"
    return {"reply": reply, "user_id": user_id}


@app.post("/openclaw/chat")
async def openclaw_chat(request: dict):
    """转发到 OpenClaw Gateway"""
    import requests as req
    try:
        resp = req.post(
            "http://localhost:18789/api/chat",
            json={"message": request.get("message",""), "user_id": request.get("user_id","")},
            timeout=30
        )
        return resp.json()
    except:
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
