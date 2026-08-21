# 旅行合同深层不可变实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 v1 跨 Agent 旅行数据合同改为深层不可变对象，防止构造后通过字段赋值、集合原地修改或嵌套模型修改破坏合同不变量。

**架构：** 所有旅行领域模型统一继承冻结的 `StrictModel`，所有零至多项字段以元组保存。Pydantic 继续接受 JSON 数组输入并输出 JSON 数组；模型内部不暴露可变列表。Agent、编排器和汇总器必须根据已有数据构造新合同对象，而不能补写已接收的结果。

**技术栈：** Python 3.12、Pydantic 2.11、pytest 8.3。

---

## 范围与非目标

- 包含：`backend/app/models/travel.py` 的深层冻结与元组字段；`backend/tests/test_models.py` 的回归测试和既有断言对齐；设计规格与原实现计划的代码示例对齐。
- 不包含：外部服务、API、Agent 编排、前端、`Source.type` 与 `data_status` 的额外映射规则、以及 Agent `partial` 状态到最终文档状态的映射。
- `partial` 映射保持未定义；不得在本计划中修改 `TravelPlanDocument` 的整体状态矩阵。

## 文件结构

- 修改：`backend/app/models/travel.py` — 冻结全部领域模型，将集合字段改为元组，并保持 UUID、固定 Agent 名称、槽位与状态合同。
- 修改：`backend/tests/test_models.py` — 先证明深层篡改当前可发生，再验证冻结模型和元组字段阻断各路径；同步既有列表断言为元组断言。
- 修改：`docs/superpowers/specs/2026-08-19-travel-data-contract-design.md` — 保持已批准的深层不可变规则与实现状态一致。
- 修改：`docs/superpowers/plans/2026-08-19-travel-data-contract.md` — 将已过时的 `list[...]`、`default_factory=list`、裸 `str` 标识符和 `StrictModel` 示例同步为当前合同；不改动无关任务。
- 创建：`docs/superpowers/plans/2026-08-20-travel-contract-immutability.md` — 本计划。

## 统一执行约定

所有命令从工作树根目录执行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

完整后端回归：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests -v
```

---

### 任务 1：用失败测试固定深层不可变边界

**文件：**
- 修改：`backend/tests/test_models.py`

- [x] **步骤 1：添加请求、结果信封与嵌套领域模型的失败测试**

在现有 `travel_plan_data()` 辅助函数之后添加：

```python
def test_contract_models_store_collection_fields_as_tuples():
    request = TravelPlanRequest(
        origin="上海",
        destination="杭州",
        departure_date=date.today(),
        travelers=2,
        preferences=["亲子"],
    )
    result = travel_plan_data().weather

    assert request.preferences == ("亲子",)
    assert result.constraints == ()
    assert result.data.daily[0].equipment_suggestions == ()


def test_contract_models_reject_collection_and_nested_field_mutation():
    result = travel_plan_data().weather

    with pytest.raises(AttributeError):
        result.constraints.append("避免户外活动")
    with pytest.raises(AttributeError):
        result.data.daily.clear()
    with pytest.raises(ValidationError):
        result.data.destination = "宁波"


def test_request_rejects_assignment_after_construction():
    request = TravelPlanRequest(
        origin="上海",
        destination="杭州",
        departure_date=date.today(),
        travelers=2,
    )

    with pytest.raises(ValidationError):
        request.destination = "宁波"
```

在已有集合断言中把预期值调整为元组，例如：

```python
assert request.preferences == ()
assert poi.model_dump()["source_ids"] == ("source-1",)
assert lodging.facilities == ()
```

- [ ] **步骤 2：运行新测试，确认其因功能缺失失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v -k "store_collection_fields_as_tuples or reject_collection_and_nested_field_mutation or request_rejects_assignment_after_construction"
```

预期：FAIL。当前模型仍保存 `list`，`append` 和 `clear` 不会抛异常，且 `TravelPlanRequest.destination` 可被改写。

- [ ] **步骤 3：确认失败原因只来自缺少深层不可变性**

检查失败信息必须包含以下至少一项，而不是导入或语法错误：

```text
AssertionError
Failed: DID NOT RAISE
```

- [ ] **步骤 4：Commit 测试红灯状态（仅在项目允许保留失败提交时）**

本项目默认不提交故意失败的测试。跳过提交，继续同一工作树完成最小实现。

---

### 任务 2：以冻结模型与元组实现深层不可变性

**文件：**
- 修改：`backend/app/models/travel.py`
- 修改：`backend/tests/test_models.py`

- [x] **步骤 1：将严格模型改为冻结模型**

将 `StrictModel` 配置替换为：

```python
class StrictModel(BaseModel):
    """禁止接收未声明字段且构造后不可修改的基础模型。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
```

不要保留仅用于浅层赋值校验的 `validate_assignment=True`，也不要在 `AgentResult` 上单独定义与基类冲突的 `model_config`。

- [x] **步骤 2：将所有集合字段改为元组**

在 `backend/app/models/travel.py` 中将以下字段统一改成元组类型；无元素默认值使用 `()`，至少一项使用 `Field(min_length=1)`：

```python
preferences: tuple[NonEmptyText, ...] = ()
tags: tuple[NonEmptyText, ...] = ()
source_ids: tuple[NonEmptyText, ...] = Field(min_length=1)
equipment_suggestions: tuple[NonEmptyText, ...] = ()
daily: tuple[DailyWeather, ...] = Field(min_length=1)
constraints: tuple[NonEmptyText, ...] = ()
daily_areas: tuple[DailyArea, ...] = Field(min_length=1)
facilities: tuple[NonEmptyText, ...] = ()
suitable_for: tuple[NonEmptyText, ...] = ()
candidates: tuple[LodgingCandidate, ...] = ()
filter_suggestions: tuple[NonEmptyText, ...] = ()
specialties: tuple[NonEmptyText, ...] = ()
dietary_notes: tuple[NonEmptyText, ...] = ()
daily_food: tuple[DailyFoodPlan, ...] = Field(min_length=1)
sources: tuple[Source, ...] = ()
warnings: tuple[NonEmptyText, ...] = ()
missing_fields: tuple[NonEmptyText, ...] = ()
degraded_agents: tuple[AgentName, ...] = ()
```

对 `FoodCandidate.suitable_for`、`DailyFoodPlan.candidates` 与 `DailyFoodPlan.filter_suggestions` 使用同一规则。保留字段名、JSON 表现和现有长度约束。Pydantic 会把传入的 JSON 数组转换为元组。

- [x] **步骤 3：保留输入清洗并使其兼容元组结果**

将请求偏好清洗器的注解与实现保持输入阶段只接受 `list[str]` 的策略：

```python
@field_validator("origin", "destination", "preferences", mode="before")
@classmethod
def strip_text_values(cls, value: str | list[str]) -> str | list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value]
    return value.strip()
```

不要把 Python `tuple` 作为请求输入放宽为合法值；这维持已有“非 JSON 数组输入被拒绝”的测试意图。字段声明负责把合法列表转换为内部元组。

- [x] **步骤 4：更新测试辅助函数与既有断言**

保留测试输入为列表，更新输出断言为元组。例如：

```python
assert request.preferences == ()
assert request.preferences == ("a" * 100,)
assert lodging.facilities == ()
assert food.specialties == ()
```

在 `travel_plan_data()` 与 `travel_plan_document_payload()` 中继续传入列表；模型构造后断言得到元组。对于从 `model_dump()` 得到的元组，构造 `degraded_agents` 时改为：

```python
degraded_agents = tuple(
    name
    for name, result in itinerary.model_dump().items()
    if result["status"] is AgentStatus.degraded
)
```

- [x] **步骤 5：运行深层不可变测试，确认转绿**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v -k "store_collection_fields_as_tuples or reject_collection_and_nested_field_mutation or request_rejects_assignment_after_construction"
```

预期：PASS，所有新测试通过；集合为元组，属性赋值和原地集合修改被拒绝。

- [x] **步骤 6：运行完整模型测试**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

预期：PASS，所有模型测试通过。

- [ ] **步骤 7：Commit**

```powershell
git add backend/app/models/travel.py backend/tests/test_models.py
git commit -m "feat: make travel contracts deeply immutable"
```

---

### 任务 3：对齐规格与原实现计划

**文件：**
- 修改：`docs/superpowers/specs/2026-08-19-travel-data-contract-design.md`
- 修改：`docs/superpowers/plans/2026-08-19-travel-data-contract.md`

- [x] **步骤 1：同步原计划中的基础模型、集合与标识符示例**

在 `docs/superpowers/plans/2026-08-19-travel-data-contract.md` 中：

- 将所有 `ConfigDict(extra="forbid")` 示例改为 `ConfigDict(extra="forbid", frozen=True)`；
- 将所有合同字段 `list[...]` 与 `default_factory=list` 改为任务 2 的元组声明和 `()` 默认值；
- 将 `AgentResult` 与 `TravelPlanDocument` 的 `request_id`、`trace_id` 示例改为当前实现共用的 `UUIDV1ToV5` 类型；
- 保持所有 `AgentName` 成员为小写；
- 在集合输入处说明 JSON 数组会转换为内部元组；
- 保留 `partial` 顶层状态映射未定义的边界，不添加新的状态矩阵。

- [x] **步骤 2：将设计规格状态更新为已实现待验证**

在 `docs/superpowers/specs/2026-08-19-travel-data-contract-design.md` 的状态行替换为：

```markdown
**状态：** 深层不可变已实现，待验证
```

仅在任务 2 的完整模型测试通过后执行此更新。

- [x] **步骤 3：运行文档格式检查**

运行：

```powershell
git diff --check -- docs/superpowers/specs/2026-08-19-travel-data-contract-design.md docs/superpowers/plans/2026-08-19-travel-data-contract.md docs/superpowers/plans/2026-08-20-travel-contract-immutability.md
```

预期：退出码 `0`，无 whitespace error。

- [ ] **步骤 4：Commit**

```powershell
git add docs/superpowers/specs/2026-08-19-travel-data-contract-design.md docs/superpowers/plans/2026-08-19-travel-data-contract.md docs/superpowers/plans/2026-08-20-travel-contract-immutability.md
git commit -m "docs: specify immutable travel contracts"
```

---

### 任务 4：执行完整回归与合同检查

**文件：**
- 验证：`backend/app/models/travel.py`
- 验证：`backend/tests/test_models.py`

- [x] **步骤 1：运行完整后端回归**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests -v
```

预期：PASS，`test_models.py` 和 `test_api.py` 均通过。

- [x] **步骤 2：验证导入和元组序列化边界**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -c "from app.models.travel import TravelPlanRequest; from datetime import date; request = TravelPlanRequest(origin='上海', destination='杭州', departure_date=date.today(), travelers=2, preferences=['亲子']); print(type(request.preferences).__name__); print(request.model_dump(mode='json')['preferences'])"
```

预期输出：

```text
tuple
['亲子']
```

- [x] **步骤 3：验证合同源文件不再声明可变列表字段**

运行：

```powershell
rg -n "list\[|default_factory=list" backend/app/models/travel.py
```

预期：无匹配，退出码为 `1`。

- [ ] **步骤 4：最终变更检查**

运行：

```powershell
git diff --check
git status --short
```

预期：`git diff --check` 退出码 `0`；状态只列出本计划涉及的模型、测试和文档变更，除非用户另有并发修改。

- [ ] **步骤 5：Commit（若前序任务未提交）**

```powershell
git add backend/app/models/travel.py backend/tests/test_models.py docs/superpowers/specs/2026-08-19-travel-data-contract-design.md docs/superpowers/plans/2026-08-19-travel-data-contract.md docs/superpowers/plans/2026-08-20-travel-contract-immutability.md
git commit -m "feat: make travel contracts deeply immutable"
```

---

## 验证记录

- 此前已执行验证：模型测试 135 项通过，全量后端回归 138 项通过。
- 本次加入 UUID 大小写一致性回归测试后重新执行：模型测试 136 项通过，全量后端回归 139 项通过。

## 计划自检

### 规格覆盖度

- 冻结所有领域模型：任务 2，步骤 1。
- 以元组保存所有集合字段：任务 2，步骤 2。
- JSON 数组输入、内部元组和 JSON 数组输出：任务 2，步骤 3 与任务 4，步骤 2。
- 阻断属性赋值、集合原地修改与嵌套对象修改：任务 1 与任务 2，步骤 5。
- UUID、固定 Agent 名称、槽位绑定与既有状态规则保持不变：任务 2 的最小实现范围。
- 规格与原计划不再漂移：任务 3。
- `partial` 顶层映射不实现：范围与非目标、任务 3。

### 占位符扫描

已逐项检查：每个代码变更步骤提供具体文件、代码片段、命令与预期结果，没有未定义实现描述。

### 类型一致性

- 所有集合字段在模型内部统一为 `tuple[T, ...]`；非空集合继续使用 `Field(min_length=1)`。
- 所有模型统一继承冻结的 `StrictModel`。
- `UUIDV1ToV5` 是 `AgentResult` 和 `TravelPlanDocument` 的共同标识符类型。
- `AgentName` 成员始终为小写：`weather`、`route`、`lodging`、`food`。
