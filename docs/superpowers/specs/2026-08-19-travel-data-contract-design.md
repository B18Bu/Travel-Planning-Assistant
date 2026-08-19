# v1 旅行数据合同设计

**日期：** 2026-08-19  
**状态：** 待书面规格审查  
**范围：** 仅定义 v1 旅行数据模型与模型测试，不实现外部服务、专业 Agent、编排器、旅行规划 API 或前端。

---

## 1. 背景与目标

v1 已完成 FastAPI 安全应用骨架，但尚无旅行领域模型。后续天气、路线、住宿、美食、汇总和 API 层需要共享一个可验证的结构化边界，防止自由字典、来源时间语义混淆和未授权字段进入结果链路。

本次设计在 `backend/app/models/travel.py` 中建立 Pydantic v2 强类型数据合同，并在 `backend/tests/test_models.py` 中通过测试验证合同意图。

### 1.1 成功标准

1. 用户请求在进入后续编排前完成字段、边界和日期校验。
2. 天气、路线、住宿、餐饮、来源和最终行程均有专属强类型模型。
3. 最终响应同时保留结构化 `itinerary` 和 Markdown 文档。
4. 价格、库存、可订状态、排队、优惠和未授权评分等字段无法通过模型校验。
5. `success`、`partial`、`degraded`、`failed` 的数据完整性规则可由模型验证。
6. 模型中不包含密钥、原始异常、内部 URL 或上游原始响应。

---

## 2. 范围与非目标

### 2.1 本次包含

- `TravelPlanRequest` 与派生住宿晚数；
- 来源、时间语义和数据状态模型；
- 天气、路线、住宿、餐饮和 POI 的领域结果模型；
- Agent 执行结果与最终文档模型；
- 受控错误摘要、缺失字段和请求追踪字段；
- 领域模型单元测试。

### 2.2 本次不包含

- `POST /api/travel-plans` 路由和响应组装；
- 和风天气、高德地图、知识库、缓存、重试、熔断或外部 HTTP 调用；
- 天气、路线、住宿、美食、汇总 Agent 与顺序编排器；
- Markdown 文档生成逻辑；
- 登录、用户、租户、审计数据库、持久化追踪和外部调用 Span；
- 前端或 Markdown 浏览器净化。

本次不修改已完成的 `backend/app/main.py`、`backend/app/config.py`、`backend/app/security.py` 及其健康检查测试。

---

## 3. 建模原则

1. **强类型优先：** 核心事实不使用 `dict[str, Any]`；每个领域都有显式模型。
2. **合同封闭：** 所有领域模型使用 `extra="forbid"`，拒绝未声明字段。
3. **事实与呈现分层：** `itinerary` 是机器可消费的事实结果；`markdown` 是后续汇总器根据该结果生成的阅读表现层。
4. **时间语义清晰：** 区分上游内容更新时间与本服务获取时间，禁止用单一模糊时间字段混淆两者。
5. **状态单一来源：** 只保留 `AgentStatus`，不再增加重复的 `degraded: bool`。
6. **降级显式：** 非成功状态必须说明缺失字段或受控错误，不能以自由文本掩盖缺失。
7. **禁止字段从 Schema 阻断：** 不为无授权实时或平台数据定义模型字段。

---

## 4. 共享基础模型

### 4.1 严格模型基类

定义内部 `StrictModel`，统一设置：

```python
model_config = ConfigDict(extra="forbid")
```

所有对外传递的领域模型继承该基类。这样，拼写错误、供应商原始字段和后续未经评审的字段不会静默通过验证。

### 4.2 枚举

```text
AgentStatus
- success
- partial
- degraded
- failed

DataStatus
- realtime
- cached
- knowledge_base
- degraded

SourceType
- weather_api
- map_api
- poi_api
- knowledge_base
```

`AgentStatus` 描述结果完整度；`DataStatus` 描述某条来源数据的取得方式；二者不得互相替代。

### 4.3 受控错误摘要

`ErrorDetail` 仅包括：

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | string | 机器可读错误代码，例如 `external_service_unavailable`。 |
| `message` | string | 可对用户展示的中文概述。 |
| `retryable` | boolean | 是否允许编排器按规则重试。 |

不包含异常对象、堆栈、请求参数、完整 URL、HTTP 响应体或供应商错误文本。

---

## 5. 用户请求与来源合同

### 5.1 `TravelPlanRequest`

| 字段 | 类型 | 规则 |
|---|---|---|
| `origin` | string | 去除首尾空白后长度为 1—100。 |
| `destination` | string | 去除首尾空白后长度为 1—100。 |
| `departure_date` | date | 不早于服务端当前日期。 |
| `travelers` | integer | 1—20。 |
| `days` | integer | 1—14，默认 3。 |
| `budget` | integer 或 null | 0—200000；只作为预算层级输入，不表示价格承诺。 |
| `preferences` | string array | 默认空数组，最多 12 项；每项去除首尾空白且不能为空。 |

`nights` 为只读派生属性，计算规则为 `max(days - 1, 0)`；不是客户端输入字段。

### 5.2 `Source`

| 字段 | 类型 | 规则 |
|---|---|---|
| `name` | string | 来源名称，长度 1—100。 |
| `type` | `SourceType` | 来源类别。 |
| `data_status` | `DataStatus` | 实时、缓存、知识库或降级。 |
| `source_updated_at` | datetime 或 null | 上游内容或数据声明的更新时间；实时、缓存数据必须提供。 |
| `retrieved_at` | datetime | 本服务获取或读取该数据的时间，必须提供。 |
| `url` | HTTPS URL 或 null | 外部来源可提供；仅允许 HTTPS。 |
| `knowledge_version` | string 或 null | 知识库来源必须提供；其他来源不得提供。 |

知识库来源必须满足 `data_status=knowledge_base` 且具有 `knowledge_version`；非知识库来源不得伪装为知识库版本。所有来源必须保留 `retrieved_at`。

---

## 6. 领域结果合同

### 6.1 POI 与地点

```text
NormalizedLocation
- name
- location（经纬度字符串，可为空）
- adcode（区域编码，可为空）

PoiCandidate
- name
- address（可为空）
- location（可为空）
- category
- tags（默认空数组）
- source_ids（至少一个来源索引或标识）
```

POI 只表达名称、位置、类别和受控标签；不含评分、价格、库存、可订状态、排队、优惠或订单链接。

### 6.2 天气

```text
WeatherRiskLevel: low / medium / high

DailyWeather
- date
- condition
- temp_min（可为空）
- temp_max（可为空）
- risk_level
- activity_suitability（可为空）
- equipment_suggestions（默认空数组）

WeatherPlanData
- destination
- daily
- constraints（默认空数组）
```

天气约束由后续天气 Agent 按确定性规则生成。本合同不把天气预测表达为安全承诺。

### 6.3 路线

```text
RouteEstimate
- distance_meters（非负整数）
- duration_minutes（非负整数）
- is_estimate（固定为 true）

DailyArea
- day（从 1 开始）
- area
- activity_window（可为空）

RoutePlanData
- origin
- destination
- round_trip（可为空）
- daily_areas
- weather_adjusted
```

`RouteEstimate` 仅为地图估算值，不能表示实时路况、最快路线或到达保证。

### 6.4 住宿

```text
LodgingCandidate
- poi
- facilities（默认空数组）
- suitable_for（默认空数组）
- commute_note（可为空）
- recommendation_reason（可为空）

LodgingPlanData
- nights
- recommended_area
- candidates（默认空数组）
- filter_suggestions（默认空数组）
```

住宿候选只表达区域、位置、设施和适配信息。模型不定义任何价格、库存或平台评分字段。

### 6.5 餐饮

```text
FoodCandidate
- poi
- cuisine（可为空）
- specialties（默认空数组）
- suitable_for（默认空数组）
- dietary_notes（默认空数组）
- business_hours_note（可为空）

DailyFoodPlan
- day（从 1 开始）
- area
- meal_period（可为空）
- candidates（默认空数组）
- filter_suggestions（默认空数组）

FoodPlanData
- daily_food
```

餐饮模型不定义排队、实时优惠、未授权评分或实时营业保证字段。`business_hours_note` 仅在后续来源证实时使用。

---

## 7. Agent 执行结果与最终文档

### 7.1 强类型 Agent 结果

定义泛型 `AgentResult[T]`：

| 字段 | 类型 | 规则 |
|---|---|---|
| `agent` | string | 固定专业 Agent 名称。 |
| `status` | `AgentStatus` | 唯一状态来源。 |
| `summary` | string | 已证实结果的简短摘要，长度受限。 |
| `data` | `T` 或 null | `success`、`partial`、`degraded` 可含数据；`failed` 必须为 null。 |
| `constraints` | string array | 下游必须遵守的确定性约束。 |
| `sources` | `Source` array | 用于形成该结果的来源。 |
| `warnings` | string array | 面向用户的风险与核验提示。 |
| `missing_fields` | string array | 非 `success` 状态必须提供至少一项，说明缺失结果。 |
| `error` | `ErrorDetail` 或 null | `failed` 必须提供；`success` 不得提供。 |
| `request_id` | UUID 字符串 | 本次用户请求的标识。 |
| `trace_id` | UUID 字符串 | v1 暂与 `request_id` 值相同，保留未来兼容性。 |

状态校验规则：

- `success`：必须有 `data`，不得包含 `missing_fields` 或 `error`。
- `partial`：必须有 `data`，且必须有 `missing_fields`。
- `degraded`：必须有 `data`，且必须有 `missing_fields` 或 `error`。
- `failed`：`data` 必须为 null，必须有 `missing_fields` 与 `error`。

### 7.2 `TravelPlanData`

最终结构化行程由四个专业结果组成：

```text
TravelPlanData
- weather: AgentResult[WeatherPlanData]
- route: AgentResult[RoutePlanData]
- lodging: AgentResult[LodgingPlanData]
- food: AgentResult[FoodPlanData]
```

该模型保存每个 Agent 的状态和领域数据，供后续 API、模板渲染、测试和导出消费。它不重新解析 Markdown。

### 7.3 `TravelPlanDocument`

```text
TravelPlanDocument
- request_id
- trace_id
- status
- itinerary: TravelPlanData
- markdown
- sources
- warnings
- degraded_agents
```

- `itinerary` 是唯一的结构化事实载体。
- `markdown` 仅是由后续汇总器根据 `itinerary` 生成的阅读表现层。
- `sources` 为四个专业结果来源的去重集合。
- `warnings` 为四个专业结果警告的聚合结果。
- `degraded_agents` 只包括状态为 `degraded` 的 Agent 名称。
- 整体状态由后续汇总器决定；本合同只限制其为 `success`、`degraded` 或 `failed`。

---

## 8. 禁止字段与安全边界

所有领域模型使用 `extra="forbid"`，因此以下字段或同义字段均不在合同中，传入时应触发验证错误：

```text
price
live_price
inventory
availability
bookable
queue
queue_time
discount
rating
review_score
order_url
```

合同本身也不包含：

- API Key、Token、Cookie、Authorization；
- 原始异常、堆栈、供应商原始响应；
- 服务端内部 URL、文件路径、数据库连接信息；
- 用户、租户、支付、预订和营销字段。

---

## 9. 测试设计

新增 `backend/tests/test_models.py`，遵循测试先行：先编写失败测试，确认因模块缺失失败，再实现最小合同。

| 测试类别 | 验证意图 |
|---|---|
| 请求默认与边界 | 保证默认 3 天 2 晚，并阻止空地点、过去日期、越界人数、越界天数、无效偏好和未知请求字段进入后续链路。 |
| 来源时间语义 | 保证来源总有读取时间；实时与缓存来源有上游更新时间；知识库来源有版本。 |
| 领域模型 | 保证天气、路线、住宿、餐饮和 POI 能按预期序列化，并限制必要的数值与日序边界。 |
| 禁止字段 | 保证价格、库存、可订、排队、优惠与评分等字段被拒绝，而不是静默保留。 |
| Agent 状态 | 保证 `success`、`partial`、`degraded`、`failed` 的 data、缺失字段和错误摘要保持一致。 |
| 最终文档 | 保证文档保留 `itinerary` 与 Markdown，且降级 Agent 列表只包含降级状态。 |
| 安全字段 | 保证未知字段、密钥字段和原始异常类字段不能进入模型序列化结果。 |

本轮不测试外部 API 映射、天气规则、路线算法、Markdown 渲染或 Agent 执行顺序；这些归属后续任务。

---

## 10. 实现影响

本规格将创建以下文件：

- `backend/app/models/__init__.py`
- `backend/app/models/travel.py`
- `backend/tests/test_models.py`

不会修改其他已存在的后端骨架文件。后续服务、Agent、编排器和 API 都必须以本规格定义的模型为输入输出合同。

---

## 11. 规格自检

- **占位符：** 未包含 TODO、待定或“后续补充”式实现占位符。
- **状态一致性：** 单一 `AgentStatus` 表达执行状态；每种状态具有明确的 data、缺失字段和错误规则。
- **时间一致性：** 明确区分 `source_updated_at` 与 `retrieved_at`，知识库版本有独立字段。
- **范围一致性：** 仅涉及数据合同和模型测试；未包含外部调用、Agent、API 路由或前端。
- **安全一致性：** 合同默认拒绝未知字段，且不定义无授权实时、密钥或内部异常字段。
