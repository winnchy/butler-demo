"""管理接口: 用户切换 / 场景触发器 / 状态检查 / 管理面板"""

import os
import shutil
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
import shared as main

router = APIRouter()

# ---- 路径配置 ----
BUTLER_DIR = os.environ.get("BUTLER_DIR", os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "butler")))
# Railway/Docker 环境使用 /app/butler
if os.path.exists("/app/butler"):
    BUTLER_DIR = "/app/butler"
PROFILES_DIR = os.path.join(BUTLER_DIR, "profiles")

USER_SWITCH_MAP = {
    "white_collar": {
        "name": "小琴 (白领)",
        "profile": "users/whitecollar.md",
        "memory": "memories/whitecollar-memory.md",
        "wardrobe": "users/whitecollar-wardrobe.md",
    },
    "parent": {
        "name": "小冉 (宝妈)",
        "profile": "users/parent.md",
        "memory": "memories/parent-memory.md",
        "wardrobe": "users/parent-wardrobe.md",
    },
    "student": {
        "name": "小晴 (大学生)",
        "profile": "users/student.md",
        "memory": "memories/student-memory.md",
        "wardrobe": "users/student-wardrobe.md",
    },
}


@router.post("/switch-user/{user_id}")
def switch_user(user_id: str):
    """切换当前用户：将 profiles/ 下的画像/记忆/衣橱复制到 butler 根目录"""
    if user_id not in USER_SWITCH_MAP:
        return {"ok": False, "error": f"未知用户: {user_id}", "available": list(USER_SWITCH_MAP.keys())}

    info = USER_SWITCH_MAP[user_id]
    results = []

    targets = {
        "USER.md": info["profile"],
        "MEMORY.md": info["memory"],
        "wardrobe.md": info["wardrobe"],
    }

    for target_name, src_rel in targets.items():
        src = os.path.join(PROFILES_DIR, src_rel)
        dst = os.path.join(BUTLER_DIR, target_name)

        if not os.path.exists(src):
            results.append({"file": target_name, "status": "error", "reason": "源文件不存在"})
            continue

        shutil.copy2(src, dst)
        size = os.path.getsize(dst)
        results.append({"file": target_name, "status": "ok", "size_bytes": size})

    return {
        "ok": True,
        "user_id": user_id,
        "user_name": info["name"],
        "files": results,
        "message": f"已切换至 {info['name']}，OpenClaw 重启后生效",
    }


@router.get("/switch-user")
def get_current_user():
    """查看当前激活的用户"""
    user_md = os.path.join(BUTLER_DIR, "USER.md")
    if not os.path.exists(user_md) or os.path.getsize(user_md) == 0:
        return {"active": None, "message": "未设置用户（USER.md 为空）"}

    with open(user_md, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()

    for uid, info in USER_SWITCH_MAP.items():
        name_hint = info["name"].split("(")[0]
        if name_hint in first_line:
            return {"active": uid, "name": info["name"], "message": f"当前用户: {info['name']}"}

    return {"active": "unknown", "message": f"无法识别用户（首行: {first_line[:50]}）"}


@router.post("/trigger/scenario/{scenario_id}")
def trigger_scenario(scenario_id: str):
    """触发沙盒演示场景"""
    ws = main.world_state
    if not ws:
        return {"error": "WorldState not initialized"}
    return ws.trigger_scenario(scenario_id)


@router.post("/reset")
def reset_scenario():
    """重置场景，恢复正常随机状态"""
    ws = main.world_state
    if not ws:
        return {"error": "WorldState not initialized"}
    return ws.reset_scenario()


@router.get("/state")
def get_full_state():
    """查看当前完整动态状态"""
    ws = main.world_state
    if not ws:
        return {"error": "WorldState not initialized"}

    # 当前用户信息
    current_user = get_current_user()

    return {
        "current_user": current_user,
        "weather": ws.get_weather(),
        "traffic": ws.get_traffic(),
        "health_events": {k: {
            "user_id": v.user_id, "event_type": v.event_type,
            "person": v.person, "severity": v.severity,
            "started_at": v.started_at, "expires_at": v.expires_at,
        } for k, v in ws.health_events.items()},
        "flights": {k: {
            "flight_id": v.flight_id, "route": v.route,
            "status": v.status, "delay_minutes": v.delay_minutes,
            "reason": v.reason,
        } for k, v in ws.flights.items()},
        "scenario_override_active": ws.scenario_override is not None,
        "scenario_description": ws.scenario_override.get("description", "") if ws.scenario_override else "",
        "restaurant_queue_sample": {str(k): {
            "current_queue": v.current_queue,
            "status": v.status,
            "estimated_wait_min": v.estimated_wait_min,
        } for k, v in list(ws.restaurant_queues.items())[:5]},
    }


@router.get("/state/weather")
def get_weather_state():
    ws = main.world_state
    return ws.get_weather() if ws else {}


@router.get("/state/traffic")
def get_traffic_state():
    ws = main.world_state
    return ws.get_traffic() if ws else {}


@router.get("/data/stats")
def data_stats():
    """查看静态数据统计"""
    stats = {}
    for key, items in main.STATIC_DATA.items():
        stats[key] = len(items)
    return {"total_categories": len(stats), "categories": stats}


# ---- 管理面板 HTML ----

@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard():
    """可视化管理面板"""
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Butler 管理面板</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 20px; }
h1 { font-size: 22px; margin-bottom: 20px; color: #fff; }
h2 { font-size: 15px; color: #999; margin: 20px 0 10px; text-transform: uppercase; letter-spacing: 1px; }
.section { background: #1a1a1a; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
.row { display: flex; gap: 10px; flex-wrap: wrap; }
.btn { padding: 12px 24px; border: none; border-radius: 8px; font-size: 14px; cursor: pointer; font-weight: 600; transition: all 0.15s; color: #fff; }
.btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
.btn:active { transform: scale(0.97); }
.btn-user { background: #2563eb; }
.btn-user.active { background: #10b981; box-shadow: 0 0 0 3px rgba(16,185,129,0.3); }
.btn-scenario { background: #7c3aed; font-size: 13px; padding: 10px 16px; }
.btn-scenario.complex { background: #dc2626; }
.btn-reset { background: #6b7280; }
.btn-refresh { background: #374151; }
.status-badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.status-ok { background: #065f46; color: #6ee7b7; }
.status-warn { background: #78350f; color: #fbbf24; }
.status-err { background: #7f1d1d; color: #fca5a5; }
.info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 10px; }
.info-card { background: #262626; border-radius: 8px; padding: 12px; }
.info-card .label { font-size: 11px; color: #888; margin-bottom: 4px; }
.info-card .value { font-size: 16px; font-weight: 600; }
#toast { position: fixed; top: 20px; right: 20px; padding: 12px 20px; border-radius: 8px; font-size: 14px; font-weight: 600; z-index: 999; opacity: 0; transition: opacity 0.3s; }
#toast.show { opacity: 1; }
#toast.success { background: #065f46; color: #6ee7b7; }
#toast.error { background: #7f1d1d; color: #fca5a5; }
</style>
</head>
<body>

<h1>🛎️ Butler 管理面板</h1>

<!-- 用户切换 -->
<div class="section">
  <h2>👤 用户切换</h2>
  <div class="row">
    <button class="btn btn-user" onclick="switchUser('white_collar')" id="btn-wc">🏢 小琴 (白领)</button>
    <button class="btn btn-user" onclick="switchUser('parent')" id="btn-parent">👶 小冉 (宝妈)</button>
    <button class="btn btn-user" onclick="switchUser('student')" id="btn-student">🎓 小晴 (大学生)</button>
  </div>
  <div style="margin-top:10px;font-size:13px;color:#888" id="current-user">当前用户: 加载中...</div>
</div>

<!-- 场景触发器 -->
<div class="section">
  <h2>🎬 场景触发器</h2>
  <div class="row">
    <button class="btn btn-scenario" onclick="triggerScenario('1')">1.接待上级</button>
    <button class="btn btn-scenario" onclick="triggerScenario('2')">2.逛街遇暴雨</button>
    <button class="btn btn-scenario" onclick="triggerScenario('7')">7.乐乐发烧</button>
    <button class="btn btn-scenario complex" onclick="triggerScenario('9')">9.航班延误</button>
    <button class="btn btn-scenario" onclick="triggerScenario('10')">10.痛经请假</button>
    <button class="btn btn-scenario" onclick="triggerScenario('14')">14.沙尘暴</button>
    <button class="btn btn-scenario complex" onclick="triggerScenario('15')">15.地铁故障</button>
    <button class="btn btn-scenario complex" onclick="triggerScenario('18')">18.宠物急诊</button>
    <button class="btn btn-scenario" onclick="triggerScenario('19')">19.餐厅歇业</button>
  </div>
  <div style="margin-top:12px">
    <button class="btn btn-reset" onclick="resetAll()">🔄 重置所有场景</button>
    <button class="btn btn-refresh" onclick="refreshState()">🔍 刷新状态</button>
  </div>
</div>

<!-- 实时状态 -->
<div class="section">
  <h2>📊 实时状态 <span id="state-time" style="font-weight:400;font-size:12px;color:#666"></span></h2>
  <div class="info-grid" id="state-grid">
    <div class="info-card"><div class="label">加载中...</div></div>
  </div>
</div>

<div id="toast"></div>

<script>
const API = '';

function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = type + ' show';
  setTimeout(() => t.classList.remove('show'), 2000);
}

async function switchUser(uid) {
  try {
    const r = await fetch(API + '/admin/switch-user/' + uid, { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      toast('已切换至: ' + d.user_name, 'success');
      document.querySelectorAll('.btn-user').forEach(b => b.classList.remove('active'));
      document.getElementById('btn-' + (uid==='white_collar'?'wc':uid==='parent'?'parent':'student')).classList.add('active');
      document.getElementById('current-user').textContent = '当前用户: ' + d.user_name + ' (需重启OpenClaw生效)';
    } else {
      toast('切换失败: ' + d.error, 'error');
    }
  } catch(e) { toast('网络错误', 'error'); }
}

async function triggerScenario(id) {
  try {
    const r = await fetch(API + '/admin/trigger/scenario/' + id, { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      toast('场景 ' + id + ' 已触发: ' + (d.description || ''), 'success');
      refreshState();
    } else {
      toast('失败: ' + (d.error || '未知'), 'error');
    }
  } catch(e) { toast('网络错误', 'error'); }
}

async function resetAll() {
  try {
    await fetch(API + '/admin/reset', { method: 'POST' });
    toast('已重置', 'success');
    refreshState();
  } catch(e) { toast('网络错误', 'error'); }
}

async function refreshState() {
  try {
    const r = await fetch(API + '/admin/state');
    const s = await r.json();
    const w = s.weather || {};
    const t = s.traffic || {};

    document.getElementById('state-grid').innerHTML =
      '<div class="info-card"><div class="label">天气</div><div class="value">' + (w.condition||'?') + ' ' + (w.current_temp||'?') + '°C</div></div>' +
      '<div class="info-card"><div class="label">AQI</div><div class="value">' + (w.aqi||'?') + ' (' + (w.aqi_level||'?') + ')</div></div>' +
      '<div class="info-card"><div class="label">拥堵指数</div><div class="value">' + ((t.citywide_congestion||0)*100).toFixed(0) + '%</div></div>' +
      '<div class="info-card"><div class="label">活跃预警</div><div class="value">' + (w.alerts||[]).length + ' 条</div></div>' +
      '<div class="info-card"><div class="label">场景覆盖</div><div class="value">' + (s.scenario_override_active ? '⚠️ ' + (s.scenario_description||'激活中') : '✅ 无') + '</div></div>' +
      '<div class="info-card"><div class="label">活跃健康事件</div><div class="value">' + Object.keys(s.health_events||{}).length + ' 个</div></div>' +
      '<div class="info-card"><div class="label">航班延误</div><div class="value">' + Object.values(s.flights||{}).filter(f=>f.status==='delayed').length + ' 班</div></div>' +
      '<div class="info-card"><div class="label">当前用户</div><div class="value">' + ((s.current_user||{}).name || '未知') + '</div></div>';

    document.getElementById('state-time').textContent = ' (更新于 ' + new Date().toLocaleTimeString() + ')';

    // 高亮当前用户按钮
    const cu = s.current_user || {};
    document.querySelectorAll('.btn-user').forEach(b => b.classList.remove('active'));
    if (cu.active === 'white_collar') document.getElementById('btn-wc').classList.add('active');
    if (cu.active === 'parent') document.getElementById('btn-parent').classList.add('active');
    if (cu.active === 'student') document.getElementById('btn-student').classList.add('active');

    // 更新当前用户文字
    if (cu.active) {
      document.getElementById('current-user').textContent = '当前用户: ' + cu.name;
    }

  } catch(e) { console.error(e); }
}

// 初始化
refreshState();
// 每 30 秒自动刷新
setInterval(refreshState, 30000);
</script>
</body>
</html>""")
