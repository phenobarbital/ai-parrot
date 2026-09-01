# TASK-2674: Email digests — retained but disabled (G9)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2670
**Assigned-to**: unassigned
**Parallel**: true

---

## Context

Spec Module 15. Keep daily/weekly email digests available for future use, shipped
**disabled** behind a feature flag. Reuse the digest approach from
`agents/fireflies_wiki.py` by porting (not editing that file).

## Scope

- `nodes/email.py`: daily/weekly digest rendered from the compiled daily notes / overview delta (not raw transcripts).
- Gated by `FIREFLIES_WIKI_EMAIL_ENABLED` (default **false**) — no send unless explicitly enabled.
- Reuse the notification/send mechanism available to the agent (`NotificationMixin`); recipients via config.

**NOT in scope**: enabling by default; Slack/Teams surfaces.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/nodes/email.py` | CREATE | disabled-by-default digests |
| `packages/ai-parrot/tests/unit/test_wiki_kb_email.py` | CREATE | flag-gated send test |

## Codebase Contract (Anti-Hallucination)
### Notes
- Reference `agents/fireflies_wiki.py` `email_daily_meeting_digest` / `email_weekly_insights` for the pattern — **do not import from or edit that file**; port the logic.
- `BasicAgent(Chatbot, NotificationMixin)` (bots/agent.py:29) provides notification helpers.
### Does NOT Exist
- ~~email enabled by default~~ — flag defaults to false.

## Implementation Notes
- Render from `Diary/Daily Notes/` synthesis; single-operator use.

## Acceptance Criteria
- [ ] Digests do NOT send unless `FIREFLIES_WIKI_EMAIL_ENABLED=true`.
- [ ] Content derives from compiled daily notes, not raw transcripts.
- [ ] No edit to `agents/fireflies_wiki.py`; `ruff`/`mypy` clean.

## Test Specification
```python
async def test_email_disabled_by_default(): ...
async def test_email_sends_when_enabled(): ...
```

### Completion Note

`nodes/email.py`: `run_email_digest(agent, toolkit, *, kind, window_days,
recipients, today=None) -> DigestOutcome` — ports the
`_run_digest`/`email_daily_meeting_digest`/`email_weekly_insights`
pattern from `agents/fireflies_wiki.py` (referenced only, never
imported/edited). Gated by `conf.FIREFLIES_WIKI_EMAIL_ENABLED` (default
`False`) as the very first check — `agent.send_email` is never even
constructed-toward when the flag is off. `build_digest_content()` reads
`Diary/Daily Notes/<date>.md` (this subsystem's own compiled synthesis,
Module 12) over the lookback window and extracts each day's
`## Daily Summary` section — never touches `Raw/` at all. Uses
`agent.send_email()` + `agent.notification_succeeded()`
(`NotificationMixin`, already mixed into `BasicAgent` → `Agent`) exactly
as the reference agent does, including the same "never raises, read the
result back" discipline (`status="partial"` vs `"ok"`).

Verified: `pytest packages/ai-parrot/tests/unit/test_wiki_kb_email.py`
(6 passed — disabled-by-default, sends when enabled, skips on no
recipients, skips on no content, content-from-compiled-notes-not-raw
with an explicit raw-transcript-string absence assertion, partial
status on provider failure); `ruff check` clean; `mypy` clean; full
wiki-kb suite (97 tests) stays green.
