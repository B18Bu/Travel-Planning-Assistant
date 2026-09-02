# 智能文旅策划助手

面向企业内部的**只读式文旅规划服务**：输入出发地、目的地、日期与人数，系统按「天气 → 路线 → 住宿 → 餐饮 → 汇总」的固定链路，汇聚天气、地图路线、住宿区域、餐饮 POI 与自建攻略知识库，生成**可追溯、可降级、不编造**的结构化行程。

> 当前版本是 **MVP**：只提供建议与核验提示，**不执行预订、支付或任何交易**。

![语言](https://img.shields.io/badge/语言-简体中文-blue) ![后端](https://img.shields.io/badge/后端-FastAPI%20%2F%20Python%203.12-brightgreen) ![前端](https://img.shields.io/badge/前端-原生%20HTML%2FJS-orange) ![状态](https://img.shields.io/badge/状态-MVP-yellow)

---

## 目录

- [功能特性](#功能特性)
- [项目背景与目标](#项目背景与目标)
- [总体架构](#总体架构)
- [功能模块说明](#功能模块说明)
  - [行程规划（核心链路）](#1-行程规划核心链路)
  - [攻略查询（文档知识库）](#2-攻略查询文档知识库)
  - [门票查询](#3-门票查询)
  - [酒店推荐](#4-酒店推荐)
  - [数据看板](#5-数据看板)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [核心概念：数据合同与状态](#核心概念数据合同与状态)
- [容错设计](#容错设计)
- [安全设计](#安全设计)
- [测试与质量](#测试与质量)
- [目录结构](#目录结构)
- [部署与打包](#部署与打包)
- [常见问题排查](#常见问题排查)
- [文档索引](#文档索引)
- [已知限制与路线图](#已知限制与路线图)

---

## 功能特性

| 功能 | 说明 | 状态 |
| --- | --- | --- |
| 行程规划 | 天气 → 路线 → 住宿 → 餐饮 → 汇总 五步链路，生成含时段、提醒、午晚餐建议的可核验 Markdown 行程 | ✅ 核心已实现 |
| 攻略查询 | 上传 PDF/DOCX 攻略，语义 + 关键词双通道检索，DeepSeek 生成带来源的回答 | ✅ 已实现 |
| 文档库 | 批量上传、解析（PDF/DOCX + 图表 OCR）、切块、向量化入库、来源可溯源 | ✅ 已实现 |
| 数据看板 | 检索结果「有用 / 没用」反馈聚合，按文档与地区统计好评率 | ✅ 已实现 |
| 门票查询 | 飞猪 FlyAI 只读文本检索，返回门票摘要（不含实时价格库存） | 🚧 筹备态，默认关闭 |
| 酒店推荐 | 飞猪 TOP 低价查询（企业）+ FlyAI 酒店与高德 POI 并列推荐（个人） | 🚧 筹备态，默认关闭 |

**核心价值**：每条事实都有来源、时间和数据状态；任何外部服务失败都能降级而非崩溃；大模型只做整理与判断，绝不当事实来源。

---

## 项目背景与目标

旅行规划需要同时处理日期、活动区域、天气风险、路线估算和餐饮住宿候选。若各模块直接传递自由字典，容易出现字段漂移、来源时间混淆、上游原始错误泄露和降级状态不一致。

**项目目标：**

1. 以强类型数据合同连接天气、路线、住宿、餐饮、汇总与 API。
2. 通过 `request_id`（请求标识）与 `trace_id`（追踪标识）贯穿一次请求，便于日志关联与问题定位。
3. 清晰区分实时数据、进程内缓存与降级结果，要求用户对关键事实复核。
4. 以同源、**双栏**页面展示行程正文与待核验事项，不把供应商原始响应直接暴露给浏览器。
5. 以服务端密钥、固定供应商域名、受控超时、重试与熔断建立最小安全边界。

本项目遵循 `docs/项目宪法.md` 的硬性约束：

1. **不编造事实**：实时信息一律来自受控 API；拿不到就明确标注「暂不可用 / 待核验」，绝不用模型补造。
2. **禁止交易字段**：价格、库存、可订状态、评分、排队时长等字段被数据模型直接拒绝。
3. **模型不能成为事实来源**：大模型只用于归纳、解释、起草等判断类任务。
4. **失败必须显式暴露**：任何模块失败都要在最终文档中说明。
5. **全程可追溯**：每次请求贯穿 `request_id` 与 `trace_id`，每条数据记录来源与时间。

### 用户流程

用户在浏览器填写出发地、目的地、出行日期、人数、天数、预算与偏好；服务端校验请求后按固定顺序运行专业 Agent，最终返回结构化行程与 Markdown；前端只渲染净化后的 Markdown 与来源、警告、降级信息。

### 范围与非目标

**包含**：行程规划、攻略查询（文档知识库）、文档库、数据看板，以及默认关闭的门票查询与酒店推荐；系统只提供建议与核验提示，**不执行预订、支付或任何交易**。

**不包含**：知识库内容运营后台、OTA（在线旅行代理）交易、酒店或餐厅交易、预订、支付、库存、优惠、排队与订单链接。门票与酒店查询保持只读边界，不收集游客身份信息；模型使用 `extra="forbid"` 拒绝未声明字段，禁止把禁止字段通过自由字段带入结果。密钥不提交到版本控制，真实密钥不进入文档示例。

---

## 总体架构

```text
[浏览器工作台页面]
      │  同源请求
      ▼
[FastAPI API 层] ── 请求校验、UUID、错误隐藏、安全响应头
      │
      ▼
[顺序编排器 SequentialTravelOrchestrator]
      │  1 天气 → 2 路线 → 3 住宿 → 4 餐饮 → 5 汇总
      ├──────────────┬───────────────┬───────────────┐
      ▼              ▼               ▼               ▼
[和风天气客户端]  [高德地图客户端]  [文档知识库]   [飞猪 / FlyAI]
 /v7/weather/15d  地理编码/驾车/POI  PDF/DOCX→向量→检索  门票 / 酒店 / 酒店推荐
      │              │               │
      └────── 受控重试、缓存、熔断、降级 ──────┘
                       │
                       ▼
             [TravelPlanDocument]
       itinerary + markdown + sources + warnings
```

- **前端**：原生 HTML/JavaScript 工作台，由后端同源托管，只调用相对路径 API。
- **后端**：FastAPI + Pydantic 强类型数据合同，按固定顺序编排专业 Agent。
- **外部数据**：和风天气、高德地图、飞猪 FlyAI / TOP、DeepSeek、Qwen-VL、本地 BGE + Chroma。

外部数据源端点（固定 HTTPS 域名，只读 GET）：

| 数据源 | 端点 | 用途与关键参数 |
| --- | --- | --- |
| 和风天气 | `GET /v7/weather/15d` | 逐日预报，参数 `location`、`key` |
| 高德地图 | `GET /v3/geocode/geo` | 地理编码（地名 → 经纬度），参数 `address`、`key` |
| 高德地图 | `GET /v3/direction/driving` | 驾车路线，参数 `origin`、`destination`、`key` |
| 高德地图 | `GET /v5/place/text` | 文本 POI 搜索，参数 `keywords`、`region`、`city_limit=true`、`key` |
| 高德地图 | `GET /v5/place/around` | 附近 POI 搜索，参数 `keywords`、`location`、`radius=2000`、`key` |

数据流中的 `itinerary` 是唯一机器可消费的事实载体；`markdown` 是汇总 Agent 根据 `itinerary` 生成的阅读表现层，**不能反向解析为事实**。

---

## 功能模块说明

### 1. 行程规划（核心链路）

用户在页面填写出发地、目的地、出行日期、人数、天数、预算和偏好，服务端按固定顺序执行五个专业 Agent：

| Agent | 职责 | 数据来源 |
| --- | --- | --- |
| 天气 Agent | 逐日预报、风险等级（暴雨/台风/高温）、活动约束 | 高德地理编码 + 和风天气 |
| 路线 Agent | 每日上午/下午/傍晚景点安排（各约 120 分钟）、景区间驾车预估；高风险天气优先室内文化场所 | 高德地理编码、驾车路线、POI |
| 住宿 Agent | 推荐住宿区域与候选（只给位置和筛选建议，不含价格） | 高德住宿 POI |
| 餐饮 Agent | 按上午景区推荐午餐、按傍晚（回退下午）景区推荐晚餐，从 POI 标签提取推荐菜品 | 高德周边餐饮 POI |
| 汇总 Agent | 聚合四结果、来源去重、警告收集、顶层状态判定、生成 Markdown | 前序结构化结果（不新增事实） |

> 天气风险判断、路线约束传递、候选合并与汇总均为**确定性代码**，保证可审计、可测试、可降级。

### 2. 攻略查询（文档知识库）

一套完整的 RAG（检索增强生成）子系统：

- **入库**：上传 PDF/DOCX（校验 MIME 与文件魔数）→ 异步后台解析（PyMuPDF / python-docx，图表经 Qwen-VL OCR）→ 切块（上限 800 字符、重叠 100）→ 本地 BGE 向量化 → 写入 Chroma 向量库。
- **检索**：语义检索（向量）+ 关键词检索（识别省市与意图）双通道，RRF 倒排融合，含省份硬过滤。
- **回答**：DeepSeek 基于检索片段生成带来源的 Markdown 回答，**只使用片段事实、不编造**。
- **闭环**：检索记录持久化，支持赞/踩反馈，聚合为「数据看板」统计。
- **质量**：`backend/evaluation/` 提供可复跑评估工具（16 题、四项指标、DeepSeek 裁判）。

> MinerU 云端 PDF 解析客户端已接入代码但**当前未启用**，PDF 始终本地用 PyMuPDF 提取。

### 3. 门票查询

通过飞猪 AI 开放平台（FlyAI）做**只读文本检索**，不创建订单、不处理支付、不收集游客身份信息。三种 provider 由 `FLIGGY_TICKET_PROVIDER` 选择：

| Provider | 行为 |
| --- | --- |
| `disabled`（默认） | 不发起请求，返回「服务尚未配置」（503） |
| `mock` | 返回明确标注的本地演示数据（西湖/故宫/黄山） |
| `flyai` | 调用 FlyAI `ai-search` / `search-poi` 只读检索，返回门票文本摘要（`data_status=flyai_text`） |

FlyAI 文本检索返回自然语言摘要而非结构化价格/库存，因此价格固定显示「信息暂不可用」，**绝不从自然语言猜测实时交易字段**。前端查询前会弹窗告知只读边界。

### 4. 酒店推荐

两种互不混用的数据源模式，均只读展示：

- **模式一：飞猪 TOP 酒店低价查询（企业模式）**——固定网关 + MD5 签名，需要飞猪商旅资质与渠道授权；价格按「分」内部处理、以「元」输出，按最低价升序稳定排序。
- **模式二：FlyAI 酒店 + 高德 POI 并列推荐（个人模式）**——FlyAI 查价格/评分/星级/图片/详情，高德查地址/位置；仅对规范化后名称完全相等的酒店合并展示，匹配状态为 `matched` / `flyai_only` / `poi_only`，**不补造价格或地址**。

### 5. 数据看板

基于知识检索结果下的「有用 / 没用」反馈，统计知识库内容与 AI 生成内容的好评率，并按来源文档、按地区分组展示。

---

## 快速开始

以下命令在 Windows PowerShell 中从仓库根目录执行。

### 环境要求

- Python **3.12**（以项目当前环境为准）
- 本地 BGE 向量模型 `bge-small-zh-v1.5`（模型文件由使用者自行准备）
- （可选）`flyai` 命令行工具：`npx skills add alibaba-flyai/flyai-skill` 或 `npm i -g @fly-ai/flyai-cli`，用于门票 / 酒店 FlyAI 模式

启用 FlyAI 时，先访问 [FlyAI 开放平台](https://open.fly.ai/) 注册并登录，在控制台的 API Key 管理页面创建密钥。将密钥只写入 `backend/.env` 的 `FLYAI_API_KEY`，并按需设置 `FLIGGY_TICKET_PROVIDER=flyai` 或 `FLYAI_HOTEL_ENABLED=true`。密钥不得提交到 GitHub。

### 安装与启动

```powershell
# 1. 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. 安装后端依赖
python -m pip install -r backend\requirements.txt

# 3. 复制配置模板，再编辑 backend\.env 填入服务端密钥
Copy-Item backend\.env.example backend\.env

# 4. 设置当前 PowerShell 会话的 Python 模块路径
$env:PYTHONPATH = "$PWD\backend"

# 5. 启动 FastAPI（开发环境自动重载）
python -m uvicorn app.main:app --app-dir backend --reload
```

### 验证

- 页面：启动后访问本机服务地址。

> `.env` 不得提交到版本控制（已由 `.gitignore` 排除）；真实密钥不得写入 Git、前端文件、日志或测试样例。

---

## 配置说明

复制 `backend/.env.example` 为 `backend/.env`，只填写本机或部署环境需要的密钥。所有变量**仅由后端控制，客户端不能覆盖**；密钥默认空值。

| 环境变量 | 用途 | 单位 | 默认值 |
| --- | --- | --- | --- |
| `APP_ENV` | 运行环境名称 | — | `development` |
| `ALLOWED_ORIGINS` | CORS 允许的浏览器来源列表 | URL 列表 | `["http://localhost:5173"]` |
| `HEWEATHER_API_KEY` | 和风天气服务端密钥 | — | 空 |
| `AMAP_API_KEY` | 高德地图服务端密钥 | — | 空 |
| `MINERU_API_KEY` | MinerU PDF 解析服务端密钥（预留） | — | 空 |
| `QWEN_VL_API_KEY` | Qwen-VL 图表 OCR 服务端密钥 | — | 空 |
| `QWEN_VL_MODEL` | Qwen-VL 图表 OCR 模型 | — | `qwen-vl-max` |
| `DEEPSEEK_API_KEY` | DeepSeek 大模型润色服务端密钥 | — | 空 |
| `DEEPSEEK_MODEL` | DeepSeek 润色模型（务必使用 `deepseek-chat`，勿配推理模型） | — | `deepseek-chat` |
| `DEEPSEEK_MAX_TOKENS` | DeepSeek 单次生成最大 token 数 | 个 | `2000` |
| `DEEPSEEK_TIMEOUT_SECONDS` | DeepSeek 单次请求总超时 | 秒 | `60` |
| `BGE_MODEL_PATH` | 本地 `bge-small-zh-v1.5` 模型目录 | 路径 | 由使用者填写 |
| `DOCUMENT_DATA_DIR` | 文档原文件、解析产物与索引目录 | 路径 | `backend/data` |
| `CHROMA_COLLECTION_NAME` | Chroma 文档集合名称 | — | `travel_documents` |
| `DOCUMENT_MAX_UPLOAD_BYTES` | 单份文档最大上传大小 | 字节 | `20971520` |
| `DOCUMENT_BATCH_MAX_FILES` | 单次批量上传最大文件数 | 份 | `10`（范围 1—20） |
| `KNOWLEDGE_SEARCH_RESULT_LIMIT` | 知识检索最终返回结果数 | 条 | `12`（范围 1—50） |
| `FLIGGY_TICKET_PROVIDER` | 门票查询 provider | — | `disabled`（`disabled` / `mock` / `flyai`） |
| `FLYAI_API_KEY` | FlyAI 开放平台 API Key（门票与酒店共用） | — | 空 |
| `FLYAI_TIMEOUT_SECONDS` | FlyAI 请求总超时 | 秒 | `30` |
| `FLIGGY_HOTEL_ENABLED` | 飞猪 TOP 酒店低价查询开关（企业模式） | 布尔 | `false` |
| `FLIGGY_HOTEL_APP_KEY` | 飞猪 TOP 应用 AppKey | — | 空 |
| `FLIGGY_HOTEL_APP_SECRET` | 飞猪 TOP 应用 AppSecret（仅签名） | — | 空 |
| `FLIGGY_HOTEL_SUB_CHANNEL` | 飞猪商旅酒店分销渠道值 | — | 空 |
| `FLIGGY_HOTEL_API_URL` | 飞猪 TOP 固定 HTTPS 网关 | URL | `https://eco.taobao.com/router/rest` |
| `FLYAI_HOTEL_ENABLED` | FlyAI 酒店推荐开关（个人模式） | 布尔 | `false` |
| `FLYAI_CLI_COMMAND` | FlyAI CLI 可执行命令 | 命令 | `flyai` |
| `FLYAI_CLI_TIMEOUT_SECONDS` | FlyAI CLI 单次调用总超时 | 秒 | `20.0` |
| `FLYAI_HOTEL_LIMIT` | FlyAI 酒店推荐单次最多返回结果数 | 条 | `10`（范围 1—20） |
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

外部服务地址由后端固定配置，客户端不可覆盖；密钥缺失时服务会提示配置不完整。

---

## 接口说明

项目接口由前端和后端内部协同使用，README 不展开 API 路径与请求细节。

---

## 核心概念：数据合同与状态

### Agent 结果合同

每个专业 Agent 返回统一信封（Pydantic 强类型，`extra="forbid"` 拒绝未声明字段、`frozen` 构造后不可变）：

| 字段 | 约束 |
| --- | --- |
| `agent` | 固定为 `weather` / `route` / `lodging` / `food` |
| `status` | 仅允许 `success` / `partial` / `degraded` / `failed` |
| `summary` | 面向汇总器的简短已证实结论 |
| `data` | 领域字段约束；禁止密钥、原始异常、未授权时效字段 |
| `constraints` | 供下游消费的确定性限制 |
| `sources` | 所有外部或知识库事实的来源集合 |
| `warnings` | 对用户可见的核验提示和风险说明 |
| `request_id` / `trace_id` | 请求标识与追踪标识（当前取相同值） |

### 四种状态

| 状态 | 含义 | 合同要求 |
| --- | --- | --- |
| `success` | 有完整 `data` | 不得有 `missing_fields` 或 `error` |
| `partial` | 有部分 `data` | 必须列出 `missing_fields` |
| `degraded` | 仍有可用 `data` | 必须说明缺失字段或受控错误 |
| `failed` | 完全失败 | `data` 必须为空，必须有 `missing_fields` 和受控 `error` |

顶层文档状态：存在任意 `failed` → `failed`；存在 `partial` / `degraded` → `degraded`；全成功 → `success`。

### 来源时间语义

- `retrieved_at`：本服务本次获取（或从缓存读取）的时间，所有来源必须填写；
- `source_updated_at`：上游真实提供的内容更新时间，上游未提供时为 `null`，**不能用 `retrieved_at` 伪造**；
- `data_status`：`realtime`（本次上游获取）/ `cached`（缓存命中）/ `degraded`（降级）；模型保留 `knowledge_base` 枚举以兼容未来知识库来源合同。

汇总器按 weather → route → lodging → food 顺序聚合来源与警告，来源去重忽略每次不同的 `retrieved_at`，只依据来源事实字段。

### 禁止交易字段

领域合同拒绝 `price`、`live_price`、`inventory`、`availability`、`bookable`、`queue`、`queue_time`、`discount`、`rating`、`review_score`、`order_url` 及其同义扩展。系统只给出候选位置、区域、设施、菜系、偏好筛选与核验提示，**不承诺价格、库存、营业、排队或预订结果**。

---

## 容错设计

当前 MVP 为进程内行为，不是分布式治理：

1. **缓存**：天气、地理编码、驾车路线、POI 分别使用对应 TTL 的内存缓存；命中缓存返回 `data_status=cached` 并刷新 `retrieved_at`。
2. **重试**：仅对连接错误、超时、HTTP `429` 和 `5xx` 做最多 3 次指数退避重试；业务参数错误与其他响应不盲目重试。
3. **熔断**：连续失败达 `CIRCUIT_BREAKER_FAILURE_THRESHOLD`（默认 3 次）后打开熔断，保持 `CIRCUIT_BREAKER_OPEN_SECONDS`（默认 60 秒）；熔断期间不访问上游，恢复后允许探测请求。
4. **降级**：单个 Agent 异常转换为受控 `failed`，汇总器继续生成其余可用信息；无真实 POI 时保留区域建议并列出待补字段，**不复用候选、不伪造结果**。

---

## 安全设计

### 密钥安全
- 密钥只在后端环境变量（`.env`），不提交 Git、不进日志与响应；前端只访问相对路径。
- FlyAI API Key 仅注入子进程环境变量（`FLYAI_API_KEY`），不出现在命令行参数或异常中；飞猪 AppSecret 仅用于请求签名。

### 输入 / 输出安全
- 所有接口输入经 Pydantic 做类型、长度、范围校验；未知字段一律拒绝。
- 供应商原始字段不透传前端；API 返回通用错误，不暴露异常堆栈、内部 URL 或上游原文。
- 领域合同 `extra="forbid"` 拒绝未声明字段，禁止交易字段进入数据链路。

### 前端安全
- Markdown 先由 `marked.parse` 转换，再由 `DOMPurify.sanitize` 净化，防 XSS（跨站脚本攻击）；配置 `FORBID_TAGS` 禁止 `script` / `style` / `svg` / `math`，配置 `FORBID_ATTR` 禁止 `on*` 事件属性。
- 列表与错误文字使用 `textContent` / `replaceChildren` 渲染，不把响应 JSON 序列化为页面原文；酒店 / 门票供应商字段一律 `textContent` / `createElement`。
- 前端不携带任何服务端密钥；第三方库（marked、DOMPurify）为本地固定版本，不从 CDN 加载。
- 图片与详情链接仅允许 HTTPS（图片加载失败自动隐藏）；本地依赖版本与 SHA-256 见 `frontend/vendor/THIRD_PARTY_NOTICES.md`。

### 响应头与 CORS
每个响应带 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: strict-origin-when-cross-origin` 与 `X-Request-Id`；CORS 仅允许配置的同源来源，不使用通配符。

---

## 测试与质量

从仓库根目录执行，显式设置 `PYTHONPATH`：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests -v
```

- 测试覆盖模型、配置、供应商客户端、韧性（重试/熔断）、四类 Agent、汇总、编排、API 和前端资源。
- **测试验证意图**：验证「为什么需要此行为」，如禁止字段不得进入系统、降级时不得伪造数据、汇总不新增事实。
- 提交前门禁：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_docs.py -q
python -m pytest -c backend/pytest.ini backend/tests -q
git diff --check
```

### RAG 检索质量评估

```powershell
cd backend
$env:PYTHONPATH = "$PWD"
python -m evaluation.evaluate
```

基于 16 道真实攻略问题（7 个目的地），由 DeepSeek 裁判按 RAGAS 口径输出四项指标，报告见 `backend/evaluation/report.md`。最近一次结果：**忠实度 0.948 · 上下文召回率 0.838 · 上下文准确率 0.758 · 相关性 0.920**。

---

## 目录结构

```text
backend/
  app/
    main.py               应用工厂、路由注册、依赖组装
    config.py             服务端配置（密钥、超时、开关）
    security.py           请求标识与安全响应头
    dependencies.py       受控依赖组装
    errors.py             受控错误码
    models/               强类型数据合同（travel / documents / fliggy / flyai_hotel）
    services/             外部服务客户端与通用能力（天气、地图、缓存、韧性、文档、检索、酒店、门票）
    agents/               专业 Agent（weather / route / lodging / food / summary）
    orchestration/        顺序编排器
    api/                  接口层（travel / documents / fliggy / flyai_hotel）
  tests/                  自动化测试
  evaluation/             RAG 检索质量评估工具（golden 集、裁判、主脚本、报告）
  data/                   本地文档库数据（.gitignore 排除）
frontend/
  index.html              工作台页面
  app.js                  页面逻辑（请求、安全渲染）
  styles.css              样式
  vendor/                 marked、DOMPurify 本地固定版本与许可
docs/
  项目宪法.md             项目最高规则
  v1-baseline-design.md   v1 基线设计
  superpowers/            分功能设计与实现计划
  答辩-项目理解与讲解.md   答辩讲解文档（Markdown）
  答辩-项目理解与讲解.html 答辩讲解文档（网页版）
```

---

## 部署与打包

部署包必须同时包含后端与前端静态目录：`backend/`（应用、依赖、配置模板）与 `frontend/`（`index.html`、`app.js`、`styles.css`、`vendor/`）。FastAPI 从 `backend/app/main.py` 的上级目录定位 `frontend`；只打包后端会导致 API 可用但页面根路径 `404`。

生产环境使用外部进程管理器运行 Uvicorn，注入密钥与配置环境变量，不提交 `.env`，并限制日志访问权限。

---

## 常见问题排查

| 现象 | 检查与处理 |
| --- | --- |
| 页面打不开或根路径 `404` | 确认从仓库根目录启动，`frontend/index.html` 存在；不要把 `--app-dir` 指向 `frontend` |
| 启动报 `ModuleNotFoundError: app` | 设置 `$env:PYTHONPATH = "$PWD\backend"`，或按示例使用 `--app-dir backend` |
| 服务提示配置不完整 | 检查 `backend/.env` 是否包含非空 `HEWEATHER_API_KEY` 与 `AMAP_API_KEY` |
| 规划返回 `degraded` | 查看页面「待核验事项」和「降级说明」；确认上游网络、密钥、配额与熔断状态 |
| 规划返回 `422` | 对照请求合同检查地点、日期、人数、天数、预算与偏好；未知字段会被拒绝 |
| 规划返回 `500` | 查看服务端受控日志中的请求标识，检查编排器与配置；客户端不会收到原始堆栈 |
| 外部请求反复失败 | 检查固定域名可达性、系统时间与供应商配额，等待熔断窗口结束；不要通过客户端覆盖 `*_BASE_URL` |
| 文档上传被拒绝 | 确认格式为 PDF/DOCX、MIME 与后缀一致、文件魔数有效、大小不超过 20MB |
| 攻略检索无结果 | 确认文档已处理为 `ready` 状态；检查省份/城市过滤是否排除目标文档 |
| 门票 / 酒店页面显示「服务尚未配置」 | 检查对应开关（`FLIGGY_TICKET_PROVIDER` / `FLIGGY_HOTEL_ENABLED` / `FLYAI_HOTEL_ENABLED`）与密钥 |
| 前端显示 Markdown 异常 | 确认 `frontend/vendor/` 两个本地文件未被替换，核对 `THIRD_PARTY_NOTICES.md` 中版本与 SHA-256 |

---

## 文档索引

| 文档 | 说明 |
| --- | --- |
| `docs/项目宪法.md` | 项目最高规则：产品边界、数据授权、安全、可观测性、发布门禁 |
| `docs/v1-baseline-design.md` | v1 基线设计：目标、范围、数据合同、降级矩阵、实施顺序 |
| `docs/superpowers/` | 各功能的规格设计与实现计划 |
| `docs/答辩-项目理解与讲解.md` / `.html` | 答辩讲解：项目理解 + 精讲详讲（通俗中文） |

---

## 已知限制与路线图

### 当前已知限制

- 缓存与熔断为**进程内**行为，重启即清空，不支持多实例共享；
- 多日行程的外部调用按顺序执行，暂无统一的请求级超时预算；
- 附近 POI 仅检查坐标字符串非空，未做本地经纬度格式校验；
- 和风天气 15 日窗口之外的日期可能没有匹配的逐日预报；
- PDF 扫描件（图片型）依赖 OCR 能力，复杂版面不能保证完整还原；
- 认证、限流、租户隔离、集中式密钥管理、审计与监控等生产化治理尚未实现。

### 生产化路线图

按优先级补齐：

1. 相同请求 single-flight，避免缓存未命中时并发击穿上游；
2. 可观测的异步 HTTP 连接池，明确连接生命周期；
3. 有上限、可观测的缓存淘汰策略；
4. 统一的请求级超时预算（天气、路线、住宿、餐饮、汇总共享剩余时间）；
5. 限流、认证、租户隔离与配额控制；生产 CORS 仅允许明确前端来源；
6. 结构化审计日志、密钥轮换、供应商调用指标、脱敏追踪与告警；
7. 在不改变非交易边界的前提下，为知识库或 OTA 扩展评审独立的数据合同、授权范围与安全审查。
