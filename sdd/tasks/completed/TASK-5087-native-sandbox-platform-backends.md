# TASK-5087: Per-platform sandbox probe — macOS Seatbelt, native-Windows refusal, Windows-safe hook

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5086
**Assigned-to**: unassigned

---

## Context

Spec §2 policy 12 and AC15 (rev 0.4). `native_sandbox_available()` only knows Linux (`bwrap` + `socat`), so on
macOS `required` refuses and `preferred` degrades even though Claude Code's native sandbox runs there on
Seatbelt. On native Windows there is no Claude Code sandbox, and the hook module cannot even import:
`worktree_environment.py:149` evaluates `os.getuid()` at module level (absent on Windows), so every tool call
fails — including a `preferred` degraded session that should keep its guards. The SDD flow is installed in
consumer repositories on all three OSes (FEAT-633), so each platform needs an explicit, legible outcome.

---

## Scope

- `native_claude_sandbox.py`:
  - `sandbox_platform() -> str` returning `"linux"` (`sys.platform.startswith("linux")`, WSL2 included),
    `"macos"` (`darwin`) or `"windows"` (`win32`/`cygwin`); anything else → `"unsupported"`.
  - `native_sandbox_available()` dispatches on `sandbox_platform()` (cache unchanged):
    - linux → today's behaviour exactly (`bwrap` + `socat` + `_bwrap_probe` from TASK-5086).
    - macos → `shutil.which("sandbox-exec")` (missing → `(False, "missing prerequisite(s): sandbox-exec")`),
      then `subprocess.run([exe, "-p", "(version 1)(allow default)", "/usr/bin/true"], capture_output=True,
      text=True, timeout=10, check=False)`; nonzero/timeout → `(False, <first stderr line or "sandbox-exec probe failed/timed out">)`.
    - windows → `(False, "native Windows has no Claude Code sandbox; run the worker inside WSL2, or set PARROT_SDD_SANDBOX_MODE=preferred for a degraded (hook-only) launch")`.
    - unsupported → `(False, f"unsupported platform {sys.platform!r} for the native sandbox")`.
  - `plan_native_launch`: `legacy` on a non-Linux platform raises
    `RuntimeError(f"legacy mode needs Linux Bubblewrap; not available on {sandbox_platform()}")` (TASK-5086 left
    a bare Linux check — reword it to this message).
  - `launch_worker`: on a strict (non-degraded) macOS launch print once to stderr
    `launch_worker: NOTICE macOS Seatbelt backend is implemented but not certified (see docs/dev_loop/claude-native-sandbox.md)`.
    Dispatcher: the same text via `self.logger.warning` — see below.
  - `native_command_environment`: replace the two `os.getuid()` uses (lines 469/472) with a module helper
    `_user_tag() -> str` = `str(os.getuid())` when `hasattr(os, "getuid")`, else the sanitized
    `getpass.getuser()` (only `[A-Za-z0-9_.-]`).
- `worktree_environment.py`:
  - `CLAUDE_SCRATCH_ROOT` (line 149) must not raise on Windows: POSIX keeps `Path("/tmp") / f"claude-{os.getuid()}"`
    byte-identical; Windows uses `Path(tempfile.gettempdir()) / f"claude-{<sanitized getpass.getuser()>}"`.
  - `protected_argv`: when `bwrap` is missing, the `RuntimeError` text becomes
    `f"Bubblewrap (bwrap) is required for the legacy SDD hook and is not available on {sys.platform}; refusing unsandboxed execution. Launch the worker with `parrot devloop launch-worker <FEAT-ID>` (native sandbox) instead."`
    — still a denial, never an unwrapped command.
- `dispatchers/claude.py`: after a strict plan on macOS (`native_claude_sandbox.sandbox_platform() == "macos"`
  and not degraded), log the uncertified notice as a warning once per dispatch.
- Tests (see Test Specification).

**NOT in scope**: running or recording a macOS/Windows live qualification (no such host here); changing the
compiled settings shape per platform; WSL-specific code (WSL2 is Linux); `parrot devloop launch-worker`
(TASK-5088); docs (TASK-5089).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py` | MODIFY | `sandbox_platform`, per-platform probe, legacy platform message, macOS notice, `_user_tag` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` | MODIFY | Windows-safe `CLAUDE_SCRATCH_ROOT`; actionable bwrap-missing message |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | macOS uncertified warning |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | platform probe branches, `_user_tag` |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | import without `os.getuid`, new bwrap-missing message |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py` | MODIFY | macOS warning logged |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# native_claude_sandbox.py: stdlib only — add `import getpass` if needed.
# worktree_environment.py: stdlib only — add `import getpass`, `import tempfile` if needed (it already imports os, shutil, sys, Path).
```

### Existing Signatures to Use
```text
native_claude_sandbox.py (line numbers before TASK-5086 lands; re-locate after it)
  def native_sandbox_available() -> tuple[bool, str]          (262) — linux branch at 277-297
  def plan_native_launch(...)                                  (347)
  def native_command_environment(cwd: Path) -> dict[str, str]  (449) — os.getuid() at 469 and 472
  def launch_worker(argv: Sequence[str]) -> int                (620)
  TASK-5086 adds: _bwrap_probe(executable: str) -> tuple[bool, str], launch_backend(mode: str) -> str
worktree_environment.py
  CLAUDE_SCRATCH_ROOT = Path("/tmp") / f"claude-{os.getuid()}"   (149)
  def claude_scratch_root() -> Path                               (211)
  def protected_argv(cwd, argv) -> list[str]                      (228) — bwrap-missing RuntimeError at 245-247
dispatchers/claude.py: sandboxed branch of _resolve_run_options (651-670)
tests: test_native_sandbox_available_branches (test_native_claude_sandbox.py:172) is the pattern for probe tests;
  autouse fixture at test_native_claude_sandbox.py:86 resets the probe cache — keep using it.
```

### Does NOT Exist
- ~~any `sys.platform` / `darwin` / `win32` handling in `native_claude_sandbox.py` or `worktree_environment.py`~~ — add it here.
- ~~a Claude Code sandbox on native Windows~~ — never emit settings that pretend otherwise; `required` must refuse.
- ~~`sandbox-exec` qualification evidence~~ — do not edit `sdd/state/FEAT-768/native-sandbox-qualification.md`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#native_sandbox_available",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#plan_native_launch",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#native_command_environment",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#protected_argv",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher._resolve_run_options"
  ]
}
```

---

## Implementation Notes

- Linux behaviour must not change by a single byte of output (existing tests are the regression contract).
- Tests run on Linux: drive branches with `monkeypatch.setattr(native_claude_sandbox, "sandbox_platform", lambda: "macos")`
  and stub `sandbox-exec` on PATH; for the Windows import test, run a subprocess `python -c` that deletes
  `os.getuid` before importing the module file by path (`runpy.run_path` or `importlib.util`), and assert it
  imports and `claude_scratch_root()` resolves.
- `_user_tag` must be filesystem-safe and stable per user; never empty (fallback `"user"`).

---

## Acceptance Criteria

- [ ] Linux probe/launch output unchanged (all existing tests green).
- [ ] macOS: probe uses `sandbox-exec` only; missing/failing → reason; strict launch prints/logs the uncertified notice once.
- [ ] Windows: `required` refusal names WSL2 and `PARROT_SDD_SANDBOX_MODE=preferred`; `preferred` degrades with that reason; `legacy` refuses with the platform message.
- [ ] `worktree_environment.py` and `native_claude_sandbox.py` import and build a command environment without `os.getuid`.
- [ ] Missing `bwrap` in the legacy hook still denies, with the actionable message.
- [ ] `ruff check` clean on changed Python files; all Validation Commands green.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -q`
- `pytest tests/sdd/test_launch_worker.py -q`  (regression only — the launcher subprocess cannot fake the platform; the macOS notice is tested in-process in test_native_claude_sandbox.py by calling `launch_worker` with `os.execvpe` monkeypatched)

---

## Test Specification

Unit tests only, on Linux, by monkeypatching `sandbox_platform` / `shutil.which` and stubbing `sandbox-exec`
scripts in `tmp_path` on PATH (exit 0 / exit 1 with a stderr line). Windows import: a subprocess that removes
`os.getuid` before loading `worktree_environment.py` by path.

---

## Agent Instructions

1. Work only in the worktree you are given; commit only the files in the table.
2. Verify every Codebase Contract entry before editing (line numbers move after TASK-5086); stop and report if one is stale.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note


- Task: TASK-5087
- Feature: sdd-claude-native-sandbox
- Implementation SHA: 6832359a450b8ec6ef908fb27b3de31b8fa50c9a
- Closed at (UTC): 2026-11-01T01:02:52+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| review | orchestrator review of diff bdf058a852..08e99c8170, no corrections (cosmetic only: duplicated user-tag helper, displaced CLAUDE_SCRATCH_ROOT comment) |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 292.9s · Tokens: n/a |
| validation | merge tier: 267 passed/1 skipped; tests/sdd/test_launch_worker.py 32 passed (manual regression) |
