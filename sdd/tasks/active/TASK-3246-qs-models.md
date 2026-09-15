# TASK-3246: Pydantic input/output models for QuerysourceToolkit

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Data Models" and §3 Module 2. All tool results are Pydantic v2 models dumped by `_post_execute`
(spec §3 M5), so the LLM receives JSON-safe dicts. The field names are fixed by the spec (`returned_rows`,
`total_rows`, `truncated`, … — design research S8) and are referenced by later tasks and tests verbatim.

---

## Scope

- Implement `models.py` with exactly the models in spec §2 Data Models: `FilterScalar`/`FilterValue` aliases,
  `SlugSummary`, `PlaceholderInfo`, `SlugDetail`, `ExecutionResult`, `MultiQueryResult`, `PipelineIssue`,
  `PipelineValidation`, `ComponentAttribute`, `ComponentDoc`, `SavedSlug`, `DialectReference`.
- Write unit tests (construction, defaults, `model_dump()` JSON-serialisable).

**NOT in scope**: any logic that fills these models (TASK-3247+), exports in `__init__.py` (TASK-3251).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/models.py` | CREATE | Pydantic models |
| `packages/ai-parrot-tools/tests/querysource/test_models.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field   # pydantic v2 (workspace dependency; used by parrot/tools/abstract.py:250 ToolResult)
```

### Existing Signatures to Use
```python
# parity target — querysource/queries/multi/registry.py:24-43 (installed 4.5.11)
@dataclass class AttributeInfo: name: str; type: str; default: Any = None; required: bool = False; description: str = ""
@dataclass class ComponentInfo: name: str; category: str; description: str; usage: str; attributes: list[AttributeInfo]; json_schema: dict | None; example: str = ""; icon: str = ""
```

### Does NOT Exist
- ~~`parrot_tools.querysource.models.QueryResult`~~ — the name is `ExecutionResult` (do not reuse `parrot.tools.databasequery` names).
- ~~`ExecutionResult.row_count`~~ — fields are `returned_rows` / `total_rows` (S8).
- ~~`ToolResult` subclassing~~ — tool methods return these models; `AbstractTool.execute` wraps them.

---

## Implementation Notes

### Key Constraints
- Pydantic v2 only (`model_dump`, `Field(default_factory=…)`); no `Config` class — use `model_config = ConfigDict(extra="forbid")` only if you need it (not required).
- Keep field order and names exactly as the spec; `SlugDetail` MUST NOT declare `source`, `params`, `attributes`, `dwh_info`, `dwh_scheduler`, `cache_options` (S10 redaction is enforced by omission).
- `FilterValue` is a type alias used by `execute_slug`'s signature (TASK-3252) — export it.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py:115-200` — sibling toolkit returning Pydantic models.

---

## Implementation Blueprint

### Steps (in order)
1. Write `models.py` from the block — *why*: the spec's Data Models section is authoritative; nothing to design.
2. Write tests asserting defaults and `json.dumps(model.model_dump())` works.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/models.py` (CREATE)
```python
"""Pydantic models for QuerysourceToolkit inputs and outputs (spec §2 Data Models)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

FilterScalar = str | int | float | bool | None
FilterValue = FilterScalar | list[FilterScalar] | dict[str, FilterScalar]  # scalar | IN list | {op: v} | [op, v]


class SlugSummary(BaseModel):
    """One row of public.queries as shown by qs_list_slugs."""
    slug: str
    description: str | None = None
    program_slug: str
    provider: str
    is_multiquery: bool
    placeholders: list[str] = Field(default_factory=list)  # keys of cond_definition ∪ stored conditions


class PlaceholderInfo(BaseModel):
    """A declared placeholder: name, cond_definition type, stored default."""
    name: str
    type: str | None = None
    default: Any = None


class SlugDetail(SlugSummary):
    """Full, redacted description of a slug (never source/params/attributes/dwh_*/cache_options)."""
    placeholders_detail: list[PlaceholderInfo] = Field(default_factory=list)
    filtering: dict[str, Any] = Field(default_factory=dict)
    fields: list[str] = Field(default_factory=list)
    ordering: list[str] = Field(default_factory=list)
    grouping: list[str] = Field(default_factory=list)
    is_cached: bool
    cache_timeout: int
    sql: str | None = None                  # query_raw when include_sql=True and not multiquery
    pipeline: dict[str, Any] | None = None  # parsed query_raw when is_multiquery
    rendered_query: str | None = None       # QS.dry_run() output when dry_run=True


class ExecutionResult(BaseModel):
    """Bounded, JSON-safe result of a slug execution (S8 naming)."""
    status: Literal["success", "empty"]
    slug: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    returned_rows: int
    total_rows: int | None = None
    truncated: bool = False
    columns: list[str] = Field(default_factory=list)
    applied_conditions: dict[str, Any] = Field(default_factory=dict)
    rejected_inputs: list[str] = Field(default_factory=list)
    duration_ms: int


class MultiQueryResult(BaseModel):
    """Result of a MultiQuery run: one ExecutionResult per returned frame ('result' when single)."""
    status: Literal["success", "empty"]
    results: dict[str, ExecutionResult]
    duration_ms: int


class PipelineIssue(BaseModel):
    """One validation problem (mirrors querysource ValidationError(step, field, message))."""
    step: str
    field: str
    message: str


class PipelineValidation(BaseModel):
    """Outcome of qs_validate_pipeline (structural rules + toolkit policy)."""
    valid: bool
    issues: list[PipelineIssue] = Field(default_factory=list)
    referenced_slugs: list[str] = Field(default_factory=list)
    has_raw_nodes: bool = False
    has_external_sources: bool = False
    destination_steps: list[str] = Field(default_factory=list)
```
(continued in the next block — same file)
```python
class ComponentAttribute(BaseModel):
    """Mirror of querysource AttributeInfo (registry.py:24)."""
    name: str
    type: str
    default: Any = None
    required: bool = False
    description: str = ""


class ComponentDoc(BaseModel):
    """Mirror of querysource ComponentInfo (registry.py:34) — the /api/v3/qs/components payload."""
    name: str
    category: str
    description: str
    usage: str
    attributes: list[ComponentAttribute] = Field(default_factory=list)
    json_schema: dict[str, Any] | None = None
    example: str = ""
    icon: str = ""


class SavedSlug(BaseModel):
    """Outcome of qs_save_multiquery."""
    slug: str
    program_slug: str
    action: Literal["inserted", "updated"]


class DialectReference(BaseModel):
    """The QuerySource conditions dialect as shown to the LLM (spec §3 M3)."""
    verified_against: str
    option_keys: dict[str, str]
    placeholder_rules: list[str]
    where_grammar: list[str]
    operators_list_form: list[str]
    operators_dict_form: list[str]
    examples: list[dict[str, Any]]
    variables: dict[str, str] = Field(default_factory=dict)  # '@name' → one-line doc (§8 Q2)
    notes: list[str]
```
**Why this shape**: verbatim spec §2; `SlugDetail` extends `SlugSummary` so `list_slugs` and `describe_slug`
share the summary fields. Nothing here is negotiable — TASK-3247..3254 import these names.

### FILL IN checklist
- [ ] none — mechanical; tests need bodies.

---

## Acceptance Criteria

- [ ] All twelve names import from `parrot_tools.querysource.models`.
- [ ] `SlugDetail.model_fields` contains none of `source`, `params`, `attributes`, `dwh_info`, `dwh_scheduler`, `cache_options`.
- [ ] `json.dumps(ExecutionResult(status="empty", returned_rows=0, duration_ms=1).model_dump())` succeeds.
- [ ] `pytest packages/ai-parrot-tools/tests/querysource/test_models.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/test_models.py
import json
from parrot_tools.querysource import models as m


def test_slug_detail_redaction_by_omission():
    forbidden = {"source", "params", "attributes", "dwh_info", "dwh_scheduler", "cache_options"}
    assert forbidden.isdisjoint(m.SlugDetail.model_fields)


def test_execution_result_defaults_and_json():
    r = m.ExecutionResult(status="empty", returned_rows=0, duration_ms=3)
    assert r.rows == [] and r.truncated is False and r.total_rows is None
    json.dumps(r.model_dump())


def test_component_doc_matches_registry_shape():
    doc = m.ComponentDoc(name="Concat", category="Operators", description="d", usage="u",
                         json_schema={"type": "object"}, example="{\"Concat\": {}}", icon="git-merge")
    assert set(doc.model_dump()) == {"name", "category", "description", "usage", "attributes", "json_schema", "example", "icon"}


def test_dialect_reference_variables_default():
    ref = m.DialectReference(verified_against="4.5.11", option_keys={}, placeholder_rules=[], where_grammar=[],
                             operators_list_form=[], operators_dict_form=[], examples=[], notes=[])
    assert ref.variables == {}
```

---

## Agent Instructions

1. Read spec §2 Data Models and §3 Module 2.
2. Update index → `in-progress`; write the file verbatim; write tests; run `pytest` + `ruff`.
3. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
