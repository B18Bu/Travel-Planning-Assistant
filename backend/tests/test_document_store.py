from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.models.documents import DocumentChunk, DocumentRecord, DocumentStatus
from app.services.document_store import DocumentNotFound, DocumentStore


PDF = "application/pdf"


def make_record(document_id=None, **overrides):
    payload = {
        "id": str(document_id or uuid4()),
        "filename": "成都调研.pdf",
        "media_type": PDF,
        "status": DocumentStatus.pending,
        "created_at": datetime.now(timezone.utc),
    }
    payload.update(overrides)
    return DocumentRecord(**payload)


def make_chunk(document_id, **overrides):
    payload = {
        "id": str(uuid4()),
        "document_id": str(document_id),
        "content": "成都亲子旅游资源丰富。",
        "chunk_type": "text",
        "document_name": "成都调研.pdf",
        "source_page": 1,
        "char_start": 0,
        "char_end": 11,
    }
    payload.update(overrides)
    return DocumentChunk(**payload)


def test_store_persists_document_state_and_traceable_chunks_atomically(tmp_path):
    store = DocumentStore(tmp_path)
    record = make_record()
    chunk = make_chunk(record.id)

    stored = store.create_document(record, b"%PDF-example")
    ready = record.model_copy(update={"status": DocumentStatus.ready, "updated_at": datetime.now(timezone.utc), "chunk_count": 1, "text_chunk_count": 1})
    store.save_processed_document(ready, [chunk])

    restored = DocumentStore(tmp_path)
    assert restored.get_document(record.id) == ready
    assert restored.get_chunks(record.id) == (chunk,)
    assert restored.upload_path(record.id).name == f"{record.id}.pdf"
    assert restored.upload_path(record.id).read_bytes() == b"%PDF-example"
    assert (tmp_path / "uploads").is_dir()
    assert (tmp_path / "extracted").is_dir()
    assert (tmp_path / "chroma").is_dir()
    assert (tmp_path / "documents.json").is_file()


def test_create_removes_new_upload_when_metadata_write_fails(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    record = make_record()
    monkeypatch.setattr(store, "_write_state", lambda _state: (_ for _ in ()).throw(OSError("metadata failure")))

    with pytest.raises(OSError, match="metadata failure"):
        store.create_document(record, b"pdf")

    assert not store.upload_path(record.id).exists()


def test_create_cleans_final_and_temporary_upload_when_write_fails(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    record = make_record()
    original_open = Path.open

    class PartialWriter:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, _content):
            raise OSError("disk full")

        def flush(self):
            return None

        def fileno(self):
            return -1

    def fail_upload_open(path, *args, **kwargs):
        if path.parent == store.uploads_dir and path.suffix == ".tmp":
            return PartialWriter()
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_upload_open)

    with pytest.raises(OSError, match="disk full"):
        store.create_document(record, b"pdf")

    assert not any(store.uploads_dir.iterdir())
    with pytest.raises(DocumentNotFound):
        store.get_document(record.id)


def test_store_persists_minimal_mineru_task_state_without_exposing_it_in_document_record(tmp_path):
    store = DocumentStore(tmp_path)
    record = make_record()
    store.create_document(record, b"pdf")

    store.save_processing_state(record.id, "batch-1", "submitted")

    assert store.get_processing_state(record.id) == {"task_id": "batch-1", "phase": "submitted"}
    assert not hasattr(store.get_document(record.id), "mineru_task_id")
    restored = DocumentStore(tmp_path)
    assert restored.get_processing_state(record.id) == {"task_id": "batch-1", "phase": "submitted"}


def test_store_rejects_chunks_for_a_different_document(tmp_path):
    store = DocumentStore(tmp_path)
    record = make_record()
    store.create_document(record, b"pdf")

    with pytest.raises(ValueError, match="仅 ready"):
        store.save_processed_document(record, [make_chunk(uuid4())])


def test_store_rejects_mismatched_ready_chunk_statistics_without_persisting(tmp_path):
    store = DocumentStore(tmp_path)
    record = make_record()
    store.create_document(record, b"pdf")
    ready = record.model_copy(update={"status": DocumentStatus.ready, "chunk_count": 2, "text_chunk_count": 2})

    with pytest.raises(ValueError, match="统计不一致"):
        store.save_processed_document(ready, [make_chunk(record.id)])

    assert store.get_document(record.id) == record
    assert store.get_chunks(record.id) == ()


def test_delete_does_not_restore_vectors_before_first_idempotent_chroma_delete(tmp_path):
    store = DocumentStore(tmp_path)
    record = make_record()
    store.create_document(record, b"pdf")
    calls = []

    store.delete_document(
        record.id,
        lambda document_id: calls.append(("delete", document_id)),
        lambda _document_id: (_ for _ in ()).throw(RuntimeError("BGE unavailable")),
    )

    assert calls == [("delete", UUID(record.id))]


def test_delete_runs_chroma_callback_before_removing_files_and_metadata(tmp_path):
    store = DocumentStore(tmp_path)
    record = make_record()
    store.create_document(record, b"pdf")
    events = []

    def delete_from_chroma(document_id: UUID) -> None:
        assert store.get_document(document_id) == record
        assert store.upload_path(document_id).exists()
        events.append(document_id)

    store.delete_document(record.id, delete_from_chroma, lambda _document_id: None)

    assert events == [UUID(record.id)]
    with pytest.raises(DocumentNotFound):
        store.get_document(record.id)
    assert not store.upload_path(record.id).exists()


def test_delete_retains_retryable_cleanup_intent_when_physical_cleanup_fails(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    record = make_record()
    store.create_document(record, b"pdf")
    extracted = store.extracted_dir / str(record.id)
    extracted.mkdir()
    (extracted / "figure.png").write_bytes(b"png")
    original_cleanup = store._clean_physical_files
    failed = False

    def fail_once(document_id):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("disk busy")
        return original_cleanup(document_id)

    monkeypatch.setattr(store, "_clean_physical_files", fail_once)
    calls = []

    with pytest.raises(OSError, match="disk busy"):
        store.delete_document(record.id, lambda document_id: calls.append(document_id), lambda _document_id: None)

    with pytest.raises(DocumentNotFound):
        store.get_document(record.id)
    assert any(store.uploads_dir.glob(f"{record.id}.*"))
    assert extracted.exists()
    assert store.pending_cleanup_ids() == (UUID(record.id),)

    store.delete_document(record.id, lambda document_id: calls.append(document_id), lambda _document_id: None)

    assert calls == [UUID(record.id)]
    assert not any(store.uploads_dir.glob(f"{record.id}.*"))
    assert not extracted.exists()
    assert store.pending_cleanup_ids() == ()


def test_delete_recovers_after_restore_failure_across_restart_without_blind_second_delete(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    record = make_record()
    store.create_document(record, b"pdf")
    original_write = store._write_state
    writes = 0

    def fail_post_chroma_write(state):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("metadata failure")
        return original_write(state)

    monkeypatch.setattr(store, "_write_state", fail_post_chroma_write)
    with pytest.raises(RuntimeError, match="补偿失败"):
        store.delete_document(record.id, lambda _document_id: None, lambda _document_id: (_ for _ in ()).throw(RuntimeError("restore unavailable")))

    recovered = DocumentStore(tmp_path)
    calls = []
    recovered.delete_document(record.id, lambda document_id: calls.append(("delete", document_id)), lambda document_id: calls.append(("restore", document_id)))

    assert calls == [("delete", UUID(record.id))]
    with pytest.raises(DocumentNotFound):
        recovered.get_document(record.id)


def test_delete_skips_chroma_callback_when_restart_has_chroma_deleted_phase(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    record = make_record()
    store.create_document(record, b"pdf")
    original_write = store._write_state
    writes = 0

    def fail_metadata_removal(state):
        nonlocal writes
        writes += 1
        if writes == 3:
            raise OSError("metadata removal failure")
        return original_write(state)

    monkeypatch.setattr(store, "_write_state", fail_metadata_removal)
    with pytest.raises(OSError, match="metadata removal failure"):
        store.delete_document(record.id, lambda _document_id: None, lambda _document_id: None)

    recovered = DocumentStore(tmp_path)
    calls = []
    recovered.delete_document(record.id, lambda document_id: calls.append(document_id), lambda _document_id: None)

    assert calls == []
    with pytest.raises(DocumentNotFound):
        recovered.get_document(record.id)
    assert recovered.pending_deletion_ids() == ()
    assert recovered.pending_cleanup_ids() == ()


def test_delete_persists_intent_before_chroma_and_retries_after_restart(tmp_path):
    store = DocumentStore(tmp_path)
    record = make_record()
    store.create_document(record, b"pdf")
    calls = []

    def fail_chroma(document_id):
        calls.append(document_id)
        raise RuntimeError("Chroma 暂不可用")

    with pytest.raises(RuntimeError, match="Chroma 暂不可用"):
        store.delete_document(record.id, fail_chroma, lambda _document_id: None)

    assert store.get_document(record.id) == record
    assert store.pending_deletion_ids() == (UUID(record.id),)
    recovered = DocumentStore(tmp_path)
    recovered.delete_document(record.id, lambda document_id: calls.append(document_id), lambda _document_id: None)

    assert calls == [UUID(record.id), UUID(record.id)]
    with pytest.raises(DocumentNotFound):
        recovered.get_document(record.id)
    assert recovered.pending_deletion_ids() == ()


def test_delete_does_not_report_success_or_remove_local_state_when_chroma_delete_fails(tmp_path):
    store = DocumentStore(tmp_path)
    record = make_record()
    store.create_document(record, b"pdf")

    with pytest.raises(RuntimeError, match="Chroma 删除失败"):
        store.delete_document(record.id, lambda _document_id: (_ for _ in ()).throw(RuntimeError("Chroma 删除失败")), lambda _document_id: None)

    assert store.get_document(record.id) == record
    assert store.upload_path(record.id).exists()


def test_store_rejects_unknown_document_operations(tmp_path):
    store = DocumentStore(tmp_path)

    with pytest.raises(DocumentNotFound):
        store.get_document(uuid4())
    with pytest.raises(DocumentNotFound):
        store.delete_document(uuid4(), lambda _document_id: None, lambda _document_id: None)
