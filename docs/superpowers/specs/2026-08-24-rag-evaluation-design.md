# 知识检索 RAG 子系统评估工具 设计规格

**日期：** 2026-08-24
**状态：** 已批准（brainstorming 设计评审）

## 背景与目标

对项目的**知识检索 / 文档问答子系统**（RAG 部分）做量化评估，产出四项指标：**忠实度、上下文准确率、上下文召回率、相关性**（RAGAS 口径）。评估工具可复用、可复跑，用于持续追踪检索与生成质量。

旅行规划链路是确定性 Agent 编排，非 RAG，不在本评估范围。

## 指标定义（RAGAS 口径）

| 指标 | 计算方式 | 衡量 |
| --- | --- | --- |
| 忠实度 Faithfulness | 将「生成答案」拆为独立陈述，逐句判断是否被检索上下文支持；支持句数 / 总句数 | 幻觉程度（低 = 幻觉少） |
| 上下文召回率 Context Recall | 将「参考答案」拆为独立陈述，逐句判断是否可从检索上下文归因；可归因句数 / 总句数 | 检索是否覆盖回答所需信息 |
| 上下文准确率 Context Precision | 逐块判断检索结果中每个块是否相关；按相关块排名计算 RAGAS `CP@k = Σ_k(P@k × v_k) / 相关块总数` | 相关块是否排在前面 |
| 相关性 Answer Relevance | DeepSeek 对「生成答案是否切题、充分回答」直接打分 0-1 | 回答是否真正回应问题 |

## 架构与组件

位置：`backend/evaluation/`

| 文件 | 职责 |
| --- | --- |
| `golden_set.json` | golden 测试集：每题 `{question, reference_answer}`，约 16 题，覆盖 7 个目的地 |
| `judge.py` | DeepSeek 裁判：4 项指标的判定提示词与可解析输出解析器 |
| `evaluate.py` | 主脚本：加载 golden 集 → 逐题检索 + 生成 + 判定 → 聚合 → 生成 `report.md` |

## 数据流（每题）

1. **检索**：复刻 `backend/app/api/documents.py` 的检索流，复用服务层组件：
   - `ChromaStore.query(query, limit=fetch_limit=36)`（语义）
   - `parse_query` + `search_chunks(..., limit=36)`（关键词）
   - `merge_ranked_hits(..., limit=result_limit=12)`（区域感知融合）
   - 参数取 `knowledge_search_result_limit=12`、`fetch_limit=36`，与线上一致。
2. **生成**：`KnowledgePolisher.polish(query, results)` → DeepSeek Markdown 答案。
3. **判定**：`judge.py` 用 DeepSeek 计算四项指标。
4. **输出**：聚合 + 每题明细 + 失败案例。

## Golden 测试集设计

- 来源：7 份攻略正文（成都/贵州/三亚/青岛/西安/新疆（伊犁）/云南）。
- 结构：`[{ "id": "q01", "question": "...", "reference_answer": "..." }]`。
- 构造方式：通读各文档提取事实 → 每个目的地 2-3 题（覆盖景点、美食、行程、交通等主题）→ 参考答案基于文档真实内容撰写，不含编造。
- 规模：约 16 题。

## 判定提示词策略

- 每个判定输出设计为「每行一个判定」（如「支持」「不支持」或「是」「否」），`judge.py` 逐行解析。
- 忠实度/上下文召回率：先让 LLM 把文本拆成原子陈述（编号输出），再逐条判定；为节省调用，拆句与判定合并为一次调用（返回编号 + 判定）。
- 相关性：一次调用输出 0-1 分 + 一句话理由。
- 上下文准确率：一次调用对全部检索块编号 + 判定相关与否。

## 错误处理与降级

- 检索失败（外部不可用/熔断）→ 该题跳过并记录 `skipped`，不纳入均分，报告列出。
- 生成失败（DeepSeek 不可用）→ 该题保留检索侧指标（上下文准确率），忠实度/召回率/相关性记 `n/a`。
- 判定失败 → 该题对应指标记 `n/a`，报告标注。
- 输出报告须明确暴露跳过/缺失情况，不得静默算均值。

## 输出

- `backend/evaluation/report.md`：
  - 四项指标总均分（0-1）。
  - 每题明细：各指标得分、检索到哪些块（前 5 摘要）、生成答案摘要、判定理由。
  - 失败/跳过清单。
  - 运行参数（golden 题数、判定模型、时间戳）。

## 验收标准

1. `python -m pytest backend/tests` 现有测试不回归（评估工具独立于 app 运行，不修改生产代码）。
2. 对 `backend/evaluation/golden_set.json` 运行 `python -m evaluation.evaluate`（在 `backend/` 下）可产出 `report.md`。
3. 四项指标各有一致、可解释的 0-1 分数；跳题/缺失项在报告中明确标注。
4. 评估可复跑：同一 golden 集连续两次运行结果一致（判定用确定性解析；LLM 判定可能有波动，报告注明）。
