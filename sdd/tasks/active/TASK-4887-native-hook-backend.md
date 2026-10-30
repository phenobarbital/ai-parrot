# TASK-4887: Native backend in the retained SDD hook

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4885, TASK-4886
**Assigned-to**: unassigned

---

## Context

Spec §3 M1 (second half) and §2 policies 3–4. Under the native sandbox, the hook must keep the
test-scope guard → RTK → bounded-shell ordering but must NOT insert Bubblewrap (nested bwrap fails
with ENOSPC — preflight Q2). The backend is selected by the launcher-set child environment
variable `PARROT_SDD_SANDBOX_BACKEND`: missing → legacy Bubblewrap (unchanged), `claude-native` →
native branch, anything else → deny. File tools get the native write validator in native mode.

---

## Scope

- Add a `backend` keyword to `hook_response` (default `"bubblewrap"`, legacy behavior byte-identical).
- Native Bash branch: resolve the task cwd with `native_task_cwd`, run the scope guard and RTK
  against that cwd, wrap the command as `env K=V… <bounded_shell_argv>` using
  `native_command_environment(task_cwd)`; never call `protected_argv`.
- Native file-tool branch: `validate_native_write_path(cwd, target)` for every path the tool
  input carries (Write/Edit/MultiEdit `file_path`, NotebookEdit `notebook_path`); malformed → deny.
- `main()` reads the backend from the environment; an unknown value yields a deny response.
- Tests in `test_worktree_environment.py`.

**NOT in scope**: changes to `protected_argv`, `validate_write_path`, guard/RTK/timeout helpers;
dispatcher/launcher wiring (TASK-4888/4889).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` | MODIFY | `hook_response(..., backend=)`, `main()` backend selection |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | Native-branch tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Inside worktree_environment.py — lazy dual import of the TASK-4885 module, same pattern as
# _load_guard_bash (:295-307). Do it inside the native branch only, so the legacy path never
# depends on the new module.
if __package__:
    from . import native_claude_sandbox as native
else:
    import native_claude_sandbox as native
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py
def validate_write_path(cwd: Path, path: Path) -> None: ...                         # :96
def protected_argv(cwd: Path, argv: Sequence[str]) -> list[str]: ...                # :228 (legacy only)
def _scope_guard(command: str, cwd: Path) -> tuple[str, str | None]: ...            # :336
def bounded_shell_argv(command: str, tool_input: dict[str, Any]) -> list[str]: ...  # :424
def rtk_rewrite(command: str) -> str | None: ...                                    # :463
def hook_response(payload: dict[str, Any]) -> dict[str, Any]:                       # :502 (anchor, 1 occurrence)
def main() -> None:                                                                 # :534 (anchor, 1 occurrence)
# From TASK-4885 (native_claude_sandbox.py):
BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"; BACKEND_NATIVE = "claude-native"; BACKEND_BUBBLEWRAP = "bubblewrap"
def native_task_cwd(session_cwd: Path, command: str) -> Path: ...
def native_command_environment(cwd: Path) -> dict[str, str]: ...
def validate_native_write_path(cwd: Path, path: Path) -> None: ...
```

### Does NOT Exist
- ~~`hook_response(payload, backend=...)`~~ — the keyword is added by this task.
- ~~a `--backend` CLI flag on the hook~~ — the backend comes from the environment only (spec §2 overview).
- ~~`protected_argv(..., native=True)`~~ — do not add a native mode to `protected_argv`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#hook_response",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#main",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#_scope_guard",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#bounded_shell_argv",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#rtk_rewrite",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#validate_write_path"
  ]
}
```

---

## Implementation Notes

- The hook payload `cwd` is the parent session's cwd, also for native `Agent` children (preflight
  Q2); `native_task_cwd` is the only way to reach a coder's sub-worktree.
- Keep `|| exit 2` semantics: any exception → `permissionDecision="deny"`, never an empty success.
- Keep `timeout`/`run_in_background`/`description` fields: spread `**tool_input` as today.
- Native env application: build `["env", *(f"{k}={v}" for k, v in env.items()), *bounded_shell_argv(...)]`
  and `shlex.join` it — the native sandbox wraps the whole thing; do not export into the host.

---

## Implementation Blueprint

### Steps (in order)
1. Change `hook_response`'s signature and split the Bash branch into legacy/native — *why*: the
   legacy branch must stay byte-identical (AC9).
2. Add the native file-tool branch — *why*: native shell policy does not protect file tools (policy 3).
3. Update `main()` to pass the environment backend — *why*: the launcher's env is the only selector.
4. Add tests — *why*: prove no bwrap in native mode and unchanged legacy output.

### `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cxF 'def hook_response(payload: dict[str, Any]) -> dict[str, Any]:' worktree_environment.py)
# REPLACE the signature line (verified: worktree_environment.py:502) and its body through
# `return {"hookSpecificOutput": output}` (:531) with:
def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]:
    """Apply guards and file checks; omit bwrap only for explicit claude-native mode; deny invalid modes."""
    cwd = Path(payload["cwd"])
    tool_input = payload["tool_input"]
    output: dict[str, Any] = {"hookEventName": "PreToolUse"}
    try:
        if backend not in ("bubblewrap", "claude-native"):
            raise ValueError(f"Unknown SDD sandbox backend {backend!r}; refusing to run")
        native = None
        if backend == "claude-native":
            if __package__:
                from . import native_claude_sandbox as native
            else:  # run as a script: this file's directory is sys.path[0]
                import native_claude_sandbox as native
        if payload["tool_name"] == "Bash":
            command = tool_input["command"]
            if not isinstance(command, str) or not command:
                raise ValueError("Bash command must be a non-empty string")
            task_cwd = native.native_task_cwd(cwd, command) if native else cwd
            action, value = _scope_guard(command, task_cwd)
            if action == "block":
                raise ValueError(value or "over-broad pytest blocked by the test-scope guard")
            if action in ("rewrite", "verdict") and value:
                command = value
            if optimized := rtk_rewrite(command):
                command = optimized
            shell = bounded_shell_argv(command, tool_input)
            if native:
                env = native.native_command_environment(task_cwd)
                wrapped = ["env", *(f"{key}={value}" for key, value in env.items()), *shell]
            else:
                wrapped = protected_argv(cwd, shell)
            output["updatedInput"] = {**tool_input, "command": shlex.join(wrapped)}
        else:
            path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if not isinstance(path, str):
                raise ValueError("File tool requires a path")
            # FILL IN: native → native.validate_native_write_path(cwd, cwd / path); legacy →
            # validate_write_path(cwd, cwd / path) exactly as today — bounded by policy 3, AC9
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        output.update(permissionDecision="deny", permissionDecisionReason=str(exc))
    return {"hookSpecificOutput": output}
```
**Why**: the legacy path keeps calling `_scope_guard(command, cwd)` and `protected_argv(cwd, …)`
(with `task_cwd == cwd`), so its output does not change. Keep the existing inline comments of the
original body (guard-before-RTK note, "Preserve timeout/background/description…").
`native` is shadowed by the import only in native mode; rename to `native_mod` if ruff flags it.

### `worktree_environment.py` — `main()` (MODIFY)
```python
# occurrences: 1 (verified: grep -cxF 'def main() -> None:' worktree_environment.py) — :534
# CHANGE inside main() (verified: worktree_environment.py:540, 1 occurrence): `result = hook_response(json.load(sys.stdin))` becomes:
        backend = os.environ.get("PARROT_SDD_SANDBOX_BACKEND") or "bubblewrap"
        result = hook_response(json.load(sys.stdin), backend=backend)
```
**Why**: missing metadata keeps the legacy wrapper; an unknown value reaches `hook_response`,
which denies (spec §2 overview). Do not import `native_claude_sandbox` at module scope.

### `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` (MODIFY)
```python
# Append at end of file (last test is test_real_rtk_cannot_write_its_trust_store_from_the_sandbox, :802)
# FILL IN: tests from Test Specification; build a linked worktree under tmp_path (or reuse the
# conftest `linked_worktree` fixture from TASK-4886) so native helpers accept the cwd
```

### FILL IN checklist
- [ ] native/legacy file-tool split; bounded by policy 3 and AC9
- [ ] tests from Test Specification

---

## Acceptance Criteria

- [ ] `backend="claude-native"`: the rewritten command contains no `bwrap`, starts with `env`, and carries the task worktree's `PYTHONPATH`.
- [ ] Legacy (`backend` omitted or `"bubblewrap"`): output identical to today for the same payload.
- [ ] Unknown backend, malformed command, disallowed `cd` prefix → `permissionDecision="deny"`.
- [ ] Guard runs before RTK and both see the task cwd; timeout/background fields preserved.
- [ ] Native file tools: allowed task file passes; `.git/config`, shared `.venv` alias and hook files denied.
- [ ] `main()` with `PARROT_SDD_SANDBOX_BACKEND=claude-native` produces the native rewrite (subprocess test, `python3 -S`).
- [ ] Existing tests in the file still pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`

---

## Test Specification

```python
def test_native_hook_retains_operational_guards(tmp_path: Path) -> None:
    """Scope/RTK/backstop/environment behavior without an inserted bwrap wrapper."""

def test_native_hook_uses_cd_prefix_task_cwd(tmp_path: Path) -> None:
    """`cd <pool worktree> && pytest x` → PYTHONPATH of the pool worktree, guard rooted there."""

def test_legacy_hook_output_unchanged(checkout: tuple[Path, Path]) -> None:
    """hook_response(p) == hook_response(p, backend='bubblewrap'); contains bwrap."""

@pytest.mark.parametrize("backend", ["", "none", "CLAUDE-NATIVE", "docker"])
def test_unknown_backend_denies(checkout: tuple[Path, Path], backend: str) -> None: ...

def test_native_file_tool_denies_control_paths(tmp_path: Path) -> None: ...

def test_main_reads_backend_from_environment(tmp_path: Path) -> None: ...
```

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4885 and TASK-4886 are `done` in the index.
2. Verify the contract (anchors at :502 and :534), mark in progress.
3. Implement from the blueprint; run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4887 sdd-claude-native-sandbox verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
