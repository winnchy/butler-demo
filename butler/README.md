# 全天候私人管家 — 项目说明

基于 OpenClaw 框架的本地生活智能管家，服务三位北京用户（小琴/小冉/小晴），覆盖衣、食、行、逛、记五大场景。

## 项目结构

```
butler/
├── SOUL.md                 # Agent 人格定义（OpenClaw 读取）
├── USER.md                 # 当前用户画像（切换用户时覆盖）
├── MEMORY.md               # 当前用户记忆（切换用户时覆盖）
├── wardrobe.md             # 当前用户衣橱（切换用户时覆盖）
├── HEARTBEAT.md            # 心跳调度 Skill
├── switch_user.py          # 用户切换脚本（演示前手动运行）
├── skills/                 # 5 个核心 Skill
│   ├── dining-butler/      # 餐饮管家
│   ├── mobility-butler/    # 出行管家
│   ├── city-explorer/      # 本地活动管家
│   ├── outfit-advisor/     # 穿搭管家
│   └── life-organizer/     # 日程记忆管家
├── profiles/               # 用户模板库（OpenClaw 不直接读取）
│   ├── users/              # 三个用户的画像 + 衣橱
│   └── memories/           # 三个用户的记忆档案
│   └── scenarios.md        # 21 个演示场景
└── mock_backend/            # 动态模拟后端（独立 FastAPI 服务）
```

## 演示流程

### 1. 启动 Mock 后端
```bash
cd mock_backend
pip install fastapi uvicorn
python data_generator.py          # 一次性：生成丰富化数据
python route_generator.py       # 一次性：构建交通网络
python main.py                  # 启动 API 服务 → http://localhost:8000
```

### 2. 切换用户（每次演示前）
```bash
cd butler
python switch_user.py list          # 查看可用用户
python switch_user.py student       # 切换到小晴
python switch_user.py parent        # 切换到小冉
python switch_user.py white_collar  # 切换到小琴
```
此脚本将对应 `profiles/` 下的画像、记忆、衣橱复制到 OpenClaw 标准文件位置（USER.md / MEMORY.md / wardrobe.md）。

### 3. 启动 OpenClaw
```bash
# 在 butler 目录下启动 OpenClaw
# OpenClaw 自动读取 SOUL.md + USER.md + MEMORY.md + skills/*/SKILL.md
```

### 4. 触发场景（演示用）
```bash
# 通过 Mock 后端触发预设场景
curl -X POST http://localhost:8000/admin/trigger/scenario/1   # 接待上级
curl -X POST http://localhost:8000/admin/trigger/scenario/9   # 航班延误
curl -X POST http://localhost:8000/admin/trigger/scenario/15  # 地铁故障
curl -X POST http://localhost:8000/admin/reset                # 恢复正常
```

## 动态沙盒
Mock 后端内置 WorldState 引擎，定时更新天气、路况、排队、健康事件等动态数据。21 个场景覆盖暴雨、沙尘暴、地铁故障、宠物急诊、航班延误等真实突发事件。

## API 文档
后端启动后访问 `http://localhost:8000/docs` 查看完整 API 文档（FastAPI 自动生成）。
