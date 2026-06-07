# LocalLife Butler — 全天候私人管家

基于 [OpenClaw](https://github.com/openclaw/openclaw) v2026.5.28 框架的本地生活 AI 管家。服务三位北京用户（白领小琴、宝妈小冉、大学生小晴），覆盖衣、食、行、逛、记五大场景，支持 21 个动态沙盒演示场景。

> **版本说明：** 框架要求 ≥ v2026.4.24（DeepSeek 支持）。实际部署通过 `npm install openclaw@latest` 自动安装最新稳定版 v2026.5.28。

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
│  Railway Service 2: Butler Agent         │
│  ┌────────────────────────────────────┐  │
│  │  OpenClaw Gateway (:18789)         │  │
│  │  - 读取 butler/ 全部标准文件       │  │
│  │  - SOUL.md + SKILL.md + USER.md    │  │
│  │  - 调用 DeepSeek API (LLM 大脑)    │  │
│  │  - 通过 MCP Bridge 调用后端工具    │  │
│  ├────────────────────────────────────┤  │
│  │  MCP Bridge (:18790)               │  │
│  │  - 注册 26 个 MCP 工具             │  │
│  │  - 转发到 Service 1 (BACKEND_URL)  │  │
│  ├────────────────────────────────────┤  │
│  │  Chat Proxy (:8080)                │  │
│  │  - H5 聊天界面                     │  │
│  │  - 双模式降级：OpenClaw / 直连 DS  │  │
│  │  - HEARTBEAT + GUARDIAN 后台引擎   │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
    │ HTTP (BACKEND_URL)
    ▼
┌──────────────────────────────────────────┐
│  Railway Service 1: Mock Backend         │
│  - 30+ REST API 端点                     │
│  - WorldState 7x24 动态引擎              │
│  - 天气 / 路况 / 排队 / 航班 / 健康      │
│  - 371 站北京地铁网络 + Dijkstra 路径规划 │
└──────────────────────────────────────────┘
```

## 项目结构

```
├── butler/                     # OpenClaw 工作区（Agent 标准文件）
│   ├── SOUL.md                 # Agent 灵魂设定
│   ├── HEARTBEAT.md            # 心跳调度 Skill
│   ├── USER.md                 # 当前用户画像（运行时从 profiles/ 复制）
│   ├── MEMORY.md               # 当前用户记忆（运行时从 profiles/ 复制）
│   ├── wardrobe.md             # 当前用户衣橱（运行时从 profiles/ 复制）
│   ├── switch_user.py          # 用户切换脚本（CLI）
│   ├── skills/                 # 8 个 Skill（OpenClaw 插件格式）
│   │   ├── dining-butler/      #   餐饮管家
│   │   ├── mobility-butler/    #   出行管家
│   │   ├── outfit-advisor/     #   穿搭管家
│   │   ├── city-explorer/      #   活动管家
│   │   └── life-organizer/     #   日程管家
│   └── profiles/               # 三用户模板库
│       ├── users/              #   用户画像（每人一份）
│       └── memories/           #   用户记忆（每人一份）
│
├── agent/                      # Service 2: Butler Agent
│   ├── chat_proxy.py           # 主程序：Chat API + H5 前端 + 26 工具 + Agent Loop
│   ├── mcp_bridge.py           # MCP Bridge（26 工具 → 后端 API）
│   ├── heartbeat.py            # HEARTBEAT 定时调度引擎
│   ├── guardian.py             # GUARDIAN 事件检测引擎
│   ├── scenario_scripts.py     # 21 个沙盒场景定义
│   ├── start.sh                # 启动脚本（Gateway + MCP + Chat Proxy）
│   ├── Dockerfile              # Node.js + Python + OpenClaw 镜像
│   └── requirements.txt        # Python 依赖
│
├── mock_backend/               # Service 1: 动态模拟后端
│   ├── main_api.py             # FastAPI 入口
│   ├── config.py               # 全局配置 + 场景触发器
│   ├── world_state.py          # WorldState 动态引擎
│   ├── route_generator.py      # 路径规划（Dijkstra + 371 站地铁）
│   ├── enrich_pois.py          # POI 数据生成
│   ├── api_routes/             # API 路由模块
│   │   ├── dining_routes.py    #   餐饮 API
│   │   ├── mobility_routes.py  #   出行 API
│   │   ├── outfit_routes.py    #   穿搭 + 天气 API
│   │   ├── city_routes.py      #   活动 + 购物 API
│   │   ├── life_routes.py      #   日程 + 记忆 API
│   │   └── admin_routes.py     #   管理 API（场景/加速/重置）
│   └── Dockerfile              # Python 镜像
│
├── railway.toml                # Railway 部署配置
└── README.md
```

## 快速开始

### 本地开发

```bash
# 终端 1: 启动 Mock Backend (Service 1)
cd mock_backend
pip install fastapi uvicorn requests
python enrich_pois.py && python route_generator.py
python main_api.py
# → http://localhost:8000/docs        API 文档
# → http://localhost:8000/admin/dashboard  管理面板

# 终端 2: 启动 Butler Agent (Service 2)
cd agent
pip install fastapi uvicorn openai requests httpx
set OPENAI_API_KEY=sk-xxx           # DeepSeek API Key
set BACKEND_URL=http://localhost:8000
python chat_proxy.py
# → http://localhost:8080            H5 聊天界面（评委入口）
```

### 部署到 Railway

**Service 1 — Mock Backend:**
1. Railway → New Project → Deploy from GitHub
2. Root Directory: `mock_backend/`
3. Railway 自动检测 Dockerfile → 构建 → 上线
4. 记录生成的域名（如 `https://mock-backend-xxx.up.railway.app`）

**Service 2 — Butler Agent:**
1. 同一项目 → Add Service → Deploy from GitHub
2. Root Directory: `./`
3. 环境变量:
   - `PORT` = `8080`
   - `OPENAI_API_KEY` = `sk-xxx`（DeepSeek Key）
   - `OPENAI_BASE_URL` = `https://api.deepseek.com/v1`
   - `BACKEND_URL` = Service 1 的域名
4. Networking → Generate Domain
5. 评委访问 Service 2 的域名

## 核心特性

- **OpenClaw 原生运行**：Gateway 读取 butler/ 下全部标准文件（SOUL / SKILL / USER / MEMORY）
- **DeepSeek 驱动**：LLM 调用 26 个工具，MCP Bridge 转发到 Mock Backend
- **双服务架构**：Mock Backend（纯 API）+ Butler Agent（OpenClaw + Chat），职责分离
- **智能降级**：OpenClaw Gateway 不可用时自动切换到直连 DeepSeek 模式
- **三用户画像系统**：前端一键切换，后端复制对应 USER.md / MEMORY.md 到标准位置
- **7x24 WorldState**：天气 / 路况 / 排队 / 航班延误 / 健康事件
- **21 个沙盒场景**：一键触发，每场景涉及 ≥2 个 Skill 联动
- **实时监控**：排队进度 + 叫车倒计时，侧边栏 + 通知面板双通道
- **H5 聊天界面**：手机风格、语音输入（Web Speech API）
- **MCP 协议**：工具通过标准 MCP (Model Context Protocol) 注册

## 技术栈

| 组件 | 技术 |
|------|------|
| Agent 框架 | OpenClaw v2026.5.28（Gateway + MCP + 标准文件格式） |
| LLM | DeepSeek Chat（OpenAI 兼容 API） |
| 后端框架 | Python 3.12 + FastAPI |
| Agent 运行时 | Node.js 22 + Python + OpenClaw CLI |
| 工具协议 | MCP (Model Context Protocol) JSON-RPC 2.0 |
| 动态引擎 | WorldState 后台线程 |
| 路径规划 | Dijkstra 算法 + 371 站北京地铁网络 |
| 前端 | 内嵌 H5（响应式、语音输入、结构化卡片） |
| 部署 | Railway 双服务（Docker 容器化） |

## 比赛信息

- 命题：基于 OpenClaw 的本地生活「全天候私人管家」
- OpenClaw 版本：v2026.5.28（最低要求 v2026.4.24）
- Skill 数量：5 个核心 + HEARTBEAT + GUARDIAN + 3 个参考 Skill
- 场景数量：21 个动态沙盒场景（小琴 8 + 小冉 6 + 小晴 7）
- 工具数量：26 个（覆盖全部 5 个 Skill 的后端 API）
- 数据安全：所有用户数据为模拟数据，不收集真实个人信息
- 部署方式：Railway 双服务，全自动 CI/CD
