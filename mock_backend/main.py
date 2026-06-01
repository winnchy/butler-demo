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
const DEPLOY_MODE = 'standalone';  // 'standalone'=直连后端AI  'openclaw'=通过OpenClaw
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

  // 思考计时器
  let thinkSec = 0;
  const thinkId = 'think-' + Date.now();
  addMessage('bot', '<div class="typing"><span></span><span></span><span></span></div> 思考中 (<span id="' + thinkId + '">0</span>秒)...', true);
  const timer = setInterval(() => {
    thinkSec++;
    const el = document.getElementById(thinkId);
    if (el) el.textContent = thinkSec;
  }, 1000);

  const chatUrl = DEPLOY_MODE === 'openclaw' ? OPENCLAW_CHAT_URL : '/chat';

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    const r = await fetch(chatUrl, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg, user_id: currentUser}),
      signal: controller.signal
    });
    clearTimeout(timeout);
    const d = await r.json();
    clearInterval(timer);
    document.getElementById('temp-msg')?.remove();
    addMessage('bot', d.reply || d.response || '抱歉，出了点问题...');
  } catch(e) {
    clearInterval(timer);
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
  const scenes = {
    '1':  { title: '接待上级午餐', detail: '小琴12:00接待王总+深圳合作方。已为你筛选包厢粤菜，金融街附近3家可选。' },
    '2':  { title: '逛街突遇暴雨', detail: '⚠️ 暴雨黄色预警！蓝色港湾附近突降暴雨，预计持续到15:00。建议改室内活动，已推送同商场备选餐厅。' },
    '7':  { title: '乐乐凌晨发烧', detail: '🚨 凌晨2:00，乐乐体温38.5°C。已推送最近儿科急诊、叫车到医院、提醒阿彬明天请假。' },
    '9':  { title: '航班延误', detail: '⚠️ 北京→上海 CA1234 因雷暴延误2小时。已查高铁G7替代（10:00-14:30），延误险可理赔，面试酒店已推送。' },
    '14': { title: '沙尘暴突袭', detail: '⚠️ 沙尘暴黄色预警！AQI 350+，能见度低。建议戴N95、改地铁出行、关好门窗。' },
    '15': { title: '早高峰地铁故障', detail: '⚠️ 6号线常营段信号故障，延误约20分钟。已推替代方案：打车(12分钟等)+共享单车到黄渠站。' },
    '18': { title: '宠物急诊', detail: '🚨 布丁疑似误食呕吐！已推送最近宠物医院（2.3km）、叫车、提醒公婆帮忙照顾乐乐。' },
    '19': { title: '餐厅临时歇业', detail: '⚠️ 你约好的餐厅因设备维修临时歇业。已切换同商圈备选，步行3分钟可达。' }
  };
  try {
    await fetch('/admin/trigger/scenario/' + id, {method:'POST'});
    const s = scenes[id] || {title:'场景'+id, detail:'已激活'};
    addMessage('bot', '<b>🎬 ' + s.title + '</b><br>' + s.detail);
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
        # 读 SOUL.md（管家性格和行为指南）— 只取前 2000 字符提效
        soul_prompt = "你是全天候私人管家。"
        try:
            with open("/app/butler/SOUL.md", "r", encoding="utf-8") as f:
                soul_prompt = f.read()
        except: pass

        # 读当前用户资料 — 只取系统可读字段
        user_context = ""
        try:
            with open("/app/butler/USER.md", "r", encoding="utf-8") as f:
                user_context += f.read()[:1200] + "\n"
        except: pass
        try:
            with open("/app/butler/MEMORY.md", "r", encoding="utf-8") as f:
                user_context += f.read()[:1200]
        except: pass

        # 附加实时天气
        try:
            import requests
            w = requests.get("http://localhost:8000/api/weather/current", timeout=3).json()
            user_context += f"\n北京当前{w.get('condition','?')} {w.get('current_temp','?')}°C AQI{w.get('aqi','?')}"
        except: pass

        system_prompt = soul_prompt + "\n\n## 当前服务用户\n" + user_context

        # 调用 DeepSeek API
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return await _fallback_chat(msg, user_id)

        from openai import OpenAI
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1"
        )

        # 定义工具（对应 mock_backend 所有 API，覆盖 5 个 Skill）
        tools = [
            # dining-butler
            {"type":"function","function":{"name":"restaurant_recommend","description":"推荐餐厅，支持菜系/预算/设施/过敏过滤","parameters":{"type":"object","properties":{"cuisine":{"type":"string"},"budget":{"type":"integer"},"user_id":{"type":"string"},"must_have":{"type":"string","description":"baby_seat/parking/private_room/pet_allowed"}},"required":["user_id"]}}},
            {"type":"function","function":{"name":"restaurant_queue","description":"查餐厅排队状态","parameters":{"type":"object","properties":{"restaurant_id":{"type":"integer"}},"required":["restaurant_id"]}}},
            {"type":"function","function":{"name":"restaurant_emergency","description":"突发兜底：暴雨/满座/迟到时的替代方案","parameters":{"type":"object","properties":{"emergency_type":{"type":"string","description":"weather/full/late"},"current_lat":{"type":"number"},"current_lng":{"type":"number"},"has_child":{"type":"boolean"}},"required":["emergency_type","current_lat","current_lng"]}}},
            # mobility-butler
            {"type":"function","function":{"name":"plan_route","description":"多模式路径规划：驾车/地铁/骑行/步行/打车","parameters":{"type":"object","properties":{"origin_lat":{"type":"number"},"origin_lon":{"type":"number"},"dest_lat":{"type":"number"},"dest_lon":{"type":"number"},"user_type":{"type":"string"}},"required":["origin_lat","origin_lon","dest_lat","dest_lon"]}}},
            {"type":"function","function":{"name":"transport_search","description":"查机票/火车票(模拟)","parameters":{"type":"object","properties":{"origin_city":{"type":"string"},"dest_city":{"type":"string"},"transport_type":{"type":"string","description":"flight/train/all"}},"required":["origin_city","dest_city"]}}},
            {"type":"function","function":{"name":"nearby_facilities","description":"周边设施：加油站/充电桩/便利店/停车场","parameters":{"type":"object","properties":{"lat":{"type":"number"},"lon":{"type":"number"},"facility_type":{"type":"string"}},"required":["lat","lon","facility_type"]}}},
            # outfit-advisor
            {"type":"function","function":{"name":"get_weather","description":"北京当前天气+预警","parameters":{"type":"object","properties":{}}}},
            {"type":"function","function":{"name":"get_outfit","description":"穿搭建议(基于温度+用户身份)","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
            {"type":"function","function":{"name":"get_wardrobe","description":"查用户衣橱+缺失物品","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
            # city-explorer
            {"type":"function","function":{"name":"get_events","description":"周末活动：展览/市集/演出/亲子","parameters":{"type":"object","properties":{"type":{"type":"string","description":"exhibition/show/market/kids/all"},"user_id":{"type":"string"}},"required":[]}}},
            {"type":"function","function":{"name":"get_shopping","description":"商场促销","parameters":{"type":"object","properties":{"category":{"type":"string","description":"clothing/electronics/home/child/all"}},"required":[]}}},
            # life-organizer
            {"type":"function","function":{"name":"get_schedule","description":"今日日程","parameters":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]}}},
            {"type":"function","function":{"name":"search_memory","description":"搜索用户偏好记忆","parameters":{"type":"object","properties":{"user_id":{"type":"string"},"keyword":{"type":"string"}},"required":["user_id"]}}},
        ]

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role":"system","content":system_prompt},
                {"role":"user","content":msg}
            ],
            tools=tools,
            temperature=0.7,
            max_tokens=500,
            timeout=25
        )

        # 处理 LLM 响应和工具调用
        choice = response.choices[0]
        reply = choice.message.content or ""

        # 如果 LLM 要调工具，执行并拼接结果
        if choice.message.tool_calls:
            import requests
            for tc in choice.message.tool_calls:
                fn = tc.function
                try: args = json_mod.loads(fn.arguments)
                except: args = {}

                try:
                    if fn.name == "restaurant_recommend":
                        r = requests.post("http://localhost:8000/api/dining/recommend",json={"user_id":user_id,"cuisine":args.get("cuisine"),"budget_per_person":args.get("budget"),"latitude":39.925,"longitude":116.59,"must_have":args.get("must_have","").split(",") if args.get("must_have") else None})
                        recs = r.json().get("recommendations",[])[:3]
                        if recs:
                            reply += "\n\n"
                            for rec in recs:
                                reply += f"🍽️ **{rec['name']}** | {rec['cuisine']} | ⭐{rec['rating']} | ¥{rec['avg_price']}/人 | {rec.get('status','')}\n  {', '.join(rec.get('match_reasons',[])[:2])}\n"

                    elif fn.name == "restaurant_queue":
                        rid = args.get("restaurant_id",0)
                        r = requests.get(f"http://localhost:8000/api/dining/queue?restaurant_id={rid}")
                        q = r.json()
                        reply += f"\n当前排队{q.get('current_queue',0)}桌，预计等{q.get('estimated_wait_min',0)}分钟"

                    elif fn.name == "restaurant_emergency":
                        r = requests.post("http://localhost:8000/api/dining/emergency-plan",json={"user_id":user_id,"emergency_type":args.get("emergency_type","weather"),"current_lat":args.get("current_lat",39.925),"current_lng":args.get("current_lng",116.59),"has_child":args.get("has_child",False)})
                        plan = r.json().get("priority_plan",{})
                        reply += f"\n\n🔔 突发兜底：{plan.get('message','已为你找到替代方案')}"

                    elif fn.name == "plan_route":
                        r = requests.post("http://localhost:8000/api/mobility/route",json={"origin_lat":args.get("origin_lat",39.925),"origin_lon":args.get("origin_lon",116.59),"dest_lat":args.get("dest_lat",39.91),"dest_lon":args.get("dest_lon",116.46),"user_type":user_id})
                        opts = r.json().get("options",[])[:3]
                        if opts:
                            reply += "\n\n"
                            for o in opts:
                                reply += f"{'🚗🚇🚲🚶🚕'[['driving','transit','cycling','walking','taxi'].index(o['mode'])] if o['mode'] in ['driving','transit','cycling','walking','taxi'] else '📍'} {o['mode']} {o['time_min']}分钟 | ¥{o.get('cost_yuan',0)}\n"

                    elif fn.name == "transport_search":
                        r = requests.get(f"http://localhost:8000/api/mobility/transport/search?origin_city={args.get('origin_city','北京')}&dest_city={args.get('dest_city','上海')}&transport_type={args.get('transport_type','all')}")
                        results = r.json().get("results",[])[:3]
                        if results:
                            reply += "\n\n"
                            for t in results:
                                reply += f"✈️🚄 {t['type']} {t.get('departure','')}-{t.get('arrival','')} | ¥{t.get('price','?')} | {'延误!'+str(t.get('delay_min'))+'min' if t.get('status')=='delayed' else t.get('seats_left','?')+'座'}\n"

                    elif fn.name == "nearby_facilities":
                        r = requests.get(f"http://localhost:8000/api/mobility/nearby?lat={args.get('lat',39.925)}&lon={args.get('lon',116.59)}&facility_type={args.get('facility_type','gas_station')}")
                        facs = r.json().get("facilities",[])[:3]
                        if facs:
                            reply += "\n\n"
                            for f in facs:
                                reply += f"📍 {f['name']} | {f['distance_km']}km\n"

                    elif fn.name == "get_weather":
                        r = requests.get("http://localhost:8000/api/weather/current")
                        w = r.json()
                        reply += f"\n\n🌤 北京 {w.get('condition','?')} {w.get('temperature','?')}°C | 体感{w.get('feels_like','?')}°C | AQI{w.get('aqi','?')}({w.get('aqi_level','?')})"
                        if w.get('alerts'):
                            for a in w['alerts']:
                                reply += f"\n⚠️ {a.get('type','')}"

                    elif fn.name == "get_outfit":
                        r = requests.get(f"http://localhost:8000/api/outfit/suggest?user_id={user_id}")
                        o = r.json()
                        reply += f"\n\n👔 {o.get('base_suggestion','?')}：{', '.join(o.get('recommended_items',[])[:5])}"

                    elif fn.name == "get_wardrobe":
                        r = requests.get(f"http://localhost:8000/api/wardrobe?user_id={user_id}")
                        wb = r.json()
                        reply += f"\n\n👗 衣橱：上装{wb.get('tops',[])[:3]} 下装{wb.get('bottoms',[])[:2]} 缺：{', '.join(wb.get('missing',[]))}"

                    elif fn.name == "get_events":
                        r = requests.get(f"http://localhost:8000/api/city/events?type={args.get('type','all')}&user_id={user_id}")
                        events = r.json().get("events",[])[:3]
                        if events:
                            reply += "\n\n"
                            for e in events:
                                reply += f"🎯 {e['name']} | {e['location']} | {e.get('date','')} | ¥{e.get('price',{}).get('regular','?')}\n"

                    elif fn.name == "get_shopping":
                        r = requests.get(f"http://localhost:8000/api/city/shopping?category={args.get('category','all')}")
                        promos = r.json().get("promotions",[])[:3]
                        if promos:
                            reply += "\n\n"
                            for p in promos:
                                reply += f"🛍️ {p['mall']}：{p['promotion']}（至{p.get('valid_until','?')}）\n"

                    elif fn.name == "get_schedule":
                        r = requests.get(f"http://localhost:8000/api/schedule/today?user_id={user_id}")
                        scheds = r.json().get("schedules",[])
                        if scheds:
                            reply += "\n\n"
                            for s in scheds:
                                reply += f"📌 {s['time']} {s['title']} @{s.get('location','?')}\n"
                        else:
                            reply += "\n\n今天没有日程安排。"

                    elif fn.name == "search_memory":
                        r = requests.get(f"http://localhost:8000/api/memory/search?user_id={user_id}&keyword={args.get('keyword','')}")
                        mems = r.json().get("memories",[])[:5]
                        if mems:
                            reply += "\n\n"
                            for m in mems:
                                reply += f"🧠 {m['key']}: {m['value']}\n"
                except Exception as tool_err:
                    reply += f"\n[工具调用异常: {str(tool_err)[:50]}]"

        return {"reply": reply or "收到，让我想想...", "user_id": user_id}

    except Exception as e:
        return {"reply": f"抱歉，AI 服务暂时异常：{str(e)[:200]}", "user_id": user_id}


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
    import os
    key = os.environ.get("OPENAI_API_KEY", "")
    return {
        "status": "ok",
        "ws_active": world_state._running if world_state else False,
        "api_key_set": bool(key),
        "api_key_preview": (key[:8] + "..." + key[-4:]) if key else "NOT SET",
    }

@app.get("/debug/env")
def debug_env():
    """诊断：检查环境变量是否正确加载"""
    import os
    key = os.environ.get("OPENAI_API_KEY", "")
    base = os.environ.get("OPENAI_BASE_URL", "")
    return {
        "openai_api_key_set": bool(key),
        "openai_api_key_preview": (key[:8] + "..." + key[-4:]) if key else "NOT SET",
        "openai_base_url": base or "NOT SET",
        "all_env_keys": [k for k in os.environ.keys() if "API" in k or "OPEN" in k or "KEY" in k.upper()],
    }


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
