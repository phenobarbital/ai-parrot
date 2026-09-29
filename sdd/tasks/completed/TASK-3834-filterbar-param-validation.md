# TASK-3834: FilterBar param validation + stale E2E guard-call count

**Feature**: FEAT-611 — A2UI Linked Surfaces E2E (parallel track)
**Spec**: `sdd/specs/a2ui-linked-e2e-parallel.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 4, and also covers §9 S8 ("validate FilterBar bindings at envelope validation").

A linked surface's `FilterBar` can bind a filter to a QuerySource parameter with `filters[].param = {source, name}`. When the user picks a value, the TS lane calls `setParam(source, name, value)`. Today nothing checks the binding at validation time, so a typo in `source`, or a `name` that is undeclared or locked, only shows up at runtime as a silent no-op. The spec's "Does NOT Exist" list includes "~~FilterBar param validation~~".

The task also fixes a stale assertion in the existing server E2E test. Since `ff066c3ae` (TASK-3796 review fixes), `LinkedSurfaceService.ensure_snapshot` re-checks the guard at `service.py:127`. The publish-then-refresh flow therefore calls the guard **three** times (validate_for_persistence :117, ensure_snapshot :127, refresh :159), not two.

---

## Scope

- Add `_validate_filter_params(envelope, sources, issues)` to `catalog/__init__.py`. Call it once from `_validate_linked_sources`, after the per-source loop.
- Walk every component where `component == "FilterBar"`, and every dict entry of its `filters` list that carries a dict `param`:
  - Emit `FILTER_PARAM_UNKNOWN_SOURCE` when `param["source"]` is not a key of the parsed sources.
  - Emit `FILTER_PARAM_UNDECLARED` when `param["name"]` is not in that source's `params`, **or** is in its `locked` list.
- Define the two issue-code string constants in `catalog/__init__.py`, next to `_DATA_SOURCES_KEY`.
- Fix `test_linked_surfaces_e2e.py:356` from `* 2` to `* 3`, with a comment that cites `service.py:127`.
- Create `packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_filterbar_params.py` with four cases: unknown source, undeclared name, locked name, and a valid binding that passes.

**NOT in scope**:
- Validating lowered `ChoicePicker` nodes that carry `metadata.extensions.parrot_param`. Envelopes are validated **pre-lowering**: `build_linked_surface` (builders.py:514-571) and `LinkedSurfaceService.validate_for_persistence` (service.py:116) both call `validate_envelope` on raw `Component(component="FilterBar", filters=[...])`. Lowering only happens in renderers (`FilterBarComponent.lower`, filterbar.py; `adapters/structured.py:152`).
- FilterBars on **baked** surfaces, which have no `parrot_data_sources`. `_validate_linked_sources` returns early at `if not raw: return`, and a `param` there is inert.
- The TS `setParam` undeclared-name fix (TASK for M3), the dashboard TOOL (M8), and any change to `filterbar.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | MODIFY | Add the issue-code constants and `_validate_filter_params`; call it from `_validate_linked_sources` |
| `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py` | MODIFY | Guard-call expectation `* 2` → `* 3` (line 356) |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_filterbar_params.py` | CREATE | Unknown source / undeclared / locked / valid |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# catalog/__init__.py already has (module top, verified :27-69) — add NOTHING new at module level:
from typing import Any                                            # verified: catalog/__init__.py:33
from parrot.outputs.a2ui.models import Component, CreateSurface   # verified: catalog/__init__.py:62-69
# function-local inside _validate_linked_sources (verified :539-543) — already imported there:
from parrot.outputs.a2ui.linked.models import LinkedSources

# Test file imports (all verified, same as test_validate_linked.py:1-11 and linked/conftest.py):
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401  — registers FilterBar/Chart; verified test_validate_linked.py:7
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID, ProducerOrigin, validate_envelope  # verified test_validate_linked.py:8
from parrot.outputs.a2ui.catalog.base import CatalogValidationError   # verified test_validate_linked.py:9
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata  # verified test_validate_linked.py:10
from parrot.outputs.a2ui.linked import LinkedDataSource, ParamSpec, SourceRequest  # verified linked/conftest.py:10
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
_DATA_SOURCES_KEY = "parrot_data_sources"                                     # :502
def _validate_linked_sources(envelope: CreateSurface, *, origin: ProducerOrigin,
                             issues: list[dict[str, Any]]) -> None:            # :517-622
    # early returns: `if not raw: return` (:525-526); LLM origin → return (:527-535);
    # parse error → return (:546-555)
    sources = LinkedSources.model_validate(raw).root                           # :544  -> dict[str, LinkedDataSource]
    for key, source in sources.items():                                        # :565  (per-source loop, ends :622)
# issue dict shape used throughout (e.g. :528-534, :569-575):
#   {"code": <STR>, "path": <str|None>, "message": <str>}
def validate_envelope(envelope, *, origin=ProducerOrigin.TOOL, surface_catalog_id=None) -> None  # :625
    #   calls _validate_linked_sources(envelope, origin=origin, issues=issues) only for CreateSurface (:845-846)
    #   raises CatalogValidationError(summary, issues=issues, ...) (:848-855)

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class Component(BaseModel):  # :400 — extra="allow"; FilterBar props live in component.model_extra["filters"]
    id: str; component: str
class CreateSurface(A2UIMessageBase):  # :446 — .components: list[Component] (:468), .data_model, .metadata

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py
class LinkedDataSource:  # :192
    params: dict[str, ParamSpec]   # :203
    locked: list[str]              # :204  (model validator :219 forces locked ⊆ params)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py
# FILTERBAR_SCHEMA filters[].param = {"source": str, "name": str}, both required, additionalProperties False  (:57-66)

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py
async def validate_for_persistence(...)  # :109 → guard check :117
async def ensure_snapshot(...)           # :119 → guard check :127  (added by ff066c3ae)
async def refresh(...)                   # :152 → guard check :159
```

### Does NOT Exist
- ~~`FILTER_PARAM_UNKNOWN_SOURCE` / `FILTER_PARAM_UNDECLARED` constants anywhere~~. This task creates them. They are NOT in `catalog/base.py`: that file's codes end at `TRANSFORM_REF_UNKNOWN` (:96), and this task does not touch `base.py`.
- ~~A FilterBar Pydantic model~~. Filters are raw dicts in `component.model_extra["filters"]`.
- ~~`LinkedSources.keys()` on the local `sources`~~. The local variable is already `.root`, a plain `dict[str, LinkedDataSource]`, so use `sources` / `sources[name]` directly.
- ~~Lowered `ChoicePicker` components in the envelope at validation time~~. See NOT in scope.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_filterbar_params.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#_validate_linked_sources",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#validate_envelope",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#Component",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#CreateSurface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py#LinkedDataSource",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py#LinkedSources",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py#LinkedSurfaceService.ensure_snapshot"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Follow the issue-dict pattern already used inside `_validate_linked_sources`, e.g. `catalog/__init__.py:569-575`:
```python
issues.append({"code": DATA_SOURCE_INVALID, "path": path, "message": f"..."})
```
Use `path = f"{comp.id}.filters[{index}].param"`, so a producer's retry loop can point at the exact filter.

### Key Constraints
- Never raise from `_validate_filter_params`. It only appends issues, because `validate_envelope` aggregates every issue and raises once (:848-855).
- Skip malformed entries silently: a non-dict filter, a non-dict `param`, or a non-str `source`/`name`. The FilterBar JSON schema (`filterbar.py:57-66`) owns shape errors, and double-reporting them adds noise.
- Emit at most one issue per filter. When the source is unknown, do not also emit UNDECLARED.
- Existing fixtures must stay valid. No envelope fixture under `linked/contract/fixtures/envelopes/` contains a FilterBar (verified: `grep -rl FilterBar` finds no fixture), so `test_contract_envelopes.py` is unaffected. Run it to prove that.

### References in Codebase
- `packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_linked.py`: the `_envelope` / `_codes` helpers to copy.
- `packages/ai-parrot/tests/outputs/a2ui/test_filterbar_parrot_param.py:19-32`: the FilterBar component shape with `param`.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the two constants below `_DATA_SOURCES_KEY`. *Why*: the issue codes must be importable by tests and must stay stable wire strings.
2. Add `_validate_filter_params` directly above `def _validate_linked_sources(`. *Why*: it keeps the helper next to its only caller.
3. Call it as the last statement of `_validate_linked_sources`, after the per-source loop and at function-body indentation (4 spaces). *Why*: at that point `sources` is parsed, and the LLM, empty and parse-error cases have already returned early.
4. Change the E2E assertion to `* 3` and add the comment. *Why*: `ensure_snapshot` re-checks the guard since `ff066c3ae`.
5. Write the test file and run the Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` (MODIFY) — constants
```python
# occurrences: 1 (verified: grep -c '_DATA_SOURCES_KEY = "parrot_data_sources"' packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py)
# AFTER — insert below `_DATA_SOURCES_KEY = "parrot_data_sources"` (verified: catalog/__init__.py:502)
#: A FilterBar ``filters[].param.source`` names no key of ``parrot_data_sources`` (FEAT-611 M4).
FILTER_PARAM_UNKNOWN_SOURCE = "FILTER_PARAM_UNKNOWN_SOURCE"
#: A FilterBar ``filters[].param.name`` is not declared in that source's ``params``, or is ``locked`` (FEAT-611 M4).
FILTER_PARAM_UNDECLARED = "FILTER_PARAM_UNDECLARED"
```
**Why**: the constants are kept local to `catalog/__init__.py` and not added to `base.py`, so that this task touches one production file. Tests compare on the string value, so the location is not load-bearing.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` (MODIFY) — helper
```python
# occurrences: 1 (verified: grep -c 'def _validate_linked_sources(' packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py)
# BEFORE — insert above `def _validate_linked_sources(` (verified: catalog/__init__.py:517)
def _validate_filter_params(
    envelope: CreateSurface,
    sources: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    """Append FILTER_PARAM_UNKNOWN_SOURCE / FILTER_PARAM_UNDECLARED issues for FilterBar filters[].param.

    ``sources`` is the parsed ``LinkedSources(...).root`` mapping (key -> LinkedDataSource).
    Malformed filters/params are skipped: the FilterBar JSON schema owns shape errors.
    """
    for comp in envelope.components:
        if comp.component != "FilterBar":
            continue
        filters = (comp.model_extra or {}).get("filters") or []
        for index, flt in enumerate(filters):
            param = flt.get("param") if isinstance(flt, dict) else None
            if not isinstance(param, dict):
                continue
            source_key, name = param.get("source"), param.get("name")
            if not isinstance(source_key, str) or not isinstance(name, str):
                continue
            path = f"{comp.id}.filters[{index}].param"
            # FILL IN: when source_key not in sources -> append FILTER_PARAM_UNKNOWN_SOURCE and `continue`;
            #   else when name not in sources[source_key].params OR name in sources[source_key].locked ->
            #   append ONE FILTER_PARAM_UNDECLARED (message must say "locked" vs "undeclared") —
            #   bounded by: issue dict shape {"code","path","message"} (:569-575); one issue per filter; AC (spec §5) no raise
```
**Why**: the signature matches the spec §3 M4 skeleton `(envelope, sources, issues)`. The annotation of `sources` is `dict[str, Any]` rather than `"LinkedSources"`, because the caller's local `sources` is already `.root` (:544), a plain dict. This also keeps `linked.models` a function-local import, as :539-543 already does.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` (MODIFY) — call site
```python
# occurrences: 1 (verified: grep -c '"message": f"Transform reference {source.transform.ref.name!r} is not in the manifest.",' packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py)
# AFTER — the per-source loop's last block ends at :620-622:
#                         "message": f"Transform reference {source.transform.ref.name!r} is not in the manifest.",
#                     }
#                 )
# insert, at 4-space (function-body) indentation, BEFORE the two blank lines preceding `def validate_envelope(` (:625):
    _validate_filter_params(envelope, sources, issues)
```
**Why**: this must sit outside the `for key, source in sources.items():` loop (8-space indent), or it would run once per source and duplicate issues.

### `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'assert allow_guard.calls == [("query_slug", "public:epson_field_activity")] * 2' packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py)
# REPLACE line :356
        # validate_for_persistence (service.py:117) + ensure_snapshot re-check (service.py:127, since ff066c3ae) + refresh (service.py:159)
        assert allow_guard.calls == [("query_slug", "public:epson_field_activity")] * 3
```
**Why**: the assertion is stale, not the code. Do NOT change `fake_core_qs.executions == 2` at :350. `ensure_snapshot` returns early without executing, because the built envelope already has `snapshot_at` and rows (service.py:136-137: all sources have `snapshot_at` + list rows → `return envelope`).

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_filterbar_params.py` (CREATE)
```python
"""FEAT-611 M4 — FilterBar filters[].param validation against parrot_data_sources."""

from __future__ import annotations

import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — registers FilterBar/Chart
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID, ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata


def _envelope(linked_source, param: dict, *, locked: list[str] | None = None) -> CreateSurface:
    """Chart bound to /activity/rows + a FilterBar whose single filter carries `param`."""
    source = linked_source.model_dump(mode="json", by_alias=True)
    if locked is not None:
        source["locked"] = locked
    return CreateSurface(
        surfaceId="fb-validation",
        catalogId=DEFAULT_CATALOG_ID,
        components=[
            Component(id="root", component="Column", children=["chart", "fb"]),
            Component(id="chart", component="Chart", type="bar", x="day", y=["visits"], data={"path": "/activity/rows"}),
            Component(
                id="fb",
                component="FilterBar",
                filters=[{"column": "day", "label": "From", "options": [], "param": param}],
            ),
        ],
        dataModel={},
        metadata=SurfaceMetadata(extensions=Extensions({"parrot_data_sources": {"activity": source}})),
    )


def _codes(envelope: CreateSurface) -> list[str]:
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)
    return [issue["code"] for issue in exc_info.value.issues]


def test_validate_filterbar_param_unknown_source(linked_source) -> None:
    # FILL IN: param {"source": "missing", "name": "firstdate"} -> codes == ["FILTER_PARAM_UNKNOWN_SOURCE"] — bounded by M4 scope
    ...


def test_validate_filterbar_param_undeclared(linked_source) -> None:
    # FILL IN: param {"source": "activity", "name": "program"} (not in fixture params) -> ["FILTER_PARAM_UNDECLARED"]
    ...


def test_validate_filterbar_param_locked(linked_source) -> None:
    # FILL IN: locked=["firstdate"], param name "firstdate" -> ["FILTER_PARAM_UNDECLARED"]; keep conditions consistent
    #   (fixture conditions already hold firstdate, so derive_conditions still matches) — bounded by DATA_SOURCE_INVALID not emitted
    ...


def test_validate_filterbar_param_valid(linked_source) -> None:
    # FILL IN: param {"source": "activity", "name": "firstdate"} -> validate_envelope does NOT raise
    ...
```
**Why**: the `linked_source` fixture comes from `tests/outputs/a2ui/linked/conftest.py`. It declares params `firstdate` and `lastdate` and targets `/activity/rows`. The `Column` root keeps both the Chart binding and the FilterBar reachable. Verify at implementation time that `Column` accepts `Chart`/`FilterBar` children (no `UNALLOWED_CHILD`). If it does not, use the valid test as the canary and adjust the root, not the assertion.

### FILL IN checklist
- [ ] `catalog/__init__.py::_validate_filter_params`: the unknown-source vs undeclared/locked branches; bounded by one issue per filter and the issue dict shape.
- [ ] `test_validate_filterbar_params.py`: four bodies; each asserts the exact code list (valid → no raise).
- [ ] If the locked case unexpectedly also emits `DATA_SOURCE_INVALID` (a conditions mismatch), set `conditions` to `derive_conditions(request, locked={...})`. Do not weaken the assertion.

---

## Acceptance Criteria

- [ ] An unknown `param.source` → `FILTER_PARAM_UNKNOWN_SOURCE`. An undeclared or locked `param.name` → `FILTER_PARAM_UNDECLARED`. A valid binding passes.
- [ ] Baked surfaces and LLM-origin surfaces are unaffected (the early returns are unchanged).
- [ ] `test_linked_surface_end_to_end` passes with `* 3`.
- [ ] The existing contract-envelope suite stays green.
- [ ] `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_filterbar_params.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_filterbar_params.py -q`
- `pytest packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_contract_envelopes.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_linked.py -q`

---

## Test Specification

See the CREATE block above. There are four cases: `test_validate_filterbar_param_unknown_source`, `test_validate_filterbar_param_undeclared`, `test_validate_filterbar_param_locked`, and `test_validate_filterbar_param_valid`. The spec §4 row also lists `test_linked_surface_end_to_end` (fixed).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**, never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-linked-e2e-parallel --feature-id FEAT-611`).
2. **Read the spec** at the path listed above for full context.
3. **Check dependencies**: none.
4. **Verify the Codebase Contract**: re-run the `grep -c` anchors before editing.
5. **Update status** in `sdd/tasks/index/a2ui-linked-e2e-parallel.json` → `"in-progress"`.
6. **Implement** from the Blueprint, and complete every `# FILL IN:`.
7. **Verify** by running the Validation Commands.
8. **Commit the code**. Stage only the three files listed.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3834 a2ui-linked-e2e-parallel verified`.
10. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: SDD sub-agent (session_01CFWijXsJLATx5g6k94o1EP), sub-worktree feat-FEAT-611-sub-TASK-3834 (commit 1475dca11, merged)
**Date**: 2026-09-28
**Notes**: Added `_validate_filter_params` and the `FILTER_PARAM_UNKNOWN_SOURCE` / `FILTER_PARAM_UNDECLARED` constants in `catalog/__init__.py`. It is called once, after the per-source loop in `_validate_linked_sources`, so the baked, LLM-origin and parse-error early returns are unchanged. It emits at most one issue per filter, with path `<comp.id>.filters[i].param`; it never raises and skips malformed entries. The E2E guard-call assertion is now `* 3` (the ensure_snapshot re-check at service.py:127, since ff066c3ae). 4 new tests. `tests/outputs/a2ui/linked`: 122 passed. Server `test_linked_surfaces_e2e.py`: 4 passed. ruff is clean.

**Deviations from spec**: No behaviour deviations. `filters` values that are not a list are also skipped. The locked branch is checked before the undeclared branch so the message is clearer; both use the same code. The sub-worktree needed the main checkout's compiled Cython `.so` files temporarily symlinked in to import `parrot.utils.types`; nothing of that was committed.
