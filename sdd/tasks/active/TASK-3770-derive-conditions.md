# TASK-3770: derive_conditions + conditions fixtures

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3769
**Assigned-to**: unassigned

---

## Context

`SourceRequest` is the canonical condition representation (spec S5); `LinkedDataSource.conditions`
is a **derived cache** of it — the exact payload a renderer POSTs to QuerySource. Every executor
(Python here, the bundled UI's `conditions.ts` in TASK-3793, third-party renderers) re-implements the
same derivation from shared JSON fixtures. This task writes the pure Python reference
`derive_conditions`, a helper to read a source's locked values, and the fixture files under the
installable contract directory (spec §3 Module 1, §7 "derive_conditions rules", S5, S7).

---

## Scope

- Create `linked/conditions.py` with `derive_conditions(request, *, locked)` and
  `locked_values(source)`.
- Create four fixtures under `linked/contract/fixtures/conditions/` with shape
  `{"request": {...}, "locked": {...}, "expected": {...}}`.
- Create `test_derive_conditions.py` parametrised over every `*.json` in that directory,
  asserting value equality AND key order.

**NOT in scope**: the toolkit parity test `test_toolkit_build_conditions_matches_derive` (TASK-3785);
the M3 mismatch check (TASK-3777); `querylimit` computation (the executor, TASK-3780).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/conditions.py` | CREATE | `derive_conditions`, `locked_values` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/placeholders_only.json` | CREATE | fixture |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/locked_override.json` | CREATE | fixture |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/filter_and_fields.json` | CREATE | fixture |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/limit_offset.json` | CREATE | fixture |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_derive_conditions.py` | CREATE | golden tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest   # created by TASK-3769
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py:165-192 — THE dialect the derivation mirrors
def build_conditions(*, placeholders, filter, fields, ordering, grouping, limit, offset, refresh, max_rows, forced) -> dict:
    payload = dict(placeholders or {})                       # placeholders first, request order
    if filter: payload["filter"] = dict(filter)              # filter NESTED under the "filter" key (not spread)
    for key, val in (("fields", fields), ("ordering", ordering), ("grouping", grouping)):
        if val: payload[key] = list(val)
    payload["querylimit"] = min(limit or max_rows, max_rows) # limit → querylimit (a LANE-TIME key)
    if offset: payload["_offset"] = int(offset)              # offset → "_offset", only when truthy
    if refresh: payload["refresh"] = True
    if forced: payload = {**payload, **forced}               # forced wins
    return payload
```
(Reference only — core MUST NOT import `parrot_tools`; re-implement the rules.)

### Does NOT Exist
- ~~`parrot.outputs.a2ui.linked.conditions`~~ — this task creates it.
- ~~a `limit` or `querylimit` key emitted by `derive_conditions`~~ — see decision below.
- ~~`linked/contract/`~~ — this task creates the `fixtures/conditions/` subtree (TASK-3771 adds `schema.json`, TASK-3773/TASK-3774 `fixtures/dsl/`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/conditions.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/placeholders_only.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/locked_override.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/filter_and_fields.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/limit_offset.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_derive_conditions.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py#build_conditions"
  ]
}
```

---

## Implementation Notes

### Binding derivation rules (reconciled with the real `build_conditions`)
1. Start with `request.placeholders` in request (insertion) order; a `locked` value overrides a
   same-named key **in place**; locked keys absent from placeholders are appended right after the
   placeholders, in `locked` mapping order.
2. `"filter": dict(request.filter)` — only when non-empty (nested, as `build_conditions` does).
3. `"fields"`, `"ordering"`, `"grouping"` — each only when non-empty, in that order, as lists.
4. `"_offset": int(request.offset)` — only when `request.offset` is truthy (0/None emit nothing).
5. **`request.limit` is NOT emitted.** `build_conditions` maps `limit` into `querylimit`, which
   spec §7 declares lane-time and forbids `derive_conditions` to emit; the parity pin
   `build_conditions(...) − {querylimit, refresh} == derive_conditions(...)` therefore requires
   dropping it. Lanes compute `querylimit = min(request.limit or max_fetch_rows, max_fetch_rows)`
   (TASK-3780 Python executor, TASK-3794 renderer). Record this as a spec clarification in the Completion Note.
6. Never emit `refresh` or `querylimit`. Never mutate the input request.
- Equality is value equality; **key order is also contractual** (fixture JSON order = expected order)
  so TS and Python produce byte-identical `JSON.stringify` / `json.dumps` output.
- `locked_values(source)` = `{k: source.conditions[k] for k in source.locked if k in source.conditions}` —
  the locked values live in the descriptor's `conditions` (they came from the toolkit's
  `forced_conditions`). TASK-3777 (surface validation) and TASK-3780 (executor) call it.

### Key Constraints
- Pure, deterministic, no I/O, no pandas, stdlib only.
- Fixture files: `json.dumps(obj, indent=2)` + trailing newline, UTF-8; keys in contractual order (do NOT sort_keys the `expected` object).

---

## Implementation Blueprint

### Steps (in order)
1. Write `conditions.py` — *why*: single reference implementation of S5.
2. Write the four fixtures with the exact content below — *why*: they are the cross-language contract; the first fixture fixes key names (spec §7).
3. Write the parametrised test; run it.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/conditions.py` (CREATE)
```python
"""Canonical ``SourceRequest`` → QuerySource ``conditions`` derivation (FEAT-598 S5, spec §7).

Every executor re-implements these rules from ``contract/fixtures/conditions/*.json``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest

#: Keys a lane adds at fetch time; derive_conditions never emits them.
LANE_TIME_KEYS: frozenset[str] = frozenset({"querylimit", "refresh"})


def derive_conditions(request: SourceRequest, *, locked: Mapping[str, Any]) -> dict[str, Any]:
    """Return the deterministic QuerySource payload for ``request`` with ``locked`` values applied.

    Args:
        request: The structured, editable request.
        locked: Locked parameter values; they win over same-named placeholders.

    Returns:
        A new dict; key order is part of the contract.
    """
    payload: dict[str, Any] = {}
    # FILL IN: rules 1-4 of the task's "Binding derivation rules" in that exact order — bounded by S5 / §7
    return payload


def locked_values(source: LinkedDataSource) -> dict[str, Any]:
    """Return ``{name: value}`` for every locked name present in ``source.conditions``."""
    return {name: source.conditions[name] for name in source.locked if name in source.conditions}
```

### `.../contract/fixtures/conditions/placeholders_only.json` (CREATE)
```json
{
  "request": {"placeholders": {"firstdate": "YESTERDAY", "lastdate": "TODAY"}},
  "locked": {},
  "expected": {"firstdate": "YESTERDAY", "lastdate": "TODAY"}
}
```

### `.../contract/fixtures/conditions/locked_override.json` (CREATE)
```json
{
  "request": {"placeholders": {"program": "pokemon", "firstdate": "FDOM"}},
  "locked": {"program": "epson", "store_id": 42},
  "expected": {"program": "epson", "firstdate": "FDOM", "store_id": 42}
}
```

### `.../contract/fixtures/conditions/filter_and_fields.json` (CREATE)
```json
{
  "request": {
    "placeholders": {"firstdate": "CURRENT_MONTH"},
    "filter": {"region": ["East", "West"], "visits": [">=", 10]},
    "fields": ["day", "visits"],
    "ordering": ["day"],
    "grouping": []
  },
  "locked": {},
  "expected": {
    "firstdate": "CURRENT_MONTH",
    "filter": {"region": ["East", "West"], "visits": [">=", 10]},
    "fields": ["day", "visits"],
    "ordering": ["day"]
  }
}
```

### `.../contract/fixtures/conditions/limit_offset.json` (CREATE)
```json
{
  "request": {"placeholders": {}, "limit": 100, "offset": 20, "grouping": ["program"]},
  "locked": {},
  "expected": {"grouping": ["program"], "_offset": 20}
}
```
**Why**: `limit` is absent from `expected` by rule 5; `offset: 0` would also be absent (rule 4). Add a fifth
fixture only if you find a case the four do not cover — never change these.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_derive_conditions.py` (CREATE)
```python
"""Golden tests for derive_conditions (FEAT-598 S5)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import parrot.outputs.a2ui.linked as linked
from parrot.outputs.a2ui.linked.conditions import LANE_TIME_KEYS, derive_conditions, locked_values
from parrot.outputs.a2ui.linked.models import SourceRequest

FIXTURES = Path(linked.__file__).parent / "contract" / "fixtures" / "conditions"
CASES = sorted(FIXTURES.glob("*.json"))


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_derive_conditions_golden(path: Path) -> None:
    case = json.loads(path.read_text(encoding="utf-8"))
    got = derive_conditions(SourceRequest.model_validate(case["request"]), locked=case["locked"])
    assert got == case["expected"]
    assert list(got) == list(case["expected"])   # key order is contractual


def test_fixture_dir_not_empty() -> None:
    assert len(CASES) >= 4
```
(FILL IN the extra tests listed in Test Specification.)

### FILL IN checklist
- [ ] `derive_conditions` body — rules 1-4; bounded by S5 / §7 and the four fixtures
- [ ] extra tests (lane-time keys absent, input not mutated, `locked_values`)

---

## Acceptance Criteria

- [ ] All four fixtures pass, including key order (AC7: `derive_conditions` is deterministic).
- [ ] No output ever contains `querylimit`, `refresh` or `limit`.
- [ ] `derive_conditions` does not mutate `request` (dump before == dump after).
- [ ] `from parrot.outputs.a2ui.linked import derive_conditions` resolves through the lazy map from TASK-3769.
- [ ] `ruff check` + `black --check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_derive_conditions.py -q`

---

## Test Specification

```python
def test_derive_conditions_golden(path): ...          # parametrised over contract/fixtures/conditions/*.json
def test_fixture_dir_not_empty(): ...
def test_never_emits_lane_time_keys(): ...            # request with limit/offset → no key in LANE_TIME_KEYS | {"limit"}
def test_request_not_mutated(): ...
def test_locked_values_reads_conditions(linked_source): ...   # locked=["firstdate"] → {"firstdate": "YESTERDAY"}
def test_lazy_export(): ...                           # from parrot.outputs.a2ui.linked import derive_conditions
```

---

## Agent Instructions

1. Read spec §3 Module 1, §7 "derive_conditions rules", §9 S5.
2. Confirm TASK-3769 is in `sdd/tasks/completed/`.
3. Re-verify `dialect.py:165-192` still matches the reference block above; if the dialect changed, STOP and report.
4. Index → `in-progress`; implement; run Validation Commands (`PYTHONPATH=packages/ai-parrot/src` in a worktree).
5. Move to `sdd/tasks/completed/`, index → `done`, Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `limit` is not emitted (see rule 5); the lane computes `querylimit`.
