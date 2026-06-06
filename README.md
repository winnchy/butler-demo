# 🛎️ 全天候私人管家 — LocalLife Butler

基于 [OpenClaw](https://github.com/openclaw/openclaw) v2026.4.15 插件规范的本地生活 AI 管家。服务三位北京用户（白领小琴、宝妈小冉、大学生小晴），覆盖衣、食、行、逛、记五大场景，支持 21 个动态沙盒演示场景。

## Demo 链接

| 服务 | URL | 说明 |
|------|-----|------|
| **Butler Agent** | `https://butler-agent-xxx.up.railway.app` | 评委交互入口（OpenClaw + Chat UI） |
| Mock Backend | `https://mock-backend-xxx.up.railway.app` | 动态数据 API（内部） |

## 架构

```
评委浏览器
    │
    ▼
┌──────────────────────────────────────────┐
│  Railway Service 2: butler-agent         │
│  ┌────────────────────────────────────┐  │
│  │  OpenClaw Gateway (:18789)         │  │
│  │  - 读取 butler/ 全部标准文件       │  │
│  │  - SOUL.md + 5×SKILL.md + USER.md  │  │
│  │  - 调用 DeepSeek API (LLM 大脑)    │  │
│  │  - 通过 MCP Bridge 调用后端工具    │  │
│  ├────────────────────────────────────┤  │
│  │  MCP Bridge (:18790)               │  │
│  │  - 注册 13 个 MCP 工具            │  │
│  │  - 转发到 Service 1 (BACKEND_URL)  │  │
│  ├────────────────────────────────────┤  │
│  │  Chat Proxy (:8080)                │  │
│  │  - H5 聊天界面                     │  │
│  │  - Gateway 优先 / 降级直连 DS      │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
    │ HTTP (BACKEND_URL)
    ▼
┌──────────────────────────────────────────┐
│  Railway Service 1: mock-backend         │
│  - 30+ REST API 端点                     │
│  - WorldState 7×24 动态引擎              │
│  - 天气/路况/排队/拥挤/健康/航班         │
└──────────────────────────────────────────┘
```

## 项目结构

```
├── butler/                     # OpenClaw 工作区（标准文件）
│   ├── SOUL.md                 # Agent 灵魂设定
│   ├── HEARTBEAT.md            # 心跳调度 Skill
│   ├── USER.md                 # 当前用户画像
│   ├── MEMORY.md               # 当前用户记忆
│   ├── skills/                 # 5 个核心 Skill（OpenClaw 插件格式）
│   │   ├── dining-butler/      #   餐饮管家
│   │   ├── mobility-butler/    #   出行管家
│   │   ├── city-explorer/      #   活动管家
│   │   ├── outfit-advisor/     #   穿搭管家
│   │   └── life-organizer/     #   日程管家
│   └── profiles/               # 用户模板库
│
├── mock_backend/               # Service 1: 动态模拟后端
│   ├── main_api.py             # 纯 API 服务器（FastAPI）
│   ├── config.py               # 全局配置
│   ├── enrich_pois.py          # POI 数据丰富化
│   ├── route_generator.py      # 路径规划引擎
│   ├── world_state.py          # WorldState 动态引擎
│   ├── api_routes/             # API 路由模块
│   └── Dockerfile              # Python-only 镜像
│
├── agent/                      # Service 2: OpenClaw Agent
│   ├── chat_proxy.py           # Chat 转发 + H5 前端 + 降级逻辑
│   ├── mcp_bridge.py           # MCP 工具桥（13 工具 → 后端 API）
│   ├── Dockerfile              # Node.js + Python + OpenClaw
│   └── start.sh                # 三进程启动脚本
│
├── railway.toml                # Railway 部署配置
└── README.md
```

## 快速开始

### 本地开发（双终端）

```bash
# 终端 1: 启动 Mock Backend (Service 1)
cd mock_backend
pip install fastapi uvicorn openai requests
python enrich_pois.py && python route_generator.py
python main_api.py
# → http://localhost:8000/docs   API 文档
# → http://localhost:8000/admin/dashboard  管理面板

# 终端 2: 启动 Butler Agent (Service 2)
cd agent
pip install fastapi uvicorn openai requests httpx
set OPENAI_API_KEY=sk-xxx  # DeepSeek API Key
set BACKEND_URL=http://localhost:8000
python chat_proxy.py
# → http://localhost:8080         H5 聊天界面（评委入口）
```

### 部署到 Railway

**Service 1 — Mock Backend:**
1. Railway → New Project → Deploy from GitHub
2. Root Directory: `mock_backend/`
3. 自动检测 Dockerfile → 构建 → 上线
4. 记录生成的域名（如 `https://mock-backend-xxx.up.railway.app`）

**Service 2 — Butler Agent:**
1. 同 Project → + New → Deploy from GitHub（再次选择同一仓库）
2. Root Directory: `./`
3. Settings → 添加环境变量:
   - `PORT` = `8080`
   - `OPENAI_API_KEY` = `sk-xxx`（DeepSeek Key）
   - `OPENAI_BASE_URL` = `https://api.deepseek.com/v1`
   - `BACKEND_URL` = `https://mock-backend-xxx.up.railway.app`（Service 1 的 URL）
4. Settings → Networking → Generate Domain
5. **评委访问 Service 2 的域名**

## 核心特性

- **OpenClaw 原生运行**：Gateway 真正读取 butler/ 下所有标准文件（SOUL/SKILL/USER/MEMORY）
- **DeepSeek 驱动**：LLM 调用 13 个 API 工具，MCP Bridge 转发到 Mock Backend
- **双服务架构**：Mock Backend（纯 API）+ Butler Agent（OpenClaw + Chat），职责分离
- **智能降级**：OpenClaw Gateway 不可用时自动切直连 DeepSeek，用户无感知
- **3 用户画像系统**：前端一键切换，后端自动读取对应 USER.md/MEMORY.md
- **7×24 WorldState**：天气/路况/排队/拥挤度/健康事件/航班延误/沙尘暴/地铁故障
- **21 个沙盒场景**：一键触发，≥2 个 Skill 联动
- **H5 聊天界面**：手机风格、语音输入（Web Speech API）
- **MCP 协议**：工具通过标准 MCP (Model Context Protocol) 注册，符合 OpenClaw 生态

## 技术栈

| 组件 | 技术 |
|------|------|
| Agent 规范 | OpenClaw v2026.4.15（Gateway + MCP Bridge + 标准文件格式） |
| LLM | DeepSeek V4 Pro（OpenAI 兼容 API） |
| 后端 API | Python 3.12 + FastAPI（Service 1） |
| Agent 服务 | Node.js 22 + Python + OpenClaw Gateway（Service 2） |
| 工具协议 | MCP (Model Context Protocol) JSON-RPC 2.0 |
| 动态引擎 | WorldState 后台线程 |
| 路径规划 | Dijkstra + 北京 371 站地铁网络 |
| 前端 | 内嵌 H5（手机风格、语音输入、卡片式回复） |
| 部署 | Railway 双服务 |

## 比赛信息

- 命题：基于 OpenClaw 的本地生活「全天候私人管家」
- OpenClaw 版本：v2026.4.15
- Skill 数量：5 个核心 + HEARTBEAT 心跳调度 + 3 个美团参考 Skill
- 场景数量：21 个动态沙盒场景
- MCP 工具：21 个（覆盖全部 5 个 Skill 的后端 API）
- 数据安全：所有用户数据为模拟数据，不收集真实个人信息
