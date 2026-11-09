# TASK-5397: Define queued command models, discovery and shared messages

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Create M2 value models, a non-wrapping decorator, bound-method discovery and shared user-facing message formatters.
- Export only declarations initially; the service task extends the package exports.
- Use canonical names matching ^[a-z0-9_]{1,32}$; aliases may include hyphens.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/models.py` | CREATE | Pydantic value contracts |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/decorators.py` | CREATE | Non-wrapping decorator and discovery |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/messages.py` | CREATE | One source for user-facing job texts |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/__init__.py` | CREATE | Declaration exports |
| `packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py` | CREATE | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
from typing import Any, Awaitable, Callable, List, Literal, Optional, Sequence
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
import logging
import re
import pytest
from typing import Any, Awaitable, Callable, Literal, Optional
from typing import Any, Callable, List, Optional, Sequence
from .models import ParseMode, QueuedCommand, QueuedCommandSpec
from typing import Sequence
from .models import JobNotice, JobView, SubmitOutcome
from .decorators import discover_queued_commands, queued_command, queued_spec_of
from parrot.integrations.core.queued import queued_command, discover_queued_commands
from .models import CommandUsageError, Deliver, JobNotice, JobView, ParseMode, PreparedCommand, QueuedCommand, QueuedCommandSpec, Requester, SubmitOutcome
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py:5
def telegram_command(command: str, description: str='', parse_mode: str='keyword') -> Callable

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py:35
def discover_telegram_commands(agent: Any) -> List[Dict[str, Any]]
```

### Does NOT Exist

- core.queued and its models/decorator do not exist; create them here.
- There is no existing generic cross-platform command registry.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/core/queued/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/core/queued/decorators.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/core/queued/messages.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/core/queued/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py#telegram_command",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py#discover_telegram_commands"
  ]
}
```

## Implementation Notes



**Parallelism**: Independent: owns packages/ai-parrot-integrations/src/parrot/integrations/core/queued/models.py, packages/ai-parrot-integrations/src/parrot/integrations/core/queued/decorators.py, packages/ai-parrot-integrations/src/parrot/integrations/core/queued/messages.py, packages/ai-parrot-integrations/src/parrot/integrations/core/queued/__init__.py, packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py; consumes only existing APIs and changes no shared external state.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/models.py` (CREATE)

```python
"""Platform-neutral queued command value contracts."""
from typing import Any, Awaitable, Callable, Literal, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
ParseMode = Literal["keyword", "positional", "raw"]
class QueuedCommandSpec(BaseModel):
    """QueuedCommandSpec value contract for queued commands."""
    command: str
    description: str
    parse_mode: ParseMode = "raw"
    aliases: tuple[str, ...] = ()
    prepare: Optional[str] = None
    max_runtime: float = 1800.0
    max_queue_wait: float = 1800.0
    max_concurrent: int = 2
    concurrency_group: Optional[str] = None
class PreparedCommand(BaseModel):
    """PreparedCommand value contract for queued commands."""
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = Field(default_factory=dict)
    label: str = ""
    dedup_key: Optional[str] = None
class Requester(BaseModel):
    """Requester value contract for queued commands."""
    platform: Literal["telegram", "msteams", "slack"]
    user_id: str
    chat_id: str
    thread_id: Optional[str] = None
    message_id: Optional[str] = None
    display_name: Optional[str] = None
    @property
    def actor(self) -> str:
        """Platform-scoped identity for job ownership."""
        return f"{self.platform}:{self.user_id}"
class JobNotice(BaseModel):
    """JobNotice value contract for queued commands."""
    job_id: str
    command: str
    label: str
    status: Literal["completed", "failed", "cancelled", "timed_out"]
    result: Any = None
    error: Optional[str] = None
    elapsed_s: float = 0.0
class SubmitOutcome(BaseModel):
    """SubmitOutcome value contract for queued commands."""
    status: Literal["accepted", "duplicate", "rejected"]
    job_id: Optional[str] = None
    label: str = ""
    message: str
class JobView(BaseModel):
    """JobView value contract for queued commands."""
    job_id: str
    command: str
    label: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "expired"]
    progress: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    summary: Optional[str] = None
class QueuedCommand(BaseModel):
    """A discovered bound command and optional preparation hook."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    spec: QueuedCommandSpec
    method_name: str
    method: Callable[..., Any]
    prepare: Optional[Callable[..., Any]] = None
class CommandUsageError(ValueError):
    """Preparation rejected; show the message without creating a job."""
Deliver = Callable[[JobNotice], Awaitable[None]]
```

**Why**: Pydantic value contracts. Create M2 value models, a non-wrapping decorator, bound-method discovery and shared user-facing message formatters.

### `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/decorators.py` (CREATE)

```python
"""Declare and discover platform-neutral queued commands."""
import logging
import re
from typing import Any, Callable, List, Optional, Sequence
from .models import ParseMode, QueuedCommand, QueuedCommandSpec

def queued_command(command: str, description: str = "", parse_mode: ParseMode = "raw", *,
                   aliases: Sequence[str] = (), prepare: Optional[str] = None,
                   max_runtime: float = 1800.0, max_queue_wait: float = 1800.0,
                   max_concurrent: int = 2, concurrency_group: Optional[str] = None) -> Callable:
    """Attach validated command metadata and return the original function unchanged."""
    # FILL IN: AC2 validation plus attachment; direct method calls stay inline.
    raise NotImplementedError

def discover_queued_commands(agent: Any) -> List[QueuedCommand]:
    """Discover public bound methods, skipping missing/non-callable prepare hooks."""
    # FILL IN: AC3; follow verified Telegram discovery walk and log skipped hooks.
    raise NotImplementedError

def queued_spec_of(method: Any) -> Optional[QueuedCommandSpec]:
    """Read command metadata from bound or plain methods."""
    return getattr(method, "_queued_command", None)
```

**Why**: Non-wrapping decorator and discovery. Create M2 value models, a non-wrapping decorator, bound-method discovery and shared user-facing message formatters.

### `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/messages.py` (CREATE)

```python
"""Shared texts for queued commands and job controls."""
from typing import Sequence
from .models import JobNotice, JobView, SubmitOutcome

JOB_COMMANDS: tuple[tuple[str, str], ...] = (
    ("jobs", "Your recent jobs"), ("job_status", "Show one of your jobs"),
    ("job_cancel", "Cancel one of your running jobs"),
)
def format_ack(outcome: SubmitOutcome) -> str:
    """Render acceptance, duplicate or rejection with the label and job ID."""
    # FILL IN: AC4 and spec user-facing example; never recursively read outcome.message.
    raise NotImplementedError
def format_notice_header(notice: JobNotice) -> str:
    """Render outcome, elapsed time, label and job ID without formatting raw results."""
    # FILL IN: AC4 including timeout/interrupted wording.
    raise NotImplementedError
def format_job_view(view: JobView) -> str:
    """Render status, progress, timing and bounded summary/error."""
    # FILL IN: AC4; queued differs from running.
    raise NotImplementedError
def format_job_list(views: Sequence[JobView]) -> str:
    """Render the requester's recent jobs in supplied order."""
    # FILL IN: AC4 and an empty-list response.
    raise NotImplementedError
def format_cancel(result: str, job_id: str) -> str:
    """Render cancelling/not-found/finished/not-on-this-worker consistently."""
    # FILL IN: AC4; unknown and foreign use No job <id> found for you.
    raise NotImplementedError
```

**Why**: One source for user-facing job texts. Create M2 value models, a non-wrapping decorator, bound-method discovery and shared user-facing message formatters.

### `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/__init__.py` (CREATE)

```python
"""Public queued command declarations."""
from .decorators import discover_queued_commands, queued_command, queued_spec_of
from .models import (
    CommandUsageError, Deliver, JobNotice, JobView, ParseMode, PreparedCommand,
    QueuedCommand, QueuedCommandSpec, Requester, SubmitOutcome,
)
__all__ = (
    "CommandUsageError", "Deliver", "JobNotice", "JobView", "ParseMode", "PreparedCommand",
    "QueuedCommand", "QueuedCommandSpec", "Requester", "SubmitOutcome",
    "discover_queued_commands", "queued_command", "queued_spec_of",
)
```

**Why**: Declaration exports. Create M2 value models, a non-wrapping decorator, bound-method discovery and shared user-facing message formatters.

### `packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py` (CREATE)

```python
"""Regression coverage for Define queued command models, discovery and shared messages."""
import pytest
from parrot.integrations.core.queued import queued_command, discover_queued_commands

async def test_queued_command_rejects_bad_name() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_discover_skips_missing_prepare() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Create M2 value models, a non-wrapping decorator, bound-method discovery and shared user-facing message formatters.

### FILL IN checklist

- [ ] packages/ai-parrot-integrations/src/parrot/integrations/core/queued/models.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/core/queued/decorators.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/core/queued/messages.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/core/queued/__init__.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.
- [ ] packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.

## Acceptance Criteria

- [ ] AC1: Models match spec §2 exactly, including Requester.actor = platform:user_id, all timing fields and result types.
- [ ] AC2: Decorator returns the original function, validates positive finite timing/cap values, and attaches QueuedCommandSpec.
- [ ] AC3: Discovery skips private attributes and invalid prepare hooks with logging; queued_spec_of supports bound/plain methods.
- [ ] AC4: All ack/status/list/cancel/notice texts live in messages.py; foreign and unknown IDs produce the same wording.
- [ ] AC5: No platform SDK or server import enters core.queued.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_queued_command_rejects_bad_name` | M2 | `"pr-review"` / uppercase / >32 chars as canonical → `ValueError` at decoration |
| `test_discover_skips_missing_prepare` | M2 | `prepare="_nope"` → command skipped, error logged, others still discovered |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5397`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
