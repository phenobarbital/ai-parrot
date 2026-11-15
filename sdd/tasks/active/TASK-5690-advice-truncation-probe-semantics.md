# TASK-5690: Keep the escape hint when advice is truncated; align probe semantics

**Feature**: FEAT-899 — Procedure guards and plane — FEAT-891 review follow-ups
**Spec**: `sdd/specs/fixgroup-848b9a0ceee1.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5689
**Assigned-to**: unassigned
**Discovered-from**: `issue:bab5aa4a8d70`

---

## Context

Spec §2 M2 and M3 / §3 Modules 2 and 3 (review notes 3, 4 and 5 of `issue:bab5aa4a8d70`).

- `evaluate_command` returns `text[:MAX_ADVICE_CHARS]`: a long reason or `use_instead` cuts off the
  `PARROT_ALLOW_PROCEDURE=1` hint that tells the user how to make a deliberate exception.
- `task.depends_done` accepts only `done`, while `feature.tasks_done` (and `check_task_state.py`) treat
  `done-with-issues` as closed, so a dependent of a `done-with-issues` task is denied at task close.
- `branch.pushed` returns `False` when `git rev-list @{u}..HEAD` fails; a failed read is unknown.

---

## Scope

- Add `_bounded_text` and build both the deny and the advise text through it.
- Add the module constant `CLOSED_STATUSES` and use it in `_probe_task_depends_done` and
  `_probe_feature_tasks_done`.
- Make `SddProbeRunner._branch_pushed` return `None` on a non-zero git exit.
- Tests: `test_deny_text_keeps_escape_hint`, `test_depends_done_accepts_done_with_issues`,
  `test_branch_pushed_unknown_on_git_failure`.

**NOT in scope**: guard matching (TASK-5689); `flow.base_allowed` (spec Non-Goals, note 2); the `pr.open`
probe; the wording of the messages when they fit the limit.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` | MODIFY | `_bounded_text`, `CLOSED_STATUSES`, both probes |
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py` | MODIFY | `_branch_pushed` returns `None` on git failure |
| `packages/ai-parrot/tests/sdd/test_procedure_advice.py` | MODIFY | two new tests |
| `packages/ai-parrot/tests/sdd/test_procedure_cli.py` | MODIFY | one new test |

---

## Codebase Contract (Anti-Hallucination)

Verified against `909ec8aced`.

### Verified Imports
```python
# packages/ai-parrot/tests/sdd/test_procedure_advice.py
from parrot.sdd.scripts import procedure_advice as advice        # line 15
import json                                                       # line 5
# packages/ai-parrot/tests/sdd/test_procedure_cli.py — add:
import subprocess
from parrot.sdd.scripts.procedure_probes import SddProbeRunner    # verified: procedure_probes.py:32
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py
_OPERATORS = frozenset({"&&", "||", ";", "|", "&", "\n"})                    # line 28
MAX_ADVICE_CHARS = 600                                                        # line 333
def _probe_task_depends_done(checkout, scope, args) -> bool | None:           # line 463
#   last line: `return all(statuses.get(dependency) == "done" for dependency in dependencies)`          # line 476
def _probe_feature_tasks_done(checkout, scope, args) -> bool | None:          # line 479
#   last line: `return all(isinstance(item, Mapping) and item.get("status") in {"done", "done-with-issues"} for item in tasks)`   # line 487
def evaluate_command(command: str, cwd: Path, *, env: Mapping[str, str] | None = None) -> Advice:   # line 617
#   builds `text` for deny (three f-string parts) and advise, then `return Advice(decision, text[:MAX_ADVICE_CHARS])`   # line 700

# packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py
class SddProbeRunner:
    def __init__(self, checkout: Path, *, timeout: int = 5) -> None:          # line 35
    def _branch_pushed(self, checkout, scope, args) -> bool | None:           # line 70
#       `if completed.returncode != 0:` / `return False`                     # lines 88-89

# packages/ai-parrot/tests/sdd/test_procedure_advice.py
def _repo(tmp_path: Path, *, status: str = "in-progress", config: dict | None = None) -> Path:   # line 116
#   writes sdd/tasks/index/demo.json with TASK-1 (status) and TASK-2 (pending, depends_on TASK-1),
#   and the plane index at root / advice.PLANE_DIR / advice.INDEX_FILE with procedures["sdd:task-close"]["use_instead"]
```

### Does NOT Exist
- ~~`advice.CLOSED_STATUSES` today~~ — added by this task (a private `_CLOSED_STATUSES` exists only in
  `check_task_state.py`, which `procedure_advice.py` must not import).
- ~~`_bounded_text` today~~ — added by this task.
- ~~a `detail` return from `_branch_pushed`~~ — it returns `bool | None` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_procedure_advice.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_procedure_cli.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py#evaluate_command",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py#_probe_task_depends_done",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py#_probe_feature_tasks_done",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py#SddProbeRunner._branch_pushed"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- A message already within `MAX_ADVICE_CHARS` must be byte-for-byte what it is today.
- The truncation marker `…` counts toward the limit; the suffix is never cut.
- `procedure_advice.py` stays stdlib-only.

---

## Implementation Blueprint

### Steps (in order)
1. Add `CLOSED_STATUSES` below `_OPERATORS` and use it in both probes — *why*: one definition of
   "closed" for the two probes that must agree.
2. Add `_bounded_text` above `evaluate_command` and build both texts through it — *why*: only the
   variable middle may be cut.
3. Change `_branch_pushed` — *why*: a git failure is not evidence that the branch is unpushed.
4. Add the three tests, run the Validation Commands, `ruff check --fix` the four files.

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` (MODIFY) — block 1
```python
# occurrences: 1 (verified: grep -c '^_OPERATORS = ' …/procedure_advice.py)
# AFTER — insert below `_OPERATORS = frozenset({"&&", "||", ";", "|", "&", "\n"})` (verified: procedure_advice.py:28)
CLOSED_STATUSES: frozenset[str] = frozenset({"done", "done-with-issues"})

# occurrences: 1 (verified: grep -c 'return all(statuses.get(dependency) == "done" for dependency in dependencies)' …/procedure_advice.py)
# REPLACE that line (verified: procedure_advice.py:476)
    return all(statuses.get(dependency) in CLOSED_STATUSES for dependency in dependencies)

# occurrences: 1 (verified: grep -c 'in {"done", "done-with-issues"} for item in tasks)' …/procedure_advice.py)
# REPLACE the set literal on that line with CLOSED_STATUSES (verified: procedure_advice.py:487)
    return all(isinstance(item, Mapping) and item.get("status") in CLOSED_STATUSES for item in tasks)
```
**Why**: also update the docstring of `_probe_task_depends_done` to say "closed".

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` (MODIFY) — block 2
```python
# occurrences: 1 (verified: grep -c '^def evaluate_command' …/procedure_advice.py)
# BEFORE — insert above `def evaluate_command(command: str, cwd: Path, *, env: Mapping[str, str] | None = None) -> Advice:` (verified: procedure_advice.py:617)
def _bounded_text(prefix: str, variable: str, suffix: str = "", *, limit: int = MAX_ADVICE_CHARS) -> str:
    """Return ``prefix + variable + suffix`` within ``limit``, truncating only ``variable`` (marked with ``…``)."""
    # FILL IN: return the plain concatenation when it fits; otherwise cut `variable` so that
    #   prefix + cut + "…" + suffix is exactly `limit` long — bounded by AC4; when prefix + suffix
    #   alone exceed the limit fall back to a plain cut at `limit`

# occurrences: 1 (verified: grep -c 'return Advice(decision, text\[:MAX_ADVICE_CHARS\])' …/procedure_advice.py)
# REPLACE the `if decision == "deny": text = (...) else: ... text = f"..."` block and the return (verified: procedure_advice.py:700)
        if decision == "deny":
            text = _bounded_text(
                f"Procedure {procedure_id} is mandatory: ",
                f"{reason}. Use: {procedure.get('use_instead') or procedure.get('command')}",
                ". (Deliberate exception: ask the user to re-run with PARROT_ALLOW_PROCEDURE=1.)",
            )
        else:
            advice_text = procedure.get("advice") or procedure.get("use_instead") or procedure.get("command") or ""
            text = _bounded_text(f"Procedure {procedure_id}: ", f"{reason}. {advice_text}")
        return Advice(decision, text)
```
**Why**: the three parts concatenate to exactly the current deny string, so short messages do not change.

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py` (MODIFY)
```python
# occurrences: 1 for the 8-space form (verified: grep -c '^        if completed.returncode != 0:' …/procedure_probes.py);
#   the `pr.open` twin at line 115 is indented 12 spaces and already returns None
# REPLACE `            return False` under `        if completed.returncode != 0:` (verified: procedure_probes.py:88-89)
        if completed.returncode != 0:
            return None
```
**Why**: also update the `_branch_pushed` docstring ("None when git cannot answer").

### `packages/ai-parrot/tests/sdd/test_procedure_advice.py` (MODIFY)
```python
# AFTER — append at the end of the file
def test_deny_text_keeps_escape_hint(tmp_path: Path) -> None:
    """A long instruction is truncated in the middle; the deliberate-exception hint survives."""
    # FILL IN: rewrite the plane index of `_repo(tmp_path)` with a `use_instead` longer than
    #   MAX_ADVICE_CHARS, evaluate the `git mv` bypass and assert len(text) <= MAX_ADVICE_CHARS and
    #   text.endswith("PARROT_ALLOW_PROCEDURE=1.)") — bounded by spec §4 row 4


def test_depends_done_accepts_done_with_issues(tmp_path: Path) -> None:
    """A dependency closed with issues satisfies ``task.depends_done``; an open one does not."""
    # FILL IN: call advice.apply_check({"probe": "task.depends_done", "expect": True}, root,
    #   {"feature": "demo", "task": "TASK-2"}) for status "done-with-issues" (True) and "in-progress" (False)
```

### `packages/ai-parrot/tests/sdd/test_procedure_cli.py` (MODIFY)
```python
# AFTER — append at the end of the file; add `import subprocess` and the SddProbeRunner import at the top
def test_branch_pushed_unknown_on_git_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A git failure is unknown; only a successful count decides pushed or not."""
    # FILL IN: monkeypatch "parrot.sdd.scripts.procedure_probes.subprocess.run" to return
    #   subprocess.CompletedProcess for (128, "") -> None, (0, "0\n") -> True, (0, "2\n") -> False
```

### FILL IN checklist
- [ ] `_bounded_text` body — bounded by AC4
- [ ] three test bodies

---

## Acceptance Criteria

- [ ] A deny text longer than the limit is cut in the middle, is at most `MAX_ADVICE_CHARS` long and ends
      with the escape hint; a short deny or advise text is unchanged.
- [ ] `task.depends_done` is true for a `done-with-issues` dependency and false for an open one.
- [ ] `branch.pushed` is `None` on a non-zero git exit, `True` for a count of 0, `False` for a count above 0.
- [ ] Every pre-existing test in the two test files still passes; `ruff check` is clean on the four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_procedure_advice.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_procedure_cli.py -q`

---

## Test Specification

See the three test stubs in the blueprint; spec §4 rows 4–6 state what each asserts.

---

## Agent Instructions

1. Work in the feature worktree; TASK-5689 must be `done` (it edits the same two files).
2. Verify the Codebase Contract (line numbers shift after TASK-5689), mark the task `in-progress`.
3. Implement from the blueprint, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the four files listed, close with the close script, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
