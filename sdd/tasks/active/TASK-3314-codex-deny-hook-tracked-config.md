# TASK-3314: Codex deny hook — tracked `.codex/hooks.json`, portable launcher, no `--ignore-user-config` for dev dispatches

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3309
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, AC6, risks R3 / R3b, spike S1. Codex executes its own shell
commands, so the pytest argv cannot be rewritten in Python; the only lever is a
codex PreToolUse hook that **denies** an over-broad pytest and returns the exact
scoped command as the reason.

Today that hook cannot fire inside codex attempt sub-worktrees:
- `.codex/hooks.json` is git-ignored (`.gitignore:363` `.codex/*`, only
  `.codex/agents/*.toml` is re-included), so worktrees do not carry it; the local
  copy in the main checkout hard-codes `/home/jesuslara/proyectos/ai-parrot/.venv/bin/python`.
- `CodexCodeDispatchProfile.ignore_user_config` defaults to `True`
  (`models/codex.py:23-29`), so `--ignore-user-config` is appended
  (`dispatchers/codex.py:379-380`, `:442-443`) for every dispatch.

Decisions recorded in the spec (§8, resolved by Jesus Lara): track
`.codex/hooks.json` with a **portable launcher**, and stop passing
`--ignore-user-config` for **development** dispatches; the review profiles keep it
explicitly. `--model`, sandbox and approval policy are already explicit flags, so
operator config cannot swap them (R3b).

The attempt context that activates the guard is written by the engine for every
`_run_attempt` (TASK-3312), including codex seats; this task only reads it (through
the kernel's `guard_bash`).

---

## Scope

- Add `evaluate_scope(command, cwd)` to `parrot_tools/tool_optimizations/hooks.py`: load the stdlib kernel **by path** as top-level `test_scope` (from `<repo root>/packages/ai-parrot/src/parrot/flows/dev_loop`), call `guard_bash`; `rewrite` or `block` → `GuardDecision(deny=True, reason=<scoped command / guard message>)`; anything else, missing kernel or any exception → `None`.
- In `main()`'s Bash branch, call `evaluate_scope` first and fall back to `evaluate_shell` when it returns `None`.
- Keep `hooks.py` dependency-light (no pydantic/parrot at import time — existing test `test_hook_import_is_dependency_light`).
- `.gitignore`: add `!.codex/hooks.json` after `!.codex/agents/*.toml`.
- Create tracked `.codex/hooks.json` whose Bash hook command is `sh scripts/sdd/codex_hook.sh` (no absolute user path).
- Create `scripts/sdd/codex_hook.sh`: resolve the main checkout via `git rev-parse --path-format=absolute --git-common-dir`, exec `<main>/.venv/bin/python -m parrot_tools.tool_optimizations.hooks --host codex`; missing git/venv → exit 0 silently.
- `models/codex.py`: `CodexCodeDispatchProfile.ignore_user_config` default → `False` (field kept); `CodexCodeReviewProfile` and `CodexAdversarialReviewProfile` declare `ignore_user_config: bool = True` explicitly.
- Update tests: `test_codex_dispatcher.py:177` (flag absent for dev dispatch), `test_models.py:150` (`is False` + review profiles `is True`), `test_codex_command_variants.py:74` (comment: explicit True on review profile); add hook tests.
- Spike S1: run a real `codex exec --cd <attempt sub-worktree>` (without `--ignore-user-config`) issuing `pytest packages/ai-parrot/tests`; record whether the tracked project hook fired and denied, plus any feature flag codex needed, in `artifacts/logs/feat-563-s1-codex-hook.md`.

**NOT in scope**: the kernel (TASK-3309); writing the attempt context (TASK-3312); `/sdd-spec` §3b design-research `--ignore-user-config` (unchanged — spec non-goal); `.codex/config.toml` (stays ignored/local); the Claude host path of `hooks.py` beyond sharing `main()`.

> Note: `.codex/hooks.json` already exists **untracked** in the main checkout (git-ignored, machine-specific path). Do NOT modify that local file from the main checkout; this task CREATES the tracked, portable version inside the feature worktree. Once merged, `git` will show the tracked file replacing the local one.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py` | MODIFY | `evaluate_scope` + Bash-branch wiring |
| `.gitignore` | MODIFY | re-include `.codex/hooks.json` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py` | MODIFY | dev default `ignore_user_config=False`; review profiles explicit `True` |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py` | MODIFY | scope-deny tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py` | MODIFY | dev dispatch has no `--ignore-user-config` |
| `packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py` | MODIFY | comment/assertion for explicit review default |
| `packages/ai-parrot/tests/flows/dev_loop/test_models.py` | MODIFY | profile defaults |
| `.codex/hooks.json` | CREATE | tracked, portable codex hook config |
| `scripts/sdd/codex_hook.sh` | CREATE | launcher resolving the main checkout venv |
| `artifacts/logs/feat-563-s1-codex-hook.md` | CREATE | spike S1 evidence |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# hooks.py — stdlib only, already present (L30-39)
import argparse, json, os, re, shlex, stat, sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# tests — already present
from parrot_tools.tool_optimizations.hooks import (GuardPolicy, build_reason, count_lines_bounded, coverage_matrix,
                                                   evaluate_shell, main, parse_shell_subset)  # verified: test_hooks.py:11-19
from parrot.flows.dev_loop.models import CodexCodeDispatchProfile  # used by test_models.py / test_codex_dispatcher.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py
@dataclass(frozen=True)
class GuardPolicy:  # L69-70 — load(cls, root: Path) (L86)
@dataclass
class GuardDecision:  # L110-111 — deny: bool=False, reason: str="", path=None, lines=None, size=None, coverage: str="not_applicable"
def evaluate_shell(command: str, cwd: Path, policy: GuardPolicy) -> GuardDecision:  # L400
DENY_VALUE = {"claude": "deny", "codex": "deny"}  # L466
def render_output(decision: Optional[GuardDecision], host: str) -> Optional[str]:  # L469 — prints only when decision.deny
def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:  # L535 — --host {claude,codex}
def main(argv=None, stdin=None, stdout=None) -> int:  # L549 — always returns 0, swallows exceptions
        cwd = Path(payload.get("cwd") or os.getcwd())  # L569
        elif tool_name == "Bash":                        # L577
            decision = evaluate_shell(str(tool_input.get("command", "")), cwd, policy)  # L578

# packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py
class CodexCodeDispatchProfile(BaseModel):  # L10
    ignore_user_config: bool = Field(default=True, description=...)  # L23-29
class CodexCodeReviewProfile(CodexCodeDispatchProfile):  # L40 — last field timeout_seconds (L52)
class CodexAdversarialReviewProfile(CodexCodeDispatchProfile):  # L55 — last field timeout_seconds default=600 (L78)

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py
class CodexCodeDispatcher:  # L136
    def _build_command(self, *, profile, cwd, schema_path, output_path, prompt) -> List[str]:  # L341
        if profile.ignore_user_config: cmd.append("--ignore-user-config")  # L379-380
    def _build_adversarial_review_command(...):  # L405
        cmd += ["--model", profile.model]  # L432
        if profile.ignore_user_config: cmd.append("--ignore-user-config")  # L442-443

# tests
# test_hooks.py
def _run(payload, *, host="claude", cwd=None): ...  # L32 — drives main()
def _bash_payload(command): ...  # L47
def test_hook_import_is_dependency_light(): ...  # L246 — hooks import must not pull pydantic/parrot
# test_codex_dispatcher.py:177   assert "--ignore-user-config" in command     (CodexCodeDispatchProfile(model="gpt-5.5"))
# test_codex_command_variants.py:74   assert "--ignore-user-config" in cmd  # default True on the base profile  (CodexAdversarialReviewProfile())
# test_models.py:150   assert profile.ignore_user_config is True     (CodexCodeDispatchProfile())
```

### Existing configuration
```text
# .gitignore:363-366
.codex/*
!.codex/
!.codex/agents/
!.codex/agents/*.toml
```
Local (untracked) `.codex/hooks.json` today:
`{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/home/jesuslara/proyectos/ai-parrot/.venv/bin/python -m parrot_tools.tool_optimizations.hooks --host codex", "timeout": 10}]}]}}`

### Created by dependency tasks (verify they exist before starting)
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py  (TASK-3309) — stdlib only
@dataclass(frozen=True)
class GuardOutcome:
    action: str                          # "allow" | "rewrite" | "block"
    argvs: tuple[tuple[str, ...], ...]
    message: str
def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]: ...
# guard is inactive (action "allow") when test_scope.context.read_attempt_context(worktree) is None  (TASK-3306)
```

### Does NOT Exist
- ~~`CodexCodeDispatchProfile.allowed_commands`~~ — codex has no argv allow-list; no interception point in Python
- ~~a tracked `.codex/hooks.json`~~ / ~~`scripts/sdd/codex_hook.sh`~~ — created by this task
- ~~`import parrot.flows.dev_loop.test_scope` inside `hooks.py`~~ — forbidden (pulls `parrot`, breaks `test_hook_import_is_dependency_light`); load by path as top-level `test_scope`
- ~~a codex `-c hooks=...` override in `CodexCodeDispatcher`~~ — not used; the tracked project file is the chosen mechanism
- ~~changes to `_build_command` / `_build_adversarial_review_command`~~ — they already honour the field; only defaults change

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py", "action": "MODIFY"},
    {"path": ".gitignore", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_models.py", "action": "MODIFY"},
    {"path": ".codex/hooks.json", "action": "CREATE"},
    {"path": "scripts/sdd/codex_hook.sh", "action": "CREATE"},
    {"path": "artifacts/logs/feat-563-s1-codex-hook.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py#main",
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py#evaluate_shell",
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py#GuardDecision",
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py#render_output",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py#CodexCodeDispatchProfile",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py#CodexCodeReviewProfile",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py#CodexAdversarialReviewProfile",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#CodexCodeDispatcher._build_command"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# hooks.py never breaks the host: main() swallows everything and always returns 0 (hooks.py:549-583).
# evaluate_scope follows the same rule: any failure → None (no decision), never an exception.
```

### Key Constraints
- `hooks.py` stays stdlib-only at import time. Import the kernel lazily inside `evaluate_scope` after inserting `<root>/packages/ai-parrot/src/parrot/flows/dev_loop` into `sys.path` (only if that directory contains `test_scope/`).
- Repo root = `git -C <cwd> rev-parse --show-toplevel` (the attempt sub-worktree root — it carries the feature branch's kernel). Use `subprocess.run(..., capture_output=True, text=True, timeout=5)`; failure → `None`.
- Deny reason must contain the **exact scoped command(s)** (`shlex.join` of each `outcome.argvs` entry, joined by ` && ` or newlines) for `rewrite`, and the guard message for `block` (AC6).
- `coverage` of the returned `GuardDecision`: reuse an existing value (e.g. `"shell"`) unless `coverage_matrix()` / `test_coverage_matrix_is_honest_and_complete` is updated accordingly (FILL IN below).
- Launcher: POSIX `sh`, no bashisms; `exec` so stdin (the hook payload) flows through; always exit 0 when it cannot run.
- Review profiles keep `--ignore-user-config` (reviewers stay isolated); only `CodexCodeDispatchProfile`'s default flips.
- R3b: document nothing here beyond the S1 log — docs are TASK-3319.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py:549-583` — hook entry
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:341-450` — where the flag is emitted (unchanged)

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-3309's `test_scope/guard.py::guard_bash` exists — *why*: `evaluate_scope` is a thin adapter.
2. Add `evaluate_scope` + `_load_scope_guard` to `hooks.py` and wire them into the Bash branch — *why*: codex (and Claude read-guard users) get the deny only inside attempts.
3. Flip the dev profile default and pin review profiles to `True` in `models/codex.py` — *why*: spec decision R3; reviewers stay isolated.
4. Create `scripts/sdd/codex_hook.sh`, tracked `.codex/hooks.json`, and re-include it in `.gitignore` — *why*: every worktree must carry a portable hook.
5. Update the three existing tests and add hook tests — *why*: AC6, AC13.
6. Run spike S1 with a real `codex exec` and write the log — *why*: AC6 requires evidence the tracked hook fires under `--cd <sub-worktree>` without `--ignore-user-config`.

### `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def render_output(decision: Optional\[GuardDecision\], host: str) -> Optional\[str\]:' hooks.py)
# BEFORE — insert immediately above the `DENY_VALUE` comment block preceding `def render_output(...)` (verified: hooks.py:461-469)
#: Repo-relative directory holding the stdlib-only test-scope kernel (FEAT-563).
SCOPE_KERNEL_DIR = Path("packages/ai-parrot/src/parrot/flows/dev_loop")


def _load_scope_guard(cwd: Path) -> tuple[Any, Path] | None:
    """Load ``test_scope.guard.guard_bash`` by path, without importing Parrot.

    Args:
        cwd: The host's working directory (an attempt sub-worktree).

    Returns:
        ``(guard_bash, repo_root)`` or None when git or the kernel is unavailable.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if proc.returncode != 0:
            return None
        root = Path(proc.stdout.strip())
        kernel_dir = root / SCOPE_KERNEL_DIR
        if not (kernel_dir / "test_scope").is_dir():
            return None
        if str(kernel_dir) not in sys.path:
            sys.path.insert(0, str(kernel_dir))
        from test_scope.guard import guard_bash  # noqa: PLC0415 — lazy by design (dependency-light hook)
        return guard_bash, root
    except Exception:  # noqa: BLE001 — never break the host session
        return None


def evaluate_scope(command: str, cwd: Path) -> Optional[GuardDecision]:
    """Deny an over-broad pytest inside an sdd-coder attempt (FEAT-563).

    Args:
        command: The raw shell command.
        cwd: The host's working directory.

    Returns:
        A denying decision whose reason is the scoped command (rewrite) or
        the guard message (block); None when the guard is inactive or fails.
    """
    loaded = _load_scope_guard(cwd)
    if loaded is None:
        return None
    guard_bash, root = loaded
    try:
        outcome, _rewritten = guard_bash(command, worktree=root)
    except Exception:  # noqa: BLE001
        return None
    if outcome.action == "rewrite":
        scoped = " && ".join(shlex.join(argv) for argv in outcome.argvs)
        # FILL IN: final reason wording — must contain `scoped` verbatim and tell the seat to run it instead — AC6
        return GuardDecision(deny=True, reason=f"{outcome.message} Run instead: {scoped}", coverage="shell")
    if outcome.action == "block":
        return GuardDecision(deny=True, reason=outcome.message, coverage="shell")
    return None


```
**Why this shape**: `subprocess` must be added to the stdlib imports at the top (FILL IN checklist); nothing else is imported eagerly, preserving `test_hook_import_is_dependency_light`. The kernel is loaded from the attempt worktree's own checkout, so the guard version matches the branch under test.

```python
# occurrences: 1 (verified: grep -c 'decision = evaluate_shell(str(tool_input.get("command", "")), cwd, policy)' hooks.py)
# REPLACE — the single line `            decision = evaluate_shell(str(tool_input.get("command", "")), cwd, policy)` (verified: hooks.py:578)
            command = str(tool_input.get("command", ""))
            decision = evaluate_scope(command, cwd) or evaluate_shell(command, cwd, policy)
```
**Why**: scope denial takes precedence; otherwise the existing read guard decides exactly as before.

### `.gitignore` (MODIFY)
```text
# occurrences: 1 (verified: grep -c '!.codex/agents/\*.toml' .gitignore)
# AFTER — insert below `!.codex/agents/*.toml` (verified: .gitignore:366)
!.codex/hooks.json
```

### `.codex/hooks.json` (CREATE)
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "sh scripts/sdd/codex_hook.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```
**Why**: identical shape to the local file, minus the machine-specific interpreter path. If S1 shows codex runs hooks from a cwd other than the worktree root, change the command to resolve the script via `git rev-parse --show-toplevel` (FILL IN checklist).

### `scripts/sdd/codex_hook.sh` (CREATE)
```sh
#!/bin/sh
# FEAT-563 — portable launcher for the codex PreToolUse hook.
# Resolves the MAIN checkout (the one owning the shared .venv) from any linked
# worktree and runs the parrot_tools guard with the hook payload on stdin.
# Never breaks codex: any missing piece exits 0 silently (no decision).
common_dir=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
main_checkout=$(dirname "$common_dir")
python_bin="$main_checkout/.venv/bin/python"
[ -x "$python_bin" ] || exit 0
exec "$python_bin" -m parrot_tools.tool_optimizations.hooks --host codex
```
**Why**: `--git-common-dir` of any worktree is `<main>/.git`, so its parent is the checkout that owns `.venv` (worktrees never have their own venv — worktree rules). `exec` forwards stdin.

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py` (MODIFY)
```python
# FILL IN: disambiguate — `default=True,` occurs once but quote the field header for safety:
#   anchor lines (verified: models/codex.py:23-24):
#     ignore_user_config: bool = Field(
#         default=True,
# REPLACE `default=True,` with `default=False,` and the description with:
        description=(
            "When True, pass --ignore-user-config. Development dispatches default to "
            "False (FEAT-563) so the tracked project .codex/hooks.json test-scope guard "
            "applies; review profiles pin True so reviewers stay isolated."
        ),
```
```python
# occurrences: 2 (verified: grep -c '    timeout_seconds: int = Field(default=1800, ge=60, le=7200)' models/codex.py)
# FILL IN: disambiguate — insert below the timeout line INSIDE `class CodexCodeReviewProfile` (verified: models/codex.py:50-52):
#     sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
#     approval_policy: Literal["untrusted", "on-request", "never"] = "on-request"
#     timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    ignore_user_config: bool = True  # FEAT-563: reviewers never inherit operator Codex config
```
```python
# occurrences: 1 (verified: grep -c '    timeout_seconds: int = Field(default=600, ge=60, le=7200)' models/codex.py)
# AFTER — insert below `    timeout_seconds: int = Field(default=600, ge=60, le=7200)` (verified: models/codex.py:78)
    ignore_user_config: bool = True  # FEAT-563: reviewers never inherit operator Codex config
```

### `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert "--ignore-user-config" in command' test_codex_dispatcher.py)
# REPLACE — line 177
        assert "--ignore-user-config" not in command  # FEAT-563: dev dispatches load project hooks
```

### `packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert "--ignore-user-config" in cmd  # default True on the base profile' test_codex_command_variants.py)
# REPLACE — line 74
    assert "--ignore-user-config" in cmd  # review profiles pin ignore_user_config=True (FEAT-563)
```

### `packages/ai-parrot/tests/flows/dev_loop/test_models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert profile.ignore_user_config is True' test_models.py)
# REPLACE — line 150
        assert profile.ignore_user_config is False
        # FILL IN: import CodexCodeReviewProfile / CodexAdversarialReviewProfile the same way CodexCodeDispatchProfile is
        #          imported in this file and assert both default to ignore_user_config is True — spec M8 item 3
```

### `packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py` (MODIFY)
```python
# FILL IN: append at the end of the file (after `test_guard_does_not_fail_open`, verified: test_hooks.py:332; file ends at L378)
from parrot_tools.tool_optimizations import hooks as hooks_module
from parrot_tools.tool_optimizations.hooks import evaluate_scope


class _Outcome:
    def __init__(self, action, argvs=(), message=""):
        self.action, self.argvs, self.message = action, argvs, message


def test_scope_rewrite_denies_with_scoped_command(workspace, monkeypatch):
    fake = lambda command, *, worktree: (_Outcome("rewrite", (("pytest", "tests/test_a.py", "-q"),), "scoped"), None)
    monkeypatch.setattr(hooks_module, "_load_scope_guard", lambda cwd: (fake, workspace))
    out = json.loads(_run(_bash_payload("pytest packages/ai-parrot/tests"), host="codex", cwd=workspace))
    # FILL IN: assert permissionDecision == "deny" and "pytest tests/test_a.py -q" in the reason — AC6


def test_scope_inactive_falls_back_to_read_guard(workspace, monkeypatch):
    # FILL IN: _load_scope_guard → fake returning _Outcome("allow"); a large `cat big.py` is still denied by evaluate_shell,
    #          and a harmless `pytest tests/test_a.py` produces no output
    ...


def test_scope_missing_kernel_is_silent(workspace):
    # FILL IN: tmp dir that is not a git repo → evaluate_scope(...) is None (no exception)
    ...
```

### `artifacts/logs/feat-563-s1-codex-hook.md` (CREATE)
```markdown
# FEAT-563 spike S1 — tracked codex hook inside an attempt sub-worktree

- Date / codex CLI version:
- Command run (no `--ignore-user-config`):
- Sub-worktree path and attempt context present (yes/no):
- Did the PreToolUse hook fire? Evidence (codex JSON events / stderr excerpt):
- Deny reason received by codex:
- Feature flags or config codex required (e.g. hooks enablement) and where they live:
- Hook cwd observed (worktree root or elsewhere):
- Verdict: tracked hook enforces the scope guard — PASS / FAIL (+ follow-up if FAIL)
```

### FILL IN checklist
- [ ] `hooks.py` — add `import subprocess` to the stdlib import block (L30-39); keep it lazy-safe for `test_hook_import_is_dependency_light`
- [ ] `hooks.py::evaluate_scope` — final deny wording containing the scoped command; bounded by AC6
- [ ] `hooks.py` — `coverage` value: reuse `"shell"` or extend `coverage_matrix()` + its honesty test consistently
- [ ] `models/codex.py` — both disambiguated edits (dev default False; review profiles True)
- [ ] `test_models.py` — review-profile default assertions
- [ ] `test_hooks.py` — three test bodies; bounded by AC6 / "never break the host"
- [ ] `.codex/hooks.json` — adjust the command if S1 shows a non-root hook cwd
- [ ] `artifacts/logs/feat-563-s1-codex-hook.md` — real codex run evidence (not a simulation)

---

## Acceptance Criteria

- [ ] Inside a codex attempt, an over-broad pytest is denied and the reason contains the scoped command; with an empty plan the reason is the guard's block message (spec AC6)
- [ ] `git check-ignore .codex/hooks.json` exits non-zero; the tracked file contains no absolute `/home/` path (spec AC6)
- [ ] `CodexCodeDispatchProfile().ignore_user_config is False`; dev dispatch argv has no `--ignore-user-config`; both review profiles still pass it (spec AC6)
- [ ] `hooks.py` import stays free of pydantic/parrot (`test_hook_import_is_dependency_light` passes)
- [ ] Spike S1 log shows a real `codex exec --cd <sub-worktree>` where the tracked hook fired (spec AC6, S1)
- [ ] All tests pass (see Validation Commands) (spec AC13)
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py`

## Validation Commands
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_models.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py
def test_scope_rewrite_denies_with_scoped_command(workspace, monkeypatch): ...
def test_scope_inactive_falls_back_to_read_guard(workspace, monkeypatch): ...
def test_scope_missing_kernel_is_silent(workspace): ...

# packages/ai-parrot/tests/flows/dev_loop/test_models.py
#   CodexCodeDispatchProfile().ignore_user_config is False
#   CodexCodeReviewProfile().ignore_user_config is True; CodexAdversarialReviewProfile().ignore_user_config is True

# packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py
#   dev dispatch command has no "--ignore-user-config"

# shell check (manual, recorded in the S1 log)
#   git check-ignore .codex/hooks.json  → exit 1
#   grep -c '/home/' .codex/hooks.json  → 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3314-codex-deny-hook-tracked-config.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
