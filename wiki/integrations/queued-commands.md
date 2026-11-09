---
title: Queued chat commands
summary: Queued chat commands configuration, APIs and operational behavior.
---

# Queued chat commands

## Purpose

Queued commands acknowledge a long-running chat request immediately with a job
id, run the agent method in an asyncio task, and deliver the result back to the
conversation that requested it. They are available on Telegram, Microsoft
Teams, and Slack when the wrapped agent declares at least one command. The
built-in `/jobs`, `/job_status <job_id>`, and `/job_cancel <job_id>` commands
are scoped to the requesting user.

## Public API

- [`queued_command`](ref:parrot.integrations.core.queued.queued_command) marks
  an agent method as a queued command without wrapping direct Python calls.
- [`QueuedCommandService`](ref:parrot.integrations.core.queued.QueuedCommandService)
  performs local admission, preparation, execution, progress reporting, and
  delivery for one platform wrapper.
- [`report_command_progress`](ref:parrot.integrations.core.queued.report_command_progress)
  updates the running job's requester-visible progress text.
- [`JobManager`](ref:parrot.jobs.JobManager) stores the job lifecycle; use its
  `cancel_job(job_id, reason)` method for non-destructive cancellation.

Declare an async agent method with a stable canonical command name. A prepare
hook validates arguments before a job exists, so it must not perform network
I/O and should raise `CommandUsageError` with user-facing usage text.

```python
from parrot.integrations.core.queued import CommandUsageError, PreparedCommand, queued_command


class ReviewAgent:
    @queued_command(
        "report",
        description="Build the requested report in the background",
        parse_mode="raw",
        aliases=("build-report",),
        prepare="_prepare_report",
        max_runtime=900,
        max_queue_wait=300,
        max_concurrent=2,
        concurrency_group="reports",
    )
    async def report(self, target: str) -> str:
        return f"Report for {target}"

    async def _prepare_report(self, raw: str) -> PreparedCommand:
        if not raw.strip():
            raise CommandUsageError("Usage: /report <target>")
        return PreparedCommand(kwargs={"target": raw.strip()}, label="requested report")
```

## Configuration & Parameters

The decorator's `command` is lowercase letters, digits, and underscores; it is
the menu name. `aliases` are additional routing names and may contain a hyphen,
but Telegram never shows aliases in its command menu. `max_runtime` bounds
execution after a slot is acquired, while `max_queue_wait` independently bounds
time waiting for that slot. `max_concurrent` limits one command or the named
`concurrency_group`; commands in the same group share that group's first cap.

Queued wrappers use `JobManager` with Redis key prefix `parrot:chat_jobs` when
Redis is available, and retain a memory-only local fallback when it is not.
Platform setup is still required:

- Telegram registers each canonical command and the three job controls. Results
  return to the same chat, forum topic, and reply target.
- Teams requires the bot configuration `client_id`; otherwise queued commands
  are rejected because proactive result delivery cannot be established. Results
  use the captured conversation reference and `continue_conversation`.
- Slack must declare these slash commands in its app manifest:
  `/pr_review`, `/review_pr`, `/jobs`, `/job_status`, `/job_cancel`, and,
  optionally, `/pr-review`. The endpoint must acknowledge within Slack's
  request window; result delivery is a later message in the same channel that
  mentions the requester.

## Usage Examples

For an agent that exposes the GitHub reviewer commands:

```text
/pr_review https://github.com/acme/api/pull/412 NAV-8036 --auto-draft
/job_status 3f9c2a1b7d40
/jobs
/job_cancel 3f9c2a1b7d40
```

The acceptance reply includes the job id. A duplicate active request with the
same command-specific deduplication key returns the existing job instead of
starting another one. `/job_status` and `/job_cancel` intentionally treat a
different user's job like an unknown id.

## Gotchas

Queue and execution deadlines are separate. A job that cannot acquire its
concurrency slot before `max_queue_wait` fails without calling the agent;
execution that outlives `max_runtime` also fails. The persisted total lifetime
is immutable and is used for foreign-record expiry.

Jobs execute only in the process that accepted them. Redis makes status reads
fresh across workers, but cancellation and deduplication are local to the
owning process. There is no external worker, broker, restart resumption, or
cross-worker cancellation/deduplication. During a Redis outage, local admission
and execution can continue, while cross-worker visibility and persistence are
unavailable until Redis saves succeed. Shutdown cancels local running jobs and
sends an interruption notice when the platform session remains available.

## Related

- [GitHub reviewer](github-reviewer.md) — queued `/review_pr` and `/pr_review`.
- [JobManager](../flows/jobmanager.md) — lifecycle and persistence semantics.
