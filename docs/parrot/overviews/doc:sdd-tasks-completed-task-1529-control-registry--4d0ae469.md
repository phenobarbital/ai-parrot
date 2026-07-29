---
type: Wiki Overview
title: 'TASK-1529: Control-registry rule capability metadata + field_helpers snippets'
id: doc:sdd-tasks-completed-task-1529-control-registry-rule-metadata-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 6 (metadata/helpers slice). To author rules, a designer UI/LLM
  needs to know which
---

# TASK-1529: Control-registry rule capability metadata + field_helpers snippets

**Feature**: FEAT-234 — Form Designer — Conditional Sections (Pre/Post Dependencies)
**Spec**: `sdd/specs/formdesigner-conditional-sections.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1523, TASK-1524, TASK-1525
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (metadata/helpers slice). To author rules, a designer UI/LLM needs to know which
operators, effects, and operations each `FieldType` supports, plus ready-made schema snippets for
building rules. This task exposes that capability metadata on the control registry and adds
rule/operation snippet/builder helpers.

---

## Scope

- Extend `FieldControlMetadata` (`controls/registry.py:36`) with capability fields describing
  supported rule pieces per control — e.g. `supported_operators: list[str]`,
  `supported_effects: list[str]`, `supported_operations: list[str]` (all optional with safe
  defaults to preserve backward compatibility of existing registrations).
- Populate these in `controls/builtin.py` for built-in `FieldType`s (e.g. numeric types support
  `gt/lt/...` and arithmetic ops; text types support `eq/neq/contains`-style + string ops).
- Add snippet/builder helpers in `tools/field_helpers.py` alongside
  `get_form_field_schema_snippets` (line 256) / `list_supported_form_field_types` (line 250):
  e.g. `get_dependency_rule_snippets()` and/or builder helpers returning valid `depends_on` /
  `post_depends` JSON skeletons.
- Unit tests asserting metadata is present and snippets are structurally valid.

**NOT in scope**: `EditToolkit`/`CreateFormTool` (TASK-1528); validation logic (TASK-1526);
evaluation (TASK-1530). Keep new metadata fields OPTIONAL so existing `register_field_control`
callers keep working.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py` | MODIFY | Add optional capability fields to `FieldControlMetadata` + `register_field_control` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py` | MODIFY | Populate capabilities for built-in controls |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` | MODIFY | Rule/operation snippets/builders |
| `packages/parrot-formdesigner/tests/` | CREATE/MODIFY | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.controls import register_field_control, get_controls, iter_controls, FieldControlMetadata
from parrot_formdesigner.tools import get_form_field_schema_snippets, list_supported_form_field_types
from parrot_formdesigner.core import ConditionOperator, DependencyRule, DependencyOperation, PostDependency
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py
class FieldControlMetadata(BaseModel):              # line 36 (extra="forbid")
    type: str; label: str; description: str; category: str; icon: str    # 55-59
    snippet: dict[str, Any]; render_hint: str                            # 60-61
    supports_constraints: bool; is_container: bool = False               # 62-63
    # ADD optional capability fields here (defaults so existing registrations still validate)
def register_field_control(field_type, *, label, description, category, icon,
                           snippet, render_hint, supports_constraints, is_container=False) -> None  # 70
def get_controls() -> list[FieldControlMetadata]    # 116
def iter_controls() -> Iterator[FieldControlMetadata]   # 126

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py
def list_supported_form_field_types() -> list[str]              # 250
def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]   # 256

# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
class ConditionOperator(str, Enum)   # 129 (eq/neq/gt/lt/gte/lte/in/not_in/is_empty/is_not_empty)
```

### Does NOT Exist
- ~~`FieldControlMetadata.supported_operators / supported_effects / supported_operations`~~ — not present (this task adds them, OPTIONAL).
- ~~`get_dependency_rule_snippets`~~ — does not exist (this task creates it).
- ~~A rule evaluator~~ — TASK-1530; not referenced here.

### `extra="forbid"` warning
`FieldControlMetadata` uses `extra="forbid"`. New fields MUST be declared on the model (not passed
as extras) and given defaults, or existing `register_field_control(...)` calls in `builtin.py` will
break. Update `register_field_control`'s signature/body to thread the new optional params through.

---

## Implementation Notes

### Pattern to Follow
Mirror existing `FieldControlMetadata` fields + the `register_field_control` keyword-only style
(registry.py:70-113). For snippets, mirror `get_form_field_schema_snippets` return shape
(`dict[str, dict[str, Any]]`).

### Key Constraints
- New metadata fields OPTIONAL with safe defaults (empty list) → backward-compatible registrations.
- Snippets must be valid against the models from TASK-1523/1524/1525 (construct them in a test to prove it).

### References in Codebase
- `controls/registry.py:36-132`, `controls/builtin.py` (built-in registrations).
- `tools/field_helpers.py:250-256`.

---

## Acceptance Criteria

- [ ] `FieldControlMetadata` carries optional capability fields; existing `register_field_control` calls still validate.
- [ ] Built-in numeric controls advertise numeric operators + arithmetic ops; text controls advertise string ops.
- [ ] `get_controls()` exposes the capability metadata.
- [ ] New snippet/builder helper returns `depends_on`/`post_depends` skeletons that construct valid models.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/ -k "registry or helper or snippet" -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_formdesigner.controls import get_controls, FieldControlMetadata
from parrot_formdesigner.core import DependencyRule

class TestControlCapabilities:
    def test_metadata_has_capability_fields(self):
        ...  # each built-in control exposes supported_operators/effects/operations (possibly empty)

    def test_numeric_control_supports_arithmetic(self):
        ...

    def test_rule_snippet_constructs_valid_model(self):
        ...  # snippet dict → DependencyRule(**snippet) succeeds
```

---

## Agent Instructions

1. **Read the spec** §3 Module 6.
2. **Check dependencies** — TASK-1523/1524/1525 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — note the `extra="forbid"` warning before editing.
4. **Update index** → `"in-progress"`.
5. **Implement** capability metadata + builtin population + snippets + tests.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Added optional `supported_operators`, `supported_effects`, `supported_operations` fields to `FieldControlMetadata` with empty-list defaults (backward-compatible). Updated `register_field_control` to accept these as keyword-only optional args. Populated capability metadata for all 29 built-in `FieldType`s in `_BUILTIN_METADATA`. Updated `_seed()` to pass capability fields through. Added `get_dependency_rule_snippets()` to `tools/field_helpers.py` returning 4 valid skeleton PostDependency dicts and 1 depends_on skeleton. Exported from `tools/__init__.py`. Updated `test_metadata_dump_keys.py` contract to include the 3 new fields. 35 tests pass across all controls tests (21 new + 14 pre-existing).

**Deviations from spec**: `test_metadata_dump_keys.py` EXPECTED_KEYS updated to include the 3 new capability fields — necessary contract bump since the test guards the exact field set.
