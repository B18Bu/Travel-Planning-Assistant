# 飞猪 FlyAI 门票只读检索设计

**日期：** 2026-08-25
**状态：** 已确认设计，待规格审阅
**范围：** 使用飞猪 AI 开放平台的服务端 API/CLI 能力，提供门票信息自然语言只读检索；不创建订单、不预订、不支付、不退款、不改签、不核销。

## 1. 背景与决策

项目当前的 `25781` / `25767` TOP API 方案依赖尚未完成的应用授权、session、签名、字段展示许可和沙箱合同。飞猪 AI 开放平台 Quickstart 明确提供 `FLYAI_API_KEY` 配置和 `fliggy-fast-search` 检索示例，官方能力概览覆盖 POI 与景点门票场景。

本阶段采用最快的文本检索方案：新增 FlyAI 文本适配器，保留 `mock` 和 `disabled` provider；不把 FlyAI 自然语言响应伪装成 TOP API 的结构化 SKU、价格或库存。

官方依据：

- [飞猪 AI 开放平台快速开始](https://flyai.open.fliggy.com/docs/quickstart)
- [飞猪 AI 开放平台能力概览](https://flyai.open.fliggy.com/docs)
- [飞猪 AI Skill](https://github.com/alibaba-flyai/flyai-skill)

## 2. 产品边界

### 2.1 请求

沿用现有 `TicketSearchRequest`：

- `scenic_keyword`：1—100 个字符；
- `entry_date`：不早于服务端当天；
- `visitor_count`：1—20，仅用于本地校验和结果上下文。

游客姓名、证件号码、手机号、护照、支付信息和订单信息不进入请求。客户端不能传入 API Key、provider、原始提示词或上游地址。

### 2.2 FlyAI 查询

后端根据关键词和日期生成固定查询内容，要求 FlyAI 仅返回景点门票信息，并明确要求：只读查询、不预订、不下单、不支付；游客人数不作为上游身份或交易参数。

FlyAI Key 只从服务端 `FLYAI_API_KEY` 读取，不记录、不返回、不写入测试快照或 Git。真实 Key 曾在对话中暴露时必须先撤销并重新生成。

### 2.3 展示

采用紧凑信息卡：

- 景点/门票标题；
- 已确认的门票文本摘要；
- 查询日期；
- 来源和查询时间；
- `data_status = flyai_text`；
- “FlyAI 文本检索结果，不代表实时可售状态”警告；
- 价格和库存固定显示“价格信息暂不可用”“库存信息暂不可用”，除非后续取得稳定、明确、获准展示的结构化合同。

不得从自然语言中正则提取或猜测价格、库存、可售性、最低价或余票。

页面不添加预订、购买、支付、订单、跳转或游客身份输入控件。

## 3. 架构与 provider

```text
前端门票表单
  │ 关键词、日期、人数
  ▼
POST /api/fliggy/tickets/search
  │ 服务端校验
  ▼
TicketServiceProvider
  ├─ disabled：默认关闭，不访问外部
  ├─ mock：本地明确标记的演示数据，不访问外部
  └─ flyai：服务端 FlyAI 只读文本检索
  ▼
白名单文本响应 + 来源/时间/状态/警告
  ▼
前端 textContent 安全渲染
```

配置：

```env
FLIGGY_TICKET_PROVIDER=disabled
FLYAI_API_KEY=
FLYAI_TIMEOUT_SECONDS=30
```

可选本地演示：

```env
FLIGGY_TICKET_PROVIDER=mock
```

启用 FlyAI：

```env
FLIGGY_TICKET_PROVIDER=flyai
FLYAI_API_KEY=仅填入本地或部署环境的已轮换密钥
```

provider 只能由服务端配置决定。`FLIGGY_ENABLED`、旧 TOP API 凭据和 `FLIGGY_MOCK_ENABLED` 不得被客户端覆盖。

## 4. 响应合同

FlyAI 文本适配器仍返回项目领域响应，但商品结构字段不作虚假填充：

```json
{
  "source_name": "飞猪 AI 开放平台",
  "retrieved_at": "2026-08-25T10:00:00+08:00",
  "data_status": "flyai_text",
  "scenic_keyword": "西湖",
  "visitor_count": 2,
  "tickets": [],
  "summary": "已确认的门票信息文本摘要",
  "warnings": [
    "FlyAI 文本检索结果，不代表实时可售状态。",
    "价格信息暂不可用。",
    "库存信息暂不可用。请以飞猪官方页面为准。"
  ]
}
```

如果现有 `TicketSearchResponse` 不能表达文本摘要，应新增严格的 `summary` 字段或单独的文本结果模型；不得伪造 `TicketProduct` 的 `item_id`、价格、库存或 SKU。

## 5. 错误与降级

| 场景 | HTTP | 行为 |
| --- | ---: | --- |
| provider=disabled | 503 | 显示服务未配置，不访问外部。 |
| provider=mock | 200 | 返回本地演示数据，标记 `mock`。 |
| provider=flyai 且 Key 缺失 | 503 | 显示 FlyAI 服务尚未配置，不发请求。 |
| FlyAI 超时、鉴权失败、限流或 5xx | 503 | 清空旧结果，显示受控重试提示，不泄露上游错误。 |
| FlyAI 返回空文本 | 200 | 返回空结果并提示调整关键词。 |
| 文本缺少价格/库存 | 200 | 保留文本摘要，价格/库存显示暂不可用。 |
| 文本包含疑似交易操作建议 | 200 | 仅保留门票信息摘要，过滤预订/支付操作内容。 |

不回显 API Key、Authorization、Cookie、原始请求、完整上游响应、内部 URL 或堆栈。

## 6. 测试与验收

先写失败测试，再实现最小适配器：

- provider 默认 disabled 且不创建外部客户端；
- provider=mock 仍返回明确的本地演示数据；
- provider=flyai 从服务端读取 Key，客户端字段不能覆盖；
- 请求只包含景点关键词和日期等必要查询上下文，不包含身份/支付信息；
- FlyAI 文本结果不填充结构化价格、库存、SKU；
- 缺失价格/库存显示不可用状态；
- 超时、鉴权、限流和 5xx 映射为受控 503；
- 上游文本不作为 HTML 渲染；
- 前端展示来源、时间、`flyai_text` 状态和警告；
- 不出现预订、支付、订单或游客身份输入；
- `node --check frontend/app.js`、全量 pytest 和 `git diff --check` 通过。

## 7. 未完成前置条件

在 FlyAI 文档明确或实测确认以下内容前，不得宣称结构化实时价格/库存：

1. 稳定的后端调用方式和 endpoint/CLI 服务契约；
2. 门票查询响应字段、来源和查询时间语义；
3. 价格、库存、图片和规则的展示许可；
4. 超时、限流、错误码、配额和数据时效；
5. Key 的受控保存、轮换和撤销流程；
6. 沙箱/测试验证与安全评审。
