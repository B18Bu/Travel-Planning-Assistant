from __future__ import annotations

import asyncio
import mimetypes
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.models.documents import DocumentStatus, PDF_MEDIA_TYPE
from app.services.document_extractors import (
    chunk_extracted_content,
    extract_docx,
    extract_pdf_with_pymupdf,
)
from app.services.document_store import DocumentNotFound, DocumentStore


class DocumentProcessor:
    """单进程文档处理编排；原文块只保存到 DocumentStore。"""

    def __init__(
        self,
        store: DocumentStore,
        mineru,
        qwen_vl,
        chroma,
        *,
        mineru_poll_attempts: int = 3,
    ) -> None:
        self.store = store
        self.mineru = mineru
        self.qwen_vl = qwen_vl
        self.chroma = chroma
        self.mineru_poll_attempts = mineru_poll_attempts
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}

    @staticmethod
    def document_key(document_id: UUID | str) -> str:
        return str(UUID(str(document_id)))

    @asynccontextmanager
    async def lock_for(self, document_id: UUID | str):
        key = self.document_key(document_id)
        lock, references = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = (lock, references + 1)
        try:
            async with lock:
                yield
        finally:
            current_lock, current_references = self._locks[key]
            if current_references == 1:
                del self._locks[key]
            else:
                self._locks[key] = (current_lock, current_references - 1)

    async def process(self, document_id: UUID | str) -> None:
        document_id = UUID(self.document_key(document_id))
        async with self.lock_for(document_id):
            try:
                record = self.store.get_document(document_id)
            except DocumentNotFound:
                return
            if record.status is DocumentStatus.ready:
                return
            if record.status is DocumentStatus.processing:
                try:
                    await asyncio.to_thread(self.chroma.delete_document, document_id)
                except Exception:
                    self.store.mark_vector_cleanup_required(document_id)
                    return
                self.store.clear_processing_state(document_id)
            self.store.mark_processing(document_id)
            try:
                extracted = await self._extract(record.id, record.media_type)
                chunks = await asyncio.to_thread(
                    chunk_extracted_content,
                    record.id,
                    record.filename,
                    await self._with_chart_ocr(record.id, extracted),
                )
                if not chunks:
                    raise ValueError("文档未提取到可检索内容")
                await asyncio.to_thread(self.chroma.upsert, chunks, ready=False)
                counts = {kind: sum(chunk.chunk_type == kind for chunk in chunks) for kind in ("text", "table", "chart_ocr")}
                ready = record.model_copy(
                    update={
                        "status": DocumentStatus.ready,
                        "updated_at": datetime.now(timezone.utc),
                        "chunk_count": len(chunks),
                        "text_chunk_count": counts["text"],
                        "table_chunk_count": counts["table"],
                        "chart_ocr_chunk_count": counts["chart_ocr"],
                    }
                )
                self.store.save_processed_document(ready, chunks)
                await asyncio.to_thread(self.chroma.mark_document_ready, document_id)
            except Exception:
                try:
                    await asyncio.to_thread(self.chroma.delete_document, document_id)
                except Exception:
                    # 保持处理记录与持久清理意图，使后续任务或删除操作可重试补偿删除。
                    self.store.mark_vector_cleanup_required(document_id)
                    return
                self.store.mark_failed(document_id, "文档内容无法处理")

    async def _extract(self, document_id: UUID, media_type: str) -> list[dict]:
        path = self.store.upload_path(document_id, media_type)
        extracted_dir = self.store.extracted_dir / str(document_id)
        if media_type != PDF_MEDIA_TYPE:
            return await asyncio.to_thread(extract_docx, path, extracted_dir)
        return await self._extract_pdf(document_id, path, extracted_dir)

    async def _extract_pdf(self, document_id: UUID, path: Path, extracted_dir: Path) -> list[dict]:
        """v1 不创建外发 URL，PDF 始终在本地以 PyMuPDF 提取。"""
        return await asyncio.to_thread(extract_pdf_with_pymupdf, path, extracted_dir)

    def _safe_image_path(self, document_id: UUID, image_path: object) -> Path | None:
        """仅允许当前文档提取目录内的相对图片路径。"""
        if not isinstance(image_path, str) or not image_path or ":" in image_path or "\\" in image_path:
            return None
        root = (self.store.extracted_dir / str(document_id)).resolve()
        candidate = (root / image_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate

    async def _with_chart_ocr(self, document_id: UUID, extracted: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for item in extracted:
            if item.get("chunk_type") != "chart_ocr":
                normalized.append(item)
                continue
            image_path = item.get("image_path")
            safe_path = self._safe_image_path(document_id, image_path)
            if safe_path is None:
                continue
            image_bytes = item.get("image_bytes")
            if not isinstance(image_bytes, bytes):
                try:
                    image_bytes = safe_path.read_bytes()
                except OSError:
                    continue
            media_type = mimetypes.guess_type(image_path or "")[0]
            if not isinstance(image_bytes, bytes) or media_type not in {"image/png", "image/jpeg", "image/webp"}:
                continue
            try:
                result = await self.qwen_vl.recognize_chart(image_bytes, media_type)
            except Exception:
                # 单张图片 OCR 失败仅跳过该图，正文与表格块仍需正常入库。
                continue
            text = result.get("text") if isinstance(result, dict) else None
            if isinstance(text, str) and text.strip():
                normalized.append({key: value for key, value in item.items() if key != "image_bytes"} | {"content": text.strip()})
        return normalized
