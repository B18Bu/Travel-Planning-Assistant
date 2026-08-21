# v1 旅行规划全链路设计

**日期：** 2026-08-21
**状态：** 待书面规格审查
**范围：** 在已合并的强类型旅行数据合同基础上，实现受控外部数据访问、固定顺序 Agent 编排、旅行规划 API、同源前端表单与安全 Markdown 页面展示。

---

## 1. 目标与边界

### 1.1 目标

用户填写出发地、目的地、出行日期和人数后，系统生成可读的旅行规划页面。规划按天气、路线、住宿、餐饮的固定顺序生成，结果保留可验证的结构化 `itinerary`，同时生成面向用户的 Markdown 文档。

系统使用以下受控事实来源：

- 和风天气逐日预报 API；
- 高德地图地理编码、驾车路线和 POI 文本搜索 API；
- 首版不接入知识库、数据库、向量库或示例商家数据。

### 1.2 非目标

首版不实现：

- OTA、点评、票务或其他未经授权平台的数据抓取；
- 实时房价、库存、可订状态、排队时长、优惠、平台评分、订单链接；
- 支付、预订、退改、营销或任何外部写操作；
- 用户、租户、数据库持久化、审计数据库或分布式追踪；
- 动态 Agent 路由、并行编排或模型直接访问外部服务；
- 审核知识库及其检索接口。

### 1.3 成功标准

1. 配置有效密钥时，可由真实天气、高德路线与 POI 生成带来源的旅行规划页面。
2. 密钥缺失、上游失败、超时、熔断或 POI 无结果时，系统仍返回结构正确、明确降级的结果，不伪造事实。
3. 所有 Agent 输入输出遵循 `backend/app/models/travel.py` 的冻结合同。
4. 前端以页面形式展示行程，不向用户展示 JSON 源码、密钥、原始异常或供应商原始响应。
5. Markdown 经过本地 DOMPurify 净化；来源、警告和降级说明以 DOM 文本节点渲染。
6. 现有合同测试和新增服务、Agent、编排、API、前端安全测试均通过。

---

## 2. 总体架构

```text
浏览器（同源静态页面）
  │ POST /api/travel-plans
  ▼
FastAPI 应用
  ├─ 安全中间件：请求 ID、响应头、受控 CORS
  ├─ API 路由：合同校验、依赖注入
  ├─ 顺序编排器
  │   ├─ 天气 Agent（和风天气 + 高德地理编码）
  │   ├─ 路线 Agent（高德地理编码 + 路线）
  │   ├─ 住宿 Agent（高德住宿 POI）
  │   ├─ 餐饮 Agent（高德餐饮 POI）
  │   └─ 汇总器（结构化结果 → Markdown 文档）
  └─ 静态资源：HTML、CSS、JS、固定本地依赖

外部服务层
  ├─ 进程内 TTL 缓存
  ├─ 受限重试
  ├─ 服务级短时熔断
  ├─ 和风天气 API
  └─ 高德地图 API
```

浏览器只请求同源 API。所有密钥、上游地址、重试、缓存和熔断逻辑仅存在于后端。专业 Agent 只通过服务层获取受控结构化事实，不能直接处理密钥、URL、原始 HTTP 响应或写操作。

---

## 3. 后端数据流与状态

### 3.1 请求与追踪

1. `SecurityHeadersMiddleware` 从 `X-Request-Id` 接收 UUID v1—v5；缺失、无效或其他 UUID 版本时生成 UUID v4。
2. `POST /api/travel-plans` 将请求体校验为 `TravelPlanRequest`。
3. 路由读取 `request.state.request_id`，以同一值传入 `request_id` 和 `trace_id`。
4. 所有 Agent 结果及最终 `TravelPlanDocument` 使用该标识。

### 3.2 固定顺序编排

编排器严格按以下顺序调用，并将前序结果的受控数据传递给后续步骤：

1. 天气 Agent：目的地 → 逐日天气、风险、活动约束；
2. 路线 Agent：完整请求 + 天气约束 → 路线估算、每日活动区域；
3. 住宿 Agent：请求 + 每日活动区域 → 住宿区域与高德住宿 POI 候选；
4. 餐饮 Agent：请求 + 每日活动区域 → 每日餐饮区域与高德餐饮 POI 候选；
5. 汇总器：四个强类型结果 → `TravelPlanData` 与 `TravelPlanDocument`。

天气 Agent 的 `constraints` 是路线 Agent 的唯一天气输入。路线的 `daily_areas` 是住宿和餐饮 Agent 的空间锚点。汇总器不访问外部服务，也不新增前序结果以外的事实。

### 3.3 状态与降级

每个 Agent 返回现有 `AgentResult[T]`。状态及最低行为如下：

| 场景 | 状态 | 数据与说明 |
|---|---|---|
| 完整外部数据可用 | `success` | 返回对应的强类型领域数据与来源。 |
| 可用数据不完整 | `partial` | 返回可用数据并列出 `missing_fields`。 |
| 密钥缺失、超时、熔断、上游失败或 POI 无结果 | `degraded` | 返回最小领域数据、`missing_fields` 或受控错误、警告和核验提示。 |
| 无法构造最低合同数据 | `failed` | `data` 为 null，提供受控错误与缺失字段。 |

降级结果不得伪造天气预报、精确路线、通行时长、POI 名称或任何交易字段。顶层文档的 `sources`、`warnings`、`degraded_agents` 由既有合同重新计算并校验，不信任调用方手工填写的汇总值。

---

## 4. 外部服务与韧性

### 4.1 高德地图客户端

`AmapClient` 仅公开：

- `geocode(keyword)`：标准化地点，输出名称、坐标与区域编码；
- `driving_route(origin, destination)`：输出非实时估算距离与时长；
- `search_poi(category, city_or_area)`：输出 POI 名称、地址、坐标与分类。

客户端使用固定 HTTPS 高德域名与固定 API 路径。客户端不接受前端传入 URL，不保留原始响应，不将供应商错误文本传到 Agent 或 API。

缓存策略：地理编码 7 天、路线 15 分钟、POI 1 小时。

### 4.2 和风天气客户端

`HeWeatherClient` 仅请求固定的逐日预报端点。天气缓存键由目的地标识、出行日期和天数组成，TTL 为 30 分钟。供应商数据只映射为日期、天气状况、温度上下限和来源更新时间，不保留原始响应。

### 4.3 缓存、重试与熔断

- `MemoryCache`：进程内 TTL 缓存。缓存命中的来源必须标记为 `cached`；保留上游 `source_updated_at` 并为本次读取记录 `retrieved_at`。
- 重试：仅连接/读取超时、传输错误、HTTP `429` 和 `5xx` 重试。总计最多 3 次请求（首次加 2 次重试），使用确定性指数退避。
- 熔断：按服务独立计数。达到连续失败阈值后打开 60 秒；打开期间禁止发起请求，直接由 Agent 返回降级结果。
- 服务层只返回受控映射数据或抛出 `ExternalServiceUnavailable`。该异常不包含密钥、URL、参数、堆栈或上游响应。

### 4.4 配置与环境变量

`backend/app/config.py` 与 `backend/.env.example` 中每个配置项均使用中文注释，说明：用途、对应的外部 API、单位、默认值和安全边界。

必须覆盖：

- `HEWEATHER_API_KEY`：和风天气逐日预报 API 的服务端密钥；
- `AMAP_API_KEY`：高德地理编码、驾车路线和 POI 文本搜索 API 的服务端密钥；
- 固定基础 URL、连接/读取/总超时；
- 缓存 TTL、重试次数、熔断阈值与熔断时长。

密钥只能来自后端环境变量。不得写入前端资源、响应、Markdown、日志或测试快照。`/api/ready` 在任一必需密钥未配置时返回泛化的 `503`，不回显变量名或配置值；`/api/health` 不依赖外部服务。

---

## 5. 专业 Agent

### 5.1 天气 Agent

天气 Agent 先调用高德地理编码，再调用和风逐日预报。它按明确的词表将暴雨、台风、强对流和高温映射为 `WeatherRiskLevel`、用户警告及确定性活动约束。例如，暴雨或台风生成「避免长时间户外活动」约束。

密钥缺失或服务失败时，Agent 返回 `degraded` 的最小 `WeatherPlanData`，不构造虚假逐日预报，并提示用户出行前复核官方天气与预警。

### 5.2 路线 Agent

路线 Agent 使用高德标准化出发地和目的地，并获取驾车路线估算。它为每个出行日建立 `DailyArea`。天气约束不为空时，`weather_adjusted` 必须为 true。

路线服务不可用时，Agent 返回目的地区域化日程建议，不输出距离、精确时长、拥堵结论或「最快」承诺。

### 5.3 住宿 Agent

住宿 Agent 使用高德「住宿服务」POI 搜索。每个 POI 只映射为 `PoiCandidate` 和 `LodgingCandidate` 中允许的字段：名称、地址、位置、分类、来源标识、推荐区域和通勤说明。

POI 无结果、密钥缺失或调用失败时，返回 `degraded` 的 `LodgingPlanData`：推荐区域、筛选条件和通过官方或授权渠道核验的警告；不得编造住宿商家。

### 5.4 餐饮 Agent

餐饮 Agent 按路线的每日区域搜索高德「餐饮服务」POI，并为每一天构造 `DailyFoodPlan`。候选只包含合同允许的 POI、菜系和说明字段。

POI 无结果、密钥缺失或调用失败时，返回 `degraded` 的 `FoodPlanData`：每日餐饮区域、筛选条件与营业信息核验提示；不得编造餐厅或排队、优惠、评分等字段。

---

## 6. 汇总与 API

### 6.1 汇总器

汇总器是确定性组件，不调用模型或外部服务。它只读取四个 `AgentResult`，构造 `TravelPlanData`，并按现有合同规则得到最终文档：

- `sources`：按 weather、route、lodging、food 顺序，以 `name`、`type`、`data_status`、`source_updated_at`、`url`、`knowledge_version` 去重；忽略 `retrieved_at`，保留首次完整来源；
- `warnings`：按 weather、route、lodging、food 顺序拼接；
- `degraded_agents`：只包含 `degraded` 结果；
- Markdown：只根据结构化行程、来源、警告和降级状态生成。

Markdown 固定包含：行程概览、天气与出游风险、每日路线、住宿建议、餐饮建议、待核验事项、来源与更新时间、降级说明。模板不能输出价格、库存、可订状态、评分、队列、优惠、密钥、原始异常或内部 URL。

### 6.2 API

`POST /api/travel-plans` 的请求模型是 `TravelPlanRequest`，响应模型是 `TravelPlanDocument`。应用工厂支持注入替身编排器，供 API 测试隔离外部服务。

应用启动时通过依赖组装创建生产编排器。静态资源由同一 FastAPI 应用提供；前端调用相对路径 `/api/travel-plans`，无需放宽 CORS。

---

## 7. 同源前端与安全展示

### 7.1 静态资源

前端文件由 FastAPI 同源托管：

- `frontend/index.html`：旅行输入表单与结果容器；
- `frontend/app.js`：表单校验、API 请求、状态渲染与安全 DOM 操作；
- `frontend/styles.css`：双栏布局与响应式样式；
- `frontend/vendor/marked.min.js`：本地固定版本的 Markdown 解析器；
- `frontend/vendor/purify.min.js`：本地固定版本的 DOMPurify。

第三方文件必须来自可复核的正式发行包，并在 `frontend/vendor/THIRD_PARTY_NOTICES.md` 记录包名、版本、许可证和 SHA-256。前端不得请求 CDN 或其他第三方主机。

### 7.2 页面交互

表单必须校验四项必填字段：出发地、目的地、出行日期、人数。可选字段为天数、预算和偏好。页面展示提交中、成功、失败与降级状态。

成功结果采用双栏：

- 桌面端主栏：`document.markdown` 经过 `marked` 解析与 DOMPurify 净化后展示；
- 桌面端侧栏：待核验事项、来源与更新时间、降级说明；
- 窄屏：两栏折叠为单栏，侧栏位于主行程之后。

`itinerary` 仅用于 API 和后端消费，页面不得把它或整个响应对象序列化为 JSON 源码展示。

### 7.3 XSS 防护

- Markdown 必须先由本地 `marked` 解析，再由 DOMPurify 净化；
- 净化禁止 `script`、`style`、`svg`、`math` 标签及事件属性；
- `sources`、`warnings`、`degraded_agents` 和 API 错误信息用 `document.createElement`、`textContent` 与 `replaceChildren` 渲染，禁止插入未净化 HTML；
- 页面不读取、不显示或不传递 API 密钥。

---

## 8. 测试与验收

### 8.1 后端测试

| 层级 | 验证内容 |
|---|---|
| 服务层 | 固定端点、响应映射、缓存命中、密钥缺失、超时、传输错误、429、5xx、重试与熔断。 |
| Agent | 天气约束传递、允许字段映射、POI 无结果、上游失败、禁止交易字段与显式降级。 |
| 编排器 | weather → route → lodging → food 固定顺序、上下游数据传递、单 Agent 降级不阻断后续、请求标识一致。 |
| 汇总器 | 不新增事实、Markdown 内容、来源/警告/降级项与冻结合同一致。 |
| API | 必填字段、默认天数、成功/降级响应、请求 ID、安全响应头、就绪检查与替身注入。 |

### 8.2 前端验收

- 同源页面能提交表单并展示页面化行程；
- 结果区不显示 JSON 源码；
- 恶意 Markdown（脚本、事件属性、SVG 等）净化后不执行；
- 来源、警告和降级信息以纯文本 DOM 节点展示；
- 双栏在窄屏下变为单栏；
- 静态资源不含 CDN URL 或 API 密钥。

---

## 9. 规格自检

- **占位符：** 不包含 TODO、待定或「后续补充」形式的实现描述。
- **范围：** 只包含 v1 受控旅行规划链路；不包含知识库、交易数据、外部写操作或动态 Agent 路由。
- **合同一致性：** 所有运行时数据遵循已合并的冻结旅行合同；来源、警告与降级项由最终文档合同校验。
- **降级一致性：** 外部数据失败时不伪造事实，所有降级路径都通过状态、缺失字段、警告和来源语义说明。
- **安全一致性：** 前端同源、依赖本地固定、Markdown 净化、元数据纯文本渲染，密钥只在后端环境变量中存在。
