---
name: HEARTBEAT
description: 系统心跳调度器，定时触发各 Skill 的主动推送任务、轮询监控条件、监听突发天气与排队事件，不直接面向用户，而是唤醒其他 Skill 执行具体任务
---

# 心跳调度器 (heartbeat) Skill

## 1. 定位
整个管家系统的"心跳"和"中枢神经"。不直接处理衣、食、行、娱具体业务，而是维护一张7*24小时全天候任务清单，在正确的时间点唤醒对应的 Skill 去执行。

## 2. 核心职责

### 2.1 定时任务调度
按预设时间表，唤醒各 Skill 执行主动推送：
- 早晚定时推送（天气、穿搭、通勤）
- 用餐时段推荐（午餐、晚餐）
- 周末活动推荐
- 换季提醒

### 2.2 事件轮询
持续监控外部条件，满足条件时触发对应 Skill：
- 突发天气预警 → `outfit-advisor` + `dining-butler` + `mobility-butler`
- 排队监控触发 → `dining-butler` + `mobility-butler`
- 日程即将到期 → `life-organizer`

### 2.3 特殊日期检测
- 每日检查是否为特殊日期（生日、纪念日、节日、发薪日、生理期）
- 提前 N 天触发对应 Skill 做好准备

### 2.4 健康标签维护
- 每日检查用户健康标签有效期
- 过期自动清除，仍有效的传递给 `dining-butler`

## 3. 触发条件

### 3.1 系统级触发（不依赖用户输入）
- 后台定时器按本 Skill 时间表自动执行
- 建议实现方式：系统定时任务（APScheduler / cron）每 1 分钟执行一次本 Skill 的主循环

### 3.2 主循环流程
1. 获取当前时间（精确到分钟）
2. 匹配时间表，判断是否有定时任务需要触发
3. 轮询 `GET /api/weather/alerts` 检查突发天气
4. 轮询 `/api/dining/monitor/check` 检查排队监控
5. 轮询 `GET /api/schedule/upcoming?user_id=xxx&hours=1` 检查即将到期的日程提醒
6. 对每个需要触发的任务，调用对应 Skill 的执行函数

## 4. 定时任务清单

### 4.1 每日定时
| 时间 | 唤醒 Skill | 执行任务 |
|------|-----------|----------|
| 07:00 | `outfit-advisor` | 推送今日天气 + 穿搭确认卡片 |
| 07:00 | `mobility-butler` | 推送今日通勤路况与建议出发时间 |
| 11:30 | `dining-butler` | 推送午餐建议，展示常去餐厅排队 |
| 17:30 | `mobility-butler` | 推送晚高峰回家路况 |
| 17:30 | `dining-butler` | 若有晚餐计划，提醒出发 |
| 21:00 | `outfit-advisor` | 推送次日天气 + 穿搭建议 |

### 4.2 每周定时
| 时间 | 唤醒 Skill | 执行任务 |
|------|-----------|----------|
| 周五 18:00 | `city-explorer` | 推送周末活动精选 |
| 周五 18:00 | `dining-butler` | 提醒周末热门餐厅可提前取号 |
| 周日 10:00 | `life-organizer` | 汇总下周日程，推送周报 |

### 4.3 特殊日期触发
| 触发条件 | 唤醒 Skill | 执行任务 |
|----------|-----------|----------|
| 生日/纪念日前3天 | `dining-butler` | 提醒预订庆祝餐厅 |
| 发薪日 | `life-organizer` | 推送"今天发工资"提醒 |
| 节日前3天 | `city-explorer` | 推送节庆活动 |
| 限行日前1天 | `mobility-butler` | 推送限行提醒 |

### 4.4 事件驱动触发
| 触发条件 | 唤醒 Skill | 执行任务 |
|----------|-----------|----------|
| 突发暴雨/大雪 | `outfit-advisor` | 推送紧急天气卡片 |
| 突发暴雨/大雪 | `dining-butler` | 建议改为外卖 |
| 突发暴雨/大雪 | `mobility-butler` | 建议调整出行方式 |
| 排队监控触发 | `dining-butler` | 推送出发提醒卡片 |
| 排队监控触发 | `mobility-butler` | 联动叫车 |
| 健康标签(上火) | `dining-butler` | 推送时标注"清淡优先" |
| 换季信号检测 (`wardrobe_season_ready: pending`) | `outfit-advisor` | 最近一个周五 20:00 推送衣橱调整与采购提醒 |

## 5. 关键参数
| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| current_time | string | 是 | 当前时间（系统注入） |
| user_id | string | 是 | 用户标识 |
| timezone | string | 否 | 时区，默认 Asia/Shanghai |

## 6. 后端接口依赖
| 接口 | 用途 | 频率 |
|------|------|------|
| `GET /api/weather/alerts` | 检查突发天气 | 每5分钟 |
| `GET /api/dining/monitor/check?user_id=xxx` | 检查排队监控 | 每2分钟 |
| `GET /api/schedule/upcoming?user_id=xxx&hours=1` | 检查即将到期的日程提醒 | 每1分钟 |
| `GET /api/special-dates?user_id=xxx` | 检查特殊日期（纪念日/生日等） | 每日1次 |
| `GET /api/weather/trend?city=xxx&days=14` | 换季趋势检测（由 `outfit-advisor` 每日附带执行，非本 Skill 直接调用） | 每日 |

## 7. 与其他 Skill 协同
本 Skill 是所有 Skill 的上游调度者。其他 Skill 的**主动推送**和**事件响应**功能，均由本 Skill 在满足条件时唤醒执行。各 Skill 的**被动查询**功能（用户主动询问）不受本 Skill 控制，由 OpenClaw 的路由机制直接触发。
## 8. 输出规范
- 本 Skill 本身不向用户输出任何内容
- 所有面向用户的内容，由被唤醒的 Skill 按其自身的卡片输出规范执行
- 心跳执行的日志信息记录到系统日志，供用户查看后台运行状态

## 9. 约束
- 定时任务时间可配置，用户可自定义调整
- 所有调度基于模拟时间轴，不依赖真实时钟（方便演示时加速展示）
- 突发天气和排队事件由 Mock 后端动态生成