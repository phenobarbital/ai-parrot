# TASK-1882: Section descriptor contract + fail-fast validation gate

**Feature**: FEAT-326 — DataAgent Infographic — Infographic Authoring for Data Agents
**Spec**: `sdd/specs/dataagent-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-326. The `SectionDescriptor` is the shared spine of the whole feature: it
declares which data fills each section of an infographic template (hero cards ← revenue
projection + variance + EBITDA, …) and is consumed by the data-splice render mode (TASK-1883),
the authoring mixin (TASK-1884), and recipe publication (TASK-1885). Validation is
**machine-enforced and fail-fast** (spec G-3): rendering must never start with unmet
datasets/columns, and the error must enumerate every deficit (philosophy of FEAT-324's `$bind`
cross-check).

---

## Scope

- Implement `parrot/tools/infographic_sections.py` with Pydantic models (`extra="forbid"`):
  `SectionSpec`, `SectionDescriptor`, `ProvenanceDescriptor`, `TransformerGap`, `GapReport`
  — shapes per spec §2 Data Models.
- Implement the validation gate: check every section's required dataset aliases and columns
  against `DatasetManager.get_dataset_entry()`, and an assembled payload dict against each
  section's declared `shape` (`records | scalar | mapping | table`). Aggregate ALL deficits
  into ONE structured error (do not stop at the first).
- `ProvenanceDescriptor` must record datasets/params/section mapping and snapshot timestamps —
  and MUST NOT have any field for python source code (resolved brainstorm decision).
- Export the new names from the appropriate `parrot/tools/` namespace.
- Write unit tests.

**NOT in scope**: rendering (TASK-1883), mixin/tool wiring (TASK-1884), recipe mapping
(TASK-1885), transformers (TASK-1887).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_sections.py` | CREATE | Models + validation gate |
| `packages/ai-parrot/src/parrot/tools/__init__.py` | MODIFY | Export new public names (follow existing export style) |
| `packages/ai-parrot/tests/unit/tools/test_infographic_sections.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# DatasetManager lives in a sub-package, class at tool.py:501:
from parrot.tools.dataset_manager.tool import DatasetManager  # verify the public re-export in
# parrot/tools/dataset_manager/__init__.py before importing; prefer the package export if one exists.
from parrot.tools.infographic_toolkit import InfographicValidationError  # infographic_toolkit.py:93
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                                   # line 501
    def get_dataset_entry(self, name: str) -> Optional[DatasetEntry]:    # line 2250

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicValidationError(Exception):                             # line 93
    def __init__(self, code: str, detail: Dict[str, Any]) -> None:       # line 114
```

### Does NOT Exist
- ~~`SectionDescriptor` / `SectionSpec` / `ProvenanceDescriptor` / `GapReport`~~ — created HERE;
  today's closest analogue is the positional block contract from
  `InfographicToolkit.get_template_contract`.
- ~~`ProvenanceDescriptor.code` / any stored python source~~ — must NOT exist by design.
- ~~`DatasetManager.validate_sections()`~~ — no such helper; the gate composes
  `get_dataset_entry` lookups itself.

---

## Implementation Notes

### Pattern to Follow
```python
# Aggregate-deficit error style — raise ONE InfographicValidationError with a
# structured detail dict listing every unmet section, e.g.:
# InfographicValidationError("sections_unmet", {"sections": [
#     {"section": "hero-cards", "missing_datasets": ["revenue"], "missing_columns": {...}},
# ]})
```

### Key Constraints
- Pydantic v2 style, `model_config = ConfigDict(extra="forbid")` on every model.
- Pure validation module: no I/O, no rendering, no LLM calls — synchronous checks are fine
  where no await is needed, but any DatasetManager access that is async must be awaited.
- Google-style docstrings + strict type hints; `self.logger`-style logging is N/A for pure
  functions — use module-level `logging.getLogger(__name__)` if logging is needed.

### References in Codebase
- `parrot/outputs/a2ui/recipes/models.py:74` — `TransformStep` model style (ConfigDict, Field docs)
- `parrot/tools/infographic_toolkit.py:93-123` — `InfographicValidationError` shape

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/tools/test_infographic_sections.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/infographic_sections.py`
- [ ] `SectionDescriptor(extra field)` raises (extra="forbid")
- [ ] Validation error enumerates EVERY deficit (dataset-level and column-level) in one raise
- [ ] `ProvenanceDescriptor` has no code/source field (assert via model_fields in a test)

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/tools/test_infographic_sections.py
import pytest
from parrot.tools.infographic_sections import (
    SectionDescriptor, SectionSpec, ProvenanceDescriptor,
)

class TestSectionDescriptor:
    def test_forbids_extra_fields(self): ...
    def test_requires_mode_literal(self): ...          # jinja | data-splice only

class TestValidationGate:
    def test_missing_dataset_listed(self): ...          # unmet alias reported
    def test_missing_columns_listed_per_alias(self): ...
    def test_all_deficits_aggregated_in_one_error(self): ...
    def test_payload_shape_mismatch(self): ...          # shape="records" vs scalar payload

class TestProvenance:
    def test_provenance_has_no_code_field(self):
        assert not any("code" in f or "source" in f
                       for f in ProvenanceDescriptor.model_fields)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** before writing ANY code (grep/read each anchor)
4. **Update status** in `sdd/tasks/index/dataagent-infographic.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1882-section-descriptor-contract.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
