from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, Response, UploadFile

from app.models.documents import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    DocumentBatchUploadItem,
    DocumentBatchUploadResponse,
    DocumentChunk,
    DocumentRecord,
    DocumentStatus,
    FeedbackCount,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeStats,
    QueryRecord,
    RatingRequest,
    SourceLocation,
)
from app.services.document_store import DocumentNotFound
from app.services.keyword_search import (
    merge_ranked_hits,
    parse_query,
    region_from_document_name,
    search_chunks,
)
from app.services.query_record_store import QueryRecordNotFound
from app.services.resilience import ExternalServiceUnavailable


router = APIRouter(prefix="/api")
_ALLOWED_MEDIA_TYPES = {PDF_MEDIA_TYPE, DOCX_MEDIA_TYPE}
# 混合检索最终返回的结果数；语义与关键词各多拉取三倍候选，供城市过滤与融合留出余量。


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="文档不存在")


def _normalized_chunk_content(content: str) -> str:
    return " ".join(content.split()).casefold()


def _deduplicate_ranked_hits(ranked, chunks_by_id, limit: int):
    selected = []
    seen = set()
    for hit in ranked:
        chunk = chunks_by_id.get(hit.chunk_id)
        if chunk is None:
            continue
        fingerprint = _normalized_chunk_content(chunk.content)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        selected.append(hit)
        if len(selected) == limit:
            break
    return tuple(selected)


def _empty_reason(ready_records, query_region: str | None, results) -> str | None:
    if results:
        return None
    if not ready_records:
        return "no_ready_documents"
    if query_region is not None and not any(
        region_from_document_name(record.filename) == query_region
        for record in ready_records
    ):
        return "no_region_documents"
    return "no_matching_chunks"


def _valid_signature(content: bytes, media_type: str) -> bool:
    if media_type == PDF_MEDIA_TYPE:
        return content.startswith(b"%PDF-")
    return content.startswith(b"PK\x03\x04")


def _record_for_upload(filename: str, media_type: str) -> DocumentRecord:
    return DocumentRecord(
        id=str(uuid4()), filename=filename, media_type=media_type,
        status=DocumentStatus.pending, created_at=datetime.now(timezone.utc),
    )


async def _read_and_validate_upload(
    file: UploadFile, max_upload_bytes: int
) -> tuple[DocumentRecord, bytes]:
    filename = file.filename or ""
    media_type = file.content_type or ""
    if media_type not in _ALLOWED_MEDIA_TYPES or Path(filename).suffix.lower() not in {".pdf", ".docx"}:
        raise HTTPException(status_code=422, detail="仅支持 Word 或 PDF 文档")
    expected_suffix = ".pdf" if media_type == PDF_MEDIA_TYPE else ".docx"
    if Path(filename).suffix.lower() != expected_suffix:
        raise HTTPException(status_code=422, detail="文件名与文档类型不匹配")
    content = await file.read(max_upload_bytes + 1)
    if len(content) > max_upload_bytes:
        raise HTTPException(status_code=422, detail="文档文件超过大小限制")
    if not _valid_signature(content, media_type):
        raise HTTPException(status_code=422, detail="文档文件内容无效")
    try:
        return _record_for_upload(filename, media_type), content
    except ValueError:
        raise HTTPException(status_code=422, detail="文档文件名无效") from None


async def _accept_upload(request: Request, record: DocumentRecord, content: bytes) -> None:
    if request.app.state.document_processor is None:
        raise HTTPException(status_code=503, detail="文档处理服务暂不可用")
    await asyncio.to_thread(request.app.state.document_store.create_document, record, content)


async def _process_batch_documents(processor, document_ids: tuple[UUID, ...]) -> None:
    """并发处理批量上传中已接收的文档，单项异常不影响其余任务。"""

    await asyncio.gather(
        *(processor.process(document_id) for document_id in document_ids),
        return_exceptions=True,
    )


@router.post("/documents", status_code=202, response_model=DocumentRecord)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> DocumentRecord:
    record, content = await _read_and_validate_upload(
        file, request.app.state.settings.document_max_upload_bytes
    )
    await _accept_upload(request, record, content)
    background_tasks.add_task(request.app.state.document_processor.process, record.id)
    return record


@router.post(
    "/documents/batch",
    status_code=202,
    response_model=DocumentBatchUploadResponse,
    responses={422: {"description": "批量上传请求或文件校验失败"}, 503: {"description": "文档服务暂不可用"}},
)
async def upload_documents_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] | None = File(None),
) -> DocumentBatchUploadResponse:
    max_files = request.app.state.settings.document_batch_max_files
    if not files:
        raise HTTPException(status_code=422, detail="请至少上传一份文档")
    if len(files) > max_files:
        raise HTTPException(status_code=422, detail="文档数量超过批量上传限制")

    items = []
    accepted_document_ids = []
    for index, file in enumerate(files, start=1):
        try:
            record, content = await _read_and_validate_upload(
                file, request.app.state.settings.document_max_upload_bytes
            )
        except HTTPException as error:
            items.append(DocumentBatchUploadItem(
                index=index, status="rejected", error=error.detail
            ))
            continue
        except Exception:
            items.append(DocumentBatchUploadItem(
                index=index, status="unavailable", error="文档上传服务暂不可用"
            ))
            continue
        try:
            await _accept_upload(request, record, content)
        except HTTPException:
            items.append(DocumentBatchUploadItem(
                index=index, status="unavailable", error="文档处理服务暂不可用"
            ))
            continue
        except Exception:
            items.append(DocumentBatchUploadItem(
                index=index, status="unavailable", error="文档存储服务暂不可用"
            ))
            continue
        accepted_document_ids.append(record.id)
        items.append(DocumentBatchUploadItem(index=index, status="accepted", document=record))

    if accepted_document_ids:
        background_tasks.add_task(
            _process_batch_documents,
            request.app.state.document_processor,
            tuple(accepted_document_ids),
        )
    status_code = 202 if any(item.status == "accepted" for item in items) else (
        503 if any(item.status == "unavailable" for item in items) else 422
    )
    return Response(
        content=DocumentBatchUploadResponse(items=tuple(items)).model_dump_json(exclude_none=True),
        status_code=status_code,
        media_type="application/json",
    )


@router.get("/documents", response_model=tuple[DocumentRecord, ...])
async def list_documents(request: Request) -> tuple[DocumentRecord, ...]:
    return await asyncio.to_thread(request.app.state.document_store.list_documents)


@router.get("/documents/{document_id}", response_model=DocumentRecord)
async def get_document(document_id: UUID, request: Request) -> DocumentRecord:
    try:
        return await asyncio.to_thread(
            request.app.state.document_store.get_document, document_id
        )
    except DocumentNotFound:
        raise _not_found() from None


@router.get("/documents/{document_id}/chunks", response_model=tuple[DocumentChunk, ...])
async def list_document_chunks(document_id: UUID, request: Request) -> tuple[DocumentChunk, ...]:
    try:
        return await asyncio.to_thread(
            request.app.state.document_store.get_chunks, document_id
        )
    except DocumentNotFound:
        raise _not_found() from None


@router.delete("/documents/{document_id}", status_code=204, response_class=Response)
async def delete_document(document_id: UUID, request: Request) -> Response:
    store = request.app.state.document_store
    chroma = request.app.state.chroma_store
    processor = request.app.state.document_processor

    def restore_from_store(restore_id: UUID) -> None:
        chunks = store.get_chunks(restore_id)
        if chunks:
            chroma.upsert(chunks)

    if chroma is None:
        raise HTTPException(status_code=503, detail="文档删除暂不可用")
    lock = processor.lock_for(document_id) if processor is not None else None
    try:
        if lock is None:
            await asyncio.to_thread(
                store.delete_document, document_id, chroma.delete_document, restore_from_store
            )
        else:
            async with lock:
                await asyncio.to_thread(
                    store.delete_document, document_id, chroma.delete_document, restore_from_store
                )
    except DocumentNotFound:
        raise _not_found() from None
    except Exception:
        raise HTTPException(status_code=503, detail="文档删除暂不可用") from None
    return Response(status_code=204)


@router.post("/knowledge-search", response_model=KnowledgeSearchResponse)
async def search_knowledge(payload: KnowledgeSearchRequest, request: Request) -> KnowledgeSearchResponse:
    store = request.app.state.document_store
    if request.app.state.chroma_store is None:
        raise HTTPException(status_code=503, detail="知识检索服务暂不可用")
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="检索内容不能为空")
    result_limit = request.app.state.settings.knowledge_search_result_limit
    fetch_limit = result_limit * 3
    try:
        semantic_hits = await asyncio.to_thread(
            request.app.state.chroma_store.query,
            query,
            document_ids=payload.document_ids,
            limit=fetch_limit,
        )
        parsed = parse_query(query)
        records = await asyncio.to_thread(store.list_documents)
        if payload.document_ids:
            wanted = {str(document_id) for document_id in payload.document_ids}
            ready_records = [
                record for record in records
                if record.status is DocumentStatus.ready and str(record.id) in wanted
            ]
        else:
            ready_records = [
                record for record in records
                if record.status is DocumentStatus.ready
            ]
        ready_ids = {record.id for record in ready_records}
        indexed = await asyncio.to_thread(store.get_documents_with_chunks, ready_ids)
        chunks_by_id = {
            UUID(str(chunk.id)): chunk
            for _record, chunks in indexed.values()
            for chunk in chunks.values()
        }
        keyword_hits = search_chunks(
            list(chunks_by_id.values()), parsed,
            document_ids=payload.document_ids, limit=fetch_limit,
        )
        ranked = merge_ranked_hits(
            semantic_hits,
            keyword_hits,
            region_of_chunk=lambda chunk_id: (
                region_from_document_name(chunks_by_id[chunk_id].document_name)
                if chunk_id in chunks_by_id else None
            ),
            query_region=parsed.region,
            limit=fetch_limit,
        )
        ranked = _deduplicate_ranked_hits(ranked, chunks_by_id, result_limit)
    except (ExternalServiceUnavailable, RuntimeError, ValueError):
        raise HTTPException(status_code=503, detail="知识检索服务暂不可用") from None

    semantic_score = {UUID(str(hit.chunk_id)): hit.score for hit in semantic_hits}
    keyword_score = {UUID(str(hit.chunk_id)): hit.score for hit in keyword_hits}
    results = []
    for hit in ranked:
        chunk = chunks_by_id.get(hit.chunk_id)
        if chunk is None:
            continue
        document = indexed.get(hit.document_id)
        if document is None:
            continue
        record, _chunks = document
        if record.status is not DocumentStatus.ready:
            continue
        results.append(KnowledgeSearchResult(
            content=chunk.content, chunk_type=chunk.chunk_type,
            score=semantic_score.get(hit.chunk_id, keyword_score.get(hit.chunk_id, 0.0)),
            source=SourceLocation(document_name=chunk.document_name, page=chunk.source_page, section=chunk.source_section, table=chunk.source_table, figure=chunk.source_figure),
            matched_by=hit.matched_by,
        ))

    answer: str | None = None
    answer_status = "none"
    if payload.generate_markdown and results:
        polisher = request.app.state.knowledge_polisher
        if polisher is None:
            answer_status = "unavailable"
        else:
            answer = await polisher.polish(query, results)
            answer_status = "generated" if answer is not None else "unavailable"

    record_store = request.app.state.query_record_store
    record_id: str | None = None
    if results and record_store is not None:
        try:
            if payload.record_id is not None:
                try:
                    await asyncio.to_thread(
                        record_store.update, payload.record_id,
                        results=tuple(results), answer=answer, answer_status=answer_status,
                    )
                    record_id = str(payload.record_id)
                except QueryRecordNotFound:
                    record_id = await asyncio.to_thread(
                        _create_query_record, record_store,
                        query, answer, answer_status, tuple(results),
                    )
            else:
                record_id = await asyncio.to_thread(
                    _create_query_record, record_store,
                    query, answer, answer_status, tuple(results),
                )
        except Exception:
            # 记录持久化失败不阻断检索结果返回。
            pass
    return KnowledgeSearchResponse(
        query=query, results=tuple(results), answer=answer,
        answer_status=answer_status, record_id=record_id,
        empty_reason=_empty_reason(ready_records, parsed.region, results),
    )


def _create_query_record(
    store, query: str, answer: str | None, answer_status: str, results: tuple
) -> str:
    record = QueryRecord(
        id=str(uuid4()), query=query, created_at=datetime.now(timezone.utc),
        answer=answer, answer_status=answer_status, results=results,
    )
    store.add(record)
    return record.id


@router.get("/knowledge-records", response_model=tuple[QueryRecord, ...])
async def list_knowledge_records(request: Request) -> tuple[QueryRecord, ...]:
    store = request.app.state.query_record_store
    if store is None:
        raise HTTPException(status_code=503, detail="查询记录服务暂不可用")
    return await asyncio.to_thread(store.list)


@router.delete("/knowledge-records/{record_id}", status_code=204, response_class=Response)
async def delete_knowledge_record(record_id: UUID, request: Request) -> Response:
    store = request.app.state.query_record_store
    if store is None:
        raise HTTPException(status_code=503, detail="查询记录服务暂不可用")
    try:
        await asyncio.to_thread(store.delete, record_id)
    except QueryRecordNotFound:
        raise HTTPException(status_code=404, detail="查询记录不存在") from None
    return Response(status_code=204)


@router.delete("/knowledge-records", status_code=204, response_class=Response)
async def clear_knowledge_records(request: Request) -> Response:
    store = request.app.state.query_record_store
    if store is None:
        raise HTTPException(status_code=503, detail="查询记录服务暂不可用")
    await asyncio.to_thread(store.clear)
    return Response(status_code=204)


@router.post("/knowledge-records/{record_id}/rating", response_model=QueryRecord)
async def rate_knowledge_record(
    record_id: UUID, payload: RatingRequest, request: Request
) -> QueryRecord:
    store = request.app.state.query_record_store
    if store is None:
        raise HTTPException(status_code=503, detail="查询记录服务暂不可用")
    try:
        return await asyncio.to_thread(store.set_rating, record_id, payload.rating)
    except QueryRecordNotFound:
        raise HTTPException(status_code=404, detail="查询记录不存在") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="评价无效") from None


@router.get("/knowledge-stats", response_model=KnowledgeStats)
async def get_knowledge_stats(request: Request) -> KnowledgeStats:
    store = request.app.state.query_record_store
    if store is None:
        raise HTTPException(status_code=503, detail="查询记录服务暂不可用")
    records = await asyncio.to_thread(store.list)
    return _compute_stats(records)


def _compute_stats(records: tuple[QueryRecord, ...]) -> KnowledgeStats:
    rated = tuple(record for record in records if record.rating is not None)
    like_count = sum(1 for record in rated if record.rating == "like")
    total = len(rated)
    good_rate = like_count / total if total else 0.0
    ai_rated = tuple(
        record for record in rated if record.answer_status == "generated"
    )
    ai_like = sum(1 for record in ai_rated if record.rating == "like")
    ai_good_rate = ai_like / len(ai_rated) if ai_rated else 0.0
    ai_dislike = len(ai_rated) - ai_like
    document_pairs = [
        (document_name, record.rating)
        for record in rated
        for document_name in {result.source.document_name for result in record.results}
    ]
    region_pairs = []
    for record in rated:
        parsed = parse_query(record.query)
        region_pairs.append((parsed.region or parsed.city or "未知地区", record.rating))
    return KnowledgeStats(
        total_feedback=total,
        like_count=like_count,
        dislike_count=total - like_count,
        good_rate=good_rate,
        ai_good_rate=ai_good_rate,
        ai_like_count=ai_like,
        ai_dislike_count=ai_dislike,
        by_document=_aggregate_feedback(document_pairs),
        by_region=_aggregate_feedback(region_pairs),
    )


def _aggregate_feedback(
    pairs: Iterable[tuple[str, str | None]]
) -> tuple[FeedbackCount, ...]:
    counts: dict[str, list[int]] = {}
    for name, rating in pairs:
        entry = counts.setdefault(name, [0, 0])
        entry[0 if rating == "like" else 1] += 1
    items = [
        FeedbackCount(name=name, like=entry[0], dislike=entry[1], total=entry[0] + entry[1])
        for name, entry in sorted(counts.items(), key=lambda item: item[1][0] + item[1][1], reverse=True)
    ]
    return tuple(items)
