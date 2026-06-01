---
name: life-organizer
description: 日程与记忆管家，统管用户日程、提醒、纪念日、周期性事件及跨 Skill 协同调度，在正确的时间触发正确的 Skill
---

# 日程与记忆管家 (life-organizer)

## 1. 定位
整个管家系统的调度中枢。不直接处理衣、食、行具体业务，而是管理"什么时候该做什么事"，并在正确的时间节点唤醒对应的 Skill。同时维护用户和重要人物的长期记忆档案。

## 2. 核心职责

### 2.1 日程管理
- 创建日程：用户口头说"下周三下午3点开会""明天提醒我交电费"
- 查询日程："今天有什么安排""这周末有空吗"
- 修改/取消："把明天的会议改到后天"
- 冲突检测：新建日程时自动检查是否与已有安排冲突

### 2.2 提醒与闹钟
- 一次性提醒："30分钟后提醒我看锅"
- 周期性提醒："每周五下午5点提醒我提交周报"
- 条件提醒："到家门口时提醒我拿快递"（基于位置模拟）
- 跨 Skill 提醒：按 HEARTBEAT 时间表唤醒其他 Skill

### 2.3 特殊日期管理
- 生日：用户及重要人物生日，提前3天提醒准备礼物/订餐厅
- 纪念日：恋爱纪念日、结婚纪念日、入职纪念日
- 节日：情人节、母亲节、春节等
- 发薪日：每月提醒，可联动 dining-butler 建议"今天吃点好的"
- 生理期：每月提前提醒，联动 dining-butler 清淡饮食建议

### 2.4 健康与生活提醒
- 体检提醒 / 宠物驱虫疫苗 / 车辆年检保险 / 信用卡还款

### 2.5 跨 Skill 调度
- 按 HEARTBEAT 定时表唤醒对应 Skill
- 根据实时事件（突发天气、排队触发等）动态插入紧急任务

### 2.6 记忆档案管理
- `memory.md`：用户自身长期记忆
- `person_{name}.md`：重要人物档案
- `health.md`：健康相关记忆
- `vehicle.md`：车辆信息

## 3. 核心 API 调用

### 3.1 创建日程 → `POST /api/schedule/create`

**入参**：
```json
{
  "user_id": "white_collar",
  "title": "老爸生日聚餐",
  "date": "2026-06-02",
  "time": "18:30",
  "end_time": "20:30",
  "location": "金悦(金融街购物中心店)",
  "notes": "提前订包厢，备蛋糕",
  "reminder_minutes": 1440
}
```

**返回**：
```json
{
  "ok": true,
  "schedule": {
    "id": 123,
    "title": "老爸生日聚餐",
    "date": "2026-06-02", "time": "18:30",
    "end_time": "20:30", "location": "金悦(金融街购物中心店)",
    "reminder_minutes": 1440
  }
}
```

**执行逻辑**：
1. 解析用户意图（日期、时间、事件内容、是否重复）
2. 调用 API 存入
3. 若与已有日程冲突 → 提醒用户
4. 若 `related_skill` 非空 → 通知对应 Skill 做好准备

### 3.2 查询今日日程 → `GET /api/schedule/today?user_id=white_collar`

```json
// 返回
{
  "user_id": "white_collar",
  "date": "2026-06-02",
  "schedules": [
    {"id": 1, "title": "晨会", "date": "2026-06-02", "time": "09:00",
     "end_time": "10:00", "location": "公司会议室", "reminder_minutes": 15}
  ]
}
```

### 3.3 查询本周日程 → `GET /api/schedule/week?user_id=white_collar`

返回本周所有日程列表，用于用户问"这周有什么安排"。

### 3.4 即将到期提醒（HEARTBEAT 轮询用）→ `GET /api/schedule/upcoming?user_id=white_collar&hours=24`

```json
// 返回
{
  "user_id": "white_collar",
  "upcoming": [
    {"id": 1, "title": "晨会", "date": "2026-06-02", "time": "09:00",
     "in_hours": 0.5, "reminder_minutes": 15}
  ]
}
```
HEARTBEAT 每 1 分钟轮询一次，`hours=1` 只取未来1小时内的。

### 3.5 保存记忆 → `POST /api/memory/save`

**入参**：
```json
{
  "user_id": "white_collar",
  "key": "favorite_cuisine",
  "value": "川菜",
  "category": "dining"
}
```
- `category` 枚举：`dining`（口味偏好）/ `mobility`（出行习惯）/ `health`（健康标签）/ `special_dates`（纪念日）/ `pets`（宠物）/ `general`（通用）

**返回**：
```json
{"ok": true, "memory": {"key": "favorite_cuisine", "value": "川菜", "category": "dining"}, "action": "updated"}
```
若 `key` 已存在则更新（`action: "updated"`），否则新建（`action: "created"`）。

### 3.6 搜索记忆 → `GET /api/memory/search?user_id=white_collar&keyword=川`

返回匹配的记忆列表。各 Skill 在需要用户偏好时调用此接口。

### 3.7 特殊日期 → `GET /api/special-dates?user_id=white_collar`

```json
// 返回
{
  "user_id": "white_collar",
  "special_dates": [
    {"key": "wedding_anniversary", "value": "6月18日", "category": "special_dates"}
  ],
  "health_tags": ["果果花生过敏"],
  "active_health_event": null
}
```
同时返回健康标签和是否有活跃健康事件（如"乐乐发烧"）。

### 3.8 健康提醒 → `GET /api/health-reminder?user_id=white_collar`

```json
// 返回
{
  "user_id": "white_collar",
  "reminders": ["久坐提醒: 每小时站起来活动一下", "饮水提醒: 今日已饮 4/8 杯"],
  "active_health_event": null
}
```
若 WorldState 中有活跃健康事件（如发烧/痛经），会在此返回。

## 4. 跨 Skill 调度

| 时间节点 | 唤醒 Skill | 动作 |
|---------|-----------|------|
| 每日 7:00 | outfit-advisor + mobility-butler | 天气穿搭 + 通勤推送 |
| 工作日 11:30 | dining-butler | 午餐推荐 |
| 工作日 17:30 | mobility-butler + dining-butler | 晚高峰路况 + 晚餐推荐 |
| 周五 18:00 | city-explorer | 周末活动推荐 |
| 周五 20:00 | outfit-advisor | 换季衣橱提醒（条件触发） |
| 每 1 分钟 | 自身 | 轮询 upcoming 日程提醒 |
| 每 2 分钟 | dining-butler | 轮询排队监控 |
| 每 5 分钟 | outfit-advisor | 轮询天气预警 |
| 每月 15 号 | 自身 | 生理期提醒（小晴） |
| 每月 20 号 | dining-butler + 自身 | 奶茶配额检查（小晴） |

## 5. 记忆文件规范

以下文件由 Agent 在运行时通过 `POST /api/memory/save` 动态创建和维护，存储在 OpenClaw 可访问的工作区中。初始状态下不要求这些文件物理存在。

| 文件 | 内容 | 写入者 |
|------|------|--------|
| `MEMORY.md` | 用户自身偏好、习惯、历史（OpenClaw 标准文件，切换用户时从 profiles/memories/ 复制） | 所有 Skill（通过 life-organizer API 统一写入） |
| `person_{name}.md` | 重要人物档案（口味、过敏、偏好），由 Agent 运行时创建 | dining-butler |
| `health.md` | 健康标签、过敏、体检记录，由 Agent 运行时创建 | life-organizer + dining-butler |
| `vehicle.md` | 车牌、保险、年检、限行日，由 Agent 运行时创建 | mobility-butler |

## 6. 与其他 Skill 协同

| 协同 Skill | 调度内容 |
|------------|----------|
| outfit-advisor | 早晚天气推送、换季提醒、突发天气预警 |
| dining-butler | 午餐/晚餐建议、生日餐厅预订、排队监控、奶茶配额 |
| mobility-butler | 通勤提醒、长途出行准备、限行提醒 |
| city-explorer | 周末活动推荐、节日活动提醒 |

## 7. 约束
- 所有日程和记忆为模拟数据，不存储真实个人信息
- 记忆搜索支持关键词模糊匹配
- 健康标签有时效性（"上火"有效期3天，过期自动清除）
- 提醒内容明确标注"模拟"
- 跨 Skill 调度不直接输出用户内容，由被唤醒的 Skill 按其规范推送
