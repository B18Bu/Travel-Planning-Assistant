from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from threading import RLock
from typing import Callable
from uuid import UUID

from app.models.documents import DocumentChunk, DocumentRecord, DocumentStatus


class DocumentNotFound(KeyError):
    """文档不存在。"""


class DocumentStore:
    """以 documents.json 为唯一元数据与原文块来源的单进程文档存储。"""

    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self.uploads_dir = self.data_dir / "uploads"
        self.extracted_dir = self.data_dir / "extracted"
        self.chroma_dir = self.data_dir / "chroma"
        self.metadata_path = self.data_dir / "documents.json"
        self._lock = RLock()
        for directory in (self.uploads_dir, self.extracted_dir, self.chroma_dir):
            directory.mkdir(parents=True, exist_ok=True)
        if not self.metadata_path.exists():
            self._write_state({"documents": [], "chunks": [], "pending_deletion": [], "pending_cleanup": [], "processing_state": {}})

    def create_document(self, record: DocumentRecord, content: bytes) -> DocumentRecord:
        with self._lock:
            state = self._read_state()
            if self._find_document(state, record.id) is not None:
                raise ValueError("文档已存在")
            upload_path = self.upload_path(record.id, record.media_type)
            temporary_path = upload_path.with_suffix(f"{upload_path.suffix}.tmp")
            try:
                with temporary_path.open("wb") as file:
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary_path, upload_path)
                state["documents"].append(record.model_dump(mode="json"))
                self._write_state(state)
            except Exception:
                for path in (temporary_path, upload_path):
                    if path.exists():
                        path.unlink()
                raise
        return record

    def get_document(self, document_id: UUID) -> DocumentRecord:
        with self._lock:
            item = self._find_document(self._read_state(), document_id)
            if item is None:
                raise DocumentNotFound(str(document_id))
            return DocumentRecord.model_validate(item)

    def list_documents(self) -> tuple[DocumentRecord, ...]:
        with self._lock:
            return tuple(
                DocumentRecord.model_validate(item)
                for item in self._read_state()["documents"]
            )

    def get_chunks(self, document_id: UUID) -> tuple[DocumentChunk, ...]:
        with self._lock:
            state = self._read_state()
            if self._find_document(state, document_id) is None:
                raise DocumentNotFound(str(document_id))
            return tuple(
                DocumentChunk.model_validate(item)
                for item in state["chunks"]
                if item["document_id"] == str(document_id)
            )

    def get_documents_with_chunks(
        self, document_ids: set[UUID | str]
    ) -> dict[UUID, tuple[DocumentRecord, dict[UUID, DocumentChunk]]]:
        """单次读取 JSON，按文档与块 ID 返回受控原文索引。"""
        with self._lock:
            state = self._read_state()
            wanted = {str(document_id) for document_id in document_ids}
            records = {
                UUID(item["id"]): DocumentRecord.model_validate(item)
                for item in state["documents"]
                if item["id"] in wanted
            }
            result = {document_id: (record, {}) for document_id, record in records.items()}
            for item in state["chunks"]:
                document_id = item["document_id"]
                if document_id in wanted:
                    chunk = DocumentChunk.model_validate(item)
                    result[UUID(document_id)][1][UUID(str(chunk.id))] = chunk
            return result

    def mark_processing(self, document_id: UUID) -> DocumentRecord:
        """将待处理文档转为处理中；重复调用保持幂等。"""
        return self._replace_document_status(document_id, "processing")

    def mark_failed(self, document_id: UUID, message: str) -> DocumentRecord:
        """以受控摘要记录处理失败，并清空块计数。"""
        return self._replace_document_status(document_id, "failed", failure_message=message)

    def _replace_document_status(
        self, document_id: UUID, status: str, failure_message: str | None = None
    ) -> DocumentRecord:
        from datetime import datetime, timezone

        with self._lock:
            state = self._read_state()
            index = self._find_document_index(state, document_id)
            if index is None:
                raise DocumentNotFound(str(document_id))
            current = DocumentRecord.model_validate(state["documents"][index])
            if current.status.value == "ready" and status == "processing":
                return current
            updated = current.model_copy(
                update={
                    "status": DocumentStatus(status),
                    "updated_at": datetime.now(timezone.utc),
                    "failure_message": failure_message,
                    "processing_message": None,
                    "chunk_count": 0,
                    "text_chunk_count": 0,
                    "table_chunk_count": 0,
                    "chart_ocr_chunk_count": 0,
                }
            )
            state["documents"][index] = updated.model_dump(mode="json")
            if status == "failed":
                state["processing_state"].pop(str(document_id), None)
                state["chunks"] = [
                    item for item in state["chunks"] if item["document_id"] != str(document_id)
                ]
            self._write_state(state)
            return updated

    def get_processing_state(self, document_id: UUID) -> dict[str, str] | None:
        with self._lock:
            state = self._read_state()
            value = state["processing_state"].get(str(document_id))
            return dict(value) if value is not None else None

    def save_processing_state(self, document_id: UUID, task_id: str, phase: str) -> None:
        if phase not in {"submitted", "polling", "vector_cleanup"}:
            raise ValueError("处理阶段无效")
        with self._lock:
            state = self._read_state()
            if self._find_document(state, document_id) is None:
                raise DocumentNotFound(str(document_id))
            state["processing_state"][str(document_id)] = {"task_id": task_id, "phase": phase}
            self._write_state(state)

    def mark_vector_cleanup_required(self, document_id: UUID) -> None:
        """持久标记可能存在部分向量，下一次处理或删除必须先清理。"""
        with self._lock:
            state = self._read_state()
            if self._find_document(state, document_id) is None:
                raise DocumentNotFound(str(document_id))
            state["processing_state"][str(document_id)] = {
                "task_id": "",
                "phase": "vector_cleanup",
            }
            index = self._find_document_index(state, document_id)
            record = DocumentRecord.model_validate(state["documents"][index])
            state["documents"][index] = record.model_copy(
                update={
                    "status": DocumentStatus.processing,
                    "processing_message": "向量清理待重试",
                    "chunk_count": 0,
                    "text_chunk_count": 0,
                    "table_chunk_count": 0,
                    "chart_ocr_chunk_count": 0,
                }
            ).model_dump(mode="json")
            self._write_state(state)

    def clear_processing_state(self, document_id: UUID) -> None:
        with self._lock:
            state = self._read_state()
            if state["processing_state"].pop(str(document_id), None) is not None:
                index = self._find_document_index(state, document_id)
                record = DocumentRecord.model_validate(state["documents"][index])
                state["documents"][index] = record.model_copy(
                    update={"processing_message": None}
                ).model_dump(mode="json")
                self._write_state(state)

    def save_processed_document(
        self, record: DocumentRecord, chunks: list[DocumentChunk]
    ) -> DocumentRecord:
        if record.status.value != "ready":
            raise ValueError("仅 ready 文档可保存处理结果")
        if any(chunk.document_id != record.id for chunk in chunks):
            raise ValueError("块不属于文档")
        counts = {"text": 0, "table": 0, "chart_ocr": 0}
        for chunk in chunks:
            counts[chunk.chunk_type] += 1
        if (record.chunk_count, record.text_chunk_count, record.table_chunk_count, record.chart_ocr_chunk_count) != (len(chunks), counts["text"], counts["table"], counts["chart_ocr"]):
            raise ValueError("文档块统计不一致")
        with self._lock:
            state = self._read_state()
            index = self._find_document_index(state, record.id)
            if index is None:
                raise DocumentNotFound(str(record.id))
            record = record.model_copy(update={"processing_message": None})
            state["documents"][index] = record.model_dump(mode="json")
            state["processing_state"].pop(str(record.id), None)
            state["chunks"] = [
                item for item in state["chunks"] if item["document_id"] != str(record.id)
            ]
            state["chunks"].extend(chunk.model_dump(mode="json") for chunk in chunks)
            self._write_state(state)
        return record

    def delete_document(
        self,
        document_id: UUID,
        delete_from_chroma: Callable[[UUID], None],
        restore_to_chroma: Callable[[UUID], None],
    ) -> None:
        document_uuid = UUID(str(document_id))
        with self._lock:
            state = self._read_state()
            if document_uuid in {UUID(value) for value in state["pending_cleanup"]}:
                self._clean_physical_files(document_uuid)
                state["pending_cleanup"] = [value for value in state["pending_cleanup"] if value != str(document_uuid)]
                self._write_state(state)
                return

            pending = self._pending_deletion(state, document_uuid)
            if pending is None:
                if self._find_document(state, document_uuid) is None:
                    raise DocumentNotFound(str(document_uuid))
                state["pending_deletion"].append({"id": str(document_uuid), "phase": "delete_intent"})
                self._write_state(state)
                pending = {"id": str(document_uuid), "phase": "delete_intent"}
            if pending["phase"] == "delete_intent":
                delete_from_chroma(document_uuid)
                chroma_deleted = {**pending, "phase": "chroma_deleted"}
                try:
                    self._replace_pending_deletion(state, chroma_deleted)
                    self._write_state(state)
                except Exception:
                    try:
                        restore_to_chroma(document_uuid)
                    except Exception as restore_error:
                        raise RuntimeError("文档删除补偿失败") from restore_error
                    raise

            new_state = {**state}
            new_state["documents"] = [item for item in state["documents"] if item["id"] != str(document_uuid)]
            new_state["chunks"] = [item for item in state["chunks"] if item["document_id"] != str(document_uuid)]
            new_state["pending_deletion"] = [item for item in state["pending_deletion"] if item["id"] != str(document_uuid)]
            new_state["processing_state"].pop(str(document_uuid), None)
            new_state["pending_cleanup"] = [*state["pending_cleanup"], str(document_uuid)]
            self._write_state(new_state)
            self._clean_physical_files(document_uuid)
            new_state["pending_cleanup"] = [value for value in new_state["pending_cleanup"] if value != str(document_uuid)]
            self._write_state(new_state)

    def pending_deletion_ids(self) -> tuple[UUID, ...]:
        with self._lock:
            return tuple(UUID(item["id"]) for item in self._read_state()["pending_deletion"])

    @staticmethod
    def _pending_deletion(state: dict, document_id: UUID) -> dict | None:
        return next((item for item in state["pending_deletion"] if item["id"] == str(document_id)), None)

    @staticmethod
    def _replace_pending_deletion(state: dict, replacement: dict) -> None:
        state["pending_deletion"] = [replacement if item["id"] == replacement["id"] else item for item in state["pending_deletion"]]

    def pending_cleanup_ids(self) -> tuple[UUID, ...]:
        with self._lock:
            return tuple(UUID(value) for value in self._read_state()["pending_cleanup"])

    def _clean_physical_files(self, document_id: UUID) -> None:
        for upload_path in self.uploads_dir.glob(f"{document_id}.*"):
            upload_path.unlink()
        extracted_path = self.extracted_dir / str(document_id)
        if extracted_path.exists():
            shutil.rmtree(extracted_path)

    def upload_path(self, document_id: UUID, media_type: str | None = None) -> Path:
        suffix = "pdf" if media_type == "application/pdf" else "docx"
        if media_type is None:
            state = self._read_state()
            item = self._find_document(state, document_id)
            if item is not None:
                suffix = "pdf" if item["media_type"] == "application/pdf" else "docx"
        return self.uploads_dir / f"{document_id}.{suffix}"

    def _read_state(self) -> dict:
        try:
            with self.metadata_path.open(encoding="utf-8") as file:
                state = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("文档元数据不可用") from error
        if not isinstance(state, dict) or not isinstance(state.get("documents"), list) or not isinstance(state.get("chunks"), list):
            raise RuntimeError("文档元数据不可用")
        if "pending_deletion" not in state:
            state["pending_deletion"] = []
        if "pending_cleanup" not in state:
            state["pending_cleanup"] = []
        if "processing_state" not in state:
            state["processing_state"] = {}
        if not isinstance(state["pending_deletion"], list) or not isinstance(state["pending_cleanup"], list) or not isinstance(state["processing_state"], dict):
            raise RuntimeError("文档元数据不可用")
        if any(not isinstance(document_id, str) or not isinstance(value, dict) or set(value) != {"task_id", "phase"} or not isinstance(value["task_id"], str) or value["phase"] not in {"submitted", "polling", "vector_cleanup"} for document_id, value in state["processing_state"].items()):
            raise RuntimeError("文档元数据不可用")
        if any(not isinstance(item, dict) or set(item) != {"id", "phase"} or not isinstance(item["id"], str) or item["phase"] not in {"delete_intent", "chroma_deleted"} for item in state["pending_deletion"]):
            raise RuntimeError("文档元数据不可用")
        return state

    def _write_state(self, state: dict) -> None:
        temporary_path = self.metadata_path.with_suffix(".json.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(state, file, ensure_ascii=False, separators=(",", ":"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.metadata_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _find_document(state: dict, document_id: UUID) -> dict | None:
        return next(
            (item for item in state["documents"] if item["id"] == str(document_id)),
            None,
        )

    @staticmethod
    def _find_document_index(state: dict, document_id: UUID) -> int | None:
        return next(
            (index for index, item in enumerate(state["documents"]) if item["id"] == str(document_id)),
            None,
        )
