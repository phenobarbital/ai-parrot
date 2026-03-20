# TASK-020: MentionBuilder

**Feature**: FEAT-010 — TelegramCrewTransport
**Spec**: `sdd/specs/telegram-crew-transport.spec.md`
**Status**: in-progress
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-017
**Assigned-to**: claude-session

---

## Context

This task implements Module 5 from the spec. `MentionBuilder` provides helper utilities for constructing `@mention` strings used in all crew communication. Mentions are the addressing mechanism for routing messages between agents and humans.

Implements spec Section 3, Module 5.

---

## Scope

- Implement `mention_from_username(username: str)` — returns `@username`
- Implement `mention_from_user_id(user_id: int, display_name: str)` — returns Telegram HTML deep-link mention
- Implement `mention_from_card(card: AgentCard)` — returns `@username` from an AgentCard
- Implement `format_reply(mention: str, text: str)` — formats a response with mention prefix

**NOT in scope**: Message routing logic (TASK-022), registry operations (TASK-018).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/crew/mention.py` | CREATE | MentionBuilder utilities |
| `tests/test_telegram_crew/test_mention.py` | CREATE | Unit tests |

---

## Implementation Notes

### Key Constraints
- Strip leading `@` if already present in username input
- HTML mention format: `<a href="tg://user?id={user_id}">{display_name}</a>`
- `format_reply()` should prepend the mention to the text with a newline separator
- Keep functions as module-level functions (no class needed — simple utility module)
- Reuse existing `extract_query_from_mention` from `parrot/integrations/telegram/` for consistency

### References in Codebase
- `parrot/integrations/telegram/filters.py` — existing `BotMentionedFilter` and mention extraction

---

## Acceptance Criteria

- [ ] `mention_from_username("bot")` returns `"@bot"`
- [ ] `mention_from_username("@bot")` also returns `"@bot"` (idempotent)
- [ ] `mention_from_user_id()` returns valid HTML mention
- [ ] `mention_from_card()` returns `@username` from AgentCard
- [ ] `format_reply()` prepends mention to text
- [ ] All tests pass: `pytest tests/test_telegram_crew/test_mention.py -v`

---

## Test Specification

```python
# tests/test_telegram_crew/test_mention.py
import pytest
from datetime import datetime, timezone
from parrot.integrations.telegram.crew.mention import (
    mention_from_username,
    mention_from_user_id,
    mention_from_card,
    format_reply,
)
from parrot.integrations.telegram.crew.agent_card import AgentCard


class TestMentionBuilder:
    def test_from_username(self):
        assert mention_from_username("test_bot") == "@test_bot"

    def test_from_username_idempotent(self):
        assert mention_from_username("@test_bot") == "@test_bot"

    def test_from_user_id(self):
        result = mention_from_user_id(12345, "TestUser")
        assert "12345" in result
        assert "TestUser" in result

    def test_from_card(self):
        card = AgentCard(
            agent_id="a1",
            agent_name="Test",
            telegram_username="test_bot",
            telegram_user_id=123,
            model="test",
            joined_at=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        assert mention_from_card(card) == "@test_bot"

    def test_format_reply(self):
        result = format_reply("@user", "Here is your answer")
        assert result.startswith("@user")
        assert "Here is your answer" in result
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-crew-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-017 (AgentCard) is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-020-mention-builder.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented 4 module-level utility functions: `mention_from_username` (idempotent @ handling), `mention_from_user_id` (HTML deep-link), `mention_from_card` (from AgentCard), `format_reply` (mention + newline + text). All 9 unit tests pass.

**Deviations from spec**: none
