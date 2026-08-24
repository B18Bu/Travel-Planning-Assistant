"""DeepSeek 裁判：为 RAG 评估计算四项指标。"""
from __future__ import annotations

import re
from typing import Any, Sequence

from app.services.deepseek import DeepSeekClient
from app.services.resilience import ExternalServiceUnavailable

_SYSTEM = (
    "你是严谨的 RAG 质量评估裁判。只依据给定材料与规则判断，"
    "输出严格遵守规定的格式，不要输出任何额外说明。"
)


def _parse_verdict_lines(
    text: str, verdict_yes: str, verdict_no: str
) -> list[tuple[int, bool, str]]:
    """解析「编号|判定|陈述」行；无法解析的行直接跳过。"""
    rows: list[tuple[int, bool, str]] = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 3:
            continue
        num, verdict, statement = (part.strip() for part in parts)
        if not num.isdigit() or verdict not in (verdict_yes, verdict_no):
            continue
        rows.append((int(num), verdict == verdict_yes, statement))
    return rows


def _parse_pair_lines(
    text: str, verdict_yes: str, verdict_no: str
) -> list[tuple[int, bool]]:
    """解析「编号|判定」行。"""
    pairs: list[tuple[int, bool]] = []
    for line in text.splitlines():
        parts = line.split("|", 1)
        if len(parts) != 2:
            continue
        num, verdict = (part.strip() for part in parts)
        if not num.isdigit() or verdict not in (verdict_yes, verdict_no):
            continue
        pairs.append((int(num), verdict == verdict_yes))
    return pairs


def _context_precision(relevant_positions: set[int], total: int) -> float:
    """RAGAS 上下文准确率 CP@k = Σ_k(P@k × v_k) / R。"""
    if not relevant_positions or total <= 0:
        return 0.0
    relevant_in_k = 0
    acc = 0.0
    for k in range(1, total + 1):
        if k in relevant_positions:
            relevant_in_k += 1
            acc += relevant_in_k / k
    return acc / len(relevant_positions)


class Judge:
    """用 DeepSeek 计算四项 RAG 指标的裁判。"""

    def __init__(self, client: DeepSeekClient) -> None:
        self._client = client

    async def _ask(self, user_prompt: str) -> str:
        return await self._client.chat_completion(_SYSTEM, user_prompt)

    @staticmethod
    def _context_text(results: Sequence[Any]) -> str:
        return "\n".join(f"[{i}] {result.content}" for i, result in enumerate(results, 1))

    async def faithfulness(
        self, question: str, answer: str, context_results: Sequence[Any]
    ) -> float | None:
        prompt = (
            f"用户问题：{question}\n\n检索片段：\n{self._context_text(context_results)}\n\n"
            f"待判断的回答：\n{answer}\n\n"
            "任务：把回答拆分为若干独立事实陈述，逐条判断该陈述是否被上述检索片段支持"
            "（支持=能从片段推断，不支持=片段没有依据）。\n"
            "每行严格输出：<编号>|<支持|不支持>|<陈述内容>\n示例：\n1|支持|三亚有天涯海角景区"
        )
        raw = await self._ask(prompt)
        rows = _parse_verdict_lines(raw, "支持", "不支持")
        if not rows:
            return None
        return sum(1 for _, ok, _ in rows if ok) / len(rows)

    async def context_recall(
        self, question: str, reference_answer: str, context_results: Sequence[Any]
    ) -> float | None:
        prompt = (
            f"用户问题：{question}\n\n检索片段：\n{self._context_text(context_results)}\n\n"
            f"参考答案（golden）：\n{reference_answer}\n\n"
            "任务：把参考答案拆分为若干独立事实陈述，逐条判断该陈述是否可从上述检索片段归因"
            "（可归因=片段包含该事实或可推断，不可归因=片段中没有）。\n"
            "每行严格输出：<编号>|<可归因|不可归因>|<陈述内容>"
        )
        raw = await self._ask(prompt)
        rows = _parse_verdict_lines(raw, "可归因", "不可归因")
        if not rows:
            return None
        return sum(1 for _, ok, _ in rows if ok) / len(rows)

    async def context_precision(
        self, question: str, context_results: Sequence[Any]
    ) -> float | None:
        prompt = (
            f"用户问题：{question}\n\n检索片段（按当前排序）：\n{self._context_text(context_results)}\n\n"
            "任务：逐条判断每个检索片段是否与回答该问题相关。\n"
            "每行严格输出：<编号>|<相关|不相关>\n示例：\n1|相关\n2|不相关"
        )
        raw = await self._ask(prompt)
        pairs = _parse_pair_lines(raw, "相关", "不相关")
        relevant = {num for num, ok in pairs if ok}
        return _context_precision(relevant, len(context_results))

    async def answer_relevance(self, question: str, answer: str) -> float | None:
        prompt = (
            f"用户问题：{question}\n\n生成回答：\n{answer}\n\n"
            "任务：从 0 到 1 评分该回答是否切题、充分回答用户问题"
            "（1=完全切题且充分，0=完全无关）。\n"
            "只输出：<0-1数字>|<一句话理由>"
        )
        raw = await self._ask(prompt)
        match = re.match(r"\s*([0-9]*\.?[0-9]+)\s*\|", raw)
        if not match:
            return None
        try:
            return max(0.0, min(1.0, float(match.group(1))))
        except ValueError:
            return None
