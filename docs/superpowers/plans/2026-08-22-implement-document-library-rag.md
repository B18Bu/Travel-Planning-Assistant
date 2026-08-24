# 文档库 RAG 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在不改变现有首页、出行规划和右侧搜索布局的前提下，实现 Word/PDF 文档库上传、异步 MinerU/Qwen-VL 解析、本地 BGE embedding、Chroma 持久化检索，以及可追溯的原文片段搜索。

**架构：** 浏览器上传文件后，后端创建 `pending` 文档记录并在 FastAPI `BackgroundTasks` 中完成解析、图表 OCR、切分、embedding 和 Chroma upsert。PDF 优先由 MinerU 解析，MinerU 不可用、超时或解析失败时使用 PyMuPDF 兜底；Qwen-VL OCR 不可用仅跳过图表块，不阻断正文和表格入库。`documents.json` 是状态与原文分块的唯一来源，Chroma 仅保存向量和白名单检索元数据；右侧自定义搜索调用 RAG API，仅显示可追溯原文，不调用 LLM 总结。

**技术栈：** FastAPI、Pydantic v2、ChromaDB、sentence-transformers、本地 `D:\作业\model\bge-small-zh-v1.5`、python-docx、PyMuPDF、MinerU 云端 API、Qwen-VL OCR 云端 API、pytest、httpx/respx。

**v1 约束：** 仅支持单进程、单实例的进程内后台任务；任务重启恢复、多实例锁和持久化队列不在本次范围。真实 MinerU 端到端调用需要运行环境提供受控短期 HTTPS 文件地址；未具备该条件时以 PyMuPDF 兜底并记录受控降级原因。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `backend/app/config.py` | 增加 MinerU、Qwen-VL、BGE、Chroma、文档数据目录和上传限制的后端配置。 |
| `backend/.env.example` | 增加空的 MinerU/Qwen-VL/BGE/Chroma 配置模板，永不写真实密钥。 |
| `backend/requirements.txt` | 固定 Chroma、embedding、Word/PDF 解析依赖。 |
| `backend/app/models/documents.py` | 定义文档、状态、切分块、检索请求/结果的严格合同。 |
| `backend/app/services/document_store.py` | 受控保存、读取、删除原文件/解析产物和 `documents.json` 元数据。 |
| `backend/app/services/mineru.py` | MinerU 云端异步 PDF 解析适配器。 |
| `backend/app/services/qwen_vl.py` | Qwen-VL 图表图片 OCR 适配器。 |
| `backend/app/services/document_extractors.py` | Word/PDF 文本、表格、图片抽取与 chunk 标准化。 |
| `backend/app/services/embeddings.py` | 本地 BGE 模型生命周期和 embedding 接口。 |
| `backend/app/services/chroma_store.py` | Chroma collection upsert/query/delete 和 metadata filter。 |
| `backend/app/services/document_processor.py` | 后台处理编排：解析 → OCR → chunk → embedding → Chroma → 状态更新。 |
| `backend/app/api/documents.py` | 文档上传、列表、详情、块浏览、删除、知识检索 API。 |
| `backend/app/main.py` | 注册文档 API、初始化文档服务状态和安全文件静态预览路由。 |
| `backend/tests/test_documents_models.py` | 文档合同测试。 |
| `backend/tests/test_document_store.py` | 文件/元数据持久化与级联删除测试。 |
| `backend/tests/test_document_extractors.py` | Word/PDF/表格/chart OCR chunk 标准化测试。 |
| `backend/tests/test_chroma_store.py` | Chroma upsert/query/filter/delete 测试。 |
| `backend/tests/test_documents_api.py` | 上传、状态、块浏览、删除、知识检索 API 测试。 |
| `backend/tests/test_frontend_assets.py` | 增加“文档库最小 UI 改动”视觉回归静态断言。 |
| `frontend/index.html` | 仅增加文档库导航、`view-library` 和搜索范围提示。 |
| `frontend/app.js` | 文档库视图切换、上传/删除/状态轮询、原文检索展示。 |
| `frontend/styles.css` | 仅新增文档库局部样式；不修改既有首页布局选择器。 |

数据目录在运行时创建，不提交真实文档：

```text
backend/data/uploads/
backend/data/extracted/
backend/data/chroma/
backend/data/documents.json
```

将 `backend/data/` 添加到 `.gitignore`。文档、解析产物和 Chroma 数据一律不得进入版本库。

---

### 任务 1：受控配置、依赖与文档合同

**文件：**
- 修改：`backend/requirements.txt`
- 修改：`backend/app/config.py`
- 修改：`backend/.env.example`
- 修改：`.gitignore`
- 创建：`backend/app/models/documents.py`
- 测试：`backend/tests/test_documents_models.py`
- 测试：`backend/tests/test_config.py`

- [ ] **步骤 1：编写失败的配置与模型测试**

新增 `test_documents_models.py`，定义期望 API：

```python
from app.models.documents import (
    DocumentChunk,
    DocumentRecord,
    DocumentStatus,
    KnowledgeSearchRequest,
)


def test_document_record_rejects_illegal_status_and_raw_error_detail():
    record = DocumentRecord(
        id="5f6bb8f6-0b24-4630-9f43-8a9a0d1c410d",
        filename="成都调研.pdf",
        media_type="application/pdf",
        status=DocumentStatus.pending,
        created_at="2026-08-22T00:00:00Z",
    )
    assert record.status is DocumentStatus.pending

    with pytest.raises(ValueError):
        DocumentRecord(
            id="5f6bb8f6-0b24-4630-9f43-8a9a0d1c410d",
            filename="成都调研.exe",
            media_type="application/x-msdownload",
            status=DocumentStatus.ready,
            created_at="2026-08-22T00:00:00Z",
        )


def test_document_chunk_limits_to_known_types_and_safe_metadata():
    chunk = DocumentChunk(
        id="f4e14ce5-11c1-4c42-bbdf-83edcd8fd739",
        document_id="5f6bb8f6-0b24-4630-9f43-8a9a0d1c410d",
        content="表 3：成都亲子游资源",
        chunk_type="table",
        document_name="成都调研.docx",
        source_table=3,
    )
    assert chunk.chunk_type == "table"

    with pytest.raises(ValueError):
        DocumentChunk(
            id="f4e14ce5-11c1-4c42-bbdf-83edcd8fd739",
            document_id="5f6bb8f6-0b24-4630-9f43-8a9a0d1c410d",
            content="x",
            chunk_type="raw_supplier_payload",
            document_name="报告.docx",
        )


def test_knowledge_search_defaults_to_global_library():
    request = KnowledgeSearchRequest(query="成都室内亲子场所")
    assert request.document_ids == ()
```

在 `test_config.py` 添加：

```python
def test_document_settings_are_backend_only_and_have_safe_defaults():
    settings = Settings(_env_file=None)

    assert settings.document_data_dir.endswith("backend/data")
    assert settings.document_max_upload_bytes > 0
    assert settings.chroma_collection_name == "travel_documents"
    assert settings.mineru_api_key == ""
    assert settings.qwen_vl_api_key == ""
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_documents_models.py backend/tests/test_config.py -q
```

预期：FAIL，原因是 `app.models.documents` 与新增 `Settings` 字段尚不存在。

- [ ] **步骤 3：添加依赖和后端配置**

在 `backend/requirements.txt` 添加固定依赖：

```text
chromadb==0.5.23
sentence-transformers==3.3.1
python-docx==1.1.2
PyMuPDF==1.25.1
python-multipart==0.0.20
```

在 `Settings` 中增加：

```python
# MinerU 云端 PDF 解析密钥，仅后端使用，不得暴露。
mineru_api_key: str = ""
mineru_base_url: str = "https://mineru.net"
# Qwen-VL 图表 OCR 密钥，仅后端使用，不得暴露。
qwen_vl_api_key: str = ""
qwen_vl_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
qwen_vl_model: str = "qwen-vl-max"
# 本地 BGE embedding 模型路径，仅后端读取。
bge_model_path: str = r"D:\作业\model\bge-small-zh-v1.5"
# 文档文件、解析产物和 Chroma 持久化目录，仅后端读取。
document_data_dir: str = str(Path(__file__).resolve().parents[1] / "data")
chroma_collection_name: str = "travel_documents"
document_max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0, le=100 * 1024 * 1024)
```

将 `document_max_upload_bytes` 加入现有整数配置 validator。

创建 `documents.py`，所有模型继承 `StrictModel`，只定义：

```python
class DocumentStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class DocumentRecord(StrictModel):
    id: UUIDV1ToV5
    filename: NonEmptyText
    media_type: Literal[
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime | None = None
    failure_message: NonEmptyText | None = None
    chunk_count: int = Field(default=0, ge=0)
    text_chunk_count: int = Field(default=0, ge=0)
    table_chunk_count: int = Field(default=0, ge=0)
    chart_ocr_chunk_count: int = Field(default=0, ge=0)


class DocumentChunk(StrictModel):
    id: UUIDV1ToV5
    document_id: UUIDV1ToV5
    content: NonEmptyText
    chunk_type: Literal["text", "table", "chart_ocr"]
    document_name: NonEmptyText
    source_page: int | None = Field(default=None, ge=1)
    source_section: NonEmptyText | None = None
    source_table: int | None = Field(default=None, ge=1)
    source_figure: int | None = Field(default=None, ge=1)
    image_path: str | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class KnowledgeSearchRequest(StrictModel):
    query: NonEmptyText
    document_ids: tuple[UUIDV1ToV5, ...] = Field(max_length=20)
```

在 `.env.example` 仅加入空值：

```text
MINERU_API_KEY=
MINERU_BASE_URL=https://mineru.net
QWEN_VL_API_KEY=
QWEN_VL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_VL_MODEL=qwen-vl-max
BGE_MODEL_PATH=D:\作业\model\bge-small-zh-v1.5
DOCUMENT_DATA_DIR=backend/data
CHROMA_COLLECTION_NAME=travel_documents
DOCUMENT_MAX_UPLOAD_BYTES=20971520
```

`.gitignore` 添加：

```gitignore
# 本地文档库原文件、解析产物和向量索引，禁止提交
backend/data/
```

- [ ] **步骤 4：运行模型和配置测试验证通过**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_documents_models.py backend/tests/test_config.py -q
```

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/requirements.txt backend/app/config.py backend/.env.example .gitignore backend/app/models/documents.py backend/tests/test_documents_models.py backend/tests/test_config.py
git commit -m "feat: add document RAG configuration and contracts"
```

---

### 任务 2：文件与文档元数据存储

**文件：**
- 创建：`backend/app/services/document_store.py`
- 测试：`backend/tests/test_document_store.py`

- [ ] **步骤 1：编写失败测试**

```python
from app.services.document_store import DocumentStore


def test_store_creates_metadata_and_writes_document_without_path_escape(tmp_path):
    store = DocumentStore(tmp_path)

    record = store.create_document(
        filename="成都调研.pdf",
        media_type="application/pdf",
        content=b"%PDF-1.7 test",
    )

    assert record.status.value == "pending"
    assert (tmp_path / "uploads" / f"{record.id}.pdf").read_bytes() == b"%PDF-1.7 test"
    assert store.get_document(record.id) == record


def test_store_delete_removes_file_extracted_outputs_and_metadata(tmp_path):
    store = DocumentStore(tmp_path)
    record = store.create_document("报告.docx", DOCX_MEDIA_TYPE, b"word")
    extracted = tmp_path / "extracted" / record.id / "figure-1.png"
    extracted.parent.mkdir(parents=True)
    extracted.write_bytes(b"image")

    store.delete_document(record.id)

    assert store.get_document(record.id) is None
    assert not extracted.exists()
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_document_store.py -q
```

预期：FAIL，原因是 `DocumentStore` 尚不存在。

- [ ] **步骤 3：实现受控存储**

实现 `DocumentStore`：

- 在构造中创建 `uploads/`、`extracted/`、`chroma/`；
- 使用 `documents.json` 原子写入（先写临时文件，再 replace）；
- 文件名仅用于展示，不参与服务器文件路径；
- 存储路径使用 `document_id + suffix`；
- 仅允许 PDF / DOCX MIME；
- `create_document()` 返回 `pending`；
- `mark_processing()`、`mark_ready(chunk_counts)`、`mark_failed(message)` 使用受控摘要；
- `delete_document()` 删除原文件、提取目录、元数据，Chroma 删除由下一任务 API/processor 协调调用。

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_document_store.py -q
```

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/services/document_store.py backend/tests/test_document_store.py
git commit -m "feat: add local document metadata store"
```

---

### 任务 3：Word/PDF/图表解析适配器

**文件：**
- 创建：`backend/app/services/document_extractors.py`
- 创建：`backend/app/services/mineru.py`
- 创建：`backend/app/services/qwen_vl.py`
- 测试：`backend/tests/test_document_extractors.py`
- 测试：`backend/tests/test_mineru.py`
- 测试：`backend/tests/test_qwen_vl.py`

- [ ] **步骤 1：编写失败测试**

```python
from app.services.document_extractors import normalize_table, split_text_blocks


def test_normalize_table_preserves_title_headers_and_rows():
    chunk = normalize_table(
        document_id=DOCUMENT_ID,
        document_name="成都调研.docx",
        table_index=3,
        title="成都景区客流",
        headers=["景区", "2025 年客流"],
        rows=[["武侯祠", "100 万"], ["杜甫草堂", "80 万"]],
    )

    assert chunk.chunk_type == "table"
    assert "表 3：成都景区客流" in chunk.content
    assert "景区=武侯祠；2025 年客流=100 万" in chunk.content


def test_split_text_blocks_keeps_section_and_offsets():
    chunks = split_text_blocks(
        document_id=DOCUMENT_ID,
        document_name="成都调研.docx",
        section="亲子游资源",
        text="甲" * 1300,
        max_chars=800,
        overlap_chars=100,
    )

    assert len(chunks) == 2
    assert chunks[0].source_section == "亲子游资源"
    assert chunks[1].char_start == 700
```

MinerU/Qwen-VL 失败测试必须验证：

```python
async def test_mineru_rejects_missing_key_before_http():
    client = MinerUClient(api_key="")
    with pytest.raises(ExternalServiceUnavailable, match="MinerU API 密钥未配置"):
        await client.submit_pdf("/safe/path/report.pdf")


async def test_qwen_vl_extracts_only_ocr_text_from_chart_response(respx_mock):
    # mock OpenAI-compatible response
    text = await client.extract_chart_ocr(image_bytes=b"png")
    assert text == "横轴：月份；纵轴：客流"
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_document_extractors.py backend/tests/test_mineru.py backend/tests/test_qwen_vl.py -q
```

预期：FAIL，原因是解析器和云端客户端尚不存在。

- [ ] **步骤 3：实现解析职责边界**

`document_extractors.py`：

- `split_text_blocks()`：标题/段落优先，再按 `max_chars=800`、`overlap_chars=100` 切分；
- `normalize_table()`：标题、表头、行转写；
- `extract_docx()`：用 `python-docx` 提取段落、表格；将内嵌图片写入 `extracted/{document_id}/`；
- `normalize_chart_ocr()`：把 Qwen-VL OCR 结果写为 `chart_ocr` chunk；
- 块内容不得携带原始文件路径或密钥。

`mineru.py`：

```python
class MinerUClient:
    _base_url = "https://mineru.net"

    async def submit_pdf(self, file_path: Path) -> str: ...
    async def get_task_result(self, task_id: str) -> MinerUResult: ...
```

- Base URL 固定为 `https://mineru.net`，客户端不能覆盖；
- Bearer Key 仅来自后端配置；
- 官方解析任务提交为 `POST /api/v4/extract/task`，请求体只包含后端生成的短期 HTTPS 文件 URL 与 `model_version="vlm"`；
- 后端将 PDF 临时副本放在不可猜测的 URL token 下，仅允许 MinerU 读取；任务完成、失败或超时后撤销 URL 并删除临时副本；该 URL 不得出现在浏览器响应、日志、错误或文档块；
- 使用现有 `request_with_retry` / `CircuitBreaker` / `ExternalServiceUnavailable` 模式；
- API 合同字段封装在 `MinerUClient` 内：提交返回 task id，轮询状态为 `waiting-file` / `pending` / `running` / `converting` / `done` / `failed`，完成后下载 `full_zip_url` 解析产物；
- 轮询由 `DocumentProcessor` 控制，不在客户端无限循环；
- 返回的文本、表格和图片路径必须标准化，不透传供应商原始 payload。

`qwen_vl.py`：

- 固定 Qwen OpenAI-compatible Base URL；
- 用图像 bytes 的 data URI 发送 OCR 提示；
- Prompt 仅要求“提取图中可见文字、标题、坐标轴、图例、标签；不做趋势推理；返回纯文本”；
- OCR 内容为空时返回受控失败；
- 不把 prompt、图像 bytes、Key 或供应商响应体写入错误。

- [ ] **步骤 4：运行解析器测试验证通过**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_document_extractors.py backend/tests/test_mineru.py backend/tests/test_qwen_vl.py -q
```

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/services/document_extractors.py backend/app/services/mineru.py backend/app/services/qwen_vl.py backend/tests/test_document_extractors.py backend/tests/test_mineru.py backend/tests/test_qwen_vl.py
git commit -m "feat: add document extraction and OCR adapters"
```

---

### 任务 4：本地 BGE 与 Chroma 持久化检索

**文件：**
- 创建：`backend/app/services/embeddings.py`
- 创建：`backend/app/services/chroma_store.py`
- 测试：`backend/tests/test_chroma_store.py`

- [ ] **步骤 1：编写失败测试**

使用可注入 fake embedder，避免测试加载真实 BGE：

```python
class FakeEmbedder:
    def embed_documents(self, texts):
        return [[float(len(text))] for text in texts]

    def embed_query(self, text):
        return [float(len(text))]


def test_chroma_store_queries_global_and_document_filtered_chunks(tmp_path):
    store = ChromaStore(tmp_path / "chroma", "travel_documents", FakeEmbedder())
    store.upsert([CHUNK_A, CHUNK_B])

    global_results = store.query("成都", limit=5)
    filtered_results = store.query("成都", document_ids=(CHUNK_A.document_id,), limit=5)

    assert {item.document_id for item in global_results} == {CHUNK_A.document_id, CHUNK_B.document_id}
    assert [item.document_id for item in filtered_results] == [CHUNK_A.document_id]


def test_chroma_store_deletes_all_document_chunks(tmp_path):
    store = ChromaStore(tmp_path / "chroma", "travel_documents", FakeEmbedder())
    store.upsert([CHUNK_A, CHUNK_B])
    store.delete_document(CHUNK_A.document_id)

    assert all(item.document_id != CHUNK_A.document_id for item in store.query("成都", limit=10))
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_chroma_store.py -q
```

预期：FAIL，原因是 `ChromaStore` 尚不存在。

- [ ] **步骤 3：实现 embedding 和 Chroma 存储**

`embeddings.py`：

```python
class LocalBgeEmbedder:
    def __init__(self, model_path: str) -> None: ...
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
```

- 启动时不下载模型；路径不存在时抛 `ExternalServiceUnavailable("本地 BGE 模型未配置")`；
- 通过 `sentence_transformers.SentenceTransformer(model_path)` 加载；
- 使用归一化 embedding；
- 不对浏览器暴露模型路径。

`chroma_store.py`：

- 使用 persistent Chroma client，collection 名为 `travel_documents`；
- `upsert(chunks)` 写入 ids、documents、embeddings 和白名单 metadata；
- `query(query, document_ids, limit)`：全库/metadata filter；
- `delete_document(document_id)`：按 metadata delete；
- 只从 Chroma 返回 `DocumentChunk` 白名单字段，供应商/Chroma 原始结构不透传。

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_chroma_store.py -q
```

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/services/embeddings.py backend/app/services/chroma_store.py backend/tests/test_chroma_store.py
git commit -m "feat: add local BGE and Chroma document search"
```

---

### 任务 5：异步文档处理编排

**文件：**
- 创建：`backend/app/services/document_processor.py`
- 测试：`backend/tests/test_document_processor.py`

- [ ] **步骤 1：编写失败测试**

```python
@pytest.mark.asyncio
async def test_processor_marks_ready_only_after_extraction_embedding_and_upsert(tmp_path):
    processor = DocumentProcessor(store=store, mineru=mineru, qwen_vl=qwen, embedder=embedder, chroma=chroma)
    record = store.create_document("成都.pdf", PDF_MEDIA_TYPE, b"pdf")

    await processor.process(record.id)

    saved = store.get_document(record.id)
    assert saved.status is DocumentStatus.ready
    assert saved.table_chunk_count == 1
    assert saved.chart_ocr_chunk_count == 1
    assert chroma.query("客流", limit=5)


@pytest.mark.asyncio
async def test_processor_keeps_text_chunks_when_chart_ocr_fails(tmp_path):
    qwen_vl.extract_chart_ocr.side_effect = ExternalServiceUnavailable("Qwen-VL 服务暂不可用")

    await processor.process(record.id)

    saved = store.get_document(record.id)
    assert saved.status is DocumentStatus.ready
    assert saved.text_chunk_count > 0
    assert saved.chart_ocr_chunk_count == 0
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_document_processor.py -q
```

预期：FAIL，原因是 `DocumentProcessor` 尚不存在。

- [ ] **步骤 3：实现后台处理器**

```python
class DocumentProcessor:
    async def process(self, document_id: str) -> None:
        record = self.store.get_document(document_id)
        self.store.mark_processing(document_id)
        try:
            if record.media_type == PDF_MEDIA_TYPE:
                extracted = await self.mineru.parse_pdf(self.store.upload_path(record.id))
            else:
                extracted = extract_docx(self.store.upload_path(record.id), self.store.extracted_dir(record.id))
            chunks = normalize_extracted_document(extracted)
            chart_chunks = await self._extract_chart_ocr(record, extracted.images)
            all_chunks = [*chunks, *chart_chunks]
            self.chroma.upsert(all_chunks)
            self.store.mark_ready(document_id, all_chunks)
        except ExternalServiceUnavailable as error:
            self.store.mark_failed(document_id, "文档处理服务暂不可用")
        except (OSError, ValueError, TypeError, ValidationError):
            self.store.mark_failed(document_id, "文档内容无法处理")
```

约束：

- 在 FastAPI `BackgroundTasks` 中调用 `process()`；
- 不在请求中长时间阻塞 MinerU 轮询；
- MinerU PDF 处理使用受控轮询次数和总等待预算；
- Qwen-VL 单张图 OCR 失败只影响该图表块，不使正文/表格入库失败；
- BGE 模型或 Chroma 失败使文档整体 `failed`，不得写入部分向量；
- 同一 document_id 不重复并发处理。

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_document_processor.py -q
```

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/services/document_processor.py backend/tests/test_document_processor.py
git commit -m "feat: add asynchronous document processing pipeline"
```

---

### 任务 6：文档与知识检索 API

**文件：**
- 创建：`backend/app/api/documents.py`
- 修改：`backend/app/main.py`
- 测试：`backend/tests/test_documents_api.py`

- [ ] **步骤 1：编写失败 API 测试**

```python
@pytest.mark.asyncio
async def test_upload_returns_pending_document_without_exposing_storage_path(app_client):
    response = await app_client.post(
        "/api/documents",
        files={"file": ("成都调研.docx", DOCX_BYTES, DOCX_MEDIA_TYPE)},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert "path" not in body
    assert "MINERU_API_KEY" not in response.text


@pytest.mark.asyncio
async def test_knowledge_search_returns_chunks_and_source_locations(app_client):
    response = await app_client.post(
        "/api/knowledge-search",
        json={"query": "成都亲子游", "document_ids": []},
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["chunk_type"] in {"text", "table", "chart_ocr"}
    assert result["source"]["document_name"]
    assert "raw_payload" not in result
```

再添加：非法 MIME、超大文件、未 ready 文档不会被检索、删除时 Chroma delete 被调用、文档块浏览不泄露文件系统绝对路径。

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_documents_api.py -q
```

预期：FAIL，原因是文档路由尚未注册。

- [ ] **步骤 3：实现 API 和应用接线**

在 `documents.py` API 路由中实现：

```python
router = APIRouter(prefix="/api")

@router.post("/documents", status_code=202, response_model=DocumentRecord)
async def upload_document(file: UploadFile, request: Request, background_tasks: BackgroundTasks): ...

@router.get("/documents", response_model=tuple[DocumentRecord, ...])
async def list_documents(request: Request): ...

@router.get("/documents/{document_id}", response_model=DocumentRecord)
async def get_document(document_id: str, request: Request): ...

@router.get("/documents/{document_id}/chunks", response_model=tuple[DocumentChunk, ...])
async def list_document_chunks(document_id: str, request: Request): ...

@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: str, request: Request): ...

@router.post("/knowledge-search", response_model=KnowledgeSearchResponse)
async def search_knowledge(payload: KnowledgeSearchRequest, request: Request): ...
```

上传验证：

```python
if file.content_type not in {PDF_MEDIA_TYPE, DOCX_MEDIA_TYPE}:
    raise HTTPException(status_code=422, detail="仅支持 Word 或 PDF 文档")
content = await file.read(settings.document_max_upload_bytes + 1)
if len(content) > settings.document_max_upload_bytes:
    raise HTTPException(status_code=422, detail="文档文件超过大小限制")
```

在 `main.py`：

- `app.state.document_store`、`app.state.document_processor`、`app.state.chroma_store`；
- 注册文档 router；
- 仅当 extracted 图片目录存在时挂载受控预览路径，不挂载 uploads 原始文件目录；
- 保持既有 `/api/travel-plans`、前端静态挂载和安全中间件顺序不变。

- [ ] **步骤 4：运行 API 测试验证通过**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_documents_api.py -q
```

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/api/documents.py backend/app/main.py backend/tests/test_documents_api.py
git commit -m "feat: add document library and knowledge search APIs"
```

---

### 任务 7：最小前端文档库与搜索接入

**文件：**
- 修改：`frontend/index.html`
- 修改：`frontend/app.js`
- 修改：`frontend/styles.css`
- 修改：`backend/tests/test_frontend_assets.py`

**不可变视觉基线：** 不修改 `.home-nav-pane` 的 `grid-template-columns`，不修改 `.home-plan-zone`、`.home-service-zone`、`.travel-window`、`.digital-human-card`、`.search-card` 的现有布局声明；不修改原出行表单、数字人、查询记录、数据看板、设置和结果页的 DOM 结构/样式。

- [ ] **步骤 1：编写失败的静态 UI 回归测试**

```python
def test_document_library_adds_only_approved_navigation_and_search_scope_ui():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")

    assert 'id="nav-library"' in html
    assert 'id="view-library"' in html
    assert "检索范围：全部已处理文档" in html
    assert "showView('library')" in html
    assert "grid-template-columns: minmax(0, 1.08fr) 1px minmax(0, .92fr)" in styles
    assert 'id="home-origin"' in html
    assert 'id="home-dest"' in html
    assert 'id="home-region-input"' in html
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
```

预期：FAIL，原因是文档库导航、视图和检索范围提示尚不存在。

- [ ] **步骤 3：实现仅允许的前端增量**

`index.html`：

- 在左侧“管理”区 `nav-dashboard` 后增加：
  ```html
  <button class="side-nav" id="nav-library" onclick="showView('library')">
    <span>📚</span> 文档库
  </button>
  ```
- 在主内容增加独立：
  ```html
  <section id="view-library" class="view">
    <div class="library-head">
      <div><div class="zone-kicker">DOCUMENT LIBRARY</div><h2>文档库</h2><p>上传、处理和浏览已入库 Word/PDF 文档。</p></div>
      <label class="library-upload"><input id="document-upload" type="file" accept=".docx,.pdf,application/pdf" hidden>上传文档</label>
    </div>
    <p id="library-status" role="status"></p>
    <div id="library-list" class="library-list"></div>
    <section id="library-detail" hidden></section>
  </section>
  ```
- 在原 `search-card` 内、搜索表单后增加不改变卡片宽高结构的提示：
  ```html
  <p class="search-scope">📚 检索范围：全部已处理文档 · 可在“文档库”管理</p>
  <div id="knowledge-results" class="knowledge-results" hidden></div>
  ```

`app.js`：

- 扩展 `showView()`，激活 `nav-library`；
- `loadDocuments()` 请求 `/api/documents`，用 DOM 节点显示状态、块统计、删除按钮；
- 上传 `FormData` 到 `/api/documents`，显示 pending；
- 轮询 pending/processing 文档直到 ready/failed，间隔 2 秒、最大 30 次；
- `deleteDocument(id)` 调用 DELETE 后刷新；
- 将 `homeRegion()` 从静态 toast 改为 `POST /api/knowledge-search`，显示原文、chunk type、来源定位；
- 结果文本用 `textContent`，不得以 `innerHTML` 渲染文档原文或 OCR 文本。

`styles.css`：

只新增局部选择器：

```css
.library-head, .library-list, .library-card, .library-upload,
.library-chunk, .knowledge-results, .knowledge-result, .search-scope
```

不得编辑首页既有布局选择器。

- [ ] **步骤 4：运行前端静态测试验证通过**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
```

预期：PASS。

- [ ] **步骤 5：浏览器视觉回归验证**

启动后端：

```bash
PYTHONPATH=backend python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

浏览器检查：

1. 首页出行规划、轮播、数字人和右侧搜索卡片与实现前截图/原型保持同样比例；
2. 左侧仅增加“文档库”入口；
3. 文档库页面可打开，不影响数据看板；
4. 上传/删除/检索文档时原首页布局未变化；
5. 文档原文和 OCR 结果不会执行 HTML/脚本。

- [ ] **步骤 6：Commit**

```bash
git add frontend/index.html frontend/app.js frontend/styles.css backend/tests/test_frontend_assets.py
git commit -m "feat: add document library navigation and RAG search UI"
```

---

### 任务 8：完整回归、RAG 冒烟与视觉验收

**文件：** 无功能代码改动。

- [ ] **步骤 1：运行完整后端测试**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests -q
```

预期：全部通过。不得用旧测试统计数字描述结果，以命令实际输出为准。

- [ ] **步骤 2：RAG 本地冒烟**

实施前先确认：

```powershell
Test-Path "D:\作业\model\bge-small-zh-v1.5"
```

预期：`True`。

MinerU/Qwen-VL 密钥尚未提供时：

- 上传 PDF 返回 `pending` 后进入 `failed`；
- failure_message 为受控摘要；
- API、前端、日志中不出现 Key；
- Word/PDF 解析成功冒烟延后到密钥配置完成后执行。

密钥配置完成后，执行：

1. 上传含正文、表格和图表图片的 DOCX；
2. 上传含正文、表格和图表的 PDF；
3. 等待 `ready`；
4. 检查文档块统计包含 `text`、`table` 和 `chart_ocr`；
5. 用右侧搜索查询一个表格字段和一个 OCR 图表标签；
6. 确认结果包含原文和来源页码/章节/表格或图表索引；
7. 删除文档，确认 `/api/documents/{id}/chunks` 和 `/api/knowledge-search` 不再返回其 chunks。

- [ ] **步骤 3：安全与视觉回归**

运行：

```bash
git diff --check
```

预期：无空白错误。

人工验证：

- 首页原双栏比例未变化；
- 出行规划表单、数字人、搜索输入框和按钮未移动/重绘；
- 左侧仅增加文档库入口；
- 文档原文包含 `<script>`、`<img onerror>` 或 Markdown 控制字符时，不执行脚本；
- `.env` 和 `backend/data/` 未被 Git 跟踪：

```bash
git check-ignore -v backend/.env backend/data/example
```

- [ ] **步骤 4：Commit**

```bash
git add README.md docs/superpowers/plans/2026-08-22-implement-document-library-rag.md
git commit -m "docs: add document library RAG operations guide"
```

---

## 自检记录

- **规格覆盖度：** 任务 1 覆盖配置和合同；任务 2 覆盖文件与元数据；任务 3 覆盖 Word/PDF/MinerU/Qwen-VL；任务 4 覆盖 BGE/Chroma；任务 5 覆盖异步处理；任务 6 覆盖 API；任务 7 覆盖最小 UI；任务 8 覆盖真实/安全/视觉验收。
- **原 UI 不变：** 任务 7 将既有首页选择器作为不可改动基线，并用前端静态测试和浏览器视觉回归双重验证。
- **密钥边界：** MinerU/Qwen-VL/BGE 只经 `Settings` 后端读取；`.env.example` 空值；真实密钥只留在 `backend/.env`；文档/测试/API 都不回显。
- **类型一致性：** `DocumentRecord` / `DocumentChunk` / `KnowledgeSearchRequest` 在任务 1 定义，并在 Store、Processor、Chroma 和 API 后续任务统一使用；`daily_itineraries` 与现有旅行规划不改变。
- **外部 API 不确定性：** MinerU 云端提交/轮询响应字段封装在 `MinerUClient`；真实 Base URL 和密钥于实施前通过环境变量配置，所有错误映射为受控文档状态。
- **不混改项：** 天气日期连续性、POI 服务容错、Route 总 deadline、来源 metadata 容错、模型日期覆盖约束、前端历史性能是既有独立可靠性项，RAG 实现不顺手修改。
