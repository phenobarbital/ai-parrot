# TASK-4885: Native sandbox policy compiler

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 M1 (first half), §2 policy decisions 1, 2, 4, 5, 6. Every other module consumes the
stdlib-only policy module this task creates: the hook (TASK-4887), the dispatcher (TASK-4888)
and the interactive launcher (TASK-4889). It compiles the strict `--settings` object, the
per-command environment, the native file-write validator and the leading-`cd` task-cwd rule.
Preflight evidence for the decisions: `sdd/state/FEAT-768/native-sandbox-preflight.md`.

---

## Scope

- Create `native_claude_sandbox.py` (standard library only, importable both as
  `parrot.flows.dev_loop.native_claude_sandbox` and as a top-level module when the hook runs as a
  script with its directory on `sys.path[0]`).
- Implement `validate_allowed_domains`, `native_sandbox_settings`, `native_command_environment`,
  `validate_native_write_path`, `native_task_cwd`, plus the constants listed in the blueprint.
- Write the deterministic unit tests in `test_native_claude_sandbox.py`.

**NOT in scope**: the hook routing in `worktree_environment.py` (TASK-4887), dispatcher wiring
(TASK-4888), `launch_worker()`/`main()` CLI (TASK-4889 adds them to this same file), any live
Claude call (TASK-4890/4891), documentation (TASK-4892). Do not modify `worktree_environment.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py` | CREATE | Policy compiler, env builder, write validator, task-cwd rule |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | CREATE | Deterministic unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Package import (tests, dispatcher):
from parrot.flows.dev_loop import worktree_environment  # verified: dispatchers/claude.py:66
# Inside native_claude_sandbox.py — dual import, mirrors worktree_environment._load_guard_bash (:295-307):
if __package__:
    from . import worktree_environment as _we
else:  # run as a script: this file's directory is sys.path[0]
    import worktree_environment as _we
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py
def existing_directory(path: Path) -> Path: ...                                   # :28
def repository_paths(cwd: Path) -> tuple[Path, Path | None]: ...                  # :54  (root, common git dir)
def shared_environments(cwd: Path) -> tuple[Path, ...]: ...                       # :75
def validate_write_path(cwd: Path, path: Path) -> None: ...                       # :96  (UNCHANGED, legacy)
WORKTREE_ADMIN_DIR = Path(".claude") / "worktrees"                               # :139
SHARED_LEDGER_DIR = Path(".parrot") / "ledger"                                   # :143
CLAUDE_SCRATCH_ROOT = Path("/tmp") / f"claude-{os.getuid()}"                     # :149
def worktree_admin_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]: ... # :152
def shared_ledger_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]: ...  # :182
def claude_scratch_root() -> Path: ...                                            # :211 (mkdir 0o700, resolves)
POLICY_MESSAGE: str                                                               # :20
# protected_argv (:228) shows the legacy env contract to mirror:
#   XDG_CACHE_HOME, UV_CACHE_DIR, UV_NO_SYNC=1, PYTHONDONTWRITEBYTECODE=1,
#   PYTHONPATH = sorted(root/"packages"/*/src) + inherited PYTHONPATH
```

Repository facts: a linked worktree has a `.git` *file* (`gitdir: <admin>`); `repository_paths`
returns `(root, common_git_dir)` and `common_git_dir.parent` is the primary checkout. A primary
checkout has `root == common_git_dir.parent`.

### Does NOT Exist
- ~~`native_claude_sandbox.py`~~ — does not exist yet; this task creates it.
- ~~`worktree_environment.validate_native_write_path` / `native_command_environment`~~ — live in the new module, not in `worktree_environment.py`.
- ~~`worktree_environment.RTK_DATA_DIR`~~ or any RTK trust-store path constant — not defined; resolve RTK's data dir yourself (see FILL IN).
- ~~A Claude settings key that locks project/local sandbox settings~~ — none is used; preflight showed none is needed.
- ~~`sandbox.filesystem.allowWrite` granting `/tmp`~~ — never grant general host `/tmp`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#existing_directory",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#repository_paths",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#shared_environments",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#worktree_admin_dirs",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#shared_ledger_dirs",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#claude_scratch_root"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Standard library only. No Pydantic, no `parrot` package-level import (the hook runs as a script).
- Pure functions: never mutate `os.environ`; no subprocess/network calls while compiling policy.
- Errors: `ValueError` for invalid input/roots/domains; `RuntimeError` reserved for missing host
  prerequisites (not raised in this task — TASK-4889 checks them).
- Strict settings shape (spec §2 overview): `sandbox.enabled=true`, `failIfUnavailable=true`,
  `allowUnsandboxedCommands=false`, `excludedCommands=[]`, `allowNestedUserNamespaces=false`,
  `network.allowAllUnixSockets=false`, explicit `network.allowedDomains`, explicit
  `filesystem.allowWrite` and `filesystem.denyWrite`. Emit EVERY key explicitly (spec policy 7).
- Never copy the preflight's relaxed `allowAllUnixSockets: true` into production.

### References in Codebase
- `worktree_environment.protected_argv` — the legacy writable/read-only path set to mirror.
- `sdd/state/FEAT-768/native-sandbox-preflight.md` — observed native behavior.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module with the dual import of `worktree_environment` — *why*: the hook imports
   this module as a script sibling; a package-relative import alone would fail there.
2. Implement `validate_allowed_domains` first — *why*: `native_sandbox_settings` must reject bad
   domains before building anything (spec policy 6).
3. Implement `_native_roots(cwd)` and the root check — *why*: one place decides "linked worktree
   with valid Git metadata" (policy 2) for settings, env, write validation and task cwd.
4. Implement `native_sandbox_settings`, then `validate_native_write_path`, `native_task_cwd`,
   `native_command_environment` — *why*: each reuses `_native_roots`.
5. Write the tests listed under Test Specification with fixture repos in `tmp_path` — *why*:
   positive controls prove each denial is meaningful (spec §4).

### `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py` (CREATE)
```python
"""Compile the strict Claude Code native sandbox policy for SDD sessions (FEAT-768).

Standard library only: the SDD PreToolUse hook imports this module as a script sibling.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re
import shlex
from typing import Any, Sequence

if __package__:
    from . import worktree_environment as _we
else:  # run as a script: this file's directory is sys.path[0]
    import worktree_environment as _we

BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"
BACKEND_NATIVE = "claude-native"
BACKEND_BUBBLEWRAP = "bubblewrap"
CACHE_DIR_ENV = "PARROT_SDD_CACHE_DIR"
_HOSTNAME_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_CD_PREFIX = re.compile(r"^\s*cd\s+(?P<target>\S+)\s*&&\s*(?P<rest>.+)$", re.DOTALL)


def validate_allowed_domains(domains: Sequence[str]) -> list[str]:
    """Normalize exact DNS hostnames; raise ValueError for URLs, wildcards, ports or IP literals."""
    normalized: list[str] = []
    for raw in domains:
        # FILL IN: reject non-str, "://", "/", "*", ":" (port), ipaddress.ip_address() successes,
        # empty labels and labels failing _HOSTNAME_LABEL; lower-case; strip one trailing "." —
        # bounded by spec policy 6 (exact hostnames only, no wildcard egress)
        host = raw
        if host not in normalized:
            normalized.append(host)
    return normalized


def _native_roots(cwd: Path) -> tuple[Path, Path, Path]:
    """Return (worktree root, common git dir, primary checkout); raise ValueError unless a linked worktree."""
    root, git_dir = _we.repository_paths(cwd)
    # FILL IN: raise ValueError when git_dir is None, when git_dir.parent == root (primary checkout,
    # even if a profile waives the root check — policy 2), or when the administration directory is
    # missing; never return the primary checkout as a writable root
    return root, git_dir, git_dir.parent


def _rtk_data_dir() -> Path:
    """Return RTK's data directory (holds the filter trust store) without importing RTK."""
    # FILL IN: XDG_DATA_HOME or ~/.local/share, joined with "rtk" — bounded by policy 1
    # (deny writes to the RTK trust store); a missing directory is still denied
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "rtk"


def _denied_write_paths(root: Path, git_dir: Path) -> list[str]:
    """Paths the native policy must keep read-only even under a broader Git grant."""
    # FILL IN: shared_environments(root); _rtk_data_dir(); git_dir/"hooks"; git_dir/"config";
    # git_dir/"config.lock"; per-worktree admin dir's "config.worktree" and "hooks" — bounded by
    # policy 1; list nonexistent paths too (canonical, os.path.abspath + resolve(strict=False))
    return []


def native_sandbox_settings(cwd: Path, *, allowed_domains: Sequence[str] = ()) -> dict[str, Any]:
    """Build strict CLI settings including hooks; raise ValueError for invalid roots/domains."""
    domains = validate_allowed_domains(allowed_domains)
    root, git_dir, _primary = _native_roots(cwd)
    allow_write = [str(root), str(git_dir), str(_we.claude_scratch_root())]
    allow_write += [str(path) for path in _we.worktree_admin_dirs(root, git_dir)]
    allow_write += [str(path) for path in _we.shared_ledger_dirs(root, git_dir)]
    hook_command = shlex.join(["python3", str(Path(_we.__file__).resolve()), "--hook"]) + " || exit 2"
    # FILL IN: dedupe allow_write preserving order — bounded by policy 1
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": [],
            "allowNestedUserNamespaces": False,
            "network": {"allowAllUnixSockets": False, "allowedDomains": domains},
            "filesystem": {"allowWrite": allow_write, "denyWrite": _denied_write_paths(root, git_dir)},
        },
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|Write|Edit|MultiEdit|NotebookEdit",
                    "hooks": [{"type": "command", "command": hook_command, "timeout": 10}],
                }
            ]
        },
    }
```
**Why this shape**: one compiler feeds both launch paths (G4); every security key is explicit
(policy 7); the hook command mirrors the dispatcher's existing `|| exit 2` fail-closed form.
TASK-4888 replaces `"python3"` with `sys.executable` only if its tests require it — do not change
the key layout. Do not grant the primary checkout, `$HOME` or `/tmp`.

### `native_claude_sandbox.py` — continued (same CREATE, second block)
```python
def validate_native_write_path(cwd: Path, path: Path) -> None:
    """Reject writes outside native allowances or into protected environment/control paths."""
    root, git_dir, _primary = _native_roots(cwd)
    target = Path(os.path.abspath(path)).resolve(strict=False)
    _we.validate_write_path(cwd, path)  # keep the legacy shared-environment denial
    # FILL IN: deny when target is under any _denied_write_paths entry, or under the policy/settings
    # and hook control files (this module, worktree_environment.py, .claude/settings*.json,
    # .claude/agents/*.md of root); allow only under the allow_write roots of native_sandbox_settings
    # — bounded by policy 3 (malformed input denies) and AC4 (symlink aliases)


def native_task_cwd(session_cwd: Path, command: str) -> Path:
    """Return the absolute `cd <path> &&` prefix target inside allowed roots, else session_cwd; raise ValueError for a disallowed or malformed prefix."""
    match = _CD_PREFIX.match(command)
    if match is None:
        if command.lstrip().startswith("cd "):
            raise ValueError("A leading cd must have the exact form 'cd <absolute path> && <command>'")
        return session_cwd
    # FILL IN: shlex.split the target (exactly one token, no expansion chars $ ` ~ *), require
    # absolute, resolve, require it to be a linked worktree whose primary checkout equals the
    # session's (via _native_roots), else ValueError — bounded by spec policy 4
    return session_cwd


def native_command_environment(cwd: Path) -> dict[str, str]:
    """Return task-cwd import/cache/safety overrides without mutating os.environ."""
    root, _git_dir, _primary = _native_roots(cwd)
    env = {"UV_NO_SYNC": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    source_roots = sorted((root / "packages").glob("*/src"))
    if source_roots:
        python_path = os.pathsep.join(map(str, source_roots))
        if inherited := os.environ.get("PYTHONPATH"):
            python_path += os.pathsep + inherited
        env["PYTHONPATH"] = python_path
    # FILL IN: XDG_CACHE_HOME / UV_CACHE_DIR under os.environ[CACHE_DIR_ENV] when set and inside
    # claude_scratch_root(); otherwise under claude_scratch_root()/"parrot-sdd-cache"/"shared-<uid>"
    # — bounded by spec policy 5 (never a shared host cache, never general /tmp)
    return env
```
**Why**: the task cwd rule exists because the hook payload `cwd` is always the parent session's
(preflight Q2). `native_command_environment` mirrors `protected_argv`'s `--setenv` set so imports
and caches behave identically to the legacy wrapper (AC5).

### `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` (CREATE)
```python
"""Deterministic FEAT-768 native policy tests (no Claude process, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop import native_claude_sandbox as native
from parrot.flows.dev_loop import worktree_environment as policy


@pytest.fixture(autouse=True)
def scratch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the scratch root inside tmp_path."""
    root = tmp_path / "claude-scratch"
    monkeypatch.setattr(policy, "CLAUDE_SCRATCH_ROOT", root)
    return root


@pytest.fixture
def linked(tmp_path: Path) -> tuple[Path, Path]:
    """Return (linked feature worktree, primary checkout) with a shared .venv and a sibling pool worktree."""
    # FILL IN: build main/.git (dir), main/.git/worktrees/{feat,pool} with commondir "../..",
    # main/.claude/worktrees/{feat,pool} checkouts with ".git" files, main/.venv/pyvenv.cfg,
    # main/.parrot/ledger, packages/x/src in feat — same layout as test_worktree_environment.checkout
    raise NotImplementedError
```
**Why**: fixtures, not the operator's real repo (spec §4 Integration Tests).

### FILL IN checklist
- [ ] `validate_allowed_domains` — exact-host rules; bounded by policy 6
- [ ] `_native_roots` — linked-worktree only; bounded by policy 2
- [ ] `_rtk_data_dir` / `_denied_write_paths` — control paths incl. nonexistent; bounded by policy 1
- [ ] `native_sandbox_settings` — dedupe allowWrite; bounded by policy 1
- [ ] `validate_native_write_path` — allow/deny matrix; bounded by policy 3, AC4
- [ ] `native_task_cwd` — exact prefix rule; bounded by policy 4
- [ ] `native_command_environment` — cache locations; bounded by policy 5
- [ ] tests — every row of Test Specification

---

## Acceptance Criteria

- [ ] Settings carry the strict booleans, empty `excludedCommands`, no nesting/all-socket grants, explicit domains and paths (spec §4 "Policy generation").
- [ ] Primary checkout cwd and non-repository cwd raise `ValueError`; linked feature and pool worktrees compile.
- [ ] Domains: empty default; case/trailing-dot normalization and dedupe; URL, wildcard, port, IPv4/IPv6 rejected.
- [ ] Write validator: task edits, scratch and admin dir allowed; shared venv (and its symlink alias), RTK data dir, Git `config`/`hooks`/`config.worktree`, policy/hook files and nonexistent paths under them denied.
- [ ] Task cwd: `cd <abs linked worktree> && x` selects it; relative, outside-root, other-primary, quoted/expanding and malformed prefixes raise; no prefix returns the session cwd.
- [ ] `native_command_environment` puts the task worktree's `packages/*/src` first in `PYTHONPATH`, sets `UV_NO_SYNC`/`PYTHONDONTWRITEBYTECODE`, keeps caches out of `~/.cache` and general `/tmp`, and leaves `os.environ` unchanged.
- [ ] The module imports with `python3 -S` as a script sibling (no `parrot` import).
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`

---

## Test Specification

```python
def test_native_settings_reject_widening_inputs(tmp_path: Path) -> None:
    """Malformed roots and invalid domains cannot produce a permissive launch."""

def test_settings_are_strict_and_explicit(linked: tuple[Path, Path]) -> None:
    """All security keys present; allowAllUnixSockets False; excludedCommands []."""

@pytest.mark.parametrize("bad", ["https://github.com", "*.github.com", "github.com:443", "10.0.0.1", "::1", ""])
def test_domain_rejected(linked: tuple[Path, Path], bad: str) -> None: ...

def test_write_matrix_positive_and_negative(linked: tuple[Path, Path]) -> None:
    """Task file allowed; .venv alias, .git/config, .git/hooks/x, config.worktree, RTK dir denied."""

def test_task_cwd_prefix_rules(linked: tuple[Path, Path]) -> None: ...

def test_environment_does_not_mutate_os_environ(linked: tuple[Path, Path]) -> None: ...

def test_module_imports_as_script_sibling() -> None:
    """subprocess: python3 -S -c 'import sys; sys.path.insert(0, <dir>); import native_claude_sandbox'."""
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-claude-native-sandbox --feature-id FEAT-768`).
2. Read the spec and `sdd/state/FEAT-768/native-sandbox-preflight.md`.
3. Verify the Codebase Contract, mark the task in progress in `sdd/tasks/index/sdd-claude-native-sandbox.json`.
4. Implement from the blueprint; complete every `FILL IN`; never change a signature.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4885 sdd-claude-native-sandbox verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
