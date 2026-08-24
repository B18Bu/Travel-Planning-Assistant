# 文档库 RAG 检索设计

**日期：** 2026-08-22  
**状态：** 已确认，待用户审查书面规格  
**范围：** 在不改变现有首页、出行规划、数字人占位和右侧自定义搜索布局的前提下，新增 Word/PDF 文档库、异步解析、Chroma 向量检索与可追溯原文片段检索。

---

## 1. 目标、UI 约束与非目标

### 1.1 目标

用户可在独立“文档库”页面上传 `.docx` / `.pdf` 文档。后端异步解析正文、表格和图表图片，将可检索块写入 Chroma。首页右侧“自定义搜索”默认检索所有 `ready` 文档，仅返回原文、表格转写或图表 OCR 文本以及来源定位，不调用生成模型总结。

### 1.2 不可变 UI 约束

以下内容为既有视觉基线，不得修改其布局、比例、配色、间距、卡片、按钮、动画或既有交互：

- 首页出行规划左侧区域、轮播图及始发地/目的地表单；
- 右侧数字人卡片；
- 右侧自定义搜索卡片的尺寸、位置、输入框和查询按钮；
- 左侧查询记录、数据看板、设置和既有结果页。

允许的前端改动仅有：

1. 左侧“管理”区新增“📚 文档库”入口；
2. 新增独立 `view-library` 文档库页面；
3. 自定义搜索卡片增加轻量提示“📚 检索范围：全部已处理文档 · 可在‘文档库’管理”；
4. 现有安全结果区展示原文检索片段与来源定位。

### 1.3 非目标

第一版不实现 LLM 检索后总结、图表趋势推理、在线编辑或替换、重切分参数界面、权限与多租户、云端 embedding、版本管理、批量导入、全文下载和任务队列。

---

## 2. 架构与持久化边界

### 2.1 模块职责

| 模块 | 职责 |
| --- | --- |
| `services/document_store.py` | 管理 `documents.json`、上传原文件与解析产物；提供文档、分块、状态的原子读写。 |
| `services/document_extractors.py` | 解析 Word，标准化正文、表格、图片及分块；不处理向量。 |
| `services/mineru.py` | 封装 MinerU PDF 提交、轮询和结果下载。 |
| `services/qwen_vl.py` | 为图片提供 OCR 文本；失败时返回可记录的降级结果。 |
| `services/embeddings.py` | 懒加载本地 BGE 模型并生成向量。 |
| `services/chroma_store.py` | 持久化 Chroma collection，按文档写入、查询和删除向量。 |
| `services/document_processor.py` | 编排解析、OCR、分块、嵌入、Chroma 写入和状态流转。 |
| `api/documents.py` | 提供上传、查询、详情、分块、删除和知识检索 API。 |

`main.py` 仅注册路由、初始化所需目录和应用级依赖；前端只增加 `library` 视图，不改变既有旅行规划行为。

### 2.2 数据目录与数据来源

```text
backend/data/
├─ uploads/        原始 .docx / .pdf 文件
├─ extracted/      MinerU、Word 解析产物及图片
├─ chroma/         Chroma 持久化向量数据
└─ documents.json  文档元数据、状态和可追溯原文分块
```

- `documents.json` 是文档状态、详情和分块 API 的唯一来源；
- Chroma 只保存向量及检索所需白名单元数据，不能作为文档详情或分块浏览 API 的数据来源；
- 浏览器不能直接遍历或下载这些目录；不得暴露原始文件路径、临时 URL、密钥、供应商原始响应或异常堆栈；
- `documents.json` 使用进程内锁和“写临时文件后替换”的方式更新，仅保证单进程写入安全。

### 2.3 级联删除与一致性

删除按以下顺序执行：记录删除意图、删除该 `document_id` 的 Chroma 向量、删除上传文件与解析产物、删除 `documents.json` 记录。任一中间步骤失败时，不得静默宣称删除成功；保留元数据和受控失败原因，供后续重试或人工清理。

---

## 3. 生命周期与处理策略

### 3.1 状态

```text
上传成功 → pending → processing → ready
                              └→ failed
```

| 状态 | 含义 |
| --- | --- |
| `pending` | 文件已接收，等待后台任务。 |
| `processing` | 正在解析、OCR、分块或向量化。 |
| `ready` | 正文/表格已完成处理并已写入 Chroma，可参与检索。 |
| `failed` | 正文或表格解析、本地 embedding 或 Chroma 写入失败。 |

失败信息必须为受控摘要，不包含 Key、Token、绝对路径、原始供应商响应或堆栈。

### 3.2 后台流程

1. 上传接口校验后保存原文件，创建 `pending` 记录，并返回 `202`；
2. FastAPI `BackgroundTasks` 将记录置为 `processing`；
3. DOCX 用 `python-docx` 抽取正文、表格和嵌入图片；
4. PDF 优先调用 MinerU 提取版面、正文、表格和图表图片；MinerU 调用、超时或结果处理失败时，使用 PyMuPDF 兜底提取文本和页面图片；
5. 对图片调用 Qwen-VL OCR，仅提取可见文字、标题、坐标轴、图例和标签，不做视觉趋势推理；
6. 正文、表格与成功的 OCR 结果标准化为分块；
7. 本地 BGE 生成 embedding，Chroma 原子批量 upsert；
8. 成功后保存可追溯分块并标记 `ready`；处理失败时清理该文档已写入的向量并标记 `failed`。

### 3.3 OCR 降级

Qwen-VL 未配置、单张图 OCR 失败或返回不可用结果时：

- 正文和表格继续分块、向量化和入库；
- 文档最终仍可标记为 `ready`；
- 不生成该图表的 `chart_ocr` 块；
- 在受控处理信息中记录 OCR 降级原因。

本地 BGE 模型缺失或编码失败、正文/表格无法解析、Chroma 写入失败均使文档标记为 `failed`，并不得保留部分向量。

### 3.4 v1 运行约束

- 使用进程内 FastAPI `BackgroundTasks`，不引入 Redis/Celery/RQ；
- 仅支持单进程、单实例处理；同一 `document_id` 不允许并发处理；
- 应用重启可能使任务停留于 `pending` 或 `processing`，第一版不自动恢复；
- MinerU 若需要可访问文件 URL，由可配置公开基础 URL 生成受控短期路径；当前部署无法提供 HTTPS 可访问地址时，直接改走 PyMuPDF，并记录降级原因；
- MinerU 客户端由处理器控制轮询次数和总等待预算，不能无限轮询。

---

## 4. 分块、embedding 与检索

### 4.1 DocumentChunk

每个分块包含稳定 UUID、`document_id`、受控文本内容、`chunk_type`、文档名和来源定位字段：页码、章节、表格索引、图表索引、字符起止偏移和可选预览相对路径。

- 类型限定为 `text`、`table`、`chart_ocr`；
- 文本先按标题和段落划分，再按最多 800 字符、100 字符重叠细分；
- 超长表格与正文遵循相同上限与重叠规则；
- 表格转写格式为“表标题 + 表头 + 行键值对”；
- 图表块只保存 OCR 所见文本和来源定位。

### 4.2 向量与 Chroma

- embedding 固定使用配置的本地中文 BGE 模型；文档内容和查询内容不得发送给外部 embedding API；
- collection 名称默认 `travel_documents`；
- 每条 Chroma 记录的 metadata 仅包含 `document_id`、文档名、块类型和白名单来源定位；
- 默认检索仅覆盖 `ready` 文档；指定文档范围时按 `document_id` filter；
- 搜索结果基于 `documents.json` 的原文块构造响应，以 Chroma 的命中 id 与分数作为检索依据。

---

## 5. API 与安全校验

| 接口 | 行为 |
| --- | --- |
| `POST /api/documents` | 校验并保存 DOCX/PDF，返回 `202` 和 `pending` 记录。 |
| `GET /api/documents` | 返回文档列表和处理状态。 |
| `GET /api/documents/{document_id}` | 返回详情、分块统计、失败或降级摘要。 |
| `GET /api/documents/{document_id}/chunks` | 从 `documents.json` 返回可追溯分块。 |
| `DELETE /api/documents/{document_id}` | 级联删除 Chroma、文件、解析产物和元数据。 |
| `POST /api/knowledge-search` | 检索全库或指定文档，返回原文片段、块类型、分数与来源定位。 |

上传必须同时校验：

1. 扩展名仅为 `.docx` 或 `.pdf`；
2. 声明 MIME 与对应类型一致；
3. 文件签名与类型一致；
4. 文件大小不超过 `document_max_upload_bytes`；
5. 服务器文件路径仅使用 `document_id + 安全后缀`，用户文件名仅用于展示。

`DELETE` 必须加入 CORS 允许方法。接口不得回传文件系统绝对路径、原始上传路径、密钥、临时 URL、供应商 payload 或异常堆栈。

---

## 6. 最小前端范围

- 新增“文档库”导航入口和 `view-library`；
- 支持上传 PDF/DOCX、展示 `pending` / `processing` / `ready` / `failed` 状态、查看详情及删除文档；
- 支持知识库检索，展示命中文档名、章节、页码或字符偏移、块类型和原文片段；
- 文档原文和 OCR 内容必须用 DOM 文本节点（`textContent`）渲染，不能使用 `innerHTML`；
- 前端对待处理文档可进行有上限的状态轮询；
- 不实现编辑、替换、版本、权限、问答聊天和 LLM 总结。

---

## 7. 测试与验收

### 7.1 自动化测试

- 模型与配置：状态、字段约束、目录配置和上传限制；
- DocumentStore：原子写入、列表/详情/分块读取、路径隔离与删除失败保留；
- 解析：DOCX 正文/表格、MinerU 成功、MinerU 失败转 PyMuPDF、文本/超长表格分块；
- OCR：Qwen-VL 失败时正文/表格仍可 `ready`；
- Chroma 与处理器：全库/指定文档查询、状态流转、失败向量清理、来源元数据；
- API：扩展名、MIME、签名和大小校验，异步 `202` 上传、详情、分块、删除、检索和 DELETE CORS；
- 前端资产：仅新增获准入口、页面、检索提示与结果挂载点；断言既有首页关键 DOM 与布局声明不变。

### 7.2 验收标准

1. 合法 DOCX/PDF 上传后可观察 `pending → processing → ready`；
2. 结果可追溯至原文分块及页码、章节、表格、图表或字符偏移；
3. MinerU 失败时 PDF 仍可由 PyMuPDF 建库；
4. Qwen-VL 不可用不阻断正文和表格建库；
5. 非法类型、伪造 MIME/签名和超限文件被拒绝；
6. 删除成功后 JSON、磁盘产物和 Chroma 均不保留该文档数据；
7. 既有旅行规划 API、页面布局与交互回归通过；
8. RAG 结果不包含密钥、绝对路径、供应商原始数据或未经证实的图表趋势结论。

---

## 8. 后续项

以下项目明确不与本次 RAG 功能混改：任务持久化与重启恢复、多实例锁与数据库迁移、鉴权/RBAC、多租户、审计、集中密钥管理，以及既有天气、POI、路线等可靠性改进。
