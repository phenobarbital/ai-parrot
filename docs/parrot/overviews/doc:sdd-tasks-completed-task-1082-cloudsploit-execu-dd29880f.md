---
type: Wiki Overview
title: 'TASK-1082: Plumb `config` through `_run_with_outputs`, `run_scan`, `run_compliance_scan`'
id: doc:sdd-tasks-completed-task-1082-cloudsploit-executor-config-plumbing-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per FEAT-160 proposal §3 ("What Changes" → fourth and fifth bullets) and
  §2.1
---

# TASK-1082: Plumb `config` through `_run_with_outputs`, `run_scan`, `run_compliance_scan`

**Feature**: FEAT-160 — CloudSploit `--config` support for run_scan
**Spec**: `sdd/proposals/cloudsploit-config-support.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1079, TASK-1080, TASK-1081
**Assigned-to**: unassigned

---

## Context

Per FEAT-160 proposal §3 ("What Changes" → fourth and fifth bullets) and §2.1
(Localization rows 3-4): connect the new `config_path` argv arg (TASK-1081) and
the widened mount list (TASK-1080) by accepting a `config` parameter on
`_run_with_outputs`, `run_scan`, and `run_compliance_scan`.

When set, the executor must:
1. Fail fast if the path doesn't exist on disk.
2. Under Docker — bind-mount the parent directory of the config file
   **read-only** at `/cloudsploit/config/` and rewrite the path passed to
   `_build_cli_args` as `/cloudsploit/config/<basename>`.
3. Under direct-CLI mode (`use_docker=False`) — pass the host path verbatim to
   `_build_cli_args` (no rewriting).
4. Leave existing output-dir mount and argv unchanged when `config` is None.

The two resolved decisions from the proposal Q&A apply here:
- Mount path convention: `/cloudsploit/config/<basename>` (mirrors `_DOCKER_OUTPUT_MOUNT`).
- Mount mode: read-only (`:ro`).

---

## Scope

- Add module-level constant `_DOCKER_CONFIG_MOUNT = "/cloudsploit/config"` next
  to the existing `_DOCKER_OUTPUT_MOUNT`.
- Add `config: Optional[str] = None` kwarg on `_run_with_outputs`, `run_scan`,
  `run_compliance_scan`.
- In `_run_with_outputs`:
  - If `config` is None → unchanged behaviour.
  - If `config` is set → call `Path(config).is_file()` and raise
    `FileNotFoundError(f"CloudSploit config file not found: {config}")` if
    absent.
  - Under Docker mode: compute `host_dir = Path(config).resolve().parent`,
    append `(str(host_dir), _DOCKER_CONFIG_MOUNT, "ro")` to the volume-mounts
    list, and pass
    `config_path=f"{_DOCKER_CONFIG_MOUNT}/{Path(config).name}"` to
    `_build_cli_args`.
  - Under direct-CLI mode: pass `config_path=config` unchanged.
- Update test coverage in `tests/cloudsploit/test_executor.py`.

**NOT in scope**:
- Toolkit-level surface — TASK-1083.
- Reading `self.config.config_file` as a fallback — that's TASK-1083's
  responsibility at the toolkit layer.
- Parsing the JS file's contents.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py` | MODIFY | Add `_DOCKER_CONFIG_MOUNT`; thread `config` through three methods; validate path; orchestrate mount + path-rewrite |
| `packages/ai-parrot-tools/tests/cloudsploit/test_executor.py` | MODIFY | Add tests for: FileNotFoundError, Docker path rewrite, direct-CLI passthrough, mount ro flag, no-config baseline preserved |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in executor.py
import asyncio, os, re, tempfile
from pathlib import Path
from typing import Optional
from .models import CloudProvider, CloudSploitConfig, ComplianceFramework
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:15
_DOCKER_OUTPUT_MOUNT = "/cloudsploit/output"

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:233-309
async def _run_with_outputs(
    self,
    *,
    plugins: Optional[list[str]] = None,
    compliance: Optional[ComplianceFramework] = None,
    ignore_ok: bool = False,
    suppress: Optional[list[str]] = None,
    capture_collection: bool = True,
) -> tuple[str, str, str, str, int]:
    ...
    if self.config.use_docker:
        container_results = f"{_DOCKER_OUTPUT_MOUNT}/results.json"
        ...
        volume_mount = (str(host_dir), _DOCKER_OUTPUT_MOUNT)  # ← becomes list after TASK-1080
    else:
        container_results = str(host_results)
        ...
        volume_mount = None
    args = self._build_cli_args(...)  # ← gets new config_path kwarg from TASK-1081

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:311-336
async def run_scan(
    self,
    plugins: Optional[list[str]] = None,
    ignore_ok: bool = False,
    suppress: Optional[list[str]] = None,
    capture_collection: bool = True,
) -> tuple[str, str, str, str, int]:
    return await self._run_with_outputs(...)

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:338-360
async def run_compliance_scan(
    self,
    framework: ComplianceFramework,
    ignore_ok: bool = True,
    capture_collection: bool = True,
) -> tuple[str, str, str, str, int]:
    return await self._run_with_outputs(...)
```

### Does NOT Exist
- ~~`self.executor.validate_config_file()`~~ — no such helper; just inline the
  `Path(...).is_file()` check.
- ~~`CloudSploitError` exception~~ — use plain `FileNotFoundError`.
- ~~`os.path.expanduser` magic~~ — pass the path through as the user gave it.
  If they want `~`, they expand it before calling.

---

## Implementation Notes

### Pattern to Follow
```python
# At module level, next to _DOCKER_OUTPUT_MOUNT (line 15):
_DOCKER_CONFIG_MOUNT = "/cloudsploit/config"

# Inside _run_with_outputs, after computing the existing output mount:
config_container_path: Optional[str] = None
if config is not None:
    config_path = Path(config)
    if not config_path.is_file():
        raise FileNotFoundError(
            f"CloudSploit config file not found: {config}"
        )
    if self.config.use_docker:
        host_cfg_dir = str(config_path.resolve().parent)
        volume_mounts.append(
            (host_cfg_dir, _DOCKER_CONFIG_MOUNT, "ro")
        )
        config_container_path = f"{_DOCKER_CONFIG_MOUNT}/{config_path.name}"
    else:
        config_container_path = str(config_path)

args = self._build_cli_args(
    ...,
    config_path=config_container_path,
)
```

### Key Constraints
- Use `Path(config).resolve().parent` so symlinks and relative paths are
  normalised before becoming a host mount. This is important — Docker bind
  mounts require absolute host paths.
- The mode flag MUST be the literal string `"ro"` (matches TASK-1080's spec).
- `FileNotFoundError` is the right exception class — agents will see it as a
  clear, actionable Python error.
- Forward `config` from `run_scan` → `_run_with_outputs` and from
  `run_compliance_scan` → `_run_with_outputs`. Both helpers accept it.
- Docstring updates: mention what happens when `config` is None vs set.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:263-309` —
  existing `_run_with_outputs` body, especially the if/else block that already
  branches on `self.config.use_docker` for the output dir.
- The Trivy executor `_extra_docker_args` injection added earlier in this
  repo (`parrot_tools/security/trivy/executor.py`) is a sibling reference
  for "mount-on-demand" patterns, but is NOT a direct API to import.

---

## Acceptance Criteria

- [ ] `run_scan(config=None)` produces identical argv + mount as before this feature.
- [ ] `run_scan(config="/missing.js")` raises `FileNotFoundError` with the
      offending path in the message.
- [ ] Under Docker mode, `run_scan(config="/abs/p/config.js")` results in:
      - The argv contains `--config=/cloudsploit/config/config.js`.
      - The mount list contains `("/abs/p", "/cloudsploit/config", "ro")`.
- [ ] Under direct-CLI mode (`use_docker=False`),
      `run_scan(config="/abs/p/config.js")` results in:
      - The argv contains `--config=/abs/p/config.js` (host path verbatim).
      - No mount-related side effect.
- [ ] `run_compliance_scan(config=...)` behaves identically to `run_scan` w.r.t.
      the config path.
- [ ] All existing tests still pass.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py` clean.

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_run_scan_no_config_keeps_argv_clean(tmp_path, monkeypatch):
    """run_scan with config=None still works exactly as before."""
    # ... (mock self.execute, assert _build_cli_args was called with
    # config_path=None or omitted)


@pytest.mark.asyncio
async def test_run_scan_missing_config_file_raises(tmp_path):
    e = CloudSploitExecutor(CloudSploitConfig())
    with pytest.raises(FileNotFoundError, match="cloudsploit-missing.js"):
        await e.run_scan(config=str(tmp_path / "cloudsploit-missing.js"))


def test_docker_path_rewrite(tmp_path):
    """Internal: verify the path-rewriting math directly."""
    cfg_file = tmp_path / "config.js"
    cfg_file.write_text("module.exports = {};\n")
    # call internal helper or do an integration-style assertion that
    # the constructed command contains
    #    --config=/cloudsploit/config/config.js
    # AND a mount for `<tmp_path>:/cloudsploit/config:ro`


def test_direct_cli_passthrough(tmp_path):
    """When use_docker=False, the host path is used verbatim."""
    cfg_file = tmp_path / "config.js"
    cfg_file.write_text("module.exports = {};\n")
    cfg = CloudSploitConfig(use_docker=False, cli_path="/usr/bin/cloudsploit")
    # ... assert the argv contains --config=<host path>, no mount
```

---

## Agent Instructions

When you pick up this task:

1. **Confirm dependencies**: TASK-1079, TASK-1080, TASK-1081 must be in
   `sdd/tasks/completed/`. If not, abort and pick one of those first.
2. **Read the proposal** §3 fully.
3. **Verify the Codebase Contract** by reading `executor.py:233-360`.
4. **Implement** per the pattern above.
5. **Run the full cloudsploit suite**:
   `pytest packages/ai-parrot-tools/tests/cloudsploit/ -v`.
6. **Move this file** to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-12
**Notes**: Added `_DOCKER_CONFIG_MOUNT` constant. Added `config: Optional[str] = None` to `_run_with_outputs`, `run_scan`, and `run_compliance_scan`. Implemented: fail-fast FileNotFoundError, Docker path rewrite + `:ro` mount, direct-CLI passthrough. 4 new tests cover all branches. All new tests pass; only pre-existing env-specific failures remain.

**Deviations from spec**: none
