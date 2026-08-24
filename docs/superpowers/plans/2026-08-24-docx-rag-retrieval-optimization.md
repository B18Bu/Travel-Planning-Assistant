# DOCX 结构化分块与检索优化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为旅游方案 DOCX 保留标题路径和表格语义，按结构边界分块，并将混合检索最终结果数提升至 12、候选数提升至 36。

**架构：** `document_extractors.py` 把 DOCX 转为带标题路径和保序元数据的内容项，再由同一模块按正文、表格和 OCR 三类规则生成 `DocumentChunk`。`documents.py` 使用 `Settings` 的最终 Top-K 计算双路候选数量，将标准化查询与文档范围一致地传给语义、关键词检索。既有 Chroma、BGE、RRF 和 DocumentStore 的职责不变。

**技术栈：** Python 3、FastAPI、Pydantic Settings、python-docx、Chroma、pytest、httpx。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `backend/app/services/document_extractors.py` | 提取 DOCX 标题路径、表格语义，完成结构感知的正文/表格/OCR 分块。 |
| `backend/app/services/document_processor.py` | 使单张图片 OCR 的运行时异常降级为跳过该图，不影响正文和表格入库。 |
| `backend/app/api/documents.py` | 读取可配置 Top-K、计算 3 倍候选数、拒绝空白查询并将文档范围传给关键词检索。 |
| `backend/app/config.py` | 定义并校验 `knowledge_search_result_limit`，默认 12、范围 1—50。 |
| `backend/.env.example` | 记录 `KNOWLEDGE_SEARCH_RESULT_LIMIT=12` 的用途、单位和后端边界。 |
| `backend/tests/test_document_extractors.py` | 覆盖标题路径、正文聚合、自然边界、表格语义与 OCR 块来源。 |
| `backend/tests/test_document_processor.py` | 覆盖 Qwen-VL 单图异常时正文/表格继续入库。 |
| `backend/tests/test_documents_api.py` | 覆盖 Top-K/候选数、空白查询和指定文档的关键词范围。 |
| `backend/tests/test_keyword_search.py` | 覆盖 36 条候选下的关键词文档范围与 RRF 行为。 |
| `backend/tests/test_config.py` | 覆盖检索结果上限的默认值、环境变量覆盖和非法值拒绝。 |

## 任务 1：为结构化内容项与 DOCX 分块建立失败测试

**文件：**
- 修改：`backend/tests/test_document_extractors.py`
- 修改：`backend/app/services/document_extractors.py`

- [ ] **步骤 1：为标题路径、原始顺序和表格键值语义编写失败测试**

在 `backend/tests/test_document_extractors.py` 增加一个真实 `python-docx` 文档：`Heading 1` 为“第三章 产品设计”、`Heading 2` 为“三日游线路”，其后写入两段正文和一个两列表格。断言提取项包含下列结构：

```python
assert extracted[2]["section_path"] == ("第三章 产品设计", "三日游线路")
assert extracted[2]["source_section"] == "第三章 产品设计 > 三日游线路"
assert [item["source_order"] for item in extracted] == [0, 1, 2, 3]
assert extracted[3]["content"] == (
    "章节：第三章 产品设计 > 三日游线路\n"
    "表格 1\n"
    "表头：日期 | 行程\n"
    "第 1 行：日期=第一天；行程=宽窄巷子"
)
```

- [ ] **步骤 2：运行新测试，确认因字段/表格格式缺失而失败**

运行：

```bash
cd backend && pytest tests/test_document_extractors.py -q
```

预期：FAIL；失败原因是当前提取项没有 `section_path`/`source_order`，且表格文本仍是 `日期 | 行程` 的简单拼接。

- [ ] **步骤 3：实现标题路径和表格标准化辅助函数**

在 `backend/app/services/document_extractors.py` 添加下列私有辅助函数，并将 `extract_docx` 的 `current_section` 改为标题路径列表：

```python
def _heading_level(style_name: str) -> int | None:
    match = re.search(r"(?:Heading|标题)\s*(\d+)", style_name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _section_name(section_path: list[str]) -> str:
    return " > ".join(section_path) if section_path else "正文"


def _format_table(section: str, table_index: int, rows: list[list[str]]) -> str:
    non_empty_rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not non_empty_rows:
        return ""
    header = non_empty_rows[0]
    lines = [f"章节：{section}", f"表格 {table_index}", f"表头：{' | '.join(header)}"]
    for row_index, row in enumerate(non_empty_rows[1:], start=1):
        pairs = [
            f"{header[column] if column < len(header) and header[column] else f'第 {column + 1} 列'}={value}"
            for column, value in enumerate(row)
        ]
        lines.append(f"第 {row_index} 行：{'；'.join(pairs)}")
    return "\n".join(lines)
```

在正文和图片项中写入 `section_path=tuple(section_path)`、`source_section=_section_name(section_path)` 和递增的 `source_order`；标题本身仍作为 `text` 项输出。表格以 `_format_table()` 的结果作为 `content`，保留已有 `source_table`。

- [ ] **步骤 4：运行提取测试，确认标题路径和表格语义通过**

运行：

```bash
cd backend && pytest tests/test_document_extractors.py -q
```

预期：PASS；已有正文、表格、嵌入图片和 PDF 提取测试也保持通过。

- [ ] **步骤 5：为正文聚合、句子边界、表格重复表头和 OCR 来源编写失败测试**

在同一测试文件新增以下四类测试：

```python
def test_chunking_combines_consecutive_text_in_one_section_and_keeps_table_as_boundary():
    items = [
        {"content": "第一段。", "chunk_type": "text", "section_path": ("线路",), "source_section": "线路", "source_order": 0},
        {"content": "第二段。", "chunk_type": "text", "section_path": ("线路",), "source_section": "线路", "source_order": 1},
        {"content": "章节：线路\n表格 1\n表头：日期\n第 1 行：日期=第一天", "chunk_type": "table", "source_section": "线路", "source_table": 1, "source_order": 2},
        {"content": "表格后的正文。", "chunk_type": "text", "section_path": ("线路",), "source_section": "线路", "source_order": 3},
    ]
    chunks = chunk_extracted_content(uuid4(), "方案.docx", items)
    assert chunks[0].content == "章节：线路\n\n第一段。\n\n第二段。"
    assert chunks[1].chunk_type == "table"
    assert chunks[2].content == "章节：线路\n\n表格后的正文。"


def test_chunking_prefers_sentence_boundary_and_only_overlaps_text_body():
    text = "甲。" * 401
    chunks = chunk_extracted_content(uuid4(), "方案.docx", [{"content": text, "chunk_type": "text", "source_section": "线路"}])
    assert all(len(chunk.content) <= 800 for chunk in chunks)
    assert chunks[0].content.endswith("。")
    assert chunks[1].content.startswith("章节：线路\n\n")


def test_chunking_repeats_table_context_and_header_for_each_row_group():
    # 以足够多的短行构造超过 800 字符的格式化表格。
    ...


def test_chunking_chart_ocr_includes_section_and_figure_marker():
    chunks = chunk_extracted_content(uuid4(), "方案.docx", [{"content": "客流量", "chunk_type": "chart_ocr", "source_section": "市场", "source_figure": 2}])
    assert chunks[0].content == "章节：市场\n图表 2\n\n客流量"
```

表格测试需断言每个表格块都有 `章节：`、`表格 1`、`表头：`，且块长度不超过 800。

- [ ] **步骤 6：运行新增分块测试，确认当前逐项滑窗行为失败**

运行：

```bash
cd backend && pytest tests/test_document_extractors.py -q
```

预期：FAIL；当前实现不会合并相邻正文、不会添加章节/图表前缀，且表格不会按行组重复表头。

- [ ] **步骤 7：实现正文、表格和 OCR 的结构感知分块**

在 `document_extractors.py` 中将 `chunk_extracted_content()` 拆为以下私有函数，并由主函数按 `source_order` 顺序调度：

```python
def _chunk_text_group(document_id, document_name, items, max_chars, overlap) -> list[DocumentChunk]: ...
def _chunk_table_item(document_id, document_name, item, max_chars) -> list[DocumentChunk]: ...
def _chunk_chart_item(document_id, document_name, item, max_chars, overlap) -> list[DocumentChunk]: ...
def _split_at_natural_boundary(text: str, limit: int) -> int: ...
```

具体约束：

```python
prefix = f"章节：{source_section}\n\n" if source_section != "正文" else ""
body_limit = max_chars - len(prefix)
cut = _split_at_natural_boundary(remaining_body, body_limit)
body = remaining_body[:cut]
next_start = max(cut - overlap, 0)
```

`_split_at_natural_boundary()` 依序在 `\n\n`、`。！？；`、最后一个 `\n` 查找不超过 `limit` 的切点；找不到时返回 `limit`。`char_start`/`char_end` 指向不含标题前缀的正文聚合文本偏移。

表格拆分必须先从格式化文本中分离前三行（章节、表格、表头），再逐条追加 `第 N 行`；下一个块重复三行上下文。单行超过剩余容量时生成 `第 N 行（续）`，每个续块仍写入这三行上下文。`chart_ocr` 使用 `章节：<section>\n图表 <index>\n\n` 前缀，并复用自然边界文本分块。

- [ ] **步骤 8：运行分块测试，确认所有 DOCX/分块用例通过**

运行：

```bash
cd backend && pytest tests/test_document_extractors.py -q
```

预期：PASS；所有正文块、表格块、OCR 块均不超过 800 字符。

- [ ] **步骤 9：Commit**

```bash
git add backend/app/services/document_extractors.py backend/tests/test_document_extractors.py
git commit -m "feat: preserve DOCX structure in retrieval chunks"
```

预期：创建仅包含 DOCX 提取与分块变更的提交。

## 任务 2：保证 OCR 单项故障不阻断 DOCX 入库

**文件：**
- 修改：`backend/tests/test_document_processor.py`
- 修改：`backend/app/services/document_processor.py`

- [ ] **步骤 1：为 Qwen-VL 运行时异常编写失败测试**

在 `backend/tests/test_document_processor.py` 新增一个 `qwen_vl.recognize_chart()` 抛出 `RuntimeError` 的 fake，并用含一个 `text`、一个 `table` 和一个 `chart_ocr` 项目的 `_extract` fake 驱动 `processor.process()`：

```python
await processor.process(record.id)
ready = store.get_document(record.id)
assert ready.status is DocumentStatus.ready
assert ready.text_chunk_count == 1
assert ready.table_chunk_count == 1
assert ready.chart_ocr_chunk_count == 0
assert chroma.upserted_chunks[0].chunk_type == "text"
assert chroma.upserted_chunks[1].chunk_type == "table"
```

- [ ] **步骤 2：运行处理器测试，确认 OCR 异常当前会导致文档失败**

运行：

```bash
cd backend && pytest tests/test_document_processor.py -q
```

预期：FAIL；`recognize_chart()` 的异常传播到 `process()`，记录被标记为 `failed` 或未写入正文/表格块。

- [ ] **步骤 3：对单图 OCR 调用实施局部降级**

在 `DocumentProcessor._with_chart_ocr()` 中只包裹调用与结果读取，不扩大 `process()` 的总体异常边界：

```python
try:
    result = await self.qwen_vl.recognize_chart(image_bytes, media_type)
except Exception:
    continue
text = result.get("text") if isinstance(result, dict) else None
if isinstance(text, str) and text.strip():
    normalized.append(
        {key: value for key, value in item.items() if key != "image_bytes"}
        | {"content": text.strip()}
    )
```

保留现有安全路径、媒体类型和空 OCR 文本跳过逻辑；不要吞掉 `_extract`、分块、embedding 或 Chroma 失败。

- [ ] **步骤 4：运行处理器测试，确认降级不阻断正文/表格入库**

运行：

```bash
cd backend && pytest tests/test_document_processor.py -q
```

预期：PASS；现有处理状态流转、向量清理和 OCR 成功测试保持通过。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/services/document_processor.py backend/tests/test_document_processor.py
git commit -m "fix: degrade DOCX chart OCR failures"
```

预期：创建仅包含 OCR 局部降级变更的提交。

## 任务 3：将检索 Top-K 配置为 12 并记录环境变量

**文件：**
- 修改：`backend/tests/test_config.py`
- 修改：`backend/app/config.py`
- 修改：`backend/.env.example`

- [ ] **步骤 1：为默认值、覆盖和非法值编写失败测试**

在 `backend/tests/test_config.py` 添加：

```python
def test_knowledge_search_result_limit_defaults_to_twelve():
    assert Settings(_env_file=None).knowledge_search_result_limit == 12

@pytest.mark.parametrize("value", [0, -1, 51, True, False, "1.2", 1.2, "not-a-number"])
def test_settings_rejects_invalid_knowledge_search_result_limit(value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, knowledge_search_result_limit=value)

def test_settings_accepts_knowledge_search_result_limit_from_dotenv_string():
    assert Settings(_env_file=None, knowledge_search_result_limit="36").knowledge_search_result_limit == 36
```

在环境示例测试的变量列表和字段列表中加入 `KNOWLEDGE_SEARCH_RESULT_LIMIT` / `knowledge_search_result_limit`，并断言其注释包含“默认值：12”“范围：1—50”“仅后端控制，客户端不可覆盖”。

- [ ] **步骤 2：运行配置测试，确认配置字段尚不存在而失败**

运行：

```bash
cd backend && pytest tests/test_config.py -q
```

预期：FAIL；`Settings` 没有 `knowledge_search_result_limit` 字段，环境示例不含对应变量。

- [ ] **步骤 3：新增受控检索结果上限配置**

在 `Settings` 的文档配置字段后新增：

```python
# 知识检索最终返回结果数，默认值：12，范围：1—50；仅由后端控制，不接受客户端覆盖。
knowledge_search_result_limit: int = Field(default=12, ge=1, le=50)
```

将该字段加入 `validate_external_integer_settings()` 的字段列表。随后在 `backend/.env.example` 的 `DOCUMENT_BATCH_MAX_FILES` 后写入：

```dotenv
# 知识检索最终返回结果数，默认值：12，范围：1—50；仅后端控制，客户端不可覆盖。
KNOWLEDGE_SEARCH_RESULT_LIMIT=12
```

将字段加入 `test_config.py` 的默认值、环境解析和相邻注释映射表。

- [ ] **步骤 4：运行配置测试，确认默认值、覆盖和边界校验通过**

运行：

```bash
cd backend && pytest tests/test_config.py -q
```

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/config.py backend/.env.example backend/tests/test_config.py
git commit -m "feat: configure knowledge search result limit"
```

预期：创建仅包含 Top-K 配置及其文档测试的提交。

## 任务 4：统一 API 的检索数量、范围过滤和查询标准化

**文件：**
- 修改：`backend/tests/test_documents_api.py`
- 修改：`backend/tests/test_keyword_search.py`
- 修改：`backend/app/api/documents.py`

- [ ] **步骤 1：为 API 的 36 候选、12 最终结果、关键词文档范围和空白查询编写失败测试**

在 `FakeChroma` 中记录最后一次查询参数：

```python
def query(self, query, *, document_ids=(), limit=5):
    self.last_query = (query, tuple(document_ids), limit)
    ...
```

新增 API 测试：

```python
async def test_knowledge_search_uses_three_times_candidate_limit_and_returns_twelve(tmp_path):
    app, record, first_chunk, chroma = app_with_documents(tmp_path)
    # 在同一 ready 文档中存入 15 个匹配正文块，并将 15 个 ChromaSearchHit 交给 fake。
    ...
    response = await client.post("/api/knowledge-search", json={"query": "正文", "document_ids": []})
    assert chroma.last_query[2] == 36
    assert len(response.json()["results"]) == 12

async def test_knowledge_search_passes_document_ids_to_keyword_search(tmp_path, monkeypatch):
    app, record, _chunk, _chroma = app_with_documents(tmp_path)
    other_record, other_chunk = ready_sanya_document(app.state.document_store)
    captured = {}
    original = documents_api.search_chunks
    def capture(chunks, parsed, *, document_ids=(), limit=5):
        captured["document_ids"] = tuple(document_ids)
        return original(chunks, parsed, document_ids=document_ids, limit=limit)
    monkeypatch.setattr(documents_api, "search_chunks", capture)
    response = await client.post("/api/knowledge-search", json={"query": "美食", "document_ids": [str(record.id)]})
    assert captured["document_ids"] == (record.id,)
    assert all(result["source"]["document_name"] != other_record.filename for result in response.json()["results"])

async def test_knowledge_search_rejects_whitespace_only_query_without_calling_search_backends(tmp_path):
    app, _record, _chunk, chroma = app_with_documents(tmp_path)
    response = await client.post("/api/knowledge-search", json={"query": "   ", "document_ids": []})
    assert response.status_code == 422
    assert not hasattr(chroma, "last_query")
```

在 `test_keyword_search.py` 增加 `limit=36`、两份文档和明确 `document_ids` 的回归断言，确认 `search_chunks()` 结果不含范围外 UUID。

- [ ] **步骤 2：运行 API 与关键词测试，确认候选数、范围传递和空白查询失败**

运行：

```bash
cd backend && pytest tests/test_documents_api.py tests/test_keyword_search.py -q
```

预期：FAIL；当前 Chroma 调用 limit 为 15，最终结果限制为 5，关键词调用没有传 `document_ids`，空白请求可能进入后端。

- [ ] **步骤 3：改用 Settings 驱动的检索限制并传递文档范围**

在 `backend/app/api/documents.py` 删除模块级 `_RESULT_LIMIT`，在 `search_knowledge()` 入口使用：

```python
query = payload.query.strip()
if not query:
    raise HTTPException(status_code=422, detail="检索内容不能为空")

result_limit = request.app.state.settings.knowledge_search_result_limit
fetch_limit = result_limit * 3
```

之后替换所有使用 `payload.query` 的检索输入为 `query`，并把关键词调用改为：

```python
keyword_hits = search_chunks(
    list(chunks_by_id.values()),
    parsed,
    document_ids=payload.document_ids,
    limit=fetch_limit,
)
```

RRF 调用的上限改为 `limit=result_limit`。生成润色、查询记录和响应中也使用 `query`，确保记录的查询与真正检索的内容一致。保留 `document_ids` 为空时检索所有 ready 文档的既有语义。

- [ ] **步骤 4：运行 API 与关键词测试，确认检索合同通过**

运行：

```bash
cd backend && pytest tests/test_documents_api.py tests/test_keyword_search.py -q
```

预期：PASS；指定文档范围下，语义、关键词和最终结果均不含其他文档。

- [ ] **步骤 5：运行文档相关回归测试**

运行：

```bash
cd backend && pytest tests/test_document_extractors.py tests/test_document_processor.py tests/test_keyword_search.py tests/test_documents_api.py tests/test_chroma_store.py tests/test_config.py -q
```

预期：PASS；无失败、错误或跳过以外的异常。

- [ ] **步骤 6：Commit**

```bash
git add backend/app/api/documents.py backend/tests/test_documents_api.py backend/tests/test_keyword_search.py
git commit -m "fix: expand and scope document retrieval"
```

预期：创建仅包含 API 检索数量、查询标准化和范围过滤变更的提交。

## 任务 5：执行全量验证与更新设计状态

**文件：**
- 修改：`docs/superpowers/specs/2026-08-24-docx-rag-retrieval-optimization-design.md`

- [ ] **步骤 1：运行整个后端测试套件**

运行：

```bash
cd backend && pytest -q
```

预期：PASS。若任何已有测试失败，先定位其是否因本次分块、Top-K 或 API 响应合同变化导致；修复生产实现，不得删除或放宽现有断言。

- [ ] **步骤 2：检查工作树仅包含本计划规定的变更**

运行：

```bash
git diff --check
git status --short
```

预期：`git diff --check` 无输出；新增或修改文件仅属于本计划文件结构列出的范围以及本计划/规格文档。

- [ ] **步骤 3：将设计规格状态更新为已实现并记录验证命令**

将规格文档第 4 行更新为：

```markdown
**状态：** 已实现并通过后端测试
```

在末尾新增：

```markdown
## 9. 实现验证

已执行：`cd backend && pytest -q`。
```

仅在步骤 1 确实通过后执行本步骤。

- [ ] **步骤 4：Commit**

```bash
git add docs/superpowers/specs/2026-08-24-docx-rag-retrieval-optimization-design.md docs/superpowers/plans/2026-08-24-docx-rag-retrieval-optimization.md
git commit -m "docs: record DOCX retrieval optimization plan"
```

预期：创建文档状态与实现计划的提交。
