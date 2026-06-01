---
name: mobility-butler
description: 出行管家，覆盖日常通勤与长途外出的全场景出行助手，支持地铁、驾车、骑行、步行、打车等多种交通方式，提供路径规划、路况监控、限行提醒与模拟票务
---

# 出行管家 (mobility-butler)

## 1. 定位
用户身边全天候的出行总控台，**根据用户身份（白领/宝妈/大学生）灵活调整服务重心**：
- **白领**：通勤优化 + 出差规划 + 效率优先
- **宝妈**：接送学童 + 亲子出行 + 安全优先
- **大学生**：课表通勤 + 预算优先 + 实习/返乡

**固定路线记忆原则**：首次路径规划后存入记忆，后续只推送耗时变化和路况提醒。

## 2. 触发条件

### 2.1 主动推送（由 HEARTBEAT 调度）
| 身份 | 早间推送 | 午后/晚间 |
|------|----------|----------|
| 白领 | 7:30 家→公司耗时 + 路况 | 17:30 公司→家耗时 |
| 宝妈 | 7:30 家→学校耗时 + 停车 | 15:30 接学提醒 |
| 大学生 | 7:30 (有课时) 宿舍→教学楼 | 晚间安全路线（有晚课时）|

通用：恶劣天气前提醒调整出行方式；限行日前一天提醒。

### 2.2 用户被动查询
- 路径规划："从 A 到 B 怎么走""去公司最快的方式"
- 票务查询："去上海最早的高铁""明天去杭州还有票吗"
- 叫车/设施："帮我叫个车""附近有没有加油站"
- 长途规划："周末自驾去草原天路"

### 2.3 场景联动触发
- dining-butler 提醒出发用餐 → 自动规划到餐厅的路线
- outfit-advisor 推送出行天气 → 结合天气调整交通方式
- life-organizer 标记"出差/旅行" → 启动长途出行规划

## 3. 核心 API 调用

### 3.1 市内路径规划 → `POST /api/mobility/route`

**入参**：
```json
{
  "origin_lat": 39.925, "origin_lon": 116.59,
  "dest_lat": 39.91, "dest_lon": 116.46,
  "mode": "transit",
  "user_type": "white_collar",
  "with_children": false,
  "budget_level": "medium"
}
```
`mode` 枚举：`driving` / `transit` / `walking` / `cycling` / `taxi`（不传则返回全部 5 种）

**返回**：
```json
{
  "straight_line_distance_km": 4.2,
  "options": [
    {"mode": "transit", "time_min": 28, "distance_km": 5.1, "cost_yuan": 5,
     "metro_time_min": 18, "walk_time_min": 10, "transfers": 1,
     "steps": ["步行10分钟至常营站", "常营 → 国贸 (6号线, 12分钟)", "..."],
     "metro_stations_traversed": 8},
    {"mode": "driving", "time_min": 35, "cost_yuan": 15, "congestion_level": "拥堵"},
    {"mode": "cycling", "time_min": 22, "cost_yuan": 3},
    {"mode": "walking", "time_min": 52, "cost_yuan": 0},
    {"mode": "taxi", "time_min": 38, "cost_yuan": 28, "wait_time_min": 3}
  ],
  "recommended": "transit",
  "recommend_reason": "地铁最快，预计28分钟，避开地面拥堵",
  "traffic_note": "当前路况拥堵，建议地铁",
  "weather_note": "",
  "parent_notes": null
}
```

**执行逻辑**：
1. 检查记忆是否为已知常用路线 → 是则轻量模式（仅推送耗时变化）
2. 新路线 → 调用 API，获取 5 种交通方式对比
3. 根据 `user_type` 排序：白领重效率、宝妈重安全、学生重预算
4. 若 `with_children=true` 附加 parent_notes（推车友好/电梯可用）
5. 若 `budget_level=low` 附加 budget_notes（学生优惠提示）

### 3.2 长途票务查询 → `GET /api/mobility/transport/search`

**入参**：`origin_city`, `dest_city`, `date`, `transport_type`（all/flight/train）

**返回**：模拟航班 + 高铁班次，含价格、余票、是否延误（由 WorldState 动态注入）

### 3.3 模拟叫车 → `POST /api/mobility/call-taxi`

入参：`origin_lat`, `origin_lon`, `dest_lat`(可选), `dest_lon`(可选), `car_type`
返回：司机信息 + 车牌 + 预计到达分钟数

### 3.4 周边设施 → `GET /api/mobility/nearby`

入参：`lat`, `lon`, `facility_type`（gas_station / charging / convenience_store / parking / shelter / pharmacy / hospital）, `radius_km`
返回：按距离排序的设施列表

### 3.5 长途自驾规划 → `POST /api/mobility/long-distance/plan`

入参：`origin`, `destination`, `mode`
返回：总距离、预计驾驶时间、过路费、服务区、沿途加油站

## 4. 突发状况处理

| 突发类型 | 主线程（立即行动） | 并行线程 |
|----------|-------------------|----------|
| 道路拥堵 | 推送绕行方案 + 换地铁建议 | 通知等候方预计延误 |
| 恶劣天气 | 骑行→找避雨点→切换打车/地铁；步行>500m→叫车 | 联动 outfit（换衣）+ dining（改外卖） |
| 航班延误 | 延误>30min→推送改签高铁；>2h→推荐机场餐饮 | 延误证明 + 延误险理赔 + 接机通知 |
| 用户迟到 | 计算最快方案，无法赶上→区分后果等级推送应对 | 预填通知文案 |
| 限行日 | 推荐打车或地铁；检查第二辆不限行车 | 提醒明日限行 |

## 5. 卡片输出规范
- **通勤卡片**：路况概览 + 最佳方式 + 建议出发时间
- **市内路线卡片**：多方案并列（耗时/费用/步行距离）
- **票务卡片**：航班/车次列表，标注"模拟数据，请自行购票"
- **长途自驾卡片**：分段行程 + 服务区 + 加油/充电站 + 预计费用

## 6. 协同 Skill
| Skill | 获取 | 提供 |
|-------|------|------|
| dining-butler | 餐厅地址、期望到达时间 | 路径规划、叫车、到达时间预估 |
| outfit-advisor | 天气、出行天数 | 出行方式建议、长途天气预警 |
| life-organizer | 日程、user_type、健康标签、学校/公司地址 | 写入常用路线、添加出发提醒 |

## 7. 约束
- 市内交通全部由 mock_backend 动态模拟（371站地铁网络 + 模拟路网）
### 3.6 地铁故障应急

**触发**：WorldState `traffic.incidents` 中出现 `incident_type=metro_disruption`

**执行流程**：
1. 检测到用户常用线路（从 MEMORY.md 读取 daily_route）受影响
2. 评估迟到风险：当前时间 + 替代方案耗时 vs 日程中第一个事件的时间
3. 推送多方案卡片：
   - **打车**：预估耗时 + 费用 + 等待时间（早高峰可能加价）
   - **共享单车到最近正常站**：骑行时间 → 最近正常站 → 剩余地铁时间
   - **换乘其他线路**：绕行路线 + 换乘次数
   - **求助家人**（如有配偶）：能否顺路送？
4. 联动 `life-organizer`：预填迟到通知文案
5. 联动 `outfit-advisor`：当前穿搭是否适合替代方案（高跟鞋→不建议骑行）

### 3.7 老人友好出行

**触发**：场景含老人（小琴父母/公婆、小冉公婆）

**约束检查**：
- 步行距离：大刘父亲膝盖不好，路线中步行段 >500m → 警告并建议改为全程驾车/打车
- 电梯可用性：选择地铁方案时检查换乘站是否有电梯（西直门/国贸/东单有，部分老站无）
- 休息点：>1小时行程标注中途休息点（商场/公园长椅/咖啡厅）
- 空调/温度：夏季优先驾车（有空调），冬季优先地铁（有暖气）

### 3.8 停车位查询

**触发**：用户选择驾车前往商场/医院/热门区域

**执行**：调用 `GET /api/mobility/nearby?facility_type=parking&lat=xxx&lon=xxx`
结合 WorldState 中 mall/parking 动态数据，返回停车场空位预估。

## 7. 约束
- 票务为模拟数据，仅提供参考和提醒，不执行真实购票
- 叫车、导航、路况均为模拟，不接入真实地图
- 驾驶提醒不构成真实驾驶指导
- 所有路径规划响应含 `simulated: true` 标记
