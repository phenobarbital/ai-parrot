---
type: Wiki Overview
title: 'TASK-1213: Implement templated HTML renderer for the weekly digest'
id: doc:sdd-tasks-completed-task-1213-weekly-html-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The weekly report ships via Telegram with `parse_mode="HTML"` (same
---

# TASK-1213: Implement templated HTML renderer for the weekly digest

**Feature**: FEAT-180 — GitHub Repository Weekly Activity Report
**Spec**: `sdd/specs/github-repo-weekly-activity-report.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1212
**Assigned-to**: unassigned

---

## Context

The weekly report ships via Telegram with `parse_mode="HTML"` (same
hygiene as the existing `_format_alert_message`). This task converts a
`WeeklyActivitySummary` into the HTML body that the orchestrator
(TASK-1215) will send. Implements spec §3 Module 4.

The templated path is **authoritative**: even when the optional LLM
summarizer (TASK-1214) is enabled, this renderer's output is the fact
sheet the LLM rephrases — the LLM never has its own access to raw stats.

---

## Scope

- Add `_format_weekly_activity_html(summary: WeeklyActivitySummary)` on
  `GitHubReviewer`. Returns the full Telegram-ready HTML body.
- Escape every interpolation with `html.escape(...)` (logins, repo,
  arbitrary text). Numbers can be formatted with `f"{n:,}"` for
  thousand separators.
- Render structure:
  - Header: `<b>Weekly activity — {repo}</b>` + period line.
  - Totals: commits + adds/dels for the week + delta vs prev week
    (e.g. `▲ +12%`, `▼ −5%`, or `flat 0%`). Compute percentages from
    `prev_total_*`; show `n/a` when prev is zero.
  - Active contributors: up to top-N rows. Format:
    `1. <code>alice</code> — 12 commits, 1,834 ± 421`
    (or similar — keep one-line-per-contributor).
  - Silent contributors: if non-empty, a `<b>Silent (≥{threshold}w)</b>`
    section listing `<code>charlie</code> — 4 weeks` per line.
  - Footer one-liner identifying the bot.
- Total message MUST stay under Telegram's 4096 character limit. With
  top-N capped (default 10) this is fine; document that the cap exists
  so it can't blow up.

**NOT in scope**:

- LLM prose generation (TASK-1214).
- Sending the message (TASK-1215).
- Locale / i18n. Output is English.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Add `_format_weekly_activity_html` near the other formatters. |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | Add `TestFormatWeeklyActivityHtml` test class. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present at the top of github_reviewer.py:
import html                                  # used by _format_alert_message
from collections import Counter              # may be unused here
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py

class GitHubReviewer(Agent):                 # line 153
    repository: str
    jira_project: str
    # WeeklyActivitySummary and _ContributorWindowSummary
    # were added by TASK-1212.

    def _format_alert_message(               # ~line 795 — STYLE REFERENCE
        self,
        payload: Dict[str, Any],
        ticket_key: str,
        result: PRReviewResult,
    ) -> str:
        """Uses html.escape on every interpolation; parse_mode=HTML on send."""
```

### Does NOT Exist

- ~~`telegram.Bot.escape_html`~~ — not part of the python-telegram-bot
  API; use stdlib `html.escape`.
- ~~`<table>` tags in Telegram~~ — Telegram HTML supports only a small
  whitelist: `<b>`, `<i>`, `<u>`, `<s>`, `<code>`, `<pre>`, `<a>`,
  `<tg-spoiler>`, `<blockquote>`. Plain newlines for layout.
- ~~Emoji from a dedicated lib~~ — use literal Unicode chars (▲ ▼ ◯)
  embedded in the source. They are valid in Telegram HTML.

---

## Implementation Notes

### Pattern to Follow

```python
def _format_weekly_activity_html(
    self,
    summary: WeeklyActivitySummary,
) -> str:
    repo = html.escape(summary.repository)
    period = (
        f"{summary.period_start:%Y-%m-%d} → "
        f"{(summary.period_end - timedelta(days=1)):%Y-%m-%d}"
    )
    # Period start (Sunday) → end (Saturday) inclusive in display.

    def pct(curr: int, prev: int) -> str:
        if prev == 0:
            return "n/a" if curr == 0 else "▲ new"
        delta = (curr - prev) / prev * 100
        if abs(delta) < 0.5:
            return "flat 0%"
        arrow = "▲" if delta > 0 else "▼"
        return f"{arrow} {delta:+.0f}%"

    lines: List[str] = [
        f"<b>Weekly activity — <code>{repo}</code></b>",
        f"Period: {period}",
        "",
        (
            f"<b>{summary.total_commits}</b> commits "
            f"({pct(summary.total_commits, summary.prev_total_commits)})"
        ),
        (
            f"{summary.total_additions:,} added / "
            f"{summary.total_deletions:,} removed "
            f"({pct(summary.total_additions + summary.total_deletions, "
            f"summary.prev_total_additions + summary.prev_total_deletions)})"
        ),
    ]

    if summary.contributors_active:
        lines.append("")
        lines.append(f"<b>Top contributors</b>")
        for i, c in enumerate(summary.contributors_active, start=1):
            login = html.escape(c.login)
            lines.append(
                f"{i}. <code>{login}</code> — {c.commits_this_week} commits, "
                f"{c.additions:,} / {c.deletions:,}"
            )

    if summary.contributors_silent:
        lines.append("")
        lines.append(f"<b>Silent contributors</b>")
        for c in summary.contributors_silent:
            login = html.escape(c.login)
            lines.append(
                f"<code>{login}</code> — silent {c.weeks_silent} weeks"
            )

    lines.append("")
    lines.append("<i>Posted by the GitHubReviewer agent.</i>")
    return "\n".join(lines)
```

### Key Constraints

- **All interpolations through `html.escape(...)`**. A login like
  `<bad>` must not break the message.
- **Telegram HTML whitelist only**: `<b>`, `<i>`, `<code>`, `<a>`,
  `<pre>`, `<u>`, `<s>`, `<blockquote>`. No `<table>`, no `<div>`,
  no `<span>`.
- **Stay under 4096 chars** — top-N capped from TASK-1212 keeps this
  comfortably bounded.
- **No I/O** — pure formatting.
- **No `self.logger`** — formatters in this module don't log.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:795` —
  `_format_alert_message` is the structural and hygiene reference.
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:707` —
  `_format_review_body` (different markup but similar layering of
  helpers).

---

## Acceptance Criteria

- [ ] `_format_weekly_activity_html(summary)` exists and returns a
      string.
- [ ] Every login, repo name, and arbitrary text is `html.escape`-d.
- [ ] Output uses ONLY whitelisted Telegram HTML tags.
- [ ] When `summary.contributors_silent` is empty, the "Silent
      contributors" section is omitted (not just an empty header).
- [ ] When `prev_total_commits == 0`, the percentage shows `n/a` (no
      div-by-zero crash).
- [ ] Total message length < 4096 chars for any
      `WeeklyActivitySummary` produced by TASK-1212 with default
      `top_n=10`.
- [ ] Unit tests cover: escaping of `<`, `>`, `&` in logins; missing
      silent section; pct n/a path; pct positive / negative / flat
      paths; expected ordering preserved.
- [ ] `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py::TestFormatWeeklyActivityHtml -v` passes.
- [ ] No regression in existing tests.

---

## Test Specification

```python
# tests/bots/test_github_reviewer.py — appended

class TestFormatWeeklyActivityHtml:
    def _summary(self, **overrides):
        defaults = dict(
            repository="owner/repo",
            period_start=W_CURR,
            period_end=W_CURR + timedelta(days=7),
            contributors_active=[
                _ContributorWindowSummary(
                    login="alice", commits_this_week=12,
                    additions=1834, deletions=421, weeks_silent=0,
                ),
            ],
            contributors_silent=[],
            total_commits=12,
            total_additions=1834,
            total_deletions=421,
            prev_total_commits=10,
            prev_total_additions=2000,
            prev_total_deletions=500,
        )
        defaults.update(overrides)
        return WeeklyActivitySummary(**defaults)

    def test_escapes_special_chars(self):
        r = _MinimalReviewer()
        r._format_weekly_activity_html = GitHubReviewer._format_weekly_activity_html
        s = self._summary(
            contributors_active=[
                _ContributorWindowSummary(
                    login="<bad>&you", commits_this_week=1,
                    additions=0, deletions=0, weeks_silent=0,
                )
            ]
        )
        body = r._format_weekly_activity_html(s)
        assert "&lt;bad&gt;&amp;you" in body
        assert "<bad>" not in body

    def test_skips_empty_silent_section(self):
        body = ... # render summary with contributors_silent=[]
        assert "Silent contributors" not in body

    def test_pct_handles_zero_prev(self):
        s = self._summary(prev_total_commits=0)
        body = ... # render
        assert "n/a" in body or "▲ new" in body

    def test_pct_positive_and_negative(self): ...
    def test_truncation_respected(self): ...
```

---

## Agent Instructions

1. Read spec §3 Module 4, §7 Patterns to Follow.
2. Dependencies: TASK-1212 done; `WeeklyActivitySummary` exists.
3. Verify `html.escape` import; verify `_format_alert_message` line.
4. Update index → in-progress.
5. Implement + test.
6. Move file → completed, update index → done.

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-05-18
**Notes**: Added _format_weekly_activity_html to GitHubReviewer. Uses html.escape on all
interpolations, respects Telegram HTML whitelist, stays under 4096 chars with default top_n=10.
All 8 tests in TestFormatWeeklyActivityHtml pass; no regressions.

**Deviations from spec**: None.
