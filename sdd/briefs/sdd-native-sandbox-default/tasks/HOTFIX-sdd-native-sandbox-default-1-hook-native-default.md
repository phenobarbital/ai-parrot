# HOTFIX-sdd-native-sandbox-default-1: Hook defaults to native, with a runtime branch and explicit legacy

**Feature**: sdd-native-sandbox-default — native sandbox by default, launcher-only guidance
**Spec**: `sdd/briefs/sdd-native-sandbox-default.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`worktree_environment.main()` falls back to the legacy Bubblewrap wrapper when
`PARROT_SDD_SANDBOX_BACKEND` is unset. Inside Claude Code's native sandbox
(`allowNestedUserNamespaces: false`), that nested `bwrap` fails on every Bash call. The hook runs
outside the sandbox and cannot see it, but the wrapped command can. Read the brief's Decisions 1-4.

## Scope

In `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py`:

- **Backend resolution in `main()`.** Unset or empty `PARROT_SDD_SANDBOX_BACKEND` selects a new
  `auto` backend. `bubblewrap` stays available, but only when set explicitly. `claude-native` is
  unchanged. Unknown values still deny. Keep the existing "native launch markers present but
  backend unset" refusal; it now means "markers without a backend", not "legacy fallback".
  Update the `hook_response` keyword default and docstring to match.
- **Runtime branch for `auto`.** Emit one wrapper whose shell text tests whether the command runs
  inside the native sandbox: `SANDBOX_RUNTIME=1` and, on Linux, `/proc/self/uid_map` is a single line
  that does not start with `0 0 `. Inside, run the native path (the `env …` + bounded shell the
  `claude-native` branch emits today). Outside, run the legacy `protected_argv` path. Exactly one of
  the two runs; nothing runs unsandboxed. Keep guard → RTK → bounded-shell ordering, and run them once
  on the inner command, not per branch.
- **Fail-closed check for `claude-native`.** Prefix the native wrapper with the same check. When it
  fails and `PARROT_SDD_SANDBOX_DEGRADED` is not `1`, print one line to stderr and exit non-zero
  without running the command: `[sdd] native sandbox not active; launch with: parrot sdd launch worker <FEAT>`.
  Degraded and `off` launches keep `DEGRADED_BANNER` and run as today.
- **Hand-written `bwrap` in native mode.** In `hook_response` with backend `claude-native`, deny (no
  rewrite) a Bash command whose first word is `bwrap` or a path ending in `/bwrap`, unless it is this
  hook's own output (it never is in native mode). Reason, one line:
  `native sandbox is active; resend the command without the bwrap wrapper`.
- **Idempotency.** `_is_own_wrapper` must recognize the new `auto` and fail-closed shapes:
  `hook_response(hook_response(x))` returns no `updatedInput` for all three backends. Keep the
  "byte-identical rebuild from the inner command" rule: a look-alike never skips the guard.
- **Docstrings** of `hook_response`, `_wrap_bash`, `_is_own_wrapper` and `main` describe the three
  backends.

Tests in `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py`:

- Update `test_main_reads_backend_from_environment` (:891) and any test asserting "unset ⇒
  bubblewrap" to assert "unset ⇒ auto".
- New tests:
  - `auto` output runs the native path when the check passes and `protected_argv` when it fails. Use
    a fake `/proc/self/uid_map` path injected through a module-level constant, or run the emitted
    shell with `SANDBOX_RUNTIME` unset/set and assert on which branch executed.
  - `auto` output is idempotent (`hook(hook(x))` gives no `updatedInput`).
  - `claude-native` exits non-zero with the launcher message outside the sandbox, and runs the
    command when `PARROT_SDD_SANDBOX_DEGRADED=1`.
  - The hand-written `bwrap …` command is denied under `claude-native`, and allowed (wrapped) under
    `bubblewrap`.
  - The RTK rewrite of the inner command survives in all three backends (reuse the existing RTK
    test fixtures).

**NOT in scope**: launcher changes, docs and command text (tasks 2-3), moving env into the launcher
(task 4), in-process dispatcher `protected_argv` callers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | `auto` backend, runtime branch, fail-closed native check, `bwrap` denial, idempotency |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | updated and new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev, 2026-11-04)
```
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:229  def protected_argv(cwd: Path, argv: Sequence[str]) -> list[str]:
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:432  def bounded_shell_argv(command: str, tool_input: dict[str, Any]) -> list[str]:
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:471  def rtk_rewrite(command: str) -> str | None:
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:525  DEGRADED_BANNER = "echo '[sdd] degraded sandbox: no OS write boundary' >&2; "
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:528  def _wrap_bash(command: str, cwd: Path, tool_input: dict[str, Any], native: Any) -> str:
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:563  def _is_own_wrapper(command: str, cwd: Path, tool_input: dict[str, Any], native: Any) -> bool:
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:597  def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]:
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:637          backend = os.environ.get("PARROT_SDD_SANDBOX_BACKEND")
packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:29   BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"
packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:31   BACKEND_BUBBLEWRAP = "bubblewrap"
packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:35   DEGRADED_ENV = "PARROT_SDD_SANDBOX_DEGRADED"
packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:557  def native_command_environment(cwd: Path) -> dict[str, str]:
packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py:803  def test_native_hook_is_idempotent_on_own_output(
packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py:818  def test_bubblewrap_hook_is_idempotent_on_own_output(
packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py:891  def test_main_reads_backend_from_environment(tmp_path: Path) -> None:
packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py:1121 def test_hook_refuses_legacy_fallback_when_native_markers_are_present(tmp_path: Path) -> None:
```

### Facts verified in-session (2026-11-04)
- Inside the native sandbox: `SANDBOX_RUNTIME=1`, `/proc/self/uid_map` = `1000 1000 1`.
  Plain session: no `SANDBOX_RUNTIME`, `uid_map` = `0 0 4294967295`.
- Inside the native sandbox, any `bwrap` fails with `No permissions to create new namespace`.
- `worktree_environment.py` is stdlib-only and must stay importable as a script (`main()` runs
  without `parrot` application dependencies) and on Windows.

### Does NOT Exist
- No `BACKEND_AUTO` constant exists yet. If you add one, define it in `native_claude_sandbox.py`
  next to `BACKEND_BUBBLEWRAP`, or as a local constant in `worktree_environment.py`. Do not import
  `native_claude_sandbox` eagerly in the bubblewrap path (`_load_native_sandbox` is lazy on purpose).

---

## Acceptance Criteria

- [ ] Unset backend ⇒ `auto`: runs natively inside the native sandbox, through `bwrap` outside it,
      and never both.
- [ ] `claude-native` outside the sandbox (not degraded) exits non-zero with the launcher message and
      runs nothing. Degraded keeps the banner and runs.
- [ ] `PARROT_SDD_SANDBOX_BACKEND=bubblewrap` keeps today's output byte-for-byte
      (`test_legacy_hook_output_unchanged` passes unchanged).
- [ ] A hand-written `bwrap` command is denied under `claude-native` with the one-line reason.
- [ ] `hook(hook(x))` gives no `updatedInput` for `auto`, `claude-native` and `bubblewrap`.
- [ ] RTK and scope-guard behavior is unchanged in all backends.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`

## Agent Instructions

Read the brief first. Touch only the listed files. Never weaken a deny into an allow: every path
that cannot prove a sandbox must still run under `bwrap`, or not run at all.

## Completion Note
