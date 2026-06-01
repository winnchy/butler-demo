# 🛎️ 全天候私人管家 — LocalLife Butler

基于 [OpenClaw](https://github.com/openclaw/openclaw) v2026.4.15 框架的本地生活 AI 管家。服务三位北京用户（白领小琴、宝妈小冉、大学生小晴），覆盖衣、食、行、逛、记五大场景，支持 21 个动态沙盒演示场景。

## 项目结构

```
mt_workspace/
├── butler/                     # 管家的大脑（OpenClaw Skill 定义）
│   ├── SOUL.md                 # Agent 人格设定
│   ├── HEARTBEAT.md            # 心跳调度 Skill
│   ├── switch_user.py          # 用户切换脚本
│   ├── skills/                 # 5 个核心 Skill
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
├── mock_backend/               # 动态模拟后端（FastAPI）
│   ├── main.py                 # 服务器入口 + H5 前端
│   ├── config.py               # 全局配置（菜系、地铁、拥堵参数…）
│   ├── enrich_pois.py          # POI 数据丰富化管道
│   ├── route_generator.py      # 地铁网络 + 路网 + 路径规划
│   ├── world_state.py          # WorldState 动态引擎
│   ├── data/                   # 种子数据
│   └── api_routes/             # API 路由
│
├── docker-compose.yml          # Docker 编排
├── start.sh                    # 一键启动脚本
├── .env.example                # API Key 模板
└── .gitignore
```

## 快速开始

### 本地开发
```bash
cd mock_backend
pip install fastapi uvicorn
python enrich_pois.py
python route_generator.py
python main.py
# → http://localhost:8000  H5 聊天界面
# → http://localhost:8000/docs  API 文档
# → http://localhost:8000/admin/dashboard  管理面板
```

### Docker 部署（含 OpenClaw）
```bash
cp .env.example .env
# 编辑 .env 填入 ANTHROPIC_API_KEY
./start.sh
# → http://localhost:8000  H5 聊天界面
# → http://localhost:3000  OpenClaw Web 界面
```

## 技术栈

| 组件 | 技术 |
|------|------|
| Agent 框架 | OpenClaw v2026.4.15 |
| 后端 | Python 3.12 + FastAPI |
| 动态引擎 | WorldState（后台线程持续更新天气/路况/排队） |
| 数据来源 | 高德地图 API 种子数据 + 算法丰富化 |
| 路径规划 | Dijkstra + 北京 371 站地铁网络 + 模拟路网 |
| 前端 | 内嵌 H5（HTML/CSS/JS，Web Speech API 语音） |
| 部署 | Docker Compose（openclaw + mock_backend） |

## 核心特性

- **5 个 OpenClaw Skill**：严格遵循插件规范（SKILL.md + frontmatter）
- **3 用户画像系统**：一键切换，场景感知推荐（非硬编码过滤）
- **WorldState 动态引擎**：天气/路况/排队/拥挤度/健康事件/航班延误持续变化
- **21 个沙盒场景**：暴雨、沙尘暴、地铁故障、宠物急诊、航班延误……
- **场景触发器**：评委可通过管理面板一键触发预设场景
- **H5 聊天界面**：手机风格、语音输入、卡片式回复

## 比赛信息

- 命题：基于 OpenClaw 的本地生活「全天候私人管家」
- OpenClaw 版本：v2026.4.15（稳定版）
- Skill 数量：5 个核心 + 1 个心跳调度
- 数据安全：所有用户数据为模拟数据，不收集真实个人信息
