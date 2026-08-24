from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.documents import KnowledgeSearchResult, QueryRecord, SourceLocation
from app.services.query_record_store import QueryRecordNotFound, QueryRecordStore


def make_record(query="成都美食推荐", answer="成都美食攻略。" * 6, status="generated", created_at=None):
    return QueryRecord(
        id=str(uuid4()),
        query=query,
        created_at=created_at or datetime.now(timezone.utc),
        answer=answer,
        answer_status=status,
        results=(
            KnowledgeSearchResult(
                content="成都火锅以麻辣著称。",
                chunk_type="text",
                score=0.8,
                source=SourceLocation(document_name="成都美食攻略.docx", page=2),
            ),
        ),
    )


def test_add_list_delete_roundtrip(tmp_path):
    store = QueryRecordStore(tmp_path)
    record = make_record()

    store.add(record)
    listed = store.list()

    assert len(listed) == 1
    assert listed[0].id == record.id
    assert listed[0].query == "成都美食推荐"
    assert listed[0].answer == record.answer
    assert listed[0].answer_status == "generated"
    assert listed[0].results[0].content == "成都火锅以麻辣著称。"
    assert listed[0].results[0].source.document_name == "成都美食攻略.docx"

    store.delete(record.id)
    assert store.list() == ()


def test_list_orders_newest_first(tmp_path):
    store = QueryRecordStore(tmp_path)
    older = make_record(created_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
    newer = make_record(created_at=datetime(2026, 8, 2, tzinfo=timezone.utc))

    store.add(older)
    store.add(newer)

    assert [item.id for item in store.list()] == [newer.id, older.id]


def test_clear_removes_all_records(tmp_path):
    store = QueryRecordStore(tmp_path)
    store.add(make_record())
    store.add(make_record())

    store.clear()

    assert store.list() == ()


def test_delete_missing_record_raises(tmp_path):
    store = QueryRecordStore(tmp_path)

    with pytest.raises(QueryRecordNotFound):
        store.delete(uuid4())


def test_add_duplicate_record_raises(tmp_path):
    store = QueryRecordStore(tmp_path)
    record = make_record()
    store.add(record)

    with pytest.raises(ValueError):
        store.add(record)


def test_update_record_answers_and_results(tmp_path):
    store = QueryRecordStore(tmp_path)
    record = make_record()
    store.add(record)

    updated_results = (
        KnowledgeSearchResult(
            content="更新后的回答片段。",
            chunk_type="text",
            score=0.9,
            source=SourceLocation(document_name="成都美食攻略.docx", page=5),
        ),
    )
    store.update(
        record.id,
        results=updated_results,
        answer="新的完整回答。" * 10,
        answer_status="generated",
    )

    listed = store.list()
    assert len(listed) == 1
    assert listed[0].answer == "新的完整回答。" * 10
    assert listed[0].answer_status == "generated"
    assert listed[0].results[0].content == "更新后的回答片段。"
    assert listed[0].query == record.query


def test_update_missing_record_raises(tmp_path):
    store = QueryRecordStore(tmp_path)

    with pytest.raises(QueryRecordNotFound):
        store.update(uuid4(), results=(), answer=None, answer_status="none")


def test_set_rating_like_dislike_and_clear(tmp_path):
    store = QueryRecordStore(tmp_path)
    record = make_record()
    store.add(record)

    store.set_rating(record.id, "like")
    assert store.list()[0].rating == "like"

    store.set_rating(record.id, "dislike")
    assert store.list()[0].rating == "dislike"

    store.set_rating(record.id, None)
    assert store.list()[0].rating is None


def test_set_rating_missing_record_raises(tmp_path):
    store = QueryRecordStore(tmp_path)

    with pytest.raises(QueryRecordNotFound):
        store.set_rating(uuid4(), "like")


def test_list_only_keeps_generated_answer_records_and_cleans_others(tmp_path):
    store = QueryRecordStore(tmp_path)
    generated = make_record()
    store.add(generated)
    store.add(make_record(query="成都亲子游", status="none", answer=None))
    store.add(make_record(query="三亚亲子游", status="unavailable", answer=None))

    listed = store.list()

    assert [item.id for item in listed] == [generated.id]
    assert len(store.list()) == 1  # 未完成回答的记录已被物理清理
