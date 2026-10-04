# TASK-3789: FilterBar `parrot_param` — schema extension + lowering pass-through

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10. On a linked surface a `FilterBar` filter can either filter rows **locally** (today's
behaviour, `parrot_filter_column`) or **re-fetch** a source with a changed QuerySource parameter. The
second case is declared by an optional `param: {"source": "<source key>", "name": "<param name>"}` on
the filter; lowering carries it onto the `ChoicePicker` as `metadata.extensions.parrot_param`, next to
`parrot_filter_column`. Renderers consume the **lowered** nodes (S10), so the pass-through is the whole
contract; the bundled UI's re-fetch behaviour is TASK-3795.

---

## Scope

- Add an optional `param` object (`{source: string, name: string}`, both required inside it,
  `additionalProperties: false`) to `FILTERBAR_SCHEMA.properties.filters.items.properties`.
- In `_lower_filter`, accept `param: dict[str, str] | None` and, when present, add
  `"parrot_param": {"source": …, "name": …}` to the ChoicePicker's `metadata.extensions`.
- Pass `f.get("param")` from `FilterBarComponent.lower`.
- Update `FILTERBAR_INSTRUCTIONS` with one sentence about `param`.
- New golden `filterbar_param_lowered.json` + tests. The EXISTING `golden/filterbar_lowered.json` and
  `test_components_filterbar.py` must stay byte-for-byte unchanged and green (AC11): a filter without
  `param` lowers exactly as today (no `parrot_param` key at all — not `null`).

**NOT in scope**: validating that `param.source` names a real `parrot_data_sources` key or that
`param.name` is in that source's `params` (surface-level concern — not part of TASK-3777's rule list
either; renderers ignore an unknown source). UI behaviour (TASK-3795). Docs (TASK-3796).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py` | MODIFY | schema `param`; lowering pass-through; instructions |
| `packages/ai-parrot/tests/outputs/a2ui/test_filterbar_parrot_param.py` | CREATE | param pass-through + golden + schema tests |
| `packages/ai-parrot/tests/outputs/a2ui/golden/filterbar_param_lowered.json` | CREATE | new golden (one filter with param, one without) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import get_component                      # used by test_components_filterbar.py:7
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, to_components   # filterbar.py:26; test_components_filterbar.py:8
from parrot.outputs.a2ui.catalog.parrot import filterbar                   # test_components_filterbar.py:9
from parrot.outputs.a2ui.models import Component                           # filterbar.py:27
import jsonschema                                                           # existing dependency (catalog/__init__.py:35)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py
FILTERBAR_SCHEMA: dict[str, Any] = {                     # L29 (also referenced at L107: SCHEMA = FILTERBAR_SCHEMA)
    ... "filters": {"type": "array", "items": {"type": "object", "properties": {
        "column": …, "label": …, "options": …,
        "multiple": {"type": "boolean"},                 # L54 — last property of a filter item
    }, "required": ["column", "label", "options"]}}      # L56
}
FILTERBAR_INSTRUCTIONS = ( … )                           # L63-68
def _lower_filter(*, column: str, label: str, options: list[dict[str, Any]], multiple: bool,
                  node_id: str) -> BasicNode:            # L71
    return BasicNode(id=node_id, component="ChoicePicker", label=label, options=choice_options, value=value,
                     variant=…,
                     metadata={"extensions": {"parrot_role": "filter", "parrot_filter_column": column}})  # L92-100 (metadata L99)
@register_component("FilterBar")
class FilterBarComponent:                                # L104
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:   # L110
        children = [_lower_filter(column=…, label=…, options=…, multiple=bool(f.get("multiple")),  # L119
                                  node_id=f"{component.id}-f{i}") for i, f in enumerate(filters) if isinstance(f, dict)]

# packages/ai-parrot/tests/outputs/a2ui/test_components_filterbar.py — golden convention
GOLDEN_DIR = Path(__file__).parent / "golden"            # L12
def _dump(tree) -> bytes:                                # L15-16
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"
```

### Does NOT Exist
- ~~`parrot_param` anywhere in the catalog~~ — net-new.
- ~~`ParamBar` component~~ — rejected in the brainstorm; FilterBar is extended instead.
- ~~A `metadata.extensions.parrot_param` on the FilterBar DECLARATION~~ — the declaration uses a plain
  `param` key on each filter item; `parrot_param` appears only on the LOWERED ChoicePicker (spec M10
  skeleton; §2 Integration Points' wording "filters may carry metadata.extensions.parrot_param" refers to
  the lowered form).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/test_filterbar_parrot_param.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/golden/filterbar_param_lowered.json", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py#FilterBarComponent",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py#_lower_filter",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py#FILTERBAR_SCHEMA"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- AC11: no key added when `param` is absent — build the extensions dict, then conditionally add.
- Keep `_lower_filter` keyword-only; the new parameter defaults to `None` so any other caller is unaffected.
- Do not touch `golden/filterbar_lowered.json`.

### References in Codebase
- `test_components_filterbar.py:15-42` — golden idiom (lower twice, compare byte-for-byte).

---

## Implementation Blueprint

### Steps (in order)
1. Add `param` to the filter item schema — *why*: the catalog schema is the LLM/tool-facing contract.
2. Thread `param` through `_lower_filter` and `lower` — *why*: renderers read the lowered node (S10).
3. Generate the new golden by lowering the test's component once, review it, commit — *why*: pins the
   pass-through shape.
4. Run the new test AND the existing FilterBar test — *why*: AC11.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py` (MODIFY) — schema
```python
# occurrences: 1 (verified: grep -c '"multiple": {"type": "boolean"},' packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py)
# AFTER — insert below `                    "multiple": {"type": "boolean"},` (verified: filterbar.py:54)
                    "param": {
                        "type": "object",
                        "description": (
                            "Linked surfaces only: re-fetch data source `source` with QuerySource parameter "
                            "`name` set to the selected value, instead of filtering rows locally."
                        ),
                        "properties": {"source": {"type": "string"}, "name": {"type": "string"}},
                        "required": ["source", "name"],
                        "additionalProperties": False,
                    },
```

### `…/filterbar.py` (MODIFY) — `_lower_filter`
```python
# occurrences: 1 (verified: grep -c 'def _lower_filter(' filterbar.py) — L71. Change the signature to:
def _lower_filter(
    *,
    column: str,
    label: str,
    options: list[dict[str, Any]],
    multiple: bool,
    node_id: str,
    param: dict[str, Any] | None = None,
) -> BasicNode:
# Docstring Args: add `param: Optional {"source", "name"} (FEAT-598) — lowered to parrot_param.`
# occurrences: 1 (verified: grep -c 'metadata={"extensions": {"parrot_role": "filter", "parrot_filter_column": column}},' filterbar.py)
# REPLACE that line (L99) with `metadata={"extensions": extensions},` and build, above `return BasicNode(`:
    extensions: dict[str, Any] = {"parrot_role": "filter", "parrot_filter_column": column}
    if isinstance(param, dict) and param.get("source") and param.get("name"):
        extensions["parrot_param"] = {"source": param["source"], "name": param["name"]}
```

### `…/filterbar.py` (MODIFY) — `lower`
```python
# occurrences: 1 (verified: grep -c 'multiple=bool(f.get("multiple")),' filterbar.py)
# AFTER — insert below `                multiple=bool(f.get("multiple")),` (verified: filterbar.py:119)
                param=f.get("param"),
```
Also append to `FILTERBAR_INSTRUCTIONS` (L63-68): `" On linked surfaces a filter may add `param: {source, name}` to re-fetch that data source with the selected value."`
**Why**: dict key order puts `parrot_param` after the existing two keys; the old golden is unaffected
because the key is only added when `param` is set.

### `packages/ai-parrot/tests/outputs/a2ui/test_filterbar_parrot_param.py` (CREATE)
```python
"""FilterBar parrot_param pass-through (FEAT-598 M10)."""

import json
from pathlib import Path

import jsonschema

from parrot.outputs.a2ui.catalog.base import to_components
from parrot.outputs.a2ui.catalog.parrot import filterbar
from parrot.outputs.a2ui.models import Component

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def _filterbar() -> Component:
    return Component(
        id="fb",
        component="FilterBar",
        filters=[
            {"column": "program", "label": "Program", "options": [{"label": "Epson", "value": "epson"}],
             "param": {"source": "activity", "name": "program"}},
            {"column": "store", "label": "Store", "options": []},
        ],
    )


def test_filterbar_param_passthrough() -> None: ...        # FILL IN: children[0] ext has parrot_param; children[1] has NO parrot_param key
def test_filterbar_param_golden() -> None: ...             # FILL IN: lower twice == golden/filterbar_param_lowered.json bytes
def test_filterbar_param_schema_valid() -> None: ...       # FILL IN: jsonschema.validate(props, FILTERBAR_SCHEMA) ok
def test_filterbar_param_schema_rejects_extra_key() -> None: ...  # FILL IN: param with "url" → ValidationError
def test_filterbar_param_lowered_is_v1_valid() -> None: ...  # FILL IN: to_components(tree) does not raise
```

### FILL IN checklist
- [ ] test bodies
- [ ] new golden file (generated then reviewed)

---

## Acceptance Criteria

- [ ] A filter with `param` lowers to a ChoicePicker whose extensions carry `parrot_param = {source, name}`
- [ ] A filter without `param` lowers byte-identically to today; `golden/filterbar_lowered.json` unchanged (AC11)
- [ ] `FILTERBAR_SCHEMA` accepts `param`, rejects unknown keys inside it
- [ ] `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/test_filterbar_parrot_param.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_components_filterbar.py -q`

---

## Test Specification

As above; `test_filterbar_param_passthrough` is the spec §4 row for M10.

---

## Agent Instructions

1. Read spec §3 M10.
2. No dependencies.
3. Re-run the three `grep -c` anchors; implement; fill every `# FILL IN:`.
4. Run the Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src`).
5. Commit only the listed files; update the index; fill the Completion Note.

---

## Completion Note


- Task: TASK-3789
- Feature: a2ui-linked-surfaces
- Implementation SHA: e632de4a296c1bc6fcdb1575703213128bf5946a
- Closed at (UTC): 2026-09-26T02:19:02+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| coder_record_review | NOT recorded - coder_record_review MCP tool rejects every payload including {} (systemic tool outage, confirmed also on coder_record_feedback and coder_record_native_observation) |
| merge_validation_outcome | failed: same systemic pre-existing failures already characterized (parrot-formdesigner version/schema drift, ai-parrot-embeddings wheel-layout conftest collision), unrelated to this task's diff. Task's own scoped tests: 14 passed (filterbar parrot_param + pre-existing filterbar suite). See issue:181bd0c01bb4. |
| seat_summary | Seat: sonnet - Backend: native - Model: sonnet - Attempts: 1 - Duration: n/a - Tokens: n/a |
