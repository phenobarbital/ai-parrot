# TASK-4594: Repair the server, embeddings, loaders and formdesigner import sites

**Feature**: FEAT-720 — One Importable Identity per Package Test Tree
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4593
**Assigned-to**: unassigned
**Discovered-from**: `issue:45cf6a054e06`

---

## Context

Implements spec **Module 3** for the last four affected distributions:
`ai-parrot-server` (6 round-2 collect errors), `parrot-formdesigner` (5, with 4
class-(i) sites), `ai-parrot-embeddings` (1) and `ai-parrot-loaders` (1).

**Amendment A**: the former hard case (class (vi), `ai-parrot-server/tests/mcp/__init__.py` shadowing the real
`mcp`) is now resolved by TASK-4591's identity fixpoint, which deletes that file. This task verifies it: after
TASK-4591, `import mcp` inside the server tests must resolve to the installed package (check `mcp.__file__`).

This is also the task that closes the feature's headline invariant: once
`ai-parrot-embeddings` and `parrot-formdesigner` both collect, AC1's pair works.

---

## Scope

- Repair the 4 class-(i) sites in `packages/parrot-formdesigner/tests`.
- Repair the one class-(x) site in `packages/parrot-formdesigner/tests`: `unit/test_build_snippet_bundles.py`
  imports `scripts.build_snippet_bundles`, which used to resolve through prepend mode; give it an explicit
  owning-package path in `packages/parrot-formdesigner/tests/conftest.py`.
- `ai-parrot-server`, `ai-parrot-embeddings`, `ai-parrot-loaders`: nothing to repair (verify and record). Class (vi)
  (`server/tests/mcp/__init__.py` shadowing `mcp`) is **resolved by TASK-4591**, which deletes that file.
- Confirm AC1's pair collect now exits 0.

**NOT in scope**: `ai-parrot`, `ai-parrot-integrations`, `ai-parrot-tools`
(TASK-4592/4593); restoring a top-level `__init__.py`; the regression test
(TASK-4595); **any `parrot-formdesigner` test failure** — that package is 40
tests red on `dev` for reasons FEAT-618 owns (AC7).


> **Amendment A (spec rev 0.2)** — measured in the (a′) state (TASK-4591 applied, importlib mode), standalone
> per-root `--collect-only`: `parrot-formdesigner` fails on exactly 1 file (`unit/test_build_snippet_bundles.py`, `No module named 'scripts.build_snippet_bundles'`); `ai-parrot-embeddings` and `ai-parrot-loaders` collect clean at their baseline counts (214, 421); `ai-parrot-server` collects 3,647 items with only 2 pre-existing `fakeredis` errors (its baseline collect stopped early on a shadowed `mcp`, so its count rises — state it in the AC2 matrix, do not treat it as a defect). The 4 class-(i) formdesigner sites still resolve only by import-order luck and are repaired.
> Class (ii)/(iii)/(vi) work formerly attributed to TASK-4590 §3 is **moot** unless named in the table below:
> TASK-4591 now removes/adds the nested `__init__.py` files that caused it. Repairs may change only an import
> statement, a `conftest.py`, or a dotted string target. Never restore or add an `__init__.py`.
> Class (xi) `sys.modules` pollution seen only in many-trees-one-session runs is NOT this task's.


> **Class (ii) correction (measured after TASK-4591 merged)**: `ai-parrot-embeddings/tests/test_namespace_imports.py` and `ai-parrot-loaders/tests/test_metadata_standardization.py` do `from .<sibling> import …` in a root-level test file; the tests root is no longer a package, so there is no parent. Repair by loading the sibling by file location (`importlib.util.spec_from_file_location` + `module_from_spec`, registered in `sys.modules` under a unique name) at the same place the import was — an import-statement-level change only. Do NOT add an `__init__.py` (AC4) and do NOT put the tests directory on `sys.path`.


> **Class (ii) at scale (corrected measurement, real `addopts`, TASK-4591 + TASK-4592 merged)**: removing the 51 nested
> `__init__.py` files left every `from .<sibling> import …` in those directories without a parent package. This is the
> bulk of the residual work, not the handful first reported: `ai-parrot-server` 17 files (`ui/` ×13, `handlers`, `integration`, `unit/e2e` ×2; the 2 `fakeredis` errors are pre-existing and out of scope) and 2 more `parrot-formdesigner` files (`test_submission_metadata_storage.py`, `test_submission_revisions.py`). Repair each by loading the sibling **by file
> location** (`importlib.util.spec_from_file_location` + `module_from_spec`, registered in `sys.modules` under a unique,
> distribution-prefixed name) at the place the import was. Import-level change only; never add an `__init__.py` (AC4),
> never put the tests directory on `sys.path`, never change what a test asserts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/integration/conftest.py` | MODIFY | class (i) import |
| `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py` | MODIFY | class (i) import |
| `packages/parrot-formdesigner/tests/unit/test_feat302_review_fixes.py` | MODIFY | class (i) import |
| `packages/parrot-formdesigner/tests/unit/test_org_graph_service.py` | MODIFY | class (i) import |
| `packages/parrot-formdesigner/tests/conftest.py` | MODIFY | class (x): explicit `sys.path` entry for the package's own `scripts/` |
| `packages/ai-parrot-embeddings/tests/test_namespace_imports.py` | MODIFY | class (ii): `from ._helpers import run_in_pruned_venv` has no parent package |
| `packages/ai-parrot-loaders/tests/test_metadata_standardization.py` | MODIFY | class (ii): `from .conftest import CANONICAL_DOC_META_KEYS, CANONICAL_TOP_LEVEL_KEYS` has no parent package |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/unit/e2e/test_evidence.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/unit/e2e/test_supervisor.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_canvas_linked.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_chart_adapter.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_format_parity.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_refresh.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_runtime.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_types.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_chart_dual_axis.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_my_tool_settings.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_schema_form.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/ai-parrot-server/tests/ui/test_vitest_tools_tab.py` | MODIFY | class (ii): relative import in a directory that lost its `__init__.py` |
| `packages/parrot-formdesigner/tests/unit/test_submission_metadata_storage.py` | MODIFY | class (i)/(ii): `tests.unit.real_db_shapes` / relative import |
| `packages/parrot-formdesigner/tests/unit/test_submission_revisions.py` | MODIFY | class (i)/(ii): `tests.unit.real_db_shapes` / relative import |

`ai-parrot-server`, `ai-parrot-embeddings` and `ai-parrot-loaders` have no failing site: record their
standalone collect (server 3,647 items with only the 2 pre-existing `fakeredis` errors; embeddings 214; loaders 421).

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

The sites being repaired, sampled verbatim on `dev c2fd0ae28`:

```python
# packages/parrot-formdesigner/tests/integration/conftest.py:9
from tests.fixtures.persistence import (  # noqa: F401

# packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py:32
from tests.unit.test_api_feat300 import _make_form, _make_handler, _make_request
```

### Verified facts (measured on `dev c2fd0ae28`)

| Fact | Value | Command |
|---|---|---|
| class-(i) sites, formdesigner | **4 files** | `grep -rln -E '^\s*(from\|import)\s+tests[.\s]' packages/parrot-formdesigner/tests` |
| class-(i) sites, server / embeddings / loaders | **0** | same, per tree |
| `packages/ai-parrot-server/tests/mcp/__init__.py` | present, 0 bytes **until TASK-4591 deletes it** | `ls -l` |
| round-2 collect errors | server 6, formdesigner 5, embeddings 1, loaders 1 | `sdd/state/FEAT-720/spike-collect.md` §2 supersedes |
| `parrot-formdesigner` baseline on `dev` | **40 failed**, 3825 passed | `pytest packages/parrot-formdesigner/tests -q -p no:randomly` |

Server, embeddings and loaders have **zero** class-(i) sites yet 8 round-2
collect errors between them — so their breakage is entirely classes (ii)/(iii)
and must come from TASK-4590 §3, not from a grep for imports.

### Does NOT Exist
- ~~a `tests` package after TASK-4591~~ — do not restore one.
- ~~a class-(i) import site in `ai-parrot-server`, `ai-parrot-embeddings` or
  `ai-parrot-loaders`~~ — **verified zero**. If you find yourself editing an
  import statement in those trees, you are working from the wrong list.
- ~~`packages/ai-parrot-embeddings/tests/test_wheel_layout.py` being broken~~ —
  it passes **15/15 standalone** today and must still do so (AC3). It is the
  victim in the original bug report, not a cause.
- ~~a `parrot-formdesigner` failure this task may fix~~ — all 40 belong to
  FEAT-618 (AC7).

### Class (vi) — verification only (Amendment A)

TASK-4591 deletes `packages/ai-parrot-server/tests/mcp/__init__.py`. Verify, do not repair: with the
(a′) state applied, `python -c` run through pytest's collection (or a one-off test-free probe) must show
`mcp.__file__` under site-packages, and the server tests that import `mcp` still collect. Record the path.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/tests/integration/conftest.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_feat302_review_fixes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_org_graph_service.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/conftest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-embeddings/tests/test_namespace_imports.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-loaders/tests/test_metadata_standardization.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/e2e/test_evidence.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/e2e/test_supervisor.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_canvas_linked.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_chart_adapter.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_format_parity.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_refresh.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_runtime.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_types.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_chart_dual_axis.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_my_tool_settings.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_schema_form.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_tools_tab.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_submission_metadata_storage.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_submission_revisions.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints — the hard one
A repair may change **only** an import statement, a `conftest.py`, or a dotted
string target. It may **not** change an assertion, a fixture's behaviour, a
test's parameters, or add a skip/xfail (AC5, AC6).

### The class-(x) site
`packages/parrot-formdesigner/tests/unit/test_build_snippet_bundles.py` does `from scripts.build_snippet_bundles import …`;
`scripts/` lives at `packages/parrot-formdesigner/scripts/` (no `__init__.py`). Add, in
`packages/parrot-formdesigner/tests/conftest.py`, an explicit insertion of `Path(__file__).resolve().parents[1]`
into `sys.path` (idempotent: only if absent). Do not touch the test file.

### Other constraints
- `parrot-formdesigner` is red for unrelated reasons. Compare its **collect item
  count** and its **failure count** (40) before and after; both must be unchanged.
  Do not read a red run here as this task failing.
- `test_feat300_review_fixes.py:32` imports helpers from a sibling **test module**
  (`tests.unit.test_api_feat300`), not from a fixtures module. FEAT-618's TASK-3910
  will later fold `_tenant_request` into `_make_request` in that same file —
  repair the import path only, and leave the imported names exactly as they are.
- `PYTHONPATH` per distribution when running in the worktree.

### References in Codebase
- `sdd/state/FEAT-720/spike-identity-fixpoint.md` — the measured residual sites in the (a′) state
- `sdd/specs/tests-test-wheel-layout-tech-debt.spec.md` (FEAT-618) — the 40
  formdesigner failures this task must not touch

---

## Implementation Blueprint

### Steps (in order)
1. Record `parrot-formdesigner`'s current collect count and failure count (40) —
   *why*: AC7 is a before/after comparison and cannot be made retroactively.
2. Repair the 4 formdesigner class-(i) imports — *why*: they are the only
   import-statement work in this task; the other three distributions have none.
3. Fix the class-(x) `scripts.*` site in `tests/conftest.py` — *why*: prepend mode used to provide that path.
4. Verify (do not repair) that `mcp` resolves to the installed package, and record server/embeddings/loaders
   standalone collect counts — *why*: a shadowed `mcp` import returns the wrong module silently, and these
   three distributions have no repair of their own.
5. Run AC1's pair collect — *why*: this is the first task at which the feature's
   headline invariant can be true, and it is this task's real deliverable.

### `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from tests.unit.test_api_feat300 import _make_form, _make_handler, _make_request' packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py)
# REPLACE — the line `from tests.unit.test_api_feat300 import _make_form, _make_handler, _make_request` (verified: packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py:32)
# FILL IN: the replacement import — bounded by AC5 (import-only change) and by
#          keeping the imported NAMES identical: _make_form, _make_handler,
#          _make_request. FEAT-618 TASK-3910 edits that sibling module's
#          _make_request; renaming anything here would collide with it.
```
**Why**: this site imports from a sibling *test module*, not a fixtures module,
and it is the one file in this feature that another in-flight feature also edits.
Changing only the path keeps the two changes disjoint.

### `packages/parrot-formdesigner/tests/conftest.py` (MODIFY)
```python
# Add near the top, after the existing imports (idempotent; no other change to this file):
#   _PKG_ROOT = str(Path(__file__).resolve().parents[1])
#   if _PKG_ROOT not in sys.path:
#       sys.path.insert(0, _PKG_ROOT)
# FILL IN: the exact placement and the `Path`/`sys` imports, only if not already present — bounded by AC5.
```
**Why**: `scripts/` sits beside `src/` and `tests/`, not inside the tests tree. Prepend mode used to put that directory
on `sys.path` as a side effect of the removed `tests/__init__.py`; importlib mode does not, so the owning package
path must be explicit. Only `conftest.py` changes, never the test.

### FILL IN checklist
- [ ] `test_feat300_review_fixes.py:32` — replacement import, identical names; bounded by AC5
- [ ] the other 3 formdesigner class-(i) sites; bounded by AC5
- [ ] `tests/conftest.py` explicit package path for `scripts.*`; bounded by AC5
- [ ] `mcp.__file__` verification recorded in the Completion Note

---

## Acceptance Criteria

- [ ] No `from tests.<x>` or `import tests.<x>` remains anywhere under
      `packages/*/tests`:
      `grep -rn -E '^\s*(from|import)\s+tests[.\s]' packages/` → empty.
- [ ] **AC1 met**: `pytest packages/ai-parrot-embeddings/tests packages/parrot-formdesigner/tests --collect-only -q`
      exits 0 — no `ImportPathMismatchError`, no pluggy double-registration.
- [ ] **AC3 met**: `pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q`
      passes 15/15.
- [ ] Class (vi) resolved: in a session that collects
      `packages/ai-parrot-server/tests`, `import mcp; print(mcp.__file__)` resolves
      to the **real** third-party package, not to
      `packages/ai-parrot-server/tests/mcp/`.
- [ ] **AC7 met**: `parrot-formdesigner`'s failure count is still exactly **40** —
      neither repaired nor worsened — and its collect item count is unchanged.
- [ ] All four distributions collect with exit 0 and unchanged item counts (AC2).
- [ ] Every edit is an import statement, a `conftest.py`, a dotted string target,
      or the class-(vi) structural change (AC5).
- [ ] No test is skipped, xfailed or deleted (AC6).
- [ ] `ruff check` clean on every changed file (AC9).

---

## Validation Commands

- `pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_org_graph_service.py -q`

---

## Test Specification

No new test code. Each repaired file's existing tests are the specification.
`parrot-formdesigner`'s 40 known failures are the control: unchanged means
correct.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** §2 breakage classes and **TASK-4590's `sdd/state/FEAT-720/spike-collect.md` §3** —
   for server/embeddings/loaders it is the only list
3. **Check dependencies** — TASK-4593 must be `"done"` in the per-spec index
4. **Verify the Codebase Contract** — re-run the per-tree `grep` counts; the
   "zero class-(i) sites" claim for three distributions is load-bearing
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file
6. **Implement** — record formdesigner's baseline counts BEFORE editing
7. **Verify** every acceptance criterion, especially the `mcp.__file__` check and
   the unchanged 40
8. **Commit the code** — stage only this task's files, never `git add .` / `-A`
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4594 tests-test-wheel-layout-tech-debt-2 verified`
10. **Fill in the Completion Note** — state the class-(vi) resolution chosen and
    why, and list any site that needed more than an import change

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
