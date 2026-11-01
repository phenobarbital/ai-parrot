# TASK-5086: Legacy sandbox mode — explicit Bubblewrap-hook rescue path

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4908
**Assigned-to**: unassigned

---

## Context

Spec §2 policy 11 and AC14 (rev 0.4). TASK-4908 gave the native sandbox three modes, but `preferred`/`off`
drop the OS write boundary entirely; there is no supported way back to the pre-FEAT-768 boundary (the
retained hook wrapping every Bash call in its own Bubblewrap) when the *native* sandbox misbehaves on a host
where Bubblewrap itself works. Today that is only reachable by bypassing the launcher by hand, and the
dispatcher has no equivalent at all. The operator decided (2026-11-01) to add `legacy` as a fourth,
declared mode.

---

## Scope

- `native_claude_sandbox.py`:
  - `SANDBOX_MODES = ("required", "preferred", "off", "legacy")`.
  - `resolve_sandbox_mode`: `legacy` is accepted from `MODE_ENV` only; `[tool.parrot.sdd] sandbox = "legacy"`
    raises `ValueError(f"Invalid sandbox mode in {config_path}: 'legacy' may only be set through {MODE_ENV}")`
    — same shape as the existing `off` rejection (it drops the network boundary).
  - `plan_native_launch`: `legacy` → do **not** call `native_sandbox_available()`; instead require
    `sys.platform.startswith("linux")` and a successful legacy probe (`shutil.which("bwrap")` plus the same
    `bwrap --unshare-user --unshare-pid --ro-bind / / true` run, without the `socat` requirement — factor
    the bwrap run out of `native_sandbox_available` into `_bwrap_probe(executable: str) -> tuple[bool, str]`
    so both share it). Failure → `RuntimeError(f"legacy mode needs a working Bubblewrap: {reason}")`.
    Success → `("legacy", False, "", native_sandbox_settings(cwd, allowed_domains=allowed_domains,
    include_sandbox=False))`. `allowed_domains` are ignored with no error (legacy has no network boundary;
    the launcher prints that once, see below).
  - New helper `launch_backend(mode: str) -> str`: `BACKEND_BUBBLEWRAP` for `legacy`, else `BACKEND_NATIVE`.
  - `launch_worker`: set `env[BACKEND_ENV] = launch_backend(mode)`; for `legacy` print
    `launch_worker: mode=legacy — native sandbox disabled, Bash runs in the hook's Bubblewrap (filesystem only, no network isolation)`
    to stderr (plus `; --sandbox-allow-domain ignored` when domains were given), never set `DEGRADED_ENV`
    (pop it, like strict launches). The `RuntimeError` message for legacy must not say `mode=required`:
    print `launch_worker: native sandbox unavailable ({exc}); mode={mode} refuses to start` using the
    resolved mode (resolve the mode before `plan_native_launch` raises — e.g. have `plan_native_launch`
    raise a `RuntimeError` whose message already carries the mode, or resolve it in `launch_worker` first;
    the existing `required` stderr line must stay byte-identical).
- `dispatchers/claude.py` `_resolve_run_options` sandboxed branch: `env[BACKEND_ENV] =
  native_claude_sandbox.launch_backend(mode)`; for `legacy` log
  `self.logger.warning("native sandbox LEGACY for %s: Bubblewrap hook boundary, no network isolation", profile.subagent)`
  and pop `DEGRADED_ENV`.
- `worktree_environment.py`: no logic change is expected (explicit `bubblewrap` backend + launcher markers is
  already accepted by `main()`); add a test proving it.
- Tests (see Test Specification).

**NOT in scope**: platform-specific probes (TASK-5087), the `parrot devloop launch-worker` command and its
`--sandbox` flag (TASK-5088), docs (TASK-5089), changing the default mode, any change to `protected_argv`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py` | MODIFY | `legacy` mode, `_bwrap_probe`, `launch_backend`, launcher wiring |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | backend from `launch_backend(mode)`, legacy warning |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | resolution + plan tests for legacy |
| `tests/sdd/test_launch_worker.py` | MODIFY | launcher legacy tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py` | MODIFY | legacy dispatch test in `TestSandboxedSettingSources` |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | hook with `bubblewrap` backend + launcher markers wraps in bwrap |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# native_claude_sandbox.py already imports: ipaddress, json, os, Path, re, shlex, shutil, subprocess, sys, time, tomllib, Any, Sequence, uuid
# and `worktree_environment as _we` (relative import when packaged, sibling import as a script) — keep it stdlib only.
# dispatchers/claude.py already has:
from parrot.flows.dev_loop import native_claude_sandbox, worktree_environment
```

### Existing Signatures to Use
```text
native_claude_sandbox.py
  BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"; BACKEND_NATIVE = "claude-native"; BACKEND_BUBBLEWRAP = "bubblewrap"  (lines 27-29)
  MODE_ENV (32), DEGRADED_ENV (33), SANDBOX_MODES = ("required", "preferred", "off")  (34)
  def resolve_sandbox_mode(repo_root: Path) -> str                                  (204) — `off` rejection at 248-252
  _PROBE_TTL_SECONDS / _probe_cache                                                 (258-259)
  def native_sandbox_available() -> tuple[bool, str]                                (262) — bwrap run at 283-297
  def native_sandbox_settings(cwd, *, allowed_domains=(), include_sandbox=True)     (302)
  def plan_native_launch(cwd, *, allowed_domains=()) -> tuple[str, bool, str, dict] (347)
  def launch_worker(argv: Sequence[str]) -> int                                     (620) — `mode=required refuses to start` line at 635
dispatchers/claude.py
  _SANDBOXED_SUBAGENTS (94); def _resolve_run_options(...) (583); sandboxed branch 651-670:
    mode, degraded, reason, settings = native_claude_sandbox.plan_native_launch(Path(cwd), allowed_domains=profile.sandbox_allowed_domains)
    env[native_claude_sandbox.BACKEND_ENV] = native_claude_sandbox.BACKEND_NATIVE   (662)
worktree_environment.py
  def protected_argv(cwd, argv) -> list[str]   (228) — raises RuntimeError when bwrap missing (247)
  def hook_response(payload, *, backend="bubblewrap") (502); def main() (553) — native-marker guard 559-566, backend default 567
tests
  tests/sdd/test_launch_worker.py: fixtures fake_claude_path (24), linked_cwd (43), autouse _clean_sandbox_mode_env (69);
    helpers _run(path, cwd, *args) (56), _output(result) (75); test_required_mode_refuses_failing_bwrap_probe (191), test_off_mode_skips_probe (270)
  packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py: test_sandbox_mode_pyproject_errors (121, parametrized),
    test_plan_native_launch_degrades_or_refuses (138), test_native_sandbox_available_branches (172)
  packages/ai-parrot/tests/flows/dev_loop/conftest.py: fixture linked_worktree(tmp_path, monkeypatch) (136)
  packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py: fixture dispatcher(monkeypatch) (109); class TestSandboxedSettingSources (741)
  packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py: test_main_reads_backend_from_environment (804),
    test_hook_refuses_legacy_fallback_when_native_markers_are_present (989)
```

### Does NOT Exist
- ~~a `legacy` value anywhere in `SANDBOX_MODES`~~ — add it.
- ~~`launch_backend`, `_bwrap_probe`~~ — create them in `native_claude_sandbox.py`.
- ~~a `--sandbox` option in `_parse_launch_arguments`~~ — not in this task; the mode comes from `MODE_ENV` here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "tests/sdd/test_launch_worker.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#resolve_sandbox_mode",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#native_sandbox_available",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#plan_native_launch",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#launch_worker",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher._resolve_run_options"
  ]
}
```

---

## Implementation Notes

- Legacy is a *declared* posture, not a degraded one: no `DEGRADED_ENV`, no hook banner.
- Keep the probe cache semantics of `native_sandbox_available` untouched; `_bwrap_probe` itself is uncached
  (legacy launches are rare and interactive).
- The compiled settings for legacy are exactly `native_sandbox_settings(..., include_sandbox=False)`: the hook
  block is identical; the hook picks the Bubblewrap wrapper because the backend env says so.
- Never let `legacy` fall through to an unprotected launch: any probe failure is a `RuntimeError`.

---

## Acceptance Criteria

- [ ] `PARROT_SDD_SANDBOX_MODE=legacy` resolves to `legacy`; `[tool.parrot.sdd] sandbox = "legacy"` raises naming the env var.
- [ ] `plan_native_launch` in legacy returns hooks without a `sandbox` key, never calls `native_sandbox_available`, and raises when `bwrap` is missing, the probe fails or the platform is not Linux.
- [ ] Launcher legacy: child env has `PARROT_SDD_SANDBOX_BACKEND=bubblewrap`, no `PARROT_SDD_SANDBOX_DEGRADED`, the legacy stderr line; failing probe → exit 1 with `mode=legacy refuses to start`; the `required` refusal line is unchanged.
- [ ] Dispatcher legacy: settings without `sandbox`, backend `bubblewrap`, warning logged; legacy failure → `DispatchExecutionError`.
- [ ] Hook `main()` with `PARROT_SDD_SANDBOX_BACKEND=bubblewrap` and launcher markers present wraps Bash with `bwrap` (no deny).
- [ ] `ruff check` clean on changed Python files; all Validation Commands green.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `pytest tests/sdd/test_launch_worker.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`

---

## Test Specification

Unit tests only. Launcher: reuse `fake_claude_path` (its `bwrap` stub exits 0; write a failing stub for the
refusal case, as `test_required_mode_refuses_failing_bwrap_probe` does) and set `PARROT_SDD_SANDBOX_MODE=legacy`
in the `_run` env; assert on `_output(result)`. Plan/dispatcher: `monkeypatch.setattr(native_claude_sandbox,
"native_sandbox_available", <raising lambda>)` to prove it is not called, and monkeypatch `_bwrap_probe` /
`sys.platform` for the failure branches. Hook: a stub `bwrap` on PATH and `test_main_reads_backend_from_environment`
as the pattern.

---

## Agent Instructions

1. Work only in the worktree you are given; commit only the files in the table.
2. Verify every Codebase Contract entry before editing; stop and report if one is stale.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
