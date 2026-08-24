from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from uuid import UUID

from app.models.documents import QueryRecord


class QueryRecordNotFound(KeyError):
    """查询记录不存在。"""


class QueryRecordStore:
    """以 query_records.json 持久化知识检索记录的进程内存储。"""

    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.data_dir / "query_records.json"
        self._lock = RLock()
        if not self.metadata_path.exists():
            self._write_state({"records": []})

    def add(self, record: QueryRecord) -> QueryRecord:
        with self._lock:
            state = self._read_state()
            if any(item["id"] == record.id for item in state["records"]):
                raise ValueError("查询记录已存在")
            state["records"].append(record.model_dump(mode="json"))
            self._write_state(state)
        return record

    def list(self) -> tuple[QueryRecord, ...]:
        """仅返回已生成完整回答的记录，并物理清理未完成回答的记录。"""
        with self._lock:
            state = self._read_state()
            kept = [
                item for item in state["records"]
                if item.get("answer_status") == "generated"
                and isinstance(item.get("answer"), str)
                and item["answer"]
            ]
            if len(kept) != len(state["records"]):
                state["records"] = kept
                self._write_state(state)
            records = tuple(QueryRecord.model_validate(item) for item in kept)
        return tuple(sorted(records, key=lambda record: record.created_at, reverse=True))

    def update(
        self,
        record_id: UUID | str,
        *,
        results: tuple,
        answer: str | None,
        answer_status: str,
    ) -> QueryRecord:
        """更新已有记录的检索结果、润色回答与状态，未命中抛出异常。"""
        with self._lock:
            state = self._read_state()
            index = next(
                (
                    index for index, item in enumerate(state["records"])
                    if item["id"] == str(record_id)
                ),
                None,
            )
            if index is None:
                raise QueryRecordNotFound(str(record_id))
            updated = QueryRecord.model_validate(state["records"][index]).model_copy(
                update={
                    "results": tuple(results),
                    "answer": answer,
                    "answer_status": answer_status,
                }
            )
            state["records"][index] = updated.model_dump(mode="json")
            self._write_state(state)
        return updated

    def set_rating(
        self, record_id: UUID | str, rating: str | None
    ) -> QueryRecord:
        """设置或清除（None）记录的用户评价，未命中抛出异常。"""
        if rating not in {None, "like", "dislike"}:
            raise ValueError("rating 无效")
        with self._lock:
            state = self._read_state()
            index = next(
                (
                    index for index, item in enumerate(state["records"])
                    if item["id"] == str(record_id)
                ),
                None,
            )
            if index is None:
                raise QueryRecordNotFound(str(record_id))
            updated = QueryRecord.model_validate(state["records"][index]).model_copy(
                update={"rating": rating}
            )
            state["records"][index] = updated.model_dump(mode="json")
            self._write_state(state)
        return updated

    def delete(self, record_id: UUID | str) -> None:
        with self._lock:
            state = self._read_state()
            before = len(state["records"])
            state["records"] = [
                item for item in state["records"] if item["id"] != str(record_id)
            ]
            if len(state["records"]) == before:
                raise QueryRecordNotFound(str(record_id))
            self._write_state(state)

    def clear(self) -> None:
        with self._lock:
            state = self._read_state()
            state["records"] = []
            self._write_state(state)

    def _read_state(self) -> dict:
        try:
            with self.metadata_path.open(encoding="utf-8") as file:
                state = json.load(file)
        except (OSError, json.JSONDecodeError):
            raise RuntimeError("查询记录元数据不可用") from None
        if (
            not isinstance(state, dict)
            or not isinstance(state.get("records"), list)
        ):
            raise RuntimeError("查询记录元数据不可用")
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
