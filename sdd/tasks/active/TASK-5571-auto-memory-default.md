# TASK-5571: Automatic conversation-memory default (`memory_type="auto"`, `REDIS_HISTORY_EXPLICIT`)

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 12)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5568 (conf.py)
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12 / §2 "Piece 2" / G6. Today the bot default is `memory_type="memory"` and the factory knows only
`memory | file | redis`. `parrot.conf` always synthesizes `REDIS_HISTORY_URL` from host/port defaults, so the mere existence of that
constant is NOT evidence that an operator configured Redis for history. This task adds:

- `REDIS_HISTORY_EXPLICIT` in `parrot/conf.py` — captured from the operator's own `REDIS_HISTORY_URL` BEFORE the synthesized default applies.
- `"auto"` as the new default `memory_type` and a factory branch: Redis only with an explicit signal (host-injected `redis_url` kwarg,
  or `REDIS_HISTORY_EXPLICIT`), otherwise `InMemoryConversation`. The factory performs no I/O and never probes.
- `configure_conversation_memory` no longer falls back to in-memory when Redis was selected — it re-raises (a silent fallback would
  split history across processes). Explicit `memory` / `file` keep the fallback.

`conf.py` is edited by TASK-5568 (adds `CHAT_HOT_TTL_HOURS`, anchored on a different line) and later by TASK-5581 (turn-bus settings);
`bots/abstract.py` is edited again by TASK-5583. This task sits between them — keep every edit anchored on the lines named below.

---

## Scope

- Add `REDIS_HISTORY_EXPLICIT: bool` to `parrot/conf.py`.
- Change the default at `bots/abstract.py:616` to `"auto"` and teach `get_conversation_memory` the `"auto"` resolution (default arg `"auto"`).
- Make `configure_conversation_memory` re-raise when Redis was selected (explicit `redis`, or `auto` resolving to Redis).
- Write `test_auto_memory_resolution.py` covering `test_auto_memory_resolution` and `test_auto_redis_failure_surfaces`.

**NOT in scope**: `RedisConversation` constructor changes (see drift note on a `redis=` kwarg); `models/bots.py` `memory_type` validation and
DB defaults; `bots/chatbot.py` / `bots/voice.py` memory-type handling (drift note); turn publisher / hydration injection (TASK-5583);
turn-bus settings (TASK-5581); documentation (TASK-5586).

### Spec clarifications (instructed by the coordinator; supersede the literal spec reading)
1. **`REDIS_HISTORY_URL` follows the operator.** Spec §3 M12 says it "keeps its current value either way"; that would make `REDIS_HISTORY_EXPLICIT=True`
   connect to the synthesized host/port URL instead of the one the operator wrote. Clarified rule: when `REDIS_HISTORY_EXPLICIT` is True,
   `REDIS_HISTORY_URL` IS the operator-provided value (never the synthesized one); otherwise it stays the synthesized f-string.
2. **`RedisConversation` has no `redis=` parameter** (`memory/redis.py:47-58`). Only a non-empty `redis_url` kwarg is the host-injected signal; `redis` is not accepted
   (needs `memory/redis.py`, not in this task). Record in the Completion Note.
3. **Code that assumed the `"memory"` default is fixed here:** `bots/voice.py:402`, `models/bots.py:365-368`, `server/ui/models.py:113`, `server/ui/catalog.py:123`.
   (`bots/chatbot.py:225/:382` default DB-loaded bots to `"memory"` explicitly and stay unaffected.)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | add `REDIS_HISTORY_EXPLICIT` |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `"auto"` default, factory branch, no silent fallback when Redis was selected |
| `packages/ai-parrot/tests/unit/bots/test_auto_memory_resolution.py` | CREATE | resolution, failure-surfacing, REDIS_HISTORY_URL, voice and validation tests |
| `packages/ai-parrot/src/parrot/bots/voice.py` | MODIFY | VoiceBot requires Redis: `"auto"` must not yield in-memory history |
| `packages/ai-parrot/src/parrot/models/bots.py` | MODIFY | `valid_memory_types` accepts `"auto"` |
| `packages/ai-parrot-server/src/parrot/server/ui/models.py` | MODIFY | `memory_type` Literal includes `"auto"` |
| `packages/ai-parrot-server/src/parrot/server/ui/catalog.py` | MODIFY | `memory_types` enumeration includes `"auto"` |

---

## Codebase Contract (Anti-Hallucination)

Re-verified against the tree at `6d564b36a2` (branch `dev`).

### Verified Imports
```python
from parrot.conf import REDIS_HISTORY_EXPLICIT                          # NEW — created by THIS task
from ..conf import EMBEDDING_DEFAULT_MODEL, KB_DEFAULT_MODEL            # verified: bots/abstract.py:26 (extend this line; 1 occurrence)
# bots/abstract.py already imports (module level, :45-47 via `from ..memory import (...)`):
#   InMemoryConversation, FileConversationMemory, RedisConversation, ConversationMemory
# tests:
from parrot.bots.base import BaseBot                                    # verified: tests/unit/bots/test_bot_history_wiring.py:17
from parrot.clients.base import AbstractClient                          # verified: test_bot_history_wiring.py:18
from parrot.memory import InMemoryConversation, RedisConversation       # verified: memory/__init__.py:19,21 (re-exports)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py
REDIS_HISTORY_DB = config.get("REDIS_HISTORY_DB", fallback=3)                        # :331
REDIS_HISTORY_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_HISTORY_DB}"          # :332  (1 occurrence) — synthesized; keep unchanged
# `config` is navconfig's `config` (conf.py:6) — `config.get(KEY, fallback=...)`, `config.getboolean(...)`

# packages/ai-parrot/src/parrot/bots/abstract.py
self.memory_type: str = kwargs.get("memory_type", "memory")  # 'memory', 'file', 'redis'   # :616  (1 occurrence)
self.memory_config: dict = kwargs.get("memory_config", {})                                  # :617
def configure_conversation_memory(self) -> None:                                            # :1432 (1 occurrence)
    try:
        self.conversation_memory = self.get_conversation_memory(storage_type=self.memory_type, **self.memory_config)   # :1435
        self.logger.info(f"Configured conversation memory: {self.memory_type}")
    except Exception as e:
        self.logger.error(f"Error configuring conversation memory: {e}")
        self.conversation_memory = self.get_conversation_memory("memory")                   # :1440  fallback
        self.logger.warning("Fallback to in-memory conversation storage")
    self._register_recovery_tool()                                                          # :1445 (runs after both branches)
def get_conversation_memory(self, storage_type: str = "memory", **kwargs) -> ConversationMemory:  # :2081 (1 occurrence)
    # 'memory' -> InMemoryConversation(**kwargs); 'file' -> FileConversationMemory(**kwargs);
    # 'redis'  -> RedisConversation(**kwargs); else raise ValueError(f"Unknown storage type: {storage_type}")

# packages/ai-parrot/src/parrot/memory/redis.py
class RedisConversation(ConversationMemory):
    def __init__(self, redis_url=None, key_prefix="conversation", use_hash_storage=True, *, token_counter=None,
                 omission_store=None, normalize=True, omission_ttl=None, history_ttl=None)  # :47-58  (NO `redis=` param)
    self.redis = Redis.from_url(...)   # :85 — lazy: construction performs no network I/O
```

### Does NOT Exist
- ~~`REDIS_HISTORY_EXPLICIT`~~ or any explicit-configuration signal in `parrot.conf` — created by THIS task; ~~a global env var for `memory_type`~~.
- ~~An `"auto"` / `"chat_storage"` `memory_type`~~ — the factory knows only `memory`, `file`, `redis` today.
- ~~`RedisConversation(redis=<client>)`~~ — not a parameter (drift 1).
- ~~A connection probe in the factory~~ — forbidden by the spec; `get_conversation_memory` must stay I/O-free.
- ~~A `REDIS_HISTORY_URL` that reflects the operator's env value~~ — it is always the synthesized f-string (drift 2).
- ~~`"auto"` accepted by `models/bots.py` validation~~ — it is not (drift 3); do not edit that file here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/conf.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/bots/test_auto_memory_resolution.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/bots/voice.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/models/bots.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/server/ui/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/server/ui/catalog.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.get_conversation_memory",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure_conversation_memory",
    "sym:packages/ai-parrot/src/parrot/memory/redis.py#RedisConversation"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **REDIS_HISTORY_URL (spec clarification 1)**: in `conf.py` compute `_explicit = str(config.get("REDIS_HISTORY_URL", fallback="") or "").strip()`;
  `REDIS_HISTORY_EXPLICIT = bool(_explicit)`; `REDIS_HISTORY_URL = _explicit or f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_HISTORY_DB}"` (replace the
  existing synthesized line, anchor `REDIS_HISTORY_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_HISTORY_DB}"`, 1 occurrence). Other readers of the constant
  (`memory/redis.py`, `stores/cache.py`, interfaces) then pick up the operator value too — intended.
- **VoiceBot**: replace the `bots/voice.py:402` check so `memory_type` in (`None`, `""`, `"memory"`, `"auto"`) becomes `"redis"` — VoiceBot requires Redis, so `"auto"` must not
  resolve to in-memory. An explicit `"file"` / `"redis"` is kept.
- **Validation / UI**: `valid_memory_types = ["memory", "file", "redis"]` (`models/bots.py:366`) becomes `["auto", "memory", "file", "redis"]`;
  `Literal["memory", "file", "redis"] | None` (`server/ui/models.py:113`) and `memory_types=["memory", "file", "redis"]` (`server/ui/catalog.py:123`) gain `"auto"`.
  Leave the `BotModel.memory_type` default `'memory'` (`models/bots.py:298`, DB column) unchanged.
- Resolution table (spec §3 M12): explicit `memory` / `file` / `redis` behave EXACTLY as today (explicit wins). `auto` -> `RedisConversation(**kwargs)` when
  `kwargs` carries a non-empty `redis_url`, or `REDIS_HISTORY_EXPLICIT` is true; otherwise `InMemoryConversation(**kwargs)`. Unknown type -> `ValueError`.
- The factory performs NO I/O and infers nothing from `REDIS_HISTORY_URL` truthiness (it is always truthy).
- `kwargs` for the in-memory branch of `auto`: `memory_config` may carry Redis-only keys (`key_prefix`, `history_ttl`, ...) when an operator flips to `auto`; the
  in-memory branch must not crash on them. FILL IN the filtering rule below.
- Re-raise rule: if Redis was selected (explicit `redis`, or `auto` that resolved to Redis), `configure_conversation_memory` logs at ERROR and re-raises the original exception;
  `memory` / `file` keep the fallback + WARNING. `self._register_recovery_tool()` still runs on the success path only.
- `REDIS_HISTORY_EXPLICIT` must be a plain `bool`: `True` only for a non-empty, non-whitespace operator value of `REDIS_HISTORY_URL`. Read through `config.get` (never `os.environ`, spec §7).
- `self.logger` only; Google-style docstrings; do not add a new dependency.

### References in Codebase
- `packages/ai-parrot/src/parrot/conf.py:325-336` — neighbouring `config.get(..., fallback=...)` lines (placement).
- `packages/ai-parrot-server/src/parrot/handlers/studio/conversation.py:28-58` — an existing caller that passes `memory_type="redis"` + `memory_config={"redis_url": ..., "key_prefix": ...}` (what a host-injected URL looks like).
- `packages/ai-parrot/tests/unit/bots/conftest.py:316-345` (`make_bot`) and `tests/unit/bots/test_bot_history_wiring.py:30-102` — offline bot construction with a stub client.

---

## Implementation Blueprint

### Steps (in order)
1. Add `REDIS_HISTORY_EXPLICIT` to `conf.py` — *why*: `abstract.py` imports it.
2. Edit `bots/abstract.py` (import, default, factory, configure) — *why*: the behaviour.
3. Write the tests; mutation-check — *why*: AC evidence.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'REDIS_HISTORY_DB = config.get("REDIS_HISTORY_DB", fallback=3)' packages/ai-parrot/src/parrot/conf.py)
# BEFORE — insert ABOVE `REDIS_HISTORY_DB = config.get("REDIS_HISTORY_DB", fallback=3)` (conf.py:331), so the capture precedes the synthesized URL:
# FEAT-886: True only when the operator set REDIS_HISTORY_URL themselves. Captured BEFORE the host/port default
# below is synthesized; REDIS_HISTORY_URL is the operator value when explicit, else the synthesized URL (spec clarification 1).
_explicit_history_url = str(config.get("REDIS_HISTORY_URL", fallback="") or "").strip()
REDIS_HISTORY_EXPLICIT: bool = bool(_explicit_history_url)
# and REPLACE the synthesized line below (conf.py:332) with:
#   REDIS_HISTORY_URL = _explicit_history_url or f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_HISTORY_DB}"
```
**Why**: spec §3 M12 skeleton, plus clarification 1: ALSO replace `REDIS_HISTORY_URL = f"redis://..."` (conf.py:332) with `_explicit or f"..."` as described in Key Constraints. The anchor differs from TASK-5568 (which anchors on `REDIS_DATASET_URL`) and from the `REDIS_HISTORY_URL` line, so the three edits do not collide.
Re-run the `grep -c` first; if TASK-5568 already landed the file has shifted but the anchor string is unchanged.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..conf import EMBEDDING_DEFAULT_MODEL, KB_DEFAULT_MODEL' packages/ai-parrot/src/parrot/bots/abstract.py)
# REPLACE (abstract.py:26) with:
from ..conf import EMBEDDING_DEFAULT_MODEL, KB_DEFAULT_MODEL, REDIS_HISTORY_EXPLICIT
# NOTE for the tests: this binds the value at import time — tests monkeypatch `parrot.bots.abstract.REDIS_HISTORY_EXPLICIT`.

# occurrences: 1 (verified: grep -c 'self.memory_type: str = kwargs.get("memory_type", "memory")' packages/ai-parrot/src/parrot/bots/abstract.py)
# REPLACE the whole line (abstract.py:616) with:
        self.memory_type: str = kwargs.get("memory_type", "auto")  # 'auto', 'memory', 'file', 'redis'

# occurrences: 1 (verified: grep -c 'def get_conversation_memory(self, storage_type: str = "memory", \*\*kwargs) -> ConversationMemory:' packages/ai-parrot/src/parrot/bots/abstract.py)
# REPLACE the whole method (abstract.py:2081-2090) with:
    def get_conversation_memory(self, storage_type: str = "auto", **kwargs) -> ConversationMemory:
        """Factory function to create conversation memory instances.

        ``'memory'`` | ``'file'`` | ``'redis'`` behave as before. ``'auto'`` selects
        :class:`RedisConversation` when ``kwargs`` carries a host-injected ``redis_url`` or
        ``REDIS_HISTORY_EXPLICIT`` is true, otherwise :class:`InMemoryConversation`. The factory
        performs no I/O and never probes a connection.

        Raises:
            ValueError: For an unknown storage type.
        """
        if storage_type == "auto":
            storage_type = "redis" if self._auto_selects_redis(kwargs) else "memory"
            # FILL IN: when 'auto' resolves to 'memory', drop Redis-only keys from kwargs (key_prefix, history_ttl,
            #   omission_ttl, use_hash_storage, redis_url) before InMemoryConversation(**kwargs) so an operator who
            #   configured them without an explicit URL does not crash on a TypeError — bounded by AC-1 and by
            #   InMemoryConversation.__init__'s accepted keys (memory/mem.py:15-20: token_counter, omission_store, normalize).
        if storage_type == "memory":
            return InMemoryConversation(**kwargs)
        elif storage_type == "file":
            return FileConversationMemory(**kwargs)
        elif storage_type == "redis":
            return RedisConversation(**kwargs)
        else:
            raise ValueError(f"Unknown storage type: {storage_type}")

    @staticmethod
    def _auto_selects_redis(kwargs: dict) -> bool:
        """Whether ``memory_type='auto'`` resolves to Redis (no I/O).

        True for a non-empty host-injected ``redis_url`` kwarg, or when ``REDIS_HISTORY_EXPLICIT`` is set.
        """
        return bool(kwargs.get("redis_url")) or bool(REDIS_HISTORY_EXPLICIT)

# occurrences: 1 (verified: grep -c 'def configure_conversation_memory(self) -> None:' packages/ai-parrot/src/parrot/bots/abstract.py)
# REPLACE the `except Exception as e:` block of that method (abstract.py:1437-1441) with:
        except Exception as e:
            self.logger.error(f"Error configuring conversation memory: {e}")
            if self.memory_type == "redis" or (
                self.memory_type == "auto" and self._auto_selects_redis(self.memory_config)
            ):
                # Redis was selected: a silent in-memory fallback would split history across processes.
                raise
            # Fallback to in-memory (explicit 'memory' / 'file', or 'auto' without Redis)
            self.conversation_memory = self.get_conversation_memory("memory")
            self.logger.warning("Fallback to in-memory conversation storage")
```
**Why**: `grep -c` of every anchor is 1 (verified). `get_conversation_memory`'s default changes to `"auto"` so a bare call matches the new bot default (spec skeleton).
`configure_conversation_memory` re-raises exactly when Redis was selected (spec §7 "`configure_conversation_memory` fallback"); the success path and the
`_register_recovery_tool()` call below the try/except are untouched. Keep `configure_conversation_memory` under complexity 10 (one added branch).

### Extra edits (voice / validation / UI) — each anchor verified
```python
# packages/ai-parrot/src/parrot/bots/voice.py   occurrences: 1 (grep -c 'if not self.memory_type or self.memory_type == "memory":' voice.py) (:402)
        if not self.memory_type or self.memory_type in ("memory", "auto"):
            self.memory_type = "redis"
# packages/ai-parrot/src/parrot/models/bots.py  occurrences: 1 (grep -c 'valid_memory_types = \["memory", "file", "redis"\]' bots.py) (:366)
        valid_memory_types = ["auto", "memory", "file", "redis"]
# packages/ai-parrot-server/src/parrot/server/ui/models.py  occurrences: 1 (grep -c 'memory_type: Literal\["memory", "file", "redis"\] | None = None' models.py) (:113)
    memory_type: Literal["auto", "memory", "file", "redis"] | None = None
# packages/ai-parrot-server/src/parrot/server/ui/catalog.py  occurrences: 1 (grep -c 'memory_types=\["memory", "file", "redis"\],' catalog.py) (:123)
        memory_types=["auto", "memory", "file", "redis"],
```
**Why**: coordinator-instructed (spec clarifications 1 and 3). Re-run each `grep -c` first.

### `packages/ai-parrot/tests/unit/bots/test_auto_memory_resolution.py` (CREATE)
```python
"""FEAT-886 M12 — memory_type='auto' resolution and no-fallback when Redis was selected."""
from __future__ import annotations

import pytest

from parrot.bots import abstract as bots_abstract
from parrot.bots.base import BaseBot
from parrot.memory import InMemoryConversation, RedisConversation

# FILL IN: `_StubClient(AbstractClient)` + `_bot(**kw)` — copy the minimal offline stub from tests/unit/bots/conftest.py
#   (`_BudgetStubClient`) or tests/unit/bots/test_bot_history_wiring.py:30-60; BaseBot(name=..., llm=_StubClient(), injection_detection=False, **kw).
#   Bounded by: no network, no event loop needed (the tests call get_conversation_memory / configure_conversation_memory, both synchronous).


def test_auto_memory_resolution(monkeypatch):
    """Synthesized defaults -> in-memory (no Redis I/O); explicit URL / injected redis_url -> Redis; explicit types win."""
    # FILL IN: (1) monkeypatch bots_abstract.REDIS_HISTORY_EXPLICIT False: _bot().get_conversation_memory("auto") is InMemoryConversation;
    #   to prove "no Redis I/O", monkeypatch RedisConversation in bots_abstract to a class that raises AssertionError on construction.
    #   (2) REDIS_HISTORY_EXPLICIT True -> RedisConversation instance (construction is lazy, no connection).
    #   (3) EXPLICIT False but kwargs redis_url="redis://localhost:6379/9" -> RedisConversation with that .redis_url.
    #   (4) explicit "memory"/"file" stay authoritative even with EXPLICIT True; explicit "redis" is Redis with EXPLICIT False;
    #   (5) unknown storage type raises ValueError; (6) a fresh BaseBot has memory_type == "auto".
    #   Bounded by spec §3 M12 resolution table and AC-1.
    #   Mutation: make _auto_selects_redis ignore REDIS_HISTORY_EXPLICIT -> case (2) RED; ignore redis_url -> case (3) RED.


def test_auto_redis_failure_surfaces(monkeypatch):
    """A configured Redis failure raises from configure_conversation_memory; no in-memory fallback."""
    # FILL IN: monkeypatch bots_abstract.RedisConversation to a class whose __init__ raises ConnectionError("down");
    #   (a) memory_type="redis" -> pytest.raises(ConnectionError) and bot.conversation_memory is still None;
    #   (b) memory_type="auto", memory_config={"redis_url": "redis://x:1/0"} -> raises;
    #   (c) memory_type="auto" with EXPLICIT True -> raises;
    #   (d) memory_type="auto" with EXPLICIT False and no URL -> no raise, InMemoryConversation (the constructor is never reached);
    #   (e) memory_type="file" with a broken FileConversationMemory -> still falls back to InMemoryConversation (explicit file keeps the fallback).
    #   Bounded by AC-2. Mutation: remove the `raise` in the new branch -> cases (a)-(c) RED.
```
```python
def test_redis_history_url_is_operator_value_when_explicit(monkeypatch):
    """EXPLICIT True -> REDIS_HISTORY_URL == the operator's value; otherwise the synthesized host/port URL."""
    # FILL IN: monkeypatch parrot.conf.config.get to return "redis://ops:6380/7" for REDIS_HISTORY_URL, importlib.reload(parrot.conf) (restore afterwards),
    #   assert REDIS_HISTORY_EXPLICIT is True and REDIS_HISTORY_URL == "redis://ops:6380/7"; then with the key absent/blank assert EXPLICIT is False and the URL
    #   starts with "redis://{REDIS_HOST}". Bounded by AC-3. Mutation: keep the f-string unconditionally -> RED.

async def test_voicebot_auto_means_redis():
    """A VoiceBot left on the default 'auto' is switched to 'redis'; explicit 'file' is kept."""
    # FILL IN: build a VoiceBot (see tests for bots/voice.py; offline), call the memory-type normalisation path (configure() or the extracted check) with
    #   memory_type 'auto' / 'memory' / None -> 'redis'; 'file' -> 'file'. Bounded by AC-4. Mutation: restore `== "memory"` -> 'auto' case RED.

def test_bot_model_validation_accepts_auto():
    """BotModel memory_type='auto' validates; an unknown value still raises ValueError."""
    # FILL IN: construct the models/bots.py model whose __post_init__ holds valid_memory_types with memory_type='auto' (and 'bogus' raises). Bounded by AC-5.
```
Server-side enumeration test, in the same task test file under `pytest.importorskip("parrot.server.ui.models")`:
```python
def test_ui_enumerations_include_auto():
    # FILL IN: importorskip parrot.server.ui.catalog / .models; assert "auto" in the catalog's memory_types and that the models' memory_type Literal accepts "auto"
    #   (typing.get_args). Bounded by AC-5.
```

**Why this shape**: the factory's real classes are used (`RedisConversation` construction is lazy — no I/O — so "explicit URL -> Redis" needs no server); the
only doubles are the constructor-failure injections, which are legitimate (a network failure is the thing being simulated).

### FILL IN checklist
- [ ] `abstract.py::get_conversation_memory` — which kwargs to drop on the `auto -> memory` path; bounded by `InMemoryConversation.__init__` keys and AC-1.
- [ ] `test_auto_memory_resolution.py` — stub client/bot helper and the six cases; bounded by the spec resolution table.
- [ ] `test_auto_redis_failure_surfaces` cases (a)-(e); bounded by AC-2.
- [ ] Completion Note records spec clarifications 1-3.

---

## Acceptance Criteria

- [ ] AC-1 (spec §5 "Automatic selection"): with only synthesized defaults, `auto` selects `InMemoryConversation` with no Redis constructor call; an explicit history URL (`REDIS_HISTORY_EXPLICIT`) and a host-injected `redis_url` select `RedisConversation`; explicit `memory` / `file` / `redis` stay authoritative; a fresh bot's `memory_type` is `"auto"`. `test_auto_memory_resolution` passes.
- [ ] AC-2: a configured Redis failure raises from `configure_conversation_memory` and does not fall back (explicit `redis`, `auto`+URL, `auto`+explicit signal); explicit `memory`/`file` keep the fallback. `test_auto_redis_failure_surfaces` passes.
- [ ] AC-3: `REDIS_HISTORY_EXPLICIT` is a `bool` (`False` when the operator set nothing); when True, `REDIS_HISTORY_URL` equals the operator-provided value, never the synthesized one; when False it stays the synthesized host/port URL.
- [ ] AC-4: a VoiceBot with `memory_type` `auto`/`memory`/unset resolves to `redis`; explicit `file` is kept.
- [ ] AC-5: `models/bots.py` validation, `server/ui/models.py` and `server/ui/catalog.py` accept/list `"auto"`.
- [ ] Mutation checks (record evidence): (1) ignore `REDIS_HISTORY_EXPLICIT` in `_auto_selects_redis` -> resolution test RED; (2) delete the new `raise` -> failure test RED; (3) restore the default to `"memory"` -> the `memory_type == "auto"` assertion RED.
- [ ] Existing bot suites that build bots with the default memory type still pass (`tests/unit/bots/test_bot_history_wiring.py`, `tests/unit/bots/test_context_budget.py`).
- [ ] `parrot/clients/base.py` untouched; `ruff check` clean on all three files.
- [ ] Completion Note records spec clarifications 1-3.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/bots/test_auto_memory_resolution.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_bot_history_wiring.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_context_budget.py -q`

---

## Test Specification

Spec §4 rows for M12 (fixtures inside the test file):

```python
def test_auto_memory_resolution(monkeypatch): ...      # synthesized defaults -> in-memory, no Redis I/O; explicit URL / injected connection -> Redis; explicit types win
def test_auto_redis_failure_surfaces(monkeypatch): ...  # a configured Redis failure raises, no in-memory fallback
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5568 must be `"done"` in `sdd/tasks/index/durable-conversation-memory.json` (it edits `conf.py` first)
4. **Verify the Codebase Contract** — re-run every `grep -c` above (all expected `1`); update the contract first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** all acceptance criteria — run the Validation Commands and the mutation checks
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5571 durable-conversation-memory verified`
10. **Fill in the Completion Note** below (spec clarifications 1-3), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
