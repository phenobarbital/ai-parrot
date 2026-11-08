# TASK-5351: Launcher preflight for Google — snap refusal and fail-closed worker sandbox

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, "Snap refusal" and "Worker sandbox (fail-closed)". Before `feature_launcher` can start
`agy` (TASK-5352/5353), it needs two host-side checks that never touch Claude's native-sandbox preflight:
1. refuse an `agy` that resolves into the community snap, printing the official install command;
2. select the Google worker's sandbox — always Bubblewrap — and fail before AGY starts when it cannot run, when
   `--sandbox off` is asked for, or when a network-domain restriction is configured (Bubblewrap does not
   isolate the network).

This task adds those helpers only; wiring them into `launch()`/`launch_session()` is TASK-5352/5353.

---

## Scope

- Add to `feature_launcher.py`: `OFFICIAL_AGY_INSTALL`, `resolve_agy()`, `agy_is_snap()`,
  `require_official_agy()`, `google_worker_sandbox()`.
- Tests in `test_sdd_launch.py`.

**NOT in scope**: exec'ing `agy` and environment building (TASK-5352); `launch()`/`main()`/tmux wiring and the
hook prerequisite (TASK-5353); CLI options (TASK-5354); any change to the Claude path or `native_claude_sandbox`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | Google preflight helpers |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | snap / sandbox preflight tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09).

### Verified Imports
```python
# feature_launcher.py is stdlib-only for its tmux child (runs under `python -S`); module imports lines 10-26:
import argparse, json, os, re, shutil, subprocess, sys, time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from . import native_claude_sandbox, worktree_environment   # (bare `import native_claude_sandbox` in the child)
# tests (test_sdd_launch.py:13-16)
from parrot.flows.dev_loop import feature_launcher as launcher
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py
class LaunchError(Exception):                                   # line 50 — LaunchError(exit_code: int, message: str), .exit_code
def _preflight_sandbox(worktree: Path, allowed_domains: Sequence[str]) -> None:   # line 94 — Claude-only; NOT used for Google
# packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py (reached as launcher.native_claude_sandbox)
SANDBOX_MODES = ("required", "preferred", "off", "legacy")      # line 38
MODE_ENV = "PARROT_SDD_SANDBOX_MODE"                             # line 36
BACKEND_BUBBLEWRAP = "bubblewrap"                                # line 33
def sandbox_platform() -> str:                                   # line 45 — "linux" | "macos" | "windows" | "unsupported"
def _bwrap_probe(executable: str) -> tuple[bool, str]:           # line 306 — (usable, reason)
# packages/ai-parrot/tests/sdd/test_sdd_launch.py
#   autouse fixtures: _restore_sandbox_mode (line 21), _no_real_sandbox_probe (line 531, patches _preflight_sandbox)
```

### Does NOT Exist
- ~~A snap sandbox backend / `--sandbox snap`~~ — dropped in spec v0.3; the snap is refused outright.
- ~~`native_claude_sandbox.agy_*` helpers~~ — all Google helpers live in `feature_launcher.py`.
- ~~Network isolation in the Bubblewrap wrapper~~ — hence domain restrictions are refused for Google.

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
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#LaunchError",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#sandbox_platform",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_bwrap_probe"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Stdlib only (the module runs as a `python -S` script in the tmux child).
- Exit codes follow the module's convention: `2` for policy/usage refusals (snap, `off`, domains, bad mode),
  `1` for host prerequisites (no `agy`, no `bwrap`, failed probe, unsupported platform).
- `required`, `legacy`, `preferred` and an unset mode all select Bubblewrap; `preferred` still fails closed.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the helpers directly below `_preflight_sandbox` — *why*: keeps all preflight code together.
2. Write the tests (mock `shutil.which`, `Path.resolve`/symlinks in `tmp_path`, `sandbox_platform`, `_bwrap_probe`).

### `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _preflight_sandbox(worktree: Path, allowed_domains: Sequence\[str\]) -> None:') — line 94
# AFTER — insert below the body of `_preflight_sandbox` (it ends with `... refusing to launch") from exc`):
OFFICIAL_AGY_INSTALL = "curl -fsSL https://antigravity.google/cli/install.sh | bash"


def resolve_agy() -> Path:
    """Locate the ``agy`` the launch would exec; LaunchError(1) when it is not on PATH."""
    found = shutil.which("agy")
    if found is None:
        raise LaunchError(1, f"missing host prerequisite(s): agy — install the official build: {OFFICIAL_AGY_INSTALL}")
    return Path(found)


def agy_is_snap(agy: Path) -> bool:
    """True when ``agy`` resolves into ``/snap/`` or is the ``snap run`` wrapper (``/usr/bin/snap``)."""
    # FILL IN: True when str(agy) or str(agy.resolve()) starts with "/snap/", or agy.resolve().name == "snap";
    #   also True for a small text wrapper (read at most 4 KiB, ignore unreadable/binary content) that contains
    #   "snap run" — bounded by spec §3 M3 "resolves (after shutil.which and symlink resolution) into /snap/ or
    #   is the snap run wrapper".
    return False


def require_official_agy(agy: Path) -> None:
    """LaunchError(2) for the community snap, naming the official install command."""
    if agy_is_snap(agy):
        raise LaunchError(
            2,
            f"{agy} is the community antigravity-cli snap, which cannot run the SDD flow (no project Python, "
            f"bwrap or ssh inside its confinement). Install the official agy instead: {OFFICIAL_AGY_INSTALL}",
        )


def google_worker_sandbox(sandbox: str | None, allowed_domains: Sequence[str]) -> str:
    """Return the Google worker's sandbox backend (always Bubblewrap) or raise LaunchError before agy starts."""
    mode = (sandbox or "required").strip().lower()
    if mode == "off":
        raise LaunchError(2, "--sandbox off is not allowed for the unattended Google worker")
    if mode not in native_claude_sandbox.SANDBOX_MODES:
        raise LaunchError(2, f"invalid sandbox mode: {sandbox}")
    if allowed_domains:
        raise LaunchError(
            2,
            "network domain restrictions are not supported with --host google (the Bubblewrap wrapper does not "
            "isolate the network); remove --sandbox-allow-domain and the configured domains",
        )
    # FILL IN: sandbox_platform() != "linux" -> LaunchError(1, ...); shutil.which("bwrap") None -> LaunchError(1, ...);
    #   _bwrap_probe(path) not ok -> LaunchError(1, f"Bubblewrap probe failed ({reason}); refusing to launch agy")
    #   — bounded by spec §3 M3 "missing Bubblewrap, unsupported platforms and failed capability probes fail
    #   before AGY starts".
    return native_claude_sandbox.BACKEND_BUBBLEWRAP
```
**Why this shape**: each check is a pure helper raising `LaunchError`, so `launch()` (TASK-5353) and
`launch_session()` (TASK-5352) can call them before any host preparation and map them to exit codes.

### `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)
```python
# AFTER — append at end of file
def test_google_snap_agy_is_refused_with_install_command(tmp_path: Path) -> None:
    with pytest.raises(launcher.LaunchError) as error:
        launcher.require_official_agy(Path("/snap/bin/agy"))
    assert error.value.exit_code == 2
    assert launcher.OFFICIAL_AGY_INSTALL in str(error.value)


# FILL IN tests (one function each):
#  - agy_is_snap: a symlink in tmp_path pointing into a fake "/snap/..." path (monkeypatch Path.resolve or use a
#    resolved-name check), a text wrapper containing "snap run", and a plain executable -> True, True, False
#  - resolve_agy with which -> None -> LaunchError exit 1 naming the install command
#  - google_worker_sandbox: "off" -> exit 2; "bogus" -> exit 2; domains -> exit 2; None/"required"/"legacy"/
#    "preferred" with platform linux + which bwrap + probe ok -> "bubblewrap"; platform "macos" -> exit 1;
#    which bwrap None -> exit 1; probe (False, "userns denied") -> exit 1 mentioning the reason
```

### FILL IN checklist
- [ ] `agy_is_snap`; bounded by spec §3 M3
- [ ] `google_worker_sandbox` host checks; bounded by spec §3 M3
- [ ] the listed tests

---

## Acceptance Criteria

- [ ] An `agy` resolving into `/snap/` (or the `snap run` wrapper) is refused with the official install command.
- [ ] `google_worker_sandbox` returns `"bubblewrap"` for every non-`off` mode and fails closed (exit 1/2) for `off`, bad modes, domains, non-Linux, missing `bwrap` and failed probes.
- [ ] No Claude-path behaviour changes; all existing launch tests pass; `ruff check` clean.

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
9. **Close the task** with `parrot sdd task close TASK-5351 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
