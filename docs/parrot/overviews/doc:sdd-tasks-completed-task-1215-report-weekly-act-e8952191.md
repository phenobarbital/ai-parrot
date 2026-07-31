---
type: Wiki Overview
title: 'TASK-1215: Implement `report_weekly_activity` orchestrator + Telegram sender'
id: doc:sdd-tasks-completed-task-1215-report-weekly-activity-orchestrator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The scheduled entry-point. Implements spec §3 Module 6 — the only
relates_to:
- concept: mod:parrot.scheduler
  rel: mentions
---

# TASK-1215: Implement `report_weekly_activity` orchestrator + Telegram sender

**Feature**: FEAT-180 — GitHub Repository Weekly Activity Report
**Spec**: `sdd/specs/github-repo-weekly-activity-report.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1211, TASK-1212, TASK-1213, TASK-1214
**Assigned-to**: unassigned

---

## Context

The scheduled entry-point. Implements spec §3 Module 6 — the only
method in the feature that fires automatically every week, fetches
stats, builds the summary, picks templated vs LLM rendering, and ships
the digest to Telegram. Everything else this feature adds is in
service of this method.

Mirrors `report_stale_pull_requests` (line ~830 of
`github_reviewer.py`) so operators see a familiar pattern.

---

## Scope

- Add an instance attribute `self.use_llm_summary: bool` initialized
  from a constructor kwarg (default `False`).
- Add `report_weekly_activity` method on `GitHubReviewer`, decorated
  with `@schedule_weekly_report`.
- Flow inside the method:
  1. If `self.git_toolkit is None`, return
     `{"status": "error", "reason": "git_toolkit not configured"}`.
  2. Fetch `get_contributor_stats` and `get_code_frequency` in
     parallel via `asyncio.gather`. On any exception, log error and
     return `{"status": "error", "reason": str(exc)}`.
  3. Call `_build_weekly_summary` with the configured
     `threshold_weeks`.
  4. Decide rendering: if `self.use_llm_summary`, call
     `_llm_summarize_weekly(summary)` inside try/except. On
     `WeeklyLLMSummarizationError`, log WARNING and fall back to
     `_format_weekly_activity_html(summary)`. Else use the templated
     path directly.
  5. Wrap LLM prose output inside a minimal HTML envelope (e.g.
     prepend a single `<b>Weekly activity — …</b>` header) so it stays
     consistent. The templated body already includes the header.
  6. Send via `self._get_telegram_bot()` to `self.public_channel_id`
     with `parse_mode="HTML"`. If the bot is None or
     `public_channel_id` is None, return without sending and report
     `telegram_sent=0`.
  7. Log `info` with one structured line summarising the run.
  8. Return the status dict with all the fields from §5 Acceptance
     Criteria.
- Idempotent: invoking twice produces no side effects beyond two
  separate Telegram messages. No internal mutation of `self.*`.

**NOT in scope**:

- Wiring `use_llm_summary` from env (TASK-1216).
- Adding the new `threshold_weeks` / `top_n` constructor kwargs from
  env (TASK-1216).
- Documentation updates (TASK-1216).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Add `use_llm_summary` / `silent_weeks_threshold` / `top_n_contributors` to `__init__`; add `report_weekly_activity`. |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | New `TestReportWeeklyActivity` class. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present:
import asyncio
from typing import Any, Dict, List, Optional

from parrot.scheduler import schedule_daily_report   # already imported
# Add the weekly decorator:
from parrot.scheduler import schedule_weekly_report   # verified: scheduler/__init__.py:164,189
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py

class GitHubReviewer(Agent):                  # line 153
    repository: str
    jira_project: str
    git_toolkit: Optional[GitToolkit]
    public_channel_id: Optional[ChatId]
    logger: logging.Logger

    def _get_telegram_bot(self):              # ~line 790
        if self._wrapper is None:
            return None
        return getattr(self._wrapper, "bot", None)

    @schedule_daily_report                    # ~line 830 — STRUCTURAL REFERENCE
    async def report_stale_pull_requests(self) -> Dict[str, Any]:
        if self.git_toolkit is None:
            return {"status": "error", "reason": "git_toolkit not configured"}
        try:
            pulls = await self.git_toolkit.list_pull_requests(...)
        except Exception as exc:
            self.logger.error(...)
            return {"status": "error", "reason": str(exc)}
        ...
        bot = self._get_telegram_bot()
        if bot is not None and self.public_channel_id:
            await bot.send_message(
                chat_id=self.public_channel_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

    # Added in TASK-1212:
    def _build_weekly_summary(
        self,
        contributors: List[ContributorStats],
        code_freq: List[WeeklyCodeFrequency],
        *,
        threshold_weeks: int,
        top_n: int = 10,
        now: Optional[datetime] = None,
    ) -> WeeklyActivitySummary: ...

    # Added in TASK-1213:
    def _format_weekly_activity_html(
        self, summary: WeeklyActivitySummary
    ) -> str: ...

    # Added in TASK-1214:
    async def _llm_summarize_weekly(
        self, summary: WeeklyActivitySummary
    ) -> str: ...

class WeeklyLLMSummarizationError(RuntimeError): ...
```

### Does NOT Exist

- ~~`Agent.run_periodically`~~ — the scheduler decorator on a method is
  the only contract. The method itself is a normal coroutine.
- ~~`BotManager.invoke_scheduled_method`~~ — no explicit invocation
  needed; the decorator + `register_bot_schedules` handle wiring.
- ~~`self._send_telegram(...)`~~ — no such generic helper. Use
  `_get_telegram_bot()` + `await bot.send_message(...)` directly, as
  `report_stale_pull_requests` does.

---

## Implementation Notes

### Constructor change

```python
def __init__(
    self,
    repository: str,
    *,
    # ... existing kwargs ...
    silent_weeks_threshold: int = 3,
    top_n_contributors: int = 10,
    use_llm_summary: bool = False,
    **kwargs: Any,
) -> None:
    # ... existing body ...
    self.silent_weeks_threshold = int(silent_weeks_threshold)
    self.top_n_contributors = int(top_n_contributors)
    self.use_llm_summary = bool(use_llm_summary)
```

### Method body sketch

```python
@schedule_weekly_report
async def report_weekly_activity(self) -> Dict[str, Any]:
    """Compose and send the weekly contributor-activity digest.

    Scheduled by schedule_weekly_report. Override the firing day/time
    via {AGENT_ID}_WEEKLY_REPORT=DDD HH:MM (UTC, default MON 09:00).
    """
    if self.git_toolkit is None:
        self.logger.warning(
            "GitHubReviewer: weekly activity report skipped — "
            "git_toolkit not configured."
        )
        return {"status": "error", "reason": "git_toolkit not configured"}

    try:
        contributors, code_freq = await asyncio.gather(
            self.git_toolkit.get_contributor_stats(repository=self.repository),
            self.git_toolkit.get_code_frequency(repository=self.repository),
        )
    except Exception as exc:  # noqa: BLE001
        self.logger.error(
            "GitHubReviewer: weekly stats fetch failed for %s: %s",
            self.repository, exc, exc_info=True,
        )
        return {"status": "error", "reason": str(exc)}

    summary = self._build_weekly_summary(
        contributors, code_freq,
        threshold_weeks=self.silent_weeks_threshold,
        top_n=self.top_n_contributors,
    )

    rendered_via = "templated"
    if self.use_llm_summary:
        try:
            llm_body = await self._llm_summarize_weekly(summary)
            text = self._wrap_llm_prose_in_html_envelope(llm_body, summary)
            rendered_via = "llm"
        except WeeklyLLMSummarizationError as exc:
            self.logger.warning(
                "GitHubReviewer: LLM summary failed (%s); falling back to "
                "templated output.", exc,
            )
            text = self._format_weekly_activity_html(summary)
    else:
        text = self._format_weekly_activity_html(summary)

    telegram_sent = 0
    bot = self._get_telegram_bot()
    if bot is not None and self.public_channel_id:
        try:
            await bot.send_message(
                chat_id=self.public_channel_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            telegram_sent = 1
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "GitHubReviewer: failed to send weekly report: %s", exc,
            )

    self.logger.info(
        "GitHubReviewer: weekly activity report — repo=%s, active=%d, "
        "silent=%d, rendered_via=%s, telegram_sent=%d.",
        self.repository,
        len(summary.contributors_active),
        len(summary.contributors_silent),
        rendered_via,
        telegram_sent,
    )

    return {
        "status": "ok",
        "repository": self.repository,
        "period_start": summary.period_start.isoformat(),
        "period_end": summary.period_end.isoformat(),
        "active": len(summary.contributors_active),
        "silent": len(summary.contributors_silent),
        "rendered_via": rendered_via,
        "telegram_sent": telegram_sent,
    }
```

### `_wrap_llm_prose_in_html_envelope`

Small helper that prepends a one-line header and footer to plain prose
returned by the LLM so the look-and-feel matches the templated path:

```python
def _wrap_llm_prose_in_html_envelope(
    self, prose: str, summary: WeeklyActivitySummary
) -> str:
    repo = html.escape(summary.repository)
    body = html.escape(prose)
    return (
        f"<b>Weekly activity — <code>{repo}</code></b>\n\n"
        f"{body}\n\n"
        f"<i>Posted by the GitHubReviewer agent.</i>"
    )
```

Note: `html.escape(prose)` because we cannot trust LLM output not to
contain `<` etc.

### Key Constraints

- **Idempotent**: no internal cache / state mutation. Safe to invoke
  twice manually for testing.
- **One INFO log line per run**, plus warnings/errors for unhappy
  paths. Never log the rendered body at INFO (GDPR — see spec §7).
- **Never raise** out of this method. Internal errors become
  `{"status": "error"}` returns so the scheduler doesn't backoff
  unnecessarily.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:830` —
  `report_stale_pull_requests` structural reference (status dict,
  bot + channel checks, error handling).

---

## Acceptance Criteria

- [ ] `self.use_llm_summary`, `self.silent_weeks_threshold`,
      `self.top_n_contributors` exist after `__init__`.
- [ ] `report_weekly_activity` is decorated with
      `@schedule_weekly_report`.
- [ ] Returns `{"status": "error"}` when `git_toolkit is None`.
- [ ] Returns `{"status": "error"}` when stats fetch raises.
- [ ] Picks the templated path when `use_llm_summary=False`.
- [ ] Picks the LLM path when `use_llm_summary=True`; falls back to
      templated on `WeeklyLLMSummarizationError`.
- [ ] Returns the documented status dict (`status`, `repository`,
      `period_start`, `period_end`, `active`, `silent`,
      `rendered_via`, `telegram_sent`).
- [ ] Telegram failure (e.g. bot raises) does not raise out of the
      method; returns with `telegram_sent=0` and logs a warning.
- [ ] No internal `self.*` state mutated.
- [ ] Unit tests cover all five branches (no toolkit, fetch fails,
      templated success, LLM success, LLM-then-fallback) plus the
      no-Telegram-wrapper case.
- [ ] All tests pass; existing 42+ tests still pass.

---

## Test Specification

```python
# tests/bots/test_github_reviewer.py — appended

class TestReportWeeklyActivity:
    def test_no_toolkit_returns_error(self):
        r = _wire_reviewer()
        r.git_toolkit = None
        r.report_weekly_activity = GitHubReviewer.report_weekly_activity
        # Decorator-wrapped — invoke via .__wrapped__ if decorator stores it,
        # otherwise call the bound method directly.
        out = asyncio.run(r.report_weekly_activity())
        assert out["status"] == "error"
        assert "git_toolkit" in out["reason"]

    def test_stats_fetch_failure_returns_error(self):
        r = _wire_reviewer()
        async def fail(**kwargs): raise RuntimeError("boom")
        r.git_toolkit.get_contributor_stats = fail
        r.git_toolkit.get_code_frequency = fail
        # ... assert out["status"] == "error"

    def test_templated_success_path(self):
        r = _wire_reviewer()
        # Stub the three pure helpers + toolkit calls, assert templated body sent.
        ...

    def test_llm_success_path(self):
        r = _wire_reviewer()
        r.use_llm_summary = True
        # Stub _llm_summarize_weekly to return prose; assert out["rendered_via"]=="llm"
        ...

    def test_llm_failure_falls_back(self):
        r = _wire_reviewer()
        r.use_llm_summary = True
        async def llm_boom(self_, summary): raise WeeklyLLMSummarizationError("x")
        # ... assert out["rendered_via"]=="templated", out["telegram_sent"]==1

    def test_telegram_failure_does_not_raise(self):
        r = _wire_reviewer()
        async def fail_send(**kwargs): raise RuntimeError("telegram 500")
        r._wrapper = MagicMock(bot=MagicMock(send_message=fail_send))
        # ... assert out["telegram_sent"] == 0
```

---

## Agent Instructions

1. Read spec §3 Module 6, §5 Acceptance Criteria.
2. Dependencies: TASKs 1211, 1212, 1213, 1214 done.
3. Verify all helper method signatures from those tasks.
4. Update index → in-progress.
5. Implement + test (decorator-wrapped methods: invoke via the bound
   method on the instance — the decorator returns an `async def
   wrapper` so calling `r.report_weekly_activity()` from a test
   works without unwrapping).
6. Move file → completed, update index → done.

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-05-18
**Notes**: Added report_weekly_activity decorated with @schedule_weekly_report. Handles all
branches: no toolkit, stats fetch failure, no-data ValueError, LLM summarization with fallback,
Telegram failure. Added import asyncio (was missing — caused asyncio.gather NameError in tests).
All 6 tests in TestReportWeeklyActivity pass; all 68 github_reviewer tests pass.

**Deviations from spec**: None.

**Deviations from spec**:
