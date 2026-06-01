# 🛎️ 全天候私人管家 — LocalLife Butler

基于 [OpenClaw](https://github.com/openclaw/openclaw) v2026.4.15 插件规范的本地生活 AI 管家。服务三位北京用户（白领小琴、宝妈小冉、大学生小晴），覆盖衣、食、行、逛、记五大场景，支持 21 个动态沙盒演示场景。

## Demo 链接

🔗 **https://butler-demo-production.up.railway.app**

## 项目结构

```
├── butler/                     # OpenClaw 工作区（SOUL + Skills + 用户画像）
│   ├── SOUL.md                 # Agent 灵魂设定（system prompt）
│   ├── HEARTBEAT.md            # 心跳调度 Skill
│   ├── switch_user.py          # 用户切换脚本（演示用）
│   ├── skills/                 # 5 个核心 Skill（OpenClaw 插件格式）
│   │   ├── dining-butler/      #   餐饮管家
│   │   ├── mobility-butler/    #   出行管家
│   │   ├── city-explorer/      #   活动管家
│   │   ├── outfit-advisor/     #   穿搭管家
│   │   └── life-organizer/     #   日程管家
│   └── profiles/               # 用户模板库
│       ├── users/              #   3 个用户画像 + 衣橱
│       ├── memories/           #   3 个用户记忆档案
│       └── scenarios.md        #   21 个演示场景
│
├── mock_backend/               # 动态模拟后端（FastAPI + DeepSeek）
│   ├── main.py                 # 服务器 + H5 前端 + /chat AI 端点
│   ├── config.py               # 全局配置（菜系关键词、地铁线路、拥堵参数）
│   ├── enrich_pois.py          # POI 数据丰富化管道（856 条北京种子数据）
│   ├── route_generator.py      # 371 站地铁网络 + 模拟路网 + Dijkstra 路径规划
│   ├── world_state.py          # 7×24 WorldState 动态引擎（天气/路况/排队/事件）
│   └── api_routes/             # 30+ API 端点
│
├── railway.toml                # Railway 部署配置
├── .env.example                # API Key 模板
└── .gitignore
```

## 快速开始

### 本地开发
```bash
cd mock_backend
pip install fastapi uvicorn openai
python enrich_pois.py
python route_generator.py
python main.py
# → http://localhost:8000        H5 聊天界面
# → http://localhost:8000/docs   API 文档
# → http://localhost:8000/admin/dashboard  管理面板
```

### 部署到 Railway
1. Fork 本仓库
2. Railway → New Project → Deploy from GitHub
3. Settings → Variables → 添加 `OPENAI_API_KEY`（DeepSeek Key）
4. Railway 自动检测 Dockerfile → 构建 → 上线

## 架构

```
评委浏览器 → H5 聊天界面 (FastAPI serve)
                ↓
         POST /chat (DeepSeek API + 13 个工具)
                ↓
         SOUL.md (system prompt)
         USER.md + MEMORY.md (用户上下文)
         SKILL.md × 5 (技能定义)
                ↓
         LLM 调工具 → mock_backend API → 返回数据
                ↓
         WorldState 后台线程 (7×24 动态更新)
```

## 技术栈

| 组件 | 技术 |
|------|------|
| Agent 规范 | OpenClaw v2026.4.15 插件格式（SKILL.md frontmatter） |
| LLM | DeepSeek V4 Pro（OpenAI 兼容 API） |
| 后端 | Python 3.12 + FastAPI |
| 动态引擎 | WorldState 后台线程（定时更新天气/路况/排队/事件） |
| 数据来源 | 高德地图 API 种子数据（856 条北京 POI）+ 算法丰富化 |
| 路径规划 | Dijkstra + 北京 371 站地铁网络 + 模拟路网 |
| 前端 | 内嵌 H5（手机风格、语音输入、卡片式回复） |
| 部署 | Railway (Docker) |

## 核心特性

- **5 个 OpenClaw Skill**：严格遵循插件规范（SKILL.md + frontmatter），SOUL.md 作为 system prompt
- **DeepSeek 驱动**：LLM 读取 SOUL.md + USER.md + MEMORY.md，调用 13 个 API 工具，完全模拟 OpenClaw Agent 行为
- **3 用户画像系统**：前端一键切换，后端自动读取对应 USER.md/MEMORY.md，场景感知推荐
- **7×24 WorldState**：天气/路况/排队/拥挤度/健康事件/航班延误/沙尘暴/地铁故障持续后台更新
- **21 个沙盒场景**：一键触发（暴雨、沙尘暴、地铁故障、宠物急诊、航班延误……）
- **H5 聊天界面**：手机风格、语音输入（Web Speech API）、卡片式回复（餐厅卡/天气卡/路线卡）
- **思考计时器**：AI 思考时动态显示"已思考 X 秒"

## 比赛信息

- 命题：基于 OpenClaw 的本地生活「全天候私人管家」
- OpenClaw 版本：v2026.4.15（稳定版）
- Skill 数量：5 个核心 + HEARTBEAT 心跳调度
- 场景数量：21 个动态沙盒场景
- 数据安全：所有用户数据为模拟数据，不收集真实个人信息
