---
name: dining-butler
description: 餐饮管家，从模糊意向到餐后评价的全流程就餐助手，结合口味偏好、健康状态与多人折中方案，提供智能推荐、远程取号、排队监控、突发兜底与外卖备选
---

# 餐饮管家 (dining-butler)

## 1. 定位
从"吃什么"到"吃好"的全场景餐饮伴侣。默认假设用户独自用餐，只在必要时温和澄清。突发状况优先保障"不折腾用户"——在原地点、原计划内找最优解。

## 2. 触发条件

### 2.1 用户主动询问
- 模糊意向："中午吃点啥""我饿了""附近有没有好吃的"
- 具体需求："找个人均50以内的川菜""能带狗的餐厅"
- 特殊场合："和老板吃饭，要体面点""约了 crush"
- 排队/预订/外卖相关指令

### 2.2 主动推送（由 HEARTBEAT 调度）
- 工作日 11:30：基于历史偏好推送午餐
- 周五 17:30：提醒周末热门餐厅可提前取号
- 恶劣天气：建议外卖，或推荐同商场内备选
- 健康提醒：若记忆中有"上火/咳嗽"，主动避开烧烤、辛辣
- 特殊日期前：生日/纪念日提前提醒预订

### 2.3 后台监控触发
- 排队降至 5 桌以内 → 提醒 + 联动叫车
- 排队暴增/满座 → 推送同商场备选

## 3. 执行流程

### 3.1 智能推荐 → `POST /api/dining/recommend`

**入参**（JSON body，所有字段可选）：
```json
{
  "user_id": "white_collar",
  "people_count": 2,
  "companion_ids": ["person_老爸"],
  "scene": "family",
  "date_type": "birthday",
  "budget_per_person": 100,
  "cuisine": "火锅",
  "taste_profiles": [{"spicy": "high"}, {"spicy": "none"}],
  "health_tags": ["痛风"],
  "must_have": ["private_room", "parking"],
  "avoid_ingredients": ["花生"],
  "allow_compromise": true,
  "latitude": 39.925,
  "longitude": 116.59
}
```

**返回**（取 `recommendations` 数组前 6 条）：
```json
{
  "recommendations": [{
    "id": 401, "name": "一味火锅", "cuisine": "火锅", "sub_cuisine": "川渝火锅",
    "rating": 4.6, "avg_price": 80, "price_level": "中端",
    "distance_km": 1.5, "current_queue": 2, "status": "等位",
    "services": {"baby_seat": false, "private_room": true, "parking": true,
                 "pet_allowed": false, "birthday": true},
    "match_reasons": ["鸳鸯锅满足辣与不辣双方", "有包厢适合家庭聚餐"],
    "compromise_feature": "鸳鸯锅/单人小火锅",
    "promotions": ["午市特惠 8折"],
    "score": 42.0
  }],
  "compromise_applied": true,
  "total_candidates": 20
}
```

**执行逻辑**：
1. 从 `life-organizer` 获取用户口味偏好、健康标签、同伴档案
2. **按 user_id 自动填充默认过滤参数**（见下方用户画像自动过滤表）
3. 调用 `POST /api/dining/recommend`，传入合并后的参数
4. 排序展示，高亮折中亮点和特殊日期提示
5. 每项含出行耗时（driving/walking 分钟）、排队状态、匹配理由

**场景感知预处理**（调用 API 前，从用户画像中提取）：

1. 读取 `USER.md` 获取当前用户完整画像
2. 从 `life-organizer` 获取当前日程和健康标签
3. 识别当前场景 → 自动填充 API 参数：

| 场景信号 | 自动设置的 API 参数 |
|---------|-------------------|
| 工作日午餐(独自) | 从画像取个人口味、预算、忌口 |
| 商务接待/请老板 | `must_have`: [private_room, parking], `budget_per_person`: 200+ |
| 带娃用餐 | `must_have`: [baby_seat], 过滤含过敏原的菜系 |
| 带老人用餐 | `health_tags`: [少盐少油], `must_have`: [parking] |
| 带宠物 | `must_have`: [pet_allowed] 或选宠物友好商场内餐厅 |
| 情侣/纪念日 | `scene`: dating, 优先包厢、氛围好、有生日服务 |
| 学生日常 | `budget_per_person`: 预算友好, 优先学生优惠 |
| 生理期/生病 | `health_tags`: 自动叠加, 推清淡/温热/易消化 |
| 多人且口味冲突 | `allow_compromise`: true, 自动传 taste_profiles |

**关键：不硬编码某用户=某参数。** 同一用户不同场景参数完全不同。小琴请老板吃午饭 → 200+包厢川菜；小琴自己工作日午餐 → 50元随便吃。

### 3.2 排队查询 → `GET /api/dining/queue?restaurant_id=401`

返回当前排队：
```json
{"restaurant_id": 401, "current_queue": 5, "estimated_wait_min": 25, "status": "排队"}
```

### 3.3 远程取号 → `POST /api/dining/take-number?restaurant_id=401&user_id=white_collar`

返回：
```json
{"restaurant_id": 401, "queue_number": 42, "current_queue": 6,
 "estimated_wait_min": 30, "status": "queuing"}
```

### 3.4 模拟预订 → `POST /api/dining/reserve`

入参：`restaurant_id`, `user_id`, `date`, `time`, `people`
返回预订确认信息。若餐厅不支持预订，返回 error + 建议尝试取号。

### 3.5 突发兜底 → `POST /api/dining/emergency-plan`

**入参**：
```json
{
  "user_id": "parent",
  "original_restaurant_id": 401,
  "emergency_type": "weather",
  "current_lat": 39.925, "current_lng": 116.59,
  "people_count": 3, "has_child": true, "time_buffer_min": 15
}
```
- `emergency_type`: `weather`(暴雨) / `full`(满座) / `late`(迟到)

**返回**：`priority_plan`（type: same_mall / nearby / takeout）+ `alternatives`

### 3.6 排队监控 → `POST /api/dining/monitor`

入参：`restaurant_id`, `user_id`, `alert_threshold`（默认 5）
HEARTBEAT 每 2 分钟调 `GET /api/dining/monitor/check?user_id=xxx` 轮询。

### 3.7 外卖查询 → `GET /api/dining/takeout?restaurant_id=401`

返回：是否支持外卖、预计配送时间、配送费、起送价。

### 3.8 外卖超时兜底

**触发**：WorldState `traffic.incidents` 中出现 `incident_type=delivery_delay`

**执行流程**：
1. 检测用户是否有进行中的外卖订单
2. 评估等待 vs 替代方案：
   - **可等**（无时间约束）→ 通知延误 + 建议"先吃点零食垫垫"
   - **不可等**（如乐乐需 20:30 前吃完入睡）→ 推替代方案
3. 替代方案矩阵：
   - 同餐厅是否支持外带自取？→ 步行/驾车时间
   - 附近便利店/快餐（步行<10分钟）
   - 冰箱现有食材能做啥（从 MEMORY.md 读最近超市采购记录）
4. 联动 `mobility-butler`：如需外出自取，评估当前天气是否适合（雨天不建议带婴儿出门）

### 3.9 到店关门应急

**触发**：查询餐厅详情时发现 `status=歇业`

**执行流程**：
1. 即时切换同商圈同类型备选（调用 `POST /api/dining/recommend` 限定坐标+菜系）
2. 约束条件照旧（预算、过敏、设施）
3. 重新规划路线（联动 `mobility-butler`）
4. 通知同行者更换地点（联动 `life-organizer`）

### 3.10 餐厅详情 → `GET /api/dining/detail?restaurant_id=401`

返回完整餐厅信息（含动态排队 + 当前有效优惠）。

### 3.9 餐后评价 → `POST /api/dining/review`

入参：`restaurant_id`, `user_id`, `rating`, `comment`。评价后联动 `life-organizer` 更新口味记忆。

### 3.10 特殊日期 → `GET /api/dining/special-dates?user_id=white_collar`

返回即将到来的生日/纪念日，含推荐动作。

## 4. 突发兜底优先级

| 突发类型 | 优先方案 | 备选 |
|----------|----------|------|
| 突然下雨 | 同商场内餐厅 > 原餐厅外卖 > 附近 500m 内 | 叫车换商圈 |
| 带小孩遇雨 | 坚决不淋雨移动，只推同商场或外卖 | - |
| 餐厅满座 | 同商场内备选 > 原餐厅外带 > 附近 500m | 换商圈 |
| 用户迟到 | 原餐厅加速提醒 > 外卖 > 便利店/快餐 | - |

## 5. 卡片输出规范
- **推荐卡片**：餐厅名 + 菜系 + 评分 + 人均 + 距离 + 排队 + 折中亮点 + 设施图标 + 匹配理由
- **兜底卡片**：原方案 vs 新方案对比（距离/等待/口味），高亮"同商场步行可达"
- **外卖卡片**：配送时间 + 费用 + "免淋雨""同餐厅味道"

## 6. 协同 Skill
| Skill | 获取 | 提供 |
|-------|------|------|
| `life-organizer` | 口味偏好、健康标签、生日/纪念日、同伴档案 | 写入用餐记录、更新口味记忆 |
| `outfit-advisor` | 当前天气 (触发突发兜底) | - |
| `mobility-butler` | 出行耗时、实时路况 | 餐厅地址、期望到达时间 |

## 7. 约束
- 所有数据来自 mock_backend 动态模拟
- 严格过滤黑名单食材（如果果花生过敏 → 过滤含花生的菜系）
- 多人折中时推荐理由必须明确说明折中方案
- 健康标签有时效性（"上火"有效期 3 天）
- 支付/下单均为模拟，不执行真实交易
