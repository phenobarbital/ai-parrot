---
type: Wiki Overview
title: 'Feature Specification: BotManager Hot Registration — NAV-6239 Confirmation'
id: doc:sdd-specs-botmanager-hot-registration-nav6239-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When a new bot is created via the CRUD handler (`PUT /api/v1/bots`), the
  bot was
relates_to:
- concept: mod:parrot.handlers.bots
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: BotManager Hot Registration — NAV-6239 Confirmation

**Feature ID**: FEAT-254
**Date**: 2026-06-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Jira**: NAV-6239

---

## 1. Motivation & Business Requirements

> Confirm that the "Service Restart Required to Train and Use New Bot" bug (NAV-6239)
> is resolved, then lock the behaviour in a regression test and close the ticket.

### Problem Statement

When a new bot is created via the CRUD handler (`PUT /api/v1/bots`), the bot was
reportedly unavailable in `BotManager` until the server was restarted.  The
reporter believes the fix is already in place but needs formal confirmation plus a
Jira comment so the ticket can be closed.

**Root-cause triage (completed during research phase):**

`ChatbotHandler._put_database` (line 863, `packages/ai-parrot-server/src/parrot/handlers/bots.py`)
already calls `_register_bot_into_manager` (line 892), which constructs a bot
instance and calls `manager.add_bot(bot)` (line 599) before returning the HTTP
201 response.  Similarly, `_post_database` (line 1127) removes the old instance
via `manager.remove_bot` and re-registers the updated one.  The `delete` handler
calls `manager.remove_bot` on successful DB deletion.

The implementation therefore already provides hot registration without restart.
What is **missing** is:

1. A dedicated regression test that verifies the immediate-availability contract.
2. A Jira comment on NAV-6239 confirming the fix with evidence (test name + file).

### Goals

- Write a focused unit test (`test_put_database_registers_bot_immediately`) that
  proves a bot created via `_put_database` is immediately available via
  `manager._bots` without any server restart or secondary call.
- Write a complementary test for `_post_database` (update) and `delete` hot
  de-registration to lock the full lifecycle.
- Post a Jira comment on NAV-6239 that cites the test file and summarises the
  finding.

### Non-Goals (explicitly out of scope)

- Implementing a new reload/hot-swap endpoint — the existing flow already works.
- Changing `BotManager.load_bots` or `_load_database_bots` startup behaviour
  (that is FEAT-042 territory).
- Integration / end-to-end tests against a live DB or running server.

---

## 2. Architectural Design

### Overview

No new production code is required.  The feature adds **regression tests** to
`packages/ai-parrot/tests/test_chatbot_handler.py` (the existing test module for
`ChatbotHandler`) that exercise the three paths already implemented:

| HTTP verb | Handler method | BotManager side-effect |
|-----------|---------------|------------------------|
| PUT       | `_put_database` | `add_bot` called → bot in `_bots` |
| POST (update) | `_post_database` | `remove_bot` + `add_bot` called |
| DELETE    | `delete`        | `remove_bot` called → bot gone |

A Jira comment is posted via the existing `JiraToolkit` / `gh` CLI as the final
task so the ticket is closed with a recorded audit trail.

### Component Diagram

```
test_chatbot_handler.py
    │
    ├── FakeBotManager (already exists in test file, line 139)
    │       ├── add_bot(bot) → _bots[name] = bot
    │       └── remove_bot(name) → del _bots[name]
    │
    ├── FakeBotModel (already exists, line 20)
    │
    └── ChatbotHandler._put_database
            │
            └── _register_bot_into_manager → manager.add_bot(bot)
                                              (bots.py line 599)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ChatbotHandler._put_database` | tested | `packages/ai-parrot-server/src/parrot/handlers/bots.py:863` |
| `ChatbotHandler._post_database` | tested | same file, line 1127 |
| `ChatbotHandler.delete` | tested | same file, line 1258 |
| `ChatbotHandler._register_bot_into_manager` | tested indirectly | line 516 |
| `FakeBotManager` | extended / reused | `packages/ai-parrot/tests/test_chatbot_handler.py:139` |
| `FakeBotModel` | extended / reused | same file, line 20 |
| Jira REST API / `gh` CLI | one-shot comment | NAV-6239 confirmation |

### Data Models

No new data models.

### New Public Interfaces

No new public interfaces — tests only.

---

## 3. Module Breakdown

### Module 1: Regression tests for hot registration

- **Path**: `packages/ai-parrot/tests/test_chatbot_handler.py`
- **Responsibility**: Add three new `pytest` async test functions:
  - `test_put_database_registers_bot_immediately` — PUT creates bot → available in `FakeBotManager._bots` without restart.
  - `test_post_database_reregisters_updated_bot` — POST update → old instance removed, new instance added.
  - `test_delete_database_removes_bot_from_manager` — DELETE → bot absent from `FakeBotManager._bots`.
- **Depends on**: Existing `FakeBotManager`, `FakeBotModel`, handler setup in the same file.

### Module 2: Jira comment confirming the fix

- **Path**: N/A (CLI task, no file created)
- **Responsibility**: Post a comment on NAV-6239 with:
  - Summary of triage findings (fix already present since `_put_database` calls
    `_register_bot_into_manager → manager.add_bot`).
  - Reference to test file and test names added in Module 1.
  - Recommendation to close/resolve the ticket.
- **Depends on**: Module 1 (tests must pass before commenting).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_put_database_registers_bot_immediately` | Module 1 | PUT creates DB bot → `manager._bots[name]` is populated right away |
| `test_post_database_reregisters_updated_bot` | Module 1 | POST updates bot → old instance gone, new instance present |
| `test_delete_database_removes_bot_from_manager` | Module 1 | DELETE removes bot → `manager._bots` no longer contains the bot |

### Integration Tests

None (out of scope — no live DB needed).

### Test Data / Fixtures

The tests must reuse the `FakeBotManager` and `FakeBotModel` classes already
present in `packages/ai-parrot/tests/test_chatbot_handler.py` at lines 20 and 139.
Minimal additional fakes are needed for `create_reranker` and `create_parent_searcher`
(mock to return `None`).

Key patch targets (all in `parrot.handlers.bots`):

```python
# Patch DB connection context manager
"parrot.handlers.bots.BotModel"
# Patch reranker/parent_searcher factories
"parrot.handlers.bots.create_reranker"
"parrot.handlers.bots.create_parent_searcher"
# Patch LLMReranker isinstance check
"parrot.handlers.bots.LLMReranker"
```

Minimal test scaffold:

```python
@pytest.mark.asyncio
async def test_put_database_registers_bot_immediately():
    """Bot created via PUT /api/v1/bots is immediately in BotManager._bots."""
    manager = FakeBotManager()
    handler = _make_handler(manager)

    with patch("parrot.handlers.bots.BotModel") as MockModel, \
         patch("parrot.handlers.bots.create_reranker", return_value=None), \
         patch("parrot.handlers.bots.create_parent_searcher", return_value=None), \
         patch("parrot.handlers.bots.LLMReranker", new_callable=lambda: type("X", (), {})):
        instance = FakeBotModel(name="my_new_bot")
        MockModel.return_value = instance
        MockModel.Meta = type("Meta", (), {"connection": None})()

        await handler._put_database({"name": "my_new_bot", "bot_class": "BasicBot"})

    assert "my_new_bot" in manager._bots, (
        "Bot must be in BotManager._bots immediately after PUT — no restart required"
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `test_put_database_registers_bot_immediately` passes — bot is in `manager._bots` right after `_put_database` returns.
- [ ] `test_post_database_reregisters_updated_bot` passes — old bot removed, new bot present after `_post_database`.
- [ ] `test_delete_database_removes_bot_from_manager` passes — bot absent from `manager._bots` after `delete`.
- [ ] All three tests run in the existing suite without real DB / Redis: `pytest packages/ai-parrot/tests/test_chatbot_handler.py -v -k "hot_registration or registers_bot or reregisters or removes_bot"` (green).
- [ ] Full test suite (`pytest packages/ai-parrot/tests/test_chatbot_handler.py -v`) still green (no regressions).
- [ ] Jira comment posted on NAV-6239 citing test names + file path + conclusion "fix confirmed, no restart required".
- [ ] No ruff linting errors on modified test file.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# In test file — already present
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import pytest

# Handler under test
# packages/ai-parrot-server/src/parrot/handlers/bots.py
from parrot.handlers.bots import ChatbotHandler  # verified
```

### Existing Class Signatures

```python
# packages/ai-parrot-server/src/parrot/handlers/bots.py

class ChatbotHandler:
    # line 516
    async def _register_bot_into_manager(self, bot_data: dict, app) -> Optional[AbstractBot]:
        ...
        manager.add_bot(bot)        # line 599
        return bot                  # line 614

    # line 863
    async def _put_database(self, payload: dict):
        ...
        bot_instance = await self._register_bot_into_manager(bot_data, self.request.app)  # line 892
        ...

    # line 1127
    async def _post_database(self, agent: BotModel, payload: dict):
        ...
        manager.remove_bot(agent.name)     # line 1153
        await self._register_bot_into_manager(bot_data, self.request.app)  # line 1161
        ...

    # line 1258
    async def delete(self):
        ...
        manager.remove_bot(agent_name)     # line 1292 (factory), ~1338 (db)
        ...
```

```python
# packages/ai-parrot-server/src/parrot/manager/manager.py

class BotManager:
    _bots: Dict[str, AbstractBot]   # line ~65 — dict keyed by bot name

    def add_bot(self, bot: AbstractBot) -> None:   # line 654
        self._bots[bot.name] = bot
        self._botdef[bot.name] = bot.__class__

    def remove_bot(self, name: str) -> None:       # line 800
        del self._bots[name]
        self._bot_expiration.pop(name, None)

    def create_bot(self, class_name=None, name=None, **kwargs) -> AbstractBot:  # line 646
        ...

    def get_bot_class(self, name: str):  # line 184 (approx)
        ...
```

```python
# packages/ai-parrot/tests/test_chatbot_handler.py — REUSE THESE

class FakeBotModel:               # line 20
    Meta: class with connection = None
    name: str
    bot_class: str
    enabled: bool
    async def insert(self) -> None: ...
    async def update(self) -> None: ...
    async def delete(self) -> None: ...
    def to_bot_config(self) -> dict: ...
    def to_dict(self) -> dict: ...
    def set(self, key, val) -> None: ...

class FakeBotManager:             # line 139
    _bots: Dict[str, Any]
    def add_bot(self, bot) -> None: self._bots[bot.name] = bot
    def remove_bot(self, name) -> None: self._bots.pop(name, None)
    def create_bot(self, class_name=None, name=None, **kwargs): ...
    def get_bot_class(self, name): ...
```

### Integration Points

| New Code | Connects To | Via | Verified At |
|---|---|---|---|
| New tests | `ChatbotHandler._put_database` | direct call | `bots.py:863` |
| New tests | `ChatbotHandler._post_database` | direct call | `bots.py:1127` |
| New tests | `ChatbotHandler.delete` | direct call (via `_delete_database`) | `bots.py:1258` |
| New tests | `FakeBotManager._bots` | dict assertion | `test_chatbot_handler.py:144` |

### Does NOT Exist (Anti-Hallucination)

- ~~`BotManager.reload_bot()`~~ — does not exist; hot-registration uses `add_bot` directly.
- ~~`ChatbotHandler.register_bot()`~~ — not a real public method; use `_register_bot_into_manager`.
- ~~`manager.get_bot("name")` returning `None` for a newly created bot~~ — after `add_bot`, `manager._bots["name"]` is set; `get_bot` without `new=True` returns it.
- ~~`BotModel.save()`~~ — does not exist; use `await model.insert()` for create, `await model.update()` for update.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror the style of existing tests in `test_chatbot_handler.py` — use
  `FakeBotModel`, `FakeBotManager`, `AsyncMock`, `patch` context managers.
- The `_make_handler` helper (if already defined in the file) should be reused;
  if not, follow the construction pattern used by existing tests.
- Patch `create_reranker` and `create_parent_searcher` to return `None` so no
  real reranker/store objects are needed.
- Patch the `BotModel` class-level `Meta.connection` and the DB context manager
  (`async with await db(request) as conn`) using `AsyncMock` context manager.
- Use `pytest.mark.asyncio` — all handler methods are `async`.

### Known Risks / Gotchas

- `_register_bot_into_manager` patches `LLMReranker` via an `isinstance` check.
  Patch `parrot.handlers.bots.LLMReranker` to a stub class so `isinstance(None, LLMRerankerStub)` is `False` by default.
- The DB context manager in `_put_database` is `async with await db(self.request) as conn`.
  This means `self.handler(request)` must be awaitable AND itself return an async
  context manager.  The existing tests in the file should already have a pattern for this.
- `_post_database` receives a `BotModel` *instance* (not just a dict), and calls
  `agent.set(key, val)` + `await agent.update()`.  Use `FakeBotModel` to satisfy this.
- `ChatbotHandler._provision_vector_store` is called inside `_put_database` after
  `_register_bot_into_manager`.  Patch it to return `{"status": "none"}` to avoid
  async store provisioning.

### External Dependencies

No new packages required — all test utilities already available (`pytest`, `pytest-asyncio`,
`unittest.mock`).

---

## 8. Open Questions

- [x] Is the fix already in production code? — *Resolved during research*: Yes. `_put_database` calls `_register_bot_into_manager → manager.add_bot` at line 892 of `bots.py`. No production code change needed.
- [x] Which CRUD handler creates database bots? — *Resolved*: `ChatbotHandler._put_database` via `PUT /api/v1/bots` (`packages/ai-parrot-server/src/parrot/handlers/bots.py:863`).
- [ ] Should the Jira comment be posted programmatically (JiraToolkit) or via the Jira web UI? — *Owner: Jesus Lara*: Use JiraToolkit / `jira` CLI if available; otherwise provide the comment text for manual posting.

---

## Worktree Strategy

- **Isolation unit**: per-spec (single worktree, sequential tasks).
- **Parallelism**: Module 1 (tests) must complete and pass before Module 2 (Jira comment); no parallel tasks.
- **Cross-feature dependencies**: none.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-23 | Claude (sdd-research) | Initial draft — bug confirmed fixed, tests + Jira comment scoped |
