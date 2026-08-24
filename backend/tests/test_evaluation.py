from types import SimpleNamespace
from uuid import uuid4

import pytest

from evaluation import evaluate
from evaluation.judge import _parse_verdict_lines, _parse_pair_lines, _context_precision
from evaluation.judge import Judge


def test_parse_verdict_lines_accepts_valid_rows():
    text = "1|支持|三亚有天涯海角\n2|不支持|三亚有免税店\n"
    rows = _parse_verdict_lines(text, "支持", "不支持")
    assert rows == [(1, True, "三亚有天涯海角"), (2, False, "三亚有免税店")]


def test_parse_verdict_lines_skips_malformed():
    text = "abc\n1|支持\n2|支持|陈述|多余\n3|不确定|坏判定\n"
    assert _parse_verdict_lines(text, "支持", "不支持") == []


def test_parse_pair_lines_ignores_malformed():
    text = "1|相关\nbad\n2|不相关\n"
    assert _parse_pair_lines(text, "相关", "不相关") == [(1, True), (2, False)]


def test_context_precision_formula():
    # 相关块在第 1、3、5 位 → CP = (1/1 + 2/3 + 3/5) / 3
    assert abs(_context_precision({1, 3, 5}, 5) - ((1.0 + 2.0 / 3.0 + 3.0 / 5.0) / 3.0)) < 1e-9


def test_context_precision_zero_relevant_is_zero():
    assert _context_precision(set(), 5) == 0.0


def test_context_precision_ignores_out_of_range_positions():
    # 越界编号不应计入分母：{1, 3, 4} 与过滤后的 {1, 3} 结果等值
    assert _context_precision({1, 3, 4}, 3) == _context_precision({1, 3}, 3)


class FakeDeepSeek:
    def __init__(self, response: str):
        self.response = response

    async def chat_completion(self, system, user):
        return self.response


@pytest.mark.asyncio
async def test_judge_faithfulness_parses_supported_ratio():
    judge = Judge(FakeDeepSeek("1|支持|a\n2|支持|b\n3|不支持|c"))
    assert await judge.faithfulness("q", "答", []) == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_judge_context_precision_unparseable_returns_none():
    judge = Judge(FakeDeepSeek("完全无法解析的输出"))
    assert await judge.context_precision("q", []) is None


@pytest.mark.asyncio
async def test_judge_answer_relevance_parses_bare_number():
    judge = Judge(FakeDeepSeek("0.8"))
    assert await judge.answer_relevance("q", "答") == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_judge_answer_relevance_parses_number_in_sentence():
    judge = Judge(FakeDeepSeek("评分：0.6|不充分"))
    assert await judge.answer_relevance("q", "答") == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_judge_answer_relevance_unparseable_returns_none():
    judge = Judge(FakeDeepSeek("无法解析"))
    assert await judge.answer_relevance("q", "答") is None


def test_load_golden_rejects_missing_or_duplicate_required_fields(tmp_path, monkeypatch):
    path = tmp_path / "golden_set.json"
    path.write_text(
        '[{"id":"q1","question":"问题","reference_answer":"答案"},'
        '{"id":"q1","question":"问题","reference_answer":"答案"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(evaluate, "GOLDEN_PATH", path)

    with pytest.raises(ValueError, match="id 不得重复"):
        evaluate._load_golden()


@pytest.mark.asyncio
async def test_evaluate_item_skips_all_metrics_after_retrieval_failure():
    class BrokenRetrieval:
        def retrieve(self, query, document_ids=()):
            raise RuntimeError("索引不可用")

    result = await evaluate.evaluate_item(
        judge=SimpleNamespace(),
        polisher=SimpleNamespace(),
        retrieval=BrokenRetrieval(),
        item={"id": "q1", "question": "问题", "reference_answer": "答案"},
    )

    assert result["retrieval_skipped"] is True
    assert result["retrieved_count"] == 0
    assert all(result[key] is None for key in evaluate.METRIC_KEYS)


@pytest.mark.asyncio
async def test_safe_metric_converts_unexpected_judge_failure_to_none():
    class BrokenJudge:
        async def faithfulness(self, *args):
            raise RuntimeError("裁判异常")

    assert await evaluate._safe_metric(BrokenJudge(), "faithfulness", "q", "a", []) is None


def test_retrieval_service_strips_query_filters_documents_and_refreshes_ready_index(monkeypatch):
    included_id, excluded_id = uuid4(), uuid4()
    included_chunk_id, excluded_chunk_id = uuid4(), uuid4()
    included_chunk = SimpleNamespace(
        id=included_chunk_id, document_id=included_id, content="包含文档内容",
        chunk_type="text", document_name="三亚旅游攻略.pdf", source_page=1,
        source_section=None, source_table=None, source_figure=None,
    )
    excluded_chunk = SimpleNamespace(
        id=excluded_chunk_id, document_id=excluded_id, content="排除文档内容",
        chunk_type="text", document_name="西安旅游攻略.docx", source_page=1,
        source_section=None, source_table=None, source_figure=None,
    )

    class Store:
        def __init__(self):
            self.calls = 0

        def list_documents(self):
            self.calls += 1
            return (
                SimpleNamespace(id=included_id, status=evaluate.DocumentStatus.ready),
                SimpleNamespace(id=excluded_id, status=evaluate.DocumentStatus.ready),
            )

        def get_documents_with_chunks(self, document_ids):
            assert document_ids == {included_id}
            return {included_id: (SimpleNamespace(status=evaluate.DocumentStatus.ready), {included_chunk_id: included_chunk})}

    class Chroma:
        def query(self, query, *, document_ids=(), limit):
            assert query == "三亚景点"
            assert document_ids == (included_id,)
            return (SimpleNamespace(chunk_id=included_chunk_id, document_id=included_id, score=0.8),)

    service = evaluate.RetrievalService.__new__(evaluate.RetrievalService)
    service.settings = SimpleNamespace(knowledge_search_result_limit=1)
    service.document_store = Store()
    service.chroma = Chroma()
    monkeypatch.setattr(evaluate, "parse_query", lambda query: SimpleNamespace(region=None))
    def search(chunks, parsed, *, document_ids=(), limit):
        assert_document_ids(document_ids, included_id)
        return ()

    monkeypatch.setattr(evaluate, "search_chunks", search)
    monkeypatch.setattr(
        evaluate, "merge_ranked_hits",
        lambda semantic, keyword, **kwargs: (SimpleNamespace(chunk_id=included_chunk_id, document_id=included_id, matched_by="semantic"),),
    )

    results = service.retrieve("  三亚景点  ", document_ids=(included_id,))

    assert [result.content for result in results] == ["包含文档内容"]
    assert service.document_store.calls == 1


def assert_document_ids(document_ids, expected_id):
    assert document_ids == (expected_id,)
    return True
