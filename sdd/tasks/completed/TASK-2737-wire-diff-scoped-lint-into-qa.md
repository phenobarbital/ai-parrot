# TASK-2737: Wire the diff-scoped ruff runner into `QANode`'s lint command

**Feature**: FEAT-497 — QA Gate: Verified Triage Evidence & Diff-Scoped Lint
**Spec**: `sdd/specs/qa-gate-evidence-and-diff-scoped-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2736
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (goal G3). TASK-2736 delivers `scripts/sdd/lint_new.py`.
This task makes `QANode._run_deterministic_qa` build its lint command around
that script instead of a bare `ruff check`, so the `sdd-qa` subagent runs
`python -m scripts.sdd.lint_new <files> && mypy --no-incremental <files>`.

Only the `ruff` half is rewritten. The `mypy` half keeps today's
file-scoped behaviour through the unchanged `_scope_lint_to_files`, and a
lint command with no `ruff check` in it is returned untouched, so an
operator-configured `lint_command` keeps working.

The spec's §3 reference implementation is **normative**: write it as given.

---

## Scope

- Add the module-level pattern next to `_LINT_TARGET_RE` in `qa.py`:
  ```python
  #: Matches the ``ruff check <targets>`` half of a compound lint command, up to
  #: the next ``&&``/``;`` separator.
  _RUFF_CHECK_RE = re.compile(r"\bruff\s+check\b[^&;]*")
  ```
- Add `QANode._baseline_aware_lint(cls, command: str, files: List[str]) -> str`
  (`@classmethod`) immediately after `_scope_lint_to_files` and before
  `@classmethod def _scope_criteria`. Body verbatim from spec §3 Module 3:
  return `command` unchanged when `files` is empty; otherwise substitute the
  first `_RUFF_CHECK_RE` match with `python -m scripts.sdd.lint_new <shlex-quoted files>`.
- In `_run_deterministic_qa`, replace
  `lint_cmd = self._scope_lint_to_files(self._lint_command, changed)` with
  `lint_cmd = self._scope_lint_to_files(self._baseline_aware_lint(self._lint_command, changed), changed)`.
  Ordering matters: `_baseline_aware_lint` runs first so the `ruff check .`
  target is gone before `_scope_lint_to_files` looks for a `.`; what it then
  scopes is the bare `mypy --no-incremental`, exactly as today.
- Write the three §4 unit tests for Module 3.
- Run the spec §5 end-to-end check: `ruff check` on the touched files reports
  no new findings relative to the parent commit — verify with the new script
  itself (`python -m scripts.sdd.lint_new packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`).

**NOT in scope**:
- Any change to `scripts/sdd/lint_new.py` (TASK-2736) — if the script needs a
  fix, note it in the Completion Note and coordinate; do not fork the script.
- Any change to `_scope_lint_to_files` — it stays as-is and still handles
  the `mypy` half.
- Anything in `_run_finding_triage` (TASK-2735).
- Making `mypy` diff-aware.
- A new configuration knob (G5) — the rewrite is unconditional.
- Changing `_DEFAULT_LINT_COMMAND` — it stays `"ruff check . && mypy --no-incremental"`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | Add `_RUFF_CHECK_RE`, `_baseline_aware_lint`; one-line change at the `lint_cmd =` site |
| `packages/ai-parrot/tests/flows/dev_loop/test_qa_lint_scoping.py` | CREATE | Unit tests for `_baseline_aware_lint` composed with `_scope_lint_to_files` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (verified 2026-09-02 on `dev` @ `565e96561`). Line numbers are pre-TASK-2735;
> if TASK-2735 has landed in this worktree first, `_run_deterministic_qa` and
> `_scope_lint_to_files` are unchanged but everything after `_get_changed_files`
> shifts down by the two helpers it added — re-`grep` before editing.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py — ALL already present, do NOT re-add:
import re                                                     # qa.py:24
import shlex                                                  # qa.py:25
from typing import Any, Dict, List, Optional, Tuple, Union    # qa.py:27 (TASK-2735 adds FrozenSet)

# For the tests:
import pytest
from parrot.flows.dev_loop.nodes.qa import QANode            # verified: test_qa_triage.py:18
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
_DEFAULT_LINT_COMMAND = "ruff check . && mypy --no-incremental"        # line 56

# Matches a positional ``.`` target in lint commands (e.g. ``ruff check .``).
_LINT_TARGET_RE = re.compile(r"(?<=\s)\." r"(?=\s|&&|;|$)")           # line 65  ← put _RUFF_CHECK_RE right after this

class QANode(DevLoopNode):
    def __init__(self, *, dispatcher, ..., lint_command: Optional[str] = None)          # line 133-137
        object.__setattr__(self, "_lint_command", lint_command or _DEFAULT_LINT_COMMAND)  # line 145

    async def _run_deterministic_qa(
        self, shared, research, brief, executable, *, cwd_override=None,
    ) -> QAReport:                                                       # line 425
        changed = await self._get_changed_files(effective_cwd)           # line 460
        lint_cmd = self._scope_lint_to_files(self._lint_command, changed)   # line 461 ← THE ONLY LINE TO EDIT HERE
        scoped_criteria = self._scope_criteria(executable, changed)      # line 462
        # ... _QABrief(lint_command=lint_cmd, ...)                        # line 466

    @staticmethod
    def _scope_lint_to_files(command: str, files: List[str]) -> str:     # line 710-730 — UNCHANGED
        # Splits on (&&|;), replaces a `.` target with shlex-quoted files, and appends
        # files to a bare `mypy` part that has no positional target. Returns `command`
        # unchanged when `files` is empty.  Body ends at line 730.

    @classmethod
    def _scope_criteria(cls, criteria, files) -> List[AcceptanceCriterion]:   # line 732-733 ← new classmethod goes BEFORE this

# `_QABrief.lint_command: str`                                          # line 96 — receives lint_cmd unchanged
```

`shlex.quote` is what `_scope_lint_to_files` already uses to build
`file_args` (`qa.py:722`); `_baseline_aware_lint` uses the same call.

### Does NOT Exist
- ~~`QANode._scope_ruff_to_diff`~~ / ~~`_diff_scoped_lint`~~ — the method name is
  `_baseline_aware_lint`; use it.
- ~~`scripts/sdd/lint_diff.py`~~ — wrong name; the script is
  `scripts/sdd/lint_new.py`, invoked as `python -m scripts.sdd.lint_new`.
- ~~`from scripts.sdd import lint_new` inside `qa.py`~~ — do NOT import the
  script into the node; the node only builds a shell command string that the
  `sdd-qa` subagent runs with the worktree as cwd.
- ~~`_LINT_TARGET_RE` handling `ruff`~~ — it only matches a positional `.`; the
  new `_RUFF_CHECK_RE` is a separate pattern.
- ~~`conf.DEV_LOOP_LINT_BASELINE`~~ / ~~`lint_baseline: bool` on `QANode.__init__`~~ —
  G5: no new knob or constructor argument.
- ~~`ruff check --diff-only`~~ — no such flag; the script does the filtering.

---

## Implementation Notes

### Pattern to Follow
The spec §3 Module 3 code block is the implementation. Copy it. The
substitution uses `_RUFF_CHECK_RE.sub(lambda _match: replacement, command, count=1)`
— the lambda avoids `re` interpreting backslashes in file paths as group
references.

### Why the ordering `_scope_lint_to_files(_baseline_aware_lint(...), ...)`
`"ruff check . && mypy --no-incremental"` with `files=["a.py"]`:
1. `_baseline_aware_lint` → `"python -m scripts.sdd.lint_new a.py && mypy --no-incremental"`
2. `_scope_lint_to_files` finds no `.` target (the `-m` flag is preceded by
   a space but followed by `m`, not whitespace — `_LINT_TARGET_RE` requires
   whitespace/`&&`/`;`/EOL after the dot, so `scripts.sdd.lint_new` is safe)
   and appends files to the bare `mypy` part →
   `"python -m scripts.sdd.lint_new a.py && mypy --no-incremental a.py"`.

Assert exactly that string in `test_ruff_half_is_replaced_mypy_half_scoped`.
Confirm step 2 by actually running the composed call in the test rather
than reasoning about the regex.

### Key Constraints
- Google-style docstring + strict type hints on `_baseline_aware_lint` (the
  spec text already provides them).
- No new dependency, no new config, no constructor change.
- `_DEFAULT_LINT_COMMAND` unchanged.
- The `sdd-qa` subagent runs the command with the worktree as cwd, which is
  the repo root of that worktree, so `python -m scripts.sdd.lint_new`
  resolves there without any path munging in the node.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:710-730` — `_scope_lint_to_files`, the sibling scoping helper and the `shlex.quote` pattern.
- `packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py` — tests that patch `QANode._get_changed_files` with `AsyncMock`, useful if you add an execute-level check that `_QABrief.lint_command` carries the rewritten string.
- `sdd/specs/qa-gate-evidence-and-diff-scoped-lint.spec.md` §2 Component Diagram — the intended command flow.

---

## Acceptance Criteria

- [ ] `_RUFF_CHECK_RE` and `QANode._baseline_aware_lint` exist as specified; `_scope_lint_to_files` is byte-for-byte unchanged.
- [ ] `_run_deterministic_qa` composes `_scope_lint_to_files(_baseline_aware_lint(self._lint_command, changed), changed)`.
- [ ] `"ruff check . && mypy --no-incremental"` + `["a.py"]` → `"python -m scripts.sdd.lint_new a.py && mypy --no-incremental a.py"`.
- [ ] `"mypy --no-incremental"` + `["a.py"]` → only the mypy scoping applies (`"mypy --no-incremental a.py"`).
- [ ] `files=[]` → the command string is returned identical.
- [ ] No new entry in `packages/ai-parrot/src/parrot/conf.py`; `QANode.__init__` signature unchanged.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop -v`.
- [ ] `python -m scripts.sdd.lint_new packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` exits 0 from the worktree root (no new ruff findings introduced by this branch).
- [ ] Spec §5 full suite: `pytest packages/ai-parrot/tests/flows/dev_loop tests/sdd_scripts -v` passes.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_qa_lint_scoping.py
from __future__ import annotations

from parrot.flows.dev_loop.nodes.qa import QANode


def _compose(command: str, files: list[str]) -> str:
    """Exactly what _run_deterministic_qa does at the lint_cmd = ... site."""
    return QANode._scope_lint_to_files(QANode._baseline_aware_lint(command, files), files)


def test_ruff_half_is_replaced_mypy_half_scoped():
    assert _compose("ruff check . && mypy --no-incremental", ["a.py"]) == (
        "python -m scripts.sdd.lint_new a.py && mypy --no-incremental a.py"
    )


def test_command_without_ruff_is_untouched():
    assert _compose("mypy --no-incremental", ["a.py"]) == "mypy --no-incremental a.py"


def test_no_changed_files_leaves_command_unchanged():
    cmd = "ruff check . && mypy --no-incremental"
    assert QANode._baseline_aware_lint(cmd, []) == cmd
    assert _compose(cmd, []) == cmd


def test_paths_are_shell_quoted():
    out = QANode._baseline_aware_lint("ruff check .", ["dir with space/a.py"])
    assert out == "python -m scripts.sdd.lint_new 'dir with space/a.py'"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context — §3 Module 3 is the implementation.
2. **Check dependencies** — verify TASK-2736 is in `sdd/tasks/completed/` and `scripts/sdd/lint_new.py` exists in this worktree.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Re-`grep` the line anchors (`_LINT_TARGET_RE`, `def _scope_lint_to_files`, `def _scope_criteria`, `lint_cmd = self._scope_lint_to_files`) — TASK-2735 may have shifted them
   - Confirm every import in "Verified Imports" still exists
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/qa-gate-evidence-and-diff-scoped-lint.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2737-wire-diff-scoped-lint-into-qa.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
