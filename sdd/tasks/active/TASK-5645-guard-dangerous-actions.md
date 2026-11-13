# TASK-5645: Procedure check in the dangerous-actions guard

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5638
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (first guard) and goal G8: no new hook registration. `dangerous_actions.main`
already runs before every Bash call in interactive Claude Code sessions (when registered by
`parrot sdd install`). After its own verdict, it now asks `procedure_advice.evaluate_command` and
renders the answer. The guard adds no decision logic of its own.

---

## Scope

- Add `_procedure_advice(payload)` to `dangerous_actions.py` and call it from `main` after the
  existing verdict.
- Render: a procedure denial as a `PreToolUse` deny; an advisory as `additionalContext`.
- Add tests to the existing `tests/sdd/test_dangerous_actions.py`.

**NOT in scope**: the worktree guard (TASK-5646); any change to `evaluate`, `_bash`, `_render` or
the existing rules; `.claude/settings.json` (untracked; the switch to this guard in ai-parrot is an
operator step documented by TASK-5652).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` | MODIFY | Call the procedure check after the verdict |
| `packages/ai-parrot/tests/sdd/test_dangerous_actions.py` | MODIFY | Four new tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). `procedure_advice` comes from TASK-5637 / TASK-5638.

### Verified Imports
```python
import importlib      # add to the stdlib imports of dangerous_actions.py (the module imports argparse, fnmatch, json, os, re, sys at :16-:21)
from parrot.sdd.scripts.dangerous_actions import evaluate, protected_branches   # test file line 14 (existing)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py   (stdlib only; no parrot import at module level)
@dataclass(frozen=True)
class Verdict: decision: Literal["allow", "deny", "warn"]; reason: str = ""      # :35
def find_root(cwd: str | Path | None) -> Path | None: ...                         # :58
def evaluate(payload: dict[str, Any], *, root: Path | None) -> Verdict: ...       # :403
def _render(verdict: Verdict) -> dict[str, Any]: ...                              # :422  deny -> hookSpecificOutput; warn -> {"systemMessage"}; allow -> {}
def main(argv: Sequence[str] | None = None) -> None:                              # :436
    ...
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
        root = find_root(payload.get("cwd") or os.getcwd())
        result = _render(evaluate(payload, root=root))                            # :446
    except Exception as exc:  # noqa: BLE001 — documented fail-open, now visible
        result = {"systemMessage": f"dangerous-actions guard: checks skipped (...)"}
    sys.stdout.write(json.dumps(result) + "\n")

# packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py  (TASK-5638)
@dataclass(frozen=True)
class Advice: decision: Literal["none", "advise", "deny"]; text: str = ""
def evaluate_command(command: str, cwd: Path, *, env: Mapping[str, str] | None = None) -> Advice   # never raises

# packages/ai-parrot/tests/sdd/test_dangerous_actions.py  (helpers to reuse)
def _bash(cmd: str) -> dict: ...                                                  # :19  a Bash payload
def _clean_env() -> dict[str, str]: ...                                           # :221
def _run_hook(stdin: str) -> subprocess.CompletedProcess[str]: ...                # :225 runs `python -m parrot.sdd.scripts.dangerous_actions --hook`
def test_hook_main_does_not_import_parrot_cli() -> None: ...                      # :256 — must keep passing
```

### Does NOT Exist
- ~~A module-level import of `procedure_advice`~~ — import it lazily inside `_procedure_advice`,
  guarded; a hook runs on every tool call.
- ~~Procedure logic in this file~~ — the decision table lives in `evaluate_command` only.
- ~~`updatedInput` in this guard's output~~ — never emitted here.
- ~~The dangerous-actions guard in launched workers, codex or agy~~ — workers run
  `worktree_environment --hook`; codex and agy run other programs.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_dangerous_actions.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py#main",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py#evaluate",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py#_render",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py#Verdict"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- Rendering rules (spec §3 M8):

  | Existing verdict | Procedure advice | Output |
  |---|---|---|
  | `deny` | (not evaluated) | unchanged |
  | `allow` / `warn` | `deny` | `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": <text>}}` |
  | `allow` / `warn` | `advise` | `_render(verdict)` plus `"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": <text>}` |
  | `allow` / `warn` | `none` or `None` | `_render(verdict)` — byte-identical to today |

- With `PARROT_ALLOW_DANGEROUS=1`, `evaluate` returns allow and `evaluate_command` itself
  downgrades a denial to an advisory; this guard needs no extra branch for it.
- Tests that need a plane write a small `procedures.json` by hand under
  `<repo>/.parrot/procedure/` (shape in spec §2 "Compiled index") with a matching `sources` entry;
  they do not depend on the index writer.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_procedure_advice` above `main` — *why*: lazy, guarded import keeps the hook's import cost
   unchanged for non-Bash tools.
2. Replace the single `result = …` line in `main` — *why*: it is the only place the verdict is
   rendered.
3. Add the tests.

### `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` (MODIFY)
```python
# Add `import importlib` to the stdlib import block (alphabetical: after `import fnmatch`).

# occurrences: 1 (verified: grep -c 'def main(argv: Sequence\[str\] | None = None) -> None:' packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py)
# BEFORE — insert above `def main(argv: Sequence[str] | None = None) -> None:` (verified: packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:436)
def _procedure_advice(payload: dict[str, Any]) -> Any | None:
    """Advice for a Bash payload, or None for other tools or on any failure (lazy, guarded import
    of parrot.sdd.scripts.procedure_advice)."""
    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return None
    try:
        module = importlib.import_module("parrot.sdd.scripts.procedure_advice")
        return module.evaluate_command(command, Path(payload.get("cwd") or os.getcwd()))
    except Exception:  # noqa: BLE001 — the procedure check never breaks the guard
        return None


def _with_procedure(verdict: Verdict, advice: Any | None) -> dict[str, Any]:
    """Render ``verdict``, then add the procedure advice (see the task's rendering table)."""
    result = _render(verdict)
    if verdict.decision == "deny" or advice is None:
        return result
    if advice.decision == "deny":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": advice.text,
            }
        }
    if advice.decision == "advise":
        result["hookSpecificOutput"] = {"hookEventName": "PreToolUse", "additionalContext": advice.text}
    return result


# occurrences: 1 (verified: grep -c '        result = _render(evaluate(payload, root=root))' packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py)
# REPLACE the line `        result = _render(evaluate(payload, root=root))` (verified: packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py:446) with:
        verdict = evaluate(payload, root=root)
        advice = None if verdict.decision == "deny" else _procedure_advice(payload)
        result = _with_procedure(verdict, advice)
```
**Why**: an existing denial wins and skips the procedure check entirely, so a destructive command
never carries procedure text. `_render` itself is untouched, which keeps the "no plane" output
byte-identical.

### `packages/ai-parrot/tests/sdd/test_dangerous_actions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_hook_main_does_not_import_parrot_cli() -> None:' packages/ai-parrot/tests/sdd/test_dangerous_actions.py)
# AFTER — insert below the body of `test_hook_main_does_not_import_parrot_cli` (verified: packages/ai-parrot/tests/sdd/test_dangerous_actions.py:256),
# before the `_bash_hook` helper. Reuse `_bash`, `_clean_env` and the `python -m … --hook` pattern of `_run_hook`,
# adding "cwd" to the payload and `cwd=`/`env=` to subprocess.run.

def _plane_repo(tmp_path: Path) -> Path:
    """A repo (.git/HEAD on feat-FEAT-1-demo) with sdd/procedures/x.yaml and a hand-written procedures.json
    holding one mandatory node `sdd:task-close` with a `git mv` bypass guard on sdd/tasks/active/* and
    `use_instead` naming `parrot sdd task close`."""
    # FILL IN


def test_dangerous_guard_unchanged_without_plane(tmp_path: Path) -> None:
    """With no index, the output for an allowed and for a denied command is byte-identical to today's."""
    # FILL IN: a repo with .git only; `ls` -> "{}\n"; `git reset --hard` -> the existing deny JSON.


def test_dangerous_guard_denies_bypass(tmp_path: Path) -> None:
    """`git mv sdd/tasks/active/TASK-1-x.md …` is denied and the reason names the script."""
    # FILL IN: permissionDecision == "deny" and "parrot sdd task close" in permissionDecisionReason.


def test_dangerous_guard_existing_deny_wins(tmp_path: Path) -> None:
    """A destructive command is denied by the original rule and carries no procedure text."""
    # FILL IN: `git reset --hard && git mv sdd/tasks/active/TASK-1-x.md y` -> reason starts with "BLOCKED:".


def test_dangerous_guard_escape_turns_deny_into_context(tmp_path: Path) -> None:
    """With PARROT_ALLOW_PROCEDURE=1 the bypass is not denied; the text arrives as additionalContext."""
    # FILL IN
```

### FILL IN checklist
- [ ] `test_dangerous_actions.py` — `_plane_repo` and four test bodies
- [ ] Run the whole file: the existing tests (including `test_hook_main_does_not_import_parrot_cli` and the bash-parity test) must still pass

---

## Acceptance Criteria

- [ ] With no plane, a stale plane, or any internal error, the guard output is exactly what it is today.
- [ ] `mv` / `git mv` of a file under `sdd/tasks/active/` is denied with a reason naming `parrot sdd task close`.
- [ ] A denial issued by an existing rule is unchanged and carries no procedure text.
- [ ] An advisory is delivered as `hookSpecificOutput.additionalContext`; `updatedInput` is never emitted.
- [ ] `procedure_advice` is imported only inside `_procedure_advice`.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_dangerous_actions.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5638 is `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5645 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
