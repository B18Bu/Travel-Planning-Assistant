from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4


class TravelPlanStore:
    """以 JSON 保存旅行方案摘要和完整文档。"""

    def __init__(self, data_dir: Path | str) -> None:
        self.path = Path(data_dir) / "travel_plans.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        if not self.path.exists():
            self._write([])

    def save(self, query: str, request: object, document: object) -> dict:
        with self.lock:
            records = self._read()
            now = datetime.now(timezone.utc).isoformat()
            record = {"plan_id": str(uuid4()), "query": query, "request": request.model_dump(mode="json"), "document": document.model_dump(mode="json"), "version": 1, "created_at": now, "updated_at": now}
            records.append(record)
            self._write(records)
            return record

    def list(self) -> list[dict]:
        with self.lock:
            return [{key: item[key] for key in ("plan_id", "query", "version", "created_at", "updated_at")} for item in reversed(self._read())]

    def get(self, plan_id: str) -> dict | None:
        with self.lock:
            return next((item for item in self._read() if item.get("plan_id") == plan_id), None)

    def delete(self, plan_id: str) -> bool:
        with self.lock:
            records = self._read()
            retained = [item for item in records if item.get("plan_id") != plan_id]
            if len(retained) == len(records):
                return False
            self._write(retained)
            return True

    def revise(self, plan_id: str, version: int, query: str, request: object, document: object) -> dict | None:
        with self.lock:
            records = self._read()
            index = next((i for i, item in enumerate(records) if item.get("plan_id") == plan_id), None)
            if index is None or records[index].get("version") != version:
                return None
            updated = dict(records[index])
            updated.update({"query": query, "request": request.model_dump(mode="json"), "document": document.model_dump(mode="json"), "version": version + 1, "updated_at": datetime.now(timezone.utc).isoformat()})
            records[index] = updated
            self._write(records)
            return updated

    def _read(self) -> list[dict]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write(self, records: list[dict]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)
