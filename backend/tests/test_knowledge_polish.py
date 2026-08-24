import pytest

from app.models.documents import KnowledgeSearchResult, SourceLocation
from app.services.knowledge_polish import KnowledgePolisher
from app.services.resilience import ExternalServiceUnavailable


class FakeDeepSeek:
    def __init__(self, result="润色后的完整回答。" * 6, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def chat_completion(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if self.error is not None:
            raise self.error
        return self.result


def snippet(content, document_name="成都美食攻略.docx", page=2, section=None):
    return KnowledgeSearchResult(
        content=content,
        chunk_type="text",
        score=0.8,
        source=SourceLocation(document_name=document_name, page=page, section=section),
    )


@pytest.mark.asyncio
async def test_polish_returns_llm_answer_and_includes_query_and_snippets():
    fake = FakeDeepSeek()
    polisher = KnowledgePolisher(fake)
    piece = "成都火锅以麻辣著称。"
    answer = await polisher.polish("成都美食推荐", (snippet(piece),))

    assert answer == fake.result
    system_prompt, user_prompt = fake.calls[0]
    assert "成都美食推荐" in user_prompt
    assert piece in user_prompt
    assert "成都美食攻略.docx" in user_prompt
    assert "第 2 页" in user_prompt
    assert "仅依据" in system_prompt


@pytest.mark.asyncio
async def test_polish_returns_none_when_llm_unavailable():
    fake = FakeDeepSeek(error=ExternalServiceUnavailable("熔断中"))
    polisher = KnowledgePolisher(fake)

    assert await polisher.polish("成都美食推荐", (snippet("内容"),)) is None


@pytest.mark.asyncio
async def test_polish_skips_llm_call_without_results():
    fake = FakeDeepSeek()
    polisher = KnowledgePolisher(fake)

    assert await polisher.polish("成都美食推荐", ()) is None
    assert fake.calls == []
