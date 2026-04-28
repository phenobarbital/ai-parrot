# TASK-908: Wire reranker + parent searcher factories into BotManager.create_bot

**Feature**: FEAT-133 — DB-Persisted Reranker & Parent-Searcher Config for AI Bots
**Spec**: `sdd/specs/bot-reranker-and-parent-searcher-config.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-905, TASK-906, TASK-907
**Assigned-to**: unassigned

---

## Context

The factories (TASK-905, TASK-906) and the `BotModel` fields (TASK-907) only
take effect when `BotManager._load_database_bots` actually invokes them.
This task threads the factories into the bot-construction sequence,
respecting the documented ordering: reranker BEFORE construction;
parent_searcher AFTER `bot.configure(app)` because it needs `bot.store`.
Implements spec section 3 / Module 5 plus the "Order of operations" block
in spec §2.

---

## Scope

- In `packages/ai-parrot/src/parrot/manager/manager.py` (within
  `_load_database_bots`, around lines 314–392):
  1. Before `bot_instance = class_name(...)`: build
     `reranker = create_reranker(bot_model.reranker_config)`.
  2. Pass `reranker=reranker` and
     `expand_to_parent=bool(bot_model.parent_searcher_config.get("expand_to_parent", False))`
     as kwargs to the bot constructor.
  3. After `await bot_instance.configure(app)`:
     - Build `parent_searcher = create_parent_searcher(bot_model.parent_searcher_config, store=bot_instance.store)`.
     - If `parent_searcher is not None`, set
       `bot_instance.parent_searcher = parent_searcher`.
  4. If `reranker` is an `LLMReranker` whose `client` was a placeholder
     (i.e., `bot_llm_client` was not available pre-construction), patch it
     post-construction:
     `if isinstance(reranker, LLMReranker) and reranker.client is None: reranker.client = bot_instance.llm_client` —
     OR (preferred) re-call the factory with
     `bot_llm_client=bot_instance.llm_client` after `configure()`. Pick one
     and document it.
- Add a single INFO log (per Q2 in spec §8) when either feature is active:
  `self.logger.info("Bot %s: reranker=%s, parent_searcher=%s", name, type(reranker).__name__ if reranker else None, type(parent_searcher).__name__ if parent_searcher else None)`.
- Catch `ConfigError` raised by either factory and log a clear error before
  re-raising (or letting the existing `except Exception` handler at line 389
  capture it). Fail-loud per spec G5 / AC8.

**NOT in scope**:
- DDL / model field changes (TASK-904, TASK-907).
- Handler endpoint changes (TASK-910).
- Integration tests (TASK-911).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | Inject factories into `_load_database_bots` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (to add at top of manager.py)
```python
from parrot.rerankers.factory import create_reranker
from parrot.stores.parents.factory import create_parent_searcher
# ConfigError is already importable from parrot.exceptions if not present
from parrot.exceptions import ConfigError
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/manager/manager.py:298
class BotManager:
    async def _load_database_bots(self, app: web.Application) -> None: ...

# Existing construction call lives at packages/ai-parrot/src/parrot/manager/manager.py:331-375
bot_instance = class_name(                       # line 331
    chatbot_id=bot_model.chatbot_id,
    name=bot_model.name,
    ...
    vector_store_config=bot_model.vector_store_config,    # line 356 — pattern to mirror
    ...
)
await bot_instance.configure(app)                # line 379

# packages/ai-parrot/src/parrot/bots/abstract.py:397-408 — kwargs the bot reads
self.reranker            = kwargs.get('reranker', None)            # 398
self.rerank_oversample_factor = int(kwargs.get('rerank_oversample_factor', 4))  # 399-401
self.parent_searcher     = kwargs.get('parent_searcher', None)     # 407
self.expand_to_parent    = bool(kwargs.get('expand_to_parent', False))          # 408

# bot_instance.store becomes available only AFTER configure() — DO NOT read
# it before. (See spec §2 R1.)
```

### Does NOT Exist
- ❌ Any kwarg parsing for `reranker_config` or `parent_searcher_config` in
  `BotManager` today — to be added.
- ❌ A factory-call site for either reranker or parent searcher in the
  manager — to be added.
- ❌ `bot.store` is NOT available before `await bot.configure(app)`.

---

## Implementation Notes

### Pseudocode (from spec §3 Module 5)
```python
from parrot.rerankers.factory import create_reranker
from parrot.stores.parents.factory import create_parent_searcher
from parrot.rerankers import LLMReranker  # for the LLM-client patch branch

# 1. Build reranker BEFORE bot construction (no store dependency).
try:
    reranker = create_reranker(
        bot_model.reranker_config,
        bot_llm_client=None,  # patched post-construction if type=llm
    )
except ConfigError as exc:
    self.logger.error(
        "Bot %s: invalid reranker_config: %s", bot_model.name, exc
    )
    raise

bot_instance = class_name(
    ...,
    vector_store_config=bot_model.vector_store_config,
    reranker=reranker,
    expand_to_parent=bool(
        bot_model.parent_searcher_config.get("expand_to_parent", False)
    ),
    ...,
)

await bot_instance.configure(app)

# 2. Patch LLM reranker client now that bot.llm_client exists.
if isinstance(reranker, LLMReranker) and reranker.client is None:
    reranker.client = bot_instance.llm_client

# 3. Build parent_searcher AFTER configure() (needs bot.store).
try:
    parent_searcher = create_parent_searcher(
        bot_model.parent_searcher_config,
        store=bot_instance.store,
    )
except ConfigError as exc:
    self.logger.error(
        "Bot %s: invalid parent_searcher_config: %s", bot_model.name, exc
    )
    raise

if parent_searcher is not None:
    bot_instance.parent_searcher = parent_searcher

self.logger.info(
    "Bot %s: reranker=%s, parent_searcher=%s",
    bot_model.name,
    type(reranker).__name__ if reranker else None,
    type(parent_searcher).__name__ if parent_searcher else None,
)
```

### Key Constraints
- Order MUST be: factory(reranker) → ctor → configure() → factory(parent_searcher).
- The existing top-level `except Exception` at line 389 currently swallows
  errors as `self.logger.error("Failed to load database bot ...")`. Per spec
  AC8, a `ConfigError` from either factory MUST be visible to the operator;
  either re-raise or log at `error` with the exception message — both are
  acceptable as long as the bot is NOT silently registered without the
  configured features.
- Do NOT mutate `bot_instance.expand_to_parent` after construction — it must
  arrive via the constructor kwarg. The `parent_searcher_config["expand_to_parent"]`
  read happens BEFORE construction; this is intentional (spec §2 R3).

### Patch decision (LLM client)
Pick ONE of:
- (a) Pass `bot_llm_client=None` pre-construction; after configure, set
  `reranker.client = bot_instance.llm_client` if needed.
- (b) Build the LLM reranker AFTER configure (parallel to parent_searcher).

(a) is simpler and matches the spec's pseudocode. Document the choice in the
completion note. (b) requires shifting the reranker construction to after
configure() — only do this if (a) breaks the constructor contract.

### References in Codebase
- `parrot/manager/manager.py:298-396` — current `_load_database_bots`.
- `parrot/bots/abstract.py:397-408` — kwargs the bot reads.
- `parrot/bots/abstract.py:1734-1771` — already-wired reranker + parent
  retrieval call sites (no edits needed there).

---

## Acceptance Criteria

- [ ] Imports of `create_reranker` and `create_parent_searcher` added at top
  of `manager.py`.
- [ ] Reranker is built BEFORE `bot_instance = class_name(...)` and passed
  via kwargs.
- [ ] `expand_to_parent` is read from `bot_model.parent_searcher_config`
  and forwarded as a constructor kwarg.
- [ ] Parent searcher is built AFTER `await bot_instance.configure(app)` and
  assigned to `bot_instance.parent_searcher` when not None.
- [ ] LLM reranker client patch branch exists (option a or b documented).
- [ ] A single INFO log surfaces the resolved reranker / parent_searcher
  class names (or None) per loaded bot.
- [ ] `ConfigError` from either factory does NOT silently fall through —
  the bot is not registered as if the feature were configured-but-broken
  (raise or log-and-skip; document the choice).
- [ ] Behavior for empty configs is identical to today (regression-safe).
- [ ] `ruff check packages/ai-parrot/src/parrot/manager/manager.py` clean.
- [ ] `mypy packages/ai-parrot/src/parrot/manager/manager.py` clean.
- [ ] Maps to spec AC5 + AC8.

---

## Test Specification

> Lightweight unit-style test using a stub `BotModel` and a fake
> `class_name`. End-to-end behavior is exercised by TASK-911.

```python
# packages/ai-parrot/tests/manager/test_botmanager_factory_wiring.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_factories_invoked_in_correct_order(monkeypatch):
    """reranker built BEFORE construction, parent_searcher AFTER configure."""
    call_order: list[str] = []

    def fake_create_reranker(cfg, *, bot_llm_client=None):
        call_order.append("reranker")
        return MagicMock(name="reranker")

    def fake_create_parent_searcher(cfg, *, store):
        call_order.append("parent_searcher")
        assert store is not None, "parent_searcher must see configured store"
        return MagicMock(name="parent_searcher")

    monkeypatch.setattr(
        "parrot.manager.manager.create_reranker", fake_create_reranker
    )
    monkeypatch.setattr(
        "parrot.manager.manager.create_parent_searcher", fake_create_parent_searcher
    )

    fake_bot = MagicMock()
    fake_bot.configure = AsyncMock(
        side_effect=lambda app: call_order.append("configure")
    )
    fake_bot.store = MagicMock()
    fake_bot.llm_client = MagicMock()

    # ... build a fake bot_model with non-empty configs and inject fake_bot
    # via patching `class_name(...)`. Concrete plumbing is left to the agent.

    # Assert order:
    # call_order == ["reranker", "configure", "parent_searcher"]
```

```python
@pytest.mark.asyncio
async def test_unknown_reranker_type_does_not_register(monkeypatch):
    """ConfigError must surface — bot is NOT silently registered."""
    from parrot.exceptions import ConfigError

    def boom(cfg, *, bot_llm_client=None):
        raise ConfigError("unknown reranker type 'magic'")

    monkeypatch.setattr("parrot.manager.manager.create_reranker", boom)
    # build BotModel with reranker_config={"type": "magic"} and assert
    # the bot is not in BotManager._bots (or that the exception propagates).
```

---

## Agent Instructions

1. Read spec section 3 (Module 5) and the "Order of operations" block
   in section 2.
2. Verify the Codebase Contract — re-read `manager.py:298-396` and
   `abstract.py:397-408` if they have moved.
3. Confirm TASK-905, TASK-906, TASK-907 are in `tasks/completed/`.
4. Update `tasks/.index.json` → `"in-progress"`.
5. Implement the wiring per pseudocode.
6. Add the two unit tests above (skeleton; flesh out the BotModel fixture).
7. Run `pytest packages/ai-parrot/tests/manager/test_botmanager_factory_wiring.py -v`.
8. `ruff` + `mypy` clean.
9. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any (especially the LLM-client
patch decision: option (a) or (b)).
