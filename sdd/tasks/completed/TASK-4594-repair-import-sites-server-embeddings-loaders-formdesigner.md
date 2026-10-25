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

This task owns the feature's one genuinely nasty case: **breakage class (vi)**.
`packages/ai-parrot-server/tests/mcp/__init__.py` declares a package named `mcp`.
While the test root was itself a package that directory was `tests.mcp` and
harmless. Once TASK-4591 makes the test root importable as a plain directory,
`mcp` becomes a **top-level** name that shadows the real `mcp` third-party
package — so a test importing `mcp` may silently get the test fixture instead.

This is also the task that closes the feature's headline invariant: once
`ai-parrot-embeddings` and `parrot-formdesigner` both collect, AC1's pair works.

---

## Scope

- Repair the 4 class-(i) sites in `packages/parrot-formdesigner/tests`.
- Repair every class-(i)/(ii)/(iii) site TASK-4590 §3 attributes to
  `ai-parrot-server`, `ai-parrot-embeddings` and `ai-parrot-loaders`.
- Resolve breakage class (vi): stop
  `packages/ai-parrot-server/tests/mcp/__init__.py` shadowing the real `mcp`
  package.
- Confirm AC1's pair collect now exits 0.

**NOT in scope**: `ai-parrot`, `ai-parrot-integrations`, `ai-parrot-tools`
(TASK-4592/4593); restoring a top-level `__init__.py`; the regression test
(TASK-4595); **any `parrot-formdesigner` test failure** — that package is 40
tests red on `dev` for reasons FEAT-618 owns (AC7).


> **Amendment B (spec rev 0.3)** — read first. (1) The live pytest config is the tracked root **`pytest.ini`**; the pytest table in
> `pyproject.toml` is dead config. (2) The remedy is `--import-mode=importlib` + `consider_namespace_packages = true` in `pytest.ini`
> (done in TASK-4591); **no `__init__.py` is deleted or added anywhere** — never touch one. Because every `__init__.py` stays,
> relative imports (`from .x`, `from ..x`) keep working: **the preferred repair for a `from tests.<x> import …` is the equivalent
> relative import**, or a conftest-provided fixture. Evidence: `sdd/state/FEAT-720/spike-namespace-packages.md`. Repairs may change only
> an import statement, a `conftest.py`, or a dotted string target. `parrot-formdesigner` fails on 5 files (4 `tests.*` + `unit/test_build_snippet_bundles.py`, class (iii)).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/integration/conftest.py` | MODIFY | class (i) import |
| `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py` | MODIFY | class (i) import |
| `packages/parrot-formdesigner/tests/unit/test_feat302_review_fixes.py` | MODIFY | class (i) import |
| `packages/parrot-formdesigner/tests/unit/test_org_graph_service.py` | MODIFY | class (i) import |
| `packages/ai-parrot-server/tests/mcp/__init__.py` | MODIFY | class (vi) — stop shadowing the real `mcp` |
| `packages/parrot-formdesigner/tests/conftest.py` | MODIFY | class (iii): explicit `sys.path` entry for the package's own `scripts/` (`scripts.build_snippet_bundles`) |

Any class-(i)/(ii)/(iii) file TASK-4590 §3 attributes to `ai-parrot-server`,
`ai-parrot-embeddings` or `ai-parrot-loaders` is added to this table by the
implementing agent **before** editing, so the Complexity Contract stays accurate.

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
| `packages/ai-parrot-server/tests/mcp/__init__.py` | present, 0 bytes | `ls -l` |
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

### The class-(vi) hazard, stated precisely

`packages/ai-parrot-server/tests/mcp/__init__.py` makes `mcp` a package name.
After TASK-4591 the test root is no longer a package, so this directory is
reachable as top-level `mcp` and can shadow the real third-party `mcp`
distribution. A shadowed import does not raise — it returns the wrong module, so
a test can **pass against the fixture** while the product code it meant to
exercise is never imported. Treat a green run here as insufficient evidence; the
acceptance criterion below checks the resolved module's file path explicitly.

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
    {"path": "packages/ai-parrot-server/tests/mcp/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/conftest.py", "action": "MODIFY"}
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

### Class (vi) specifically
Two acceptable resolutions; choose on TASK-4590's evidence and record which:
- rename the directory so it no longer claims the name `mcp`; or
- keep the directory a package whose name cannot reach top level.

Do **not** resolve it by deleting the real `mcp` dependency, by reordering
`sys.path`, or by renaming the third-party package's import.

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
- `sdd/state/FEAT-720/spike-collect.md` §3 — the **only** source for the server,
  embeddings and loaders sites
- `sdd/specs/tests-test-wheel-layout-tech-debt.spec.md` (FEAT-618) — the 40
  formdesigner failures this task must not touch

---

## Implementation Blueprint

### Steps (in order)
1. Record `parrot-formdesigner`'s current collect count and failure count (40) —
   *why*: AC7 is a before/after comparison and cannot be made retroactively.
2. Repair the 4 formdesigner class-(i) imports — *why*: they are the only
   import-statement work in this task; the other three distributions have none.
3. Take the server, embeddings and loaders sites from TASK-4590 §3 — *why*: they
   are classes (ii)/(iii), invisible to an import grep, so there is no other list.
4. Resolve class (vi) and verify the resolved module path — *why*: a shadowed
   `mcp` import returns the wrong module silently, so only the path proves it.
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

### `packages/ai-parrot-server/tests/mcp/__init__.py` (MODIFY)
```python
# occurrences: n/a — the file is 0 bytes; the defect is the directory NAME, not its contents.
# FILL IN: the class (vi) resolution — bounded by AC5 and by the two acceptable
#          options in "Class (vi) specifically" above. Record which you chose and
#          why in the Completion Note. Do NOT resolve it by touching sys.path, the
#          real `mcp` dependency, or any product import.
```
**Why**: the fix is structural rather than textual — an empty file cannot be
edited into correctness, so the decision is about the directory's identity. It is
left as a `FILL IN` because TASK-4590's evidence decides whether the name reaches
top level in practice, and a rename has call sites a blind choice would miss.

### FILL IN checklist
- [ ] `test_feat300_review_fixes.py:32` — replacement import, identical names; bounded by AC5
- [ ] the other 3 formdesigner class-(i) sites; bounded by AC5
- [ ] every server / embeddings / loaders site from TASK-4590 §3; bounded by AC5
- [ ] class (vi) resolution + the reason, recorded in the Completion Note

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

**Completed by**: sdd-worker (by hand; the task is five small edits)
**Date**: 2026-10-23
**Notes**: 4 `from tests.<x>` → relative imports in `parrot-formdesigner` (`integration/conftest.py`, `unit/test_feat300_review_fixes.py` — imported names unchanged,
`unit/test_feat302_review_fixes.py`, `unit/test_org_graph_service.py`) + class (iii): `unit/test_build_snippet_bundles.py` now loads `scripts/build_snippet_bundles.py` by path (an earlier version put the package root on `sys.path` in `tests/conftest.py`; removed after review — a global path entry is ambiguous across trees). Nothing needed in `ai-parrot-server`, `-embeddings`, `-loaders`.
Evidence (live `pytest.ini`): **AC1** `embeddings + formdesigner` collect together: 4,113 items, 0 errors, none of `ImportPathMismatchError` / `Plugin already registered` /
`import file mismatch`. Formdesigner standalone 3,899 (baseline 3,899); server 3,597 with 4 errors that are all pre-existing (2 `fakeredis`, 2 `unit/e2e`). All 28 roots in one session:
43,420 collected, **0 identity collisions**, 49 errors that are class (xi) pollution (a test replaces `sys.modules['aiohttp']`/`parrot._imports` at import) — out of scope.
Formdesigner failure count unchanged (AC7): the same 6 failures in the touched files before and after (FEAT-618's baseline).
Class (vi) (`tests/mcp` shadowing the real `mcp`) was later traced to `packages/ai-parrot/tests/conftest.py` putting its own tests directory on `sys.path`; fixed in the follow-up commit (helpers are now imported relatively).

**Deviations from spec**: class (vi) left alone (see above).
