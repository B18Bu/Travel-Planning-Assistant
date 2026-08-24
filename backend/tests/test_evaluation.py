import pytest

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


class FakeDeepSeek:
    def __init__(self, response: str):
        self.response = response

    async def chat_completion(self, system, user):
        return self.response


@pytest.mark.asyncio
async def test_judge_faithfulness_parses_supported_ratio():
    judge = Judge(FakeDeepSeek("1|支持|a\n2|支持|b\n3|不支持|c"))
    assert await judge.faithfulness("q", "答", []) == pytest.approx(2 / 3)
