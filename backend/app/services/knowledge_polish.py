from __future__ import annotations

from collections.abc import Sequence

from app.models.documents import KnowledgeSearchResult, SourceLocation
from app.services.deepseek import DeepSeekClient
from app.services.resilience import ExternalServiceUnavailable


_SYSTEM_PROMPT = (
    "你是智能文旅策划助手的知识库润色模块。你将收到用户问题与若干检索到的资料片段。"
    "请仅依据这些片段组织一份结构清晰、用户可读的 Markdown 回答。严格要求："
    "1. 只使用片段中的事实，不得编造或补充片段之外的内容；"
    "2. 尽量覆盖所有片段的关键信息；"
    "3. 对片段缺失、模糊或相互矛盾的内容明确标注「待核验」；"
    "4. 在回答末尾列出引用到的片段来源（文档名、页码或章节）；"
    "5. 只输出 Markdown，不要输出任何无关说明。"
)


class KnowledgePolisher:
    """将检索到的资料片段交由 DeepSeek 润色为完整 Markdown 回答；失败返回 None。"""

    def __init__(self, deepseek_client: DeepSeekClient) -> None:
        self.deepseek_client = deepseek_client

    async def polish(
        self, query: str, results: Sequence[KnowledgeSearchResult]
    ) -> str | None:
        if not results:
            return None
        user_prompt = self._user_prompt(query, results)
        try:
            return await self.deepseek_client.chat_completion(_SYSTEM_PROMPT, user_prompt)
        except ExternalServiceUnavailable:
            return None

    @staticmethod
    def _user_prompt(query: str, results: Sequence[KnowledgeSearchResult]) -> str:
        lines = [f"用户问题：{query}", "", "检索资料片段："]
        for index, result in enumerate(results, start=1):
            lines.append(f"[{index}] {result.content}（来源：{KnowledgePolisher._source_text(result.source)}）")
        return "\n".join(lines)

    @staticmethod
    def _source_text(source: SourceLocation) -> str:
        parts = [source.document_name]
        if source.page is not None:
            parts.append(f"第 {source.page} 页")
        if source.section is not None:
            parts.append(source.section)
        if source.table is not None:
            parts.append(f"表 {source.table}")
        if source.figure is not None:
            parts.append(f"图 {source.figure}")
        return " · ".join(parts)
