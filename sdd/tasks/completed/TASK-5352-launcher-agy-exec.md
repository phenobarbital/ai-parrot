# TASK-5352: `launch_agy_worker` and the Google branch of `launch_session`

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5351
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, "Approval depends on the mode". Two ways to start `agy`:
- **Unattended worker** (`launch_agy_worker`): `agy --agent sdd-worker --dangerously-skip-permissions … -p "run <FEAT-ID>"`
  with `PARROT_SDD_AGY_UNATTENDED=1` and `PARROT_SDD_SANDBOX_BACKEND=bubblewrap`, so the hook (TASK-5348)
  turns every `force_ask` into `deny` and wraps commands in Bubblewrap.
- **Interactive session** (`launch_session(host="google")`, used by `brief`/`fix`): `agy … -i "<prompt>"`
  with **neither** variable and **without** `--dangerously-skip-permissions`; PR #2040's allow-rules plus the
  operator approve, and the hook still denies.

Neither passes `--mode auto` (account-gated). Both refuse the community snap (TASK-5351 helpers). Neither
inherits Claude native-sandbox markers.

---

## Scope

- Add `AGY_UNATTENDED_ENV`, `AGY_WORKER_ARGS`, `agy_environment()` and `launch_agy_worker()` (spec skeleton
  signature) to `feature_launcher.py`.
- Add `host: Literal["claude", "google"] = "claude"` to `launch_session()` and its Google branch.
- Tests in `test_sdd_launch.py`.

**NOT in scope**: `launch()`/tmux/`main()` host propagation and the hook prerequisite check (TASK-5353); the
worker's sandbox selection call (TASK-5353 calls `google_worker_sandbox`); CLI options (TASK-5354).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | `agy_environment`, `launch_agy_worker`, `launch_session(host=...)` |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | exec argv / environment tests for both modes |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09). TASK-5351 symbols exist once it is merged.

### Verified Imports
```python
# feature_launcher.py (stdlib only); typing import at line 20 is `from typing import Mapping, Sequence`
#   — add `Literal` to it.
from parrot.flows.dev_loop import feature_launcher as launcher   # tests
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py
def launch_session(                                               # line 642
    initial_prompt: str, *, cwd: Path, claude_args: Sequence[str] = (), base_env: Mapping[str, str] | None = None,
) -> int:
    # line 655: claude = shutil.which("claude") ... builds [claude, "--setting-sources", "project,local", "--model",
    #   native_claude_sandbox._DEFAULT_MODEL, *claude_args, initial_prompt]; env = dict(os.environ if base_env is None
    #   else base_env); os.chdir(cwd); os.execvpe(command[0], command, env); return 1
OFFICIAL_AGY_INSTALL, resolve_agy() -> Path, agy_is_snap(agy) -> bool, require_official_agy(agy) -> None   # TASK-5351
# packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py (launcher.native_claude_sandbox)
BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"     # line 31
BACKEND_BUBBLEWRAP = "bubblewrap"              # line 33
CACHE_DIR_ENV = "PARROT_SDD_CACHE_DIR"         # line 34
ROOTS_ENV = "PARROT_SDD_SANDBOX_ROOTS"         # line 35
DEGRADED_ENV = "PARROT_SDD_SANDBOX_DEGRADED"   # line 37
# packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py
UNATTENDED_ENV = "PARROT_SDD_AGY_UNATTENDED"   # added by TASK-5348 — the launcher duplicates the literal (stdlib-only child)
# packages/ai-parrot/tests/sdd/test_sdd_launch.py
def _capture_exec(monkeypatch, tmp_path) -> dict[str, object]:   # line 1199 — patches shutil.which, _invocation_dir,
    # os.chdir and os.execvpe (records argv/env, raises SystemExit(0)); NOTE its which-mock returns "/usr/bin/claude"
    # for every name, so Google tests need their own which-mock returning "/usr/bin/agy".
```

### Does NOT Exist
- ~~`--mode auto` in any launcher command~~ — never by default (spec §3 M3).
- ~~`--dangerously-skip-permissions` in `launch_session`~~ — interactive sessions never pass it.
- ~~Importing `parrot.sdd.scripts.agy_permissions` in `feature_launcher`~~ — the tmux child runs under `python -S`; duplicate the env name and assert equality in a test.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_sdd_launch.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#launch_session"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Strip `CACHE_DIR_ENV`, `ROOTS_ENV`, `DEGRADED_ENV` in both modes ("must not inherit claude-native markers").
- Unattended: set `AGY_UNATTENDED_ENV=1` and `BACKEND_ENV=bubblewrap`. Interactive: remove both.
- Snap or missing `agy`: print `launch: <message>` / `launch-worker: <message>` to stderr and return the
  `LaunchError.exit_code` (these functions return exit codes; they do not raise).
- `agy_args` / `claude_args` are forwarded verbatim; launcher-only options never reach them (spec §3 M3).

---

## Implementation Blueprint

### Steps (in order)
1. Add `Literal` to the typing import — *why*: the `host` parameter type.
2. Insert the constants, `agy_environment` and `launch_agy_worker` directly above `def launch_session(` — *why*: the two exec paths sit together.
3. Add the `host` parameter and the Google branch at the top of `launch_session` — *why*: the Claude branch stays byte-for-byte.
4. Write the tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def launch_session(' feature_launcher.py) — line 642
# BEFORE — insert above `def launch_session(`:
#: The hook (agy_permissions.UNATTENDED_ENV) reads this: force_ask -> deny, commands wrapped in Bubblewrap.
AGY_UNATTENDED_ENV = "PARROT_SDD_AGY_UNATTENDED"
AGY_WORKER_ARGS: tuple[str, ...] = ("--agent", "sdd-worker", "--dangerously-skip-permissions")


def agy_environment(base_env: Mapping[str, str] | None, *, unattended: bool) -> dict[str, str]:
    """Environment for an agy process: no Claude native markers; unattended adds the worker's guard variables."""
    env = dict(os.environ if base_env is None else base_env)
    for name in (
        native_claude_sandbox.CACHE_DIR_ENV,
        native_claude_sandbox.ROOTS_ENV,
        native_claude_sandbox.DEGRADED_ENV,
        native_claude_sandbox.BACKEND_ENV,
        AGY_UNATTENDED_ENV,
    ):
        env.pop(name, None)
    if unattended:
        env[AGY_UNATTENDED_ENV] = "1"
        env[native_claude_sandbox.BACKEND_ENV] = native_claude_sandbox.BACKEND_BUBBLEWRAP
    return env


def launch_agy_worker(
    agy_args: Sequence[str],
    *,
    cwd: Path,
    initial_prompt: str,
    base_env: Mapping[str, str] | None = None,
) -> int:
    """Exec agy --agent sdd-worker --dangerously-skip-permissions in cwd with PARROT_SDD_AGY_UNATTENDED=1 and the bubblewrap backend (no --mode auto by default)."""
    try:
        agy = resolve_agy()
        require_official_agy(agy)
    except LaunchError as exc:
        print(f"launch-worker: {exc}", file=sys.stderr)
        return exc.exit_code
    command = [str(agy), *AGY_WORKER_ARGS, *agy_args, "-p", initial_prompt]
    env = agy_environment(base_env, unattended=True)
    os.chdir(cwd)
    os.execvpe(command[0], command, env)
    return 1

# In `launch_session` (line 642): add the keyword parameter `host: Literal["claude", "google"] = "claude",` after
# `base_env`, extend the docstring ("agy: never --dangerously-skip-permissions"), and insert as its FIRST statements:
    if host == "google":
        # FILL IN: resolve_agy() + require_official_agy() (print f"launch: {exc}" and return exc.exit_code on
        #   LaunchError); command = [str(agy), *claude_args, "-i", initial_prompt]; env =
        #   agy_environment(base_env, unattended=False); os.chdir(cwd); os.execvpe(command[0], command, env);
        #   return 1 — bounded by spec §3 M3 (no --dangerously-skip-permissions, no --mode auto, neither variable).
        return 1
```
**Why this shape**: the environment builder is the single place that decides which guard variables an `agy`
process gets, so the tests can assert the unattended/interactive contract without exec'ing anything.

### `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)
```python
# AFTER — append at end of file
def _capture_agy_exec(monkeypatch: pytest.MonkeyPatch, agy: str = "/home/u/.local/bin/agy") -> dict[str, object]:
    """Mock agy discovery and exec (no symlink into /snap)."""
    seen: dict[str, object] = {}
    monkeypatch.setattr(launcher.shutil, "which", lambda name: agy if name == "agy" else None)
    monkeypatch.setattr(launcher.os, "chdir", lambda path: seen.__setitem__("cwd", Path(path)))

    def _exec(file: str, argv: list[str], env: dict[str, str]) -> None:
        seen.update(argv=list(argv), env=env)
        raise SystemExit(0)

    monkeypatch.setattr(launcher.os, "execvpe", _exec)
    return seen


def test_launch_agy_worker_is_unattended(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = _capture_agy_exec(monkeypatch)
    base = {"PATH": "/usr/bin", launcher.native_claude_sandbox.CACHE_DIR_ENV: "/x"}
    with pytest.raises(SystemExit):
        launcher.launch_agy_worker(["--verbose"], cwd=tmp_path, initial_prompt="run FEAT-768", base_env=base)
    argv, env = seen["argv"], seen["env"]
    assert argv[1:4] == ["--agent", "sdd-worker", "--dangerously-skip-permissions"]
    assert argv[-2:] == ["-p", "run FEAT-768"] and "--verbose" in argv and "--mode" not in argv
    assert env[launcher.AGY_UNATTENDED_ENV] == "1"
    assert env[launcher.native_claude_sandbox.BACKEND_ENV] == "bubblewrap"
    assert launcher.native_claude_sandbox.CACHE_DIR_ENV not in env


# FILL IN tests (one function each):
#  - launch_session(..., host="google"): argv == [agy, *claude_args, "-i", prompt]; no
#    "--dangerously-skip-permissions", no "--mode"; neither AGY_UNATTENDED_ENV nor BACKEND_ENV in env, even when
#    base_env carried them; cwd chdir'ed
#  - snap agy (which -> "/snap/bin/agy") for both functions -> returns 2 without exec, stderr names
#    launcher.OFFICIAL_AGY_INSTALL (use capsys)
#  - missing agy -> returns 1 without exec
#  - launch_session default host stays Claude (existing test_launch_brief_and_fix_exec_slash_command passes)
#  (the AGY_UNATTENDED_ENV == agy_permissions.UNATTENDED_ENV equality test belongs to TASK-5353, which
#   already depends on the hook chain — keeping it here would make this task wait for TASK-5348)
```

### FILL IN checklist
- [ ] Google branch of `launch_session`; bounded by spec §3 M3
- [ ] the listed tests

---

## Acceptance Criteria

- [ ] `launch_agy_worker` execs `agy --agent sdd-worker --dangerously-skip-permissions … -p <prompt>` with `PARROT_SDD_AGY_UNATTENDED=1` and the bubblewrap backend, and no Claude native markers.
- [ ] `launch_session(host="google")` execs `agy … -i <prompt>` with neither variable and no `--dangerously-skip-permissions`; neither path passes `--mode auto`.
- [ ] Snap `agy` → exit 2 with the official install command; missing `agy` → exit 1; Claude `launch_session` unchanged.
- [ ] All tests pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-agy-compatibility --feature-id FEAT-847`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/sdd-agy-compatibility.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` in a worktree)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5352 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-sol (codex), 1 attempt
**Date**: 2026-11-09
**Notes**: TASK-5352 delivered per task file. Merge-tier validation green (chunk 1: 581 passed, 10 skipped; asset sync 27 passed).

**Deviations from spec**: none
