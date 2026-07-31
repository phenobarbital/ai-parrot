---
type: Wiki Overview
title: 'TASK-1013: Input Schemas, Result Envelopes & Entity Models (Phase 1 + Phase
  2)'
id: doc:sdd-tasks-completed-task-1013-odoo-pydantic-models-phase1-phase2-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: All other tasks import Pydantic input schemas, result envelopes, and entity
  models.
relates_to:
- concept: mod:parrot_tools.odoo.models.entities
  rel: mentions
- concept: mod:parrot_tools.odoo.models.envelopes
  rel: mentions
- concept: mod:parrot_tools.odoo.models.inputs
  rel: mentions
---

# TASK-1013: Input Schemas, Result Envelopes & Entity Models (Phase 1 + Phase 2)

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

All other tasks import Pydantic input schemas, result envelopes, and entity models.
This task creates them all upfront — both Phase 1 and Phase 2 models — so
subsequent tasks have stable imports from day one.

Implements spec §2 "Data Models" (all input schemas, all result envelopes, all
entity models).

---

## Scope

- Add **Phase 1 input schemas** to `models/inputs.py`:
  `AggregateRecordsInput`, `BuildDomainInput`, `GetOdooProfileInput`,
  `SchemaCatalogInput`, `InspectModelRelationshipsInput`, `DiagnoseAccessInput`,
  `SearchEmployeeInput`, `SearchHolidaysInput`

- Add **Phase 2 input schemas** to `models/inputs.py`:
  `DiagnoseOdooCallInput`, `GenerateJson2PayloadInput`, `ScanAddonsSourceInput`,
  `FitGapReportInput`, `BusinessPackReportInput`

- Add **Phase 1 result envelopes** to `models/envelopes.py`:
  `AggregateResult`, `DomainBuildResult`, `OdooProfileResult`,
  `SchemaCatalogResult`, `ModelRelationshipsResult`, `AccessDiagnosisResult`,
  `HealthCheckResult`

- Add **Phase 2 result envelopes** to `models/envelopes.py`:
  `OdooCallDiagnosisResult`, `Json2PayloadResult`, `AddonScanResult`,
  `FitGapResult`, `BusinessPackResult`

- Add **HR entity models** to `models/entities.py`:
  `HrEmployee`, `HrLeave`

- Update `__all__` exports in each file.

**NOT in scope**: Toolkit methods, smart-field logic, tests for toolkit methods.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` | MODIFY | Add 13 new input schemas |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py` | MODIFY | Add 12 new result envelopes |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py` | MODIFY | Add `HrEmployee`, `HrLeave` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# models/inputs.py — base class for all inputs
from pydantic import BaseModel, ConfigDict, Field   # verified: models/inputs.py:9-10
from typing import Any, Literal, Optional            # verified: models/inputs.py:9

# models/inputs.py:19
class _OdooBaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

OdooDomain = list[Any]  # verified: models/inputs.py:16

# models/envelopes.py — base imports
from pydantic import BaseModel, ConfigDict, Field    # verified: models/envelopes.py:11
from typing import Any, Optional                     # verified: models/envelopes.py:9

# models/entities.py — entity base
from pydantic import BaseModel, ConfigDict, Field    # verified: models/entities.py:15
from typing import Any, Optional, Union              # verified: models/entities.py:13
Many2one = Union[tuple[int, str], list[Any], bool, None]  # verified: models/entities.py:19

class _OdooEntity(BaseModel):                        # verified: models/entities.py:22
    model_config = ConfigDict(extra="allow", populate_by_name=True)  # line 25
    id: Optional[int]                                # line 27
    display_name: Optional[str]                      # line 28
```

### Existing Signatures to Use
```python
# All new input schemas inherit from _OdooBaseInput (models/inputs.py:19)
# All new envelopes inherit from BaseModel (standard Pydantic)
# All new entities inherit from _OdooEntity (models/entities.py:22)
```

### Does NOT Exist
- ~~`models/inputs.py` `AggregateRecordsInput`~~ — must be created
- ~~`models/envelopes.py` `AggregateResult`~~ — must be created
- ~~`models/entities.py` `HrEmployee`~~ — must be created
- ~~`models/entities.py` `HrLeave`~~ — must be created

---

## Implementation Notes

### Pattern to Follow
```python
# Follow existing input pattern (models/inputs.py:39)
class SearchRecordsInput(_OdooBaseInput):
    model: str = Field(..., description="Odoo model technical name")
    domain: Optional[OdooDomain] = Field(default=None, description="...")
    ...

# Follow existing envelope pattern (models/envelopes.py:52)
class SearchResult(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    ...

# Follow existing entity pattern (models/entities.py:34)
class ResPartner(_OdooEntity):
    name: Optional[str] = None
    ...
```

### Key Constraints
- All input schemas use `_OdooBaseInput` (extra="forbid")
- All entity models use `_OdooEntity` (extra="allow")
- Result envelopes use plain `BaseModel`
- All fields use `Optional[...]` with sensible defaults
- Include `Field(description=...)` on critical fields for LLM schema generation
- Update `__all__` in each file

### Model Definitions

See spec §2 "Data Models" for the complete field definitions of each model.
Key types to remember:
- `OdooDomain = list[Any]` for domain filter parameters
- `Many2one = Union[tuple[int, str], list[Any], bool, None]` for Odoo relational fields
- Use `dict[str, Any]` for open-ended structured data (e.g., `user_context`)

---

## Acceptance Criteria

- [ ] All 13 input schemas importable from `parrot_tools.odoo.models.inputs`
- [ ] All 12 result envelopes importable from `parrot_tools.odoo.models.envelopes`
- [ ] `HrEmployee` and `HrLeave` importable from `parrot_tools.odoo.models.entities`
- [ ] All models instantiate correctly with sample data
- [ ] `__all__` exports updated in all three files
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/models/`

---

## Test Specification

```python
# Quick smoke test — full tests come in TASK-1021 / TASK-1027
from parrot_tools.odoo.models.inputs import (
    AggregateRecordsInput, BuildDomainInput, DiagnoseOdooCallInput,
)
from parrot_tools.odoo.models.envelopes import (
    AggregateResult, DomainBuildResult, OdooCallDiagnosisResult,
)
from parrot_tools.odoo.models.entities import HrEmployee, HrLeave


def test_input_schema_instantiation():
    inp = AggregateRecordsInput(model="sale.order", group_by=["state"])
    assert inp.model == "sale.order"

def test_envelope_instantiation():
    res = AggregateResult(groups=[], model="sale.order", group_by=["state"], measures=[], count=0)
    assert res.count == 0

def test_hr_employee_entity():
    emp = HrEmployee(id=1, name="Alice", display_name="Alice")
    assert emp.name == "Alice"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md` §2 "Data Models"
2. **Check dependencies** — none; this is the first task
3. **Verify the Codebase Contract** — confirm `_OdooBaseInput`, `_OdooEntity`, etc. still exist
4. **Update status** in per-spec index → `"in-progress"`
5. **Implement** all models as described in spec
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
