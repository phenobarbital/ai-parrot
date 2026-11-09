# TASK-5347: `agy_verdict()` — AGY worktree-environment guard and file containment

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (first bullet + "AGY file-write boundary") and §4 regression cases for
`test_worktree_environment.py`. PR #2040 (merged on `dev`) serves the single AGY hook
`parrot-sdd-permissions` through `agy_permissions.evaluate`, which knows nothing about the shared Python
environment, the PYTHONPATH convention, Bubblewrap or file writes. This task adds the **pure** function
`worktree_environment.agy_verdict()` that TASK-5348 merges into that hook. Claude Code's `hook_response`
stays byte-for-byte unchanged.

---

## Scope

- Add `agy_verdict(payload, *, root, backend, unattended)` to `worktree_environment.py` with the exact
  signature of spec §3 M1, plus its private helpers and `validate_agy_write_path()`.
- `run_command`: deny shared-environment mutations (`uv sync`, `uv pip install` into a shared env) found in
  any simple command; return a PYTHONPATH rewrite as `overwrite={"CommandLine": ...}`; in unattended mode with
  the `bubblewrap` backend, wrap the command in the existing Bubblewrap wrapper instead, and deny when `bwrap`
  is unreachable or the backend is anything else.
- `write_file` / `edit_file`: checkout containment (relative paths resolved against the checkout, canonical
  paths, symlink ancestors of new files followed, `.git` and shared environments denied); deny a file tool
  with no identifiable `Path`.
- Deny missing or ambiguous `workspacePaths`.
- Write the tests below in `test_worktree_environment.py`.

**NOT in scope**: `agy_permissions.py`, `agy_hook.sh` (TASK-5348); the installer matcher (TASK-5349);
reading environment variables (the caller passes `backend` and `unattended`); any Claude-path change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | `agy_verdict`, `validate_agy_write_path` and private helpers |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | `agy_verdict` rewrite / bwrap / containment / workspace tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09). This file is unchanged by PR #2040.

### Verified Imports
```python
# worktree_environment.py is stdlib-only (lines 9-18) and must stay so (spec §7):
import argparse, json, math, os, shlex, shutil, subprocess, sys
from pathlib import Path
from typing import Any, Sequence          # add Literal to this import for the agy_verdict return type
# tests (test_worktree_environment.py:18):
from parrot.flows.dev_loop import worktree_environment as policy   # compatibility shim re-exporting the module
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py
def repository_paths(cwd: Path) -> tuple[Path, Path | None]:                      # line 54
def shared_environments(cwd: Path) -> tuple[Path, ...]:                            # line 75
def validate_write_path(cwd: Path, path: Path) -> None:                            # line 96 — ValueError(POLICY_MESSAGE)
def command_policy_error(cwd: Path, argv: Sequence[str]) -> str | None:            # line 103 — uv mutation policy
def protected_argv(cwd: Path, argv: Sequence[str], *, derive_pythonpath: bool = False) -> list[str]:  # line 299 — RuntimeError if no bwrap
def derived_pythonpath_assignment(root: Path) -> str:                              # line 377 — shell-substitution form
_COMPOUND_MARKERS = ("&&", "||", ";", "|")                                         # line 412
def bounded_shell_argv(command: str, tool_input: dict[str, Any]) -> list[str]:     # line 525
def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]:  # line 783 — UNCHANGED
#   _wrap_bash, lines 705-709 — the Bubblewrap "outside" branch to mirror:
#       if (root / "packages").is_dir() and any((root / "packages").glob("*/src")):
#           outside = f"{derived_pythonpath_assignment(root)} {shlex.join(protected_argv(cwd, shell, derive_pythonpath=True))}"
#       else:
#           outside = shlex.join(protected_argv(cwd, shell))

# packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
def checkout(tmp_path: Path) -> tuple[Path, Path]:   # line 40 fixture: (pool worktree with a .venv symlink, shared env)
```

### Does NOT Exist
- ~~`agy_verdict`, `validate_agy_write_path`~~ — created by this task.
- ~~A `cwd` field in the AGY payload~~ — the checkout comes from `workspacePaths` (validated) and the `root` argument.
- ~~Environment reads inside `agy_verdict`~~ — `backend`/`unattended` are parameters; the function is pure.
- ~~An observed `edit_file` argument schema~~ — only `Path` identifies a target (spec §3 M1).
- ~~File-tool exceptions for the ledger, coder evidence or Git admin dirs~~ — those exist only for guarded commands.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#repository_paths",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#validate_write_path",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#command_policy_error",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#protected_argv",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#derived_pythonpath_assignment",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#bounded_shell_argv"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Stdlib only. Return `("deny", reason, None)` instead of raising; catch `(OSError, ValueError, RuntimeError, KeyError, TypeError)`.
- **Interactive PYTHONPATH rewrite uses a literal value, not `derived_pythonpath_assignment()`** — because AGY
  evaluates permission rules against the rewritten command, and the `$(printf … | sed …)` substitution adds
  `printf`/`sed` subcommands no managed rule may cover. Leading `VAR=value` assignments are ignored by the rules
  (PR #2040 finding), so a literal `PYTHONPATH=<abs>:<abs>${PYTHONPATH:+:$PYTHONPATH}` prefix is safe.
- **Bubblewrap only when `unattended and backend == "bubblewrap"`** — a `bwrap … --` prefix in interactive mode
  would defeat PR #2040's allow-rules (spec §3 M1).
- Never use `os.getcwd()`: the hook process cwd is `.agents/`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `Literal` to the `typing` import — *why*: the fixed return type uses it.
2. Insert the helpers, `validate_agy_write_path` and `agy_verdict` directly above `def hook_response(` — *why*: they reuse the module's guard helpers and leave `hook_response` untouched.
3. Write the tests — *why*: spec §4 lists them as required regression cases.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def hook_response(payload: dict\[str, Any\], \*, backend: str = "bubblewrap")') — line 783
# BEFORE — insert above `def hook_response(...)`:
AGY_FILE_TOOLS = frozenset({"write_file", "edit_file"})


def _agy_checkout(payload: dict[str, Any], root: Path) -> Path:
    """The checkout named by the payload's single workspace; ValueError when missing, ambiguous or not ``root``."""
    paths = payload.get("workspacePaths")
    # FILL IN: require a list with exactly ONE absolute str naming an existing directory; its repository_paths()[0]
    #   must resolve to the same directory as repository_paths(root)[0]; else raise ValueError naming the problem —
    #   bounded by spec §3 M1 "reject missing or ambiguous workspace context".
    return repository_paths(root)[0]


def _agy_command_policy(cwd: Path, command: str) -> None:
    """ValueError when any simple command in ``command`` mutates a shared environment."""
    # FILL IN: split on _COMPOUND_MARKERS, shlex.split each segment (skip one that does not parse), raise
    #   ValueError(error) for the first command_policy_error(cwd, words) that is not None — bounded by spec test
    #   `test_worktree_env_agy_verdict_rewrite` ("denies uv sync").


def _literal_pythonpath(checkout: Path) -> str | None:
    """``PYTHONPATH=<abs src dirs>${PYTHONPATH:+:$PYTHONPATH}`` for a ``packages/*/src`` checkout, else None."""
    sources = sorted(str(p) for p in (checkout / "packages").glob("*/src") if p.is_dir())
    if not sources:
        return None
    return "PYTHONPATH=" + shlex.quote(":".join(sources)) + "${PYTHONPATH:+:$PYTHONPATH}"


def validate_agy_write_path(checkout: Path, raw_path: str) -> Path:
    """Confine an Antigravity file-tool target to ``checkout``; return the canonical target or raise ValueError."""
    root = checkout.resolve()
    candidate = Path(raw_path) if Path(raw_path).is_absolute() else root / raw_path
    target = candidate.resolve()  # non-strict: follows existing symlink ancestors of a new file
    if target == root or not target.is_relative_to(root):
        raise ValueError(f"Antigravity file write outside the active checkout {root}: {raw_path}")
    # FILL IN: raise ValueError when target.relative_to(root).parts[0] == ".git" — bounded by spec §3 M1
    #   ("Git administration ... must use guarded commands").
    validate_write_path(root, target)
    return target


def agy_verdict(
    payload: dict[str, Any], *, root: Path, backend: str, unattended: bool
) -> tuple[Literal["deny", "ask"], str, dict[str, str] | None]:
    """Return (decision, reason, overwrite) for one AGY PreToolUse payload against checkout ``root``."""
    try:
        checkout = _agy_checkout(payload, root)
        call = payload["toolCall"]
        name, args = call.get("name"), call.get("args")
        if not isinstance(args, dict):
            raise ValueError("Antigravity toolCall.args must be an object")
        if name in AGY_FILE_TOOLS:
            target = args.get("Path")
            if not isinstance(target, str) or not target:
                raise ValueError(f"{name} has no target path the guard can identify")
            validate_agy_write_path(checkout, target)
            return "ask", "", None
        if name != "run_command":
            return "ask", "", None
        command = args.get("CommandLine")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("run_command CommandLine must be a non-empty string")
        # FILL IN: cwd = checkout, or checkout joined with args["Cwd"] when given; a Cwd outside the checkout returns
        #   ("ask", "", None) — the PR #2040 policy force_asks it — bounded by test_agy_permissions.py
        #   ::test_cwd_argument_outside_workspace (must stay "force_ask").
        cwd = checkout
        _agy_command_policy(cwd, command)
        if unattended:
            if backend != "bubblewrap":
                raise ValueError("unattended agy requires PARROT_SDD_SANDBOX_BACKEND=bubblewrap")
            # FILL IN: shell = bounded_shell_argv(command, {}); mirror _wrap_bash lines 705-709 (outside branch)
            #   for `checkout`/`cwd`; return ("ask", "", {"CommandLine": wrapped}) — protected_argv raises
            #   RuntimeError without bwrap, which the except turns into a deny (never run unwrapped).
            raise RuntimeError("bubblewrap wrapper not implemented")
        prefix = _literal_pythonpath(checkout)
        if prefix is None or command.startswith(prefix):
            return "ask", "", None
        return "ask", "", {"CommandLine": f"{prefix} {command}"}
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return "deny", str(exc), None
```
**Why this shape**: one pure function per AGY event keeps `agy_permissions` (TASK-5348) as the only process
entry point (spec §2: one hook keeps the decision combination deterministic). `overwrite` carries only
`CommandLine` because AGY merges it shallowly into args that also hold `WaitMsBeforeAsync`/`toolSummary`.

### `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` (MODIFY)
```python
# AFTER — append at end of file (reuse `policy`, line 18, and the `checkout` fixture, line 40)
def _agy(workspaces: list[Path] | None, name: str = "run_command", **args: Any) -> dict[str, Any]:
    """An Antigravity PreToolUse event as captured from agy 1.5.3."""
    payload: dict[str, Any] = {"conversationId": "c1", "stepIdx": 1, "toolCall": {"name": name, "args": args}}
    if workspaces is not None:
        payload["workspacePaths"] = [str(w) for w in workspaces]
    return payload


def test_worktree_env_agy_verdict_rewrite(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "packages" / "core" / "src").mkdir(parents=True)
    decision, _reason, overwrite = policy.agy_verdict(
        _agy([repo], CommandLine="pytest tests/test_x.py -q"), root=repo, backend="bubblewrap", unattended=False
    )
    assert decision == "ask"
    assert overwrite is not None and set(overwrite) == {"CommandLine"}
    assert overwrite["CommandLine"].startswith("PYTHONPATH=") and overwrite["CommandLine"].endswith("pytest tests/test_x.py -q")
    assert "printf" not in overwrite["CommandLine"]  # literal value, no substitution (rules see the rewrite)


# FILL IN tests (one function each):
#  - "uv sync" and "cd sub && uv pip install x" -> ("deny", <reason>, None)
#  - a repo without packages/*/src -> ("ask", "", None); a command already carrying the prefix is not re-prefixed
#  - test_worktree_env_agy_verdict_bwrap: monkeypatch policy.shutil.which -> "/usr/bin/bwrap"; unattended=True,
#    backend="bubblewrap" -> overwrite CommandLine contains the bwrap argv ending ["/bin/bash", "-c", <cmd>]
#    (possibly inside `timeout`); which -> None -> "deny"; unattended=True with backend="auto" -> "deny";
#    unattended=False never contains "bwrap"
#  - containment (write_file Path/Content/Overwrite and edit_file): inside (relative + absolute) -> ask;
#    "../outside.txt", absolute external path, symlink escape incl. a NEW file below a symlinked parent,
#    ".venv/editable.pth" via the fixture's alias, a real shared .venv inside a primary checkout, ".git/config"
#    -> deny; edit_file without Path -> deny
#  - workspacePaths missing / [] / two entries / relative / pointing at another repo than `root` -> deny
#  - non-AGY tools (e.g. "view_file") -> ("ask", "", None)
#  - Claude hook_response output unchanged: a Bash payload with a monkeypatched bwrap still returns
#    hookSpecificOutput.updatedInput exactly as before (compare with the existing helper expectations)
```

### FILL IN checklist
- [ ] `_agy_checkout` — single-workspace rule; bounded by spec §3 M1
- [ ] `_agy_command_policy` — per-segment uv policy; bounded by `test_worktree_env_agy_verdict_rewrite`
- [ ] `validate_agy_write_path` — `.git` denial; bounded by spec §3 M1
- [ ] `agy_verdict` Cwd handling; bounded by `test_cwd_argument_outside_workspace`
- [ ] `agy_verdict` unattended Bubblewrap branch; bounded by spec §3 M1 and `test_worktree_env_agy_verdict_bwrap`
- [ ] the listed tests

---

## Acceptance Criteria

- [ ] `agy_verdict` has exactly the spec §3 M1 signature and is importable via the `policy` shim.
- [ ] Shared-environment mutations and every containment escape return `"deny"`; checkout-local writes return `"ask"`.
- [ ] Interactive rewrites are a literal PYTHONPATH prefix; unattended + bubblewrap wraps in `bwrap`; unattended without a reachable `bwrap` or without the bubblewrap backend denies.
- [ ] Missing/ambiguous workspaces deny; Claude `hook_response` behaviour and all pre-existing tests are unchanged.
- [ ] `ruff check` is clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint: `test_worktree_env_agy_verdict_rewrite` is complete; each
`FILL IN` bullet is one more function built with `_agy()` and, where useful, the `checkout` fixture.

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
9. **Close the task** with `parrot sdd task close TASK-5347 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-terra (codex), 2 attempts
**Date**: 2026-11-09
**Notes**: agy_verdict() worktree-env guard + containment in worktree_environment.py with tests. Merge-tier validation green (chunk 0: 549 passed, 10 skipped; asset sync 27 passed).

**Deviations from spec**: none
