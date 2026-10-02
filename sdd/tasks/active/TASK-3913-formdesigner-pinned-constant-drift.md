# TASK-3913: formdesigner F4 — pinned-constant drift (7 failures)

**Feature**: FEAT-618 — Merge-Tier Gate Integrity & parrot-formdesigner Baseline Repair
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3911
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5 (failure cluster **F4**, 7 of the 40). Seven tests
assert hardcoded literals the product has legitimately grown past. Each one is a
test that froze a number instead of deriving it, so each new field type or tool
re-breaks them:

| File:line | Asserts | Actual |
|---|---|---|
| `tests/unit/test_version_and_docs.py:11` | `v.__version__ == "0.9.0"` | `1.0.6` |
| `tests/unit/test_init_imports_metadata_only.py:93` | `pkg.__version__ == "0.3.0"` | `1.0.6` |
| `tests/unit/test_core_models.py:246` | `len(FieldType) == 32` | `45` |
| `tests/unit/test_controls_registry.py:180` | `len(controls) == 32` | `45` |
| `tests/test_edit_toolkit.py:608` | `len(tools) == 15` | `22` |
| `tests/test_edit_toolkit.py` (`test_tool_definitions_has_required_names`) | a frozen name set | drifted |
| `tests/integration/test_msteams_import_compat.py:50` | `len(lines) < 50` | `60` |

**The fix is never to re-pin a fresh literal.** Replacing `32` with `45` buys
one release. Each assertion must derive from the source of truth, or be
reframed so it tests the invariant it actually cares about.

---

## Scope

- Rewrite all 7 assertions to derive from the source of truth
  (`importlib.metadata.version`, `len(FieldType)`, the registry itself, the
  toolkit's own definition list) or to assert the real invariant.
- Where a test's intent is "this thing stays small" (the 50-line budget), decide
  and document whether the budget moves or the example file shrinks.
- Update each test's docstring — several state counts that are now wrong and
  would mislead the next reader.

**NOT in scope**: changing any `src/` file except where the 50-line budget
decision requires editing `examples/forms/form_server.py`; the snippets gap
(TASK-3911); the registry fixtures (TASK-3912); the tenant double (TASK-3910).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/test_version_and_docs.py` | MODIFY | derive the version |
| `packages/parrot-formdesigner/tests/unit/test_init_imports_metadata_only.py` | MODIFY | derive the version |
| `packages/parrot-formdesigner/tests/unit/test_core_models.py` | MODIFY | derive the `FieldType` count |
| `packages/parrot-formdesigner/tests/unit/test_controls_registry.py` | MODIFY | derive the control count |
| `packages/parrot-formdesigner/tests/test_edit_toolkit.py` | MODIFY | derive the tool count + name set |
| `packages/parrot-formdesigner/tests/integration/test_msteams_import_compat.py` | MODIFY | resolve the line budget |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import parrot_formdesigner.version as v                     # verified: tests/unit/test_version_and_docs.py:5
from parrot_formdesigner.core.types import FieldType        # verified: core/types.py:16  (45 members)
from parrot_formdesigner.controls.registry import get_controls  # verified: controls/registry.py:156
from importlib.metadata import version as dist_version      # stdlib — distribution name is "parrot-formdesigner"
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/version.py
__version__ = "1.0.6"                                       # line 5 — the source of truth

# packages/parrot-formdesigner/pyproject.toml
dynamic = ["version"]                                       # line 10
version = {attr = "parrot_formdesigner.version.__version__"}  # line 80
#   → importlib.metadata.version("parrot-formdesigner") and version.__version__
#     are the SAME value by construction; that is the invariant worth asserting.

# the 7 failing assertions, verbatim:
# tests/unit/test_version_and_docs.py:11        assert v.__version__ == "0.9.0"
# tests/unit/test_init_imports_metadata_only.py:93   assert pkg.__version__ == "0.3.0"
# tests/unit/test_core_models.py:246            assert len(FieldType) == 32
# tests/unit/test_controls_registry.py:180      assert len(controls) == 32, f"Expected 32 controls, got {len(controls)}"
# tests/test_edit_toolkit.py:608                assert len(tools) == 15
# tests/integration/test_msteams_import_compat.py:50
#     assert len(lines) < 50, f"form_server.py has {len(lines)} non-empty lines, expected < 50"

# tests/unit/test_controls_registry.py:175-187 also spot-checks membership:
#     assert "signature" in control_types ; "nps" ; "likert" ; "ranking"
#   — those spot-checks are GOOD and must be preserved; only the count pin moves.
```

### Does NOT Exist
- ~~`parrot_formdesigner.__version__` differing from `version.__version__`~~ — `pyproject.toml:80` derives the distribution version from that attribute, so they cannot diverge.
- ~~a `FieldType.__total__` / `FieldType.count()`~~ — use `len(FieldType)`.
- ~~`EditToolkit.TOOL_COUNT` / a declared tool-count constant~~ — the count comes from `get_tool_definitions()` only.
- ~~`examples/forms/form_server.py` being generated~~ — it is a hand-written example file; shrinking it is a real edit, not a regeneration.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/tests/unit/test_version_and_docs.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_init_imports_metadata_only.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_core_models.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_controls_registry.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/test_edit_toolkit.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/integration/test_msteams_import_compat.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py#FieldType",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py#get_controls"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **AC8 is enforced by grep**: the diff must introduce no new numeric or version
  equality literal. If an assertion genuinely needs a bound, it must be a
  derived bound, not a typed-in one.
- Keep every *membership* spot-check. `test_controls_registry.py:184-187`
  asserts `"signature"`, `"nps"`, `"likert"`, `"ranking"` are present — those
  carry real meaning and must survive; only `assert len(controls) == 32` moves.
- A version test should assert the **invariant** (`version.__version__ ==
  importlib.metadata.version("parrot-formdesigner")`, and that it parses as
  PEP 440), not a specific release.
- The `len(FieldType) == 32` and `len(controls) == 32` pins become one
  relationship: the registry registers exactly one control per `FieldType`.
  That is the property the original test was reaching for.
- TASK-3911 adds 11 snippets; the counts only settle after it lands — hence the
  dependency.
- Fix the docstrings too (`test_core_models.py:245`,
  `test_controls_registry.py:176`, `test_edit_toolkit.py:605` all assert a
  specific breakdown in prose).

### The 50-line budget (`test_msteams_import_compat.py:50`)
This one is a judgement call, not a derivation. `examples/forms/form_server.py`
is 60 non-empty lines against a `< 50` acceptance criterion from an earlier
spec. Decide ONE of:
  - the example grew legitimately → raise the budget and say why in the docstring; or
  - the example accreted → shrink it back under the budget.
Record the choice and the reason in the Completion Note. Do not delete the test.

---

## Implementation Blueprint

### Steps (in order)
1. Re-measure every current value — *why*: the table above was measured at spec time and TASK-3911 moves some of it.
2. Rewrite the two version assertions as the metadata invariant — *why*: a release bump must never turn the suite red again.
3. Replace both `== 32` pins with the one-control-per-FieldType relationship — *why*: that is the invariant the counts were standing in for.
4. Derive the toolkit count and name set from the toolkit — *why*: same reason; adding a tool should not need a test edit.
5. Decide the 50-line budget and record the reason — *why*: it is the only item here that is a real product judgement.
6. Update each stale docstring — *why*: the prose counts are as misleading as the assertions were.

### `packages/parrot-formdesigner/tests/unit/test_version_and_docs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert v.__version__ == "0.9.0"' tests/unit/test_version_and_docs.py)
# REPLACE `    assert v.__version__ == "0.9.0"` (verified: tests/unit/test_version_and_docs.py:11)
def test_version_bumped():
    """The module version is the distribution version and is a valid PEP 440 release."""
    # FILL IN: assert v.__version__ == importlib.metadata.version("parrot-formdesigner")
    # and that it parses as PEP 440 — bounded by AC8 (no new literal) and by
    # pyproject.toml:80, which derives the distribution version from this attribute.
    raise NotImplementedError
```
**Why**: `pyproject.toml:80` makes these two values the same by construction, so
asserting their equality is a real (and permanently true) invariant, while
asserting `"0.9.0"` was only ever true for one release. Rename nothing — other
tooling may reference the test id.

### `packages/parrot-formdesigner/tests/unit/test_core_models.py` + `tests/unit/test_controls_registry.py` (MODIFY)
```python
# occurrences: 1 each (verified:
#   grep -c 'assert len(FieldType) == 32' tests/unit/test_core_models.py
#   grep -c 'assert len(controls) == 32' tests/unit/test_controls_registry.py)
# REPLACE both count pins with the relationship they stood for:
#   every FieldType has exactly one registered control, and vice versa.
#
# FILL IN (test_core_models.py:246): assert the FieldType enum has no duplicate
#   values and no duplicate names — the property "total count" was guarding —
#   bounded by AC8.
# FILL IN (test_controls_registry.py:180): assert
#   {c.type for c in controls} == {m.value for m in FieldType}
#   — bounded by AC8. KEEP the membership spot-checks at lines 184-187.
```
**Why**: a set equality is strictly stronger than a count (it catches a wrong
*and* a missing entry) and never needs editing when a field type is added. The
spot-checks stay because they encode which specific types must never be dropped.

### `packages/parrot-formdesigner/tests/test_edit_toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert len(tools) == 15' tests/test_edit_toolkit.py)
# FILL IN (tests/test_edit_toolkit.py:608): derive the expected tool count from
#   the toolkit's own definitions rather than the literal 15 — e.g. assert the
#   definitions are unique by name and non-empty — bounded by AC8.
# FILL IN (test_tool_definitions_has_required_names): keep the REQUIRED names as
#   a subset assertion (`required <= actual`) instead of set equality, so adding
#   a tool does not break it — bounded by AC8.
```
**Why**: `==` on a name set makes every new tool a test failure; `<=` keeps the
guarantee that the required tools exist without freezing the whole surface.

### `packages/parrot-formdesigner/tests/integration/test_msteams_import_compat.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'expected < 50' tests/integration/test_msteams_import_compat.py)
# tests/integration/test_msteams_import_compat.py:45-50 — the example is 60
# non-empty lines against a `< 50` budget.
# FILL IN: pick ONE — raise the budget with the reason in the docstring, or
# shrink examples/forms/form_server.py back under it — bounded by the
# Implementation Notes decision and recorded in the Completion Note.
```
**Why**: this is the one item here that is a product judgement rather than a
derivation, so it is called out explicitly instead of being silently relaxed.

### FILL IN checklist
- [ ] `test_version_and_docs.py:11` — metadata invariant; bounded by AC8
- [ ] `test_init_imports_metadata_only.py:93` — same invariant; bounded by AC8
- [ ] `test_core_models.py:246` — enum uniqueness; bounded by AC8
- [ ] `test_controls_registry.py:180` — set equality, spot-checks kept; bounded by AC8
- [ ] `test_edit_toolkit.py:608` + name set — derived / subset; bounded by AC8
- [ ] `test_msteams_import_compat.py:50` — budget decision + recorded reason
- [ ] 4 stale docstrings updated

---

## Acceptance Criteria

- [ ] All 7 F4 failures pass.
- [ ] **AC8** The diff introduces no new hardcoded version string or count literal in an equality assertion (verify by grepping the diff).
- [ ] The membership spot-checks at `test_controls_registry.py:184-187` are preserved.
- [ ] Every edited test's docstring matches what it now asserts.
- [ ] The 50-line budget decision is recorded in the Completion Note with its reason.
- [ ] **AC7** `ruff check` clean on every changed file.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_version_and_docs.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_init_imports_metadata_only.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_controls_registry.py -q`
- `pytest packages/parrot-formdesigner/tests/test_edit_toolkit.py -q`
- `pytest packages/parrot-formdesigner/tests/integration/test_msteams_import_compat.py -q`

---

## Test Specification

No new test file — the 7 existing failures are the specification. The bar is
higher than "make them pass": a rewritten assertion must still fail if the
property it guards is actually violated. Sanity-check each one by temporarily
breaking the property.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug tests-test-wheel-layout-tech-debt --feature-id FEAT-618`)
2. **Read the spec** §3 Module 5 and §2's taxonomy row **F4**.
3. **Check dependencies** — TASK-3911 must be `"done"`; the counts move when it lands.
4. **Verify the Codebase Contract** — re-measure every value in the Context table.
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** the Validation Commands. Prefix with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only this task's files.
9. **Close** with `scripts/sdd/close_task.sh TASK-3913 tests-test-wheel-layout-tech-debt verified`.
10. **Fill in the Completion Note** with the budget decision and the new failure count.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: The 50-line budget decision + reason; new `parrot-formdesigner` failure count.

**Deviations from spec**: none | describe if any
