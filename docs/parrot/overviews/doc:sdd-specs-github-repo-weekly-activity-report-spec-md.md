---
type: Wiki Overview
title: 'Feature Specification: GitHub Repository Weekly Activity Report'
id: doc:sdd-specs-github-repo-weekly-activity-report-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: stale-PR digest, but teams running the agent have no visibility into
relates_to:
- concept: mod:parrot.bots.github_reviewer
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.scheduler
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: GitHub Repository Weekly Activity Report

**Feature ID**: FEAT-180
**Date**: 2026-05-18
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

`GitHubReviewer` (FEAT-179) already automates PR review and a daily
stale-PR digest, but teams running the agent have no visibility into
**who** is contributing **how much** week-to-week. Today, that data lives
in GitHub's Insights tab — useful but neither pushed nor compared against
previous periods, so the team learns about absences ("Charlie hasn't
pushed in three weeks") only when someone manually checks. We want the
bot to surface that data proactively, every Monday morning, on the same
Telegram channel where the daily report lands.

### Goals

1. Expose three new read-only GitHub statistics endpoints as tools in
   `GitToolkit`: contributor stats, weekly commit activity, and weekly
   code frequency.
2. Handle GitHub's `202 Accepted → 200 OK` async-compute protocol for
   `/stats/*` endpoints with a bounded retry-and-backoff loop, so the
   first call after a process start does not return empty data.
3. Add a `report_weekly_activity` method on `GitHubReviewer` decorated
   with `@schedule_weekly_report` (default `MON 09:00` UTC) that
   composes a templated digest and ships it via Telegram to the existing
   `public_channel_id`.
4. Templated output by default; behind a per-instance
   `use_llm_summary: bool = False` flag, generate a natural-language
   prose digest using the agent's LLM. The templated path remains
   authoritative — the LLM only re-phrases the same numbers.
5. The report compares the most recent completed week against the prior
   completed week (delta in commits + lines changed) and flags
   contributors silent for ≥ 3 consecutive weeks.

### Non-Goals (explicitly out of scope)

- **Email delivery** — the first iteration uses Telegram only. SMTP is a
  separate spec.
- **Per-team / per-area aggregation** — the report is contributor-level.
  Mapping logins to teams (HR data) is out of scope.
- **Historical persistence** — every report is composed from scratch
  off GitHub's API. No DB table, no time-series store.
- **Per-file or per-language breakdown** — additions/deletions are
  whole-commit aggregates; we do not parse the diff.
- **Outside-contributor filtering** — any login GitHub returns is
  included; teams that want to exclude bots/external contributors can
  configure an allow-list in a follow-up.
- **Multi-repo aggregation in one report** — each `GitHubReviewer`
  subclass handles its own repository. A "fleet view" is out of scope.

---

## 2. Architectural Design

### Overview

Two layers, mirroring the FEAT-179 pattern:

1. **Toolkit layer** (`parrot_tools.gittoolkit.GitToolkit`): three new
   async tools that wrap the GitHub `/stats/*` endpoints, including a
   shared private helper that polls until GitHub finishes computing
   (the `202 → 200` dance).
2. **Agent layer** (`parrot.bots.github_reviewer.GitHubReviewer`): one
   new scheduled method `report_weekly_activity` that calls the
   toolkit, builds a structured summary object, renders an HTML
   message (with optional LLM polish), and sends it via the existing
   Telegram pipeline (`_get_telegram_bot`).

No changes to webhook routing, auth, or the existing review flow.

### Component Diagram

```
@schedule_weekly_report               ┌──────────────────────────────────────┐
       │                              │ GitHub REST API                      │
       ▼                              │  /repos/.../stats/contributors       │
GitHubReviewer.report_weekly_activity │  /repos/.../stats/commit_activity    │
       │                              │  /repos/.../stats/code_frequency     │
       ├──→ GitToolkit.get_contributor_stats()      (handles 202 → 200)  ─→  │
       ├──→ GitToolkit.get_weekly_commit_activity() (handles 202 → 200)  ─→  │
       └──→ GitToolkit.get_code_frequency()         (handles 202 → 200)  ─→  │
                                                                            │
       ▼                                                                    │
_build_weekly_summary(contributors, code_freq)                              │
       │                                                                    │
       ├──→ [templated]   _format_weekly_activity_html(summary)             │
       └──→ [optional]    _llm_summarize(summary) ─→ self.ask(...)          │
       │                                                                    │
       ▼                                                                    │
_send_weekly_report_to_telegram(text)  via  self._get_telegram_bot()        │
       └──→ public_channel_id                                               │
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GitToolkit` (`parrot_tools.gittoolkit`) | extends with 3 tools + 1 helper | New methods plus a private `_get_stats_with_polling` sync helper. No change to existing PR tools. |
| `GitHubReviewer` (`parrot.bots.github_reviewer`) | extends with 1 scheduled method + helpers | Mirrors `report_stale_pull_requests` structure. |
| `schedule_weekly_report` (`parrot.scheduler`) | uses verbatim | Already exists; no scheduler changes. |
| `BotManager.register_bot_schedules` | implicit | Picks up `_schedule_report_type="weekly"` automatically via the existing scan. No code change. |
| Telegram `_get_telegram_bot()` + `public_channel_id` | uses | Same delivery path as stale-PR daily report. |
| `parrot.conf` | extends with 3 vars | `GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS`, `GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD`, `GITHUB_REVIEW_USE_LLM_SUMMARY`. |

### Data Models

```python
# parrot_tools.gittoolkit  (new Pydantic models for typed returns)

class ContributorWeek(BaseModel):
    """One week's slice of a contributor's activity (mirrors the GitHub
    `weeks[]` entry from /stats/contributors)."""
    week_start: datetime                # GitHub returns Unix epoch
    additions: int
    deletions: int
    commits: int


class ContributorStats(BaseModel):
    """Aggregated stats for a single contributor across the repo's history."""
    login: Optional[str]                # None when commit email isn't linked to a GH account
    avatar_url: Optional[str] = None
    total_commits: int
    weeks: List[ContributorWeek]


class WeeklyCodeFrequency(BaseModel):
    """Repo-wide weekly add/del totals."""
    week_start: datetime
    additions: int
    deletions: int


# parrot.bots.github_reviewer  (internal summary model)

class _ContributorWindowSummary(BaseModel):
    """One contributor's activity inside the reporting window."""
    login: str
    commits_this_week: int
    additions: int
    deletions: int
    weeks_silent: int                   # 0 if active in the last completed week

class WeeklyActivitySummary(BaseModel):
    """Structured input to the templated/LLM renderer."""
    repository: str
    period_start: datetime
    period_end: datetime
    contributors_active: List[_ContributorWindowSummary]
    contributors_silent: List[_ContributorWindowSummary]   # weeks_silent >= threshold
    total_commits: int
    total_additions: int
    total_deletions: int
    prev_total_commits: int
    prev_total_additions: int
    prev_total_deletions: int
```

### New Public Interfaces

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py

@tool_schema(GetContributorStatsInput)
async def get_contributor_stats(
    self,
    repository: Optional[str] = None,
) -> List[ContributorStats]:
    """Return per-contributor weekly stats for the repository.

    Calls GET /repos/{owner}/{repo}/stats/contributors. The endpoint is
    asynchronous on GitHub's side: the first call after a cold cache
    returns 202 with an empty body. This method retries with exponential
    backoff until it receives 200 (or gives up after `max_retries`),
    so callers always see a populated list.
    """

@tool_schema(GetCommitActivityInput)
async def get_weekly_commit_activity(
    self,
    repository: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Last 52 weeks of repo-wide commits broken down by day-of-week."""

@tool_schema(GetCodeFrequencyInput)
async def get_code_frequency(
    self,
    repository: Optional[str] = None,
) -> List[WeeklyCodeFrequency]:
    """Per-week additions/deletions for the whole repo since inception."""


# packages/ai-parrot/src/parrot/bots/github_reviewer.py

@schedule_weekly_report
async def report_weekly_activity(self) -> Dict[str, Any]:
    """Compose and send the weekly contributor-activity digest.

    Scheduled by `schedule_weekly_report`; the firing day/time is overridden
    via `{AGENT_ID}_WEEKLY_REPORT=DDD HH:MM` (UTC). Returns a small status
    dict (useful for tests + scheduler logs).
    """
```

---

## 3. Module Breakdown

### Module 1: `_get_stats_with_polling` helper in `GitToolkit`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
- **Responsibility**: Encapsulate the GitHub `202 Accepted → 200 OK`
  retry loop for `/stats/*` endpoints. Sync (runs inside
  `asyncio.to_thread`). Bounded retries (default 6) with exponential
  backoff (1s, 2s, 4s, 8s, 16s, 32s — capped at 60s). Raises
  `GitToolkitError` if GitHub never finishes within the budget.
- **Depends on**: existing `_request`, `_resolve_token`,
  `_resolve_repository`.

### Module 2: Stats tools on `GitToolkit`
- **Path**: same as Module 1.
- **Responsibility**: Three new `@tool_schema`-decorated async methods
  (`get_contributor_stats`, `get_weekly_commit_activity`,
  `get_code_frequency`), each with a matching `*Input` Pydantic schema
  and a sync `_*_sync` worker invoked via `asyncio.to_thread`. Convert
  raw JSON into the new Pydantic models declared in §2.
- **Depends on**: Module 1.

### Module 3: Weekly-summary builder in `GitHubReviewer`
- **Path**: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
- **Responsibility**: Pure function `_build_weekly_summary(contributors,
  code_freq, threshold_weeks)` that turns raw toolkit responses into a
  `WeeklyActivitySummary` covering the most recent **completed** week
  (i.e. Sunday-to-Saturday window strictly before the call moment, to
  match GitHub's week alignment). Computes prev-week deltas + silent
  contributors. No I/O, no LLM — easy to unit-test.
- **Depends on**: Module 2 (return shapes).

### Module 4: Templated HTML renderer
- **Path**: same as Module 3.
- **Responsibility**: `_format_weekly_activity_html(summary,
  jira_project)` builds the Telegram HTML message body using
  `html.escape` on every interpolation (same hygiene as
  `_format_alert_message`). Sorts contributors by commits desc, caps
  the list at top-N (configurable, default 10).
- **Depends on**: Module 3.

### Module 5: Optional LLM polishing
- **Path**: same as Module 3.
- **Responsibility**: `_llm_summarize_weekly(summary) -> str` that
  serializes the summary as a short prompt and calls `self.ask(...)`
  with a tight system prompt asking for an English paragraph. Only
  invoked when `self.use_llm_summary is True`. Falls back to the
  templated output on any exception (logged at WARNING).
- **Depends on**: Module 3.

### Module 6: `report_weekly_activity` scheduled method + sender
- **Path**: same as Module 3.
- **Responsibility**: Orchestrate the flow: fetch stats via Module 2,
  build summary via Module 3, render via Module 4 (or Module 5),
  ship via existing `_get_telegram_bot()` to `public_channel_id`.
  Return a status dict (`{"status": "ok", "active": N, "silent": M,
  "telegram_sent": K}`) for tests + scheduler logs. Idempotent / safe
  to re-trigger.
- **Depends on**: Modules 2–5.

### Module 7: Config + subclass wiring
- **Path**: `packages/ai-parrot/src/parrot/conf.py`
  and `agents/git.py` (`ParrotReviewer`).
- **Responsibility**: Add `GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS`,
  `GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD`,
  `GITHUB_REVIEW_USE_LLM_SUMMARY`. Forward them through
  `ParrotReviewer.__init__` like the existing knobs.
- **Depends on**: Modules 3 and 5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_stats_polling_returns_immediately_on_200` | 1 | One mocked response with 200 returns data; no retry. |
| `test_stats_polling_handles_202_then_200` | 1 | Two mocked 202 then 200 → returns the parsed body. |
| `test_stats_polling_gives_up_after_max_retries` | 1 | All 202 responses → raises `GitToolkitError`. |
| `test_contributor_stats_parses_models` | 2 | Mock GitHub response → returns typed `List[ContributorStats]`. |
| `test_contributor_stats_handles_anonymous_author` | 2 | `author.login == None` in raw payload → `login=None`, not crash. |
| `test_get_code_frequency_returns_models` | 2 | Raw `[[week, adds, dels], ...]` → typed list. |
| `test_build_weekly_summary_aligns_to_completed_week` | 3 | Given a fixed "now", picks the right week pair. |
| `test_build_weekly_summary_flags_silent_contributors` | 3 | Contributor with 0 commits in last `threshold` weeks → in `contributors_silent`. |
| `test_build_weekly_summary_computes_deltas` | 3 | Prev/current week totals computed correctly. |
| `test_format_weekly_activity_html_escapes_logins` | 4 | A login like `<bad>` is HTML-escaped. |
| `test_format_weekly_activity_html_truncates_top_n` | 4 | 30 contributors → only top-N shown. |
| `test_llm_summarize_falls_back_on_exception` | 5 | `self.ask` raises → returns templated output, logs WARN. |
| `test_report_weekly_activity_skips_when_no_toolkit` | 6 | `git_toolkit is None` → `{"status": "error"}`. |
| `test_report_weekly_activity_telegram_disabled` | 6 | No `_wrapper` → returns `telegram_sent=0`, no exception. |
| `test_report_weekly_activity_success_dict_shape` | 6 | Happy path returns the documented status dict. |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_weekly_report_against_recorded_github_response` | Use a fixture file with a canned `/stats/contributors` + `/stats/code_frequency` response. End-to-end: builder → renderer → assert HTML contains expected names and totals. No network. |
| `test_report_with_use_llm_summary_true_uses_stub_llm` | Pass a stub LLM that records the prompt; assert prompt contains the summary's totals. |

### Test Data / Fixtures

```python
@pytest.fixture
def github_contributors_payload():
    """Canned response body of GET /stats/contributors for a small repo."""
    return [
        {
            "author": {"login": "alice", "avatar_url": "...", "id": 1},
            "total": 27,
            "weeks": [
                {"w": 1716422400, "a": 100, "d": 20, "c": 4},  # current
                {"w": 1715817600, "a": 200, "d": 50, "c": 7},  # prev
                # ...
            ],
        },
        # ...
    ]

@pytest.fixture
def fixed_now(monkeypatch):
    """Freeze datetime.now() so week alignment is deterministic."""
    import datetime
    target = datetime.datetime(2026, 5, 18, 9, 0, tzinfo=datetime.timezone.utc)
    # ... patch helper
```

---

## 5. Acceptance Criteria

- [ ] `GitToolkit.get_contributor_stats()`, `get_weekly_commit_activity()`,
      and `get_code_frequency()` are present and decorated with
      `@tool_schema`.
- [ ] Each of the three new methods successfully retrieves data from a
      cold-cache repo by transparently handling the GitHub `202 → 200`
      poll cycle.
- [ ] `_get_stats_with_polling` gives up cleanly with a logged warning
      and a `GitToolkitError` if GitHub returns 202 more than
      `max_retries` consecutive times.
- [ ] Pydantic return models (`ContributorStats`, `ContributorWeek`,
      `WeeklyCodeFrequency`) match the shape in §2.
- [ ] `GitHubReviewer.report_weekly_activity` is decorated with
      `@schedule_weekly_report` and is picked up by
      `BotManager.register_bot_schedules` with no additional plumbing.
- [ ] When invoked, `report_weekly_activity` returns a dict with keys
      `status`, `repository`, `period_start`, `period_end`,
      `active`, `silent`, `telegram_sent`.
- [ ] The templated Telegram message renders cleanly (no 400 from
      Telegram) when contributor logins contain `<`, `>`, `&`, `"`.
- [ ] The summary marks contributors as **silent** when they have zero
      commits in the last `GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD` weeks
      (default 3).
- [ ] When `use_llm_summary=True` and `self.ask` raises, the agent
      falls back to the templated message and ships it anyway (a
      single LLM hiccup must not skip a weekly report).
- [ ] When `git_toolkit is None`, `report_weekly_activity` returns
      `{"status": "error", "reason": "git_toolkit not configured"}`
      and does not raise.
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/bots/test_github_reviewer.py` and `pytest packages/ai-parrot-tools/tests/test_gittoolkit_stats.py -v`).
- [ ] Existing 42 tests in `test_github_reviewer.py` continue to pass.
- [ ] No breaking changes to existing `GitToolkit` PR tools or
      `GitHubReviewer.handle_hook_event`.
- [ ] Documentation: `docs/github-reviewer.md` gets a new "Weekly
      activity report" subsection with the env vars and a sample output.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Stats tool layer
from parrot_tools.gittoolkit import GitToolkit, GitToolkitError
# verified: packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:38, :253

# Agent layer
from parrot.bots.github_reviewer import GitHubReviewer
# verified: packages/ai-parrot/src/parrot/bots/github_reviewer.py:153

# Scheduler decorator
from parrot.scheduler import schedule_weekly_report
# verified: packages/ai-parrot/src/parrot/scheduler/__init__.py:164,189

# Existing tool-schema decorator
from parrot.tools.base import tool_schema
# verified: same module already used at gittoolkit.py:660,720,786 etc.
# (resolves via parrot_tools' existing import chain — copy that import line
#  verbatim from the top of gittoolkit.py)

# Pydantic
from pydantic import BaseModel, Field
# verified: gittoolkit.py:42 and github_reviewer.py:40
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py

class GitToolkitError(RuntimeError):  # line 38

class GitToolkit(AbstractToolkit):     # line 253
    input_class = GitToolkitInput       # line 256

    def __init__(                       # line 258
        self,
        default_repository: Optional[str] = None,
        default_branch: str = "main",
        github_token: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...

    # All staticmethod / private helpers used by stats endpoints:
    @staticmethod
    def _request(                       # line 395
        method: str,
        url: str,
        token: str,
        *,
        expected: int,
        **kwargs: Any,
    ) -> requests.Response: ...

    def _resolve_token(self) -> str:    # line 578
    def _resolve_repository(self,       # near line 565 (verify before use)
                            repository: Optional[str]) -> str: ...

    # Existing async tool pattern to mirror:
    @tool_schema(GetPullRequestDiffInput)
    async def get_pull_request_diff(    # line 661
        self,
        pr_number: int,
        repository: Optional[str] = None,
        max_bytes: int = 50_000,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._get_pull_request_diff_sync, repository, pr_number, max_bytes
        )
```

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py

class GitHubReviewer(Agent):                       # line 153
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW     # line 200

    # Existing scheduled method to mirror:
    @schedule_daily_report                          # line ~830
    async def report_stale_pull_requests(self) -> Dict[str, Any]:
        if self.git_toolkit is None:
            return {"status": "error", "reason": "git_toolkit not configured"}
        try:
            pulls = await self.git_toolkit.list_pull_requests(
                repository=self.repository, state="open", per_page=100
            )
        except Exception as exc:
            ...
        # Telegram delivery via:
        bot = self._get_telegram_bot()              # line ~790
        if bot is not None and self.public_channel_id:
            await bot.send_message(
                chat_id=self.public_channel_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

    # Existing helper to reuse:
    def _get_telegram_bot(self):                    # line ~790
        if self._wrapper is None:
            return None
        return getattr(self._wrapper, "bot", None)

    # State attributes set in __init__:
    self.git_toolkit: Optional[GitToolkit]
    self.repository: str
    self.public_channel_id: Optional[ChatId]
    self.jira_project: str
    self.logger: logging.Logger
```

```python
# packages/ai-parrot/src/parrot/scheduler/__init__.py

schedule_weekly_report = _report_decorator_factory(   # line 164
    "weekly", ScheduleType.WEEKLY.value
)
# Sets two attributes on the wrapped function:
#   wrapper._schedule_report_type = "weekly"
#   wrapper._schedule_config = {
#     'schedule_type': 'weekly',
#     'schedule_config': {},
#     'method_name': func.__name__,
#     ...
#   }
# Env var key resolved at register-time: f"{AGENT_ID}_WEEKLY_REPORT"
# Format: "DDD HH:MM" UTC; default "MON 09:00".
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_get_stats_with_polling` | `GitToolkit._request` | direct call (loops until `200`) | `gittoolkit.py:395` |
| `get_contributor_stats` | `GitToolkit._resolve_token`, `_resolve_repository` | sync helper inside `asyncio.to_thread` | `gittoolkit.py:578` (token); resolver: re-verify before implementing |
| `report_weekly_activity` | `self.git_toolkit.get_contributor_stats()` | direct method call (no LLM tool invocation needed) | new method on `GitToolkit` |
| `report_weekly_activity` | `self._get_telegram_bot()`, `self.public_channel_id` | existing helpers | `github_reviewer.py:790` |
| `BotManager.register_bot_schedules` | `report_weekly_activity` | discovered via `_schedule_report_type` attribute | mirrors how `report_stale_pull_requests` is picked up — no new code |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.scheduler.schedule_monthly_report`~~ — not implemented;
  only `schedule_daily_report` and `schedule_weekly_report` exist
  (scheduler/__init__.py:188-189).
- ~~`GitToolkit.get_repo_insights`~~ — not a real method. The three
  endpoints in §2 are the only stats wrappers being added.
- ~~`requests.get_with_retry`~~ — the `requests` lib has no such
  helper; we implement `_get_stats_with_polling` ourselves.
- ~~`GitHubReviewer._notify_telegram`~~ — does not exist by that
  name; the actual helper is `_notify_telegram_alert`
  (`github_reviewer.py` ~line 763). For the weekly report we add a
  dedicated `_send_weekly_report_to_telegram` rather than reusing the
  alert path (different formatting, different audience).
- ~~`GitToolkit.get_languages`~~ — not part of this spec; explicitly
  out of scope (§1 Non-Goals: no language breakdown).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Sync helper + async wrapper via `asyncio.to_thread`** — keep parity
  with every other `GitToolkit` method (`gittoolkit.py:619,661,721,786`).
- **`@tool_schema(InputSchema)`** on every new public method, with the
  schema defined as a Pydantic class in the same module right before
  the method.
- **Pydantic models for all structured returns** — no raw dicts leaking
  out of toolkits.
- **HTML escape every Telegram interpolation** with `html.escape(...)`
  (same hygiene as `_format_alert_message` in `github_reviewer.py`).

…(truncated)…
