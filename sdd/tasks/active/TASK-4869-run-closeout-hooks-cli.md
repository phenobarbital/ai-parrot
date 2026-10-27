# TASK-4869: Dispatcher CLI `run_closeout_hooks` (events, agent record/finalize, artifacts, exit codes)

**Feature**: FEAT-764 — `/sdd-done` closeout hooks
**Spec**: `sdd/specs/sdd-done-closeout-hooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-4867, TASK-4868
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2 and the §2 Overview protocol: one code-enforced entry point both
`/sdd-done` twins call. The exit code is the contract (FEAT-703 pattern). AC3–AC7.

---

## Scope

- CLI `python -m scripts.sdd.run_closeout_hooks`:
  `--event {pre_pr,post_pr,on_failure}` (required), `--context <json path>` (required unless
  `--record`/`--finalize`), `--feat-id` (required with `--record`/`--finalize`), `--dry-run`,
  `--record NAME --status {pass,fail} [--summary TEXT]`, `--finalize`, `--root` (default `.`, the
  feature worktree holding `.parrot/sdd_hooks.toml`).
- Artifact root: `$SDD_HOOKS_ARTIFACT_ROOT` else `/tmp/claude-<uid>/sdd-hooks`; per feature
  `<root>/<FEAT-ID>/`, per hook `<root>/<FEAT-ID>/<hook-name>/` (created before the hook runs).
- `command` hooks: `subprocess.run(run, shell=True, cwd=ctx.worktree, timeout=timeout_s)`, env adds
  `SDD_HOOK_CONTEXT`, `SDD_HOOK_ARTIFACT_DIR`, `SDD_FEAT_ID`, `SDD_PR_URL`; exit 0 → pass,
  non-zero → fail, `TimeoutExpired` → timeout (counts as failure). Capture the last 40 lines of
  combined output into `<hook dir>/output.log` and the summary.
- `builtin` hooks: `run_builtin(...)`.
- `agent` hooks: status `pending`; add to `pending_agents[]` `{name, agent, prompt (rendered with
  context + artifact_dir), artifact_dir, blocking}`.
- `--dry-run`: `pre_pr` runs normally; `post_pr`/`on_failure` mark every hook `skipped`
  ("dry-run") and exit 0 (AC4).
- After each hook: glob `hook.artifacts` relative to its dir → absolute paths in `artifacts`.
- Persist `<root>/<FEAT-ID>/<event>.json` (`EventOutcome`), print it as one JSON object on stdout.
- Exit: 2 on `HooksConfigError`/usage; 3 when `pending_agents` non-empty; else 1 if any blocking
  hook is `fail`/`timeout`; else 0. `post_pr`/`on_failure` never return 1.
- `--record` updates that hook in `<event>.json` (status, summary, globbed artifacts); exit 0, or 2
  if the hook is not pending.
- `--finalize`: any still-`pending` hook → `fail` "agent hook not recorded" (AC6); recompute exit 0/1.
- `render_evidence(outcome)` → `## Evidence` markdown: one bullet per hook
  `name — status — summary`, nested bullets with absolute artifact paths; empty string if no hooks.
- Absent config → exit 0, outcome with no results, `evidence_md == ""`.

**NOT in scope**: editing the twins (TASK-4870), docs (TASK-4871).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/run_closeout_hooks.py` | CREATE | CLI + run_event/record/finalize/render_evidence |
| `tests/sdd_scripts/test_run_closeout_hooks.py` | CREATE | Unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.closeout_hooks_config import (EVENTS, HookContext, HookKind, HookResult, HookSpec,
    HooksConfig, HooksConfigError, load_hooks)          # created by TASK-4867
from scripts.sdd.closeout_builtins import run_builtin   # created by TASK-4868
```

### Existing Signatures to Use
```python
# scripts/sdd/check_e2e_closeout.py:201 — CLI/exit-code precedent to mirror
def main(argv: Optional[Sequence[str]] = None) -> int: ...
#   argparse flags at lines 211-213; `if __name__ == "__main__": raise SystemExit(main())`
```

### Does NOT Exist
- ~~a `--force` flag~~ — must not exist on this CLI (spec §6: blocking hooks are not force-able).
- ~~`check_e2e_closeout` integration~~ — hooks never feed the E2E gate.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/sdd/run_closeout_hooks.py",
      "action": "CREATE"
    },
    {
      "path": "tests/sdd_scripts/test_run_closeout_hooks.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:scripts/sdd/check_e2e_closeout.py#main"
  ]
}
```

---

## Implementation Notes

- Commit nothing under the artifact root; it is outside the repo by construction (AC7).
- `EventOutcome` is a Pydantic model local to this module:
  `event, feat_id, results: list[HookResult], pending_agents: list[dict], blocking_failed: bool, evidence_md: str`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the skeleton below — *why*: TASK-4870 documents these exact flags and exit codes.
2. Implement `_run_command`, then `run_event`, `record`, `finalize`, `render_evidence`, `main`.
3. Tests, using `SDD_HOOKS_ARTIFACT_ROOT=tmp_path/art` and a `tmp_path` root with `.parrot/sdd_hooks.toml`.

### `scripts/sdd/run_closeout_hooks.py` (CREATE)
```python
"""Dispatch /sdd-done closeout hooks (FEAT-764). Exit: 0 ok · 1 blocking failure · 2 config/usage · 3 agents pending."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from scripts.sdd.closeout_builtins import run_builtin
from scripts.sdd.closeout_hooks_config import (EVENTS, HookContext, HookKind, HookResult, HookSpec,
    HooksConfig, HooksConfigError, load_hooks)

EXIT_OK, EXIT_BLOCKING, EXIT_USAGE, EXIT_PENDING = 0, 1, 2, 3


class EventOutcome(BaseModel):
    """Persisted result of one event run."""

    event: str
    feat_id: str
    results: list[HookResult] = Field(default_factory=list)
    pending_agents: list[dict[str, Any]] = Field(default_factory=list)
    blocking_failed: bool = False
    evidence_md: str = ""


def artifact_root() -> Path:
    """Return $SDD_HOOKS_ARTIFACT_ROOT or /tmp/claude-<uid>/sdd-hooks."""
    env = os.environ.get("SDD_HOOKS_ARTIFACT_ROOT")
    return Path(env) if env else Path(f"/tmp/claude-{os.getuid()}") / "sdd-hooks"


def _run_command(hook: HookSpec, ctx: HookContext, ctx_path: Path, hook_dir: Path) -> HookResult:
    # FILL IN: subprocess with env + timeout; output.log tail — bounded by spec §2 step 2
    raise NotImplementedError


def run_event(event: str, ctx: HookContext, cfg: HooksConfig, root: Path, ctx_path: Path) -> EventOutcome:
    """Run every enabled hook for ``event`` in declaration order."""
    # FILL IN: dry-run rule (AC4), per-kind dispatch, artifact globbing, blocking_failed, persist + evidence
    raise NotImplementedError


def record(event: str, feat_id: str, name: str, status: str, summary: str, root: Path) -> EventOutcome:
    """Record a host-dispatched agent hook's outcome."""
    # FILL IN — raise ValueError if not pending
    raise NotImplementedError


def finalize(event: str, feat_id: str, root: Path) -> EventOutcome:
    """Turn unrecorded pending hooks into failures and recompute blocking_failed (AC6)."""
    # FILL IN
    raise NotImplementedError


def render_evidence(outcome: EventOutcome) -> str:
    """Render the PR `## Evidence` section (absolute artifact paths)."""
    # FILL IN
    raise NotImplementedError


def exit_code(outcome: EventOutcome) -> int:
    """Map an outcome to the CLI contract."""
    if outcome.pending_agents and any(r.status == "pending" for r in outcome.results):
        return EXIT_PENDING
    if outcome.event == "pre_pr" and outcome.blocking_failed:
        return EXIT_BLOCKING
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(prog="run_closeout_hooks", description=__doc__)
    parser.add_argument("--event", required=True, choices=EVENTS)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--feat-id")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--record", metavar="NAME")
    parser.add_argument("--status", choices=("pass", "fail"))
    parser.add_argument("--summary", default="")
    parser.add_argument("--finalize", action="store_true")
    # FILL IN: mode validation (usage errors → 2 with message on stderr), load_hooks (HooksConfigError → 2),
    #          dispatch run/record/finalize, print outcome JSON on stdout, return exit_code(...)
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why**: the exit-code table is the twins' only decision input (spec §2); keep `exit_code` the
single place that maps outcomes to codes.

### FILL IN checklist
- [ ] `_run_command` env/timeout/log
- [ ] `run_event` dry-run + dispatch + persist
- [ ] `record` / `finalize`
- [ ] `render_evidence`
- [ ] `main` mode validation

---

## Acceptance Criteria

- [ ] Blocking pre_pr failure → exit 1; non-blocking → 0 (AC3).
- [ ] `--dry-run`: pre_pr runs, post_pr/on_failure skipped (AC4).
- [ ] Agent hook → exit 3; `--record` then `--finalize` → 0/1; unrecorded → fail (AC6).
- [ ] Artifacts only under the artifact root; evidence lists absolute paths (AC7).
- [ ] Malformed config → exit 2 (AC2). `ruff check scripts/sdd/run_closeout_hooks.py` clean.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_run_closeout_hooks.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_run_closeout_hooks.py
def test_no_config_exit_0(tmp_path, monkeypatch): ...
def test_malformed_config_exit_2(tmp_path, monkeypatch): ...
def test_command_pass_and_env_vars(tmp_path, monkeypatch): ...      # command writes $SDD_FEAT_ID into $SDD_HOOK_ARTIFACT_DIR/x.txt
def test_blocking_command_fail_exit_1(tmp_path, monkeypatch): ...
def test_non_blocking_fail_exit_0(tmp_path, monkeypatch): ...
def test_command_timeout(tmp_path, monkeypatch): ...
def test_dry_run_runs_pre_pr_skips_post_pr(tmp_path, monkeypatch): ...
def test_agent_pending_exit_3_then_record_finalize(tmp_path, monkeypatch): ...
def test_finalize_unrecorded_pending_fails(tmp_path, monkeypatch): ...
def test_artifacts_globbed_and_in_evidence(tmp_path, monkeypatch): ...
def test_builtin_dispatch_uses_run_builtin(tmp_path, monkeypatch): ...
def test_end_to_end_pre_pr_with_agent_record(tmp_path, monkeypatch): ...  # integration: real subprocess
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-done-closeout-hooks --feature-id FEAT-764`), never on `dev`.
2. Read the spec `sdd/specs/sdd-done-closeout-hooks.spec.md` (§2 Overview, Data Models, exit-code table).
3. Every `Depends-on` task must be `done` in `sdd/tasks/index/sdd-done-closeout-hooks.json`.
4. Verify the Codebase Contract before writing code; fix stale entries first.
5. Mark `in-progress` in the index, implement from the Blueprint, complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH=.` from the worktree root; `ruff check` the new files.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh <TASK-ID> sdd-done-closeout-hooks verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
