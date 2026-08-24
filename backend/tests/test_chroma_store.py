import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.models.documents import DocumentChunk
from app.services.chroma_store import ChromaSearchHit, ChromaStore
from app.services.embeddings import LocalBgeEmbedder
from app.services.resilience import ExternalServiceUnavailable


class FakeEmbedder:
    def __init__(self):
        self.document_texts = []
        self.query_texts = []

    def embed_documents(self, texts):
        self.document_texts.append(list(texts))
        return [[float(index + 1)] for index, _text in enumerate(texts)]

    def embed_query(self, text):
        self.query_texts.append(text)
        return [42.0]


class FakeCollection:
    def __init__(self):
        self.records = {}
        self.upsert_calls = []
        self.query_calls = []
        self.delete_calls = []
        self.get_calls = []
        self.update_calls = []

    def upsert(self, *, ids, embeddings, metadatas):
        self.upsert_calls.append(
            {
                "ids": ids,
                "embeddings": embeddings,
                "metadatas": metadatas,
            }
        )
        for index, chunk_id in enumerate(ids):
            self.records[chunk_id] = {
                "metadata": metadatas[index],
            }

    def query(self, *, query_embeddings, n_results, where=None, include=None):
        self.query_calls.append(
            {
                "query_embeddings": query_embeddings,
                "n_results": n_results,
                "where": where,
                "include": include,
            }
        )
        records = list(self.records.items())
        if where:
            conditions = where.get("$and", [where])
            for condition in conditions:
                if "document_id" in condition:
                    allowed = set(condition["document_id"]["$in"])
                    records = [
                        item for item in records if item[1]["metadata"]["document_id"] in allowed
                    ]
                if "ready" in condition:
                    records = [
                        item for item in records if item[1]["metadata"].get("ready") is condition["ready"]
                    ]
        records = records[:n_results]
        return {
            "ids": [[chunk_id for chunk_id, _record in records]],
            "distances": [[float(index) / 10 for index, _record in enumerate(records)]],
            "metadatas": [[record["metadata"] for _chunk_id, record in records]],
        }

    def get(self, *, where, include):
        self.get_calls.append({"where": where, "include": include})
        records = [
            (chunk_id, record) for chunk_id, record in self.records.items()
            if record["metadata"]["document_id"] == where["document_id"]
        ]
        return {
            "ids": [chunk_id for chunk_id, _record in records],
            "metadatas": [record["metadata"] for _chunk_id, record in records],
        }

    def update(self, *, ids, metadatas):
        self.update_calls.append({"ids": ids, "metadatas": metadatas})
        for index, chunk_id in enumerate(ids):
            self.records[chunk_id]["metadata"] = metadatas[index]

    def delete(self, *, where):
        self.delete_calls.append(where)
        self.records = {
            chunk_id: record
            for chunk_id, record in self.records.items()
            if record["metadata"]["document_id"] != where["document_id"]
        }


class FakeClient:
    def __init__(self):
        self.collection = FakeCollection()
        self.get_or_create_calls = []

    def get_or_create_collection(self, *, name, metadata):
        self.get_or_create_calls.append({"name": name, "metadata": metadata})
        return self.collection


def test_chroma_store_hides_collection_creation_error(tmp_path):
    class FailingCollectionClient:
        def get_or_create_collection(self, **_kwargs):
            raise RuntimeError(r"C:\private\chroma failure")

    with pytest.raises(RuntimeError, match="^Chroma 向量库不可用$") as error:
        ChromaStore(
            tmp_path / "chroma",
            "travel_documents",
            FakeEmbedder(),
            client=FailingCollectionClient(),
        )

    assert error.value.__cause__ is None


def test_local_bge_embedder_loads_lazily_and_normalizes_embeddings(tmp_path, monkeypatch):
    class FakeSentenceTransformer:
        instances = []

        def __init__(self, model_path, *, local_files_only):
            self.model_path = model_path
            self.local_files_only = local_files_only
            self.encode_calls = []
            self.__class__.instances.append(self)

        def encode(self, texts, *, normalize_embeddings):
            self.encode_calls.append(
                {"texts": texts, "normalize_embeddings": normalize_embeddings}
            )
            return [[1, 2] for _text in texts]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    model_directory = tmp_path / "local-bge"
    model_directory.mkdir()
    embedder = LocalBgeEmbedder(model_directory)

    assert FakeSentenceTransformer.instances == []
    assert embedder.embed_documents(["成都", "重庆"]) == [[1.0, 2.0], [1.0, 2.0]]
    assert len(FakeSentenceTransformer.instances) == 1
    model = FakeSentenceTransformer.instances[0]
    assert model.model_path == str(model_directory)
    assert model.local_files_only is True
    assert model.encode_calls == [
        {"texts": ["成都", "重庆"], "normalize_embeddings": True}
    ]


def test_local_bge_embedder_hides_model_load_and_encoding_failures(tmp_path, monkeypatch):
    class FailingLoadTransformer:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError(r"C:\private\local-bge load failure")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FailingLoadTransformer),
    )
    model_directory = tmp_path / "local-bge"
    model_directory.mkdir()

    with pytest.raises(ExternalServiceUnavailable, match="^本地 BGE 模型暂不可用$") as load_error:
        LocalBgeEmbedder(model_directory).embed_query("成都")

    assert load_error.value.__cause__ is None
    assert str(model_directory) not in str(load_error.value)

    class FailingEncodeTransformer:
        def __init__(self, *_args, **_kwargs):
            return None

        def encode(self, *_args, **_kwargs):
            raise RuntimeError(r"C:\private\local-bge encode failure")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FailingEncodeTransformer),
    )

    with pytest.raises(ExternalServiceUnavailable, match="^本地 BGE 模型暂不可用$") as encode_error:
        LocalBgeEmbedder(model_directory).embed_query("成都")

    assert encode_error.value.__cause__ is None
    assert str(model_directory) not in str(encode_error.value)


def test_local_bge_embedder_fails_without_loading_when_model_directory_is_missing(tmp_path):
    embedder = LocalBgeEmbedder(tmp_path / "missing-bge")

    with pytest.raises(ExternalServiceUnavailable, match="本地 BGE 模型未配置"):
        embedder.embed_query("成都亲子游")


def make_chunk(document_id, **overrides):
    payload = {
        "id": str(uuid4()),
        "document_id": str(document_id),
        "content": "成都亲子旅游资源丰富。",
        "chunk_type": "text",
        "document_name": "成都调研.pdf",
        "source_page": 2,
        "source_section": "亲子资源",
        "char_start": 0,
        "char_end": 11,
    }
    payload.update(overrides)
    return DocumentChunk(**payload)


def test_chroma_store_upserts_vectors_and_whitelisted_metadata_only(tmp_path):
    document_id = uuid4()
    chunk = make_chunk(document_id, image_path="images/figure-1.png")
    client = FakeClient()
    embedder = FakeEmbedder()
    store = ChromaStore(tmp_path / "chroma", "travel_documents", embedder, client=client)

    store.upsert([chunk])

    assert client.get_or_create_calls == [
        {"name": "travel_documents", "metadata": {"hnsw:space": "cosine"}}
    ]
    assert embedder.document_texts == [[chunk.content]]
    assert client.collection.upsert_calls == [
        {
            "ids": [str(chunk.id)],
            "embeddings": [[1.0]],
            "metadatas": [
                {
                    "document_id": str(chunk.document_id),
                    "document_name": chunk.document_name,
                    "chunk_type": chunk.chunk_type,
                    "ready": True,
                    "source_page": chunk.source_page,
                    "source_section": chunk.source_section,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                }
            ],
        }
    ]


def test_chroma_store_batches_upserts_without_storing_chunk_content(tmp_path):
    document_id = uuid4()
    chunks = [
        make_chunk(document_id, content=f"文档块 {index}", source_page=index + 1)
        for index in range(5)
    ]

    class RejectOversizedCollection(FakeCollection):
        def upsert(self, **kwargs):
            if len(kwargs["ids"]) > 2:
                raise AssertionError("Chroma 批次超限")
            super().upsert(**kwargs)

    client = FakeClient()
    client.collection = RejectOversizedCollection()
    store = ChromaStore(
        tmp_path / "chroma",
        "travel_documents",
        FakeEmbedder(),
        client=client,
        upsert_batch_size=2,
    )

    store.upsert(chunks)

    assert [len(call["ids"]) for call in client.collection.upsert_calls] == [2, 2, 1]
    assert all("documents" not in call for call in client.collection.upsert_calls)
    assert [
        (call["ids"], call["embeddings"], [item["source_page"] for item in call["metadatas"]])
        for call in client.collection.upsert_calls
    ] == [
        ([str(chunks[0].id), str(chunks[1].id)], [[1.0], [2.0]], [1, 2]),
        ([str(chunks[2].id), str(chunks[3].id)], [[1.0], [2.0]], [3, 4]),
        ([str(chunks[4].id)], [[1.0]], [5]),
    ]


@pytest.mark.parametrize("returned_count", [1, 3])
def test_chroma_store_rejects_misaligned_batch_embeddings_before_upsert(tmp_path, returned_count):
    document_id = uuid4()
    chunks = [make_chunk(document_id, source_page=index + 1) for index in range(4)]

    class MisalignedEmbedder:
        def __init__(self):
            self.calls = 0

        def embed_documents(self, texts):
            self.calls += 1
            if self.calls == 1:
                return [[1.0] for _text in texts]
            return [[1.0] for _index in range(returned_count)]

        def embed_query(self, _text):
            return [1.0]

    client = FakeClient()
    store = ChromaStore(
        tmp_path / "chroma",
        "travel_documents",
        MisalignedEmbedder(),
        client=client,
        upsert_batch_size=2,
    )

    with pytest.raises(ValueError, match="嵌入向量数量与文本块数量不一致"):
        store.upsert(chunks)

    assert [call["ids"] for call in client.collection.upsert_calls] == [
        [str(chunks[0].id), str(chunks[1].id)]
    ]


def test_chroma_store_queries_global_and_document_filtered_controlled_hits(tmp_path):
    first_document_id = uuid4()
    second_document_id = uuid4()
    first_chunk = make_chunk(first_document_id)
    second_chunk = make_chunk(second_document_id, content="成都博物馆适合亲子游。")
    client = FakeClient()
    store = ChromaStore(tmp_path / "chroma", "travel_documents", FakeEmbedder(), client=client)
    store.upsert([first_chunk, second_chunk])

    global_hits = store.query("成都", limit=5)
    filtered_hits = store.query("成都", document_ids=(first_document_id,), limit=5)

    assert [(hit.chunk_id, hit.document_id, hit.score) for hit in global_hits] == [
        (UUID(str(first_chunk.id)), first_document_id, 1.0),
        (UUID(str(second_chunk.id)), second_document_id, 0.9),
    ]
    assert [(hit.chunk_id, hit.document_id, hit.score) for hit in filtered_hits] == [
        (UUID(str(first_chunk.id)), first_document_id, 1.0)
    ]
    assert client.collection.query_calls == [
        {
            "query_embeddings": [[42.0]],
            "n_results": 5,
            "where": {"ready": True},
            "include": ["distances", "metadatas"],
        },
        {
            "query_embeddings": [[42.0]],
            "n_results": 5,
            "where": {
                "$and": [
                    {"ready": True},
                    {"document_id": {"$in": [str(first_document_id)]}},
                ]
            },
            "include": ["distances", "metadatas"],
        },
    ]
    assert not hasattr(global_hits[0], "content")


def test_chroma_store_deletes_all_chunks_for_a_document(tmp_path):
    first_document_id = uuid4()
    second_document_id = uuid4()
    first_chunk = make_chunk(first_document_id)
    second_chunk = make_chunk(second_document_id)
    client = FakeClient()
    store = ChromaStore(tmp_path / "chroma", "travel_documents", FakeEmbedder(), client=client)
    store.upsert([first_chunk, second_chunk])

    store.delete_document(first_document_id)

    assert client.collection.delete_calls == [{"document_id": str(first_document_id)}]
    assert [hit.document_id for hit in store.query("成都", limit=10)] == [second_document_id]


def test_chroma_store_skips_corrupted_hit_ids_and_keeps_valid_hits(tmp_path):
    valid_document_id = uuid4()
    valid_chunk_id = uuid4()

    class CorruptedResultCollection:
        def query(self, **_kwargs):
            return {
                "ids": [["not-a-uuid", str(valid_chunk_id)]],
                "distances": [[0.9, 0.1]],
                "metadatas": [[
                    {"document_id": "also-not-a-uuid"},
                    {"document_id": str(valid_document_id)},
                ]],
            }

    client = FakeClient()
    client.collection = CorruptedResultCollection()
    store = ChromaStore(tmp_path / "chroma", "travel_documents", FakeEmbedder(), client=client)

    assert store.query("成都", limit=5) == (
        ChromaSearchHit(
            chunk_id=valid_chunk_id,
            document_id=valid_document_id,
            score=0.9,
        ),
    )


def test_chroma_store_returns_higher_score_for_lower_cosine_distance(tmp_path):
    document_id = uuid4()
    near_chunk_id = uuid4()
    far_chunk_id = uuid4()

    class DistanceResultCollection:
        def query(self, **_kwargs):
            return {
                "ids": [[str(near_chunk_id), str(far_chunk_id)]],
                "distances": [[0.1, 0.9]],
                "metadatas": [[
                    {"document_id": str(document_id)},
                    {"document_id": str(document_id)},
                ]],
            }

    client = FakeClient()
    client.collection = DistanceResultCollection()
    store = ChromaStore(tmp_path / "chroma", "travel_documents", FakeEmbedder(), client=client)

    hits = store.query("成都", limit=5)

    assert hits[0].score > hits[1].score


def test_chroma_store_converts_cosine_distance_to_clamped_descending_similarity(tmp_path):
    document_id = uuid4()
    chunk_ids = [uuid4() for _ in range(4)]

    class DistanceResultCollection:
        def query(self, **_kwargs):
            return {
                "ids": [[str(chunk_id) for chunk_id in chunk_ids]],
                "distances": [[0.1, 0.8, -0.2, 1.2]],
                "metadatas": [[{"document_id": str(document_id)} for _chunk_id in chunk_ids]],
            }

    client = FakeClient()
    client.collection = DistanceResultCollection()
    store = ChromaStore(tmp_path / "chroma", "travel_documents", FakeEmbedder(), client=client)

    hits = store.query("成都", limit=5)

    assert [hit.score for hit in hits] == pytest.approx([0.9, 0.2, 1.0, 0.0])
    assert hits[0].score > hits[1].score


def test_chroma_store_applies_ready_filter_before_limit(tmp_path):
    stale_document_id = uuid4()
    ready_document_id = uuid4()
    stale_chunks = [
        make_chunk(stale_document_id, content=f"已失效命中 {index}")
        for index in range(5)
    ]
    ready_chunk = make_chunk(ready_document_id, content="第六个就绪命中")
    client = FakeClient()
    store = ChromaStore(tmp_path / "chroma", "travel_documents", FakeEmbedder(), client=client)

    store.upsert(stale_chunks, ready=False)
    store.upsert([ready_chunk], ready=True)

    hits = store.query("命中", limit=5)

    assert [(hit.chunk_id, hit.document_id) for hit in hits] == [
        (UUID(str(ready_chunk.id)), ready_document_id)
    ]
    assert client.collection.query_calls[-1]["where"] == {"ready": True}


def test_chroma_store_marks_all_document_chunks_ready_without_exposing_content(tmp_path):
    document_id = uuid4()
    chunks = [make_chunk(document_id) for _ in range(2)]
    client = FakeClient()
    store = ChromaStore(tmp_path / "chroma", "travel_documents", FakeEmbedder(), client=client)

    store.upsert(chunks, ready=False)
    store.mark_document_ready(document_id)

    assert all(record["metadata"]["ready"] is True for record in client.collection.records.values())
    assert "content" not in client.collection.records[str(chunks[0].id)]["metadata"]


@pytest.mark.parametrize("limit", [0, -1, True, 1.2])
def test_chroma_store_rejects_invalid_query_limit(tmp_path, limit):
    store = ChromaStore(tmp_path / "chroma", "travel_documents", FakeEmbedder(), client=FakeClient())

    with pytest.raises(ValueError, match="limit 必须为正整数"):
        store.query("成都", limit=limit)
