# FlyAI 酒店与高德 POI 并列推荐实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为个人开发者增加 FlyAI 酒店搜索能力，并将 FlyAI 酒店价格/详情与高德住宿 POI 的地址/位置按名称做确定性匹配后并列展示。

**架构：** 保留现有飞猪 TOP API 56180 适配器和 `/api/fliggy/hotels/search` 企业模式不变；新增 `FlyAIHotelClient`，通过官方 `flyai` CLI 调用 MCP `search_hotels` 工具。新增推荐服务并行查询 FlyAI 与高德住宿 POI，仅对规范化名称完全相等的结果合并，未匹配结果分别返回，绝不补造价格、地址或库存。

**技术栈：** FastAPI、Pydantic v2、httpx/现有 AmapClient、Python asyncio 子进程、FlyAI CLI/MCP、pytest、pytest-asyncio、respx。

---

## 已确认的外部合同

- FlyAI MCP endpoint：`https://flyai.open.fliggy.com/mcp`。
- Quickstart 安装并使用 `flyai` CLI；API Key 配置名：`FLYAI_API_KEY`。
- CLI 酒店能力：`search-hotel`，底层 MCP 工具名：`search_hotels`。
- CLI 参数映射：`--dest-name`、`--poi-name`、`--check-in-date`、`--check-out-date`、`--sort`、`--hotel-stars`、`--hotel-bed-types`、`--max-price` 对应 `destName`、`poiName`、`checkInDate`、`checkOutDate`、`sort`、`hotelStars`、`hotelBedTypes`、`maxPrice`。
- 酒店结果字段：`name`、`address`、`latitude`、`longitude`、`mainPic`、`detailUrl`、`price`、`review`、`score`、`star`、`shId`；酒店详情/预订入口优先使用 `detailUrl`。
- 认证由 CLI 管理；若直接检查 MCP，使用 `Authorization: Bearer <FLYAI_API_KEY>`，不得使用传统 TOP `app_key/app_secret/sign/sub_channel`。
- 部分实时库存没有价格，客户端必须保留无价格结果并展示“价格暂不可用”，同时保留官方详情链接。

CLI/MCP 的完整返回 envelope 和工具 schema 可能随 CLI 版本变化，因此适配器只依赖上述字段，并对其他字段丢弃；所有 HTTP/CLI 交互均用 fixture 测试，不在测试中使用真实 Key。

---

## 文件结构与职责

- 创建 `backend/app/models/flyai_hotel.py`：FlyAI 原始投影、POI 合并结果、推荐请求/响应模型。
- 创建 `backend/app/services/flyai_hotel_client.py`：安全构造 `flyai search-hotel` CLI 参数、异步运行、超时/退出码/JSON 解析和字段白名单投影。
- 创建 `backend/app/services/hotel_matching.py`：名称规范化和严格相等匹配；不使用模糊相似度。
- 创建 `backend/app/services/flyai_hotel_recommendation.py`：并行调用 FlyAI 与 `AmapClient`，合并结果并标注各来源。
- 修改 `backend/app/config.py`：新增 FlyAI 开关、Key、CLI 命令、超时和结果数量配置；不改 TOP 配置含义。
- 修改 `backend/.env.example`：添加 FlyAI 变量说明，禁止写入真实 Key。
- 修改 `backend/app/dependencies.py`、`backend/app/main.py`：构造并注入 FlyAI 推荐服务；保留现有 TOP 服务和编排器。
- 创建 `backend/app/api/flyai_hotel.py`：新增 `POST /api/fliggy/hotels/recommend`。
- 修改 `backend/app/main.py`：注册新路由。
- 创建 `backend/tests/test_flyai_hotel_models.py`。
- 创建 `backend/tests/test_flyai_hotel_client.py`。
- 创建 `backend/tests/test_hotel_matching.py`。
- 创建 `backend/tests/test_flyai_hotel_recommendation.py`。
- 创建 `backend/tests/test_flyai_hotel_api.py`。
- 修改 `backend/tests/test_fliggy_hotel_config.py` 或新增 FlyAI 配置测试。
- 修改 `frontend/app.js`、`frontend/index.html`、`frontend/styles.css`：增加酒店并列展示表单、来源标签和安全图片/链接渲染；不改变门票流程。
- 修改 `frontend/tests` 中对应静态资源/基线测试，覆盖新增 DOM 和文案。

---

### 任务 1：建立 FlyAI 与并列结果模型

**文件：**
- 创建：`backend/app/models/flyai_hotel.py`
- 创建：`backend/tests/test_flyai_hotel_models.py`

- [ ] **步骤 1：编写失败测试**

```python
from decimal import Decimal
from pydantic import ValidationError
from app.models.flyai_hotel import FlyAIHotelSearchRequest, CombinedHotelResult


def test_request_accepts_city_and_date_range():
    request = FlyAIHotelSearchRequest(
        city_name="杭州", check_in="2026-09-01", check_out="2026-09-02"
    )
    assert request.city_name == "杭州"
    assert request.sort == "price_asc"


def test_combined_result_does_not_fabricate_unmatched_fields():
    result = CombinedHotelResult(
        hotel_name="测试酒店",
        flyai_price=Decimal("280.00"),
        amap_address=None,
        amap_location=None,
        price_source="flyai",
        poi_source=None,
        detail_url="https://example.com/hotel",
    )
    assert result.flyai_price == Decimal("280.00")
    assert result.amap_address is None
```

测试还必须覆盖：日期格式、城市非空、页大小上下界、未知字段拒绝、Decimal 内存值与 JSON 数字输出、来源枚举、`detail_url` 仅允许 HTTPS、无价格时 `flyai_price=None`、酒店结果集合序列化为数组。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend; python -m pytest tests/test_flyai_hotel_models.py -q`

预期：因模块不存在而失败。

- [ ] **步骤 3：实现最小模型**

定义：

```python
class FlyAIHotelSearchRequest(StrictModel):
    city_name: NonEmptyText
    check_in: date
    check_out: date
    poi_name: str | None = None
    sort: Literal["distance_asc", "rate_desc", "price_asc", "price_desc", "no_rank"] = "price_asc"
    max_price: Decimal | None = Field(default=None, ge=0)
    limit: int = Field(default=10, ge=1, le=20)

class FlyAIHotel(StrictModel):
    hotel_id: NonEmptyText
    name: NonEmptyText
    address: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    price: Decimal | None
    score: Decimal | None
    star: int | None
    main_pic: HttpUrl | None
    detail_url: HttpUrl | None

class CombinedHotelResult(StrictModel):
    hotel_name: NonEmptyText
    flyai_price: Decimal | None
    flyai_score: Decimal | None
    flyai_star: int | None
    flyai_main_pic: HttpUrl | None
    detail_url: HttpUrl | None
    amap_address: str | None
    amap_location: str | None
    price_source: Literal["flyai"] | None
    poi_source: Literal["amap"] | None
    match_status: Literal["matched", "flyai_only", "poi_only"]
```

价格保持 Decimal，使用字段序列化器在 API 边界输出 JSON 数字；没有 `price` 时保留 `None`，不输出 0。图片/详情链接仅允许 HTTPS，前端仍需二次校验。

- [ ] **步骤 4：运行模型测试**

运行：`python -m pytest tests/test_flyai_hotel_models.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交模型变更**

```bash
git add backend/app/models/flyai_hotel.py backend/tests/test_flyai_hotel_models.py
git commit -m "feat: add flyai hotel recommendation models"
```

---

### 任务 2：实现 FlyAI CLI 适配器

**文件：**
- 创建：`backend/app/services/flyai_hotel_client.py`
- 创建：`backend/tests/test_flyai_hotel_client.py`

- [ ] **步骤 1：编写失败测试**

注入 fake `run` 函数，不调用真实 CLI。覆盖：

```python
async def fake_run(command, args, timeout):
    assert command == "flyai"
    assert args[:2] == ["search-hotel", "--dest-name"]
    return '{"data":{"itemList":[{"name":"酒店A","price":280,"detailUrl":"https://example.com/a","shId":123}]}}'
```

测试必须覆盖日期和排序参数、`--max-price`、成功字段白名单、无价格结果、CLI 非零退出码、超时、非 JSON、缺少 `data.itemList`、敏感错误文本不进入异常，以及参数列表中不出现 API Key。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend; python -m pytest tests/test_flyai_hotel_client.py -q`

预期：模块不存在而失败。

- [ ] **步骤 3：实现最小客户端**

`FlyAIHotelClient.search_hotels(request)` 只接受已校验请求模型，构造 argv：

```python
[
    "search-hotel", "--dest-name", request.city_name,
    "--check-in-date", request.check_in.isoformat(),
    "--check-out-date", request.check_out.isoformat(),
    "--sort", request.sort,
    "--limit", str(request.limit),
]
```

按需加入 `--poi-name`、`--max-price`。API Key 只通过子进程环境变量 `FLYAI_API_KEY` 注入，绝不出现在 argv、日志或异常。使用 `asyncio.create_subprocess_exec`，捕获 stdout/stderr，设置硬超时；stdout 按 JSON 解析，只保留已确认字段，`detailUrl` 统一为 HTTPS。错误使用受控 `FlyAIHotelError`，自由文本只转为固定错误码。

- [ ] **步骤 4：运行客户端测试**

运行：`python -m pytest tests/test_flyai_hotel_client.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交客户端变更**

```bash
git add backend/app/services/flyai_hotel_client.py backend/tests/test_flyai_hotel_client.py
 git commit -m "feat: add flyai hotel cli client"
```

---

### 任务 3：实现确定性酒店名称匹配

**文件：**
- 创建：`backend/app/services/hotel_matching.py`
- 创建：`backend/tests/test_hotel_matching.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_normalize_name_matches_only_deterministic_equivalents():
    assert normalize_hotel_name(" 杭州 西湖酒店 ") == normalize_hotel_name("杭州西湖酒店")
    assert match_hotel("杭州西湖酒店", "杭州西湖酒店") is True
    assert match_hotel("杭州西湖酒店", "杭州西湖大酒店") is False
    assert match_hotel("酒店A", "酒店B") is False
```

测试禁止模糊相似度、编辑距离或“包含即匹配”；覆盖全角空格、大小写、中文标点和空名拒绝。

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_hotel_matching.py -q`

预期：模块不存在而失败。

- [ ] **步骤 3：实现最小匹配器**

规范化只做：去除首尾空白、Unicode NFKC、移除 Unicode 空白和中文/英文标点、英文转小写。两个非空规范化字符串完全相等才匹配；不得删除“酒店/大酒店”等业务词，不得使用模糊匹配。

- [ ] **步骤 4：运行匹配测试**

运行：`python -m pytest tests/test_hotel_matching.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交匹配变更**

```bash
git add backend/app/services/hotel_matching.py backend/tests/test_hotel_matching.py
git commit -m "feat: add deterministic hotel matching"
```

---

### 任务 4：实现 FlyAI 与高德并列推荐服务

**文件：**
- 创建：`backend/app/services/flyai_hotel_recommendation.py`
- 创建：`backend/tests/test_flyai_hotel_recommendation.py`

- [ ] **步骤 1：编写失败测试**

注入 fake FlyAI client 和 fake Amap client，覆盖：

- 完全匹配：同一 `hotel_name` 合并价格与地址；
- FlyAI-only：保留价格/评分/链接，地址为空；
- POI-only：保留名称/地址，价格为空；
- 不因匹配失败复制另一方字段；
- FlyAI 价格按升序排列，缺价格排在有效价格之后；
- Amap 失败不伪造地址，FlyAI 结果仍可返回并标记 POI 不可用；
- FlyAI 失败按受控错误返回，不降级为伪造价格；
- 不调用传统 TOP client；
- `retrieved_at` 分别保留数据源时间。

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_flyai_hotel_recommendation.py -q`

预期：模块不存在而失败。

- [ ] **步骤 3：实现最小服务**

服务并行发起：

```python
flyai_results, amap_results = await asyncio.gather(
    flyai_client.search_hotels(request),
    amap_client.search_poi("住宿服务", request.city_name),
)
```

先按规范化名称建立 Amap 索引，再逐个加入 FlyAI 结果；匹配则填 `amap_address/amap_location`，不匹配则保留 `None`；剩余 POI 追加为 `poi_only`。只保留 FlyAI 返回的价格、评分、星级、图片和 `detailUrl`，不将 Amap 位置当价格依据。Amap 异常只能让 `poi_source` 缺失，不改变 FlyAI 来源标记。FlyAI 的 `detailUrl` 只作为官方详情入口，不在后端执行跳转、下单或支付。

- [ ] **步骤 4：运行服务测试**

运行：`python -m pytest tests/test_flyai_hotel_recommendation.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交服务变更**

```bash
git add backend/app/services/flyai_hotel_recommendation.py backend/tests/test_flyai_hotel_recommendation.py
git commit -m "feat: merge flyai hotels with amap poi"
```

---

### 任务 5：配置、依赖、API 和前端并列展示

**文件：**
- 修改：`backend/app/config.py`
- 修改：`backend/.env.example`
- 修改：`backend/app/dependencies.py`
- 修改：`backend/app/main.py`
- 创建：`backend/app/api/flyai_hotel.py`
- 创建：`backend/tests/test_flyai_hotel_api.py`
- 修改：`frontend/index.html`、`frontend/app.js`、`frontend/styles.css`
- 修改：前端对应基线测试

- [ ] **步骤 1：编写失败测试**

后端 API 测试：

```python
async def test_recommendation_merges_flyai_price_and_amap_address(client):
    response = await client.post(
        "/api/fliggy/hotels/recommend",
        json={"city_name":"杭州","check_in":"2026-09-01","check_out":"2026-09-02"},
    )
    assert response.status_code == 200
    item = response.json()["hotels"][0]
    assert item["flyai_price"] == 280
    assert item["amap_address"] == "西湖边"
    assert item["price_source"] == "flyai"
    assert item["poi_source"] == "amap"
```

测试还覆盖 FlyAI 关闭时 503、Key 缺失不外呼、MCP/CLI 超时 502、未知字段 422、`detail_url` 不允许 HTTP、匹配失败不复制字段。前端静态测试覆盖城市/日期表单、来源标签、演示/实时文案、安全外链属性和不显示伪造价格。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
cd backend
python -m pytest tests/test_flyai_hotel_api.py -q
cd ../frontend
node --check app.js
```

预期：API 模块/路径不存在而失败；前端新增基线断言失败。

- [ ] **步骤 3：实现配置和后端入口**

新增配置：

```python
flyai_hotel_enabled: bool = False
flyai_api_key: str = ""
flyai_cli_command: str = "flyai"
flyai_cli_timeout_seconds: float = 20.0
flyai_hotel_limit: int = 10
```

API `POST /api/fliggy/hotels/recommend` 使用严格请求模型和 `response_model`，只返回合并模型；Key 缺失/开关关闭返回 503，FlyAI 错误返回 502；不记录 Key。保留既有 TOP `/api/fliggy/hotels/search` 和服务状态接口。

- [ ] **步骤 4：实现前端并列展示**

增加酒店查询表单和结果卡片：

```text
酒店名称
地址：若有高德匹配则展示，否则“位置暂无匹配”
价格：若 FlyAI price 为 null 则“价格暂不可用”
来源：FlyAI / 高德 POI
评分、星级、床型
官方详情：detailUrl（仅 https，target=_blank、rel=noopener noreferrer）
查询时间
```

前端使用 `textContent`/DOM API，不使用 `innerHTML` 渲染供应商字段；图片只允许 `https:`，加载失败时移除图片；未匹配字段不显示默认值；所有结果标记 FlyAI/高德来源。不要把“价格暂不可用”改成 0，不显示“可预订/库存保证”等未经返回字段。

- [ ] **步骤 5：运行 API 与前端测试**

运行：

```bash
cd backend
python -m pytest tests/test_flyai_hotel_api.py tests/test_flyai_hotel*.py -q
cd ../frontend
node --check app.js
python -m pytest tests/test_frontend_assets.py -q
```

预期：全部 PASS。

- [ ] **步骤 6：提交集成变更**

```bash
git add backend frontend
 git commit -m "feat: add flyai and amap hotel recommendations"
```

---

### 任务 6：最终验证与安全检查

**文件：**
- 测试：所有 FlyAI/酒店/高德相关测试和现有全量测试。

- [ ] **步骤 1：运行专项测试**

```bash
cd backend
python -m pytest tests/test_flyai_hotel*.py tests/test_fliggy_hotel*.py -q
```

预期：全部通过；所有调用均使用 fake CLI/MCP，不发送真实 Key。

- [ ] **步骤 2：运行现有回归测试**

```bash
python -m pytest tests/test_amap.py tests/test_agents_poi.py tests/test_api.py tests/test_fliggy*.py -q
```

预期：现有高德住宿、旅行规划、门票和 TOP 企业模式不变。

- [ ] **步骤 3：运行全量与静态检查**

```bash
python -m pytest -q
python -m compileall -q app tests
cd ../frontend
node --check app.js
```

预期：全部测试通过，编译和语法检查返回 0；仅允许已有警告。

- [ ] **步骤 4：检查敏感信息和工作区**

```bash
git diff --check
git grep -n -E "sk-[A-Za-z0-9_-]{20,}|FLYAI_API_KEY=[^$]*" -- backend frontend || true
git status --short
```

预期：仓库中无真实 Key；Key 只通过运行环境注入；不删除用户已有日志或无关修改。

- [ ] **步骤 5：提交最终修正**

```bash
git add backend frontend docs/superpowers/plans/2026-08-25-flyai-hotel-poi-recommendation.md
git commit -m "test: verify flyai hotel recommendations"
```
