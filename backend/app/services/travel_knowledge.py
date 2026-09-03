from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.documents import DocumentStatus
from app.models.travel import DataStatus, Source, SourceType


class TravelKnowledgeService:
    """为行程编排检索目的地已审核攻略，并保留可追溯来源。"""

    def __init__(self, document_store: Any, chroma_store: Any, *, limit: int = 6) -> None:
        self.document_store = document_store
        self.chroma_store = chroma_store
        self.limit = limit

    def retrieve(self, destination: str) -> tuple[Source, ...]:
        if self.chroma_store is None:
            return ()
        records = self.document_store.list_documents()
        ready = {str(record.id): record for record in records if record.status is DocumentStatus.ready}
        if not ready:
            return ()
        hits = self.chroma_store.query(f"{destination} 景点 美食 行程攻略", limit=self.limit)
        sources: list[Source] = []
        seen: set[str] = set()
        for hit in hits:
            record = ready.get(str(hit.document_id))
            if record is None or record.filename in seen:
                continue
            seen.add(record.filename)
            version = (record.updated_at or record.created_at).isoformat()
            sources.append(Source(
                name=record.filename,
                type=SourceType.knowledge_base,
                data_status=DataStatus.knowledge_base,
                source_updated_at=record.updated_at,
                retrieved_at=datetime.now(timezone.utc),
                knowledge_version=version,
            ))
        return tuple(sources)
