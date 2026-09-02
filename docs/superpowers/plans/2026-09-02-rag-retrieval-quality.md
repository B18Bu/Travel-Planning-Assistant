# RAG 检索质量与提示优化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 提升知识库检索的旅游意图匹配与结果去重质量，并向用户反馈具体的无结果原因。

**架构：** 在确定性关键词检索中加入旅游修饰词，仍由现有向量检索、关键词检索和 RRF 完成候选融合。API 在融合后按规范化内容精确去重，并基于可检索文档和地区过滤结果生成受控空结果原因；前端只映射受控原因代码至操作建议。

**技术栈：** Python 3.12、FastAPI、Pydantic、pytest、原生 JavaScript。

---

## 文件结构

- 修改：`backend/app/services/keyword_search.py` — 识别旅游查询修饰词并纳入关键词计分。
- 修改：`backend/app/models/documents.py` — 为检索响应增加受控空结果原因。
- 修改：`backend/app/api/documents.py` — 放宽 RRF 候选数、精确去重并计算空结果原因。
- 修改：`backend/tests/test_keyword_search.py` — 验证修饰词提升相关片段排序。
- 修改：`backend/tests/test_documents_api.py` — 验证去重及三类空结果原因。
- 修改：`frontend/app.js` — 映射空结果原因并显示明确引导。
- 修改：`backend/tests/test_frontend_assets.py` — 锁定前端受控原因映射与安全异常文案。

### 任务 1：旅游修饰词计分

**文件：**
- 修改：`backend/tests/test_keyword_search.py`
- 修改：`backend/app/services/keyword_search.py`

- [ ] **步骤 1：编写失败的排序测试**

在 `backend/tests/test_keyword_search.py` 添加：

```python
def test_search_chunks_prioritizes_travel_modifier_over_generic_intent_match():
    generic = make_chunk("成都博物馆展览介绍", document_name="成都玩法.docx")
    family = make_chunk("成都亲子博物馆活动与儿童互动项目", document_name="成都玩法.docx")

    hits = search_chunks(
        [generic, family],
        parse_query("成都亲子博物馆"),
        limit=2,
    )

    assert [hit.chunk_id for hit in hits] == [UUID(str(family.id)), UUID(str(generic.id))]
```

- [ ] **步骤 2：运行测试并验证失败**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_keyword_search.py::test_search_chunks_prioritizes_travel_modifier_over_generic_intent_match -v`

预期：FAIL。当前解析把“亲子博物馆”作为一个整体词，不能稳定将“亲子”作为独立的旅游修饰词计分。

- [ ] **步骤 3：实现修饰词提取**

在 `backend/app/services/keyword_search.py` 的 `STOPWORDS` 后添加固定词典，并将 `_significant_terms` 替换为以下实现：

```python
TRAVEL_MODIFIERS = (
    "亲子", "儿童", "老人", "情侣", "室内", "雨天", "避暑", "慢游",
    "自驾", "徒步", "夜游", "摄影", "露营", "文化", "历史",
)


def _significant_terms(query: str, city: str | None) -> tuple[str, ...]:
    cleaned = query
    if city is not None:
        index = cleaned.find(city)
        if index >= 0:
            cleaned = cleaned[:index] + cleaned[index + len(city):]
    if cleaned.startswith("市"):
        cleaned = cleaned[1:]
    if cleaned.endswith("市"):
        cleaned = cleaned[:-1]
    for stopword in STOPWORDS:
        cleaned = cleaned.replace(stopword, "")
    modifiers = [modifier for modifier in TRAVEL_MODIFIERS if modifier in cleaned]
    raw_terms = re.findall(r"[一-鿿]+", cleaned)
    return tuple(dict.fromkeys((*modifiers, *raw_terms)))
```

不改动 `_score_chunk`：它已为 `ParsedQuery.significant_terms` 中每个命中词加一分，因此新词将自然参与排序。

- [ ] **步骤 4：运行关键词测试并验证通过**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_keyword_search.py -q`

预期：全部通过，新增测试中亲子片段排在通用博物馆片段之前。

### 任务 2：融合结果精确去重与空结果原因

**文件：**
- 修改：`backend/tests/test_documents_api.py`
- 修改：`backend/app/models/documents.py`
- 修改：`backend/app/api/documents.py`

- [ ] **步骤 1：编写失败的 API 测试**

在 `backend/tests/test_documents_api.py` 添加三项测试：

```python
@pytest.mark.asyncio
async def test_knowledge_search_deduplicates_whitespace_equivalent_chunks(tmp_path):
    from app.services.chroma_store import ChromaSearchHit

    app, record, chunk, chroma = app_with_documents(tmp_path)
    primary = chunk.model_copy(update={"content": "成都 亲子游 攻略"})
    duplicate = chunk.model_copy(update={"id": str(uuid4()), "content": "成都\n亲子游  攻略"})
    distinct = chunk.model_copy(update={"id": str(uuid4()), "content": "成都室内亲子场所攻略", "source_page": 2})
    ready = app.state.document_store.get_document(record.id).model_copy(update={"chunk_count": 3, "text_chunk_count": 3})
    app.state.document_store.save_processed_document(ready, [primary, duplicate, distinct])
    chroma.hits = tuple(ChromaSearchHit(chunk_id=item.id, document_id=record.id, score=0.9 - index * 0.1) for index, item in enumerate([primary, duplicate, distinct]))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": "成都亲子游", "document_ids": []})

    assert response.status_code == 200
    assert [item["content"] for item in response.json()["results"]] == ["成都 亲子游 攻略", "成都室内亲子场所攻略"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "setup", "reason"),
    [
        ("成都亲子游", "no_ready", "no_ready_documents"),
        ("三亚亲子游", "other_region", "no_region_documents"),
        ("成都夜游", "no_match", "no_matching_chunks"),
    ],
)
async def test_knowledge_search_returns_controlled_empty_reason(tmp_path, query, setup, reason):
    app, record, _chunk, chroma = app_with_documents(tmp_path)
    if setup == "no_ready":
        processing = app.state.document_store.get_document(record.id).model_copy(update={"status": DocumentStatus.processing, "chunk_count": 0, "text_chunk_count": 0})
        state = app.state.document_store._read_state()
        state["documents"][app.state.document_store._find_document_index(state, record.id)] = processing.model_dump(mode="json")
        app.state.document_store._write_state(state)
    elif setup == "other_region":
        chroma.hits = ()
    elif setup == "no_match":
        chroma.hits = ()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": query, "document_ids": []})

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["empty_reason"] == reason
```

在实现时，拆分参数化测试中的 `setup` 逻辑：`other_region` 需要保留成都 ready 文档并查询三亚；`no_match` 需要保留成都 ready 文档且令 Chroma 命中为空。

- [ ] **步骤 2：运行测试并验证失败**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_documents_api.py -v -k "deduplicates_whitespace_equivalent_chunks or controlled_empty_reason"`

预期：FAIL。当前响应没有 `empty_reason`，融合结果不会按内容去重。

- [ ] **步骤 3：扩展响应模型与 API 实现**

在 `KnowledgeSearchResponse` 添加：

```python
empty_reason: Literal[
    "no_ready_documents", "no_region_documents", "no_matching_chunks"
] | None = None
```

在 `backend/app/api/documents.py` 添加并使用两个辅助函数：

```python
def _normalized_chunk_content(content: str) -> str:
    return " ".join(content.split()).casefold()


def _deduplicate_ranked_hits(ranked, chunks_by_id, limit: int):
    selected = []
    seen = set()
    for hit in ranked:
        chunk = chunks_by_id.get(hit.chunk_id)
        if chunk is None:
            continue
        fingerprint = _normalized_chunk_content(chunk.content)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        selected.append(hit)
        if len(selected) == limit:
            break
    return tuple(selected)


def _empty_reason(ready_records, query_region: str | None, results) -> str | None:
    if results:
        return None
    if not ready_records:
        return "no_ready_documents"
    if query_region is not None and not any(region_from_document_name(record.filename) == query_region for record in ready_records):
        return "no_region_documents"
    return "no_matching_chunks"
```

调用 `merge_ranked_hits` 时传入 `limit=fetch_limit`，再以 `_deduplicate_ranked_hits(..., result_limit)` 得到最终候选。构建响应时传入 `empty_reason=_empty_reason(ready_records, parsed.region, results)`；`ready_records` 必须是已按 `document_ids` 范围过滤后的 ready 文档列表。

- [ ] **步骤 4：运行 API 测试并验证通过**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_documents_api.py -q`

预期：全部通过，重复内容仅返回一次，三个空结果场景各自返回对应原因代码。

### 任务 3：前端空结果引导与异常提示

**文件：**
- 修改：`backend/tests/test_frontend_assets.py`
- 修改：`frontend/app.js:1101-1110,1509-1550`

- [ ] **步骤 1：编写失败的前端资源测试**

在 `backend/tests/test_frontend_assets.py` 添加：

```python
def test_frontend_maps_controlled_knowledge_empty_reasons_without_exposing_backend_errors():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    for reason in ("no_ready_documents", "no_region_documents", "no_matching_chunks"):
        assert reason in script
    assert "暂无可检索资料，请先上传文档并等待处理完成。" in script
    assert "目标地区暂无已处理资料，请更换地区或上传相关攻略。" in script
    assert "未找到相关内容，请尝试更具体的景点、玩法或主题关键词。" in script
    assert "检索引擎暂时不可用，请稍后重试。" in script
```

- [ ] **步骤 2：运行测试并验证失败**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py::test_frontend_maps_controlled_knowledge_empty_reasons_without_exposing_backend_errors -v`

预期：FAIL。当前前端仅显示“未找到匹配的已处理文档内容”或泛化的服务不可用提示。

- [ ] **步骤 3：实现前端受控映射**

在 `frontend/app.js` 的 `renderKnowledgeResults` 前添加：

```javascript
const knowledgeEmptyMessages = {
  no_ready_documents: "暂无可检索资料，请先上传文档并等待处理完成。",
  no_region_documents: "目标地区暂无已处理资料，请更换地区或上传相关攻略。",
  no_matching_chunks: "未找到相关内容，请尝试更具体的景点、玩法或主题关键词。",
};
```

将函数签名改为 `function renderKnowledgeResults(results, emptyReason = null)`，并在空结果分支使用：

```javascript
empty.textContent = knowledgeEmptyMessages[emptyReason] || knowledgeEmptyMessages.no_matching_chunks;
```

调用处改为：

```javascript
renderKnowledgeResults(
  Array.isArray(payload.results) ? payload.results : [],
  typeof payload.empty_reason === "string" ? payload.empty_reason : null,
);
```

将检索请求失败分支的文字改为：

```javascript
message.textContent = "检索引擎暂时不可用，请稍后重试。";
```

- [ ] **步骤 4：运行前端资源测试并验证通过**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py::test_frontend_maps_controlled_knowledge_empty_reasons_without_exposing_backend_errors -v`

预期：1 passed。

### 任务 4：回归验证

**文件：**
- 验证：`backend/tests/test_keyword_search.py`
- 验证：`backend/tests/test_documents_api.py`
- 验证：`backend/tests/test_frontend_assets.py`

- [ ] **步骤 1：运行关联测试集**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_keyword_search.py backend/tests/test_documents_api.py backend/tests/test_frontend_assets.py -q`

预期：全部通过。

- [ ] **步骤 2：运行完整后端测试集**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests -q`

预期：全部通过，无失败或跳过。

- [ ] **步骤 3：检查变更范围**

运行：`git diff --check; git status --short`

预期：无空白错误；仅出现计划列出的实现、测试、规格与计划文档，既有本地运行产物仍保持未跟踪。
