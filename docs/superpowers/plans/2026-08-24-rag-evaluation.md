# 知识检索 RAG 评估工具 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 `backend/evaluation/` 构建可复跑的 RAG 评估工具，对知识检索子系统产出四项指标（忠实度、上下文召回率、上下文准确率、相关性）的量化评分与报告。

**架构：** 主脚本 `evaluate.py` 直接复用现有服务层（`ChromaStore`/`DocumentStore`/`LocalBgeEmbedder`/`keyword_search`/`KnowledgePolisher`）复刻线上检索与生成链路，`judge.py` 用 DeepSeek 按 RAGAS 口径逐题判定四项指标，最终聚合成 `report.md`。golden 测试集从 7 份攻略正文构造。

**技术栈：** Python 3.12、Pydantic v2、httpx、asyncio、pytest。评估为独立工具，不修改任何生产代码。

**规格：** `docs/superpowers/specs/2026-08-24-rag-evaluation-design.md`（已批准）

---

## 文件结构

- 创建 `backend/evaluation/__init__.py` — 包标记（空文件）
- 创建 `backend/evaluation/golden_set.json` — golden 测试集（约 16 题）
- 创建 `backend/evaluation/judge.py` — DeepSeek 裁判（4 项指标）
- 创建 `backend/evaluation/evaluate.py` — 主脚本（检索 + 生成 + 判定 + 报告）
- 创建 `backend/tests/test_evaluation.py` — 裁判解析器单元测试

## 环境事实（已核实）

- 文档库：`data/documents.json` 含 7 个 ready 文档、193 个块（`content`/`document_name`/`source_page` 等字段）。
- 配置：`Settings.deepseek_model="deepseek-chat"`、`knowledge_search_result_limit=12`、`bge_model_path`、`document_data_dir`、`chroma_collection_name`。BGE 模型与 Chroma 索引离线可加载（实测 1.8s），DeepSeek 密钥已配置。
- 检索复刻基准：`backend/app/api/documents.py:231-302` 的 `search_knowledge`（fetch_limit=36、result_limit=12、区域硬过滤）。
- 判定统一走 `DeepSeekClient.chat_completion(system_prompt, user_prompt)`，返回纯文本。

---

## 任务 1：构建 golden 测试集

**文件：**
- 创建 `backend/evaluation/golden_set.json`

- [ ] **步骤 1：读取 7 份攻略块内容**

在 `backend/` 下用一次性脚本读取 `data/documents.json` 的 `chunks`，按 `document_name` 分组，输出每个目的地的块内容摘要（每块前 200 字），供构造题目与参考答案使用。

运行：`python -c "import json;d=json.load(open('data/documents.json',encoding='utf-8'));[print(c['document_name'],'|',c['content'][:200].replace(chr(10),' ')) for c in d['chunks']]"`

- [ ] **步骤 2：构造 16 题 + 参考答案**

每个目的地（成都/贵州/三亚/青岛/西安/新疆(伊犁)/云南）2-3 题，共约 16 题。题目覆盖景点、美食、行程安排、交通等主题。`reference_answer` 必须是该文档块中真实存在的事实，**不得编造**。

- [ ] **步骤 3：写入 golden_set.json**

```json
[
  {
    "id": "sanya-01",
    "question": "三亚有哪些必游景点？",
    "reference_answer": "三亚的必游景点包括天涯海角、亚龙湾等。"
  }
]
```

`id` 用「目的地-序号」命名；中文用 UTF-8 保存。

- [ ] **步骤 4：验证 JSON 合法且题目数 ≥ 12**

运行：`python -c "import json;d=json.load(open('backend/evaluation/golden_set.json',encoding='utf-8'));print(len(d))"`
预期：输出 ≥ 12；每题含 `id`、`question`、`reference_answer` 三个非空字段。

- [ ] **步骤 5：提交**

```bash
git add backend/evaluation/golden_set.json
git commit -m "feat: RAG 评估 golden 测试集（7 目的地约 16 题）"
```

---

## 任务 2：judge.py DeepSeek 裁判（TDD）

**文件：**
- 创建 `backend/evaluation/__init__.py`
- 创建 `backend/evaluation/judge.py`
- 测试：`backend/tests/test_evaluation.py`

- [ ] **步骤 1：编写失败的解析器测试**

`backend/tests/test_evaluation.py`：

```python
from evaluation.judge import _parse_verdict_lines, _parse_pair_lines, _context_precision


def test_parse_verdict_lines_accepts_valid_rows():
    text = "1|支持|三亚有天涯海角\n2|不支持|三亚有免税店\n"
    rows = _parse_verdict_lines(text, "支持", "不支持")
    assert rows == [(1, True, "三亚有天涯海角"), (2, False, "三亚有免税店")]


def test_parse_verdict_lines_skips_malformed():
    text = "abc\n1|支持\n2|支持|陈述|多余\n3|不确定|坏判定\n"
    assert _parse_verdict_lines(text, "支持", "不支持") == []


def test_parse_pair_lines_ignores_malformed():
    text = "1|相关\nbad\n2|不相关\n"
    assert _parse_pair_lines(text, "相关", "不相关") == [(1, True), (2, False)]


def test_context_precision_formula():
    # 相关块在第 1、3、5 位 → CP = (1/1 + 2/3 + 3/5) / 3
    assert abs(_context_precision({1, 3, 5}, 5) - ((1.0 + 2.0 / 3.0 + 3.0 / 5.0) / 3.0)) < 1e-9


def test_context_precision_zero_relevant_is_zero():
    assert _context_precision(set(), 5) == 0.0
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && python -m pytest tests/test_evaluation.py -q`
预期：FAIL，报 `ModuleNotFoundError: No module named 'evaluation'`。

- [ ] **步骤 3：实现解析器与 CP 公式**

`backend/evaluation/__init__.py` 空文件。`backend/evaluation/judge.py`：

```python
"""DeepSeek 裁判：为 RAG 评估计算四项指标。"""
from __future__ import annotations

import re
from typing import Any, Sequence

from app.services.deepseek import DeepSeekClient
from app.services.resilience import ExternalServiceUnavailable

_SYSTEM = (
    "你是严谨的 RAG 质量评估裁判。只依据给定材料与规则判断，"
    "输出严格遵守规定的格式，不要输出任何额外说明。"
)


def _parse_verdict_lines(
    text: str, verdict_yes: str, verdict_no: str
) -> list[tuple[int, bool, str]]:
    """解析「编号|判定|陈述」行；无法解析的行直接跳过。"""
    rows: list[tuple[int, bool, str]] = []
    for line in text.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        num, verdict, statement = (part.strip() for part in parts)
        if not num.isdigit() or verdict not in (verdict_yes, verdict_no):
            continue
        rows.append((int(num), verdict == verdict_yes, statement))
    return rows


def _parse_pair_lines(
    text: str, verdict_yes: str, verdict_no: str
) -> list[tuple[int, bool]]:
    """解析「编号|判定」行。"""
    pairs: list[tuple[int, bool]] = []
    for line in text.splitlines():
        parts = line.split("|", 1)
        if len(parts) != 2:
            continue
        num, verdict = (part.strip() for part in parts)
        if not num.isdigit() or verdict not in (verdict_yes, verdict_no):
            continue
        pairs.append((int(num), verdict == verdict_yes))
    return pairs


def _context_precision(relevant_positions: set[int], total: int) -> float:
    """RAGAS 上下文准确率 CP@k = Σ_k(P@k × v_k) / R。"""
    if not relevant_positions or total <= 0:
        return 0.0
    relevant_in_k = 0
    acc = 0.0
    for k in range(1, total + 1):
        if k in relevant_positions:
            relevant_in_k += 1
            acc += relevant_in_k / k
    return acc / len(relevant_positions)
```

- [ ] **步骤 4：运行测试确认通过**

运行：`cd backend && python -m pytest tests/test_evaluation.py -q`
预期：PASS（5 项）。

- [ ] **步骤 5：实现四项指标判定方法**

`backend/evaluation/judge.py` 追加：

```python
class Judge:
    """用 DeepSeek 计算四项 RAG 指标的裁判。"""

    def __init__(self, client: DeepSeekClient) -> None:
        self._client = client

    async def _ask(self, user_prompt: str) -> str:
        return await self._client.chat_completion(_SYSTEM, user_prompt)

    @staticmethod
    def _context_text(results: Sequence[Any]) -> str:
        return "\n".join(f"[{i}] {result.content}" for i, result in enumerate(results, 1))

    async def faithfulness(
        self, question: str, answer: str, context_results: Sequence[Any]
    ) -> float | None:
        prompt = (
            f"用户问题：{question}\n\n检索片段：\n{self._context_text(context_results)}\n\n"
            f"待判断的回答：\n{answer}\n\n"
            "任务：把回答拆分为若干独立事实陈述，逐条判断该陈述是否被上述检索片段支持"
            "（支持=能从片段推断，不支持=片段没有依据）。\n"
            "每行严格输出：<编号>|<支持|不支持>|<陈述内容>\n示例：\n1|支持|三亚有天涯海角景区"
        )
        raw = await self._ask(prompt)
        rows = _parse_verdict_lines(raw, "支持", "不支持")
        if not rows:
            return None
        return sum(1 for _, ok, _ in rows if ok) / len(rows)

    async def context_recall(
        self, question: str, reference_answer: str, context_results: Sequence[Any]
    ) -> float | None:
        prompt = (
            f"用户问题：{question}\n\n检索片段：\n{self._context_text(context_results)}\n\n"
            f"参考答案（golden）：\n{reference_answer}\n\n"
            "任务：把参考答案拆分为若干独立事实陈述，逐条判断该陈述是否可从上述检索片段归因"
            "（可归因=片段包含该事实或可推断，不可归因=片段中没有）。\n"
            "每行严格输出：<编号>|<可归因|不可归因>|<陈述内容>"
        )
        raw = await self._ask(prompt)
        rows = _parse_verdict_lines(raw, "可归因", "不可归因")
        if not rows:
            return None
        return sum(1 for _, ok, _ in rows if ok) / len(rows)

    async def context_precision(
        self, question: str, context_results: Sequence[Any]
    ) -> float | None:
        prompt = (
            f"用户问题：{question}\n\n检索片段（按当前排序）：\n{self._context_text(context_results)}\n\n"
            "任务：逐条判断每个检索片段是否与回答该问题相关。\n"
            "每行严格输出：<编号>|<相关|不相关>\n示例：\n1|相关\n2|不相关"
        )
        raw = await self._ask(prompt)
        pairs = _parse_pair_lines(raw, "相关", "不相关")
        relevant = {num for num, ok in pairs if ok}
        return _context_precision(relevant, len(context_results))

    async def answer_relevance(self, question: str, answer: str) -> float | None:
        prompt = (
            f"用户问题：{question}\n\n生成回答：\n{answer}\n\n"
            "任务：从 0 到 1 评分该回答是否切题、充分回答用户问题"
            "（1=完全切题且充分，0=完全无关）。\n"
            "只输出：<0-1数字>|<一句话理由>"
        )
        raw = await self._ask(prompt)
        match = re.match(r"\s*([0-9]*\.?[0-9]+)\s*\|", raw)
        if not match:
            return None
        try:
            return max(0.0, min(1.0, float(match.group(1))))
        except ValueError:
            return None
```

- [ ] **步骤 6：补充裁判异常测试**

`backend/tests/test_evaluation.py` 追加（用假客户端，不触发真实 API）：

```python
from evaluation.judge import Judge


class FakeDeepSeek:
    def __init__(self, response: str): self.response = response
    async def chat_completion(self, system, user): return self.response


async def test_judge_faithfulness_parses_supported_ratio():
    judge = Judge(FakeDeepSeek("1|支持|a\n2|支持|b\n3|不支持|c"))
    assert await judge.faithfulness("q", "答", []) == pytest.approx(2 / 3)
```

运行：`cd backend && python -m pytest tests/test_evaluation.py -q`，预期 PASS。

- [ ] **步骤 7：提交**

```bash
git add backend/evaluation/__init__.py backend/evaluation/judge.py backend/tests/test_evaluation.py
git commit -m "feat: RAG 评估 DeepSeek 裁判（四项指标）"
```

---

## 任务 3：evaluate.py 主脚本

**文件：**
- 创建 `backend/evaluation/evaluate.py`

- [ ] **步骤 1：实现检索复刻与主流程**

```python
"""RAG 评估主脚本：检索 → 生成 → 判定 → 报告。

用法（在 backend/ 下）：python -m evaluation.evaluate
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from app.config import Settings
from app.models.documents import DocumentStatus, KnowledgeSearchResult, SourceLocation
from app.services.chroma_store import ChromaStore
from app.services.deepseek import DeepSeekClient
from app.services.document_store import DocumentStore
from app.services.embeddings import LocalBgeEmbedder
from app.services.keyword_search import (
    merge_ranked_hits,
    parse_query,
    region_from_document_name,
    search_chunks,
)
from app.services.knowledge_polish import KnowledgePolisher
from app.services.resilience import ExternalServiceUnavailable

from evaluation.judge import Judge

BASE_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = BASE_DIR / "golden_set.json"
REPORT_PATH = BASE_DIR / "report.md"
METRIC_KEYS = ("faithfulness", "context_recall", "context_precision", "answer_relevance")


def _load_golden() -> list[dict[str, str]]:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("golden_set.json 顶层必须是数组")
    return data


class RetrievalService:
    """复刻 api/documents.py 的检索链路（fetch_limit=36、result_limit=12）。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.document_store = DocumentStore(settings.document_data_dir)
        self.chroma = ChromaStore(
            self.document_store.chroma_dir,
            settings.chroma_collection_name,
            LocalBgeEmbedder(settings.bge_model_path),
        )
        ready_ids = {
            record.id
            for record in self.document_store.list_documents()
            if record.status is DocumentStatus.ready
        }
        self._indexed = self.document_store.get_documents_with_chunks(ready_ids)
        self._chunks_by_id: dict[UUID, Any] = {}
        for _record, chunks in self._indexed.values():
            for chunk in chunks.values():
                self._chunks_by_id[UUID(str(chunk.id))] = chunk

    def retrieve(self, query: str) -> list[KnowledgeSearchResult]:
        result_limit = self.settings.knowledge_search_result_limit
        fetch_limit = result_limit * 3
        semantic_hits = self.chroma.query(query, limit=fetch_limit)
        parsed = parse_query(query)
        keyword_hits = search_chunks(
            list(self._chunks_by_id.values()), parsed, limit=fetch_limit
        )
        ranked = merge_ranked_hits(
            semantic_hits,
            keyword_hits,
            region_of_chunk=lambda chunk_id: (
                region_from_document_name(self._chunks_by_id[chunk_id].document_name)
                if chunk_id in self._chunks_by_id
                else None
            ),
            query_region=parsed.region,
            limit=result_limit,
        )
        semantic_score = {UUID(str(hit.chunk_id)): hit.score for hit in semantic_hits}
        keyword_score = {UUID(str(hit.chunk_id)): hit.score for hit in keyword_hits}
        results: list[KnowledgeSearchResult] = []
        for hit in ranked:
            chunk = self._chunks_by_id.get(hit.chunk_id)
            record = self._indexed.get(hit.document_id)
            if chunk is None or record is None or record[0].status is not DocumentStatus.ready:
                continue
            results.append(KnowledgeSearchResult(
                content=chunk.content,
                chunk_type=chunk.chunk_type,
                score=semantic_score.get(hit.chunk_id, keyword_score.get(hit.chunk_id, 0.0)),
                source=SourceLocation(
                    document_name=chunk.document_name,
                    page=chunk.source_page,
                    section=chunk.source_section,
                    table=chunk.source_table,
                    figure=chunk.source_figure,
                ),
                matched_by=hit.matched_by,
            ))
        return results


async def _safe_metric(judge: Judge, name: str, *args: Any) -> float | None:
    try:
        return await getattr(judge, name)(*args)
    except (ExternalServiceUnavailable, ValueError, TypeError):
        return None


async def evaluate_item(
    judge: Judge, polisher: KnowledgePolisher, retrieval: RetrievalService, item: dict[str, str]
) -> dict[str, Any]:
    question = item["question"]
    metrics: dict[str, Any] = {
        "id": item["id"],
        "question": question,
        "retrieval_skipped": False,
        "answer": None,
    }
    try:
        results = await asyncio.to_thread(retrieval.retrieve, question)
    except Exception:
        metrics["retrieval_skipped"] = True
        results = []
    metrics["retrieved_count"] = len(results)
    metrics["retrieved_preview"] = [result.content[:60] for result in results[:5]]

    answer = None
    if results:
        try:
            answer = await polisher.polish(question, results)
        except ExternalServiceUnavailable:
            answer = None
    metrics["answer"] = answer

    if answer is None:
        metrics["faithfulness"] = None
        metrics["answer_relevance"] = None
    else:
        metrics["faithfulness"] = await _safe_metric(judge, "faithfulness", question, answer, results)
        metrics["answer_relevance"] = await _safe_metric(judge, "answer_relevance", question, answer)
    metrics["context_recall"] = await _safe_metric(
        judge, "context_recall", question, item["reference_answer"], results
    )
    metrics["context_precision"] = await _safe_metric(judge, "context_precision", question, results)
    return metrics


def _aggregate(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    for key in METRIC_KEYS:
        values = [item[key] for item in results if isinstance(item.get(key), (int, float))]
        aggregated[key] = {
            "count": len(values),
            "mean": sum(values) / len(values) if values else None,
        }
    return aggregated


def write_report(results: list[dict[str, Any]], aggregated: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# 知识检索 RAG 评估报告",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"题目数：{len(results)}",
        "",
        "## 总均分",
    ]
    for key in METRIC_KEYS:
        info = aggregated[key]
        mean = f"{info['mean']:.3f}" if info["mean"] is not None else "n/a"
        lines.append(f"- **{key}**：{mean}（{info['count']}/{len(results)} 题有效）")
    lines.append("")
    lines.append("## 每题明细")
    for item in results:
        lines.append(f"### {item['id']} · {item['question']}")
        lines.append(f"- 检索状态：{'跳过' if item['retrieval_skipped'] else '完成'}，检索到 {item['retrieved_count']} 块")
        for key in METRIC_KEYS:
            value = item[key]
            text = f"{value:.3f}" if isinstance(value, (int, float)) else "n/a"
            lines.append(f"  - {key}：{text}")
        if item.get("retrieved_preview"):
            lines.append(f"  - 检索块预览：{item['retrieved_preview'][:3]}")
        if item.get("answer"):
            lines.append(f"  - 回答摘要：{item['answer'][:100].replace(chr(10), ' ')}")
        lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    settings = Settings()
    retrieval = RetrievalService(settings)
    judge = Judge(DeepSeekClient(settings.deepseek_api_key, model=settings.deepseek_model))
    polisher = KnowledgePolisher(DeepSeekClient(settings.deepseek_api_key, model=settings.deepseek_model))
    golden = _load_golden()
    results = []
    for index, item in enumerate(golden, 1):
        print(f"[{index}/{len(golden)}] 评估 {item['id']}: {item['question']}")
        results.append(await evaluate_item(judge, polisher, retrieval, item))
    aggregated = _aggregate(results)
    write_report(results, aggregated)
    print(f"报告已写入 {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **步骤 2：语法与导入验证**

运行：`cd backend && python -c "import ast; ast.parse(open('evaluation/evaluate.py',encoding='utf-8').read()); print('语法 OK')"`
预期：输出「语法 OK」。

- [ ] **步骤 3：对 1 题做冒烟运行**

把 `golden_set.json` 临时截断为 1 题，运行：`cd backend && python -m evaluation.evaluate`
预期：日志打印 1/1，产出 `backend/evaluation/report.md`，含四项指标分数或 `n/a`。恢复完整 golden 集。

- [ ] **步骤 4：提交**

```bash
git add backend/evaluation/evaluate.py
git commit -m "feat: RAG 评估主脚本（检索复刻 + 生成 + 判定 + 报告）"
```

---

## 任务 4：运行完整评估并产出报告

**文件：**
- 生成 `backend/evaluation/report.md`

- [ ] **步骤 1：运行完整评估**

运行：`cd backend && python -m evaluation.evaluate`
预期：约 16 题逐题评估，产出 `report.md`。

- [ ] **步骤 2：核对报告**

检查 `report.md`：四项指标均有总均分；每题明细含指标分数；跳过/`n/a` 项明确标注（不能静默缺失）。

- [ ] **步骤 3：提交报告**

```bash
git add backend/evaluation/report.md
git commit -m "docs: RAG 评估报告（四指标 + 每题明细）"
```

---

## 自检

- **规格覆盖度：** 规格要求四项指标、DeepSeek 裁判、可复用脚本、约 16 题 golden 集、`report.md`、错误降级——计划的任务 1（golden 集）、任务 2（judge 四项）、任务 3（evaluate 主流程）、任务 4（运行报告）逐一覆盖。✓
- **占位符扫描：** 无「待定/TODO」；每步含完整代码与命令。golden 集内容在任务 1 步骤 1-2 通过读取文档构造，不是占位符。✓
- **类型一致性：** `Judge` 四项方法签名（faithfulness/context_recall 收 `Sequence`、context_precision 收 question+results、answer_relevance 收 question+answer）与 evaluate_item 的调用一致；`_parse_verdict_lines` 返回 `(int, bool, str)`、`_parse_pair_lines` 返回 `(int, bool)`，测试与 judge 方法均按此解析；`_context_precision(relevant_positions, total)` 签名在测试与 judge 中一致。✓
- **环境假设：** 运行需 `backend/` 为 CWD（`app` 与 `evaluation` 可导入）、BGE 模型与 DeepSeek 密钥已配置（均已核实）。✓
