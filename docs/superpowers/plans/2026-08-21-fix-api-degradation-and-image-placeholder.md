# 外部 API 降级与图片 CSS 占位修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复三个外部 API 降级根因（天气 adcode、驾车 v5 无 duration、住宿/餐饮分类精确匹配）和一个前端图片 CSS 场景占位问题，使 4 个专业 Agent 恢复 `success` 且首页轮播图片正常展示照片。

**架构：** 后端为 3 个相互独立的服务端适配修复：① 天气 Agent 将高德地理编码返回的**经纬度**（而非 adcode）传给和风天气；② 高德驾车从 v5 接口切换到 v3 接口（v5 对当前 key 不返回 `duration`）；③ 住宿/餐饮 Agent 的 POI 分类校验改为取高德 `type` 分层串的**首段**。前端为 1 处 CSS 修复：`.has-image` 时隐藏 CSS 绘制的场景子元素。全部修复遵循现有受控错误、来源溯源与测试模式。

**技术栈：** Python 3.12 / FastAPI / pytest 8 / respx / httpx；纯前端 CSS（无前端测试框架，CSS 修复采用浏览器人工验证）。

---

## 文件结构

| 文件 | 职责 | 变更类型 |
|---|---|---|
| `backend/app/agents/weather.py` | 天气 Agent：传高德经纬度给和风 | 修改（1 行） |
| `backend/app/services/amap.py` | 高德客户端：驾车改用 v3 接口 | 修改（2 处路径） |
| `backend/app/agents/lodging.py` | 住宿 Agent：POI 分类取层级串首段 | 修改（1 行） |
| `backend/app/agents/food.py` | 餐饮 Agent：POI 分类取层级串首段 | 修改（1 行） |
| `frontend/styles.css` | 首页轮播：`.has-image` 隐藏 CSS 场景 | 修改（新增规则） |
| `backend/tests/test_agents_weather_route.py` | 天气 Agent 回归测试 | 修改 + 新增 |
| `backend/tests/test_amap.py` | 高德客户端回归测试 | 修改（mock URL） |
| `backend/tests/test_agents_poi.py` | 住宿/餐饮 Agent 回归测试 | 修改 + 新增 |
| `README.md` | 高德驾车端点文档 | 修改（v5→v3） |

不改动：`docs/superpowers/plans/2026-08-18-sequential-travel-agents-core.md`（历史设计记录）、`.claude/worktrees/**`（隔离分支）。

---

## 任务 1：天气 Agent 改用高德经纬度（非 adcode）

**背景根因：** `backend/app/agents/weather.py:40` 传 `location["adcode"]`（如 `510100`）给和风 `/v7/weather/3d`，实测该 key 返回 `400 invalid-parameter`；而传 `location["location"]`（经纬度，如 `104.066301,30.572961`）返回 `code:200`。

**文件：**
- 修改：`backend/app/agents/weather.py:40`
- 测试：`backend/tests/test_agents_weather_route.py:126`

- [ ] **步骤 1：改写现有断言 + 新增聚焦测试**

将 `test_agents_weather_route.py` 第 126 行的断言从传 adcode 改为传经纬度：

```python
# 第 126 行：将 "330100"（adcode）改为 "120,30"（geocode 返回的 location）
assert agent.weather_client.calls == [("120,30", request(days=1).departure_date, request(days=1).days)]
```

在 `test_agents_weather_route.py` 末尾新增聚焦测试：

```python
def test_weather_agent_uses_geocoded_coordinates_not_adcode():
    agent = WeatherAgent(
        amap_client=FakeAmapClient(
            geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}
        ),
        weather_client=FakeWeatherClient(weather_payload(days=1)),
    )

    __import__("asyncio").run(agent.run(request(days=1), **ids()))

    assert agent.weather_client.calls[0][0] == "120,30"
    assert agent.weather_client.calls[0][0] != "330100"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && PYTHONPATH=. python -m pytest tests/test_agents_weather_route.py -q`
预期：FAIL——weather 客户端收到的仍是 `"330100"`，断言不成立。

- [ ] **步骤 3：修改实现**

`backend/app/agents/weather.py:40`：

```python
# 修改前
location_id = location["adcode"]
# 修改后：和风接受经纬度，不接受高德 adcode
location_id = location["location"]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && PYTHONPATH=. python -m pytest tests/test_agents_weather_route.py -q`
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/agents/weather.py backend/tests/test_agents_weather_route.py
git commit -m "fix: pass amap coordinates to qweather forecast instead of adcode"
```

---

## 任务 2：驾车路线改用高德 v3 接口

**背景根因：** `backend/app/services/amap.py` 调用 `/v5/direction/driving`，实测该接口（当前 key）响应 `route.paths[0]` **不含 `duration`**（长/短路、加 `strategy` 均无）；而 `/v3/direction/driving` 返回 `duration`（秒）。客户端 `_project` 强制要求 `duration`，导致路线恒降级。

**文件：**
- 修改：`backend/app/services/amap.py:48`、`backend/app/services/amap.py:108`
- 测试：`backend/tests/test_amap.py`（8 处 mock URL）
- 文档：`README.md:109`

- [ ] **步骤 1：将测试中的驾车 mock URL 改为 v3**

对 `backend/tests/test_amap.py` 执行全局替换：`/v5/direction/driving` → `/v3/direction/driving`（涉及第 24、52、205、257、264、266、313、386 行）。mock 响应体不变（`{"distance": "...", "duration": "..."}` 与 v3 结构一致）。

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && PYTHONPATH=. python -m pytest tests/test_amap.py -q`
预期：FAIL——客户端仍请求 `/v5/direction/driving`，respx 无法拦截，真实网络请求失败。

- [ ] **步骤 3：修改实现**

`backend/app/services/amap.py` 两处路径：

```python
# 第 48 行：driving_route 内
result = await self._get("route", [origin, destination], "/v3/direction/driving", {"origin": origin, "destination": destination}, self.route_cache_ttl_seconds)

# 第 108 行：_project 内
if path == "/v3/direction/driving":
```

（第 117 行 `if path != "/v5/place/text":` 不变。）

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && PYTHONPATH=. python -m pytest tests/test_amap.py -q`
预期：PASS。

- [ ] **步骤 5：更新 README 文档**

`README.md:109` 将 `GET /v5/direction/driving` 改为 `GET /v3/direction/driving`，其余文字不变。

- [ ] **步骤 6：Commit**

```bash
git add backend/app/services/amap.py backend/tests/test_amap.py README.md
git commit -m "fix: use amap v3 driving endpoint which returns duration"
```

---

## 任务 3：住宿/餐饮 Agent 接受层级分类

**背景根因：** 高德 POI 的 `type` 字段是分号层级串（如 `住宿服务;宾馆;连锁`、`餐饮服务;中餐厅;中餐厅`）。`backend/app/agents/lodging.py` 与 `backend/app/agents/food.py` 的 `_poi` 用 `category != expected_category` **精确比较**，导致每个 POI 都校验失败、候选为空、Agent 降级。

**文件：**
- 修改：`backend/app/agents/lodging.py:116`、`backend/app/agents/food.py:175`
- 测试：`backend/tests/test_agents_poi.py:57`

- [ ] **步骤 1：改写住宿测试并新增餐饮测试**

将 `test_agents_poi.py:57` 的 `test_lodging_rejects_non_exact_hierarchical_category` 改写为接受层级分类：

```python
@pytest.mark.asyncio
async def test_lodging_accepts_hierarchical_category_first_segment():
    client = FakePoiClient({("住宿服务", "杭州1日区域"): [poi(category="住宿服务;宾馆;连锁")]})

    result = await LodgingAgent(client).run(request(), areas(), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.success
    assert result.data.candidates[0].poi.category == "住宿服务"
```

在 `test_agents_poi.py` 新增餐饮等价测试：

```python
@pytest.mark.asyncio
async def test_food_accepts_hierarchical_category_first_segment():
    client = FakePoiClient({("餐饮服务", "杭州1日区域"): [poi(name="餐馆", category="餐饮服务;中餐厅;中餐厅")]})

    result = await FoodAgent(client).run(request(days=1), areas(days=1), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.success
    assert result.data.daily_food[0].candidates[0].poi.category == "餐饮服务"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && PYTHONPATH=. python -m pytest tests/test_agents_poi.py -q`
预期：FAIL——两个新用例中 POI 被拒绝，状态为 `degraded`。

- [ ] **步骤 3：修改实现（住宿）**

`backend/app/agents/lodging.py:116`：

```python
# 修改前
category = category.strip()
# 修改后：取高德 type 分层串的首段（如 "住宿服务;宾馆;连锁" -> "住宿服务"）
category = category.strip().split(";")[0].strip()
```

- [ ] **步骤 4：修改实现（餐饮）**

`backend/app/agents/food.py:175` 同款修改：

```python
category = category.strip().split(";")[0].strip()
```

- [ ] **步骤 5：运行测试验证通过**

运行：`cd backend && PYTHONPATH=. python -m pytest tests/test_agents_poi.py -q`
预期：PASS（含既有的 `test_lodging_rejects_non_lodging_category`、`test_food_rejects_non_food_category`，它们仍应通过）。

- [ ] **步骤 6：Commit**

```bash
git add backend/app/agents/lodging.py backend/app/agents/food.py backend/tests/test_agents_poi.py
git commit -m "fix: match first segment of amap hierarchical poi category"
```

---

## 任务 4：首页轮播图片隐藏 CSS 场景占位

**背景根因：** 每个 `.travel-slide` 内部有 CSS 场景子元素（`.travel-sky`、`.travel-mountain`、`.travel-road`），`styles.css` 的 `.has-image` 只设置了 `background-image` 与 `background-size`，**没有隐藏这些子元素**。它们绝对定位绘制在照片之上，导致即使图片加载成功，页面仍显示 CSS 绘制的山/路/天空。

**文件：**
- 修改：`frontend/styles.css`（在 `.travel-slide.has-image` 规则之后，约第 179 行）

- [ ] **步骤 1：新增 CSS 规则**

在 `frontend/styles.css` 中 `.travel-slide.has-image::after` 规则之后添加：

```css
.travel-slide.has-image .travel-sky,
.travel-slide.has-image .travel-mountain,
.travel-slide.has-image .travel-road { opacity: 0; }
```

（保留 `.travel-pin` 标签与 `.travel-dots` 圆点可见。）

- [ ] **步骤 2：浏览器人工验证**

启动后端（`python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`），打开 `http://127.0.0.1:8000/` 并**硬刷新**（Ctrl+F5，清掉早期 404 缓存）。预期：三个轮播幻灯片显示真实照片（`travel-mountain.jpg` / `travel-coast.jpg` / `travel-ancient-city.jpg`），不再叠加 CSS 绘制的山、路、天空。前端无自动化测试框架，采用此人工验证。

- [ ] **步骤 3：Commit**

```bash
git add frontend/styles.css
git commit -m "fix: hide css scenery children once travel photo loads"
```

---

## 任务 5：全量回归与真实 API 验证

**文件：** 无代码改动。

- [ ] **步骤 1：运行完整后端测试套件**

运行：`cd backend && PYTHONPATH=. python -m pytest -q`（或项目文档的 `python -m pytest -c backend/pytest.ini backend/tests -q`）
预期：全部通过（580 个既有 + 新增用例）。

- [ ] **步骤 2：启动后端并发送真实旅行规划请求**

确认后端运行后，发送真实请求（用 UTF-8 文件避免 shell 编码问题）：

```bash
cat > /tmp/payload.json << 'EOF'
{"origin":"北京","destination":"成都","departure_date":"2026-08-22","travelers":2,"days":3,"preferences":["美食"]}
EOF
curl -s -X POST "http://127.0.0.1:8000/api/travel-plans" \
  -H "Content-Type: application/json" --data-binary @/tmp/payload.json
```

> 注意：出发日期须在和风 3 日预报窗口内（今天至后天），否则天气 Agent 因 3d 接口只返回今起 3 日、无匹配 `fxDate` 而**降级**（`daily_forecast` 缺失）——那是 3d 接口固有的日期窗口限制，非本次修复范围。

预期：`status` 为 `success`，`degraded_agents` 为空，`itinerary.weather/route/lodging/food` 的 `status` 均为 `success`。

- [ ] **步骤 3：确认无残留 v5 驾车引用**

运行：`grep -rn "v5/direction/driving" --include="*.py" --include="*.md" backend README.md | grep -v worktrees`
预期：无输出（历史设计文档 `docs/superpowers/plans/2026-08-18-sequential-travel-agents-core.md` 除外）。

---

## 自检记录

- **规格覆盖度：** 4 个 Agent 降级根因（天气/路线/住宿/餐饮）各有对应任务；图片占位有对应任务；全量回归任务覆盖验证。
- **占位符扫描：** 无"待定/TODO"；每个代码改动均给出完整代码块与精确命令。
- **类型一致性：** 测试断言引用的 `FakeWeatherClient.calls`、`FakeAmapClient`、`poi()` 辅助函数、`source_metadata`、`ids()` 均为 `test_agents_weather_route.py` / `test_agents_poi.py` 既有定义；`AmapClient._project` 路径分支与 `driving_route` 的路径字符串保持一致。
- **已知边界：** 天气出发日期超过和风 3 日预报窗口（今起 3 日）时，3d 接口无匹配 `fxDate`，天气 Agent 按现有逻辑降级（`missing_fields=daily_forecast`）——属 3d 接口固有窗口限制，不在本次修复范围；`image/travel-*.jpg` 尚未纳入 git，建议后续由用户决定是否提交。
