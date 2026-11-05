# TASK-5123: Tmux notification environment and Stop-hook wiring

**Feature**: FEAT-793 — tmux worker completion notifications
**Spec**: `sdd/specs/tmux-notify-worker.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5122
**Assigned-to**: unassigned

## Context

Implement spec §3 M2. Only a newly launched tmux feature session receives completion metadata; native launch owns the existing per-session cache and additive host Stop hook.

## Scope

- Clear inherited notification variables in feature launch, then populate validated new-tmux metadata and an allowlisted base_env snapshot.
- Load the installed sibling helper by file path after cache allocation; append the five-second command hook and export absolute helper/interpreter paths only on success.
- Preserve signatures, direct exec, reattach behavior, existing hooks and every sandbox setting.

**NOT in scope**: helper receipt/delivery internals, worker prose, new CLI flags, launch brief/fix behavior, policy relaxation or startup-detector changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | Capture desktop environment for new tmux sessions |
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | Configure installed helper and additive Stop hook |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | Environment isolation and reattach regressions |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | Compiled settings and script-mode regressions |

## Codebase Contract (Anti-Hallucination)

Freshness checked on dev `cce37eb09570cda92d86fd1242825da3f3890426`. Re-verify after dependencies land.

### Verified Imports

```python
from __future__ import annotations
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
from typing import Mapping, Sequence
import pytest
from parrot.flows.dev_loop import feature_launcher as launcher
from parrot.flows.dev_loop import native_claude_sandbox as native
```

Stdlib imports are available on the supported Python runtime. Existing test imports: `packages/ai-parrot/tests/sdd/test_sdd_launch.py:15` and `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py:12`. Pytest is declared in `pyproject.toml:63`. `importlib.util.spec_from_file_location`, `module_from_spec`, `loader.exec_module` are the verified shim pattern at `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py:25`. Load the new sibling by path; do not import parrot in a script child.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:366
def launch(key: str, *, tmux: bool, detach: bool, sandbox: str | None,
           allowed_domains: Sequence[str], no_upstream: bool,
           claude_args: Sequence[str], base_env: Mapping[str, str] | None = None) -> int:
    """Prepare and launch or attach to the worker for one feature."""
# packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:726
def launch_worker(argv: Sequence[str], *, cwd: Path | None = None,
                  initial_prompt: str | None = None,
                  base_env: Mapping[str, str] | None = None) -> int:
    """Launch sdd-worker with strict settings."""
# packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:357
def _tmux_environment(env: Mapping[str, str]) -> list[str]:
    """Build tmux -e assignments including all PARROT_SDD_ names."""
# packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:700
def _allocate_session_cache() -> Path:
    """Allocate a UUID session cache with existing lifecycle."""
```

TASK-5122 creates `configure_notification(cache: Path, *, worktree: Path, env: Mapping[str, str]) -> str | None` in `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py`; it is a dependency interface, not an existing base symbol. Read/revalidate it after TASK-5122 lands. `FeatureRef` at `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:29` already has feature_id, slug, spec and index. CLI `launch_cli.py:40` captures base_env before importing flows.

### Does NOT Exist

- Launcher notification environment exports and Stop hook registration do not exist yet.
- There is no completion callback or pane-exit notification in launch().
- No changes to `_await_worker_start`, tmux failed-pane retention or sandbox socket permissions are needed.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_sdd_launch.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#FeatureRef",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#launch",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#_tmux_environment",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#launch_worker",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_allocate_session_cache"
  ]
}
```

## Implementation Notes

Consumes configure_notification from TASK-5122 (packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py); owns launcher/native settings and their two existing test files, with no overlapping writers or external shared-state mutations.

Follow the spec’s stdlib-only host-script boundary; this is synchronous CLI work, not an async application I/O path. Add no dependencies. Do not change sandbox permissions. Blueprint gaps below are planning markers; completed implementation must contain none.

## Implementation Blueprint

### Steps (in order)

1. Clear inherited launch markers and capture only base_env desktop values — because project-loaded environment and stale tmux values must not enter notification delivery.
2. Load and configure the installed helper after cache allocation — because script-mode execution must work without package imports or monorepo paths.
3. Append the Stop hook and export executable paths only after successful setup — because optional failures must not corrupt settings or leave stale executable references.
4. Extend existing environment/exec capture tests — because these seams expose actual argv/settings without invoking Claude or a desktop.

### `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` (MODIFY)

```python
# MODIFY def launch( — occurrences: 1; verified feature_launcher.py:366.
# After env = dict(os.environ if base_env is None else base_env), clear inherited markers:
for key_to_clear in tuple(env):
    if key_to_clear.startswith("PARROT_SDD_NOTIFY_"):
        env.pop(key_to_clear)

# In the NEW tmux branch only, before constructing tmux new-session:
desktop_keys = (
    "PATH", "HOME", "DISPLAY", "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR",
)
env["PARROT_SDD_NOTIFY_FEATURE"] = ref.feature_id
env["PARROT_SDD_NOTIFY_SLUG"] = ref.slug
env["PARROT_SDD_NOTIFY_DESKTOP"] = json.dumps(
    {name: env[name] for name in desktop_keys if name in env}
)
# FILL IN: retain existing non-tmux and reattach early returns, startup detection
# and literal tmux argv. Assert assignments survive an existing tmux server; AC-1/AC-3.
```

**Why**: Use existing _tmux_environment propagation; missing desktop keys stay absent and no .env merge is permitted.

### `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` (MODIFY)

```python
# MODIFY def launch_worker( — occurrences: 1; verified native_claude_sandbox.py:726.
# Add imports importlib.util and logging; module logger = logging.getLogger(__name__).
# Immediately after env[CACHE_DIR_ENV] = str(_allocate_session_cache()),
# before settings serialization, resolve the installed sibling:
helper_path = Path(__file__).resolve().with_name("worker_notification.py")
# FILL IN: gate valid metadata plus TMUX_PANE, then load helper_path using
# importlib.util.spec_from_file_location/module_from_spec/exec_module; AC-2.
# FILL IN: catch setup/loading operational errors at this optional boundary,
# log a concise warning, and leave launch settings/exports intact on failure; AC-4.
# Once notification_module is loaded and configure_notification succeeds:
hook_command = notification_module.configure_notification(
    Path(env[CACHE_DIR_ENV]), worktree=cwd, env=env
)
if hook_command is not None:
    settings.setdefault("hooks", {}).setdefault("Stop", []).append(
        {"hooks": [{"type": "command", "command": hook_command, "timeout": 5}]}
    )
    env["PARROT_SDD_NOTIFY_PYTHON"] = str(Path(sys.executable).absolute())
    env["PARROT_SDD_NOTIFY_HELPER"] = str(helper_path)
# FILL IN: prevent stale inherited executable exports from surviving disabled or
# failed setup; retain input metadata for valid configure call. No SubagentStop; AC-2/AC-4.
```

**Why**: The helper is optional, settings are additive, and the existing cache is writable under current policy. Do not add notification paths or D-Bus sockets to sandbox grants.

### `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)

```python
# MODIFY anchor, occurrences: 1; verified test_sdd_launch.py:142:
# def test_tmux_new_session_carries_environment_and_detaches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
# Extend its explicit tmux assignment assertions and add adjacent focused tests.

def test_tmux_notification_snapshot_is_from_base_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing tmux servers receive current host desktop values without loaded secrets."""
    # FILL IN: reuse _primary and _tmux_runner; poison os.environ, pass base_env,
    # inspect JSON in -e assignments and preserved failed-pane/startup argv; AC-1/AC-3.


def test_non_tmux_clears_inherited_notification_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct launch cannot inherit notification identity or helper executable exports."""
    # FILL IN: capture launch_worker base_env and assert no NOTIFY prefix; AC-1.
# FILL IN: augment live/dead reattach coverage to assert no new setup; AC-3.
```

**Why**: Exercise actual tmux argv and supplied base_env rather than testing a duplicate snapshot implementation.

### `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` (MODIFY)

```python
# MODIFY anchor, occurrences: 1; verified test_native_claude_sandbox.py:330:
# def test_launch_worker_uses_requested_cwd_and_final_prompt(
# Append tests near this existing exec/cwd capture seam; retain original coverage.

def test_notification_settings_preserve_policy(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid tmux feature adds one Stop command while retaining hooks and sandbox policy."""
    # FILL IN: valid index/cache/metadata, existing Stop and PreToolUse hooks,
    # intercepted execvpe, JSON --settings inspection, absolute exports; AC-2/AC-4.
    # Parameterize required, preferred/degraded, off and legacy without real probing.


def test_notification_setup_failure_does_not_fail_launch(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing or broken helper leaves the worker executable and policy unchanged."""
    # FILL IN: import/config/write errors, missing TMUX_PANE/invalid identity,
    # stale executable exports, unchanged final prompt/exec status; AC-4.
# FILL IN: exercise script-mode loading under python -S without parrot imports; AC-2.
```

**Why**: Policy comparisons and script-mode loading catch regressions that mocked helper-only tests cannot.

### FILL IN checklist

- [ ] Place the environment edits only in the intended branches.
- [ ] Finish guarded sibling loading, valid-pane gating and atomic optional setup handling.
- [ ] Implement snapshot, reattach, all-mode policy and failure regression tests.

## Acceptance Criteria

- [ ] AC-1: Every inherited PARROT_SDD_NOTIFY_* key is cleared by feature launch. Only a new tmux branch sets FEATURE, SLUG and DESKTOP from the pre-import base_env allowlist; missing keys remain absent and current snapshot reaches an old tmux server via explicit -e.
- [ ] AC-2: Native launch configures only valid tmux feature metadata after cache allocation, using installed sibling path loading under python -S. Append exactly one command Stop hook with timeout 5 and export absolute Python/helper paths; preserve existing Stop/PreToolUse hooks and never register SubagentStop.
- [ ] AC-3: Non-tmux launch and live/dead reattach create no context/hook; startup detection, remain-on-exit failed, final prompt, direct exec and public signatures are unchanged.
- [ ] AC-4: Missing/invalid metadata or helper/import/filesystem setup failure never prevents launch or retains stale executable exports. Required, preferred including degraded, off and legacy preserve exact existing sandbox/security settings. No permissions or socket allowlists widen.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`

## Test Specification

Use existing _primary/_tmux_runner and linked/execvpe seams with a valid temporary feature index and UUID cache where real helper setup is exercised. Poison ambient environment separately from base_env; verify current explicit tmux assignments and omitted secrets. Compare compiled policies before/after optional hook injection. Simulate helper load and write failures; exercise installed sibling resolution under python -S. Run both complete declared test files, preserving their existing startup, reattach and mode regressions.

## Agent Instructions

1. Use `$sdd-start TASK-5123` in the FEAT-793 feature worktree; never implement on dev.
2. Read the spec, verify dependencies are done in `sdd/tasks/index/tmux-notify-worker.json`, and re-check this contract before editing.
3. Follow the implementation blueprint and complete all bounded gaps; modify only declared files.
4. Run the Validation Commands and applicable formatting/lint checks; save test logs under `artifacts/logs/`.
5. Commit only scoped implementation files. Follow the Codex adaptation contract: finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD. The finalizer owns the Completion Note and active-to-completed move; do not edit or move them manually.

## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, 349s. Orchestrator review of the src diff found no defects (coder-review:e3e961032729107109a256dd). Merge-tier validation: 101 passed (test_native_claude_sandbox.py, test_sdd_launch.py). Closed with `parrot sdd task close` (the finalizer needs an EvidenceRef for review evidence, which coder_record_review does not return).
