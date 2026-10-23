# TASK-4675: brief-aware junit report paths in `test_scope/report.py`

**Feature**: FEAT-736 — The sdd_coder MCP surface accepts every id and tier its engine already accepts
**Spec**: `sdd/specs/sdd-coder-models-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:0ea4f0acaefd`

---

## Context

`issue:0ea4f0acaefd` names `test_scope/report.py`'s `_SAFE_ID_RE` as one of its
fix sites. That constant decides whether a feature id and a task id are safe to
use as **path components** of a junit report path
(`junit_path_for` → `<root>/<feature>/<task>/<suite>-<n>.xml`); anything it
refuses is mapped to the literal `_invalid`.

Today it admits only `FEAT-<NNN>`, `TASK-<NNN>` and the `_rerun` sentinel. A
brief run has a `BRIEF-<KEY>` feature id and `HOTFIX-<KEY>-<n>` task ids, so
**every** brief validation writes to `_invalid/_invalid/` — different brief
tasks silently overwrite each other's junit XML, and a report killed before
pytest writes can be read back with another task's counts.

Spec §3 Module 3, plus Module 4 (record the decision).

## Scope

- Widen `_SAFE_ID_RE` (L80) to admit `BRIEF-<KEY>` feature ids and
  `HOTFIX-<KEY>-<n>` task ids beside the existing three shapes.
- Comment *why* this site's key class is **stricter** than `sdd_coder`'s.
- Add the four tests in **Test Specification**.
- Record the cross-site decision with `wikitoolkit remember`.

**NOT in scope**:
- `sdd_coder/models.py` (TASK-4673), `sdd_coder/optimization_models.py` and
  `sdd_coder/background.py` (TASK-4674).
- `_safe_id`'s and `junit_path_for`'s signatures and behaviour — only the
  *admitted set* changes.
- `packages/ai-parrot-server/src/parrot/e2e/{models,state,supervisor,cli}.py`,
  which each declare their own unrelated `_SAFE_ID_RE`. Different feature,
  do not touch.
- `packages/ai-parrot/build/...` — a stale build artifact tree.

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | 1 edit site |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` | MODIFY | 4 tests |

---

## Codebase Contract (Anti-Hallucination)

Verified at `dev @ b2ec65729`, 2026-10-24.

### Verified Imports

```python
# already imported at the top of report.py — add nothing
import os
import re
from pathlib import Path

# test module already imports the module under test as:
from parrot.flows.dev_loop.test_scope import report
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py
def report_root() -> Path:                                        # L72
    override = os.environ.get(REPORT_ROOT_ENV)
    if override:
        return Path(override)
    return Path("/tmp") / f"claude-{os.getuid()}" / "sdd-tests"

_SAFE_ID_RE = re.compile(r"^(?:FEAT-\d+|TASK-\d+|_rerun)$")        # L80  (1 occurrence)

def _safe_id(value: str) -> bool:                                 # L85
    """Return True when ``value`` is a feature/task id that is safe to use as a path component."""
    return bool(_SAFE_ID_RE.match(value))                         # L86

def junit_path_for(feature_id: str, task_id: str, suite: str, ordinal: int) -> Path:   # L88
    ...
    feature_dir = feature_id if _safe_id(feature_id) else "_invalid"      # L94
    task_part = task_id if _safe_id(task_id) else "_invalid"              # L95

# The id space being admitted — scripts/sdd/brief_meta.py
BRIEF_ID_PREFIX = "BRIEF-"                                        # L25  → feature_id = f"BRIEF-{key}"
def brief_task_id(meta: BriefMeta, n: int) -> str:                # L181 → f"HOTFIX-{key}-{n}"
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")        # L28  — brief_meta's own key class (ADMITS dots)

# Existing test in the target module, for style and for the env override pattern:
# tests/flows/dev_loop/test_scope/test_report.py:183  test_junit_paths_are_unique_per_invocation
#     first = report.junit_path_for("FEAT-695", "TASK-1", "one", 1)
# tests/flows/dev_loop/test_scope/test_report.py:219  test_report_root_env_override_and_default
```

### Does NOT Exist

- `_safe_id` does **not** use `fullmatch` — it uses `.match()`, which is a
  *prefix* match. The trailing `$` in the pattern is what makes it total.
  **Keep the `$`** or `"FEAT-1/../../etc"` becomes a legal path component.
- There is no `_safe_feature_id` / `_safe_task_id` split — one predicate gates
  both arguments. Do not introduce a split.
- `report.py` does **not** import anything from `sdd_coder` or `brief_meta`,
  and must not start to — it is a stdlib-only module (there is a
  `test_stdlib_only.py` beside the target test file that enforces this).
- No `HOTFIX-`/`BRIEF-` handling exists anywhere in `test_scope/` today.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#_safe_id",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#junit_path_for"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

The module is stdlib-only and keeps its constants as module-level
`re.compile(...)` right above the function that uses them. Keep that shape.

### Key Constraints

- **This site must NOT reuse `sdd_coder`'s widened class.** `sdd_coder`'s key
  class is `[A-Za-z0-9._-]`, which admits `..`; pasted here it would make
  `HOTFIX-a..b-1` a legal path component. Use the **dot-free** class
  `[A-Za-z0-9_-]` instead. A brief key containing a `.` therefore keeps
  falling back to `_invalid` — safe, and no worse than today's behaviour.
  This divergence is deliberate and must be commented at the site.
- Keep the trailing `$`; `_safe_id` relies on it (see "Does NOT Exist").
- `_rerun` must stay admitted — it is an existing sentinel directory name.
- Do not add an import to this module; `test_stdlib_only.py` guards it.

### References in Codebase

- `scripts/sdd/brief_meta.py:25,181` — where `BRIEF-<KEY>` and
  `HOTFIX-<KEY>-<n>` are generated.
- TASK-4673 / TASK-4674 — the sibling (wider, dotted) declarations.

---

## Implementation Blueprint

### Steps (in order)

1. Widen `_SAFE_ID_RE` with the dot-free key class and add the explanatory
   comment — do it in one edit so the reason ships with the change.
2. Add the four tests.
3. `ruff check` both files and run both Validation Commands.
4. Record the decision with `wikitoolkit remember` (step 5 below) — do this
   last, after the tests pass, so the memo describes shipped behaviour.

### `packages/.../test_scope/report.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '_SAFE_ID_RE = re.compile(' packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py)
# REPLACE the line `_SAFE_ID_RE = re.compile(r"^(?:FEAT-\d+|TASK-\d+|_rerun)$")` (verified: report.py:80)
# Feature/task ids safe as a PATH COMPONENT. Deliberately stricter than the
# sdd_coder task-id gates (`models._TASK_ID_RE` and friends, FEAT-736): their
# key class `[A-Za-z0-9._-]` mirrors `brief_meta._SAFE_REF_RE` and admits `.`,
# which here would make `HOTFIX-a..b-1` a usable path component. The key class
# below excludes `.`, so a dotted brief key falls back to `_invalid` -- safe,
# and no worse than refusing every brief id as this did before. `_safe_id`
# uses `.match()`, so the trailing `$` is what makes this a full match: keep it.
_SAFE_ID_RE = re.compile(
    r"^(?:FEAT-\d+|TASK-\d+|BRIEF-[A-Za-z0-9][A-Za-z0-9_-]*|HOTFIX-[A-Za-z0-9][A-Za-z0-9_-]*-\d+|_rerun)$"
)
```

**Why**: `junit_path_for` interpolates both ids straight into a filesystem
path, so this predicate is a traversal gate, not an id validator — which is
why it may not simply copy its siblings. Admitting `BRIEF-<KEY>` and
`HOTFIX-<KEY>-<n>` is what stops every brief task's junit XML from colliding
in one shared `_invalid/_invalid/` directory.

### `packages/.../tests/flows/dev_loop/test_scope/test_report.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def test_junit_paths_are_unique_per_invocation' packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py)
# AFTER — insert below the body of `def test_junit_paths_are_unique_per_invocation():` (verified: test_report.py:183-187)
def test_junit_path_for_brief_ids():
    """A brief run gets its own directory pair instead of _invalid/_invalid (issue:0ea4f0acaefd)."""
    path = report.junit_path_for("BRIEF-CS-228", "HOTFIX-CS-228-1", "one", 1)
    assert "_invalid" not in path.parts
    assert "BRIEF-CS-228" in path.parts
    assert "HOTFIX-CS-228-1" in path.parts


# FILL IN: the remaining three tests from the Test Specification table —
# bounded by AC 2, AC 3 and AC 4. Follow the shape above; assert on
# `path.parts`, never on a hand-built string, because the root comes from
# `report_root()`.
```

**Why**: asserting on `path.parts` keeps the tests independent of
`report_root()`'s `/tmp/claude-<uid>/sdd-tests` default and of the
`REPORT_ROOT_ENV` override.

### Step 5 — record the decision (no file target)

```bash
wikitoolkit remember \
  "FEAT-736: sdd_coder's task-id gates (models.py, optimization_models.py, background.py) admit brief ids HOTFIX-<KEY>-<n> beside TASK-<NNN>, each re-declared on purpose rather than shared (background.py:76-77). test_scope/report.py::_SAFE_ID_RE is deliberately STRICTER -- its key class excludes '.' because it gates a filesystem path component, so a dotted brief key still falls back to _invalid." \
  --category decision \
  --title "sdd_coder brief task ids: four separate gates, report.py stricter"
```

**Why**: the strict/wide divergence is the one non-obvious thing in this
feature; without a written reason the next author will "fix the
inconsistency" and reintroduce `..` as a path component.

### FILL IN checklist

- [ ] `test_junit_path_for_brief_tasks_do_not_collide` — two different brief
      task ids give two different parent directories; bounded by AC 2.
- [ ] `test_junit_path_for_rejects_traversal` — `"../etc"`, `"a/b"`,
      `"HOTFIX-a..b-1"`, `"BRIEF-a..b"` all map to `_invalid`; bounded by AC 3.
- [ ] `test_junit_path_for_keeps_rerun_sentinel` — `_rerun` still admitted;
      bounded by AC 4.
- [ ] The `wikitoolkit remember` call in step 5.

---

## Acceptance Criteria

1. `junit_path_for("BRIEF-CS-228", "HOTFIX-CS-228-1", …)` yields a path whose
   parts contain `BRIEF-CS-228` and `HOTFIX-CS-228-1` and no `_invalid`.
2. Two different brief task ids under the same brief feature produce two
   different parent directories.
3. `"../etc"`, `"a/b"`, `"HOTFIX-a..b-1"` and `"BRIEF-a..b"` each still map to
   `_invalid`.
4. `FEAT-<NNN>`, `TASK-<NNN>` and `_rerun` keep working exactly as before.
5. `_safe_id` and `junit_path_for` keep their current signatures, and
   `report.py` gained no import.
6. Both Validation Commands exit 0, `test_stdlib_only.py` included.
7. The decision is recorded via `wikitoolkit remember` (step 5).

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

## Test Specification

| Test | Asserts |
|---|---|
| `test_junit_path_for_brief_ids` | brief ids get their own directory pair |
| `test_junit_path_for_brief_tasks_do_not_collide` | two brief tasks → two directories |
| `test_junit_path_for_rejects_traversal` | `../etc`, `a/b`, dotted keys → `_invalid` |
| `test_junit_path_for_keeps_rerun_sentinel` | `_rerun` still admitted |

Run with `PYTHONPATH=packages/ai-parrot/src`. No new fixtures.

## Agent Instructions

1. Verify the contract lines in the source before editing; report drift rather
   than inventing an anchor.
2. Edit only the two files in the table. Do not touch the `_SAFE_ID_RE` copies
   under `packages/ai-parrot-server/src/parrot/e2e/`.
3. Use the **dot-free** key class here — do not copy `sdd_coder`'s. Keep the
   trailing `$`. Add no import to `report.py`.
4. `ruff check` both files, then run both Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src`.
5. Run the `wikitoolkit remember` call in blueprint step 5 after the tests pass.
6. Commit as `feat(sdd-coder-models-fixes): TASK-4675 — brief-aware junit report paths`.

## Completion Note

**Verified**, 2026-10-24.

`_SAFE_ID_RE` widened to
`^(?:FEAT-\d+|TASK-\d+|BRIEF-[A-Za-z0-9][A-Za-z0-9_-]*|HOTFIX-[A-Za-z0-9][A-Za-z0-9_-]*-\d+|_rerun)$`
with the dot-free key class and the seven-line comment explaining why this
gate is stricter than its `sdd_coder` twins. `_safe_id` and `junit_path_for`
keep their signatures; `report.py` gained no import.

**Correction to this task's AC 1–2 (spec §3 Module 3 said the same thing).**
The task file assumed `junit_path_for` used the task id as a *directory*. It
does not — the real layout is

```
report_root() / <feature_id> / "junit" / f"{task_id}--{suite}--{ordinal}.xml"
```

so the feature id is a directory and the task id is a **filename prefix**. The
pre-fix defect is therefore a *filename* collision, not a directory one: every
brief task wrote `_invalid/junit/_invalid--<suite>--<n>.xml` and overwrote its
siblings. The fix and its value are unchanged; only the wording of AC 1–2 and
the shape of the assertions moved. Tests assert on `path.parts` for the
feature component and `path.name` for the task component.

Tests added (4, one parametrized over 8 unsafe ids):
`test_junit_path_for_brief_ids`, `test_junit_path_for_brief_tasks_do_not_collide`,
`test_junit_path_for_rejects_traversal`, `test_junit_path_for_keeps_rerun_sentinel`.
The rejection table pins `HOTFIX-a..b-1`, `BRIEF-a..b` and `BRIEF-CS.228` as
`_invalid`, which is the deliberate strictness.

Evidence:
- `pytest .../test_scope/test_report.py .../test_scope/test_stdlib_only.py -q`
  → **43 passed**
- `ruff check` on both changed files → clean

AC 7: decision recorded as wiki memory `mem-a53868191c3b`
("sdd_coder brief task ids: four separate gates, report.py stricter"), including
the `junit_path_for` layout correction above.
