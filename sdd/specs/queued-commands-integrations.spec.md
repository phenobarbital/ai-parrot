---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-integrations, ai-parrot-server, ai-parrot-tools]
tags: [integrations, background-jobs, chat-commands, github-reviewer, pr-review]
docs:
  policy: required
  pages:
    - wiki/integrations/queued-commands.md
    - wiki/integrations/github-reviewer.md
    - wiki/flows/jobmanager.md
  api_modules:
    - parrot.jobs
    - parrot.integrations.core.queued
---

# Feature Specification: Queued chat commands for the integrations (first consumer: `/pr_review`)

**Feature ID**: FEAT-851
**Date**: 2026-11-09
**Author**: Jesus Lara
**Status**: draft
**Target version**: 2.2.0

---

## 1. Motivation & Business Requirements

### Problem Statement

Chat commands on the Telegram, MS Teams and Slack integrations run **inline**: the
handler awaits the agent method and only then replies. That is fine for a lookup,
but some commands take minutes. Reviewing a pull request is the clearest case:
`GitHubReviewer.review_pr` (`/review_pr`) awaits `strict_review_pull_request`
inside the Telegram handler, with no timeout. The wiki wait alone can take up to
`GITHUB_REVIEW_WIKI_WAIT` = 120 s, and a measured review takes about 66 s on top.
The user stares at a typing indicator for about three minutes. Each platform also
has a hard request window: Slack drops a slash command that is not acknowledged
within 3 s, and Teams runs the whole command inside the Bot Framework HTTP turn.

We need **queued commands**. A queued command:

1. validates its arguments,
2. answers at once with the acceptance and a **job id**,
3. runs the real work as a background job, and
4. pushes the result back to the conversation that asked.

The user can ask for the status of their jobs, or cancel one, at any time.

The first consumer is a **full PR reviewer** for `GitHubReviewer`, `/pr_review`
(`/pr-review` where the platform allows a hyphen). It mirrors the Claude Code
command `.claude/commands/pr-review.md`:
- per-criterion compliance with the Jira acceptance criteria;
- description alignment;
- lightweight code-quality observations;
- an assessment of the AI-bot review comments already on the PR;
- a structured report that is always posted to the PR as a comment.

The existing strict gate `/review_pr` moves to the same queued path.

### Goals

- **G1 — Channel-neutral queued-command layer.** A single decorator,
  `@queued_command`, marks an agent method as a background command. It is
  discovered and exposed by the Telegram, MS Teams and Slack wrappers.
  - The handler replies within the platform's request turn with
    `accepted · job <id>`.
  - The method runs as a background job.
  - Its return value (`str`, `ChartReply`, or anything `parse_response`
    understands) is delivered to the originating chat, topic or conversation.
- **G2 — One job system.** The job store is the existing `JobManager` +
  `RedisJobStore`, moved from `ai-parrot-server` into core `parrot.jobs` so the
  integrations can use it without a new dependency edge.
  - `parrot.handlers.jobs` keeps re-exporting the same names; no importer
    changes.
  - Chat jobs are Redis-backed (memory fallback), so their status survives a
    restart and is readable from any worker.
- **G3 — Job control commands.** Each platform that exposes a queued command
  also gets three built-in commands: `/jobs` (the requester's recent jobs),
  `/job_status <id>` and `/job_cancel <id>`. Reads and cancels are scoped to the
  requester.
- **G4 — Bounded execution.** Every queued command declares:
  - a `max_runtime`, enforced with a timeout;
  - a per-command concurrency cap (extra jobs wait for a slot, shown as
    "queued");
  - an optional dedup key (e.g. one active review per PR).

  Shutdown cancels running jobs and tells each requester that their job was
  interrupted.
- **G5 — `/pr_review` full review.** `/pr_review <PR> [JIRA-KEY] [--auto-draft] [--dry-run]`
  on `GitHubReviewer`. Same review content and report structure as the Claude
  `/pr-review` command.
  - The report is always posted as a PR comment, unless `--dry-run`.
  - `--auto-draft` converts the PR to draft when the verdict is "does not meet
    criteria".
  - It never submits an APPROVE or REQUEST_CHANGES review.
- **G6 — `/review_pr` becomes queued.** Same arguments, same verdict and reply
  text, delivered asynchronously with a job id.
- **G7 — New PR-context reads in `GitToolkit`.** List a PR's changed files,
  issue comments, reviews and inline review comments. The full review needs
  these to see bot findings and to cope with large PRs.

### Non-Goals (explicitly out of scope)

- **No external worker process or broker.** Jobs run as asyncio tasks in the
  process that accepted them. The pinned-but-unused `rq` stays unused; no
  Celery/arq.
- **No re-delivery after a restart.** A job interrupted by a restart is
  reported as interrupted (at shutdown) or `expired` (on a later status read).
  It is not resumed or re-run.
- **No cross-worker cancel or dedup.**
  - Cancel and dedup act on the process that runs the job.
  - Status reads work from any worker (via Redis).
- **No WhatsApp or Matrix support.**
  - WhatsApp dispatches only hard-coded `/clear` and `/help`, and never
    dispatches `config.commands`.
  - Matrix has only a `!ask` prefix.

  Neither has agent-method commands to build on.
- **No conversation-history writes for job results.** Results are chat messages,
  not conversation turns, so `AbstractBot.save_conversation_turn()` stays the
  only history writer (ADR-SEED-0002).
- **Not adopting other queue implementations.** `navigator.background`,
  `AgentService`/`TaskQueue`, `RedisJobInjector`,
  `SchedulerManager.run_schedule_now` and the sdd_coder `JobTable` were
  evaluated and are not used (see §7).
- **`/pr_review` does not add labels, save a report file to git, or post inline
  review comments.** Those are optional or local-only steps of the Claude
  command.
- **No conversion of `GitToolkit` from `requests` to aiohttp.** The new read
  methods reuse its existing thread-offloaded `_request` helper.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:b26f6bbc1103c16151daca30e53b404e617f1d8e6c7ac0a58b45b4d6c1e14da5 evaluation_digest=sha256:726e05c30156c333132dc30b4650f80b6839a94dc74d6b6a384b59a9d4720ba1 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

**Three layers.** Each layer depends only on the one below it.

1. **`parrot.jobs` (core, M1).** The existing `JobManager` / `Job` / `JobStatus` /
   `RedisJobStore` are moved verbatim out of `ai-parrot-server`
   (`parrot/handlers/jobs/{job,models,redis_store}.py`).
   - The three server modules become re-export shims, so
     `from parrot.handlers.jobs import JobManager` and every other existing
     import path keeps working.
   - The move adds three things:
     - `JobManager.cancel_job(job_id, reason)` — a non-destructive cancel that
       keeps the record as `CANCELLED`. Today the only cancel is
       `delete_job`, which erases the record.
     - A `user_id` filter on `list_jobs` / `list_jobs_async`.
     - A per-user Redis secondary index, so "my jobs" does not starve behind
       other users' jobs. Today `RedisJobStore.list_jobs` scans only the
       newest `limit*2` ids.
2. **`parrot.integrations.core.queued` (integrations, M2).** The
   channel-neutral queued-command layer:
   - `@queued_command(...)` attaches a `QueuedCommandSpec` to an agent method.
   - `discover_queued_commands(agent)` returns the bound commands.
   - `QueuedCommandService` owns one `JobManager` per wrapper.
     - Store: Redis key prefix `parrot:chat_jobs`, with a memory-only
       fallback when Redis is down (the same fallback `JobManager.start()`
       already has).
     - It parses and prepares arguments, enforces dedup, the per-command or
       per-group concurrency cap and `max_runtime`, and runs the method as a
       job.
     - It hands the outcome to a platform-supplied `deliver` callback.
   - `messages.py` renders the ack, status, list and notice texts once for
     every platform.
   - A ContextVar exposes the current job, so a long command can call
     `report_command_progress("…")`, which shows up in `/job_status`.
3. **Platform adapters (M3 Telegram, M4 MS Teams, M5 Slack).** They copy the
   knowledge-upload adapter pattern (FEAT-647: `TelegramKnowledgeUpload`,
   `register_knowledge_upload_commands`, `SlackKnowledgeUpload`). Each adapter:
   - discovers the agent's queued commands;
   - registers them, plus `jobs` / `job_status` / `job_cancel`, on its
     platform router;
   - builds a `Requester` and a `deliver` closure from the incoming message,
     calls `service.submit()` and answers with the ack — all inside the
     platform's request turn.

   Delivery per platform:

   | Platform | `deliver` sends the result with | Lands in |
   |---|---|---|
   | Telegram | new `TelegramAgentWrapper.send_parsed_to_chat()` | same chat and forum topic, as a reply to the command message |
   | MS Teams | `adapter.continue_conversation(conv_ref, …)` (knowledge-upload pattern) | same conversation |
   | Slack | `SlackAgentWrapper.post_message(channel, …)` | same channel, mentioning the requester |

**First consumer: `GitHubReviewer` (M7).**

- **`/pr_review <PR> [JIRA-KEY] [--auto-draft] [--dry-run]`** (alias `pr-review` on
  Slack and Teams; routing-only on Telegram) runs `full_review_pull_request()`.
  The menu shows `pr_review` everywhere, per the user's decision.
  1. Gather the context:
     - PR metadata and the truncated diff;
     - the changed-file list from the new `GitToolkit.list_pull_request_files`;
     - issue comments, reviews and inline review comments, classified by bot;
     - the Jira ticket: the explicit key, or `_resolve_requirement()` with its
       SDD-spec fallback;
     - CI checks (informational);
     - wiki context, under the same lease and bounded wait as the strict path.
  2. Ask the LLM, with the read tools, for a structured `FullPRReview`.
  3. Apply the deterministic verdict floor (see Edge cases below).
  4. Render the report with exactly the Claude `/pr-review` headings.
  5. **Always post it as a PR comment**, unless `--dry-run`.
  6. With `--auto-draft` and verdict `does_not_meet`, convert the PR to draft.
  7. Return a chat summary.

  It never submits an APPROVE or REQUEST_CHANGES review. An LLM failure
  raises `FullReviewLLMError`, which ends the job as failed with **nothing
  written to GitHub**. This deliberately differs from the strict path, where a
  failed LLM call becomes `approve=False` and can cascade into a draft.
- **`/review_pr <PR>`** keeps its body and its strict-gate behavior. Only the
  decorator changes: `@telegram_command` → `@queued_command(..., prepare="_prepare_review_pr")`.
  - The same verdict text (`_format_command_reply`) is now delivered when the
    job finishes.
  - Because the layer is channel-neutral, `/review_pr` becomes available on
    Teams and Slack too.
- **Shared concurrency.** Both commands share the concurrency group
  `github_review` (default 2 concurrent reviews per wrapper). Each dedups on
  its own key:
  - `pr_review:<repo>#<n>` — one full review per PR at a time;
  - `review_pr:<repo>#<n>`.

**User-facing behavior (Telegram example):**

```
user> /pr_review https://github.com/acme/api/pull/412 NAV-8036 --auto-draft
bot>  ⏳ Accepted — job `3f9c2a1b7d40`: full review of acme/api#412.
      I'll post the result here. Track it with /job_status 3f9c2a1b7d40
...   (≈3 min later, as a reply to the command message, same forum topic)
bot>  ✅ Job `3f9c2a1b7d40` finished in 3m12s — full review of acme/api#412
      ⚠️ acme/api#412 — Add retry to export job
      Verdict vs NAV-8036: Needs Attention · AC met 3/4 (75%)
      • [MAJOR] export/retry.py — retries are not bounded
      Report: https://github.com/acme/api/pull/412#issuecomment-…
      Draft: not converted (verdict is not "does not meet")
user> /jobs
bot>  Your recent jobs:
      `3f9c2a1b7d40` ✅ completed · full review of acme/api#412 · 3m ago
```

**Edge cases & error handling:**

- **Bad arguments.** `prepare` raises `CommandUsageError`, and the user gets the
  usage text immediately. No job is created.
- **A second request for the same PR while one is active** returns
  `🔁 Already running — job <id>`.
- **Concurrency cap reached.** The job is accepted and waits for a slot.
  `/job_status` shows `queued (waiting for a slot)`.
- **Timeouts.** A job that exceeds `max_runtime` is cancelled and recorded as
  `FAILED`, with error `timed out after <n>s`. The requester gets a
  `⌛ timed out` notice.
- **Shutdown.** Running jobs are cancelled. Each requester gets
  `🛑 Job <id> was interrupted — the bot is shutting down; run the command again`.
  The record ends `CANCELLED`.
- **A job orphaned by a crash** (non-terminal in Redis, not tracked by any live
  process) reads as `expired` once
  `(started_at or created_at) + max_runtime + expiry_grace` has passed.
- **Delivery failures** (chat gone, bot kicked) are logged and never change the
  job's recorded status.
- **`/job_status` / `/job_cancel` on another user's job** answer exactly like an
  unknown id: `No job <id> found for you.` That gives no existence oracle
  (`AgentJobs` precedent).
- **`/job_cancel` on a job running on another worker** says it cannot be
  cancelled from here. A finished job reports its final status.
- **`/pr_review` with an explicit Jira key that cannot be read** ends with
  status `ticket_not_found`. Nothing is posted.
- **No resolvable ticket at all.** The review runs anyway; the AC section says
  "No ticket linked — acceptance criteria not evaluated". The verdict is capped
  at `needs_attention`, and `--auto-draft` never fires.
- **Deterministic verdict floor.** If any criterion is `not_met`, an LLM
  `approved` is downgraded to `needs_attention`.
- **Closed or merged PRs.** `/pr_review` reviews them, and the report states the
  state. `--auto-draft` applies only to an open PR.
- **Draft PRs.** On an already-draft PR, `--auto-draft` reports
  `already a draft`.
- **`--dry-run`** wins over `--auto-draft`: no GitHub writes at all. The full
  report is sent to the chat instead.
- **Large reports.** A report longer than GitHub's 65,536-character comment
  limit is truncated, with a note. If posting the comment fails, the chat reply
  carries the full report, so it is never lost.
- **iOS smart punctuation** turns `--auto-draft` into `—auto-draft`. The parser
  normalizes a leading `—` or `–` to `--`.
- **`/function pr_review …` / `/call review_pr …`** (Telegram and Teams generic
  method invokers) refuse any method that carries `_queued_command`, with
  `Use /pr_review — it runs in the background.` Otherwise they would run it
  inline and blow the Teams HTTP turn.

### Component Diagram

```
 Telegram msg / Teams activity / Slack slash cmd
            │
            ▼
 TelegramQueuedCommands │ TeamsQueuedCommands │ SlackQueuedCommands      (M3/M4/M5)
   build Requester + deliver()   ──►  ack text (messages.format_ack)
            │ submit(command, raw_args, requester, deliver)
            ▼
 QueuedCommandService  (M2)  ── parse → prepare → dedup → JobManager.create_job
            │                    execute_job(runner):
            │                      semaphore(group) → wait_for(method(*a, **kw), max_runtime)
            │                      → deliver(JobNotice)
            ▼
 parrot.jobs.JobManager + RedisJobStore (M1)   key prefix parrot:chat_jobs
            │
            ▼ method
 GitHubReviewer.pr_review → full_review_pull_request (M7)
     ├─ GitToolkit.get_pull_request / get_pull_request_diff
     ├─ GitToolkit.list_pull_request_files / _comments / _reviews / _review_comments (M6)
     ├─ JiraToolkit via _fetch_ticket / _resolve_requirement
     ├─ wiki lease + Agent.ask(structured_output=FullPRReview)
     └─ GitToolkit.add_pr_comment  [+ convert_pr_to_draft on --auto-draft]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `JobManager` / `RedisJobStore` (`ai-parrot-server/.../handlers/jobs/`) | moved to core + extended | verbatim move to `parrot/jobs/`; server modules become shims; adds `cancel_job`, `user_id` filter, per-user index |
| `TelegramAgentWrapper` | extended | registers the queued adapter after `_register_agent_commands()` (L337); new `send_parsed_to_chat()`; `close()` stops the service |
| `discover_telegram_commands` | modified | skips methods that carry `_queued_command` (no double registration) |
| `TelegramAgentWrapper.handle_function` / `_execute_agent_method` | modified | refuse queued methods |
| `MSTeamsAgentWrapper` / `MSTeamsCommandRouter` | extended | `register_queued_commands(self._command_router, self)` after knowledge upload (L218); new `close_queued_commands()` |
| `AgentCommandHandler.handle_function` / `handle_call` (Teams) | modified | refuse queued methods |
| `SlackAgentWrapper` / `SlackCommandRouter` | extended | adapter registered after the router is built (L123); `start()` warms the service; `stop()` shuts it down; `_help_text` lists queued commands |
| `IntegrationBotManager.shutdown` / `TelegramBotManager.shutdown` | modified | call `TelegramAgentWrapper.close()` before `bot.session.close()` (never called today); call `close_queued_commands()` on Teams wrappers |
| `GitToolkit` | extended | four new read-only PR-context methods |
| `GitHubReviewer` | extended | new `/pr_review` + full review; `/review_pr` decorator swap |
| `parrot.conf` | extended | `GITHUB_REVIEW_FULL_MAX_TOOL_CALLS`, `GITHUB_REVIEW_COMMAND_MAX_RUNTIME` |

### Data Models

```python
# parrot/integrations/core/queued/models.py
ParseMode = Literal["keyword", "positional", "raw"]

class QueuedCommandSpec(BaseModel):
    command: str                         # canonical, ^[a-z0-9_]{1,32}$ (validated at decoration)
    description: str
    parse_mode: ParseMode = "raw"
    aliases: tuple[str, ...] = ()        # extra routing names (may contain '-'); never in the Telegram menu
    prepare: Optional[str] = None        # name of an agent method: (raw_or_parsed) -> PreparedCommand
    max_runtime: float = 1800.0          # seconds, > 0
    max_concurrent: int = 2              # >= 1, slots of the semaphore
    concurrency_group: Optional[str] = None  # commands sharing a group share one semaphore (first spec's cap wins)

class PreparedCommand(BaseModel):
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = Field(default_factory=dict)
    label: str = ""                      # human label, e.g. "full review of acme/api#412"
    dedup_key: Optional[str] = None

class Requester(BaseModel):
    platform: Literal["telegram", "msteams", "slack"]
    user_id: str
    chat_id: str
    thread_id: Optional[str] = None      # Telegram forum topic id
    message_id: Optional[str] = None     # message to reply to
    display_name: Optional[str] = None
    # property actor -> f"{platform}:{user_id}"  (scopes reads and cancels; stored as Job.user_id)

class JobNotice(BaseModel):
    job_id: str
    command: str
    label: str
    status: Literal["completed", "failed", "cancelled", "timed_out"]
    result: Any = None                   # method return value (completed only)
    error: Optional[str] = None
    elapsed_s: float = 0.0

class SubmitOutcome(BaseModel):
    status: Literal["accepted", "duplicate", "rejected"]
    job_id: Optional[str] = None
    label: str = ""
    message: str                         # user-facing ack / usage text (format_ack output)

class JobView(BaseModel):
    job_id: str
    command: str
    label: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "expired"]
    progress: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    summary: Optional[str] = None        # first 500 chars of the stored result text
```

Job record mapping (stored through `JobManager`):

| `Job` field | Value |
|---|---|
| `job_id` | `uuid4().hex[:12]` (regenerated when it collides) |
| `obj_id` | `f"{owner}:{command}"` |
| `query` | `{"command": str, "args": raw_args[:500]}` |
| `user_id` | `requester.actor` |
| `session_id` | `requester.chat_id` |
| `execution_mode` | `"queued_command"` |
| `metadata` | `{command, label, dedup_key, max_runtime, platform, chat_id, thread_id, phase: queued\|running, progress}` |
| `result` | `{"text": <text output, truncated to 4000 chars>}` (JSON-safe; never the raw object) |

```python
# parrot/bots/github_reviewer.py (new models, next to PRReviewResult)
class CriterionAssessment(BaseModel):
    criterion: str
    status: Literal["met", "partial", "not_met", "unable_to_verify"]
    evidence: str

class DescriptionAlignment(BaseModel):
    addressed: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    out_of_scope: List[str] = Field(default_factory=list)

class CodeObservation(BaseModel):
    severity: Literal["info", "minor", "major", "blocker"]
    file: Optional[str] = None
    line: Optional[int] = None
    note: str

class BotFindingAssessment(BaseModel):
    bot: str
    file: Optional[str] = None
    finding: str
    assessment: Literal["agree", "disagree", "resolved", "false_positive"]
    comment: str = ""

class FullPRReview(BaseModel):
    criteria: List[CriterionAssessment] = Field(default_factory=list)
    description: DescriptionAlignment = Field(default_factory=DescriptionAlignment)
    code_observations: List[CodeObservation] = Field(default_factory=list)
    bot_findings: List[BotFindingAssessment] = Field(default_factory=list)
    verdict: Literal["approved", "needs_attention", "does_not_meet"]
    recommended_action: Literal["APPROVE", "REQUEST_CHANGES", "CONVERT_TO_DRAFT"]
    summary: str = ""

class FullReviewLLMError(RuntimeError):
    """The full-review LLM call failed or returned no structured result."""
```

### New Public Interfaces

```python
from parrot.integrations.core.queued import queued_command, PreparedCommand, CommandUsageError

class MyAgent(Agent):
    @queued_command(
        "pr_review",
        description="Full PR review against its Jira ticket (runs in the background)",
        parse_mode="raw",
        aliases=("pr-review",),
        prepare="_prepare_pr_review",
        max_runtime=1800,
        max_concurrent=2,
        concurrency_group="github_review",
    )
    async def pr_review(self, target: str = "", jira_key: str | None = None,
                        auto_draft: bool = False, dry_run: bool = False, **kwargs) -> str:
        ...

    async def _prepare_pr_review(self, raw: str) -> PreparedCommand:
        ...  # raise CommandUsageError("Usage: …") on bad input; no network calls

# Built-in commands added on every platform that exposes >= 1 queued command:
#   /jobs                  — requester's 10 most recent jobs
#   /job_status <job_id>   — status, label, progress, timings, error/summary
#   /job_cancel <job_id>   — cancel the requester's own job (this worker only)
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Core job primitives (`parrot.jobs`) | yes | verbatim move + shims; `cancel_job` / `user_id` / per-user index signatures fixed below | — |
| M2: Queued-command layer | no | — | service runner semantics (cancel reasons, notify timeout, expiry) need judgement while coding |
| M3: Telegram adapter | yes | knowledge-upload adapter pattern; `send_parsed_to_chat` signature fixed below | — |
| M4: MS Teams adapter | yes | knowledge-upload `continue_conversation` pattern; signatures fixed below | — |
| M5: Slack adapter | yes | router handler contract `async (payload) -> dict`; signatures fixed below | — |
| M6: GitToolkit PR-context reads | yes | `_resolve_connection` + `_request` + `asyncio.to_thread` + `@tool_schema`, the exact shape of `list_pull_requests` | — |
| M7: GitHubReviewer `/pr_review` + queued `/review_pr` | no | — | prompt design and the report renderer need judgement |
| M8: Documentation | yes | pages listed in §10 | — |

### Module 1: Core job primitives (`parrot.jobs`)
- **Path**: `packages/ai-parrot/src/parrot/jobs/` (new); shims in `packages/ai-parrot-server/src/parrot/handlers/jobs/{job,models,redis_store}.py`
- **Responsibility**:
  - Move `Job`, `JobStatus`, `JobManager` and `RedisJobStore` into core, unchanged. Use `git mv` semantics: the code moves, it is not copied.
  - Keep every old import path working through re-export shims.
  - Add a non-destructive cancel, a `user_id` filter, and a per-user Redis index.
  - Do not add a new pyproject dependency: `redis.asyncio` stays a lazy import inside `RedisJobStore`.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/jobs/__init__.py  (new)
  from .models import Job, JobStatus
  from .manager import JobManager
  from .redis_store import RedisJobStore
  __all__ = ("Job", "JobStatus", "JobManager", "RedisJobStore")

  # packages/ai-parrot/src/parrot/jobs/models.py  (new — moved verbatim from
  #   ai-parrot-server/src/parrot/handlers/jobs/models.py; JobStatus verified: models.py:6, Job: models.py:16)

  # packages/ai-parrot/src/parrot/jobs/manager.py  (new — moved from handlers/jobs/job.py; class JobManager verified: job.py:22)
  class JobManager:
      async def cancel_job(self, job_id: str, reason: str = "Job was cancelled") -> bool:
          """Cancel this process's task for ``job_id`` but keep its record.

          The job ends ``CANCELLED`` with ``error == reason`` (``_run_job``'s CancelledError
          branch must use the stored reason instead of the fixed text). Returns ``False`` when the
          job is unknown to this process, already finished, or has no live task.
          """
      def list_jobs(self, obj_id: Optional[str] = None, status: Optional[JobStatus] = None,
                    limit: int = 100, user_id: Optional[str] = None) -> list:  # verified: job.py:321 (adds user_id)
          """In-memory listing, newest first; ``user_id`` filters on ``Job.user_id``."""
      async def list_jobs_async(self, obj_id: Optional[str] = None, status: Optional[JobStatus] = None,
                                limit: int = 100, user_id: Optional[str] = None) -> list:  # verified: job.py:347 (adds user_id)
          """Redis-backed listing (memory fallback); forwards ``user_id`` to the store."""

  # packages/ai-parrot/src/parrot/jobs/redis_store.py  (new — moved; class RedisJobStore verified: redis_store.py:120)
  class RedisJobStore:
      async def save(self, job: Job) -> None:            # verified: redis_store.py:209
          """Also ZADD ``{prefix}:_user:{user_id}`` (score created_at) when ``job.user_id`` is set;
          the per-user zset gets the same terminal-state EXPIRE as the job hash."""
      async def delete(self, job_id: str) -> bool:       # verified: redis_store.py:247
          """Also ZREM the id from its per-user index."""
      async def list_jobs(self, obj_id: Optional[str] = None, status: Optional[JobStatus] = None,
                          limit: int = 100, user_id: Optional[str] = None) -> List[Job]:  # verified: redis_store.py:261
          """With ``user_id`` read ``{prefix}:_user:{user_id}`` instead of the global index; prune stale ids
          from whichever index was read."""

  # packages/ai-parrot-server/src/parrot/handlers/jobs/job.py  (modified → shim)
  from parrot.jobs.manager import JobManager
  from parrot.jobs.models import Job, JobStatus
  __all__ = ("JobManager", "Job", "JobStatus")
  # handlers/jobs/models.py → re-exports Job, JobStatus; handlers/jobs/redis_store.py → re-exports RedisJobStore
  # handlers/jobs/__init__.py, mixin.py, worker.py stay unchanged (they import from .job / .models)
  ```

### Module 2: Queued-command layer (`parrot.integrations.core.queued`)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/` (new package: `__init__.py`, `models.py`, `decorators.py`, `service.py`, `context.py`, `messages.py`)
- **Responsibility**:
  - The channel-neutral decorator, discovery, models, service, progress ContextVar and message rendering.
  - No platform imports: no aiogram, botbuilder or Slack.
- **Depends on**: M1 (`parrot.jobs.JobManager`, `RedisJobStore`, `JobStatus`, `cancel_job`, `list_jobs_async(user_id=)`).
- **Interface Skeleton**:
  ```python
  # core/queued/decorators.py  (new)
  def queued_command(
      command: str,
      description: str = "",
      parse_mode: ParseMode = "raw",
      *,
      aliases: Sequence[str] = (),
      prepare: Optional[str] = None,
      max_runtime: float = 1800.0,
      max_concurrent: int = 2,
      concurrency_group: Optional[str] = None,
  ) -> Callable:
      """Mark an agent method as a background (queued) chat command.

      Stores ``fn._queued_command = QueuedCommandSpec(...)`` and returns ``fn`` unchanged (no wrapper),
      so direct calls still run inline. Raises ``ValueError`` at decoration time when ``command`` does
      not match ``^[a-z0-9_]{1,32}$`` or ``max_runtime``/``max_concurrent`` are not positive.
      """

  def discover_queued_commands(agent: Any) -> List[QueuedCommand]:
      """Scan public attributes for ``_queued_command`` (same walk as discover_telegram_commands,
      verified: telegram/decorators.py:35-68). Resolves ``spec.prepare`` with getattr; when it is
      missing or not callable, logs an error and SKIPS that command (never raises)."""

  def queued_spec_of(method: Any) -> Optional[QueuedCommandSpec]:
      """Return the spec attached to ``method`` (bound or plain), else ``None``. Used by the
      /function and /call guards."""

  # core/queued/models.py  (new) — QueuedCommandSpec, PreparedCommand, Requester, JobNotice,
  #   SubmitOutcome, JobView exactly as in §2 Data Models, plus:
  class QueuedCommand(BaseModel):
      model_config = ConfigDict(arbitrary_types_allowed=True)
      spec: QueuedCommandSpec
      method_name: str
      method: Callable[..., Any]
      prepare: Optional[Callable[..., Any]] = None

  class CommandUsageError(ValueError):
      """Raised by a prepare hook; ``str(exc)`` is shown to the user verbatim and no job is created."""

  Deliver = Callable[[JobNotice], Awaitable[None]]

  # core/queued/context.py  (new)
  current_command_job: ContextVar[Optional["CommandJobContext"]]   # set by the runner for the method's duration
  class CommandJobContext(BaseModel):  # job_id, command, requester, service (arbitrary types)
      ...
  async def report_command_progress(message: str) -> None:
      """Record ``metadata.progress`` for the current job; no-op outside a queued job. Never raises."""
  def current_job_id() -> Optional[str]:
      """The running job's id, or ``None`` outside a queued job."""

  # core/queued/service.py  (new)
  class QueuedCommandService:
      def __init__(
          self,
          *,
          owner: str,                              # e.g. "telegram:<bot name>"
          job_manager: Optional[JobManager] = None,  # injected in tests; else owned
          use_redis: bool = True,
          key_prefix: str = "parrot:chat_jobs",
          job_ttl: int = 86400,
          expiry_grace: float = 300.0,
          prepare_timeout: float = 10.0,
          notify_timeout: float = 30.0,
      ) -> None: ...
      async def start(self) -> None:
          """Idempotent; builds (when not injected) and starts JobManager(id=f"chat:{owner}",
          store=RedisJobStore(key_prefix=..., job_ttl=...) if use_redis else None)."""
      async def stop(self) -> None:
          """Idempotent. Marks every live job's cancel reason as 'interrupted — the bot is shutting down',
          then awaits JobManager.stop() (cancels + gathers); each runner delivers its notice."""
      async def submit(self, command: QueuedCommand, raw_args: str, requester: Requester,
                       deliver: Deliver) -> SubmitOutcome:
          """Lazy start → parse raw_args per parse_mode (keyword via parrot.integrations.utils.parse_kwargs)
          → prepare (bounded by prepare_timeout; CommandUsageError/timeout → 'rejected') → dedup
          (active key → 'duplicate' with the existing job id) → create_job + update_metadata + execute_job
          → 'accepted'. Never raises for user errors."""
      async def get(self, job_id: str, requester: Requester) -> Optional[JobView]:
          """get_job_async; ``None`` when unknown OR owned by another actor. Applies read-time expiry."""
      async def list_for(self, requester: Requester, limit: int = 10) -> List[JobView]:
          """list_jobs_async(user_id=requester.actor, limit=limit), newest first, expiry applied."""
      async def cancel(self, job_id: str, requester: Requester) -> Literal[
          "cancelling", "not_found", "finished", "not_on_this_worker"]:
          """Owner-only; sets reason 'cancelled by the requester' then JobManager.cancel_job."""

  # Runner semantics (inside execute_job): set current_command_job → update_metadata(phase="queued")
  # → async with semaphore(group or command) → update_metadata(phase="running")
  # → asyncio.wait_for(method(*args, **kwargs), max_runtime) → deliver(completed notice) → return
  # {"text": ...}. TimeoutError → deliver(timed_out) and raise TimeoutError("timed out after Ns").
  # Exception → deliver(failed, error=str(exc)[:300]) and re-raise. CancelledError → deliver(cancelled,
  # error=<cancel reason>) and re-raise. Every deliver is wrapped in wait_for(notify_timeout) +
  # try/except (logged, never raised). The dedup key is released in a finally.

  # core/queued/messages.py  (new) — the only place user-facing texts are written
  def format_ack(outcome: SubmitOutcome) -> str: ...
  def format_notice_header(notice: JobNotice) -> str: ...   # "✅ Job `id` finished in 3m12s — <label>"
  def format_job_view(view: JobView) -> str: ...
  def format_job_list(views: Sequence[JobView]) -> str: ...
  def format_cancel(result: str, job_id: str) -> str: ...
  JOB_COMMANDS: tuple[tuple[str, str], ...]  # (("jobs", ...), ("job_status", ...), ("job_cancel", ...))
  ```

### Module 3: Telegram adapter
- **Path**:
  - `packages/ai-parrot-integrations/src/parrot/integrations/telegram/queued_commands.py` (new)
  - modifies `telegram/wrapper.py`, `telegram/decorators.py`, `telegram/manager.py`, `integrations/manager.py`
- **Responsibility**:
  - Expose queued commands plus `jobs` / `job_status` / `job_cancel` on Telegram.
  - Deliver results to the same chat and forum topic, as a reply to the command message.
  - Make the managers call `TelegramAgentWrapper.close()` on shutdown.
  - Refuse queued methods in `/function` and `/call`.
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # telegram/queued_commands.py  (new)
  class TelegramQueuedCommands:
      """Owns a QueuedCommandService for one TelegramAgentWrapper (TelegramKnowledgeUpload pattern)."""
      def __init__(self, wrapper: "TelegramAgentWrapper", commands: List[QueuedCommand]) -> None: ...
      def register(self, router: Router) -> List[Tuple[str, str]]:
          """Register Command(<canonical>) and Command(<alias>) per command, plus jobs/job_status/job_cancel.
          Returns (canonical name, description) menu entries only — aliases are routing-only.
          Handler: wrapper._is_authorized(chat_id) gate (verified: wrapper.py:1206) → Requester(platform=
          "telegram", user_id=from_user.id, chat_id=chat.id, thread_id=message_thread_id if
          is_topic_message, message_id=message_id) → `with telegram_chat_scope(chat_id):` submit
          (verified: telegram/context.py:20) → message.answer(format_ack(outcome))."""
      async def shutdown(self) -> None:
          """await service.stop()."""

  # telegram/wrapper.py  (modifies wrapper.py:337 — after self._register_agent_commands())
  #   commands = discover_queued_commands(self.agent)
  #   self._queued_commands = TelegramQueuedCommands(self, commands) if commands else None
  #   if self._queued_commands: self._add_platform_commands(self._queued_commands.register(self.router))  # verified: wrapper.py:426
  class TelegramAgentWrapper(OperatorCommandsMixin):          # verified: wrapper.py:105
      async def send_parsed_to_chat(
          self,
          chat_id: int,
          parsed: ParsedResponse,                              # verified: parser.py:86
          *,
          message_thread_id: Optional[int] = None,
          reply_to_message_id: Optional[int] = None,
          prefix: str = "",
      ) -> None:
          """Send a ParsedResponse to a chat without an aiogram Message: text in 4096-char chunks via
          bot.send_message(chat_id, …, message_thread_id=…, reply_parameters=ReplyParameters(
          message_id=reply_to_message_id, allow_sending_without_reply=True)) with the same Markdown →
          plain fallback as _send_long_message (verified: wrapper.py:4164), then attachments via
          _send_attachments(chat_id, parsed) (verified: wrapper.py:3304)."""
      async def close(self) -> None:                           # verified: wrapper.py:3615
          """…existing body… + `if self._queued_commands: await self._queued_commands.shutdown()`."""
  # handle_function (wrapper.py:2379) and _execute_agent_method (wrapper.py:2747): after
  #   `method = getattr(self.agent, method_name)` (2 occurrences: L2410, L2756) refuse when
  #   queued_spec_of(method) is not None with "Use /<command> — it runs in the background."

  # telegram/decorators.py  (modifies decorators.py:54 — skip methods carrying _queued_command)
  # telegram/manager.py:372 and integrations/manager.py:1170 — before bot.session.close():
  #   `await wrapper.close()` in its own try/except (logged), so interruption notices can still be sent.
  ```

### Module 4: MS Teams adapter
- **Path**:
  - `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/queued_commands.py` (new)
  - modifies `msteams/wrapper.py`, `msteams/commands/agent_commands.py`, `integrations/manager.py`
- **Responsibility**:
  - Expose queued commands plus the job commands on Teams.
  - Deliver results proactively to the same conversation.
  - Close the service on shutdown.
  - Refuse queued methods in `/function` and `/call`.
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # msteams/commands/queued_commands.py  (new)
  class TeamsQueuedCommands:
      def __init__(self, wrapper: Any, commands: List[QueuedCommand]) -> None: ...
      def register(self, router: "MSTeamsCommandRouter") -> None:
          """router.register(name, handler) for canonical + aliases + job commands
          (verified: msteams/commands/__init__.py:81). Handler `async (turn_context) -> None`:
          raw_args = command_args(turn_context) (verified: __init__.py:32); Requester(platform="msteams",
          user_id=activity.from_property.id, chat_id=activity.conversation.id); when
          wrapper.config.client_id is empty reply "Background commands need the bot's client_id" and do
          NOT submit; conv_ref = TurnContext.get_conversation_reference(activity) captured now; deliver =
          adapter.continue_conversation(conv_ref, callback, client_id) whose callback calls
          wrapper._send_parsed_response(parsed, context) (verified: wrapper.py:1720); ack via
          wrapper.send_text(text, turn_context) (verified: msteams/handler.py:35)."""
      async def shutdown(self) -> None: ...

  def register_queued_commands(router: "MSTeamsCommandRouter", wrapper: Any) -> Optional[TeamsQueuedCommands]:
      """Discover and register; ``None`` when the agent has no queued command."""

  # msteams/wrapper.py:218 — after the knowledge-upload registration:
  #   self._queued_commands = register_queued_commands(self._command_router, self)
  class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):  # verified: wrapper.py:118
      async def close_queued_commands(self) -> None:
          """Stop the queued service (no-op when absent). Placed next to close_voice_transcriber (wrapper.py:1419)."""
  # msteams/commands/agent_commands.py:178 and :218 — next to the `_BLOCKED_METHODS` check (2 occurrences,
  #   handle_function + handle_call) refuse methods whose queued_spec_of(...) is not None.
  # integrations/manager.py:1196 — inside the msteams_bots loop: await wrapper.close_queued_commands() (isolated).
  ```

### Module 5: Slack adapter
- **Path**:
  - `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/queued_commands.py` (new)
  - modifies `slack/wrapper.py`
- **Responsibility**:
  - Expose queued commands plus the job commands as Slack slash commands, through both the webhook and socket-mode paths (both route through `SlackCommandRouter.dispatch`).
  - Ack within Slack's 3 s window.
  - Post the result to the channel.
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # slack/commands/queued_commands.py  (new)
  class SlackQueuedCommands:
      def __init__(self, wrapper: Any, commands: List[QueuedCommand]) -> None:
          """Builds the service with prepare_timeout=2.0 (Slack's 3 s ack window)."""
      def register(self, router: "SlackCommandRouter") -> List[str]:
          """router.register(name, handler) for canonical + aliases + job commands (verified:
          slack/commands/__init__.py:50). Handler `async (payload: dict) -> dict`: Requester(platform=
          "slack", user_id=payload["user_id"], chat_id=payload["channel_id"]); raw_args=payload["text"];
          returns {"response_type": "ephemeral", "text": format_ack(outcome)}. deliver posts
          wrapper.post_message(channel, text=f"<@{user}> " + header + parsed.text,
          blocks=wrapper._build_blocks(parsed)) (verified: wrapper.py:674, :562). Returns the names
          registered (for _help_text and the manifest docs)."""
      async def start(self) -> None: ...     # warms the service (Redis connect) before the first command
      async def shutdown(self) -> None: ...

  def register_queued_commands(router: "SlackCommandRouter", wrapper: Any) -> Optional[SlackQueuedCommands]: ...

  # slack/wrapper.py:123 — after `self._command_router = SlackCommandRouter()` (adapter registered once the
  #   router exists); start() (wrapper.py:171) awaits adapter.start(); stop() (wrapper.py:183) awaits
  #   adapter.shutdown() before cancelling _background_tasks; _help_text (wrapper.py:608) appends the
  #   registered queued + job commands.
  ```

### Module 6: GitToolkit PR-context reads
- **Path**: modifies `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
- **Responsibility**:
  - Four read-only, paginated methods (`per_page=100`, `page` param until a short page or `max_items`).
  - Each follows the `list_pull_requests` shape: `_resolve_connection` + `_request` + `asyncio.to_thread` + `@tool_schema`.
  - No new import.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # gittoolkit.py — input model next to ConvertPRToDraftInput (gittoolkit.py:402)
  class ListPRItemsInput(BaseModel):
      pr_number: int = Field(..., description="Pull request number")
      repository: Optional[str] = Field(None, description="owner/repo; defaults to the configured repository")
      max_items: int = Field(300, ge=1, le=1000, description="Stop after this many items")

  class GitToolkit(AbstractToolkit):                       # verified: gittoolkit.py:971
      @tool_schema(ListPRItemsInput)
      async def list_pull_request_files(self, pr_number: int, repository: Optional[str] = None,
                                        max_items: int = 300) -> List[Dict[str, Any]]:
          """List files changed by a PR: filename, status, additions, deletions, changes, patch
          (``patch`` absent for binary/huge files). GET /repos/{repo}/pulls/{n}/files."""
      @tool_schema(ListPRItemsInput)
      async def list_pull_request_comments(self, pr_number: int, repository: Optional[str] = None,
                                           max_items: int = 300) -> List[Dict[str, Any]]:
          """Issue-style PR comments: id, author, author_type ('User'|'Bot'), body, created_at, html_url.
          GET /repos/{repo}/issues/{n}/comments."""
      @tool_schema(ListPRItemsInput)
      async def list_pull_request_reviews(self, pr_number: int, repository: Optional[str] = None,
                                          max_items: int = 300) -> List[Dict[str, Any]]:
          """PR reviews: id, author, author_type, state, body, submitted_at, commit_id.
          GET /repos/{repo}/pulls/{n}/reviews."""
      @tool_schema(ListPRItemsInput)
      async def list_pull_request_review_comments(self, pr_number: int, repository: Optional[str] = None,
                                                  max_items: int = 300) -> List[Dict[str, Any]]:
          """Inline review comments: id, author, author_type, path, line, body, commit_id, created_at,
          html_url, in_reply_to_id. GET /repos/{repo}/pulls/{n}/comments."""
  # helpers verified: _resolve_connection gittoolkit.py:1117, _request gittoolkit.py:1286 (staticmethod),
  #   list_pull_requests gittoolkit.py:1834 (the shape to copy).
  ```

### Module 7: GitHubReviewer — `/pr_review` full review + queued `/review_pr`
- **Path**: modifies `packages/ai-parrot/src/parrot/bots/github_reviewer.py`, `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**:
  - The full review (context gathering, LLM structured review, verdict floor, report, PR comment, optional draft, chat reply).
  - `/review_pr` decorator swap with a prepare hook.
  - Two conf keys.
- **Depends on**: M2 (`queued_command`, `PreparedCommand`, `CommandUsageError`, `report_command_progress`, `current_job_id`), M6 (the four list methods).
- **Interface Skeleton**:
  ```python
  # conf.py — after GITHUB_REVIEW_WIKI_WAIT (conf.py:877)
  GITHUB_REVIEW_FULL_MAX_TOOL_CALLS: int = config.getint("GITHUB_REVIEW_FULL_MAX_TOOL_CALLS", fallback=15)
  GITHUB_REVIEW_COMMAND_MAX_RUNTIME: int = config.getint("GITHUB_REVIEW_COMMAND_MAX_RUNTIME", fallback=1800)

  # github_reviewer.py — import next to the telegram_command import (github_reviewer.py:77)
  from parrot.integrations.core.queued import (
      CommandUsageError, PreparedCommand, current_job_id, queued_command, report_command_progress,
  )
  # models CriterionAssessment, DescriptionAlignment, CodeObservation, BotFindingAssessment, FullPRReview,
  #   FullReviewLLMError — module level, before ChartReply (github_reviewer.py:401); see §2 Data Models.
  _KNOWN_REVIEW_BOTS: Dict[str, str]  # login -> display name: gemini-code-assist, copilot-pull-request-review,
  #   github-copilot, coderabbitai, sonarcloud, codacy-production, deepsource (plus any author_type == "Bot")

  class GitHubReviewer(Agent):                                       # verified: github_reviewer.py:499
      max_full_review_tool_calls: int  # set in __init__ next to max_review_tool_calls (github_reviewer.py:820-826)

      @queued_command(
          "review_pr",
          description="Review a PR against its Jira ticket and draft it if it does not comply",
          parse_mode="raw",
          prepare="_prepare_review_pr",
          max_runtime=conf.GITHUB_REVIEW_COMMAND_MAX_RUNTIME,
          max_concurrent=2,
          concurrency_group="github_review",
      )
      async def review_pr(self, target: str = "", **kwargs: Any) -> str:   # verified: github_reviewer.py:3383
          """Body unchanged (it still re-parses defensively and returns _format_command_reply)."""

      async def _prepare_review_pr(self, raw: str) -> PreparedCommand:
          """_parse_pr_target(raw) (verified: github_reviewer.py:2609); error → CommandUsageError(<the existing
          usage text>); else PreparedCommand(args=(raw.strip(),), label=f"strict review of {repo}#{n}",
          dedup_key=f"review_pr:{repo}#{n}"). No network."""

      @queued_command(
          "pr_review",
          description="Full PR review against its Jira ticket; posts the report on the PR (background)",
          parse_mode="raw",
          aliases=("pr-review",),
          prepare="_prepare_pr_review",
          max_runtime=conf.GITHUB_REVIEW_COMMAND_MAX_RUNTIME,
          max_concurrent=2,
          concurrency_group="github_review",
      )
      async def pr_review(self, target: str = "", jira_key: Optional[str] = None, auto_draft: bool = False,
                          dry_run: bool = False, **kwargs: Any) -> str:
          """Fetch the PR (_fetch_pr_payload, verified: github_reviewer.py:2642), run
          full_review_pull_request, return _format_pr_review_reply(...). Failures come back as a one-line
          notice string except FullReviewLLMError, which propagates so the job ends FAILED."""

      async def _prepare_pr_review(self, raw: str) -> PreparedCommand:
          """Grammar: <PR> [JIRA-KEY] [--auto-draft] [--dry-run]. Leading '—'/'–' normalized to '--'; the key
          must match ^[A-Za-z][A-Za-z0-9]+-\\d+$ (uppercased); any other token → CommandUsageError(usage).
          label=f"full review of {repo}#{n}", dedup_key=f"pr_review:{repo}#{n}". No network."""

      async def full_review_pull_request(self, payload: Dict[str, Any], *, jira_key: Optional[str] = None,
                                         auto_draft: bool = False, dry_run: bool = False) -> Dict[str, Any]:
          """Statuses: 'reviewed' | 'ticket_not_found' | 'error'. Outcome keys: status, verdict, report,
          comment ({id, html_url} | {error} | None), draft (converted | already_draft | not_open | skipped_dry_run
          | not_applicable | failed), jira_key, requirement_source, criteria_met, criteria_total, reason.
          Calls report_command_progress at each stage. Never writes to GitHub when dry_run or on
          FullReviewLLMError."""

      async def _gather_full_review_context(self, repo: str, pr_number: int, payload: Dict[str, Any],
                                            jira_key: Optional[str]) -> "FullReviewContext":
          """Diff via _fetch_diff (github_reviewer.py:2268); files/comments/reviews/review comments via the M6
          methods (each failure → empty list + a coverage note, never fatal); ticket via _fetch_ticket
          (github_reviewer.py:2223) for an explicit key, else _resolve_requirement (github_reviewer.py:1578);
          checks via _fetch_checks (github_reviewer.py:2720); wiki via _start_wiki_refresh /
          _await_wiki_refresh / _build_wiki_context under _wiki_review_lease (github_reviewer.py:1191)."""

      async def _ask_llm_for_full_review(self, context: "FullReviewContext") -> FullPRReview:
          """Same call shape as _ask_llm_for_review (github_reviewer.py:2372): self.ask(question,
          structured_output=FullPRReview, max_iterations=self.max_full_review_tool_calls + 1). Raises
          FullReviewLLMError on any exception or a missing structured result (no approve=False fallback)."""

      def _apply_verdict_floor(self, review: FullPRReview, *, ac_evaluated: bool) -> FullPRReview:
          """approved → needs_attention when no AC was evaluated or any criterion is not_met."""

      def _render_full_review_report(self, context: "FullReviewContext", review: FullPRReview) -> str:
          """Claude /pr-review headings: '# PR Review: {repo}#{n} ↔ {KEY}', Overall Verdict line,
          '## Acceptance Criteria Compliance' (table # | Criterion | Status | Evidence + **Score**),
          '## Description Alignment' (### ✅ Addressed / ### ❌ Gaps / ### ⚠️ Out of Scope),
          '## Code Observations', '## AI Bot Review Findings' (### {Bot} ({N} comments) tables),
          '## Verdict & Recommendation' ending '**Action**: …'; a coverage note when the diff was truncated;
          footer naming the job id (current_job_id()). Truncated to 65,000 chars with a note."""

      def _format_pr_review_reply(self, repo: str, pr_number: int, payload: Dict[str, Any],
                                  outcome: Dict[str, Any]) -> str:
          """Chat summary: verdict emoji + head, verdict vs ticket, AC met/total, top ≤5 findings, report link,
          draft result; the full report text when dry_run or when posting the comment failed."""
  ```

### Module 8: Documentation
- **Path**:
  - `wiki/integrations/queued-commands.md` (new)
  - `wiki/integrations/github-reviewer.md` (update)
  - `wiki/flows/jobmanager.md` (update)
- **Responsibility**:
  - How to declare a queued command, plus the job commands.
  - Per-platform setup, including the Slack app-manifest entries for each slash command (`/pr_review`, `/review_pr`, `/jobs`, `/job_status`, `/job_cancel`, optional `/pr-review`) and Teams' `client_id` requirement.
  - The `/pr_review` grammar, flags and report.
  - That `/review_pr` is now asynchronous.
  - The new `parrot.jobs` import path, `cancel_job`, and the per-user index.
- **Depends on**: M1–M7.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_core_and_server_paths_are_the_same_objects` | M1 | `parrot.jobs.JobManager is parrot.handlers.jobs.JobManager` (and `.job.JobManager`, `.models.Job`, `.redis_store.RedisJobStore`) |
| `test_cancel_job_keeps_record_with_reason` | M1 | running job → `cancel_job(id, "x")` → status `CANCELLED`, `error == "x"`, still returned by `get_job` |
| `test_cancel_job_unknown_or_finished_returns_false` | M1 | unknown id / completed job → `False` |
| `test_list_jobs_filters_by_user_id` | M1 | memory listing with two users returns only the requested user's jobs |
| `test_redis_user_index_lists_and_prunes` | M1 | real localhost Redis db 15 + unique prefix, skipped when unreachable (no fakeredis); per-user zset written on save, read by `list_jobs(user_id=)`, stale ids pruned |
| `test_queued_command_rejects_bad_name` | M2 | `"pr-review"` / uppercase / >32 chars as canonical → `ValueError` at decoration |
| `test_discover_skips_missing_prepare` | M2 | `prepare="_nope"` → command skipped, error logged, others still discovered |
| `test_submit_accepts_and_delivers_result` | M2 | fake method returns "done" → `accepted` outcome with 12-hex id; deliver receives `completed` notice with the result; stored result is `{"text": "done"}` |
| `test_submit_usage_error_creates_no_job` | M2 | prepare raises `CommandUsageError` → `rejected`, message verbatim, `JobManager.jobs` empty |
| `test_submit_duplicate_returns_existing_job` | M2 | same dedup key while running → `duplicate` with the first job id; released after completion |
| `test_concurrency_group_caps_parallel_runs` | M2 | two commands in one group with cap 1 → second job reports `queued` until the first finishes |
| `test_max_runtime_times_out` | M2 | slow method → notice `timed_out`, job `FAILED` with `timed out after` |
| `test_failure_notice_and_status` | M2 | method raises → notice `failed`, job `FAILED`, error truncated |
| `test_stop_interrupts_and_notifies` | M2 | `stop()` during a run → notice `cancelled` with the shutdown reason, job `CANCELLED` |
| `test_get_and_cancel_are_owner_scoped` | M2 | another actor → `get` is `None`, `cancel` is `not_found` |
| `test_expired_view_for_orphan` | M2 | stored RUNNING job not tracked locally, past `max_runtime + expiry_grace` → view status `expired` |
| `test_report_command_progress_visible_in_view` | M2 | method calls `report_command_progress("x")` → `get()` shows `progress == "x"`; no-op outside a job |
| `test_deliver_failure_does_not_change_status` | M2 | deliver raises → job still `COMPLETED` |
| `test_telegram_registers_queued_and_job_commands` | M3 | menu entries include `pr_review`, `jobs`, `job_status`, `job_cancel`; alias `pr-review` routed but not in the menu |
| `test_telegram_ack_then_reply_in_topic` | M3 | handler answers the ack; deliver calls `send_message` with `message_thread_id` and `reply_parameters` of the command message |
| `test_telegram_discovery_skips_queued_methods` | M3 | `discover_telegram_commands` does not return a `@queued_command` method |
| `test_telegram_function_refuses_queued_method` | M3 | `/function pr_review` and `/call review_pr` answer "runs in the background" without calling the method |
| `test_managers_call_wrapper_close_before_session_close` | M3 | `IntegrationBotManager.shutdown` and `TelegramBotManager.shutdown` await `wrapper.close()` before `bot.session.close()`; a raising `close()` is logged, not propagated |
| `test_teams_submit_and_proactive_delivery` | M4 | handler acks via `send_text`; deliver calls `adapter.continue_conversation` with the captured reference and sends the parsed result |
| `test_teams_without_client_id_does_not_submit` | M4 | empty `client_id` → explanatory reply, no job |
| `test_teams_function_and_call_refuse_queued_method` | M4 | `/function` and `/call` on a queued method are refused |
| `test_teams_manager_shutdown_closes_queued` | M4 | `IntegrationBotManager.shutdown` awaits `close_queued_commands()` per Teams wrapper |
| `test_slack_handler_returns_ephemeral_ack` | M5 | router dispatch of `pr_review` returns `{"response_type": "ephemeral", "text": <ack>}` |
| `test_slack_delivery_posts_to_channel_with_mention` | M5 | deliver calls `post_message(channel, "<@U…> …", blocks=…)` |
| `test_slack_stop_shuts_down_queued` | M5 | `stop()` awaits the adapter shutdown |
| `test_list_pull_request_files_paginates` | M6 | stubbed `_request` returns 100 + 20 items → 120 returned, two GETs with `page` 1 and 2; `max_items` honored |
| `test_list_pull_request_comments_shapes_author_type` | M6 | `user.type == "Bot"` → `author_type == "Bot"` |
| `test_list_pull_request_reviews_and_review_comments` | M6 | field mapping per §3 M6 |
| `test_review_pr_is_a_queued_command` | M7 | `review_pr._queued_command.command == "review_pr"`, `parse_mode == "raw"`, group `github_review` (replaces the `_telegram_command` assertion in `TestReviewPRCommand`) |
| `test_prepare_review_pr_usage_error` | M7 | unparsable target → `CommandUsageError` with the existing usage text |
| `test_prepare_pr_review_grammar` | M7 | URL + key + flags parsed; `—auto-draft` normalized; unknown token → usage error; dedup key and label |
| `test_full_review_posts_report_comment` | M7 | default run → `add_pr_comment` once with the rendered report; no `submit_pr_review` |
| `test_full_review_dry_run_writes_nothing` | M7 | `dry_run=True` → no `add_pr_comment`, no `convert_pr_to_draft`; reply carries the report |
| `test_full_review_auto_draft_only_on_does_not_meet` | M7 | `does_not_meet` + `auto_draft` → `convert_pr_to_draft`; `needs_attention` → not called |
| `test_full_review_llm_failure_writes_nothing` | M7 | `_ask_llm_for_full_review` raises `FullReviewLLMError` → it propagates; no GitHub write |
| `test_verdict_floor_without_ac_and_with_not_met` | M7 | `approved` downgraded to `needs_attention` in both cases; auto-draft never fires without AC |
| `test_explicit_ticket_not_found_posts_nothing` | M7 | explicit key unreadable → status `ticket_not_found`, no comment |
| `test_report_has_claude_headings_and_bot_tables` | M7 | rendered report contains every heading in §3 M7 and one table per bot that commented |
| `test_comment_failure_returns_full_report_in_chat` | M7 | `add_pr_comment` raises → status `reviewed`, `comment.error` set, reply includes the report |

### Integration Tests
| Test | Description |
|---|---|
| `test_queued_command_end_to_end_memory_store` | M2 + M3: a stub agent with one `@queued_command` behind a `TelegramAgentWrapper` with a mocked `Bot`: `/cmd` → ack → result reply → `/jobs` lists it → `/job_status` shows `completed` |
| `test_pr_review_end_to_end_stubbed_github` | M2 + M7: `GitHubReviewer` minimal stub (the `_MinimalReviewer` pattern, `test_github_reviewer.py:58`) with AsyncMock toolkits and a stubbed `_ask_llm_for_full_review` → service run → comment posted → chat notice rendered |

### Validation Contract

tests:
- packages/ai-parrot/tests/test_parrot_jobs_core.py
- packages/ai-parrot-server/tests/handlers/test_job_progress.py
- packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_agent_command_chat_scope.py
- packages/ai-parrot-integrations/tests/test_telegram_integration.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_queued_commands_msteams.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_agent_commands.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_manager_shutdown.py
- packages/ai-parrot-integrations/tests/integrations/slack/test_queued_commands_slack.py
- packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_hooks.py
- packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py
- packages/ai-parrot/tests/bots/test_github_reviewer.py
- packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def memory_service():
    """QueuedCommandService with an injected in-memory JobManager (no Redis)."""
    return QueuedCommandService(owner="test:bot", job_manager=JobManager(id="test"), use_redis=False)

@pytest.fixture
def telegram_requester():
    return Requester(platform="telegram", user_id="42", chat_id="-100123", thread_id="7", message_id="991")

class _Recorder:
    """deliver() double that stores every JobNotice and sets an asyncio.Event."""
```

- Redis-backed tests use the real localhost Redis at db 15 with a unique key prefix, and are skipped when it is unreachable. `fakeredis` is not installed in the workspace.
- `packages/ai-parrot-tools` has no `asyncio_mode = "auto"`. Its GitToolkit tests drive coroutines with `asyncio.run(...)`, as `test_gittoolkit_pr_methods.py` does.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `from parrot.jobs import JobManager, JobStatus, Job, RedisJobStore` works with only `ai-parrot` installed, and the `parrot.handlers.jobs` names are the very same objects.
- [ ] `JobManager.cancel_job` keeps the record (`CANCELLED`, `error == reason`), and `list_jobs` / `list_jobs_async` / `RedisJobStore.list_jobs` accept `user_id`.
- [ ] `ai-parrot-integrations` gains no dependency on `ai-parrot-server` (`packages/ai-parrot-integrations/pyproject.toml` dependencies unchanged).
- [ ] An agent method decorated with `@queued_command` is exposed on Telegram, MS Teams and Slack. It is acknowledged within the request turn by an acceptance message (`messages.format_ack`) carrying the 12-hex job id and the job label.
- [ ] The method's result is delivered to the originating chat. On Telegram that means the same forum topic, as a reply to the command message. On Teams it is the same conversation. On Slack it is the same channel, mentioning the requester.
- [ ] `/jobs`, `/job_status <id>` and `/job_cancel <id>` exist wherever a queued command is exposed, and only show or cancel the requester's own jobs. Another user's id reads exactly like an unknown id.
- [ ] Usage errors are answered immediately and create no job. A duplicate dedup key returns the active job id.
- [ ] A job longer than `max_runtime` ends `FAILED` with `timed out after`, and its requester is told.
- [ ] Shutdown (`IntegrationBotManager.shutdown`, `TelegramBotManager.shutdown`, `SlackAgentWrapper.stop`) cancels running jobs, and each requester gets an interruption notice. `TelegramAgentWrapper.close()` is now awaited before the bot session closes.
- [ ] `/function` and `/call` (Telegram, Teams) refuse queued methods.
- [ ] `/pr_review <PR> [JIRA-KEY] [--auto-draft] [--dry-run]` runs as a background job. It posts a report with the Claude `/pr-review` headings as a PR comment, unless `--dry-run`. It converts to draft only on `does_not_meet` with `--auto-draft`, and never submits an APPROVE or REQUEST_CHANGES review.
- [ ] An LLM failure in `/pr_review` ends the job `FAILED` and writes nothing to GitHub.
- [ ] `/review_pr` is a queued command with unchanged arguments and an unchanged verdict text (`_format_command_reply`).
- [ ] The four new `GitToolkit` list methods paginate and return the documented fields.
- [ ] All Validation Contract tests pass. `ruff check` is clean on every touched file (no new TID251 import).
- [ ] The pages declared in §10 exist under `wiki/` (`parrot sdd techwiki check`).
- [ ] No breaking change to existing public API: every `parrot.handlers.jobs` import still resolves, and every existing `@telegram_command` still works.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against `origin/dev @ 647e1df22f`.
> Implementation agents MUST NOT reference imports, attributes or methods not listed
> here without first verifying them.

### Verified Imports
```python
from parrot.handlers.jobs import JobManager, JobStatus, RedisJobStore   # verified: ai-parrot-server/.../handlers/jobs/__init__.py:1-3 (moves to parrot.jobs in M1)
from parrot.handlers.jobs.job import JobManager                          # verified: used at ai-parrot-server/.../scraping/handler.py:16 (must keep working)
from parrot.handlers.jobs.models import Job, JobStatus                   # verified: used at ai-parrot/tests/handlers/test_planogram_compliance.py:18
from parrot.integrations.telegram import telegram_command                # verified: github_reviewer.py:77; lazy export telegram/__init__.py (_LAZY_EXPORTS)
from parrot.integrations.telegram.context import telegram_chat_scope, get_current_telegram_chat_id  # verified: telegram/context.py:14-35
from parrot.integrations.parser import ParsedResponse, parse_response    # verified: integrations/parser.py:86, :416
from parrot.integrations.utils import parse_kwargs                       # verified: integrations/utils.py:5
from parrot.integrations.msteams.commands import MSTeamsCommandRouter, command_args  # verified: msteams/commands/__init__.py:55, :32
from parrot.integrations.slack.commands import SlackCommandRouter        # verified: slack/commands/__init__.py:27
from .decorators import tool_schema                                      # verified: gittoolkit.py:42 (parrot_tools/decorators.py re-exports parrot.tools.decorators.tool_schema)
from aiogram.types import ReplyParameters                                # verified: aiogram 3.31.0; Bot.send_message has message_thread_id + reply_parameters
from botbuilder.core import TurnContext                                  # verified: msteams/commands/knowledge_upload.py:11
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/jobs/models.py
class JobStatus(str, Enum):  # L6 — PENDING, RUNNING, COMPLETED, FAILED, CANCELLED (L8-12)
@dataclass
class Job:                   # L16 — job_id, obj_id, query, status, result, error, created_at, started_at,
                             #        completed_at, user_id, session_id, execution_mode, metadata: Dict[str, Any]

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py  (imports only typing/asyncio/uuid/contextlib/datetime,
#   navconfig.logging and .models — no aiohttp, no server module: L10-19)
class JobManager:                                                                   # L22
    def __init__(self, id: str = "default", cleanup_interval: int = 3600, job_ttl: int = 86400,
                 store: Optional["RedisJobStore"] = None): ...                      # L42; self.jobs, self.tasks dicts
    async def start(self) -> None: ...                                              # L63
    async def stop(self) -> None: ...                                               # L80 (cancels + gathers tasks, closes store)
    async def update_metadata(self, job_id: str, **values: Any) -> Optional[Job]: ...  # L122
    async def report_progress(self, job_id: str, progress: Any) -> Optional[Job]: ...  # L151
    def create_job(self, job_id: str, obj_id: str, query: Any, user_id: Optional[str] = None,
                   session_id: Optional[str] = None, execution_mode: Optional[str] = None) -> Job: ...  # L171 (needs a running loop)
    async def execute_job(self, job_id: str, execution_func: Callable[[], Awaitable[Any]]) -> None: ...  # L209
    async def _run_job(self, job_id: str, execution_func) -> None: ...              # L228 — CancelledError → CANCELLED, error="Job was cancelled", re-raise
    def get_job(self, job_id: str) -> Optional[Job]: ...                            # L274
    async def get_job_async(self, job_id: str) -> Optional[Job]: ...                # L288
    def list_jobs(self, obj_id=None, status=None, limit: int = 100) -> list: ...    # L321
    async def list_jobs_async(self, obj_id=None, status=None, limit: int = 100) -> list: ...  # L347
    def delete_job(self, job_id: str) -> bool: ...                                  # L374 (erases the record)

# packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py
class RedisJobStore:                                                                # L120 — __init__(redis_url=None, key_prefix="parrot:jobs", job_ttl=86400)
    async def save(self, job: Job) -> None: ...                                     # L209 (EXPIRE only on terminal states)
    async def get(self, job_id: str) -> Optional[Job]: ...                          # L234
    async def delete(self, job_id: str) -> bool: ...                                # L247
    async def list_jobs(self, obj_id=None, status=None, limit: int = 100) -> List[Job]: ...  # L261 (zrevrange limit*2, filters in Python)

# packages/ai-parrot-server/src/parrot/handlers/jobs/worker.py
def configure_job_manager(app, *, use_redis=False, redis_url=None, key_prefix="parrot:jobs", job_ttl=86400) -> JobManager: ...  # L15 — imports `from .job import JobManager` (L12)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py
def telegram_command(command: str, description: str = "", parse_mode: str = "keyword") -> Callable: ...  # L5 — sets fn._telegram_command
def discover_telegram_commands(agent: Any) -> List[Dict[str, Any]]: ...            # L35 — skips "_*", dedupes; meta read at L54

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper(OperatorCommandsMixin):                                  # L105
    def __init__(self, agent, bot: Bot, config: TelegramAgentConfig, agent_commands: list = None, *, app=None): ...  # L158; discovery L200-205; set_wrapper L266-267
    def _register_handlers(self) -> None: ...                                       # L282; Command("function") L307, Command("call") L313; self._register_agent_commands() L337; knowledge upload L340-345
    def _add_platform_commands(self, entries: list[tuple[str, str]]) -> None: ...   # L426
    def _register_agent_commands(self) -> None: ...                                 # L921-966 (inline await, Command(cmd_name))
    def _sanitize_command_name(cls, raw: Any) -> Optional[str]: ...                 # L975
    def get_bot_commands(self) -> list: ...                                         # L1025
    def _is_authorized(self, chat_id: int) -> bool: ...                             # L1206
    async def handle_call(self, message: Message) -> None: ...                      # L2010 → _execute_agent_method
    async def handle_function(self, message: Message) -> None: ...                  # L2379; `method = getattr(self.agent, method_name)` L2410
    async def _execute_agent_method(self, message: Message, method_name: str, args_text: str) -> None: ...  # L2747; getattr at L2756
    async def _send_attachments(self, chat_id: int, parsed: ParsedResponse) -> None: ...  # L3304
    async def close(self) -> None: ...                                              # L3615 (knowledge-upload shutdown at its end)
    def _parse_response(self, response: Any) -> ParsedResponse: ...                 # L3900
    async def _send_parsed_response(self, message, parsed, prefix="") -> None: ...  # L4019 (needs an aiogram Message)
    async def _send_long_message(self, message: Message, text: str, ...) -> None: ...  # L4164
    async def send_interactive_message(self, chat_id: int, text: str, keyboard: dict, parse_mode: str = "Markdown") -> int | None: ...  # L4531

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py
#   self.bots[name] = (bot, dp, wrapper) L226; shutdown() L336; `for name, (bot, _dp, _wrapper) in self.bots.items():` L372 → bot.session.close() L374
# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
#   self.telegram_bots[name] = (bot, dp, wrapper) L456; self.msteams_bots[name] = wrapper L521; self.slack_bots[name] = wrapper L1080
#   shutdown() L1150; telegram session loop L1170; msteams loop L1196; slack stop loop L1234-1243

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py
def command_args(turn_context: "TurnContext") -> str: ...                           # L32
class MSTeamsCommandRouter:                                                         # L55
    def register(self, command: str, handler: Callable) -> None: ...                # L81 — handler: async (turn_context) -> None; lstrip("/")
    async def try_dispatch(self, text: str, turn_context) -> bool: ...              # L99

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):                         # L118
    def __init__(self, agent, config: MSTeamsAgentConfig, app: web.Application, ...): ...  # L150; self.adapter L204; router + AgentCommandHandler L207-211; knowledge upload L214-218
    def _is_authorized(self, conversation_id: str, user_id: str) -> bool: ...       # L527
    async def on_message_activity(self, turn_context): ...                          # L788 (allowlist + auth gate before dispatch)
    async def close_voice_transcriber(self) -> None: ...                            # L1419
    async def _send_parsed_response(self, parsed, turn_context: TurnContext) -> None: ...  # L1720
# msteams/handler.py: async def send_text(self, text: str, turn_context: TurnContext)  # L35
# msteams/commands/knowledge_upload.py: conv_ref + continue_conversation(conv_ref, callback, client_id)  # L178-188
# msteams/commands/agent_commands.py: _BLOCKED_METHODS L38; handle_function L156 (guard L178); handle_call L200 (guard L218)

# packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py
class SlackCommandRouter:                                                           # L27
    def register(self, command: str, handler: Callable) -> None: ...                # L50 — handler: async (payload: dict) -> dict | None
    async def dispatch(self, command: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]: ...  # L68

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
class SlackAgentWrapper:                                                            # L76
    # self._background_tasks L117; self._command_router = SlackCommandRouter() L123; self._knowledge_upload L136/179
    async def start(self) -> None: ...                                              # L171
    async def stop(self) -> None: ...                                               # L183
    def _is_authorized(self, channel_id: str, user_id: str = None) -> bool: ...     # L203
    async def _handle_command(self, request: web.Request) -> web.Response: ...      # L369 (signature check, _is_authorized, router.dispatch with {team_id,user_id,channel_id,text,response_url})
    def _build_blocks(parsed: ParsedResponse) -> List[Dict[str, Any]]: ...          # L562 (staticmethod)
    def _help_text(self) -> str: ...                                                # L608
    async def post_message(self, channel: str, text: str, blocks=None, thread_ts=None) -> Optional[str]: ...  # L674
# slack/socket_handler.py: _handle_slash_command(payload) L271 → router dispatch; _send_response(response_url, body) L382

# packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/service.py  (pattern reference)
class KnowledgeUploadService:  # L43 — submit(request, notify) L137 (job_id = uuid4().hex[:12], create_task, semaphore), shutdown() L190

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class ConvertPRToDraftInput(BaseModel): ...                                         # L402
class GitToolkit(AbstractToolkit):                                                  # L971
    def _resolve_connection(self, repository: Optional[str]) -> _RepoConnection: ...  # L1117
    @staticmethod
    def _request(method: str, url: str, token: str, *, expected: int, **kwargs) -> requests.Response: ...  # L1286
    async def get_pull_request(self, pr_number: int, repository: Optional[str] = None) -> Dict[str, Any]: ...  # L1810
    async def list_pull_requests(self, repository=None, state="open", per_page: int = 100) -> List[Dict[str, Any]]: ...  # L1834
    async def get_pull_request_diff(self, pr_number: int, repository=None, max_bytes: int = 50_000) -> Dict[str, Any]: ...  # L1874
    async def add_pr_comment(self, pr_number: int, body: str, repository=None) -> Dict[str, Any]: ...  # L1898 → {id, html_url}
    async def submit_pr_review(self, pr_number: int, event: Literal["APPROVE","REQUEST_CHANGES","COMMENT"], ...) -> Dict[str, Any]: ...  # L1928
    async def get_pr_checks(...): ...                                               # L2192
    async def convert_pr_to_draft(...): ...                                         # L2275

# packages/ai-parrot/src/parrot/bots/github_reviewer.py
def _read_only_excludes(toolkit_cls: type, keep: Sequence[str]) -> tuple[str, ...]: ...  # L134
class PRReviewResult(BaseModel): ...                                                # L264
class ChartReply(BaseModel): output: str; charts: List[Dict]                        # L401
class GitHubReviewer(Agent):                                                        # L499
    WEBHOOK_TASKS_KEY = "github_review_hook_tasks"                                  # L593
    def __init__(self, ...): ...                                                    # L749; max_diff_bytes L814; max_review_tool_calls L820-826; self._wrapper = None L869
    def set_wrapper(self, wrapper) -> None: ...                                     # L974
    async def shutdown(self, **kwargs: Any) -> None: ...                            # L1045
    async def _wiki_review_lease(self) -> AsyncIterator[bool]: ...                  # L1191 (asynccontextmanager)
    def _attach_toolkit(self, toolkit: Any, name: str) -> None: ...                 # L1296 (registers the WHOLE GitToolkit as LLM tools)
    async def _resolve_requirement(self, repo: str, payload: Dict[str, Any]
        ) -> Tuple[Optional[str], Literal["jira", "sdd_spec"], Optional[Dict[str, Any]]]: ...  # L1578
    async def _fetch_ticket(self, ticket_key: str, *, fields: Optional[str] = None) -> Optional[Dict[str, Any]]: ...  # L2223
    async def _fetch_diff(self, repo: str, pr_number: int) -> Tuple[str, bool, bool]: ...  # L2268
    async def _ask_llm_for_review(self, *, payload, ticket_key, ticket, diff_text, diff_truncated,
                                  diff_available, use_wiki: bool = True) -> PRReviewResult: ...  # L2372
    def _get_telegram_bot(self): ...                                                # L2555
    @classmethod
    def _parse_pr_target(cls, text: str) -> Tuple[Optional[str], Optional[int], Optional[str]]: ...  # L2609 (regexes L2597-2606)
    async def _fetch_pr_payload(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]: ...  # L2642
    async def _fetch_checks(self, repo: str, pr_number: int, head_sha: str = "") -> PRChecksSummary: ...  # L2720
    async def strict_review_pull_request(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...  # L3114
    @telegram_command("review_pr", description=..., parse_mode="raw")             # L3378-3382
    async def review_pr(self, target: str = "", **kwargs: Any) -> str: ...          # L3383
    def _format_command_reply(self, repo, pr_number, payload, outcome) -> str: ...  # L3433

# packages/ai-parrot/src/parrot/conf.py
GITHUB_REVIEW_REQUIRE_CHECKS: bool  # L851
GITHUB_REVIEW_WIKI_WAIT: int = config.getint("GITHUB_REVIEW_WIKI_WAIT", fallback=120)  # L877
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `QueuedCommandService` | `JobManager.create_job` / `execute_job` / `update_metadata` / `get_job_async` | method calls | `handlers/jobs/job.py:171, :209, :122, :288` |
| `QueuedCommandService.cancel` | `JobManager.cancel_job` (new, M1) | method call | — (added by M1) |
| `TelegramQueuedCommands` | `TelegramAgentWrapper._add_platform_commands` | menu + `/commands` entries | `telegram/wrapper.py:426` |
| `TelegramQueuedCommands` deliver | `TelegramAgentWrapper.send_parsed_to_chat` (new) → `_send_attachments` | method calls | `telegram/wrapper.py:3304` |
| `TeamsQueuedCommands` | `MSTeamsCommandRouter.register` + `adapter.continue_conversation` | router + proactive | `msteams/commands/__init__.py:81`, `msteams/commands/knowledge_upload.py:188` |
| `SlackQueuedCommands` | `SlackCommandRouter.register` + `SlackAgentWrapper.post_message` | router + chat.postMessage | `slack/commands/__init__.py:50`, `slack/wrapper.py:674` |
| `GitHubReviewer.pr_review` | `GitToolkit.list_pull_request_*` (new, M6), `add_pr_comment`, `convert_pr_to_draft` | method calls | `gittoolkit.py:1898, :2275` |
| `GitHubReviewer._ask_llm_for_full_review` | `Agent.ask(structured_output=…)` | same call shape as the strict review | `github_reviewer.py:2372` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.jobs`~~. No such package in any distribution yet (`git ls-tree -r origin/dev | grep /parrot/jobs` is empty); M1 creates it.
- ~~`parrot.integrations.core.queued`~~ and ~~`queued_command`~~. M2 creates them. `parrot/integrations/core/` today holds only `state.py` and `auth/`.
- ~~`JobManager.cancel_job`~~, ~~`list_jobs(user_id=...)`~~, ~~a per-user Redis index~~, ~~a completion callback~~, ~~an enforced timeout~~ (`enqueue`'s `timeout` is documented "not enforced"), ~~a concurrency cap~~ in `JobManager`.
- ~~A generic cross-platform command decorator or registry~~. `telegram_command` is Telegram-only.
  - Teams exposes agent methods only via `/function`, `/call` and YAML commands.
  - Slack has no agent-method commands at all.
- ~~`message_thread_id` handling~~ anywhere in `telegram/wrapper.py`.
  - `_send_parsed_response` / `_send_long_message` require an aiogram `Message`.
  - `send_interactive_message` is the only public send-to-`chat_id` method.
- ~~A per-request ContextVar on Teams or Slack~~. Only Telegram has `current_telegram_chat_id`.
- ~~`MSTeamsAgentWrapper.close()` / `.stop()`~~. Teams wrappers have only `close_formdesigner_client` / `close_voice_transcriber`.
- ~~A call to `TelegramAgentWrapper.close()`~~ in `IntegrationBotManager.shutdown` or `TelegramBotManager.shutdown`. Both only close `bot.session`.
- ~~A per-PR lock or in-flight review registry~~ in `GitHubReviewer`. `strict_review_pull_request` does not consult `_reviewed_shas`.
- ~~`GitToolkit` methods~~ for PR files, issue comments, reviews, review comments or labels.
- ~~`.claude/skills/pr-review/`~~. The Claude command is `.claude/commands/pr-review.md`.
- ~~`ChartReply` in the integrations package~~. It lives in `github_reviewer.py:401` and is duck-typed by `parse_response`.
- ~~`fakeredis`~~. Not installed in the workspace.

### Edit Sites (Blueprint Anchors)

Verified against: `647e1df22f` (origin/dev). `/sdd-task` MUST re-run `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/jobs/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/jobs/models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/jobs/manager.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/jobs/redis_store.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/jobs/job.py` | MODIFY (→ shim) | `class JobManager:` | `job.py:22` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/jobs/models.py` | MODIFY (→ shim) | `class JobStatus(str, Enum):` | `models.py:6` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py` | MODIFY (→ shim) | `class RedisJobStore:` | `redis_store.py:120` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/models.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/decorators.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/service.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/context.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/queued/messages.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/queued_commands.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `self._register_agent_commands()` | `wrapper.py:337` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `async def close(self) -> None:` | `wrapper.py:3615` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY (new method before it) | `async def send_interactive_message(` | `wrapper.py:4531` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY (guard after each) | `method = getattr(self.agent, method_name)` — L2410 is inside `handle_function`, L2756 inside `_execute_agent_method`; guard both | `wrapper.py:2410, :2756` | 2 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py` | MODIFY | `meta = getattr(attr, "_telegram_command", None)` | `decorators.py:54` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py` | MODIFY | `for name, (bot, _dp, _wrapper) in self.bots.items():` | `manager.py:372` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | `for name, (bot, _dp, _) in self.telegram_bots.items():` | `manager.py:1170` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | `for name, wrapper in self.msteams_bots.items():` | `manager.py:1196` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/queued_commands.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `self._knowledge_upload = register_knowledge_upload_commands(self._command_router, self)` | `wrapper.py:218` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY (new method before it) | `async def close_voice_transcriber(self) -> None:` | `wrapper.py:1419` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py` | MODIFY (guard after each) | `if method_name.startswith("_") or method_name in self._BLOCKED_METHODS:` — L178 in `handle_function`, L218 in `handle_call`; guard both | `agent_commands.py:178, :218` | 2 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/queued_commands.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | `self._command_router = SlackCommandRouter()` | `wrapper.py:123` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | `async def stop(self) -> None:` | `wrapper.py:183` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | `def _help_text(self) -> str:` | `wrapper.py:608` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | `class ConvertPRToDraftInput(BaseModel):` | `gittoolkit.py:402` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY (new methods before it) | `async def get_pr_checks(` | `gittoolkit.py:2192` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `from parrot.integrations.telegram import telegram_command` | `github_reviewer.py:77` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY (models before it) | `class ChartReply(BaseModel):` | `github_reviewer.py:401` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY (decorator swap) | `"review_pr",` | `github_reviewer.py:3379` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY (new methods before it) | `def _format_command_reply(` | `github_reviewer.py:3433` | 1 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `GITHUB_REVIEW_WIKI_WAIT: int = config.getint("GITHUB_REVIEW_WIKI_WAIT", fallback=120)` | `conf.py:877` | 1 |
| `packages/ai-parrot/tests/test_parrot_jobs_core.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/integrations/core/test_queued_commands.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_queued_commands_msteams.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_queued_commands_slack.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py` | MODIFY | `import asyncio` | `test_gittoolkit_pr_methods.py:8` | 1 |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | `class TestReviewPRCommand` | `test_github_reviewer.py:5206` | 1 |
| `packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py` | CREATE | — | — | — |
| `wiki/integrations/queued-commands.md` | CREATE | — | — | — |
| `wiki/integrations/github-reviewer.md` | MODIFY | heading line containing `review_pr(target: str) -> str` (the `/review_pr` section) | `github-reviewer.md:386` | 1 |
| `wiki/flows/jobmanager.md` | MODIFY | (unverified — check before use; the page is aspirational, add a "Real implementation" section at the top) | — | — |

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-851-queued-commands-integrations`, created from `origin/dev`. The `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - **M2 → M1.** `service.py` imports `parrot.jobs.JobManager` / `RedisJobStore` / `JobStatus`, and calls `cancel_job` and `list_jobs_async(user_id=)`.
  - **M3 → M2, M4 → M2, M5 → M2.** Each adapter imports `discover_queued_commands`, `queued_spec_of`, `QueuedCommandService`, `Requester`, `JobNotice` and `messages.*`.
  - **M7 → M2.** `github_reviewer.py` imports `queued_command`, `PreparedCommand`, `CommandUsageError`, `report_command_progress` and `current_job_id`.
  - **M7 → M6.** `_gather_full_review_context` calls the four `GitToolkit.list_pull_request_*` methods.
  - **M8 → M1…M7.** The docs describe the delivered behavior.
  - **No edges between M1 and M6, or among M3, M4 and M5.** M1 ∥ M6 can run first. M3 ∥ M4 ∥ M5 can run once M2 lands. M7 needs M2 and M6.
- **Shared files**: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` is modified by M3 (Telegram `close()` in `shutdown`) and M4 (`close_queued_commands()` in `shutdown`). Those two tasks are serialized.
- **Exclusive resources**: none.
  - No pyproject or `uv.lock` change: `redis.asyncio` stays a lazy import.
  - No migration, no native rebuild.
  - The M1 move adds a subpackage under an already editable-installed `src/` tree, so no reinstall is needed. Never `uv sync` inside the worktree.
- **Cross-feature dependencies**: none to merge first.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Knowledge-upload adapters (FEAT-647)** are the template for every platform adapter. Each adapter owns the service; `register(router)` returns menu entries; `shutdown()` stops the service; deliver closures capture the platform reply target. See `telegram/knowledge_upload.py:150-200`, `msteams/commands/knowledge_upload.py:170-200`, `slack/wrapper.py:136/179`.
- **`JobManager._run_job` state machine** (`job.py:228-273`) stays the single owner of job status. The queued runner only delivers notices and raises; it never writes `job.status` itself.
- **Scoped reads without an existence oracle**: copy the `AgentJobs` precedent (`ai-parrot-server/src/parrot/mcp/agent_jobs.py`). A foreign id reads like an unknown id.
- **Background-task hygiene**: copy `GitHubReviewer.setup_webhook_route` (`github_reviewer.py:665-705`): tracked tasks, a done-callback that logs crashes, nothing silently dropped.
- **Single source for user-facing texts**: `core/queued/messages.py`. Adapters never format ack, status or notice strings themselves.
- **`report_command_progress`** at each `/pr_review` stage: "fetching PR", "fetching diff and files", "reading PR comments", "fetching ticket", "waiting for repository wiki", "LLM review", "posting report".
- **General rules**: async-first, Pydantic v2 models, `self.logger`, Google-style docstrings, 120-column lines; `black` formats and `ruff check` gates.

### Known Risks / Gotchas
- **Telegram names.** The menu only accepts `[a-z0-9_]`, so canonical names are validated at decoration time (`pr_review`). Hyphenated aliases are routing-only on Telegram. aiogram's `Command("pr-review")` does match a typed `/pr-review …`, but clients highlight only `/pr`. The menu never shows it.
- **Multi-worker gunicorn.**
  - A job's task lives in the worker that accepted it.
  - Status reads work everywhere through Redis.
  - Cancel and dedup act only on the owning worker: `/job_cancel` elsewhere says so.
  - Orphans read as `expired` after `max_runtime + expiry_grace`.
- **Shutdown ordering.**
  - Interruption notices need an open bot session, so `TelegramAgentWrapper.close()` must run before `bot.session.close()`.
  - Neither manager calls `close()` today. Adding it also runs the existing knowledge-upload shutdown, transcriber close and reminder unregister, which is intended but new.
  - Each `close()` is isolated in try/except.
- **Slack's 3 s window.** `prepare_timeout = 2.0` on Slack, and prepare hooks must not touch the network. `SlackAgentWrapper.start()` warms the service (the Redis connect) so the first command is not slow.
- **Teams proactive delivery needs `client_id`.** Without it the command is refused up front rather than run and lost. Conversation references for channel and group chats work with `continue_conversation`. The existing convref store keeps only personal chats, so the adapter captures its own reference at command time.
- **Strict-path failure cascade.** In the strict gate an LLM failure becomes `approve=False`, then a blocking reason, then a draft and alerts (`_ask_llm_for_review` → `_merge_verdict`). The full review must not inherit this: `_ask_llm_for_full_review` raises `FullReviewLLMError`, and nothing is written to GitHub.
- **Unchanged strict behavior.** `/review_pr` keeps strict-gate semantics, including `_notify_blocked_pr` Telegram alerts even when it is invoked from Slack or Teams.
- **GitToolkit is fully registered as LLM tools** in `GitHubReviewer._attach_toolkit` (`github_reviewer.py:1296`). The four new read-only list methods therefore become callable by the review LLM, which is useful. The existing exposure of write tools predates this feature and is not changed here.
- **GitToolkit uses `requests` through `asyncio.to_thread`** (`_request`, `gittoolkit.py:1286`). The new methods reuse that helper and add no import. ADR-SEED-0003 forbids blocking I/O on the loop, and thread offload keeps the loop free. Migrating the toolkit to aiohttp is a non-goal.
- **Message and comment limits.**
  - Telegram: 4096-char chunks.
  - Slack: block text limits are handled by `_build_blocks`.
  - GitHub comments: 65,536 chars. Truncate at 65,000 with a note; the chat reply carries the full report when posting fails.
- **Concurrent `Agent.ask` on one reviewer instance** already happens today (webhook reviews alongside Telegram commands). The `github_review` group caps `/pr_review` + `/review_pr` at 2 per wrapper.
- **One agent on several wrappers** (Telegram + Slack) gets one service per wrapper. The concurrency cap and dedup are per wrapper; the shared Redis prefix keeps `/job_status` uniform.
- **iOS smart punctuation** turns `--flag` into `—flag`. The `/pr_review` parser normalizes it.
- **Inline paths stay possible.** `@queued_command` does not wrap the function, so direct calls (tests, `/function` before the guard) run inline. That is why `/function` and `/call` refuse queued methods explicitly.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none new (aiogram 3.31.0, botbuilder, redis via navigator-session, and `requests` in GitToolkit are already present) |

Not adopted (evaluated in research):
- `navigator.background`: a bounded queue that raises `QueueFull`, thread defaults, tied to the app.
- `AgentService` / `TaskQueue`: a per-agent single-task guard, never instantiated.
- `RedisJobInjector`: serial polling, and its key prefix clashes with `parrot:jobs:`.
- `SchedulerManager.run_schedule_now`: needs a stored schedule; results go out by email only.
- sdd_coder `JobTable`: memory-only, no TTL.

---

## Decisions

```yaml
schema_version: 1
document_id: queued-commands-integrations
entries:
  - id: jobs-in-core
    statement: JobManager, Job, JobStatus and RedisJobStore live in core parrot.jobs; parrot.handlers.jobs only re-exports them.
    relation: constrains
    about: [server, integrations]
    targets: [file:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py]
    contradicts: []
    supersedes: []
    rationale: The integrations package depends only on ai-parrot; moving the dependency-free job primitives to core gives chat commands the same Redis-backed job system the server uses, without a new dependency edge.
    rejected_alternatives:
      - A separate in-memory job registry inside ai-parrot-integrations (status lost on restart, duplicates JobManager).
      - A hard dependency from ai-parrot-integrations on ai-parrot-server.
  - id: queued-command-contract
    statement: A queued chat command acknowledges with a job id inside the platform request turn, runs as a background job, and delivers its result to the originating conversation.
    relation: requires
    about: [integrations]
    targets:
      - file:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
      - file:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
      - file:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
    contradicts: []
    supersedes: []
    rationale: Multi-minute commands blocked the user (Telegram), and could not fit the Slack 3 s ack or the Teams HTTP turn.
    rejected_alternatives:
      - Raising per-platform timeouts and keeping commands inline.
  - id: pr-review-llm-failure-writes-nothing
    statement: A failed full-review LLM call never posts a report, converts a PR to draft, or submits a review.
    relation: forbids
    about: [bots]
    targets: [file:packages/ai-parrot/src/parrot/bots/github_reviewer.py]
    contradicts: []
    supersedes: []
    rationale: In the strict gate an LLM failure becomes approve=False and can draft a compliant PR; a user-triggered review must fail loudly instead.
    rejected_alternatives:
      - Reusing the strict path's approve=False fallback.
```

## Consequences

<!-- decision-audit: input_digest=sha256:b26f6bbc1103c16151daca30e53b404e617f1d8e6c7ac0a58b45b4d6c1e14da5 evaluation_digest=sha256:726e05c30156c333132dc30b4650f80b6839a94dc74d6b6a384b59a9d4720ba1 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: auth, bots, clients, config, flows, integrations, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: background-jobs, chat-commands, github-reviewer, pr-review
- Targets resolved: 5/5
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "auth",
      "bots",
      "clients",
      "config",
      "flows",
      "integrations",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 5,
    "targets_total": 5,
    "unmapped_tags": [
      "background-jobs",
      "chat-commands",
      "github-reviewer",
      "pr-review"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:726e05c30156c333132dc30b4650f80b6839a94dc74d6b6a384b59a9d4720ba1",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:b26f6bbc1103c16151daca30e53b404e617f1d8e6c7ac0a58b45b4d6c1e14da5",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:c665ba2fa10f93d3abc4e34b71a5904bc9884dda00579568c36d908c9249af57",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Telegram command name for the full reviewer — *Resolved by Jesus Lara (2026-11-09)*: use `/pr_review` on Telegram. `pr-review` is a routing alias on Slack and Teams.
- [x] Where the chat job store comes from — *Resolved by Jesus Lara (2026-11-09)*: move `JobManager` / `Job` / `JobStatus` / `RedisJobStore` to core `parrot.jobs`. `parrot.handlers.jobs` keeps re-exporting them (M1).
- [x] What `/pr_review` writes to GitHub by default — *Resolved by Jesus Lara (2026-11-09)*: always post the report as a PR comment, like the Claude command. `--auto-draft` drafts on failing criteria; `--dry-run` keeps it chat-only. No APPROVE or REQUEST_CHANGES review.
- [x] Whether `/review_pr` also becomes queued — *Resolved by Jesus Lara (2026-11-09)*: yes, queue it too, with arguments and verdict text unchanged (G6, M7).
- [ ] In group chats, should `/jobs` list every job of the chat rather than only the requester's? The default is requester-only. — *Owner: Jesus Lara*
- [ ] Should webhook-triggered reviews (`review_pull_request`) also be registered as jobs, so they appear in `/jobs` and `/job_status`? Deferred; not needed for G1–G7. — *Owner: Jesus Lara*
- [ ] Cross-worker dedup (a Redis `SET NX` lease on the dedup key) if production runs several gunicorn workers per bot. Deferred to a follow-up. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: skipped (no accepted exploration document — `/sdd-spec` was invoked with notes only, so the §3b precondition is not met) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/integrations/queued-commands.md` — create. Covers:
    - declaring a `@queued_command` (prepare hooks, dedup, concurrency groups, `max_runtime`, progress);
    - the `/jobs`, `/job_status` and `/job_cancel` commands;
    - per-platform behavior and setup, including the Slack manifest slash commands and Teams `client_id`;
    - multi-worker limits and expiry.
  - `wiki/integrations/github-reviewer.md` — update. Add the `/pr_review` grammar, flags, report structure and env keys (`GITHUB_REVIEW_FULL_MAX_TOOL_CALLS`, `GITHUB_REVIEW_COMMAND_MAX_RUNTIME`). Note that `/review_pr` now runs in the background.
  - `wiki/flows/jobmanager.md` — update. Add a "Real implementation" section: the `parrot.jobs` import path, `cancel_job`, the `user_id` filter and the per-user Redis index.
- **API modules**:
  - `parrot.jobs`
  - `parrot.integrations.core.queued`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-09 | Jesus Lara | Initial draft from `/sdd-spec` notes; four design decisions taken with the user (Telegram name, job store, PR writes, `/review_pr` queued) |
