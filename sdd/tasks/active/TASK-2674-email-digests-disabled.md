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
