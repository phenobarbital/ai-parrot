# TASK-843: Message ID tracking and per-chat message cache

**Feature**: FEAT-120 — Telegram Wrapper Rich Message Integration
**Spec**: `sdd/specs/telegram-wrapper-audio-files-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-842
**Assigned-to**: unassigned

---

## Context

Spec Module 2. After each agent response, the wrapper needs to store the user's
`message_id` and the bot's response `message_id` in `ConversationTurn.metadata`.
A per-chat `_message_id_cache` maps `message_id → text_snippet` for O(1) reply
lookups by the reply context task (TASK-844).

---

## Scope

- Add `_message_id_cache: Dict[int, Dict[int, str]]` instance attribute to `TelegramAgentWrapper.__init__`
  (maps `{chat_id: {message_id: text_snippet}}`)
- Implement `_cache_message_id(self, chat_id: int, message_id: int, text: str) -> None`
  helper — stores entry, enforces per-chat limit of 100 entries (evict oldest)
- Implement `async _store_telegram_metadata(self, memory, user_id, session_id, user_message_id, bot_message_id) -> None`
  helper — retrieves latest `ConversationTurn` from memory and injects
  `telegram_message_id` and `telegram_bot_message_id` into its `metadata` dict
- Update `handle_message` to:
  - Call `_cache_message_id` for the user's message (after receiving it)
  - Call `_cache_message_id` for the bot's response (after sending it)
  - Call `_store_telegram_metadata` after response is sent
- Write unit tests for cache storage, eviction, and metadata injection

**NOT in scope**: Reply context extraction (TASK-844), document handler (TASK-845),
updating `handle_photo`/`handle_voice` with message ID tracking (done in TASK-844/845)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Add `_message_id_cache`, new helpers, update `handle_message` |
| `tests/unit/test_telegram_message_ids_feat120.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py
from typing import Optional, List, Dict, Any    # line 1 area
import logging                                   # stdlib

# packages/ai-parrot/src/parrot/memory/abstract.py
from parrot.memory.abstract import ConversationTurn, ConversationHistory  # verified
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:62
class TelegramAgentWrapper:
    def __init__(self, agent, bot, config, ...):
        self.conversations: Dict[int, 'ConversationMemory'] = {}  # line 98
        self.logger: logging.Logger                                # line 99
        self._user_sessions: Dict[int, TelegramUserSession] = {}  # line 104
        self._agent_lock: asyncio.Lock = asyncio.Lock()            # line 112

# packages/ai-parrot/src/parrot/memory/abstract.py:10
@dataclass
class ConversationTurn:
    turn_id: str                                      # line 12
    user_id: str                                      # line 13
    user_message: str                                 # line 14
    assistant_response: str                           # line 15
    metadata: Dict[str, Any] = field(default_factory=dict)  # line 20

# packages/ai-parrot/src/parrot/memory/abstract.py:50
@dataclass
class ConversationHistory:
    turns: List[ConversationTurn] = field(default_factory=list)  # line 56
    def get_recent_turns(self, count: int = 5) -> List[ConversationTurn]:  # line 66

# packages/ai-parrot/src/parrot/memory/abstract.py:157
class ConversationMemory(ABC):
    async def get_history(
        self, user_id: str, session_id: str,
        chatbot_id: Optional[str] = None,
    ) -> Optional[ConversationHistory]:                # line 162

# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:1913
async def handle_message(self, message: Message) -> None:
    # line 1948: memory = self._get_or_create_memory(chat_id)
    # line 1949: session = self._get_user_session(message)
    # line 1997-2004: with telegram_chat_scope(chat_id): response = await self._invoke_agent(...)
    # line 2007: parsed = self._parse_response(response)
    # line 2013: await self._send_parsed_response(message, parsed)

# wrapper.py:2879
async def _send_parsed_response(self, message: Message, parsed: 'ParsedResponse') -> ...:
    # Returns a Message object (the sent response message)
```

### Does NOT Exist
- ~~`TelegramAgentWrapper._message_id_cache`~~ — does not exist yet; this task creates it
- ~~`TelegramAgentWrapper._reply_cache`~~ — no such attribute
- ~~`memory.update_last_turn()`~~ — no such method; must get history and mutate last turn in-place
- ~~`ConversationTurn.telegram_message_id`~~ — not a dataclass field; use `metadata` dict
- ~~`_send_parsed_response` returning message_id~~ — need to capture the return value

---

## Implementation Notes

### Pattern to Follow

Add `_message_id_cache` in `__init__` after `_agent_lock`:
```python
self._message_id_cache: Dict[int, Dict[int, str]] = {}
```

Cache helper with eviction:
```python
def _cache_message_id(self, chat_id: int, message_id: int, text: str) -> None:
    if chat_id not in self._message_id_cache:
        self._message_id_cache[chat_id] = {}
    cache = self._message_id_cache[chat_id]
    cache[message_id] = (text or "")[:200]
    # Evict oldest if over limit
    if len(cache) > 100:
        oldest_key = next(iter(cache))
        del cache[oldest_key]
```

Metadata storage:
```python
async def _store_telegram_metadata(
    self, memory, user_id: str, session_id: str,
    user_message_id: int, bot_message_id: int,
) -> None:
    try:
        history = await memory.get_history(user_id, session_id)
        if history and history.turns:
            last_turn = history.turns[-1]
            last_turn.metadata['telegram_message_id'] = user_message_id
            last_turn.metadata['telegram_bot_message_id'] = bot_message_id
    except Exception:
        self.logger.debug("Could not store Telegram message IDs in turn metadata", exc_info=True)
```

### Key Constraints
- `_store_telegram_metadata` must handle gracefully: memory returning `None`, empty turns list
- The metadata mutation works for `InMemoryConversation` (same object ref); Redis-backed memory
  may not persist it — the cache is the fallback (documented limitation in spec)
- Cache eviction is simple FIFO via `dict` insertion order (Python 3.7+)
- `_send_parsed_response` returns the sent `Message` — capture it to get `bot_message_id`
- Message ID storage must happen inside `_agent_lock` scope in singleton mode to maintain ordering

### References in Codebase
- `wrapper.py:1913-2039` — `handle_message` flow
- `abstract.py:10-20` — `ConversationTurn` dataclass
- `abstract.py:157-164` — `get_history` signature

---

## Acceptance Criteria

- [ ] `_message_id_cache` initialized as empty dict in `__init__`
- [ ] `_cache_message_id` stores `{message_id: text[:200]}` under chat_id
- [ ] Cache evicts oldest entry when exceeding 100 per chat
- [ ] `_store_telegram_metadata` injects both IDs into last turn's metadata
- [ ] `_store_telegram_metadata` handles missing history/turns gracefully (no crash)
- [ ] `handle_message` caches user message, caches bot response, stores metadata
- [ ] All unit tests pass: `pytest tests/unit/test_telegram_message_ids_feat120.py -v`

---

## Test Specification

```python
# tests/unit/test_telegram_message_ids_feat120.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestCacheMessageId:
    def test_cache_stores_entry(self):
        """Message ID and truncated text stored in cache."""

    def test_cache_truncates_text(self):
        """Text longer than 200 chars is truncated."""

    def test_cache_eviction_at_limit(self):
        """Oldest entry evicted when cache exceeds 100 entries per chat."""

    def test_cache_separate_per_chat(self):
        """Different chat_ids have independent caches."""


class TestStoreTelegramMetadata:
    async def test_metadata_injected(self):
        """Both message IDs appear in ConversationTurn.metadata."""

    async def test_no_history_no_crash(self):
        """Gracefully handles memory returning None."""

    async def test_empty_turns_no_crash(self):
        """Gracefully handles history with no turns."""


class TestHandleMessageIntegration:
    async def test_message_ids_cached_after_response(self):
        """User message and bot response are both cached."""

    async def test_metadata_stored_after_response(self):
        """_store_telegram_metadata called with correct IDs."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-842 must be done (it extends `_invoke_agent`)
3. **Verify the Codebase Contract** — confirm `handle_message` flow, `ConversationTurn.metadata` field, `get_history` signature
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-843-message-id-tracking.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-23
**Notes**: Added `_message_id_cache` to `__init__`, implemented `_cache_message_id` (FIFO eviction at 100 entries per chat), implemented `_store_telegram_metadata` (graceful handling of missing history/turns). Updated `handle_message` to cache user message, capture `_send_parsed_response` return value for bot message ID, and store metadata. Also modified `_send_safe_message`, `_send_long_message`, and `_send_parsed_response` to return `Optional[Message]` so the bot message ID can be tracked. All 12 unit tests pass.

**Deviations from spec**: Modified `_send_safe_message`, `_send_long_message`, and `_send_parsed_response` to return `Optional[Message]` (required to capture bot message ID per task implementation notes).
