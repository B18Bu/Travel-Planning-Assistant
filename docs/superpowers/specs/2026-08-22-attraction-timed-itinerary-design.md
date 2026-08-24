# 景区级时段行程与天气驱动规划设计

**日期：** 2026-08-22  
**状态：** 已确认，待编写实现计划  
**范围：** 将当前“每日活动区域”升级为景区级的上午、下午、傍晚行程；根据天气输出出游提醒并切换景区检索策略；为午餐和晚餐提供景区周边的具体餐馆名称与地址。

---

## 1. 目标与非目标

### 1.1 目标

用户提交旅行请求后，系统按每一天生成最多 3 个不重复的主景区时段安排：上午、下午、傍晚。每个景区段包含高德返回的名称、地址、坐标、类别、建议游玩时长，以及前往下一景区的高德驾车预估。

天气不再仅展示预报文字。天气 Agent 必须为每个有预报的日期生成可执行的出游提醒；路线 Agent 必须消费高风险天气约束：暴雨、台风、强对流和高温日改为优先搜索博物馆、美术馆、展馆等室内文化场所，避免机械使用常规景区安排。

餐饮 Agent 必须将午餐与晚餐关联到当日景区坐标，使用高德附近 POI 搜索输出具体餐馆名称、地址、坐标和类别。

### 1.2 非目标

本次不实现：

- DeepSeek 或任何 LLM 决定景区顺序、时段或调用外部工具；
- 根据模型推测展示景区开放时间、预约条件、价格、评分、推荐指数、招牌菜、库存或可订状态；
- 公共交通、步行、骑行路线与实时路况承诺；
- 景区预订、餐厅预订、支付、票务或交易能力；
- 动态用户偏好学习、长期记忆、知识库/RAG。

当前授权的高德 v5 文本 POI 响应未提供评分、推荐指数或招牌菜字段，因此这些字段不得加入数据合同、Markdown 或页面。

---

## 2. 关键产品规则

### 2.1 每日景区节奏

每一天最多包含以下 3 个主景区段：

| 时段 | 默认建议游玩时长 | 排程规则 |
| --- | ---: | --- |
| 上午 | 120 分钟 | 当天第 1 个已筛选景区 |
| 下午 | 120 分钟 | 当天第 2 个已筛选景区 |
| 傍晚 | 120 分钟 | 当天第 3 个已筛选景区 |

`120` 分钟是服务端提供的行程建议，不代表景区开放时长、实际停留承诺或供应商事实。

多日行程从候选景区中按返回顺序分配，优先不重复。同一候选景区在同一次旅行规划中最多出现一次。候选不足时保留已有候选，空时段通过 `missing_fields` 和页面文案显式说明，不复用景区填充。

### 2.2 天气驱动规则

| 天气条件 | 当日出游提醒 | 景区检索关键词 |
| --- | --- | --- |
| 暴雨、台风、强对流 | 减少户外暴露，关注官方预警 | 博物馆、美术馆、展馆 |
| 高温 | 防晒补水，避免长时间户外暴晒 | 博物馆、美术馆、展馆 |
| 无上述高风险 | 关注常规天气变化 | 风景名胜 |
| 当日无可用预报 | 天气待核验 | 风景名胜 |

“室内文化场所”由高德检索关键词限定，而非由模型推断 POI 属性。所有候选的开放时间、预约条件、入馆要求仍必须提示用户以官方信息为准。

### 2.3 餐饮规则

每日安排 2 个就餐段：

| 就餐段 | 关联景区 | 查询方法 |
| --- | --- | --- |
| 午餐 | 上午景区 | 使用上午景区坐标查询半径 2000 米内的餐饮服务 POI |
| 晚餐 | 优先傍晚景区；傍晚缺失时使用下午景区 | 使用关联景区坐标查询半径 2000 米内的餐饮服务 POI |

每个就餐段保留高德返回的首个有效餐饮候选，并输出名称、地址、坐标、类别和来源元数据。高德未返回评分、推荐指数和招牌菜时，系统不展示这些内容，统一提示“营业时间、菜品与服务安排请以商家官方信息为准”。

---

## 3. 数据合同

### 3.1 新增模型

在 `backend/app/models/travel.py` 增加：

```python
class TimedAttraction(StrictModel):
    time_slot: Literal["上午", "下午", "傍晚"]
    poi: PoiCandidate
    suggested_duration_minutes: int = Field(ge=1)
    activity_note: str | None = None
    travel_to_next: RouteEstimate | None = None


class DailyItinerary(StrictModel):
    day: int = Field(ge=1)
    weather_reminder: NonEmptyText
    attractions: tuple[TimedAttraction, ...] = Field(max_length=3)
    missing_fields: tuple[NonEmptyText, ...] = ()
```

`RoutePlanData` 扩展：

```python
class RoutePlanData(StrictModel):
    origin: NonEmptyText
    destination: NonEmptyText
    round_trip: RouteEstimate | None = None
    daily_areas: tuple[DailyArea, ...] = Field(min_length=1)
    daily_itineraries: tuple[DailyItinerary, ...] = Field(min_length=1)
    weather_adjusted: bool
```

保留 `daily_areas`，让现有 `LodgingAgent` 保持按每日首个景区区域/目的地回退值运行，避免一次升级破坏住宿模块调用边界。

### 3.2 WeatherPlanData 扩展

天气提醒以天气 Agent 现有 `DailyWeather` 和 `constraints` 为基础生成。为了使路线无需解析自由文本，在 `WeatherPlanData` 新增每日期受控提醒：

```python
class DailyWeather(StrictModel):
    date: date
    condition: NonEmptyText
    temp_min: int | None = None
    temp_max: int | None = None
    risk_level: WeatherRiskLevel
    activity_suitability: str | None = None
    equipment_suggestions: tuple[NonEmptyText, ...] = ()
    travel_reminder: NonEmptyText
    indoor_preferred: bool
```

- `travel_reminder` 是面向当日行程的确定性提示；
- `indoor_preferred` 只有暴雨、台风、强对流或高温时为 `True`；
- `activity_suitability`、`equipment_suggestions` 保留现有兼容位置，但 v1 时段规划只依赖 `travel_reminder` 与 `indoor_preferred`。

### 3.3 FoodPlanData 扩展

当前 `DailyFoodPlan` 只按“天 + 区域”组织。为保留午餐/晚餐关联，改为每天可以存在两个条目，`meal_period` 固定为 `午餐` 或 `晚餐`：

```python
class DailyFoodPlan(StrictModel):
    day: int = Field(ge=1)
    area: NonEmptyText
    meal_period: Literal["午餐", "晚餐"] | None = None
    nearby_attraction_name: NonEmptyText | None = None
    candidates: tuple[FoodCandidate, ...] = ()
    filter_suggestions: tuple[NonEmptyText, ...] = ()
```

当 Route Agent 未提供 `daily_itineraries`、当日景区坐标缺失或附近查询无结果时，Food Agent 保持受控降级，保留区域与核验提示，不伪造餐厅。

---

## 4. 服务层扩展

### 4.1 高德附近 POI 搜索

在 `AmapClient` 增加：

```python
async def search_nearby_poi(
    self,
    keywords: str,
    location: str,
    radius_meters: int,
) -> list[dict[str, Any]]
```

请求固定为：

```text
GET https://restapi.amap.com/v5/place/around
location=<已获取景区坐标>
keywords=<餐饮服务>
radius=2000
key=<AMAP_API_KEY>
```

约束：

- `location` 必须是已获取景区 POI 的有效坐标；
- `radius_meters` 必须是后端控制的正整数，Food Agent 固定传 `2000`；
- 只保留当前 POI 客户端白名单字段；
- 缓存 key 必须包含操作名、坐标、关键词、半径与 API key 指纹；
- 附近 POI 的 TTL 复用现有 `amap_poi_cache_ttl_seconds`；
- 非 2xx、无效 `status`、无效 POI 结构沿用现有受控错误、重试与熔断语义。

### 4.2 景区 POI 查询与路线调用

Route Agent 使用已有 `search_poi(keywords, city)`：

- 常规日：`keywords="风景名胜"`；
- 高风险日：依次查询 `"博物馆"`、`"美术馆"`、`"展馆"`，按查询顺序收集候选；
- 候选按 POI 名称 + 坐标去重；
- 每个景区只安排一次；
- 对每个相邻景区对调用 `driving_route(previous.location, next.location)`；
- 驾车估算只用于 `travel_to_next`，不得作为实时路况或到达保证。

---

## 5. Agent 流程

```text
TravelPlanRequest
  │
  ├─ WeatherAgent
  │    └─ 每日预报 → risk_level / travel_reminder / indoor_preferred
  │
  ├─ RouteAgent
  │    ├─ 起终点地理编码 + 往返驾车估算
  │    ├─ 每日读取天气规则
  │    ├─ 查询室内文化场所或风景名胜
  │    ├─ 候选去重并分配上午 / 下午 / 傍晚
  │    └─ 查询相邻景区驾车预估
  │
  ├─ LodgingAgent
  │    └─ 继续使用 daily_areas
  │
  ├─ FoodAgent
  │    ├─ 上午景区坐标 → 附近餐饮 → 午餐
  │    └─ 傍晚/下午景区坐标 → 附近餐饮 → 晚餐
  │
  └─ SummaryAgent
       └─ 输出每日天气提醒、景区时段、游玩建议时长、通勤预估、午晚餐名称与地址
```

---

## 6. Markdown 展示规则

每个日期的 Markdown 结构：

```markdown
## 第 1 天 · <目的地>

### 今日出游提醒
- <weather_reminder>

### 上午 · <景区名称>
- 建议游玩约 120 分钟。
- 地址：<高德地址或地址待核验>。
- 前往下一景区：驾车约 <duration_minutes> 分钟，约 <distance_meters> 米。

### 午餐 · <上午景区附近>
- 候选：<高德餐馆名称>（<高德地址或地址待核验>）。
- 营业时间、菜品与服务安排请以商家官方信息为准。

### 下午 · <景区名称>
...

### 傍晚 · <景区名称>
...

### 晚餐 · <傍晚或下午景区附近>
- 候选：<高德餐馆名称>（<高德地址或地址待核验>）。
```

当天高风险时，景区 `activity_note` 必须说明“已优先安排室内文化场所，开放时间与预约条件待核验”。

景区、通勤或餐饮缺失时，展示可用信息与明确核验提示，不补全不存在的项目。

---

## 7. 降级策略

| 场景 | 预期结果 |
| --- | --- |
| 当日无天气预报 | 使用常规景区关键词，`weather_reminder` 表示天气待核验。 |
| 高风险日室内候选不足 | 只输出已找到的室内候选，空段记录 `missing_fields`，不使用室外景区填充。 |
| 景区总数不足 | 优先不重复，不补重复景区；文档标示缺失时段。 |
| 景区坐标缺失 | 可展示景区名称/地址，但不调用相邻驾车或附近餐饮；记录缺失字段。 |
| 景区间驾车失败 | 保留景区顺序，`travel_to_next=None`，提示使用地图应用核验。 |
| 午餐或晚餐附近 POI 为空 | 对应就餐段无候选，保留商家官方信息核验提示。 |
| POI 混入非目标类别 | 使用现有类别组过滤规则，只保留包含目标分类组的 POI。 |
| 外部服务熔断/密钥缺失 | 沿用现有缓存、重试、熔断和 Agent 降级合同，继续生成其余可用结果。 |

---

## 8. 测试策略

### 8.1 模型与合同测试

- 时段只能是上午、下午、傍晚；
- 景区建议游玩时长必须为正整数；
- `DailyItinerary` 最多 3 个景区；
- `RoutePlanData` 必须含 `daily_areas` 与 `daily_itineraries`；
- `DailyWeather` 必须含 `travel_reminder` 与 `indoor_preferred`；
- 餐饮不含评分、推荐指数、招牌菜等未授权字段。

### 8.2 高德客户端测试

- 附近 POI 请求使用固定 `/v5/place/around` 路径；
- 参数包含 `location`、`keywords`、`radius=2000` 和 API key；
- 缓存、重试、熔断和错误映射与现有文本 POI 一致；
- 无效坐标、无效半径、非 POI 结构受控拒绝；
- 只投影白名单字段。

### 8.3 天气与路线 Agent 测试

- 常规天气查询 `风景名胜`；
- 暴雨、台风、强对流、高温查询室内文化关键词，不查询常规景区；
- 每天的提醒、室内标记与天气风险一致；
- 多日景区候选优先不重复；
- 每日按上午、下午、傍晚输出；
- 相邻景区驾车请求使用前后两个 POI 坐标；
- 驾车失败时不伪造时长。

### 8.4 Food Agent 测试

- 午餐查询使用上午景区坐标；
- 晚餐查询优先使用傍晚景区、否则下午景区坐标；
- 固定半径为 2000 米；
- 展示上游真实餐馆名称和地址；
- 非餐饮 POI 被过滤；
- 附近无候选时输出受控缺失字段和筛选提示；
- 评分、推荐指数、招牌菜不得出现在模型与 Markdown。

### 8.5 汇总与 API 回归

- Markdown 按天展示出游提醒、时段景区、通勤预估、午餐和晚餐；
- 高风险日出现室内优先与官方核验提示；
- `sources`、`warnings`、`degraded_agents` 保持既有合同；
- 现有 API、缓存、熔断、Markdown 安全和前端测试保持通过；
- 使用真实高德 / 和风 API，在天气预报窗口内执行端到端冒烟验证。

---

## 9. 实施边界与后续

本设计坚持确定性规则优先：路线骨架、时段、天气切换、景区筛选、通勤预估和餐饮关联均由后端代码决定。后续 DeepSeek 集成只能接收该结构化事实骨架并改写为自然文案，必须有确定性回退，不得自行新增景区、餐厅、评分、菜品、开放时间或路线事实。
