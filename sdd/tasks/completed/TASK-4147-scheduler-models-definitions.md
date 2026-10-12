# TASK-4147: ServiceSchedule model, JobDefinition, RunState, FireContext, CodeJobRecord and utcnow()

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 and §2 Data Models. Every later module needs a backend-independent job definition, the run-state
shape every `RunStateStore` returns, a per-fire context and a single UTC clock. Today run state lives inside
`AgentSchedule.metadata` and every timestamp is a naive `datetime.now()` (`packages/ai-parrot-server/src/parrot/scheduler/manager.py:1011,1023,1030`).

This task ADDS the new types next to the legacy `AgentSchedule`. `AgentSchedule` stays in the file until TASK-4164
removes it, because the legacy `AgentSchedulerManager` keeps importing it until TASK-4158 rewrites `manager.py`.

---

## Scope

- Add `utcnow()` and `JOB_DEFINITION_VERSION = 1` to `models.py`.
- Add the asyncdb model `ServiceSchedule` for `navigator.service_scheduler` with exactly the fields and DDL docstring of spec §2 Data Models (incl. `tenant`, run-state columns, `consecutive_failures`, no `scheduler_type`).
- Add `ServiceSchedule.to_definition()` (→ `JobDefinition(backend='db', misfire_grace_time=300)`) and `ServiceSchedule.from_definition(definition)` (run-state columns untouched).
- Add the Pydantic v2 models `JobDefinition` (extra='forbid', JSON-serializable dict fields validated) and `RunState`, and the dataclasses `FireContext` (frozen) and `CodeJobRecord`.
- Add `schedule_fingerprint(definition: JobDefinition) -> str` in `models.py` (the legacy one in `manager.py:327` stays until TASK-4158).
- Write `tests/scheduler/test_models.py`.

**NOT in scope**: removing `AgentSchedule` (TASK-4164); any manager/base code; run-state persistence (TASK-4148/4149); DDL execution (the DDL is documentation only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/models.py` | MODIFY | Add ServiceSchedule, JobDefinition, RunState, FireContext, CodeJobRecord, utcnow, schedule_fingerprint |
| `packages/ai-parrot-server/tests/scheduler/test_models.py` | CREATE | Unit tests for the new types |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# packages/ai-parrot-server/src/parrot/scheduler/models.py:1-4 (current header — keep these)
from typing import Any, Dict, Optional, List
from datetime import datetime
import uuid
from asyncdb.models import Model, Field
# New imports this task adds (stdlib / pydantic v2 — already workspace deps):
import hashlib, json
from dataclasses import dataclass, field
from datetime import timezone
from typing import Awaitable, Callable, Literal
from pydantic import BaseModel, ConfigDict, field_validator
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/models.py:7 — legacy model, KEEP unchanged in this task
class AgentSchedule(Model):
    schedule_id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    ...
    class Meta:
        driver = 'pg'; name = "agents_scheduler"; schema = "navigator"; strict = True; frozen = False

# packages/ai-parrot-server/src/parrot/scheduler/manager.py:327 — legacy fingerprint to mirror (do NOT import it):
def schedule_fingerprint(schedule: AgentSchedule) -> str:
    schedule_type = normalize_schedule_type(schedule.schedule_type)
    payload = json.dumps({"schedule_type": schedule_type,
        "schedule_config": sanitize_schedule_config(schedule_type, schedule.schedule_config),
        "scheduler_type": normalize_jobstore_alias(schedule.scheduler_type)}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```
The new fingerprint must NOT import `sanitize` (keep `models.py` import-light): hash the raw definition fields listed
in the spec (`target_kind, target_name, target_id, prompt, method_name, schedule_type, schedule_config, metadata,
send_result, callbacks, misfire_grace_time`) with `json.dumps(..., sort_keys=True, default=str)`. Callers sanitize
before building a definition.

### Does NOT Exist
- ~~`ServiceSchedule`~~, ~~`JobDefinition`~~, ~~`RunState`~~, ~~`FireContext`~~, ~~`CodeJobRecord`~~, ~~`utcnow`~~, ~~`JOB_DEFINITION_VERSION`~~ — this task creates them.
- ~~`AgentSchedule.target_kind` / `.tenant` / `.last_status` / `.consecutive_failures`~~ — not on the legacy model.
- ~~`parrot.scheduler.base`~~ — does not exist yet (TASK-4154); `models.py` must never import it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/models.py#AgentSchedule"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`AgentSchedule` (models.py:7) for the asyncdb `Model` + `Field(...)` + `class Meta` shape and the DDL-in-docstring
convention. Name clash: asyncdb's `Field` is already imported — do NOT import `pydantic.Field`; give Pydantic fields
plain defaults (`= None`, `= {}`, `= []` — Pydantic v2 copies mutable defaults).

### References in Codebase
- `packages/ai-parrot-server/src/parrot/scheduler/models.py` — the file you modify.
- Spec §2 "Data Models" — the authoritative field list and DDL (copy it verbatim into the `ServiceSchedule` docstring).

### Key Constraints
- Async-first; never block the event loop. `self.logger` / module `logger`, never `print`.
- Google-style docstrings and strict type hints; 120-column lines; `ruff check` (TID251) must pass on every touched file.
- Every timestamp the scheduler writes goes through `utcnow()` (UTC-aware) — never `datetime.now()` (spec AC7).
- Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then complete every
> `# FILL IN:` marker. Never change a signature, class name, or file path the blueprint fixes (they come from the
> spec's §3 Interface Skeletons). Anchors were re-verified with `grep -c` at task-generation time.

### Steps (in order)
1. Add the new imports and `utcnow()` / `JOB_DEFINITION_VERSION` right after the existing imports — *why*: every other block in the file and every later task uses them.
2. Append `ServiceSchedule` after `AgentSchedule` with the spec DDL docstring — *why*: hard-cut target table; the legacy class must keep working until TASK-4164.
3. Append `JobDefinition`, `RunState`, `FireContext`, `CodeJobRecord` — *why*: one backend-independent shape (spec §2) shared by db/redis/code jobs.
4. Add `to_definition` / `from_definition` on `ServiceSchedule` and the module-level `schedule_fingerprint(definition)` — *why*: db rows convert to definitions at fire time; the fingerprint detects edits between fires.
5. Write the tests listed in the Test Specification and run them.

### `packages/ai-parrot-server/src/parrot/scheduler/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^class AgentSchedule(Model):' packages/ai-parrot-server/src/parrot/scheduler/models.py)
# BEFORE `class AgentSchedule(Model):` (verified: models.py:7) — new imports + clock
import hashlib
import json
from dataclasses import dataclass, field
from datetime import timezone
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, field_validator

JOB_DEFINITION_VERSION: int = 1


def utcnow() -> datetime:
    """Return ``datetime.now(timezone.utc)``; the only clock used by the scheduler package."""
    return datetime.now(timezone.utc)


# AFTER the end of `class AgentSchedule` (end of file) — append:
class ServiceSchedule(Model):
    """asyncdb model for ``navigator.service_scheduler`` (backend='db' rows only).

    # FILL IN: paste the CREATE TABLE + 2 CREATE INDEX statements from spec §2 Data Models verbatim.
    """
    # FILL IN: the 28 fields exactly as spec §2 Data Models (created_at/updated_at use default_factory=utcnow).

    class Meta:
        driver = "pg"
        name = "service_scheduler"
        schema = "navigator"
        strict = True
        frozen = False

    def to_definition(self) -> "JobDefinition":
        """Map a db row to a ``JobDefinition(backend='db', misfire_grace_time=300)``."""
        # FILL IN: build JobDefinition from the row's definition fields; schedule_id=str(self.schedule_id).

    @classmethod
    def from_definition(cls, definition: "JobDefinition") -> "ServiceSchedule":
        """Build a row (run-state columns left at defaults) from a definition."""
        # FILL IN: uuid.UUID(definition.schedule_id); never copy run-state fields.


class JobDefinition(BaseModel):
    """Backend-independent, JSON-serializable job definition (spec §2)."""

    model_config = ConfigDict(extra="forbid")

    schedule_id: str
    backend: Literal["db", "redis", "code"]
    target_kind: str
    target_name: str
    target_id: Optional[str] = None
    tenant: Optional[str] = None
    prompt: Optional[str] = None
    method_name: Optional[str] = None
    schedule_type: str
    schedule_config: dict[str, Any]
    metadata: dict[str, Any] = {}
    send_result: dict[str, Any] = {}
    callbacks: list[dict[str, Any]] = []
    misfire_grace_time: Optional[int] = None
    created_by: Optional[int] = None
    created_email: Optional[str] = None
    created_at: datetime = None  # FILL IN: default_factory via a model_validator or Field-free pattern → utcnow()

    @field_validator("schedule_config", "metadata", "send_result", "callbacks")
    @classmethod
    def _json_only(cls, value: Any) -> Any:
        """Reject values that do not survive ``json.dumps`` (spec S8: Redis kwargs are data-only)."""
        # FILL IN: json.dumps(value) without default=; raise ValueError naming the field on TypeError.
        return value
```
**Why this shape**: the field list, names and defaults are fixed by spec §2 and consumed verbatim by TASK-4148
(`RunState`), TASK-4154+ (`JobDefinition`, `FireContext`, `CodeJobRecord`). `extra="forbid"` is what makes the
hard-cut enforceable: a payload still carrying `agent_name` / `is_crew` / `scheduler_type` fails validation.

```python
# (continued, same file) — append after JobDefinition
class RunState(BaseModel):
    """What every ``RunStateStore.read()`` returns (spec §2)."""
    # FILL IN: the 15 fields of spec §2 RunState (schedule_id, backend, enabled, ... last_callbacks).


@dataclass(frozen=True)
class FireContext:
    """Per-fire context; ``fire_id = f"{schedule_id}:{scheduled_at.isoformat()}"``."""

    fire_id: str
    scheduled_at: datetime
    run_now: bool = False

    @classmethod
    def for_fire(cls, schedule_id: str, scheduled_at: datetime, *, run_now: bool = False) -> "FireContext":
        """Build the context; ``fire_id`` uses the same ``isoformat()`` the fire coordinator claims on."""
        return cls(fire_id=f"{schedule_id}:{scheduled_at.isoformat()}", scheduled_at=scheduled_at, run_now=run_now)


@dataclass
class CodeJobRecord:
    """Process-local record for a ``@schedule``-declared job (replaces the ``_auto_tasks`` dict)."""

    job_id: str
    target_name: str
    method_name: str
    method: Callable[..., Awaitable[Any]]
    schedule_type: str
    schedule_config: dict[str, Any]
    send_result: Optional[dict[str, Any]] = None
    callbacks: list[dict[str, Any]] = field(default_factory=list)
    success_callback: Optional[Callable[..., Any]] = None
    enabled: bool = True

    def to_definition(self) -> JobDefinition:
        """Expose the record through the uniform API (backend='code', target_kind='service')."""
        # FILL IN: schedule_id=self.job_id; send_result or {}; never put `method` in the definition.


def schedule_fingerprint(definition: JobDefinition) -> str:
    """sha256 over the fields listed in spec §3 M1; sort_keys JSON, ``default=str``."""
    # FILL IN: hash exactly target_kind, target_name, target_id, prompt, method_name, schedule_type,
    #          schedule_config, metadata, send_result, callbacks, misfire_grace_time — bounded by spec §3 M1.
```
**Why**: `FireContext.for_fire` is the single place `fire_id` is built, so it always equals the coordinator's claim
key suffix (`coordination.py:101` uses `run_time.isoformat()`) — this is the fix for ledger `aa813ccc1927`.
`CodeJobRecord.to_definition` uses `target_kind='service'` because code jobs are invoked as bound methods, not
resolved through a resolver.

### FILL IN checklist
- [ ] `ServiceSchedule` docstring + 28 fields — verbatim from spec §2 Data Models (AC5).
- [ ] `ServiceSchedule.to_definition` / `from_definition` — run-state columns never copied.
- [ ] `JobDefinition.created_at` default → `utcnow()` (UTC-aware, AC7).
- [ ] `JobDefinition._json_only` — `json.dumps` without `default=`; ValueError names the field.
- [ ] `RunState` fields — spec §2.
- [ ] `CodeJobRecord.to_definition` — `backend='code'`, never includes the callable.
- [ ] `schedule_fingerprint` — exactly the 11 fields of spec §3 M1.

---

## Acceptance Criteria

- [ ] `from parrot.scheduler.models import ServiceSchedule, JobDefinition, RunState, FireContext, CodeJobRecord, utcnow, schedule_fingerprint, JOB_DEFINITION_VERSION` works.
- [ ] `ServiceSchedule.Meta.name == 'service_scheduler'` and its docstring DDL matches spec §2 (incl. `tenant`, no `scheduler_type`).
- [ ] `JobDefinition(**{..., 'agent_name': 'x'})` raises a validation error; non-JSON metadata (a lambda, a `datetime`) raises.
- [ ] `utcnow().tzinfo is timezone.utc`.
- [ ] `AgentSchedule` is unchanged (the legacy suite still imports it).
- [ ] `ruff check packages/ai-parrot-server/src/parrot/scheduler/models.py packages/ai-parrot-server/tests/scheduler/test_models.py` passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_models.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_fire_recheck.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/scheduler/test_models.py
import uuid
from datetime import datetime, timezone
import pytest
pytest.importorskip("asyncdb")
from parrot.scheduler.models import (
    JobDefinition, RunState, FireContext, CodeJobRecord, ServiceSchedule, schedule_fingerprint, utcnow,
)

def _definition(**overrides) -> JobDefinition:
    base = dict(schedule_id=str(uuid.uuid4()), backend="db", target_kind="service", target_name="svc",
                method_name="run", schedule_type="interval", schedule_config={"minutes": 5})
    base.update(overrides)
    return JobDefinition(**base)

def test_utcnow_is_aware(): ...                                   # tzinfo is timezone.utc
def test_definition_rejects_legacy_fields(): ...                  # agent_name / is_crew / scheduler_type → ValidationError
def test_definition_rejects_non_json_metadata(): ...             # lambda and datetime in metadata → ValidationError
def test_service_schedule_roundtrip_definition(): ...            # from_definition(d).to_definition() == d (misfire 300)
def test_fingerprint_covers_misfire_and_target_fields(): ...     # each of the 11 fields changes the hash
def test_fire_context_for_fire_matches_claim_key(): ...          # fire_id == f"{id}:{dt.isoformat()}"
def test_code_job_record_to_definition_has_no_callable(): ...    # backend == "code", target_kind == "service"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug scheduler-manager-base --feature-id FEAT-644 --spec sdd/specs/scheduler-manager-base.spec.md --index sdd/tasks/index/scheduler-manager-base.json`)
2. **Read the spec** at `sdd/specs/scheduler-manager-base.spec.md` (§2 Overview, the CRUD matrix, Data Models, and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/scheduler-manager-base.json`
4. **Verify the Codebase Contract** — re-`grep` every anchor and signature before writing code; if one moved, fix
   the contract in this file first; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** — `ruff check` the touched files and run every Validation Command
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`):
   `feat(scheduler-manager-base): TASK-4147 — ServiceSchedule model, JobDefinition, RunState, FireContext, CodeJobRecord and utcnow()`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4147 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4147 — ServiceSchedule model, JobDefinition, RunState, FireContext, CodeJobRecord and utcnow()`

---

## Completion Note

**Completed by**: sdd-worker (coder seat: gpt-5.6-terra)
**Date**: 2026-10-08
**Notes**: Implemented as specified and merged into the feature branch. Direct run of packages/ai-parrot-server/tests/scheduler passed. The merge-tier validation was red only because of an unrelated pre-existing studio test collection error (ledger issue:d5a7c625fbe7); closed on direct test evidence.

**Deviations from spec**: none
