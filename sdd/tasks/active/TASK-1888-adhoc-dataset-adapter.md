# TASK-1888: AdhocDatasetAdapter — ad-hoc frames + REPL locals for the validation gate

**Feature**: FEAT-327 — Infographic Render Endpoint — Deterministic Render-as-a-Service
**Spec**: `sdd/specs/infographic-render-endpoint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-327 (resolved brainstorm decision). The FEAT-326 validation gate
(`validate_descriptor_datasets`) is duck-typed: it only needs
`dataset_manager.get_dataset_entry(name)` returning an entry with a `.columns` attribute (or
`None` when unknown). The HTTP render endpoint has ad-hoc `{name: DataFrame}` dicts, and the
in-process authoring path has DataFrames living in `PythonPandasTool` locals — this adapter
makes BOTH usable with the same gate, without duplicating validation logic.

---

## Scope

- Implement `AdhocDatasetAdapter` in
  `packages/ai-parrot/src/parrot/tools/infographic_sections.py`:
  `__init__(frames: Mapping[str, pd.DataFrame] | None = None, repl_locals: Mapping[str, Any]
  | None = None)` + `get_dataset_entry(name) -> Optional[Any]` returning an object exposing
  `.columns` (list of column names) for known DataFrames, `None` otherwise.
- REPL-locals handling: only values that ARE pandas DataFrames count as datasets; every other
  local is invisible to the adapter. NEVER execute/eval anything from the namespace.
- `frames` takes precedence over `repl_locals` on name collision (document it).
- Export the adapter alongside the existing `infographic_sections` exports
  (`parrot/tools/__init__.py` lazy-export table).
- Unit tests, including an equivalence test against the gate.

**NOT in scope**: HTTP models/decoding (TASK-1889), the render route (TASK-1890), any change
to `validate_descriptor_datasets` itself (its semantics are frozen).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_sections.py` | MODIFY | Add `AdhocDatasetAdapter` |
| `packages/ai-parrot/src/parrot/tools/__init__.py` | MODIFY | Lazy export (follow lines 245/266 style) |
| `packages/ai-parrot/tests/unit/tools/test_adhoc_dataset_adapter.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools import SectionDescriptor   # lazy export, tools/__init__.py:245,266
import pandas as pd                          # core dependency
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_sections.py
class SectionSpec(BaseModel): ...                                # line 30
class SectionDescriptor(BaseModel): ...                          # line 68
def validate_descriptor_datasets(descriptor: SectionDescriptor,
                                 dataset_manager: Any) -> None:  # line 210
    # DUCK-TYPE (verified docstring): dataset_manager.get_dataset_entry(name) -> entry with
    # `.columns` attribute, or None when the alias is unknown. Raises
    # InfographicValidationError("sections_unmet", {"sections": [...]}) aggregating ALL
    # deficits. Lazy-imports InfographicValidationError (circular-import guard).
def validate_payload_shape(...): ...                             # line 262

# packages/ai-parrot/src/parrot/tools/pythonpandas.py
class PythonPandasTool(PythonREPLTool):                          # line 25
    # self.df_locals = {}                                          line 122
    # locals_dict kwarg merged into the REPL namespace              lines 128-130
```

### Does NOT Exist
- ~~`AdhocDatasetAdapter`~~ — created HERE.
- ~~`DatasetEntry` import requirement~~ — the gate does NOT require the real `DatasetEntry`
  class; any object with `.columns` satisfies it. Do NOT import DatasetManager internals.
- ~~changes to `validate_descriptor_datasets`~~ — forbidden; the adapter conforms to IT.

---

## Implementation Notes

### Pattern to Follow
```python
# A tiny entry type is enough (dataclass or NamedTuple) — e.g.
# _AdhocEntry(columns=list(df.columns)); get_dataset_entry returns it or None.
```

### Key Constraints
- Pure, synchronous, no I/O; Google-style docstrings + strict type hints.
- The adapter is CORE code (importable by both the mixin and ai-parrot-server) — no aiohttp,
  no server imports.
- Keep `pandas` usage duck-friendly: `isinstance(v, pd.DataFrame)` filter for locals.

### References in Codebase
- `parrot/tools/infographic_sections.py:210-260` — the gate the adapter must satisfy
- `parrot/tools/__init__.py:245,266` — lazy-export convention

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/tools/test_adhoc_dataset_adapter.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/infographic_sections.py`
- [ ] Imports work: `from parrot.tools import AdhocDatasetAdapter`
- [ ] `validate_descriptor_datasets(descriptor, adapter)` behaves identically to the
  DatasetManager path (pass and deficit cases)
- [ ] Non-DataFrame REPL locals are never surfaced as datasets; nothing from the namespace is
  executed

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/tools/test_adhoc_dataset_adapter.py
class TestAdhocDatasetAdapter:
    def test_frames_dict_entry_columns(self): ...
    def test_unknown_name_returns_none(self): ...
    def test_repl_locals_only_dataframes(self): ...      # ints/functions/strings invisible
    def test_frames_precedence_over_locals(self): ...
    def test_gate_pass_and_deficit_equivalence(self): ... # vs a stub DatasetManager
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — none; 3. **Verify the Codebase Contract**;
4. **Update status** in `sdd/tasks/index/infographic-render-endpoint.json` → `"in-progress"`;
5. **Implement**; 6. **Verify criteria**; 7. **Move file to completed/**;
8. **Update index** → `"done"`; 9. **Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
