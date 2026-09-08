# TASK-2774: Add observation, interrupt, and memory configuration models

**Feature**: FEAT-521 - REPL Worker Idle/Busy Detection & Memory Guardrails
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 defines the typed configuration and sample/verdict models used by every later observer, handle, pool, and test task.

## Scope

- Extend `WorkerConfig` with observer cadence, stall detection, interrupt grace, per-worker RSS limits, and host reserve fields using the defaults in spec §2.
- Validate `hard >= soft` when both are enabled, `hard <= rlimit_as_bytes`, and `interrupt_grace_ms < deadline_ms`; a zero memory limit disables that limit.
- Add `ProcessSample`, `MemoryVerdict`, and `Verdict` to `protocol.py`; they remain host-local and must not be added to `_MESSAGE_TYPES`.
- Export the new models from `repl_worker.__init__`.

**NOT in scope**: observer sampling, worker signalling, handle/pool behavior, or tests owned by TASK-2780.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | Add config fields, validators, and host-local models |
| `packages/ai-parrot/src/parrot/tools/repl_worker/__init__.py` | MODIFY | Export the new public models |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Literal  # protocol.py:26
from pydantic import BaseModel, Field  # protocol.py:28
from pydantic import model_validator  # verified Pydantic v2 usage: scripts/sdd/sdd_meta.py:15,29
```

### Existing Signatures to Use

```python
# protocol.py:277-285
class ExecResult(BaseModel):
    output: str | None = None
    status: str | None = None
    result: Any | None = None
    error: str | None = None

# protocol.py:352-362
class NamespaceLossError(BaseModel):
    cause: Literal["timeout", "memory", "crash"]

# protocol.py:365-401
class WorkerConfig(BaseModel):
    rlimit_as_bytes: int = 12 * 1024**3
    deadline_ms: int = 60_000
    bootstrap_timeout_ms: int = Field(default=30_000, gt=0)
```

### Does NOT Exist

- ~~`WorkerConfig.observer_poll_ms`~~ and the other FEAT-521 fields do not exist yet.
- ~~`ProcessSample`~~, ~~`MemoryVerdict`~~, and ~~`Verdict`~~ do not exist yet.
- The host-local models are not wire messages and must not appear in `_MESSAGE_TYPES`.

## Implementation Notes

- Preserve every existing protocol model and wire discriminator.
- Use one Pydantic model-level validator for cross-field invariants with explicit error messages.
- Defaults are: poll 500 ms, stall window 5,000 ms, bootstrap stall disabled, interrupt enabled with 2,000 ms grace, soft RSS 4 GiB, hard RSS 8 GiB, host reserve 2 GiB.

## Acceptance Criteria

- [ ] All fields and defaults match spec §2 Data Models.
- [ ] Invalid cross-field combinations raise `ValidationError`; zero disables either memory threshold.
- [ ] Existing frame serialization remains unchanged.
- [ ] `ProcessSample`, `MemoryVerdict`, and `Verdict` import from the package surface.
- [ ] `black` and `ruff` pass on touched files.

## Test Specification

Tests are implemented in TASK-2780. Before completion, manually validate default construction, each invalid combination, zero-disabled thresholds, and unchanged `_MESSAGE_TYPES` membership.

## Agent Instructions

Read the spec and re-verify `protocol.py:277-423` plus `__init__.py:14-70` before editing. Commit only this task's files and update the per-spec index through the SDD workflow.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-03
**Notes**: Added `observer_poll_ms`, `stall_window_ms`, `bootstrap_stall_ms`,
`interrupt_before_kill`, `interrupt_grace_ms`, `memory_soft_limit_bytes`,
`memory_hard_limit_bytes`, `host_memory_reserve_bytes` to `WorkerConfig` with
a `model_validator(mode="after")` enforcing `hard >= soft` (when both
enabled), `hard <= rlimit_as_bytes` (when enabled), and
`interrupt_grace_ms < deadline_ms`. Added `ProcessSample`, `Verdict`,
`MemoryVerdict` to `protocol.py` (kept out of `_MESSAGE_TYPES`) and exported
all five new symbols from `repl_worker/__init__.py`. Manually verified
defaults, zero-disables-threshold behavior, each invalid-combination
`ValidationError`, and unchanged `_MESSAGE_TYPES` membership (16 entries)
via a `PYTHONPATH`-scoped script against the worktree source (the shared
venv's editable install points at the main repo, not this worktree).
`ruff check` and `black --target-version py312` clean on both touched files.

**Deviations from spec**: none
