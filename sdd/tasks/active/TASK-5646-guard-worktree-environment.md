# TASK-5646: Procedure check in the worktree guard

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5638
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (second guard). Launched Claude workers do not run the dangerous-actions guard;
their pre-tool hook is `worktree_environment --hook`. This task calls the same
`procedure_advice.evaluate_command` from `hook_response`, and protects `procedure_advice.py` as a
control file of the native sandbox so a worker cannot edit the policy it is checked by.

---

## Scope

- Add `_load_procedure_advice()` to `worktree_environment.py` and apply the advice in
  `hook_response` for Bash payloads that were not already denied.
- Add `procedure_advice.py` to `native_claude_sandbox._control_files`.
- Create `tests/sdd/test_procedure_guards.py`.

**NOT in scope**: the dangerous-actions guard (TASK-5645); the wrapping/sandbox logic itself; the
end-to-end pilot test (TASK-5651, which extends the test file created here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | Load and apply the advice in `hook_response` |
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | Protect `procedure_advice.py` |
| `packages/ai-parrot/tests/sdd/test_procedure_guards.py` | CREATE | Worktree-guard tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). `procedure_advice` comes from TASK-5637 / TASK-5638.

### Verified Imports
```python
from parrot.sdd.scripts import worktree_environment, native_claude_sandbox   # the real modules (tests import these)
# (packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py imports the dev_loop shim
#  `parrot.flows.dev_loop.worktree_environment` as `policy`; read that file for fixture patterns.)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py
def _load_native_sandbox() -> Any:                                   # :603 — the loading pattern to copy
    if __package__:
        from . import native_claude_sandbox
    else:  # run as a script: this file's directory is sys.path[0]
        sys.modules.setdefault("worktree_environment", sys.modules[__name__])
        import native_claude_sandbox
    return native_claude_sandbox                                     # :615
BACKENDS = ("auto", "bubblewrap", "claude-native")                   # :622
def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]:   # :1026
    cwd = Path(payload["cwd"])                                       # :1042
    tool_input = payload["tool_input"]                               # :1043
    output: dict[str, Any] = {"hookEventName": "PreToolUse"}         # :1044
    try:
        ...
        if payload["tool_name"] == "Bash":                           # :1049
            command = tool_input["command"]
            ...
                    output["updatedInput"] = {**tool_input, "command": wrapped}   # :1064
        ...
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        output.update(permissionDecision="deny", permissionDecisionReason=str(exc))   # :1074
    return {"hookSpecificOutput": output}                            # :1075

# packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py
def _control_files(root: Path) -> list[Path]:                        # :209
    names = ("native_claude_sandbox.py", "worktree_environment.py")  # :218

# packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py  (TASK-5638)
class Advice: decision: Literal["none", "advise", "deny"]; text: str
def evaluate_command(command: str, cwd: Path, *, env: Mapping[str, str] | None = None) -> Advice   # never raises
```

### Does NOT Exist
- ~~Procedure logic in `worktree_environment.py`~~ — only loading and rendering.
- ~~A module-level import of `procedure_advice`~~ — load it lazily through `_load_procedure_advice`.
- ~~`.claude/settings.json` in a worktree~~ — the file is not tracked; nothing here writes settings.
- ~~A worker-sandbox flag other than the launcher markers~~ — not needed by this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_procedure_guards.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#hook_response",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#_load_native_sandbox",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_control_files"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- The check uses the **original** command (`tool_input["command"]`), never the wrapped one in
  `output["updatedInput"]`.
- Rendering:

  | State of `output` | Advice | Effect |
  |---|---|---|
  | has `permissionDecision` (already denied) | (not evaluated) | unchanged |
  | no decision | `deny` | set `permissionDecision="deny"`, `permissionDecisionReason=<text>`; remove `updatedInput` |
  | no decision | `advise` | set `additionalContext=<text>`; keep `updatedInput` |
  | no decision | `none` / error | unchanged |

- Any exception from the procedure check is swallowed; it must never turn into a denial.
- FEAT-887 (not merged) also edits `_control_files`; if it landed first, append to its tuple
  instead of replacing it.
- To get an `updatedInput` in a test without a real sandbox, read how
  `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` builds its `checkout`
  fixture (lines 40-56) and which backend its `hook_response` tests use; reuse that setup. If no
  backend rewrites the command on the test host, assert the "keeps `updatedInput`" property by
  monkeypatching the wrapper function instead of skipping the test.
- Fixtures are local to the test file (no `conftest.py`).

---

## Implementation Blueprint

### Steps (in order)
1. Add `_load_procedure_advice` next to `_load_native_sandbox` — *why*: the module runs both as a
   package member and as a script; the existing loader shows the two import forms.
2. Add `_apply_procedure_advice` and call it before the final `return` of `hook_response` — *why*:
   all wrapping decisions are final at that point.
3. Extend `_control_files`.
4. Write the tests.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    return native_claude_sandbox' packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py)
# AFTER — insert below `    return native_claude_sandbox` (verified: packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:615),
# i.e. right after the end of `_load_native_sandbox` (verified: :603), with two blank lines around it.
def _load_procedure_advice() -> Any:
    """Return the sibling ``procedure_advice`` module (FEAT-891), package or script mode."""
    if __package__:
        from . import procedure_advice
    else:  # run as a script: this file's directory is sys.path[0]
        import procedure_advice
    return procedure_advice


def _apply_procedure_advice(output: dict[str, Any], payload: dict[str, Any]) -> None:
    """Add the procedure advice for a Bash payload to ``output`` in place; never raises."""
    if "permissionDecision" in output or payload.get("tool_name") != "Bash":
        return
    try:
        command = payload["tool_input"]["command"]
        advice = _load_procedure_advice().evaluate_command(command, Path(payload["cwd"]))
    except Exception:  # noqa: BLE001 — the procedure check never breaks the guard
        return
    if advice.decision == "deny":
        output.pop("updatedInput", None)
        output.update(permissionDecision="deny", permissionDecisionReason=advice.text)
    elif advice.decision == "advise":
        output["additionalContext"] = advice.text


# occurrences: 1 (verified: grep -c '    return {"hookSpecificOutput": output}' packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py)
# BEFORE — insert above `    return {"hookSpecificOutput": output}` (verified: packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:1075),
# at the same indentation (function body level, outside the try/except):
    _apply_procedure_advice(output, payload)
```
**Why**: the helper owns the rendering table; `hook_response` gains one line. A denial drops the
pending rewrite so a denied command is never also rewritten.

### `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    names = ("native_claude_sandbox.py", "worktree_environment.py")' packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py)
# REPLACE the line (verified: packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:218) with:
    names = ("native_claude_sandbox.py", "worktree_environment.py", "procedure_advice.py")
```
**Why**: the guard's policy module must be as write-protected as the guard itself.

### `packages/ai-parrot/tests/sdd/test_procedure_guards.py` (CREATE)
```python
"""Tests for the procedure check inside the SDD pre-tool guards (FEAT-891)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from parrot.sdd.scripts import native_claude_sandbox, worktree_environment


def _plane_repo(tmp_path: Path) -> Path:
    """A repo (.git/HEAD on feat-FEAT-1-demo) with sdd/procedures/x.yaml, a per-spec index (TASK-1 pending)
    and a hand-written .parrot/procedure/procedures.json: `sdd:task-close` mandatory with a `git mv` bypass
    guard on sdd/tasks/active/*, and `sdd:push` advisory with an entry guard on `git push` whose
    precondition is env.not_worker_sandbox."""
    # FILL IN: write every file by hand (json.dumps, hashlib.sha1 for the source digest); return the root.


def _payload(root: Path, command: str) -> dict:
    return {"cwd": str(root), "tool_name": "Bash", "tool_input": {"command": command}}


def test_worktree_guard_deny_and_advise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A deny drops `updatedInput`; an advise keeps the wrapper and adds `additionalContext`."""
    # FILL IN: per Implementation Notes (backend choice / monkeypatched wrapper). Deny case: the bypass command.
    # Advise case: `git push` with a launcher marker in the environment (monkeypatch.setenv).


def test_worktree_guard_unchanged_without_plane(tmp_path: Path) -> None:
    """With no index the response equals the response computed before this feature (no extra keys)."""
    # FILL IN: compare hook_response(...) for a repo without a plane against the same call with
    # `_apply_procedure_advice` monkeypatched to a no-op.


def test_worktree_guard_existing_deny_wins(tmp_path: Path) -> None:
    """A payload the guard already denies keeps its own reason and gets no procedure text."""
    # FILL IN: an unknown backend ("nope") is denied by hook_response itself.


def test_worktree_guard_swallows_advice_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An exception inside the procedure check never becomes a denial."""
    # FILL IN: monkeypatch worktree_environment._load_procedure_advice to raise.


def test_control_files_include_advice(tmp_path: Path) -> None:
    """procedure_advice.py is protected next to the guard files."""
    names = {path.name for path in native_claude_sandbox._control_files(tmp_path)}
    assert {"native_claude_sandbox.py", "worktree_environment.py", "procedure_advice.py"} <= names
```

### FILL IN checklist
- [ ] `test_procedure_guards.py` — `_plane_repo` and four test bodies
- [ ] Run `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q` once (acceptance): no existing guard test may change

---

## Acceptance Criteria

- [ ] A procedure denial sets `permissionDecision="deny"` and removes `updatedInput`.
- [ ] An advisory adds `additionalContext` and leaves `updatedInput` untouched.
- [ ] With no plane or on any error, `hook_response` returns exactly what it returns today.
- [ ] A denial raised by the guard itself is unchanged.
- [ ] `procedure_advice.py` is in `_control_files`.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_procedure_guards.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5638 is `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5646 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
