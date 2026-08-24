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
    # 与 app/main.py 一致，DeepSeek 调用统一使用 settings.deepseek_timeout_seconds（60s）超时，
    # 避免默认 10s 读超时在 DeepSeek 首字节延迟较长时误判为服务不可用。
    judge = Judge(DeepSeekClient(
        settings.deepseek_api_key, model=settings.deepseek_model,
        min_response_length=1, timeout=settings.deepseek_timeout_seconds,
    ))
    polisher = KnowledgePolisher(DeepSeekClient(
        settings.deepseek_api_key, model=settings.deepseek_model,
        timeout=settings.deepseek_timeout_seconds,
    ))
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
