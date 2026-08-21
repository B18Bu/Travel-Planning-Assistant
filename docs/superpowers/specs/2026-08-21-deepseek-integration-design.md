# DeepSeek 集成设计：多智能体结果汇总为最终结论

**日期：** 2026-08-21
**状态：** 已批准，待编写实现计划
**范围：** 在现有 v1 旅行规划全链路上，新增 DeepSeek 大模型汇总能力——四个专业 Agent 获取结构化事实后，由 DeepSeek 生成最终 Markdown 结论；DeepSeek 失败时回退到现有确定性汇总。

---

## 1. 目标与边界

### 1.1 目标

四个专业 Agent（天气、路线、住宿、餐饮）各自获取结构化事实后，将结果交给 DeepSeek，由它汇总生成最终旅行计划 Markdown 文案。编排顺序保持确定性，DeepSeek 仅承担最终表达的职责，不改变现有编排控制流。

- DeepSeek 接收 4 个 `AgentResult` 的结构化事实快照；
- DeepSeek 生成 `TravelPlanDocument.markdown`（人读展示层）；
- DeepSeek 失败、超时、熔断或输出非法时，回退为现有确定性 `SummaryAgent` 生成的 Markdown；
- 结构化 `itinerary`、`sources`、`warnings`、`degraded_agents` 仍由确定性代码构建，作为权威事实源。

### 1.2 非目标

首版不实现：

- 由 DeepSeek 编排 Agent 调用顺序或动态路由（编排保持确定性）；
- DeepSeek 生成超出 Agent 已获取事实的内容——价格、开放时间、可预订性、班次、评分等被领域合同禁止的字段一律不得出现；
- 流式输出、对话式多轮交互；
- 知识库检索、RAG 或向量库接入；
- 将密钥或上游地址暴露给浏览器。

### 1.3 成功标准

1. 配置有效 `DEEPSEEK_API_KEY` 时，接口返回的 `markdown` 由 DeepSeek 生成，且 `TravelPlanDocument` 全部契约校验通过。
2. `DEEPSEEK_API_KEY` 缺失、DeepSeek 超时、熔断打开、非 2xx、响应异常或输出为空/过短时，接口仍返回合法文档，`markdown` 回退为确定性文案。
3. DeepSeek 生成内容严格限于结构化事实快照，不新增任何被领域合同禁止的事实。
4. DeepSeek 密钥与上游地址仅存在于后端环境变量与配置，任何接口响应、错误信息、日志与前端均不出现。
5. 现有合同测试、新增 DeepSeek 服务与汇总 Agent 测试、完整后端测试套件全部通过。

---

## 2. 总体架构

```text
POST /api/travel-plans
  │
  ▼
SequentialTravelOrchestrator（确定性编排，不变）
  ├─ WeatherAgent  → AgentResult[WeatherPlanData]
  ├─ RouteAgent    → AgentResult[RoutePlanData]
  ├─ LodgingAgent  → AgentResult[LodgingPlanData]
  ├─ FoodAgent     → AgentResult[FoodPlanData]
  │
  ▼
DeepSeekSummaryAgent（新增，包装现有 SummaryAgent 作为确定性底座）
  ├─ ① 调用 deterministic_summary.run(...) 生成完整、合法的确定性 TravelPlanDocument
  ├─ ② 序列化其 itinerary 结构化事实快照为 user prompt
  ├─ ③ 调用 DeepSeekClient 生成 Markdown
  ├─ ④ 校验输出（非空、长度合理）
  │     ├─ 通过 → 以 model_copy(update={"markdown": LLM 文案}) 返回
  │     └─ 失败 → 直接返回确定性文档
  └─ 返回 TravelPlanDocument
```

外部依赖层

- `DeepSeekClient`（新增）：httpx 异步、分项超时、受限重试、服务级熔断、受控错误映射；
- 现有 `resilience.py` 的 `request_with_retry` / `CircuitBreaker` / `ExternalServiceUnavailable` 复用；
- DeepSeek API：`POST https://api.deepseek.com/chat/completions`（OpenAI 兼容格式）。

浏览器只请求同源 API。DeepSeek 密钥、地址、模型、超时、重试与熔断逻辑仅存在于后端。

---

## 3. 组件设计

### 3.1 `app/services/deepseek.py` —— `DeepSeekClient`

仿照 `heweather.py` / `amap.py` 的受控只读客户端模式：

- `_base_url = "https://api.deepseek.com"`，构造时校验：`base_url != self._base_url` 直接抛 `ExternalServiceUnavailable("DeepSeek 服务地址不受支持")`；
- 构造参数：`api_key`、`base_url`、`model`、`cache`、`breaker`、`max_attempts`、`max_tokens`、`timeout`，全部带默认值且与现有客户端一致的校验（整数/布尔、上下界）；
- `async def chat_completion(self, system_prompt: str, user_prompt: str) -> str`：
  1. `_require_key()`：密钥为空则抛 `ExternalServiceUnavailable("DeepSeek API 密钥未配置")`；
  2. 熔断 `ensure_available()`；
  3. `POST {base}/chat/completions`，JSON 体：`{"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.2, "max_tokens": max_tokens}`，请求头 `Authorization: Bearer {api_key}`、`Content-Type: application/json`；
  4. 非 2xx → `ExternalServiceUnavailable`；JSON 解析异常、`choices` 缺失、`message.content` 非字符串或空 → 受控错误；
  5. 输出校验：去除首尾空白后长度须在 `20 ≤ len ≤ deepseek_max_tokens × 4` 字符范围内，否则视为受控失败；
  6. 成功记录熔断成功并返回 `choices[0]["message"]["content"]`（去除首尾空白）。

### 3.2 `app/agents/deepseek_summary.py` —— `DeepSeekSummaryAgent`

- 构造参数：`deepseek_client`、`deterministic_summary: SummaryAgent`；
- `async def run(weather, route, lodging, food, request_id, trace_id) -> TravelPlanDocument`：
  1. 调用 `deterministic_summary.run(...)` 生成完整、合法的确定性 `TravelPlanDocument`（其内部已校验 UUID 并构建 status / itinerary / sources / warnings / degraded_agents）；
  2. 序列化确定性文档 `itinerary` 中的结构化事实为 JSON 快照（仅各 Agent 的 `data`、`warnings`、`missing_fields`、`degraded_agents`，不含任何密钥/上游地址）；
  3. 调用 `deepseek_client.chat_completion(system_prompt, user_prompt)`；
  4. 输出校验通过 → 用 `deterministic.model_copy(update={"markdown": llm_markdown})` 返回升级版文档；
  5. 任何 LLM 异常或校验失败 → 捕获并直接返回确定性文档；
  6. 任何情况下均返回合法 `TravelPlanDocument`，不向编排器抛错。

### 3.3 接线与编排

- `app/dependencies.py`：在 `build_orchestrator` 中新增 `DeepSeekClient(settings.deepseek_api_key, base_url=settings.deepseek_base_url, model=settings.deepseek_model, ...)`，并构造 `DeepSeekSummaryAgent(deepseek_client, SummaryAgent())`；
- `SequentialTravelOrchestrator` 的 `summary` 参数改为传入 `DeepSeekSummaryAgent`，其 `run()` 方法签名与现有调用兼容，编排器主体逻辑不变。

---

## 4. 配置

`backend/app/config.py` 新增（沿用现有注释与整数校验风格）：

```python
deepseek_api_key: str = ""                                # 服务端密钥，默认空；仅后端使用，不暴露
deepseek_base_url: str = "https://api.deepseek.com"       # 固定 HTTPS 域名，不接受客户端覆盖
deepseek_model: str = "deepseek-chat"                     # 默认模型名称
deepseek_max_tokens: int = Field(default=2000, ge=256, le=8192)
```

- 超时、重试次数、熔断阈值/时长复用现有 `external_*_timeout_seconds`、`external_max_attempts`、`circuit_breaker_*`，不新增重复项；
- `backend/.env.example` 与 `backend/.env` 同步新增 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`DEEPSEEK_MAX_TOKENS`；
- `.env` 已纳入 `.gitignore`，真实密钥不提交。

---

## 5. 数据流

```text
POST /api/travel-plans（TravelPlanRequest）
  → orchestrator.run()
    → 4 个专业 Agent 依次执行（确定性）
    → DeepSeekSummaryAgent.run(...)
        deterministic_summary 确定性文档
          → 事实快照 prompt → DeepSeek API → 校验
            ├─ 通过：model_copy(update={"markdown": LLM 文案})
            └─ 失败：直接返回确定性文档
    → 返回 TravelPlanDocument
```

接口返回中的结构化 `itinerary` 是权威事实源；`markdown` 仅为人读展示层。LLM 文案即使有疏漏，机器可读数据仍完整无损。

---

## 6. Prompt 设计

**System：**

> 你是智能文旅策划助手的最终汇总模块。你将收到一份旅行规划的结构化事实快照。请将其组织成一份自然、完整、结构清晰的 Markdown 旅行计划。严格要求：
> 1. 只使用提供的结构化事实，不得新增任何事实（包括价格、开放时间、可预订性、班次、评分等）；
> 2. 必须覆盖全部事实：天气逐日、每日路线区域、住宿候选、餐饮候选、待核验事项、降级说明；
> 3. 对数据缺失、降级或待核验的内容明确标注「待核验」；
> 4. 只输出 Markdown，不要输出任何无关说明。

**User：** 序列化后的结构化事实快照 JSON。

快照内容仅含：天气逐日数据、路线区域、住宿候选（名称/地址/类别）、餐饮候选（名称/菜系）、各 Agent 的 `warnings`、`missing_fields`、`degraded_agents`。

---

## 7. 错误处理与回退

| 场景 | 行为 |
|---|---|
| `deepseek_api_key` 为空 | 跳过 LLM，直接确定性生成（同 `_require_key` 模式） |
| DeepSeek 非 2xx / JSON 异常 / 无 `choices` | `ExternalServiceUnavailable`，记熔断失败 |
| 连续失败 | 熔断器打开，后续请求快速短路到回退 |
| 超时 / 重试耗尽 | 受控错误，回退确定性文案 |
| LLM 输出去除空白后长度 < 20 或 > `deepseek_max_tokens × 4` 字符 | 视为失败，回退确定性文案 |
| `DeepSeekSummaryAgent` 任意异常 | 捕获并回退，**永不向 API 层抛错** |

`/api/ready` 不要求 `DEEPSEEK_API_KEY`（有回退保证服务可用），保持现有 weather + map 检查，README 补充说明。

---

## 8. 测试

- **`backend/tests/test_deepseek.py`**（客户端单测，仿照 `test_heweather.py` / `test_amap.py`，`respx` mock）：
  - 成功解析并返回 `choices[0].message.content`；
  - 429 / 5xx 重试后成功；重试耗尽记录熔断失败；
  - 非 2xx、JSON 异常、`choices` 缺失、`content` 空 → 受控错误，错误信息不含密钥；
  - 空密钥不发起 HTTP；
  - 非规范 `base_url` 拒绝（含尾斜杠、路径、大小写等变体）。
- **`backend/tests/test_deepseek_summary.py`**：
  - LLM 成功 → `markdown` 为 LLM 文案，`TravelPlanDocument` 契约校验通过；
  - LLM 失败 / 超时 / 熔断打开 / 输出空或过短 → 回退确定性 `markdown`；
  - 密钥未配置 → 直接确定性；
  - prompt 覆盖全部事实（断言构造的 user prompt 包含天气、路线、住宿、餐饮数据与警告）；
  - 结构契约字段（`sources` / `warnings` / `degraded_agents`）与确定性路径一致。
- **配置测试**：`test_config.py` 的 `CONFIG_FIELD_DOCUMENTATION` / `ENV_FIELD_DOCUMENTATION` 新增 DeepSeek 字段及文档片段断言。
- **回归**：完整后端测试套件（现有 580 个 + 新增）全部通过。

---

## 9. 安全

- DeepSeek 密钥、上游地址、模型、超时、重试与熔断逻辑仅存在于后端；
- 客户端错误信息不包含密钥、URL 细节或供应商原始响应体；
- DeepSeek 上游地址固定白名单，不接受客户端覆盖；
- 事实快照 prompt 只含结构化事实，不含密钥；模型输出仅为 Markdown 文本，最终渲染仍经前端 DOMPurify 净化；
- 设计遵循「事实与生成分层」：实时数据出事实，大模型只负责解释、组合和表达。
