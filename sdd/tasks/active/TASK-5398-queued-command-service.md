# TASK-5398: Implement bounded queued execution, progress and requester job control

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5396, TASK-5397
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Implement QueuedCommandService, ContextVar progress helpers and service exports from M2.
- Use one manager per wrapper, local-first admission and atomic dedup/create/scheduling; track scheduling and persistence work.
- Separate monotonic queue and execution budgets from immutable UTC read-time expiry.
- Render shared notices through platform-supplied callbacks; never write conversation history.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/service.py` | CREATE | Admission, runner and ownership-aware job controls |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/context.py` | CREATE | Request-local progress without platform coupling |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/__init__.py` | MODIFY | Export execution and progress APIs |
| `packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py` | MODIFY | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
import asyncio
import logging
from contextvars import ContextVar
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict
from parrot.jobs import JobManager, RedisJobStore, JobStatus
from parrot.integrations.utils import parse_kwargs
from parrot.integrations.parser import parse_response
import pytest
from typing import List, Literal, Optional
from .models import Deliver, JobView, QueuedCommand, Requester, SubmitOutcome
from typing import Any, Optional
from .models import Requester
from .context import current_job_id, report_command_progress
from .service import QueuedCommandService
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:209
async def execute_job(self, job_id: str, execution_func: Callable[[], Awaitable[Any]]) -> None

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:228
async def _run_job(self, job_id: str, execution_func: Callable[[], Awaitable[Any]]) -> None

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:122
async def update_metadata(self, job_id: str, **values: Any) -> Optional[Job]

# packages/ai-parrot-integrations/src/parrot/integrations/utils.py:5
def parse_kwargs(text: str) -> dict

# packages/ai-parrot-integrations/src/parrot/integrations/parser.py:416
def parse_response(response: Any) -> ParsedResponse
```

### Does NOT Exist

- QueuedCommandService/context.py are new; declaration models come from TASK-5397.
- JobManager has no completion callback or enforced queue budget; implement the runner here without changing job statuses directly.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/core/queued/service.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/core/queued/context.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/core/queued/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.execute_job",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager._run_job",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.update_metadata",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/utils.py#parse_kwargs",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/parser.py#parse_response"
  ]
}
```

## Implementation Notes

- Implement every M2 unit/regression case in spec §4, not just the representative scaffold cases. Use Events and fake clocks rather than multi-second sleeps.
- Prepare hooks are nonblocking and network-free. Parsing uses parse_kwargs for keyword, shlex for positional and unchanged raw input for raw mode; verify new stdlib imports when filling logic.

**Parallelism**: TASK-5396 supplies cancel_job, initial metadata, fresh foreign reads and bounded persistence; TASK-5397 creates QueuedCommand/Requester/JobView, discovery and messages, and shares __init__.py and test_queued_commands.py writes.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/service.py` (CREATE)

```python
"""Local-first, bounded execution of platform-neutral queued commands."""
import asyncio
import logging
from typing import List, Literal, Optional
from parrot.jobs import JobManager, RedisJobStore, JobStatus
from .models import Deliver, JobView, QueuedCommand, Requester, SubmitOutcome

class QueuedCommandService:
    """Own one wrapper's jobs, concurrency groups and delivery callbacks."""
    def __init__(self, *, owner: str, job_manager: Optional[JobManager] = None,
                 use_redis: bool = True, key_prefix: str = "parrot:chat_jobs",
                 job_ttl: int = 86400, expiry_grace: float = 300.0,
                 prepare_timeout: float = 10.0, admission_timeout: float = 10.0,
                 notify_timeout: float = 30.0) -> None:
        """Configure local admission and finite prepare, execution and delivery budgets."""
        self.logger = logging.getLogger(__name__)
        # FILL IN: initialize owned/injected manager, tasks, reservations and groups; AC1-AC3.
    async def start(self) -> None:
        """Start idempotently without waiting for Redis connectivity."""
        # FILL IN: AC10; manager id is chat:{owner}, Redis remains optional.
        raise NotImplementedError
    async def stop(self) -> None:
        """Cancel live jobs with interruption reasons and drain bounded delivery."""
        # FILL IN: AC8/AC10; protect admission-to-runner cancellation races.
        raise NotImplementedError
    async def submit(self, command: QueuedCommand, raw_args: str, requester: Requester,
                     deliver: Deliver) -> SubmitOutcome:
        """Prepare, reserve and schedule locally under one admission deadline."""
        # FILL IN: AC1-AC5; no await in reservation/create/schedule critical section.
        # execute_job is async: track its scheduled admission task and cover its cancellation race.
        raise NotImplementedError
    async def get(self, job_id: str, requester: Requester) -> Optional[JobView]:
        """Read a fresh requester-scoped view with conservative foreign expiry."""
        # FILL IN: AC6/AC7.
        raise NotImplementedError
    async def list_for(self, requester: Requester, limit: int = 10) -> List[JobView]:
        """Read the requester's newest jobs using the user index."""
        # FILL IN: AC6/AC7; same view conversion as get.
        raise NotImplementedError
    async def cancel(self, job_id: str, requester: Requester) -> Literal[
        "cancelling", "not_found", "finished", "not_on_this_worker"
    ]:
        """Cancel only a live owned task belonging to the requester."""
        # FILL IN: AC7; reason is cancelled by the requester.
        raise NotImplementedError
# FILL IN: private runner, view mapping and tracked delivery helpers; AC2-AC10.
# Runner restores ContextVar, releases semaphore and dedup in finally.
```

**Why**: Admission, runner and ownership-aware job controls. Implement QueuedCommandService, ContextVar progress helpers and service exports from M2.

### `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/context.py` (CREATE)

```python
"""Context-local access to a running command job."""
from contextvars import ContextVar
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict
from .models import Requester

class CommandJobContext(BaseModel):
    """The current command's job identity and progress owner."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    job_id: str
    command: str
    requester: Requester
    service: Any

current_command_job: ContextVar[Optional[CommandJobContext]] = ContextVar("current_command_job", default=None)
async def report_command_progress(message: str) -> None:
    """Record progress when bound; swallow/log failures and no-op otherwise."""
    # FILL IN: AC9; use the service's manager update_metadata, not raw Redis.
    raise NotImplementedError
def current_job_id() -> Optional[str]:
    """Return the running job ID, or None outside queued execution."""
    context = current_command_job.get()
    return context.job_id if context else None
```

**Why**: Request-local progress without platform coupling. Implement QueuedCommandService, ContextVar progress helpers and service exports from M2.

### `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/__init__.py` (MODIFY)

Created by TASK-5397; planned anchor `__all__ = (` occurs 1 time(s) in its blueprint. File does not exist on dev yet: verify actual count/line after the dependency lands before editing; this is dependency evidence, not a claimed current-source grep.

```python
from .context import current_job_id, report_command_progress
from .service import QueuedCommandService
__all__ = (*__all__, "current_job_id", "report_command_progress", "QueuedCommandService")
```

**Why**: Export execution and progress APIs. Implement QueuedCommandService, ContextVar progress helpers and service exports from M2.

### `packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py` (MODIFY)

Created by TASK-5397; planned anchor `async def test_queued_command_rejects_bad_name() -> None:` occurs 1 time(s) in its blueprint. File does not exist on dev yet: verify actual count/line after the dependency lands before editing; this is dependency evidence, not a claimed current-source grep.

```python
# Preserve existing fixtures and tests; append the cases below.
"""Regression coverage for Implement bounded queued execution, progress and requester job control."""
import asyncio
import pytest

async def test_submit_accepts_and_delivers_result() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_queue_deadline_never_invokes_method() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_remote_live_queue_does_not_expire_early() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_slack_ack_with_slow_or_unavailable_redis() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Implement QueuedCommandService, ContextVar progress helpers and service exports from M2.

### FILL IN checklist

- [ ] packages/ai-parrot-integrations/src/parrot/integrations/core/queued/service.py — finish the scoped behavior/test branches above, bounded by AC1–AC10.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/core/queued/context.py — finish the scoped behavior/test branches above, bounded by AC1–AC10.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/core/queued/__init__.py — finish the scoped behavior/test branches above, bounded by AC1–AC10.
- [ ] packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py — finish the scoped behavior/test branches above, bounded by AC1–AC10.

## Acceptance Criteria

- [ ] AC1: submit bounds the whole path by admission_timeout and preparation by prepare_timeout; usage/timeout rejects with no job or reservation.
- [ ] AC2: 12-hex IDs are collision-checked locally; initial metadata and JSON-safe result mapping match §2 (args 500, result text 4000, error notice 300, view summary 500 chars).
- [ ] AC3: Dedup is process-local and released on every failure/cancel/completion; groups share one semaphore using the first declared cap.
- [ ] AC4: Queue timing begins at admission, including scheduling and pre-method work; queue expiry invokes no method and yields FAILED plus timed_out.
- [ ] AC5: After acquiring a slot, record execution_started_at; metadata work counts in max_runtime; timeout yields FAILED, not CANCELLED.
- [ ] AC6: Foreign expiry uses created_at + max_queue_wait + max_runtime + notify_timeout + expiry_grace; missing deadlines are unknown liveness and local live jobs never expire.
- [ ] AC7: Reads/cancels scope to Requester.actor; foreign and unknown are indistinguishable; foreign live cancel reports not_on_this_worker.
- [ ] AC8: Delivery is bounded and logged, never changes job status; JobManager._run_job alone owns state transitions. stop is idempotent and sends interruption notices before resource closure.
- [ ] AC9: Progress is visible via job views, resets its ContextVar in finally and never raises outside/inside jobs.
- [ ] AC10: First and subsequent admissions finish with a stalled Redis connect/save; no untracked jobs on cancellation immediately after acceptance.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_submit_accepts_and_delivers_result` | M2 | fake method returns "done" → `accepted` outcome with 12-hex id; deliver receives `completed` notice with the result; stored result is `{"text": "done"}` |
| `test_submit_usage_error_creates_no_job` | M2 | prepare raises `CommandUsageError` → `rejected`, message verbatim, `JobManager.jobs` empty |
| `test_submit_duplicate_returns_existing_job` | M2 | same dedup key while running → `duplicate` with the first job id; released after completion |
| `test_concurrency_group_caps_parallel_runs` | M2 | two commands in one group with cap 1 → second job reports `queued` until the first finishes |
| `test_max_runtime_times_out` | M2 | slow method → notice `timed_out`, job `FAILED` with `timed out after` |
| `test_failure_notice_and_status` | M2 | method raises → notice `failed`, job `FAILED`, error truncated |
| `test_stop_interrupts_and_notifies` | M2 | `stop()` during a run → notice `cancelled` with the shutdown reason, job `CANCELLED` |
| `test_get_and_cancel_are_owner_scoped` | M2 | another actor → `get` is `None`, `cancel` is `not_found` |
| `test_expired_view_for_orphan` | M2 | fresh foreign non-terminal record past persisted `expires_at` → expired; missing deadline is not proof of expiry; terminal states remain terminal |
| `test_report_command_progress_visible_in_view` | M2 | method calls `report_command_progress("x")` → `get()` shows `progress == "x"`; no-op outside a job |
| `test_deliver_failure_does_not_change_status` | M2 | deliver raises → job still `COMPLETED` |
| `test_slack_ack_with_slow_or_unavailable_redis` | M2/M5 | First and subsequent webhook/socket dispatch acknowledgements finish inside 3 s when Redis save/connect stalls beyond 5 s; accepted local jobs remain runnable; prepare timeout creates no job/reservation |
| `test_remote_live_queue_does_not_expire_early` | M2 | Fake clock + two managers: queue wait exceeds max_runtime plus grace but is within max_queue_wait; remote view stays queued, then sees running/completed; Job.started_at is not the expiry clock |
| `test_queue_deadline_never_invokes_method` | M2 | Queue deadline expires before slot acquisition; no method call, timed-out notice, FAILED record, dedup released; scheduling delay counts against queue budget |
| `test_queued_command_end_to_end_memory_store` | M2 + M3: a stub agent with one `@queued_command` behind a `TelegramAgentWrapper` with a mocked `Bot`: `/cmd` → ack → result reply → `/jobs` lists it → `/job_status` shows `completed` |
| `test_pr_review_end_to_end_stubbed_github` | M2 + M7: `GitHubReviewer` minimal stub (the `_MinimalReviewer` pattern, `test_github_reviewer.py:58`) with AsyncMock toolkits and a stubbed `_ask_llm_for_full_review` → service run → comment posted → chat notice rendered |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5398`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
