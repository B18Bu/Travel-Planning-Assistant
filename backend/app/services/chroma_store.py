from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence
from uuid import UUID

from app.models.documents import DocumentChunk


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class ChromaSearchHit:
    """仅保留将命中映射回 DocumentStore 所需的受控检索信息。"""

    chunk_id: UUID
    document_id: UUID
    score: float


class ChromaStore:
    """持久化文档块向量；原文与完整块数据仍由 DocumentStore 持有。"""

    def __init__(
        self,
        persist_directory: Path | str,
        collection_name: str,
        embedder: Embedder,
        *,
        client: Any | None = None,
        upsert_batch_size: int = 100,
    ) -> None:
        if (
            not isinstance(upsert_batch_size, int)
            or isinstance(upsert_batch_size, bool)
            or not 1 <= upsert_batch_size <= 166
        ):
            raise ValueError("upsert_batch_size 必须在 1 到 166 之间")
        self._embedder = embedder
        self._upsert_batch_size = upsert_batch_size
        try:
            if client is None:
                import chromadb

                client = chromadb.PersistentClient(path=str(Path(persist_directory)))
            self._collection = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            raise RuntimeError("Chroma 向量库不可用") from None

    def upsert(self, chunks: Sequence[DocumentChunk], *, ready: bool = True) -> None:
        if not chunks:
            return
        for start in range(0, len(chunks), self._upsert_batch_size):
            batch = chunks[start : start + self._upsert_batch_size]
            contents = [chunk.content for chunk in batch]
            embeddings = self._embedder.embed_documents(contents)
            if len(embeddings) != len(batch):
                raise ValueError("嵌入向量数量与文本块数量不一致")
            self._collection.upsert(
                ids=[str(chunk.id) for chunk in batch],
                embeddings=embeddings,
                metadatas=[self._metadata_for(chunk, ready=ready) for chunk in batch],
            )

    def mark_document_ready(self, document_id: UUID) -> None:
        result = self._collection.get(
            where={"document_id": str(document_id)},
            include=["metadatas"],
        )
        ids = result.get("ids", [])
        metadatas = result.get("metadatas", [])
        if not ids or not metadatas:
            return
        updated = [
            {**metadata, "ready": True}
            for metadata in metadatas
            if isinstance(metadata, dict)
        ]
        if len(updated) != len(ids):
            raise RuntimeError("Chroma 向量元数据不可用")
        self._collection.update(ids=ids, metadatas=updated)

    def query(
        self,
        query: str,
        *,
        document_ids: Sequence[UUID] = (),
        limit: int = 5,
    ) -> tuple[ChromaSearchHit, ...]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit 必须为正整数")
        ready_filter = {"ready": True}
        where = ready_filter
        if document_ids:
            where = {
                "$and": [
                    ready_filter,
                    {"document_id": {"$in": [str(document_id) for document_id in document_ids]}},
                ]
            }
        result = self._collection.query(
            query_embeddings=[self._embedder.embed_query(query)],
            n_results=limit,
            where=where,
            include=["distances", "metadatas"],
        )
        ids = result.get("ids", [[]])
        distances = result.get("distances", [[]])
        metadatas = result.get("metadatas", [[]])
        if not ids or not distances or not metadatas:
            return ()
        hits = []
        for chunk_id, distance, metadata in zip(ids[0], distances[0], metadatas[0]):
            if not isinstance(metadata, dict) or not isinstance(metadata.get("document_id"), str):
                continue
            try:
                hits.append(
                    ChromaSearchHit(
                        chunk_id=UUID(chunk_id),
                        document_id=UUID(metadata["document_id"]),
                        score=max(0.0, min(1.0, 1.0 - float(distance))),
                    )
                )
            except (TypeError, ValueError):
                continue
        return tuple(hits)

    def delete_document(self, document_id: UUID) -> None:
        self._collection.delete(where={"document_id": str(document_id)})

    @staticmethod
    def _metadata_for(chunk: DocumentChunk, *, ready: bool) -> dict[str, str | int | bool]:
        metadata: dict[str, str | int | bool] = {
            "document_id": str(chunk.document_id),
            "document_name": chunk.document_name,
            "chunk_type": chunk.chunk_type,
            "ready": ready,
        }
        for name in (
            "source_page",
            "source_section",
            "source_table",
            "source_figure",
            "char_start",
            "char_end",
        ):
            value = getattr(chunk, name)
            if value is not None:
                metadata[name] = value
        return metadata
