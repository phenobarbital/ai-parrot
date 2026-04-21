# Feature Specification: Reminder Toolkit for Agents

**Feature ID**: FEAT-115
**Date**: 2026-04-22
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.12.x

---

## 1. Motivation & Business Requirements

> One-time reminders for agents: "recuérdame en 5 horas volver a contactar al developer".

### Problem Statement

Managers and end-users frequently request **one-time, time-delayed follow-ups** inside
an ongoing agent conversation. The canonical example is the `JiraSpecialist` workflow:

> *Developer: "I'll finish the ticket in ~4 hours."*
> *Manager (to the bot): "Recuérdame en 5 horas volver a contactar a este developer."*

Today there is no LLM-facing primitive for this. The agent has no tool to schedule a
delayed, proactive message back to the requester. The `AgentSchedulerManager` already
exists for **recurring** jobs driven by decorators or REST, but there is no thin
interface for **one-shot, self-cleaning reminders** that an agent can arm at runtime.

### Goals

- Expose three LLM-facing tools: `schedule_reminder`, `list_my_reminders`, `cancel_reminder`.
- Deliver reminders proactively via the channel through which the caller is reachable
  (Telegram as MVP priority; Email, Slack and MS Teams also supported since
  `NotificationMixin.send_notification` handles them natively).
- Persist reminders in the existing APScheduler **RedisJobStore** (db=6). Reminders
  must survive process restarts.
- Guarantee self-cleanup: after firing, the job is removed from the jobstore by
  APScheduler's built-in `DateTrigger` semantics — no manual cleanup code needed.
- Enforce ownership: a user can only list/cancel their own reminders.

### Non-Goals (explicitly out of scope)

- Recurring reminders (already covered by `ScheduleType.DAILY/WEEKLY/CRON`).
- Snooze / modify-in-place (planned as post-MVP extension).
- Scheduling reminders on behalf of other users (post-MVP; requires a manager-role check).
- Reminder enrichment (e.g. "recuérdame cuando JIRA-123 cambie de estado"); that is
  event-driven, not time-driven, and belongs to a separate spec.
- Persisting reminders in `navigator.agents_scheduler` or introducing an
  `is_reminder` column on `AgentSchedule`. The explicit design decision is
  **Redis-only** persistence.
- Admin dashboard / HTTP surface. Reminders are managed by the owning user
  through agent-mediated conversation only.

---

## 2. Architectural Design

### Overview

The reminder tooling is a thin adapter on top of the existing
`AgentSchedulerManager.scheduler` (APScheduler `AsyncIOScheduler`). The LLM-facing
tools call `scheduler.add_job(...)` with `trigger="date"` + `jobstore="redis"`.
The job's callable is a **top-level coroutine** (`deliver_reminder`) that wraps
`NotificationMixin.send_notification`. All per-reminder data (channel,
recipients, message, requester identity) is persisted with the job as its
`kwargs` payload — no new database schema is introduced.

Ownership is enforced by filtering on `job.kwargs['requested_by']` at list/cancel
time, against the caller's `PermissionContext.session.user_id`. The reminder ID
is a `reminder-<uuid>` prefix so the toolkit can distinguish reminder jobs from
other scheduler jobs sharing the same Redis jobstore.

### Component Diagram

```
LLM (agent loop)
   │
   ▼
ReminderToolkit.schedule_reminder(...)         ← new tool (LLM-facing)
   │   reads PermissionContext.extra (telegram_id / email / slack_id / teams_id)
   ▼
AgentSchedulerManager.scheduler.add_job(
     deliver_reminder,
     trigger="date", run_date=run_at,
     kwargs={provider, recipients, message, requested_by, requested_at},
     id="reminder-<uuid>", jobstore="redis",
)
   │
   ▼
RedisJobStore (db=6)                           ← survives restarts
   │   at fire time:
   ▼
AsyncIOExecutor → deliver_reminder(**kwargs)   ← new top-level coroutine
   │
   ▼
NotificationMixin.send_notification(...)       ← existing multi-channel sender
   │
   ▼
APScheduler drops the job from Redis (DateTrigger exhausted)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentSchedulerManager.scheduler` | `add_job` / `get_jobs` / `get_job` / `remove_job` | Reuses the already-configured AsyncIOScheduler + RedisJobStore |
| `NotificationMixin.send_notification` | calls | Multi-channel delivery (Telegram, Email, Slack, Teams) |
| `AbstractToolkit` | subclass | `ReminderToolkit` inherits the standard method→tool conversion |
| `PermissionContext.extra` | reads | Extracts channel-specific recipient id from the current caller |
| `JiraSpecialist.post_configure` | 1-line addition | First consumer: registers the toolkit alongside `JiraToolkit` |

### Data Models

No new Pydantic models and no new database tables. The complete reminder state lives
inside the APScheduler job kwargs payload:

```python
# Reminder payload stored inside apscheduler.jobs in Redis (db=6)
{
    "provider":     "telegram" | "email" | "slack" | "teams",
    "recipients":   list[str | int],   # telegram chat_id, email, slack id, teams id
    "message":      str,                # free text from the LLM
    "requested_by": str,                # PermissionContext.session.user_id
    "requested_at": str,                # ISO-8601 UTC
}
```

Job ID convention: `reminder-<uuid4>`.

### New Public Interfaces

```python
# parrot/tools/reminder.py  (NEW FILE)

async def deliver_reminder(
    *,
    provider: str,
    recipients: list[str | int],
    message: str,
    requested_by: str,
    requested_at: str,
) -> None:
    """Top-level coroutine invoked by APScheduler when a reminder fires.

    Kept at module scope so APScheduler serializes the job reference by
    dotted path. Must NOT be a method.
    """


class ReminderToolkit(AbstractToolkit):
    """LLM-facing tools to schedule, list, and cancel one-time reminders."""

    def __init__(self, scheduler_manager, **kwargs): ...

    async def schedule_reminder(
        self,
        message: str,
        delay_seconds: int | None = None,
        remind_at: str | None = None,
        channel: str = "telegram",
    ) -> dict[str, Any]:
        """Schedule a one-time reminder delivered to the current user.

        Exactly one of delay_seconds or remind_at must be provided.
        """

    async def list_my_reminders(self) -> list[dict[str, Any]]:
        """List pending reminders owned by the current user."""

    async def cancel_reminder(self, reminder_id: str) -> dict[str, Any]:
        """Cancel a pending reminder owned by the current user."""
```

---

## 3. Module Breakdown

### Module 1: Reminder toolkit module

- **Path**: `packages/ai-parrot/src/parrot/tools/reminder.py` (NEW)
- **Responsibility**: Defines the top-level `deliver_reminder` coroutine and the
  `ReminderToolkit` class with `schedule_reminder`, `list_my_reminders`,
  `cancel_reminder`. Handles recipient resolution per channel from
  `PermissionContext.extra`. Enforces ownership on list/cancel.
- **Depends on**: `parrot.tools.toolkit.AbstractToolkit`, `parrot.notifications.NotificationMixin`,
  `parrot.auth.permission.PermissionContext`, and a reference to the runtime
  `AgentSchedulerManager` (injected at construction time).

### Module 2: JiraSpecialist wiring

- **Path**: `packages/ai-parrot/src/parrot/bots/jira_specialist.py` (MODIFY)
- **Responsibility**: Inside `post_configure()`, instantiate `ReminderToolkit`
  with `self.app["scheduler_manager"]`, extend `self.tools`, and register with
  `self.tool_manager`. Follows the same pattern already used for `JiraToolkit`
  at lines 580-614.
- **Depends on**: Module 1 being available.

### Module 3: Unit tests — toolkit

- **Path**: `packages/ai-parrot/tests/tools/test_reminder_toolkit.py` (NEW)
- **Responsibility**: Mutual-exclusion of `delay_seconds` / `remind_at`; recipient
  resolution per channel; job created with correct kwargs, `jobstore="redis"`,
  `trigger="date"`, id prefix `reminder-`; `list_my_reminders` filters by
  `requested_by`; `cancel_reminder` raises `PermissionError` for foreign jobs
  and returns `status="not_found"` for unknown ids. Uses mocked scheduler.
- **Depends on**: Module 1.

### Module 4: Unit tests — deliver_reminder

- **Path**: `packages/ai-parrot/tests/tools/test_deliver_reminder.py` (NEW)
- **Responsibility**: Validates `deliver_reminder(...)` forwards correct args
  to a mocked `NotificationMixin.send_notification`, prepends the "⏰
  Recordatorio" prefix, and does not crash when optional fields are absent.
- **Depends on**: Module 1.

### Module 5: Integration test — end-to-end with real scheduler

- **Path**: `packages/ai-parrot/tests/integration/test_reminder_e2e.py` (NEW)
- **Responsibility**: Spins up a real `AsyncIOScheduler` with `MemoryJobStore`
  (avoids Redis dependency in CI); schedules a reminder at T+2s with
  `send_notification` mocked; verifies the coroutine fires and the job is
  removed from the jobstore after execution.
- **Depends on**: Modules 1, 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_schedule_rejects_both_delay_and_remind_at` | 3 | Providing both params raises `ValueError` |
| `test_schedule_rejects_neither_delay_nor_remind_at` | 3 | Omitting both params raises `ValueError` |
| `test_schedule_uses_delay_seconds` | 3 | `delay_seconds=300` → `run_date ≈ now + 5min UTC` |
| `test_schedule_uses_absolute_remind_at` | 3 | `remind_at="2026-04-22T20:00:00Z"` → `run_date` parsed |
| `test_schedule_telegram_extracts_chat_id_from_pctx` | 3 | Recipients = `[pctx.extra['telegram_id']]` |
| `test_schedule_email_requires_email_in_pctx` | 3 | Missing email → clear `ValueError` |
| `test_schedule_slack_and_teams_recipients` | 3 | Reads `slack_user_id`/`teams_user_id` from `pctx.extra` |
| `test_schedule_adds_job_with_redis_jobstore` | 3 | `scheduler.add_job` called with `jobstore="redis"`, `trigger="date"`, id starting with `reminder-` |
| `test_schedule_returns_reminder_id_and_fires_at` | 3 | Response shape: `{"reminder_id", "fires_at", "channel"}` |
| `test_list_filters_by_requested_by` | 3 | Only jobs whose `kwargs['requested_by']` matches `pctx.user_id` are returned |
| `test_list_only_reminder_ids` | 3 | Jobs without `reminder-` prefix are excluded (not mine) |
| `test_cancel_ownership_check` | 3 | Foreign job → `PermissionError`; missing job → `{"status": "not_found"}` |
| `test_cancel_removes_job` | 3 | Owner can cancel → `scheduler.remove_job(id, jobstore="redis")` invoked |
| `test_deliver_reminder_forwards_to_send_notification` | 4 | Correct args, prefix, provider pass-through |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_reminder_fires_and_cleans_up` | Real scheduler + MemoryJobStore; schedule at T+2s; assert `send_notification` called once; assert `scheduler.get_job(id)` is `None` after execution |
| `test_restart_preserves_pending_reminder` | Simulates a process restart by pausing & resuming a scheduler backed by a persistent jobstore fixture; asserts the job is re-loaded and fires |
| `test_cancel_removes_from_jobstore` | Schedule + cancel; verify job absent from jobstore and `send_notification` never invoked |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_scheduler():
    """Stub of AgentSchedulerManager exposing a MagicMock .scheduler."""
    sm = MagicMock()
    sm.scheduler = MagicMock()
    return sm

@pytest.fixture
def telegram_pctx():
    """PermissionContext emulating a Telegram-originated request."""
    from parrot.auth.permission import PermissionContext
    from parrot.auth.session import UserSession  # verify at contract step
    return PermissionContext(
        session=UserSession(user_id="user-123", tenant_id="acme", roles=frozenset()),
        channel="telegram",
        extra={"telegram_id": 987654321},
    )

@pytest.fixture
def real_scheduler_memory(event_loop):
    """AsyncIOScheduler with MemoryJobStore — no Redis in CI."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    s = AsyncIOScheduler(jobstores={"redis": MemoryJobStore()})  # key named 'redis' to mirror prod
    s.start()
    yield s
    s.shutdown(wait=False)
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `parrot/tools/reminder.py` exists with `deliver_reminder` and `ReminderToolkit`.
- [ ] All unit tests in `test_reminder_toolkit.py` and `test_deliver_reminder.py` pass.
- [ ] Integration test `test_reminder_e2e.py` passes in CI without a live Redis.
- [ ] `JiraSpecialist.post_configure` registers `ReminderToolkit` tools alongside
      `JiraToolkit` tools; they appear in `self.tool_manager.get_tools()` output.
- [ ] Manual end-to-end verification: from Telegram, sending *"recuérdame en 2 minutos X"*
      to the `JiraSpecialist` results in a Telegram message with the `⏰ Recordatorio`
      prefix delivered ~2 minutes later.
- [ ] After firing, `scheduler.get_job(reminder_id, jobstore="redis")` returns `None`.
- [ ] Reminder scheduled before a process restart still fires correctly after restart
      (verified with RedisJobStore).
- [ ] Ownership: user A cannot cancel a reminder owned by user B (tool raises
      `PermissionError`).
- [ ] No changes to `parrot/scheduler/__init__.py`, `parrot/scheduler/models.py`,
      `parrot/scheduler/functions/__init__.py`, or `parrot/notifications/__init__.py`.
- [ ] No new external dependencies added; `apscheduler` (already optional via
      `pip install ai-parrot[scheduler]`) is sufficient.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references below have been read from the current `dev` branch and line
> numbers are accurate as of 2026-04-22. Any implementation deviation from
> these signatures must first verify against the live code.

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit
# verified: packages/ai-parrot/src/parrot/tools/toolkit.py:168

from parrot.notifications import NotificationMixin
# verified: packages/ai-parrot/src/parrot/notifications/__init__.py:55

from parrot.auth.permission import PermissionContext
# verified: packages/ai-parrot/src/parrot/auth/permission.py:80

# Optional scheduler dep — lazy-imported to preserve parrot's opt-in model
from parrot.scheduler import AgentSchedulerManager
# verified: packages/ai-parrot/src/parrot/scheduler/__init__.py:273
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/scheduler/__init__.py:273
class AgentSchedulerManager:
    def __init__(self, bot_manager=None):  # line 284
        self.scheduler: AsyncIOScheduler = ...    # line 331
    # jobstores: {"default": MemoryJobStore(), "redis": RedisJobStore(db=6, ...)}  lines 312-321
    # stored on aiohttp app at line 1449: self.app['scheduler_manager'] = self

# packages/ai-parrot/src/parrot/notifications/__init__.py:55
class NotificationMixin:
    async def send_notification(                          # line 128
        self,
        message: Union[str, Any],
        recipients: Union[List[Actor], Actor, Channel, Chat, str, List[str]],
        provider: Union[str, NotificationProvider] = NotificationProvider.EMAIL,
        subject: Optional[str] = None,
        report: Optional[Any] = None,
        template: Optional[str] = None,
        with_attachments: bool = True,
        **kwargs,
    ) -> Dict[str, Any]: ...

# packages/ai-parrot/src/parrot/tools/toolkit.py:168
class AbstractToolkit(ABC):
    tool_prefix: Optional[str] = None                     # line 219
    prefix_separator: str = "_"                           # line 222
    def __init__(self, **kwargs): ...                     # line 224
    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...   # line 261
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any: ...  # line 276

# packages/ai-parrot/src/parrot/auth/permission.py:80
@dataclass
class PermissionContext:
    session: UserSession                                  # line 117
    request_id: Optional[str] = None                      # line 118
    channel: Optional[str] = None                         # line 119
    extra: dict[str, Any] = field(default_factory=dict)   # line 120
    @property
    def user_id(self) -> str: ...                         # line 123

# packages/ai-parrot/src/parrot/bots/jira_specialist.py:546
class JiraSpecialist(Agent):
    async def post_configure(self) -> None:               # line 546
        # ... JiraToolkit set-up at lines 580-614 ...
        # pattern to mirror:
        #   self.tools.extend(tools)                      # line 611
        #   self.tool_manager.register_tools(tools)       # line 614
```

### APScheduler methods used (documented external API)

```python
# apscheduler.schedulers.asyncio.AsyncIOScheduler
scheduler.add_job(
    func,                 # callable or "module:qualname" string
    trigger="date",       # DateTrigger for one-shot
    run_date=<datetime>,  # UTC
    kwargs={...},         # serialized with the job
    id="reminder-<uuid>",
    jobstore="redis",
    replace_existing=False,
) -> apscheduler.job.Job
scheduler.get_jobs(jobstore="redis") -> list[Job]
scheduler.get_job(job_id, jobstore="redis") -> Job | None
scheduler.remove_job(job_id, jobstore="redis") -> None

# Job fields used
job.id: str
job.kwargs: dict
job.next_run_time: datetime | None
```

### How the toolkit accesses PermissionContext

The active `PermissionContext` for the current tool call is available to the
toolkit through the `_pre_execute(tool_name, **kwargs)` hook; the key is
`_permission_context` (injected at `packages/ai-parrot/src/parrot/tools/manager.py:1174`
and propagated through `packages/ai-parrot/src/parrot/tools/toolkit.py:151-155`).

**Pattern** (implementation guidance for the executor task):

```python
class ReminderToolkit(AbstractToolkit):
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:
        # Stash the per-call PermissionContext on self so bound methods can read it.
        self._pctx = kwargs.get("_permission_context")

    async def schedule_reminder(self, ...):
        pctx = self._pctx
        telegram_id = (pctx.extra or {}).get("telegram_id") if pctx else None
        ...
```

Do **not** read the context from `kwargs` inside the bound method — it is
popped before the method is invoked (see
`packages/ai-parrot/src/parrot/tools/abstract.py:391`).

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ReminderToolkit.__init__` | `AgentSchedulerManager.scheduler` | attribute access | `parrot/scheduler/__init__.py:331` |
| `ReminderToolkit.schedule_reminder` | `scheduler.add_job(...)` | APScheduler API | external |
| `deliver_reminder` | `NotificationMixin.send_notification` | instance method | `parrot/notifications/__init__.py:128` |
| `JiraSpecialist.post_configure` | `ReminderToolkit.get_tools()` + `self.tool_manager.register_tools(tools)` | follows JiraToolkit pattern | `parrot/bots/jira_specialist.py:602-614` |
| `ReminderToolkit._pre_execute` | `kwargs['_permission_context']` | lifecycle hook | `parrot/tools/toolkit.py:151-155` |
| Scheduler manager location | `self.app["scheduler_manager"]` | aiohttp app dict | `parrot/scheduler/__init__.py:1449` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.tools.reminder`~~ — new module; does not exist yet.
- ~~`AgentSchedule.is_reminder`~~ — column intentionally NOT added; this feature
  does not touch `navigator.agents_scheduler` or `scheduler/models.py`.
- ~~`CALLBACK_REGISTRY["send_reminder"]`~~ — NOT added; reminders do not use the
  scheduler callback registry. The callable is a top-level function invoked
  directly by APScheduler, not a `BaseSchedulerCallback` subclass.
- ~~`_execute_reminder_job` on `AgentSchedulerManager`~~ — NOT added.
  Reminders use the default APScheduler executor path; no custom executor
  method is needed.
- ~~`scheduler.add_reminder(...)`~~ — not a method on `AgentSchedulerManager`;
  all scheduling goes through the native APScheduler `scheduler.add_job` API.
- ~~`NotificationMixin.send_reminder(...)`~~ — not a real method. Use
  `send_notification(..., provider=...)`.
- ~~`PermissionContext.telegram_id`~~ — not a field. The telegram id lives in
  `PermissionContext.extra['telegram_id']` (verified at `permission.py:120`
  + `integrations/telegram/wrapper.py:829`).
- ~~`AbstractToolkit.add_tool()`~~ — not the way toolkits contribute tools.
  Tools are discovered automatically by the base class via method introspection;
  consumers call `toolkit.get_tools()` and register the returned list with
  `self.tool_manager.register_tools(...)` (see `parrot/tools/manager.py:554`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first: all tool methods return `Awaitable`. `deliver_reminder` is a
  coroutine invoked by `AsyncIOExecutor`.
- `NotificationMixin` is instantiated at **module scope** inside
  `parrot/tools/reminder.py` so `deliver_reminder` can use it without
  re-instantiating per fire; APScheduler serializes only the function
  reference, not captured state.
- Logging: `self.logger = logging.getLogger(self.__class__.__name__)` is already
  initialized by `AbstractToolkit.__init__`. Use it for audit lines at schedule,
  list, cancel and fire events.
- Timezone: store `run_date` as UTC explicitly; convert `remind_at` via
  `datetime.fromisoformat(...).astimezone(timezone.utc)`.
- Reminder ID: `f"reminder-{uuid.uuid4()}"` — the `reminder-` prefix is how
  `list_my_reminders` distinguishes reminder jobs from other jobs sharing the
  Redis jobstore.

### Known Risks / Gotchas

- **Callable serialization**: APScheduler serializes jobs by module path when
  persisted. `deliver_reminder` MUST be a module-scope `async def` — not a
  method, closure, or lambda. If pickling issues appear, fall back to
  `"parrot.tools.reminder:deliver_reminder"` as the string reference (accepted
  by APScheduler).
- **Redis jobstore availability**: if Redis is down at schedule time,
  `scheduler.add_job(..., jobstore="redis")` raises. Surface as a `ValueError`
  with a clear message; do not silently fall back to `MemoryJobStore` (would
  lose the reminder on restart).
- **Recipient resolution per channel**: the agent does not know the caller's
  email / Slack id unless it is in `PermissionContext.extra`. For channels
  beyond Telegram, the tool must fail fast with a clear `ValueError`. The
  caller can fill in the recipient via a subsequent tool turn if needed.
- **Clock skew**: `delay_seconds` is computed against `datetime.now(timezone.utc)`;
  APScheduler evaluates against the scheduler's timezone (`UTC` per
  `scheduler/__init__.py:335`). Both are UTC — no skew.
- **Ownership spoofing**: ownership relies on the `_permission_context`
  injected by `tool_manager`. Do NOT accept `requested_by` as an argument
  from the LLM.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `apscheduler` | already declared in `[scheduler]` extra | Reused; no version bump |
| (none new) | — | No new dependencies introduced |

---

## 8. Open Questions

- [ ] Should the ⏰ Recordatorio prefix be localizable (user locale) or hard-coded
      Spanish for now? — *Owner: Jesus*
- [ ] Should `list_my_reminders` paginate when a user has many reminders, or is
      a cap of e.g. 50 fine for the MVP? — *Owner: Jesus*
- [ ] If Redis is unreachable, should `schedule_reminder` queue the request
      into an in-memory retry buffer, or fail immediately? — *Owner: Jesus*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (all tasks sequential in one worktree).
- **Worktree**: `.claude/worktrees/feat-115-reminder-toolkit`, branched from
  the current `dev` HEAD. Auto-commit policy applies after each `/sdd-start`.
- **Parallelism**: none recommended. Tasks have a strict linear dependency
  (toolkit module → JiraSpecialist wiring → tests); any "parallel" split
  would just serialize through Python import-time collisions.
- **Cross-feature dependencies**: none. FEAT-115 is independent of FEAT-107 /
  FEAT-108 / FEAT-109 / FEAT-110 / FEAT-114.

Creation command:
```bash
git checkout dev
git worktree add -b feat-115-reminder-toolkit \
  .claude/worktrees/feat-115-reminder-toolkit HEAD
cd .claude/worktrees/feat-115-reminder-toolkit
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-22 | Jesus Lara | Initial draft scaffolded from approved plan |
