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
from evaluation.judge import Judge

BASE_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = BASE_DIR / "golden_set.json"
REPORT_PATH = BASE_DIR / "report.md"
METRIC_KEYS = ("faithfulness", "context_recall", "context_precision", "answer_relevance")


def _load_golden() -> list[dict[str, str]]:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError("golden_set.json 顶层必须是非空数组")
    ids: set[str] = set()
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise ValueError(f"golden_set.json 第 {index} 项必须是对象")
        for field in ("id", "question", "reference_answer"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"golden_set.json 第 {index} 项的 {field} 必须是非空字符串")
        item_id = item["id"]
        if item_id in ids:
            raise ValueError("golden_set.json 的 id 不得重复")
        ids.add(item_id)
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
    def retrieve(
        self, query: str, *, document_ids: tuple[UUID, ...] = ()
    ) -> list[KnowledgeSearchResult]:
        query = query.strip()
        if not query:
            raise ValueError("检索内容不能为空")
        result_limit = self.settings.knowledge_search_result_limit
        fetch_limit = result_limit * 3
        ready_records = self.document_store.list_documents()
        if document_ids:
            wanted = {str(document_id) for document_id in document_ids}
            ready_ids = {
                record.id
                for record in ready_records
                if record.status is DocumentStatus.ready and str(record.id) in wanted
            }
        else:
            ready_ids = {
                record.id
                for record in ready_records
                if record.status is DocumentStatus.ready
            }
        indexed = self.document_store.get_documents_with_chunks(ready_ids)
        chunks_by_id: dict[UUID, Any] = {
            UUID(str(chunk.id)): chunk
            for _record, chunks in indexed.values()
            for chunk in chunks.values()
        }
        semantic_hits = self.chroma.query(
            query, document_ids=document_ids, limit=fetch_limit
        )
        parsed = parse_query(query)
        keyword_hits = search_chunks(
            list(chunks_by_id.values()), parsed,
            document_ids=document_ids, limit=fetch_limit,
        )
        ranked = merge_ranked_hits(
            semantic_hits,
            keyword_hits,
            region_of_chunk=lambda chunk_id: (
                region_from_document_name(chunks_by_id[chunk_id].document_name)
                if chunk_id in chunks_by_id
                else None
            ),
            query_region=parsed.region,
            limit=result_limit,
        )
        semantic_score = {UUID(str(hit.chunk_id)): hit.score for hit in semantic_hits}
        keyword_score = {UUID(str(hit.chunk_id)): hit.score for hit in keyword_hits}
        results: list[KnowledgeSearchResult] = []
        for hit in ranked:
            chunk = chunks_by_id.get(hit.chunk_id)
            record = indexed.get(hit.document_id)
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
    except Exception:
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
        metrics.update({
            "retrieval_skipped": True,
            "retrieved_count": 0,
            "retrieved_preview": [],
            "faithfulness": None,
            "context_recall": None,
            "context_precision": None,
            "answer_relevance": None,
        })
        return metrics
    metrics["retrieved_count"] = len(results)
    metrics["retrieved_preview"] = [result.content[:60] for result in results[:5]]

    answer = None
    if results:
        try:
            answer = await polisher.polish(question, results)
        except Exception:
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
            lines.append(f"  - 检索块预览：{item['retrieved_preview']}")
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
        settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        max_tokens=settings.deepseek_max_tokens,
        min_response_length=1,
        timeout=settings.deepseek_timeout_seconds,
    ))
    polisher = KnowledgePolisher(DeepSeekClient(
        settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        max_tokens=settings.deepseek_max_tokens,
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
