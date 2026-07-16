---
type: Wiki Overview
title: 'TASK-1616: Regression Tests — BotManager Hot Registration (NAV-6239)'
id: doc:sdd-tasks-completed-task-1616-hot-registration-regression-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: NAV-6239 reported that newly created database-backed bots required a server
relates_to:
- concept: mod:parrot.handlers.bots
  rel: mentions
---

# TASK-1616: Regression Tests — BotManager Hot Registration (NAV-6239)

**Feature**: FEAT-254 — BotManager Hot Registration — NAV-6239 Confirmation
**Spec**: `sdd/specs/botmanager-hot-registration-nav6239.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

NAV-6239 reported that newly created database-backed bots required a server
restart before they were usable.  Code review during research (FEAT-254) confirmed
that `ChatbotHandler._put_database` already calls `_register_bot_into_manager →
manager.add_bot(bot)` at line 892 of
`packages/ai-parrot-server/src/parrot/handlers/bots.py`, which immediately
registers the bot in `BotManager._bots` without any restart.

This task locks that behaviour in a regression suite so future refactors cannot
silently break hot registration.

Implements **Spec §3 Module 1** and **Spec §4 Unit Tests**.

---

## Scope

Add three new `pytest.mark.asyncio` test functions to the **existing** test
module `packages/ai-parrot/tests/test_chatbot_handler.py`:

1. `test_put_database_registers_bot_immediately` — verifies PUT creates a bot
   that is present in `FakeBotManager._bots` right after `_put_database` returns.
2. `test_post_database_reregisters_updated_bot` — verifies POST (update) removes
   the old instance and adds the new one in `FakeBotManager._bots`.
3. `test_delete_database_removes_bot_from_manager` — verifies DELETE removes the
   bot from `FakeBotManager._bots`.

**NOT in scope**:
- Modifying production code in `bots.py` or `manager.py`.
- Integration tests against a live database or running server.
- Any Jira API calls (that is TASK-1617).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_chatbot_handler.py` | MODIFY | Append the three regression test functions |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use ONLY the imports, classes, and methods listed here.
> Verify before referencing anything not listed.

### Verified Imports

```python
# Already in test_chatbot_handler.py — do NOT re-import at module level
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
# Async test support — already used in the file
import pytest_asyncio  # or: @pytest.mark.asyncio with asyncio_mode=auto
```

### Existing Signatures to Use

```python
# packages/ai-parrot/tests/test_chatbot_handler.py

class FakeBotModel:  # line 20
    """Minimal BotModel stand-in."""
    class Meta:
        connection = None
    def __init__(self, **kwargs): ...
    name: str          # set via kwargs
    bot_class: str     # default "BasicBot"
    enabled: bool      # default True
    async def insert(self) -> None: ...
    async def update(self) -> None: ...
    async def delete(self) -> None: ...
    def to_bot_config(self) -> dict: ...   # returns {"name": self.name, "description": ...}
    def set(self, key: str, val) -> None: ...

class FakeBotManager:  # line 139
    """Minimal BotManager stand-in."""
    def __init__(self, registry=None): ...
    _bots: Dict[str, Any]              # dict keyed by bot name
    def add_bot(self, bot) -> None:    # self._bots[bot.name] = bot
        ...
    def remove_bot(self, name: str) -> None:  # self._bots.pop(name, None)
        ...
    def create_bot(self, class_name=None, name=None, **kwargs): ...
    def get_bot_class(self, name: str): ...  # returns MagicMock
```

```python
# packages/ai-parrot-server/src/parrot/handlers/bots.py

class ChatbotHandler:
    async def _put_database(self, payload: dict): ...  # line 863
    async def _post_database(self, agent: BotModel, payload: dict): ...  # line 1127
    async def delete(self) -> ...: ...  # line 1258
    async def _register_bot_into_manager(self, bot_data: dict, app) -> ...: ...  # line 516
    async def _provision_vector_store(self, bot, vector_store_config: dict) -> dict: ...  # line 921
    # Handler is constructed and requires: self._manager, self._session, self.request, self.handler
```

### Patch Targets

```python
# All in module 'parrot.handlers.bots':
"parrot.handlers.bots.BotModel"              # swap with FakeBotModel or MagicMock
"parrot.handlers.bots.create_reranker"       # return None
"parrot.handlers.bots.create_parent_searcher"# return None
"parrot.handlers.bots.LLMReranker"           # stub class so isinstance(...) is False
```

### Does NOT Exist

- ~~`BotManager.reload_bot()`~~ — does not exist; hot-reg uses `add_bot`.
- ~~`ChatbotHandler.register_bot()`~~ — not a real method; use `_register_bot_into_manager`.
- ~~`BotModel.save()`~~ — use `await model.insert()` (create) or `await model.update()` (update).
- ~~`FakeBotManager.get(name)`~~ — not a method; check `manager._bots[name]` directly.
- ~~`ChatbotHandler._delete_database()`~~ — look at the actual `delete()` method body.

---

## Implementation Notes

### How to construct a ChatbotHandler in tests

Look at how existing tests in `test_chatbot_handler.py` instantiate the handler.
The handler needs `self._manager`, `self.request`, `self.handler` (DB factory),
`self._session`, and `self._registry`.

Typical pattern (adapt from existing tests):

```python
def _make_handler(manager):
    handler = ChatbotHandler.__new__(ChatbotHandler)
    handler._manager = manager
    handler._registry = None
    handler._session = MagicMock()
    handler.logger = MagicMock()
    # Mock the DB connection as async context manager
    conn = AsyncMock()
    db_cm = AsyncMock()
    db_cm.__aenter__ = AsyncMock(return_value=conn)
    db_cm.__aexit__ = AsyncMock(return_value=False)
    db_factory = AsyncMock(return_value=db_cm)
    handler.handler = db_factory
    handler.request = MagicMock()
    handler.request.app = MagicMock()
    return handler
```

### Patching the DB BotModel for `_put_database`

`_put_database` does:
```python
BotModel.Meta.connection = conn
bot_model = BotModel(**payload)
await bot_model.insert()
bot_data = bot_model.to_bot_config()
```

Patch `parrot.handlers.bots.BotModel` to be a class that returns a
`FakeBotModel` instance when called:

```python
with patch("parrot.handlers.bots.BotModel", FakeBotModel):
    ...
```

### Patching `_provision_vector_store`

Patch it on the instance to return `{"status": "none"}` so the test doesn't
need a real vector store:

```python
handler._provision_vector_store = AsyncMock(return_value={"status": "none"})
```

### `_post_database` receives an already-loaded BotModel instance

Create a `FakeBotModel(name="existing_bot")` and pre-populate `manager._bots`
with a sentinel:

```python
manager._bots["existing_bot"] = MagicMock(name="existing_bot")
```

Then call `_post_database(fake_model, {})` and verify the sentinel is gone and
a new bot is in `_bots`.

### For `delete`

`delete()` reads the agent name from the request path (via
`self._agent_name_from_request()`).  Check how existing delete tests stub this.
Alternatively, patch `_agent_name_from_request` on the instance:

```python
handler._agent_name_from_request = MagicMock(return_value="my_bot")
```

Then patch `_get_db_agent` to return a `FakeBotModel(name="my_bot")`.

### Key Constraints

- All three new tests must be `async def` with `@pytest.mark.asyncio`.
- No real DB, no real Redis, no real LLM client.
- Use only `unittest.mock` — no third-party mock libraries.
- Tests must be self-contained (no shared state between them).
- Add clear assertion messages so failures are readable without a debugger.

### References in Codebase

- `packages/ai-parrot/tests/test_chatbot_handler.py` — existing patterns to mirror
- `packages/ai-parrot-server/src/parrot/handlers/bots.py:863` — `_put_database` source
- `packages/ai-parrot-server/src/parrot/handlers/bots.py:1127` — `_post_database` source
- `packages/ai-parrot-server/src/parrot/handlers/bots.py:1258` — `delete` source
- `packages/ai-parrot-server/src/parrot/handlers/bots.py:516` — `_register_bot_into_manager` source

---

## Acceptance Criteria

- [ ] `test_put_database_registers_bot_immediately` passes: bot is in `manager._bots` after `_put_database`.
- [ ] `test_post_database_reregisters_updated_bot` passes: old bot removed, new bot present after `_post_database`.
- [ ] `test_delete_database_removes_bot_from_manager` passes: bot absent from `manager._bots` after `delete`.
- [ ] Full test file still green: `pytest packages/ai-parrot/tests/test_chatbot_handler.py -v`
- [ ] No ruff errors: `ruff check packages/ai-parrot/tests/test_chatbot_handler.py`

---

## Test Specification

```python
# Append to: packages/ai-parrot/tests/test_chatbot_handler.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# FEAT-254 — NAV-6239: BotManager hot registration regression tests
# ---------------------------------------------------------------------------

def _make_handler_feat254(manager):
    """Construct a minimal ChatbotHandler wired to a FakeBotManager."""
    from parrot.handlers.bots import ChatbotHandler
    handler = ChatbotHandler.__new__(ChatbotHandler)
    handler._manager = manager
    handler._registry = None
    handler._session = MagicMock()
    handler.logger = MagicMock()
    # DB connection — async context manager
    conn = AsyncMock()
    db_cm = AsyncMock()
    db_cm.__aenter__ = AsyncMock(return_value=conn)
    db_cm.__aexit__ = AsyncMock(return_value=False)
    db_factory = AsyncMock(return_value=db_cm)
    handler.handler = db_factory
    handler.request = MagicMock()
    handler.request.app = MagicMock()
    handler._provision_vector_store = AsyncMock(return_value={"status": "none"})
    return handler


@pytest.mark.asyncio
async def test_put_database_registers_bot_immediately():
    """PUT /api/v1/bots → bot available in BotManager._bots WITHOUT restart (NAV-6239)."""
    manager = FakeBotManager()
    handler = _make_handler_feat254(manager)

    LLMRerankerStub = type("LLMRerankerStub", (), {})

    with patch("parrot.handlers.bots.BotModel", FakeBotModel), \
         patch("parrot.handlers.bots.create_reranker", return_value=None), \
         patch("parrot.handlers.bots.create_parent_searcher", return_value=None), \
         patch("parrot.handlers.bots.LLMReranker", LLMRerankerStub):
        await handler._put_database({"name": "nav6239_bot", "bot_class": "BasicBot"})

    assert "nav6239_bot" in manager._bots, (
        "NAV-6239 regression: bot must be in BotManager._bots immediately "
        "after _put_database — no server restart should be required"
    )


@pytest.mark.asyncio
async def test_post_database_reregisters_updated_bot():
    """POST /api/v1/bots/{id} → old instance removed, new instance registered (NAV-6239)."""
    manager = FakeBotManager()
    old_sentinel = MagicMock()
    old_sentinel.name = "nav6239_bot"
    manager._bots["nav6239_bot"] = old_sentinel

    handler = _make_handler_feat254(manager)
    existing = FakeBotModel(name="nav6239_bot", bot_class="BasicBot")

    LLMRerankerStub = type("LLMRerankerStub", (), {})

    with patch("parrot.handlers.bots.BotModel", FakeBotModel), \
         patch("parrot.handlers.bots.create_reranker", return_value=None), \
         patch("parrot.handlers.bots.create_parent_searcher", return_value=None), \
         patch("parrot.handlers.bots.LLMReranker", LLMRerankerStub):
        await handler._post_database(existing, {})

    assert "nav6239_bot" in manager._bots, (
        "Updated bot must be re-registered in BotManager._bots after _post_database"
    )
    assert manager._bots["nav6239_bot"] is not old_sentinel, (
        "Old bot instance must be replaced — not just left in place"
    )


@pytest.mark.asyncio
async def test_delete_database_removes_bot_from_manager():
    """DELETE /api/v1/bots/{id} → bot absent from BotManager._bots (NAV-6239)."""
    manager = FakeBotManager()
    sentinel = MagicMock()
    sentinel.name = "nav6239_bot"
    manager._bots["nav6239_bot"] = sentinel

    handler = _make_handler_feat254(manager)
    handler._agent_name_from_request = MagicMock(return_value="nav6239_bot")
    handler._registry = FakeAgentRegistry()  # no registry hit

    existing = FakeBotModel(name="nav6239_bot")
    handler._get_db_agent = AsyncMock(return_value=existing)

    with patch("parrot.handlers.bots.BotModel", FakeBotModel):
        await handler.delete()

    assert "nav6239_bot" not in manager._bots, (
        "Deleted bot must be removed from BotManager._bots immediately"
    )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/botmanager-hot-registration-nav6239.spec.md`.
2. **Read `test_chatbot_handler.py`** — understand the existing handler construction
   patterns and the `FakeBotManager`/`FakeBotModel` helpers already defined.
3. **Read `bots.py` lines 863–919** (`_put_database`), **1127–1174** (`_post_database`),
   and **1258–1360** (`delete`) to confirm signatures haven't changed.
4. **Append** (do NOT overwrite) the three test functions to `test_chatbot_handler.py`.
5. Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_chatbot_handler.py -v`
6. Fix any failures until all three new tests are green.
7. Run: `ruff check packages/ai-parrot/tests/test_chatbot_handler.py`
8. Commit: `git commit -m "test: add NAV-6239 hot-registration regression tests (FEAT-254)"`
9. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude (sdd-worker / /sdd-start)
**Date**: 2026-06-26
**Notes**: All three regression tests were already implemented in commit `a07bdc879`
(`feat(NAV-6239): add hot-registration regression tests for BotManager`).
Verified all 28 tests pass (`pytest packages/ai-parrot/tests/test_chatbot_handler.py -v`)
and ruff reports zero linting errors. No new code needed — task is closed as verified.

**Deviations from spec**: none — tests are structurally equivalent to the spec scaffold,
organised in a `TestHotRegistrationRegression` class rather than top-level functions
(stylistic improvement consistent with the rest of the test file).
