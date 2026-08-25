# 智能文旅策划助手

面向企业内部旅行规划场景的只读式行程建议服务。系统将天气、地图路线、住宿区域、餐饮 POI 汇聚为可追溯的结构化结果，并在同源前端渲染为包含时段、提醒和午晚餐建议的可核验 Markdown 行程。

> 当前版本是 MVP：只提供建议与核验提示，不执行预订、支付或任何交易。

## 目录

- [项目背景与目标](#项目背景与目标)
- [范围与非目标](#范围与非目标)
- [用户流程与总体架构](#用户流程与总体架构)
- [模块职责与数据流](#模块职责与数据流)
- [企业 API 来源](#企业-api-来源)
- [数据合同与安全边界](#数据合同与安全边界)
- [酒店查询与推荐](#酒店查询与推荐)
- [配置](#配置)
- [本地启动](#本地启动)
- [API 使用](#api-使用)
- [前端安全与页面](#前端安全与页面)
- [缓存、重试与熔断](#缓存重试与熔断)
- [测试与质量门禁](#测试与质量门禁)
- [常见故障排查](#常见故障排查)
- [部署与打包](#部署与打包)
- [生产化后续](#生产化后续)

## 项目背景与目标

旅行规划需要同时处理日期、活动区域、天气风险、路线估算和餐饮住宿候选。若各模块直接传递自由字典，容易出现字段漂移、来源时间混淆、上游原始错误泄露和降级状态不一致。

本项目的目标是：

1. 以强类型数据合同连接天气、路线、住宿、餐饮、汇总和 API。
2. 通过 `request_id` 和 `trace_id` 贯穿一次请求，便于日志关联和问题定位。
3. 清晰区分实时数据、进程内缓存数据和降级结果，要求用户对关键事实进行复核。
4. 以同源、双栏页面展示行程正文与待核验事项，不把供应商原始响应直接暴露给浏览器。
5. 以服务端密钥、固定供应商域名、受控超时、重试和熔断建立最小安全边界。

## 范围与非目标

### 本轮包含

- FastAPI 服务和同源静态前端。
- `TravelPlanRequest`、来源、专业 Agent 结果和 `TravelPlanDocument` 数据合同。
- 天气、驾车路线、住宿区域、餐饮 POI 的只读建议。
- 天气 Agent、路线 Agent、住宿 Agent、餐饮 Agent、汇总 Agent 和顺序编排器。
- 和风天气与高德地图的受控 HTTP 客户端，以及进程内缓存、瞬时错误重试和熔断。
- `/api/health`、`/api/ready`、`/api/travel-plans` 和默认关闭的 `/api/fliggy/tickets/search`。
- 工作台保留“门票查询”入口；通过 `FLIGGY_TICKET_PROVIDER=disabled|mock|flyai` 选择服务，默认 `disabled`（不请求飞猪、不显示模拟价格或库存）。`mock` 返回明确标注的本地演示数据；`flyai` 通过飞猪 AI 开放平台（FlyAI）`ai-search` 只读文本检索返回门票摘要（`data_status=flyai_text`），价格/库存固定显示“信息暂不可用”，不从自然语言猜测实时交易字段。三种 provider 都不创建订单、不处理支付。
- 酒店只读查询与推荐：默认关闭的飞猪 TOP 酒店低价查询，以及 FlyAI 酒店 + 高德住宿 POI 的并列推荐；两者都只读展示，不创建订单、不处理支付。

### 非目标与明确不接入

本轮不接入知识库、OTA（在线旅行代理平台）、酒店或餐厅交易、预订、支付、库存、优惠、排队和订单链接。门票查询当前仅为默认关闭的筹备入口；后续仅在飞猪书面授权、字段展示许可和安全验收完成后开放只读商品、指定日期价格/库存与入园规则查询，仍不创建订单、不处理支付、不收集游客身份信息。酒店查询同样保持只读边界：飞猪 TOP 低价接口与 FlyAI 酒店搜索只返回展示字段和官方详情跳转，不在本系统内下单或支付，也不承诺实时库存或可预订状态。模型使用 `extra="forbid"` 拒绝未声明字段，禁止把上述信息通过自由字段带入结果。密钥不提交，真实密钥也不进入文档示例。

## 用户流程与总体架构

用户在浏览器填写出发地、目的地、出行日期、人数、天数、预算和偏好。服务端校验请求后按固定顺序运行专业 Agent，最终返回结构化行程和 Markdown；前端只渲染净化后的 Markdown 与来源、警告、降级信息。

```text
[浏览器双栏页面]
        │  POST /api/travel-plans（同源 JSON）
        ▼
[FastAPI API 层] ── 请求校验、UUID、错误隐藏、安全响应头
        │
        ▼
[顺序编排器 SequentialTravelOrchestrator]
        │  1 天气 → 2 路线 → 3 住宿 → 4 餐饮 → 5 汇总
        ├──────────────┬───────────────┐
        ▼              ▼               ▼
[和风天气客户端]  [高德地图客户端]  [领域数据合同]
  /v7/weather/15d  地理编码/驾车/POI  Pydantic v2
        │              │               │
        └────── 受控重试、缓存、熔断 ────┘
                       │
                       ▼
             [TravelPlanDocument]
       itinerary + markdown + sources + warnings
```

## 模块职责与数据流

| 模块 | 主要职责 | 输入 → 输出 |
| --- | --- | --- |
| `backend/app/api/travel.py` | 定义旅行规划接口，读取中间件生成的请求标识，隐藏未预期异常 | JSON 请求 → `TravelPlanDocument` |
| `backend/app/main.py` | 创建 FastAPI 应用，挂载安全中间件、CORS、健康检查和前端静态目录 | `Settings` → 可运行应用 |
| `backend/app/models/travel.py` | 封闭字段、边界、状态一致性、来源时间和 UUID 合同 | 请求与 Agent 结果 → 不可变模型 |
| `backend/app/services/heweather.py` | 调用和风天气逐日预报并规范化天气字段 | 地点编码、日期、天数 → `DailyWeather` 来源结果 |
| `backend/app/services/amap.py` | 调用高德地理编码、驾车路线和文本 POI 并规范化字段 | 地点/坐标/关键词 → 地点、路线、POI |
| `backend/app/agents/weather.py` | 根据天气生成风险等级、活动约束和天气结果 | 请求 + 天气客户端 → 天气 Agent 结果 |
| `backend/app/agents/route.py` | 按天气风险选择风景名胜或室内文化场所，生成上午、下午、傍晚景区行程、约 120 分钟建议时长和景区间驾车预估 | 请求 + 天气结果 → 路线 Agent 结果 |
| `backend/app/agents/lodging.py` | 按推荐活动区域查询住宿服务 POI，只输出位置和筛选建议 | 请求 + 每日区域 → 住宿 Agent 结果 |
| `backend/app/agents/food.py` | 按上午景区提供午餐、按傍晚景区（缺失时回退下午景区）提供晚餐，查询景区附近餐饮 POI 并提取推荐菜品；保留无结果日期 | 请求 + 每日景区行程 → 餐饮 Agent 结果 |
| `backend/app/agents/summary.py` | 聚合四个结果，去重来源、拼接警告、确定顶层状态并生成 Markdown | 四个 Agent 结果 → 最终文档 |
| `backend/app/orchestration/sequential.py` | 固定天气 → 路线 → 住宿 → 餐饮 → 汇总顺序；单个 Agent 异常转为受控失败 | 请求 → 最终文档 |
| `frontend/app.js` | 校验表单、调用相对路径 API、显示用户可读错误和净化 Markdown | 表单 → 页面结果 |

数据流中的 `itinerary` 是唯一机器可消费的事实载体；`markdown` 是汇总 Agent 根据 `itinerary` 生成的阅读表现层，不能反向解析为事实。

## 企业 API 来源

### 和风天气：逐日预报

- 固定服务域名：`https://pb5ctx5qqr.re.qweatherapi.com`。
- 端点：`GET /v7/weather/15d`。
- 服务端参数：`location=<高德地理编码返回的经纬度>`、`key=<HEWEATHER_API_KEY>`；不使用高德 `adcode`。
- 客户端按请求日期过滤并最多使用 15 日逐日预报（`15d` 端点需使用支持 15 日预报的服务密钥），保留供应商确实提供的 `updateTime` 作为 `source_updated_at`。

### 高德地图：地理编码、驾车路线和 POI

- 固定服务域名：`https://restapi.amap.com`。
- 地理编码端点：`GET /v3/geocode/geo`，参数 `address=<地点>`、`key=<AMAP_API_KEY>`。
- 驾车路线端点：`GET /v3/direction/driving`，参数 `origin=<起点经纬度>`、`destination=<终点经纬度>`、`key=<AMAP_API_KEY>`。返回值只映射为距离和时长估算，不代表实时路况或到达保证。
- POI 文本搜索端点：`GET /v5/place/text`，参数 `keywords=<住宿服务或餐饮服务>`、`region=<城市或区域>`、`city_limit=true`、`key=<AMAP_API_KEY>`。`region` 限定搜索区域，`city_limit=true` 禁止跨城扩散。
- 附近 POI 端点：`GET /v5/place/around`，参数 `keywords=餐饮服务`、`location=<景区经纬度>`、`radius=2000`、`key=<AMAP_API_KEY>`。餐饮 Agent 仅在景区坐标为非空字符串时调用，半径由后端固定为 2000 米。
- Route Agent 常规天气查询 `风景名胜`；高风险天气优先查询 `博物馆`、`美术馆`、`展馆`，并在行程中标注室内文化场所提醒。每日按上午、下午、傍晚安排，单个景区建议约 120 分钟；候选不足或景区间驾车预估不可用时明确列出待补字段并降级，不复用候选或伪造结果。
- 供应商原始字段不会透传到 API 响应；POI 仅保留名称、地址、经纬度、类别、标签（tags）和内部来源标识。餐饮展示真实名称、地址，以及来自地图 POI 标签提取、菜系兜底的推荐菜品；不展示评分与推荐指数。

## 数据合同与安全边界

### 请求、追踪和状态

`TravelPlanRequest` 的规则如下：地点去除首尾空白；`departure_date` 不得早于服务端当前日期；`travelers` 为 1—20；`days` 为 1—14，默认 3；`budget` 为 0—200000 的整数或空值；偏好最多 12 项。住宿晚数是服务端派生的 `max(days - 1, 0)`，客户端不能提交 `nights` 覆盖它。

每次请求使用 UUID v1—v5 格式的 `request_id` 和 `trace_id`。当前 v1 中两者取相同值：请求标识用于跨层关联，追踪标识保留后续接入更细粒度链路追踪的兼容位置。响应和日志不得写入 API Key、Token、Cookie、Authorization、堆栈、内部 URL 或供应商原始响应。

Agent 状态只有以下 4 种：

| 状态 | 含义与合同要求 |
| --- | --- |
| `success` | 有完整 `data`，不能有 `missing_fields` 或 `error`。 |
| `partial` | 有部分 `data`，必须列出 `missing_fields`。 |
| `degraded` | 仍有可用 `data`，且必须说明缺失字段或受控错误；例如保留区域建议但没有精确路线。 |
| `failed` | `data` 必须为空，必须有 `missing_fields` 和受控 `error` 摘要。 |

顶层文档使用 `success`、`degraded` 或 `failed`：有 `partial` 或 `degraded` 专业结果时顶层为 `degraded`；存在任意 `failed` 专业结果时顶层为 `failed`。

### 来源时间语义

- `retrieved_at`：本服务本次从上游获取，或从本进程缓存读取该数据的时间；所有来源必须填写。
- `source_updated_at`：上游真实提供的内容更新时间，例如和风天气 `updateTime`；上游未提供时为 `null`，不能用 `retrieved_at` 伪造。
- `data_status`：`realtime` 表示本次上游获取，`cached` 表示进程内缓存命中，`degraded` 表示降级结果。当前模型还保留 `knowledge_base` 枚举以支持未来合同兼容，但本轮不接知识库。

汇总器按 weather、route、lodging、food 顺序聚合来源和警告。来源去重忽略每次可能不同的 `retrieved_at`，只依据来源事实字段；因此相同上游来源不会因读取时间不同而重复出现。

### 禁止交易字段与安全边界

领域合同拒绝以下字段及其同义扩展：`price`、`live_price`、`inventory`、`availability`、`bookable`、`queue`、`queue_time`、`discount`、`rating`、`review_score`、`order_url`。系统只给出候选位置、区域、设施、菜系、偏好筛选和核验提示，不承诺价格、库存、营业、排队或预订结果。

服务端密钥只从后端环境变量读取，浏览器只访问相对路径；CORS 仅允许配置的同源来源。API 返回通用错误，避免把异常详情、请求参数和供应商响应体泄露给客户端。

## 酒店查询与推荐

酒店功能是独立于行程规划的只读能力，默认关闭。它提供两种互不混用的数据源模式：传统飞猪 TOP 接口（面向具备商家/商旅资质的部署）与飞猪 FlyAI 开放平台（面向个人开发者）。两种模式返回的酒店结果都只用于展示，不包含预订、支付、库存或下单能力。

### 模式一：飞猪 TOP 酒店低价查询（企业模式）

- 固定网关：`https://eco.taobao.com/router/rest`，固定 method：`alitrip.btrip.hotel.distribution.search.low.price`（API 56180）。
- 请求以 TOP MD5 签名，需 `FLIGGY_HOTEL_APP_KEY`、`FLIGGY_HOTEL_APP_SECRET` 和服务端配置的 `FLIGGY_HOTEL_SUB_CHANNEL`；`sub_channel` 由后端注入，不接受前端传入。
- 按城市、入住/离店日期返回酒店名称、酒店 ID 和最低价（内部按“分”整数处理，输出按人民币元），价格相同时保持飞猪返回顺序。
- 需要飞猪商旅酒店分销资质和渠道授权，不适合个人开发者；未配置时默认关闭，不发起外部请求。

### 模式二：FlyAI 酒店 + 高德 POI 并列推荐（个人模式）

- 通过官方 `flyai` CLI 调用 MCP 工具 `search_hotels`，端点 `https://flyai.open.fliggy.com/mcp`；API Key 通过 `FLYAI_API_KEY` 配置，仅注入子进程环境变量，不出现在命令行参数、日志或响应中。
- 与高德住宿 POI 并行查询，只对规范化后名称完全相等的酒店合并展示价格/评分/星级/图片/详情与地址/位置；未匹配的 FlyAI 结果与高德 POI 分别展示，不补造价格或地址。
- FlyAI 未返回价格时显示“价格暂不可用”，不显示 0；`detailUrl` 仅作为官方详情外链，只允许 HTTPS，前端新窗口打开并带 `rel="noopener noreferrer"`。
- 图片只渲染 HTTPS 地址，加载失败时隐藏；供应商字段在前端使用 `textContent`/`createElement` 渲染，不使用 `innerHTML`。
- 需要在 FlyAI 控制台获取正式 API Key，并确保本机可执行 `flyai` 命令（`npx skills add alibaba-flyai/flyai-skill` 或 `npm i -g @fly-ai/flyai-cli`）。

### 接口与启用

- `POST /api/fliggy/hotels/search`：飞猪 TOP 酒店低价查询，企业模式。
- `POST /api/fliggy/hotels/recommend`：FlyAI 酒店与高德 POI 并列推荐，个人模式。
- 默认关闭：开关关闭或凭据缺失时返回 HTTP `503`，不发外部请求；FlyAI 上游受控错误返回 HTTP `502`，仅暴露受控错误码与 `trace_id`，不泄露 API Key 或上游原文。

启用步骤：

```powershell
# 编辑 backend\.env（不要提交，也不要粘贴到聊天或文档）
FLYAI_HOTEL_ENABLED=true
FLYAI_API_KEY=你的新Key
# 确保 flyai CLI 可执行；重启后端后进入前端“酒店推荐”视图即可测试
```

## 配置

复制 `backend/.env.example` 为 `backend/.env`，只填写本机或部署环境的密钥。`.env` 不得提交，真实密钥不得写入 Git、前端文件、日志、测试样例或 README。

| 环境变量 | 用途 | 单位 | 默认值 |
| --- | --- | --- | --- |
| `APP_ENV` | 运行环境名称 | — | `development` |
| `ALLOWED_ORIGINS` | CORS 允许的浏览器来源列表 | URL 列表 | `["http://localhost:5173"]` |
| `HEWEATHER_API_KEY` | 和风天气服务端密钥 | — | 空 |
| `HEWEATHER_BASE_URL` | 和风天气固定域名 | URL | `https://pb5ctx5qqr.re.qweatherapi.com` |
| `AMAP_API_KEY` | 高德地图服务端密钥 | — | 空 |
| `AMAP_BASE_URL` | 高德地图固定域名 | URL | `https://restapi.amap.com` |
| `EXTERNAL_CONNECT_TIMEOUT_SECONDS` | 外部 HTTP 建连超时 | 秒 | `3.0` |
| `EXTERNAL_READ_TIMEOUT_SECONDS` | 外部 HTTP 响应读取超时 | 秒 | `8.0` |
| `EXTERNAL_TOTAL_TIMEOUT_SECONDS` | 外部 API 单次总超时配置 | 秒 | `10.0` |
| `EXTERNAL_MAX_ATTEMPTS` | 外部请求最大尝试次数 | 次 | `3` |
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | 连续失败后打开熔断 | 次 | `3` |
| `CIRCUIT_BREAKER_OPEN_SECONDS` | 熔断保持打开时间 | 秒 | `60` |
| `WEATHER_CACHE_TTL_SECONDS` | 和风天气逐日预报缓存 TTL | 秒 | `1800` |
| `AMAP_GEOCODE_CACHE_TTL_SECONDS` | 高德地理编码缓存 TTL | 秒 | `604800` |
| `AMAP_ROUTE_CACHE_TTL_SECONDS` | 高德驾车路线缓存 TTL | 秒 | `900` |
| `AMAP_POI_CACHE_TTL_SECONDS` | 高德 POI 搜索缓存 TTL | 秒 | `3600` |
| `MINERU_API_KEY` | MinerU PDF 解析服务端密钥 | — | 空 |
| `MINERU_BASE_URL` | MinerU 固定服务地址 | URL | `https://mineru.net` |
| `QWEN_VL_API_KEY` | Qwen-VL 图表 OCR 服务端密钥 | — | 空 |
| `QWEN_VL_BASE_URL` | Qwen-VL 固定服务地址 | URL | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `QWEN_VL_MODEL` | Qwen-VL 图表 OCR 模型 | — | `qwen-vl-max` |
| `BGE_MODEL_PATH` | 本地 BGE embedding 模型目录 | 路径 | `D:\作业\model\bge-small-zh-v1.5` |
| `DOCUMENT_DATA_DIR` | 文档原文件、解析产物与索引目录 | 路径 | `backend/data` |
| `CHROMA_COLLECTION_NAME` | Chroma 文档集合名称 | — | `travel_documents` |
| `DOCUMENT_MAX_UPLOAD_BYTES` | 单份文档最大上传大小 | 字节 | `20971520` |
| `DOCUMENT_BATCH_MAX_FILES` | 单次批量上传最大文件数 | 份 | `10`（范围 1—20） |
| `FLIGGY_HOTEL_ENABLED` | 飞猪 TOP 酒店低价查询开关（企业模式） | 布尔 | `false` |
| `FLIGGY_HOTEL_APP_KEY` | 飞猪 TOP 应用 AppKey | — | 空 |
| `FLIGGY_HOTEL_APP_SECRET` | 飞猪 TOP 应用 AppSecret（仅签名，不落日志/响应） | — | 空 |
| `FLIGGY_HOTEL_SUB_CHANNEL` | 飞猪商旅酒店分销渠道值 | — | 空 |
| `FLIGGY_HOTEL_API_URL` | 飞猪 TOP 固定 HTTPS 网关（仅允许官方地址） | URL | `https://eco.taobao.com/router/rest` |
| `FLYAI_HOTEL_ENABLED` | FlyAI 酒店推荐开关（个人模式） | 布尔 | `false` |
| `FLYAI_API_KEY` | FlyAI 开放平台 API Key（门票与酒店共用） | — | 空 |
| `FLYAI_CLI_COMMAND` | FlyAI CLI 可执行命令 | 命令 | `flyai` |
| `FLYAI_CLI_TIMEOUT_SECONDS` | FlyAI CLI 单次调用总超时 | 秒 | `20.0` |
| `FLYAI_HOTEL_LIMIT` | FlyAI 酒店推荐单次最多返回结果数 | 条 | `10`（范围 1—20） |

所有变量仅由后端控制，客户端不能覆盖。密钥默认空值；缺少任一外部密钥时，`/api/ready` 返回 HTTP `503`，但 `/api/health` 仍可用于进程存活检查。酒店相关开关默认关闭，即使密钥存在也不会在未开启时发起外部请求。

## 本地启动

以下命令在 Windows PowerShell 中从仓库根目录执行。Python 建议使用 3.12，依赖以当前项目环境为准。

```powershell
# 可选：创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 安装后端依赖（若项目环境尚未安装）
python -m pip install -r backend\requirements.txt

# 复制配置模板，再编辑 backend\.env 填入服务端密钥
Copy-Item backend\.env.example backend\.env

# 设置当前 PowerShell 会话的 Python 模块路径
$env:PYTHONPATH = "$PWD\backend"

# 启动 FastAPI（开发环境自动重载）
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

启动后访问：

- 页面：<http://127.0.0.1:8000/>
- 存活检查：<http://127.0.0.1:8000/api/health>
- 就绪检查：<http://127.0.0.1:8000/api/ready>

`/api/ready` 需要 `HEWEATHER_API_KEY` 和 `AMAP_API_KEY` 均非空；这不等同于已验证供应商网络可用性。

## API 使用

### `POST /api/travel-plans`

请求头可选 `X-Request-Id`。传入合法 UUID v4 时服务端会规范化并沿用；缺失或版本不受支持时由服务端生成新的 UUID v4。请求体 `Content-Type` 为 `application/json`。

#### 请求示例

```powershell
$body = @{
  origin = "上海"
  destination = "杭州"
  departure_date = "2026-09-01"
  travelers = 2
  days = 3
  budget = 3000
  preferences = @("亲子", "美食")
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/travel-plans" `
  -ContentType "application/json" -Body $body
```

等价的请求 JSON 形状如下：

```json
{
  "origin": "上海",
  "destination": "杭州",
  "departure_date": "2026-09-01",
  "travelers": 2,
  "days": 3,
  "budget": 3000,
  "preferences": ["亲子", "美食"]
}
```

#### 响应示例

HTTP `200` 返回结构化文档。下面是 API 合同的精简 JSON 形状；实际响应还会包含各领域的完整字段、来源和警告。

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "itinerary": {
    "weather": {"status": "success", "data": {"destination": "杭州"}},
    "route": {"status": "success", "data": {"daily_areas": [{"day": 1, "area": "西湖"}]}},
    "lodging": {"status": "success", "data": {"nights": 2, "recommended_area": "西湖周边"}},
    "food": {"status": "success", "data": {"daily_food": [{"day": 1, "area": "西湖"}]}}
  },
  "markdown": "# 旅行计划\n",
  "sources": [],
  "warnings": [],
  "degraded_agents": []
}
```

页面不展示 JSON 源码。浏览器读取响应后只展示 Markdown 正文、待核验事项、来源更新时间和降级说明；结构化 JSON 仅作为 API 消费者和测试使用。Markdown 行程包含每日天气提醒、上午/下午/傍晚景区与建议时长、景区间驾车预估，以及按时段关联的午餐和晚餐餐饮名称、地址。晚餐优先使用傍晚景区，缺失时回退下午景区；餐饮营业安排仍需以商家官方信息核验。

#### 错误响应

- HTTP `422`：请求体不符合 Pydantic 合同，例如缺少 `destination`、人数不在 1—20 或日期早于今天。浏览器显示「请求参数不符合要求」或服务端提供的可读摘要。
- HTTP `500`：编排或服务端发生未预期错误。浏览器显示「旅行规划暂时不可用」，不展示异常堆栈或供应商原始响应。
- HTTP `503`：`GET /api/ready` 在外部密钥缺失时返回「外部数据服务尚未配置」。

### 文档库上传

文档库仅接受 MIME 类型和文件后缀一致、且文件签名有效的 PDF 与 DOCX。单文件接口保持为 `POST /api/documents`，成功时返回 HTTP `202` 与一份 `DocumentRecord`；其既有错误合同不变。

批量上传使用 `POST /api/documents/batch`，请求采用 multipart，并以重复的 `files` 字段按选择顺序提交。默认最多 10 份，后端可通过 `DOCUMENT_BATCH_MAX_FILES` 设置为 1—20。响应中的每项仅包含 1-based `index`、`accepted` / `rejected` / `unavailable` 状态，以及接受项的 `DocumentRecord` 或其他项的受控错误摘要；`accepted` 项会按既有 `DocumentRecord` 合同返回文件名，`rejected` / `unavailable` 项绝不回显不可信文件名、文件路径或异常详情。任一文件被接受时外层返回 `202`；全部校验失败返回 `422`；没有接受项且存在合法文件因处理器或存储不可用而无法接收时返回 `503`。未通过的文件不会入库或进入后台处理队列。

文档处理依赖本地 BGE 模型、Chroma、`python-docx`、MinerU、Qwen-VL 和 PyMuPDF。当前 PDF 始终在本地由 PyMuPDF 提取；MinerU 配置保留给后续受控外发解析接入，当前处理链路不会调用它。PyMuPDF 只能从 PDF 中提取可访问的文本与基础结构，不能保证扫描件 OCR、复杂版面、图表或表格的完整还原；此类内容需人工核验，后续接入受控 MinerU/Qwen-VL 后再按实际能力处理。

### 酒店查询与推荐接口

两个接口默认关闭，未配置或开关关闭时返回 HTTP `503`。

#### `POST /api/fliggy/hotels/search`（飞猪 TOP，企业模式）

请求按城市与入住/离店日期查询飞猪酒店最低价，价格按最低价升序稳定排序。请求体：

```json
{
  "city_name": "杭州",
  "check_in": "2026-09-01",
  "check_out": "2026-09-02",
  "page_no": 1,
  "page_size": 20
}
```

响应包含 `hotels` 列表（`hotel_id`、`name`、`low_price`、`currency`、`supplier`）、`total`、分页和 `trace_id`；`low_price` 以人民币元输出数字。

#### `POST /api/fliggy/hotels/recommend`（FlyAI + 高德 POI，个人模式）

请求体：

```json
{
  "city_name": "杭州",
  "check_in": "2026-09-01",
  "check_out": "2026-09-02",
  "poi_name": "西湖",
  "sort": "price_asc",
  "max_price": 500,
  "limit": 10
}
```

响应包含 `hotels` 列表，每项表示一个酒店：

- `hotel_name`、`flyai_price`（无价格时为 `null`）、`flyai_score`、`flyai_star`、`flyai_main_pic`、`detail_url`；
- `amap_address`、`amap_location`（高德匹配结果，未匹配时为 `null`）；
- `price_source`、`poi_source`、`match_status`（`matched` / `flyai_only` / `poi_only`）；
- 顶层含 `flyai_retrieved_at`、`amap_retrieved_at`、`poi_unavailable` 和 `trace_id`。

错误：参数不合法返回 `422`；开关关闭或凭据缺失返回 `503`；FlyAI 上游受控错误返回 `502`，仅返回受控错误码与 `trace_id`，不泄露 API Key 或供应商原文。

### 健康检查

- `GET /api/health`：进程存活检查，正常返回 `{"status":"ok"}`，不要求外部密钥。
- `GET /api/ready`：配置就绪检查，密钥缺失时返回 `503`，就绪时返回 `{"status":"ready"}`。

## 前端安全与页面

- 页面布局为桌面端双栏：左侧行程正文，右侧待核验事项、来源与更新时间、降级说明；窄屏在 `768px` 断点下改为单栏。
- 本地依赖版本：`marked` `15.0.12`，文件为 `frontend/vendor/marked.min.js`；`DOMPurify` `3.2.6`，文件为 `frontend/vendor/purify.min.js`。
- 本地文件 SHA-256：`marked.min.js` 为 `3e7e7d7feb3e5d58cb6c804f68ab5c24cc7e5eb6270fd6e5cbb9124739217d0c`；`purify.min.js` 为 `89e1fa7647cb495370d3a997ace4387f5d15d9f4c5af12352c53daa400956287`。完整许可证和 npm shasum 见 `frontend/vendor/THIRD_PARTY_NOTICES.md`。
- XSS 策略：Markdown 先由 `marked.parse` 转换，再由 `DOMPurify.sanitize` 净化。前端配置 `FORBID_TAGS` 禁止 `script`、`style`、`svg`、`math` 标签，配置 `FORBID_ATTR` 禁止名称匹配 `on*` 的事件属性。列表和错误文字使用 `textContent` / `replaceChildren`，不把 API 响应 JSON 序列化为页面原文。
- 前端只调用相对路径 `/api/travel-plans`，不携带服务端密钥，也不从 CDN 加载运行时依赖。
- 酒店推荐视图按来源并列展示：FlyAI 负责价格/评分/星级/图片/官方详情，高德负责地址/位置；未匹配字段显示“位置暂无匹配”或“价格暂不可用”，不显示 0、不补造数据、不展示“可预订/库存/下单”等承诺。图片与详情链接仅允许 HTTPS，图片加载失败自动隐藏，供应商字段一律使用 `textContent`/`createElement` 渲染。

## 缓存、重试与熔断

这是当前 MVP 的进程内行为，不是分布式缓存或全局流量治理。当前已知限制包括：和风天气 15 日窗口之外的日期可能没有匹配的逐日预报；多日外部调用按顺序执行，暂未实现 Route 总 deadline；附近 POI 仅按非空坐标字符串调用，未做本地经纬度格式校验；生产化治理尚未实现；天气日期连续性和来源元数据异常容错仍待加强。这些事项不能视为已解决：

- 和风天气 15 日窗口之外的日期可能没有匹配的逐日预报。
- 多日外部调用按顺序执行，当前暂无 Route 总 deadline。
- 附近 POI 仅检查坐标字符串非空，未做本地经纬度格式校验。
- 认证、限流、租户隔离、集中式密钥管理、审计和监控等生产化治理尚未实现。
- 天气日期连续性校验、来源元数据异常容错仍是待加强项。

当前 MVP 的缓存、重试和熔断行为如下：

1. 天气、地理编码、驾车路线和 POI 分别使用对应 TTL 的内存缓存；命中缓存时返回 `data_status=cached`，并刷新 `retrieved_at`。
2. 首次上游请求返回 `data_status=realtime`；供应商的真实更新时间才写入 `source_updated_at`。
3. 仅对连接错误、超时、HTTP `429` 和 HTTP `5xx` 做最多 3 次指数退避重试；业务参数错误和其他响应不盲目重试。
4. 连续失败达到 `CIRCUIT_BREAKER_FAILURE_THRESHOLD` 后打开熔断，保持 `CIRCUIT_BREAKER_OPEN_SECONDS`；熔断期间不继续访问上游，恢复后允许探测请求。
5. 单个 Agent 异常会转换为受控 `failed` 结果，由汇总器继续生成其余可用信息；最终顶层状态会反映失败。

## 测试与质量门禁

从仓库根目录执行，显式设置 `PYTHONPATH`，避免 Windows 下模块导入依赖当前目录偶然性：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests -v
```

测试数量和结果随当前工作树变化，以当前完整测试命令实际结果为准。测试覆盖模型、配置、供应商客户端、韧性、四类 Agent、汇总、编排、API 和前端资源。提交前必须至少通过：

```powershell
python -m pytest -c backend/pytest.ini backend/tests/test_docs.py -q
python -m pytest -c backend/pytest.ini backend/tests -q
git diff --check
```

## 常见故障排查

| 现象 | 检查与处理 |
| --- | --- |
| 页面打不开或根路径 `404` | 确认从仓库根目录启动，`frontend/index.html` 存在；不要把 `--app-dir` 指向 `frontend`。 |
| 启动时报 `ModuleNotFoundError: app` | 在当前 PowerShell 会话设置 `$env:PYTHONPATH = "$PWD\backend"`，或按示例使用 `--app-dir backend`。 |
| `/api/health` 正常、`/api/ready` 返回 `503` | 检查 `backend/.env` 是否包含非空 `HEWEATHER_API_KEY` 和 `AMAP_API_KEY`；密钥不写进代码或 README。 |
| 规划返回 `degraded` | 查看页面「待核验事项」和「降级说明」；确认上游网络、密钥、配额和熔断状态，不能把降级当作实时保证。天气超出和风 15 日窗口、景区候选不足、景区坐标缺失或附近餐饮无结果时，均应接受相应降级提示。 |
| 规划返回 `422` | 对照请求合同检查地点、日期、人数、天数、预算和偏好；未知字段会被拒绝。 |
| 规划返回 `500` | 查看服务端受控日志中的请求标识，检查编排器和配置；客户端不会收到原始堆栈。 |
| 外部请求反复失败 | 先检查固定域名是否可达、系统时间和供应商配额，再等待熔断窗口结束；不要通过客户端覆盖 `*_BASE_URL`。 |
| 前端显示 Markdown 异常 | 确认两个本地 vendor 文件未被替换，并检查 `frontend/vendor/THIRD_PARTY_NOTICES.md` 中的版本和 SHA-256。 |

## 部署与打包

部署包必须同时包含后端和前端静态目录：`backend/`（应用、依赖、配置模板）与 `frontend/`（`index.html`、`app.js`、`styles.css`、`vendor/marked.min.js`、`vendor/purify.min.js`）。FastAPI 从 `backend/app/main.py` 的上级目录定位 `frontend`；只打包后端会导致 API 可用但页面根路径 `404`。

生产环境使用外部进程管理器运行 Uvicorn，注入密钥和配置环境变量，不提交 `.env`。上线前应验证 `/api/health`、`/api/ready`、页面资源和一次脱敏的 API 合同请求，并限制日志访问权限。

## 生产化后续

在扩大流量或接入企业生产系统前，建议按优先级补齐：

- 为相同请求增加 single-flight，避免缓存未命中时并发击穿上游。
- 使用可观测的异步 HTTP 连接池，复用连接并明确连接生命周期。
- 实现有上限、可观测的缓存淘汰策略，避免进程内缓存无限增长。
- 统一请求级超时预算，让天气、路线、住宿、餐饮和汇总共享剩余时间，而不是各自独立等待；当前多日外部调用按顺序执行，暂未实现 Route 总 deadline。
- 增加限流、认证、租户隔离和配额控制；生产 CORS 只允许明确的前端来源。
- 增加结构化审计日志、密钥轮换、供应商调用指标、脱敏追踪和告警。
- 在不改变当前非交易边界的前提下，为未来知识库或 OTA 评审独立的数据合同、授权范围和安全审查；本轮不接知识库、OTA 或交易。
