# 自定义行程描述字段解析实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 稳定提取自定义行程描述的必填字段，并在信息缺失时一次提示首个具体字段。

**架构：** `TravelQueryParser` 以规则识别地点、日期、天数、成人/儿童总人数与两类偏好，规则结果覆盖模型同名字段；模型失败时仍返回规则结果和缺失字段。前端只消费响应中的首个缺失或待确认字段，生成可行动的单字段提示。

**技术栈：** Python 3.12、FastAPI、Pydantic、pytest、原生 JavaScript。

---

## 文件结构

- 修改：`backend/app/services/query_parser.py` — 规则提取、模型结果合并与模型失败降级。
- 创建：`backend/tests/test_query_parser.py` — 旅行描述规则提取与降级回归测试。
- 修改：`frontend/app.js` — 将多字段汇总报错改为首个字段的明确提示。
- 修改：`backend/tests/test_frontend_assets.py` — 约束前端保留单字段提示逻辑。

### 任务 1：规则提取与模型失败降级

**文件：**
- 创建：`backend/tests/test_query_parser.py`
- 修改：`backend/app/services/query_parser.py:11-37`

- [ ] **步骤 1：编写失败的解析器测试**

```python
from datetime import date

import pytest

from app.services.query_parser import TravelQueryParser


class StaticClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return '{"preferences": []}'


class FailingClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        raise RuntimeError("模型不可用")


@pytest.mark.asyncio
async def test_parse_extracts_adult_child_total_and_date_without_year():
    parser = TravelQueryParser(StaticClient(), today=date(2026, 9, 2))

    result = await parser.parse("两位成人带一个孩子，9.10日从北京到成都玩3天，不吃辣，行程不要太赶")

    assert result.origin == "北京"
    assert result.destination == "成都"
    assert result.departure_date == date(2026, 9, 10)
    assert result.travelers == 3
    assert result.days == 3
    assert result.preferences == ("不吃辣", "行程不要太赶")
    assert result.missing_fields == ()


@pytest.mark.asyncio
async def test_parse_returns_only_unrecognized_required_field_when_model_fails():
    parser = TravelQueryParser(FailingClient(), today=date(2026, 9, 2))

    result = await parser.parse("9.10日从北京到成都玩3天")

    assert result.origin == "北京"
    assert result.destination == "成都"
    assert result.departure_date == date(2026, 9, 10)
    assert result.days == 3
    assert result.travelers is None
    assert result.missing_fields == ("travelers",)
```

- [ ] **步骤 2：运行测试并验证失败**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_query_parser.py -v`

预期：FAIL。当前实现不接受 `today` 参数，且不会从成人、儿童、无年份日期或中文偏好中提取信息；模型异常会直接向上抛出。

- [ ] **步骤 3：实现最小规则提取与结果合并**

在 `TravelQueryParser` 中添加以下依赖、常量和方法，并替换当前的 `__init__` 与 `parse`：

```python
from datetime import date


class TravelQueryParser:
    _required_fields = ("origin", "destination", "departure_date", "travelers", "days")
    _number_values = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    _field_patterns = {
        "origin_destination": re.compile(r"从(?P<origin>[\u4e00-\u9fff]{2,20})到(?P<destination>[\u4e00-\u9fff]{2,20})(?:玩|旅游|出行|，|,|。|$)"),
        "date": re.compile(r"(?:(?P<year>20\d{2})[年./-])?(?P<month>\d{1,2})[月./-](?P<day>\d{1,2})(?:日|号)?"),
        "days": re.compile(r"(?:玩|游|旅行|出行)?\s*(?P<days>\d+)\s*天"),
        "party": re.compile(r"(?P<count>\d+|[一二两三四五六七八九十])\s*(?:位|个|名)?\s*(?:成人|大人|儿童|孩子|小孩|老人|婴儿)"),
    }

    def __init__(self, client: DeepSeekClient, *, today: date | None = None) -> None:
        self.client = client
        self.today = today or date.today()

    async def parse(self, query: str) -> TravelQueryParseResponse:
        rule_values = self._rule_values(query)
        try:
            content = await self.client.chat_completion(
                "你是旅行需求信息抽取器。只输出 JSON，不要 Markdown 或解释。日期使用 YYYY-MM-DD。无法确定的字段填 null。",
                json.dumps({"query": query, "fields": ["origin", "destination", "departure_date", "travelers", "days", "budget", "preferences"]}, ensure_ascii=False),
            )
            model_result = TravelQueryParseResponse.model_validate(self._json_payload(content))
        except Exception:
            model_result = TravelQueryParseResponse()
        values = {
            name: rule_values[name] if rule_values[name] is not None else getattr(model_result, name)
            for name in self._required_fields
        }
        preferences = tuple(dict.fromkeys((*rule_values["preferences"], *model_result.preferences)))
        return TravelQueryParseResponse(
            **values,
            budget=model_result.budget,
            preferences=preferences,
            missing_fields=self._missing_fields(values),
            ambiguous_fields=model_result.ambiguous_fields,
        )

    def _rule_values(self, query: str) -> dict[str, object]:
        values: dict[str, object] = {name: None for name in self._required_fields}
        values["preferences"] = tuple(
            label
            for label, phrases in (("不吃辣", ("不吃辣", "不要辣", "不吃辛辣")), ("行程不要太赶", ("行程不要太赶", "不要太赶", "轻松游")))
            if any(phrase in query for phrase in phrases)
        )
        location = self._field_patterns["origin_destination"].search(query)
        if location:
            values["origin"] = location.group("origin")
            values["destination"] = location.group("destination")
        date_match = self._field_patterns["date"].search(query)
        if date_match:
            values["departure_date"] = self._parse_date(date_match)
        day_match = self._field_patterns["days"].search(query)
        if day_match:
            values["days"] = int(day_match.group("days"))
        party_counts = [self._parse_count(match.group("count")) for match in self._field_patterns["party"].finditer(query)]
        if party_counts and all(count is not None for count in party_counts):
            total = sum(party_counts)
            values["travelers"] = total if 1 <= total <= 20 else None
        return values

    def _parse_date(self, match: re.Match[str]) -> date | None:
        year = int(match.group("year") or self.today.year)
        try:
            parsed = date(year, int(match.group("month")), int(match.group("day")))
            return date(year + 1, parsed.month, parsed.day) if match.group("year") is None and parsed < self.today else parsed
        except ValueError:
            return None

    def _parse_count(self, value: str) -> int | None:
        return int(value) if value.isdigit() else self._number_values.get(value)

    @staticmethod
    def _missing_fields(values: dict[str, object]) -> tuple[str, ...]:
        return tuple(name for name in TravelQueryParser._required_fields if values.get(name) is None)
```

`parse` 在 `chat_completion`、JSON 解析或 Pydantic 校验抛出异常时，使用空模型值继续合并，返回 `TravelQueryParseResponse`，并由 `_missing_fields` 重新计算缺失项。合并偏好时按出现顺序去重，保留规则识别出的“不吃辣”“行程不要太赶”。

- [ ] **步骤 4：运行解析器测试并验证通过**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_query_parser.py -v`

预期：2 passed。

- [ ] **步骤 5：提交原子变更**

```powershell
git add backend/app/services/query_parser.py backend/tests/test_query_parser.py
git commit -m "feat: 增强行程描述字段解析"
```

### 任务 2：单字段缺失提示

**文件：**
- 修改：`backend/tests/test_frontend_assets.py`
- 修改：`frontend/app.js:272-275`

- [ ] **步骤 1：编写失败的前端提示约束测试**

在 `backend/tests/test_frontend_assets.py` 添加：

```python
def test_frontend_prompts_only_the_first_missing_travel_field():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "const field = [...new Set(missing)][0]" in script
    assert "请补充${labels[field] || field}" in script
    assert "以下字段是必填项或信息不明确" not in script
```

- [ ] **步骤 2：运行测试并验证失败**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py::test_frontend_prompts_only_the_first_missing_travel_field -v`

预期：FAIL。当前代码拼接全部字段，并使用“以下字段是必填项或信息不明确”的泛化文案。

- [ ] **步骤 3：实施首字段提示**

将 `frontend/app.js` 中的缺失字段分支替换为：

```javascript
const labels = { origin: "始发地", destination: "目的地", departure_date: "出行日期", travelers: "出行人数", days: "出行天数" };
const field = [...new Set(missing)][0];
const prefix = (parsed.ambiguous_fields || []).includes(field) ? "请确认" : "请补充";
throw new Error(`${prefix}${labels[field] || field}`);
```

- [ ] **步骤 4：运行前端提示测试并验证通过**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py::test_frontend_prompts_only_the_first_missing_travel_field -v`

预期：1 passed。

- [ ] **步骤 5：提交原子变更**

```powershell
git add frontend/app.js backend/tests/test_frontend_assets.py
git commit -m "fix: 精确提示缺失行程字段"
```

### 任务 3：回归验证

**文件：**
- 验证：`backend/tests/test_query_parser.py`
- 验证：`backend/tests/test_planning_api.py`
- 验证：`backend/tests/test_frontend_assets.py`

- [ ] **步骤 1：运行关联测试集**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_query_parser.py backend/tests/test_planning_api.py backend/tests/test_frontend_assets.py -q`

预期：全部通过，无失败、跳过或警告。

- [ ] **步骤 2：运行完整后端测试集**

运行：`$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests -q`

预期：全部通过。

- [ ] **步骤 3：检查变更范围**

运行：`git diff --check; git status --short`

预期：无空白错误；仅出现计划列出的实现、测试与设计文档变更，已有的用户工作区修改保持不变。
