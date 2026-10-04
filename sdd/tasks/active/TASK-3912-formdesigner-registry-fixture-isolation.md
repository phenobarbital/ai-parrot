# TASK-3912: formdesigner F2 — registry fixture isolation + controls contract drift (11 failures)

**Feature**: FEAT-618 — Merge-Tier Gate Integrity & parrot-formdesigner Baseline Repair
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3911
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6 (failure cluster **F2**, 11 of the 40). Two
problems live in the same two files.

**1. Fixture pollution — 8 failures in a file this task does not edit.**
Both autouse fixtures clear the module-global `_REGISTRY`
(`controls/registry.py:91`), re-seed it, `yield`, and then **clear it again on
teardown** — leaving it empty for every test that runs afterwards in the same
session:

```python
# test_form_controls_contract.py:33-37  and  test_form_controls_endpoint.py:19-23
    _REGISTRY.clear()
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    yield
    _REGISTRY.clear()          # ← nothing restores it
```

That teardown is the sole cause of the 8 failures in
`tests/unit/controls/test_control_registry_capabilities.py` (`KeyError: 'text'`,
`'number'`, `'select'`, `'nps'`, `'group'`, `'version'`, `Missing control for
FieldType.TEXT`, `assert 'text' in {'cap_test', 'compat_test'}`). **That file
passes 21/21 standalone and must not be edited** — if the fix is right, it goes
green on its own.

**2. Contract drift — the 3 failures these two files own.**
`form_controls_response_schema.json` forbids fields the endpoint now returns
(`Additional properties are not allowed ('supported_effects', …)`), and
`test_form_controls_payload_shape`'s `expected_keys` set has drifted the same
way.

---

## Scope

- Replace the destructive `_REGISTRY.clear()` teardown in both fixtures with a
  **snapshot/restore**, so the registry is returned to its prior contents.
- Regenerate `form_controls_response_schema.json` from the live endpoint
  response so it admits the fields the endpoint actually returns.
- Update `test_form_controls_payload_shape`'s `expected_keys` to the endpoint's
  real key set.
- Add a guard proving no fixture leaves `_REGISTRY` mutated after teardown (AC10).

**NOT in scope**: editing
`tests/unit/controls/test_control_registry_capabilities.py` — it is the
*victim*, and editing it would mask the bug rather than fix it. Also out:
`controls/builtin.py` (verified complete), the snippets gap (TASK-3911), the
`len(controls) == 32` pin (TASK-3913).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py` | MODIFY | snapshot/restore fixture; schema assertions |
| `packages/parrot-formdesigner/tests/unit/api/test_form_controls_endpoint.py` | MODIFY | snapshot/restore fixture; `expected_keys` |
| `packages/parrot-formdesigner/tests/fixtures/form_controls_response_schema.json` | MODIFY | regenerate from the live endpoint |
| `packages/parrot-formdesigner/tests/unit/controls/test_registry_isolation.py` | CREATE | AC10 guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.controls.registry import _REGISTRY     # verified: tests/integration/test_form_controls_contract.py:20
from parrot_formdesigner.controls.registry import get_controls  # verified: controls/registry.py:156
from parrot_formdesigner.core.types import FieldType            # verified: core/types.py:16  (45 members)
import jsonschema                                               # verified: tests/integration/test_form_controls_contract.py:15
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py
_REGISTRY: dict[str, FieldControlMetadata] = {}   # line 91 — module-global, keyed by FieldType value
    supported_effects: list[str] = []             # line 84 — the field the JSON schema rejects
def register_field_control(...)                   # line 94
def get_controls() -> list[FieldControlMetadata]: # line 156
def iter_controls() -> Iterator[FieldControlMetadata]:  # line 166

# packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py
SCHEMA_PATH = (... / "form_controls_response_schema.json")   # line 24-27
@pytest.fixture(autouse=True)
def _seed_builtin():                                          # line 32
    _REGISTRY.clear()                                         # line 33
    ...
    yield
    _REGISTRY.clear()                                         # line 37  ← the defect
async def test_endpoint_matches_schema(aiohttp_client):       # line 51
    schema = json.loads(SCHEMA_PATH.read_text())              # line 57
    jsonschema.validate(body, schema)                         # line 58
def test_schema_fixture_is_valid_json_schema():               # line 86

# packages/parrot-formdesigner/tests/unit/api/test_form_controls_endpoint.py
    _REGISTRY.clear()                                         # line 19
    yield
    _REGISTRY.clear()                                         # line 23  ← the defect
async def test_form_controls_payload_shape(aiohttp_client):   # line 26
    expected_keys = {                                          # line 36
        "type", "label", "description", "category", "icon",
        "snippet", "render_hint", "supports_constraints", "is_container",
    }                                                          # ← missing "supported_effects"
```

### Does NOT Exist
- ~~`registry.reset()` / `registry.snapshot()` / `registry.restore()`~~ — no such helpers; `registry.py` exposes only `register_field_control`, `get_controls`, `iter_controls` (lines 94/156/166). Snapshot with `dict(_REGISTRY)` and restore with `_REGISTRY.clear(); _REGISTRY.update(saved)`.
- ~~a `conftest.py` fixture already isolating `_REGISTRY`~~ — the two autouse fixtures named above are the only ones touching it.
- ~~rebinding `_REGISTRY` to a new dict~~ — `registry.py`'s functions close over the module global; rebinding the test's local name would not affect them. Mutate in place.
- ~~`FieldControlMetadata.effects`~~ — the attribute is `supported_effects` (`registry.py:84`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_form_controls_endpoint.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/fixtures/form_controls_response_schema.json", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/controls/test_registry_isolation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py#get_controls",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py#register_field_control"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Mutate `_REGISTRY` in place.** `get_controls()` reads the module global, so
  rebinding a local name has no effect.
- The fixtures re-seed by popping `parrot_formdesigner.controls.builtin` from
  `sys.modules` and re-importing it for its side effect. Keep that; only the
  **teardown** changes.
- Regenerate the JSON schema from a real response, not by hand-adding one
  property — `test_schema_fixture_is_valid_json_schema` (`:86`) will reject a
  malformed edit, and hand-patching is how the fixture drifted in the first place.
- `test_form_controls_payload_shape` asserts `len(body["controls"]) == len(FieldType)`
  — this is correct and must keep passing (45 == 45).
- TASK-3911 adds 11 snippets, which changes the endpoint payload. Regenerate the
  schema **after** that task lands — hence the dependency.

### References in Codebase
- `controls/registry.py:84-91` — `supported_effects` and the global `_REGISTRY`.
- `tests/unit/controls/test_control_registry_capabilities.py` — the victim file; read it, do not edit it.

---

## Implementation Blueprint

### Steps (in order)
1. Replace both teardowns with snapshot/restore — *why*: this one change fixes 8 failures in a file this task never opens.
2. Confirm `test_control_registry_capabilities.py` goes green untouched — *why*: that is the proof the root cause, not the symptom, was fixed (AC9).
3. Regenerate the schema fixture from the live endpoint — *why*: the endpoint is the contract; a hand-patched schema drifts again.
4. Update `expected_keys` from the real payload — *why*: same drift, same source of truth.
5. Add the isolation guard — *why*: AC10 must hold for every future fixture, not just these two.

### `packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '    _REGISTRY.clear()' tests/integration/test_form_controls_contract.py)
# The anchor is ambiguous — disambiguate by the surrounding context below.
# REPLACE the fixture body at tests/integration/test_form_controls_contract.py:32-37, which reads:
#     @pytest.fixture(autouse=True)
#     def _seed_builtin():
#         _REGISTRY.clear()
#         sys.modules.pop("parrot_formdesigner.controls.builtin", None)
#         importlib.import_module("parrot_formdesigner.controls.builtin")
#         yield
#         _REGISTRY.clear()

@pytest.fixture(autouse=True)
def _seed_builtin():
    """Re-seed the builtin control set, then restore whatever was there before.

    FEAT-618 TASK-3912: the previous teardown cleared the module-global
    `_REGISTRY` outright, so every test that ran later in the same session saw
    an empty registry — 8 failures in test_control_registry_capabilities.py that
    had nothing to do with this file.
    """
    saved = dict(_REGISTRY)
    _REGISTRY.clear()
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    yield
    _REGISTRY.clear()
    _REGISTRY.update(saved)
```
**Why**: `dict(_REGISTRY)` is a shallow copy of the mapping, which is all that
is needed — the `FieldControlMetadata` values are not mutated by these tests.
Clearing then `update()`-ing restores the *same* dict object, which matters
because `registry.py`'s functions close over that global.

### `packages/parrot-formdesigner/tests/unit/api/test_form_controls_endpoint.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '    _REGISTRY.clear()' tests/unit/api/test_form_controls_endpoint.py)
# FILL IN: apply the identical snapshot/restore to the autouse fixture at
# tests/unit/api/test_form_controls_endpoint.py:15-23 — bounded by AC9/AC10.
#
# FILL IN: update `expected_keys` (tests/unit/api/test_form_controls_endpoint.py:36)
# to the endpoint's real key set — add "supported_effects" and any other key the
# live payload carries. Derive it by printing one entry's keys from the actual
# response; do NOT guess — bounded by AC6 (no product change to satisfy a test).
# Leave `assert len(body["controls"]) == len(FieldType)` (line 35) untouched.
```
**Why**: the same defect in a second fixture — either one left unfixed keeps the
pollution alive, because both run in a full-package session.

### `packages/parrot-formdesigner/tests/fixtures/form_controls_response_schema.json` (MODIFY)
```text
# FILL IN: regenerate from the live endpoint response rather than hand-editing.
# Start the same aiohttp app the tests build (handle_form_controls on
# GET /api/v1/form-controls), capture the JSON body, and derive the schema from
# it — bounded by: (a) test_schema_fixture_is_valid_json_schema (line 86) must
# still pass against Draft202012Validator, and (b) test_endpoint_matches_schema
# (line 51) must validate the live body.
# Run this AFTER TASK-3911 lands — its 11 new snippets change the payload.
```
**Why**: the fixture is a snapshot of the endpoint, so it is generated, not
authored. Hand-adding `supported_effects` would fix today's error and leave the
next added field to break it again.

### `packages/parrot-formdesigner/tests/unit/controls/test_registry_isolation.py` (CREATE)
```python
"""FEAT-618 TASK-3912: no fixture may leave the global control registry mutated (AC10)."""
from __future__ import annotations

from parrot_formdesigner.controls.registry import _REGISTRY, get_controls  # verified: registry.py:91,156
from parrot_formdesigner.core.types import FieldType                        # verified: core/types.py:16


def test_registry_is_fully_seeded_at_module_scope() -> None:
    """Every FieldType has a registered control when no fixture is mid-flight."""
    # FILL IN: import parrot_formdesigner.controls.builtin for its side effect,
    # then assert {c.type for c in get_controls()} == {m.value for m in FieldType}
    # — bounded by AC10 and by the spec-time measurement (45 registered, 0 missing).
    raise NotImplementedError


def test_seed_fixture_restores_prior_contents() -> None:
    """A snapshot/restore fixture leaves `_REGISTRY` byte-identical afterwards."""
    # FILL IN: snapshot dict(_REGISTRY), run the same clear/re-import/restore
    # cycle the two autouse fixtures perform, and assert _REGISTRY equals the
    # snapshot afterwards — bounded by AC10.
    raise NotImplementedError
```
**Why this shape**: AC9 is proven by `test_control_registry_capabilities.py`
going green untouched; AC10 needs its own assertion so a *future* fixture cannot
reintroduce the same teardown. Keep this file out of `tests/unit/api/` so it does
not inherit those autouse fixtures.

### FILL IN checklist
- [ ] `test_form_controls_endpoint.py` — snapshot/restore fixture; bounded by AC9/AC10
- [ ] `test_form_controls_endpoint.py::expected_keys` — real key set; bounded by AC6
- [ ] `form_controls_response_schema.json` — regenerated; bounded by the `:51` and `:86` tests
- [ ] `test_registry_isolation.py` — both bodies; bounded by AC10

---

## Acceptance Criteria

- [ ] **AC9** `tests/unit/controls/test_control_registry_capabilities.py` scores 21/21 standalone AND in the full package run, **with that file unmodified** (`git diff --name-only` must not list it).
- [ ] **AC10** No fixture leaves `_REGISTRY` mutated after teardown; `test_registry_isolation.py` proves it.
- [ ] The 3 own failures pass: `test_endpoint_matches_schema`, `test_each_entry_has_full_metadata`, `test_form_controls_payload_shape`.
- [ ] `test_schema_fixture_is_valid_json_schema` still passes.
- [ ] `assert len(body["controls"]) == len(FieldType)` still passes (45 == 45).
- [ ] **AC6** No `src/` file modified — `git diff --name-only` shows tests and the JSON fixture only.
- [ ] **AC7** `ruff check` clean on both changed test files and the new one.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/controls/test_control_registry_capabilities.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/controls/test_registry_isolation.py -q`
- `pytest packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_form_controls_endpoint.py -q`

---

## Test Specification

The AC9 proof is a **combined** run: the capabilities file must pass when
collected together with the two fixture files in one session, which is exactly
what the pollution broke. Run them together as well as individually.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug tests-test-wheel-layout-tech-debt --feature-id FEAT-618`)
2. **Read the spec** §3 Module 6 and §2's taxonomy row **F2**.
3. **Check dependencies** — TASK-3911 must be `"done"` before regenerating the schema.
4. **Verify the Codebase Contract** — re-confirm `registry.py:84,91` and both fixture line ranges.
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** the Validation Commands, individually and combined. Prefix with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only this task's four files.
9. **Close** with `scripts/sdd/close_task.sh TASK-3912 tests-test-wheel-layout-tech-debt verified`.
10. **Fill in the Completion Note** with the new package failure count.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: Confirm test_control_registry_capabilities.py was NOT edited, and give the new failure count.

**Deviations from spec**: none | describe if any
