# TASK-5584: Server wiring — start the turn bus, attach durable memory to bots, make AgentTalk persistence-free

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: sdd/specs/durable-conversation-memory.spec.md (Module 17)
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5568, TASK-5581, TASK-5582, TASK-5579, TASK-5583
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 17 (Piece 1, "AgentTalk owns no persistence (hard cut)"). The server host is where the
pieces meet: `BotManager` starts and stops the turn bus at application level, attaches the publisher,
hydration source and sequence allocator to every bot it registers, and registers a working-memory cleaner
per bot so a conversation deletion also clears the bot's `ConversationMemory`. `AgentTalk`
(`handlers/agent.py`) stops writing anywhere: no `chat_storage.save_turn(...)` (both the streaming and the
JSON path), no `ConversationMemory` construction or injection, no serialization of turns or tool calls. It
only passes `output_mode` and `turn_id=client_message_id` into the bot.

TASK-5568 (M1) already removes the per-request `RedisConversation()` injection (spec M1 (a)). This task
finishes the hard cut and adds the AST fence that keeps it cut.

---

## Scope

- `BotManager.setup_registry_only(..., turn_persistence: bool = False)`: opt-in that also initializes
  `ChatStorage` and the turn bus at startup and stops them at shutdown.
- `BotManager.on_startup` calls `setup_turn_persistence(chat_storage)` right after
  `chat_storage.initialize()` succeeds and stores the handle in `app["turn_persistence"]`;
  `on_shutdown` calls `shutdown_turn_persistence(handle)` BEFORE closing `ChatStorage`.
- A failure to start the bus is logged at ERROR and leaves the server running without persistence (Q16).
- `BotManager._attach_durable_memory(bot)`: set `turn_publisher`, `hydration_source`, `sequence_allocator`
  and register a working-memory cleaner. No-op when turn persistence is not running. Called from
  `add_bot`, `add_agent`, the other places the manager registers bots lazily, and once for every
  already-registered bot right after the bus starts.
- `handlers/agent.py`: remove both `chat_storage.save_turn(...)` blocks, any remaining `memory=` /
  `RedisConversation` plumbing, and pass `turn_id=client_message_id` into `bot.ask` / `bot.ask_stream`.
- Tests, including an AST fence on `handlers/agent.py` and the rewrite of the tenant-metadata test.

**NOT in scope**:
- `setup_turn_persistence` / `ChatStorageHydrationSource` themselves (TASK-5581 / TASK-5582); the bot-side
  behavior (TASK-5583); `ChatStorage` internals (TASK-5579 owns
  `storage/chat.py`).
- `handlers/chat_interaction.py` / `handlers/threads.py`: unchanged call sites; new deletion semantics live
  behind `ChatStorage` (spec §2 Integration Points).
- Agent Studio (`StudioRuntimeCache`): `add_bot` refuses Studio instances, so their wiring is consumed in
  the Studio repo (spec §7 "Studio and registry-only hosts").
- Any Rule 2 migration of `handlers/agent.py` endpoints: this task deletes code from it, it adds no endpoint.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | turn-bus lifecycle, `_attach_durable_memory`, `setup_registry_only(turn_persistence=)` |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | delete persistence code; forward `turn_id=client_message_id` |
| `packages/ai-parrot-server/tests/manager/test_turn_persistence_wiring.py` | CREATE | lifecycle + attachment tests on a real `BotManager` and aiohttp app |
| `packages/ai-parrot-server/tests/handlers/test_agenttalk_no_persistence_writes.py` | CREATE | AST fence + turn_id forwarding |
| `packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py` | MODIFY | rewrite the two `save_turn` tests against the event's presentation payload |

---

## Codebase Contract (Anti-Hallucination)

> `S` = `packages/ai-parrot-server/src/parrot`, `P` = `packages/ai-parrot/src/parrot`.
> Items marked **(created by TASK-NNNN)** are not in the tree yet; re-verify once the dependency is `done`.

### Verified Imports
```python
# S/manager/manager.py already has:
from ..storage import ChatStorage, ArtifactStore, build_conversation_backend, build_overflow_store  # manager.py:61-66
from aiohttp import web                                                                               # manager.py:10
_REGISTRY_ONLY_APP_KEY = "_bot_manager_registry_only"                                                 # manager.py:196

# NEW in manager.py (all created by dependencies):
from ..storage.turn_bus import setup_turn_persistence, shutdown_turn_persistence, TurnPersistence  # TASK-5581 (P/storage/turn_bus.py)
from ..storage.hydration import ChatStorageHydrationSource                                         # TASK-5582 (P/storage/hydration.py)
from ..memory.hydration import LocalSequenceAllocator, RedisSequenceAllocator                      # TASK-5580 (P/memory/hydration.py)

# tests:
from parrot.manager.manager import BotManager                       # verified: tests/manager/test_registry_only.py:6
from parrot.bots.base import BaseBot                                # verified: P/bots/base.py:130
from parrot.storage import ChatStorage                              # verified: P/storage/__init__.py:3
from parrot.storage.backends.sqlite import ConversationSQLiteBackend   # verified: P/storage/backends/sqlite.py:35
from parrot.memory import InMemoryConversation                     # verified: P/memory/__init__.py
from navigator_eventbus import EventBus                             # needs navigator-eventbus >= 0.4.0 (transport=)
```
Environment note: the local `.venv` of this repo currently has `navigator_eventbus 0.3.0`, whose
`EventBus.__init__` has no `transport=` parameter; the pin in `packages/ai-parrot/pyproject.toml:201` is
`>=0.4.0`. The new tests must `pytest.skip` (module-level guard on
`inspect.signature(EventBus.__init__)`) when `transport` is unsupported rather than fail.

### Existing Signatures to Use
```python
# S/manager/manager.py
class BotManager:                                                    # :221
    self.app = None                                                  # :2405 (set in setup()); setup_registry_only sets self.app = app (:3155)
    def add_bot(self, bot: AbstractBot) -> None                      # :817  (refuses Studio bots; sets self._bots[bot.name], self._botdef[...])
    def add_agent(self, agent: AbstractBot) -> None                  # :1313 (self._bots[str(agent.chatbot_id)] = agent)
    def setup_registry_only(self, app, *, import_modules=False, load_definitions=False) -> None   # :3130
        app[_REGISTRY_ONLY_APP_KEY] = {"import_modules": ..., "load_definitions": ...}            # :3149
        app.on_startup.append(self._registry_only_startup)           # :3157 (hooks count is asserted by test_registry_only_hooks_once)
    async def _registry_only_startup(self, app) -> None              # :3167 reads opts = app[_REGISTRY_ONLY_APP_KEY]
    async def _registry_only_shutdown(self, app) -> None             # :3182
    async def on_startup(self, app) -> None                          # :3194
        chat_storage = ChatStorage()                                 # :3237
        self.logger.info("ChatStorage initialized (Redis + DocumentDB)")   # :3240 (inside try after chat_storage.initialize())
        app["chat_storage"] = chat_storage                           # :3246
    async def on_shutdown(self, app) -> None                         # :3264  "# Close ChatStorage" :3277
# bots registered WITHOUT add_bot (verified direct `self._bots[...] =` writes):
#   self._bots[agent_name] = instance        # :459  _process_startup_results
#   self._bots[new_name] = bot               # :924  temporary user instances
#   self._bots[name] = new_instance          # :1058 reload_agent

# P/storage/chat.py (existing)
class ChatStorage:                                                   # :25
    # created by TASK-5579 (depends_on): read-only properties
    #   cold_backend: Optional[ConversationBackend]     (today the private `_dynamo`)
    #   hot_redis_client: Optional[Any]                 (Redis client, or None when the hot tier has none)
    self._initialized                                                              :38
    # register_memory_cleaner(cleaner: Callable[[str, str, str], Awaitable[None]])   created by TASK-5579
# P/memory/redis.py
class RedisConversation: self.redis  # redis.asyncio client                        :85
    async def delete_history(self, user_id, session_id, chatbot_id=None) -> bool   :652 (also clears omission data)

# S/handlers/agent.py  (baseline line numbers; TASK-5568 shifts them — re-grep)
from ..memory import RedisConversation                               # :42
memory = None / memory = RedisConversation()                         # :1733-1738 (TASK-5568 removes the injection)
await self._handle_stream_response(... client_message_id=client_message_id, ...)   # :1829-1850
bot.followup(..., turn_id=followup_turn_id, ..., memory=memory, **data)            # :1853  (keeps its own turn_id)
bot.ask(question=..., ..., output_mode=output_mode, memory=memory, llm=llm, tenant=tenant, **data)   # :1869-1884
async def _handle_stream_response(self, ..., memory: Optional[Any], ..., client_message_id=None, ...)  # :2684
async for chunk in bot.ask_stream(question=..., output_mode=output_mode, memory=memory, ...)          # :2728-2745
# Persist chat turn via ChatStorage  ... chat_storage.save_turn(...)  ... "Error scheduling streamed chat turn save"  # :2807-2863
# Persist chat turn via ChatStorage (hot + cold) ... chat_storage.save_turn(...) ... "Error scheduling chat turn save"  # :3060-3093
```
Created by dependencies:
```python
# P/storage/turn_bus.py (TASK-5581)
@dataclass
class TurnPersistence: bus: Any; publisher: BusTurnPublisher; subscription_ids: List[str]; dlq: Optional[Any] = None
async def setup_turn_persistence(chat_storage, *, bus=None) -> TurnPersistence    # raises RuntimeError: outbox dir unset / not writable
async def shutdown_turn_persistence(handle) -> None
# P/storage/hydration.py (TASK-5582):  ChatStorageHydrationSource(backend: ConversationBackend)
# P/memory/hydration.py (TASK-5580):   LocalSequenceAllocator();  RedisSequenceAllocator(redis_client, *, key_prefix="conversation")
# P/bots/abstract.py (TASK-5583):      bot.turn_publisher / bot.hydration_source / bot.sequence_allocator (default None)
```

### Does NOT Exist
- ~~`BotManager._attach_durable_memory`~~, ~~`setup_registry_only(turn_persistence=)`~~, ~~`app["turn_persistence"]`~~ — added here.
- ~~Private-attribute access to ChatStorage~~ — not needed: use the TASK-5579 properties `cold_backend` and
  `hot_redis_client`; never read `_dynamo` / `_redis`.
- ~~A bot registered through `add_bot` only~~ — three other write sites exist (`:459`, `:924`, `:1058`) and
  `load_bots` runs BEFORE ChatStorage is initialized in `on_startup`, so bots registered at load time are
  attached by the post-start sweep, not by `add_bot`.
- ~~`handlers/agent.py` reads/writes through a `memory` argument after this task~~ — gone.
- ~~Studio instances in `BotManager._bots`~~ — `add_bot` raises `ValueError` for them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/agent.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/manager/test_turn_persistence_wiring.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_agenttalk_no_persistence_writes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_bot",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_agent",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.setup_registry_only",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.on_startup",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.on_shutdown",
    "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- `BotManager._setup_dataplane_guard` (`manager.py:3102`) is the in-file precedent for "inject something
  into every managed bot after startup": it loops `self._bots.values()` and never overwrites a bot's own
  value. `_attach_durable_memory` follows that rule (an explicitly injected collaborator wins).
- Bus lifecycle mirrors `observability/fanout.py` through TASK-5581; this task only calls it.

### Key Constraints
- `manager.py` is far over the 500-line module budget (grandfathered, ARCHITECTURE.md ratchet). Add only
  small methods (<= 30 lines, complexity <= 10) and one-line call sites; no logic inline in `on_startup`.
- `test_registry_only_hooks_once` asserts the exact number of `on_startup` / `on_shutdown` / `on_cleanup`
  hooks. Do NOT append new aiohttp hooks: extend `_registry_only_startup` / `_registry_only_shutdown`.
- Bus startup failure: log at ERROR with `exc_info` and continue; no publisher / source is attached and
  the server serves (Q16). This tolerance never extends to conversation history selection (TASK-5571).
- Never block the event loop; everything stays `async`.
- Test doubles (ARCHITECTURE.md Rule 6): the manager is a real `BotManager` on a real `web.Application`; the
  bus is a real `EventBus(transport="memory")`; the cold tier is a real `ConversationSQLiteBackend`. The
  hot tier is an in-file `InMemoryConversation` subclass with `upsert_turn` because Redis is the one external
  service that cannot run here (tests that need real Redis skip without `TEST_REDIS_URL`, as
  `tests/unit/memory/test_redis_history_ttl.py` does). No `MagicMock` request/session objects.

### References in Codebase
- `packages/ai-parrot-server/tests/manager/test_registry_only.py` — `_manager()` helper, runner lifecycle tests
- `packages/ai-parrot-server/tests/manager/test_dataplane_guard_wiring.py` — "inject into every managed bot" test pattern
- `packages/ai-parrot-server/src/parrot/handlers/chat_interaction.py:314` / `threads.py:364` — deletion call sites (unchanged)

---

## Implementation Blueprint

### Steps (in order)
1. Re-verify the contract and that TASK-5568/5581/5582/5583 are `done`; re-grep every anchor below (TASK-5568 already edited `handlers/agent.py`) — *why*: line numbers and some blocks change under you.
2. `manager.py`: imports, `_DurableMemory` dataclass, `_memory_cleaner_for`, class default `_durable_memory = None` — *why*: typed home for the shared collaborators.
3. `manager.py`: `_build_durable_memory`, `_start_turn_persistence`, `_stop_turn_persistence`, `_attach_durable_memory` — *why*: spec M17 interface.
4. `manager.py`: wire `add_bot`, `add_agent`, the three lazy registration sites, `on_startup`, `on_shutdown`, `setup_registry_only`, `_registry_only_startup/_shutdown` — *why*: lifecycle and attachment points.
5. `handlers/agent.py`: delete the persistence code and forward `turn_id` — *why*: hard cut (spec §2).
6. Tests: wiring, AST fence, rewrite of the tenant-metadata test; run mutation checks.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY) — module-level additions
```python
# occurrences: 1 (verified: grep -c '_REGISTRY_ONLY_APP_KEY = "_bot_manager_registry_only"' S/manager/manager.py)
# AFTER that line (manager.py:196), add imports at the top import block and this at module level:
from dataclasses import dataclass  # FILL IN: skip if already imported (grep '^from dataclasses' first; none at baseline)
from ..storage.turn_bus import TurnPersistence, setup_turn_persistence, shutdown_turn_persistence
from ..storage.hydration import ChatStorageHydrationSource
from ..memory.hydration import LocalSequenceAllocator, RedisSequenceAllocator


@dataclass(frozen=True)
class _DurableMemory:
    """Collaborators every managed bot receives once turn persistence is running (FEAT-886)."""

    chat_storage: ChatStorage
    handle: TurnPersistence
    hydration_source: Optional[ChatStorageHydrationSource]
    sequence_allocator: Any


def _memory_cleaner_for(bot: AbstractBot):
    """Working-memory cleaner for ``ChatStorage.register_memory_cleaner`` bound to one bot."""

    async def _clean(user_id: str, agent_id: str, session_id: str) -> None:
        memory = getattr(bot, "conversation_memory", None)
        if memory is None or agent_id != bot.name:
            return
        await memory.delete_history(user_id, session_id, chatbot_id=bot.memory_key_id)

    return _clean
```
**Why**: the cleaner is keyed by `agent_id == bot.name` because ChatStorage identifies agents by NAME while the
history lives under `memory_key_id` (spec §2 "Identity"). `delete_history` already clears omission data on the
Redis backend (`memory/redis.py:657`).

### `manager.py` (MODIFY) — lifecycle and attachment methods
```python
# occurrences: 1 (verified: grep -c '    async def _registry_only_startup' S/manager/manager.py)
# Insert these methods BEFORE `async def _registry_only_startup` (manager.py:3167):

    _durable_memory: Optional[_DurableMemory] = None

    def _build_durable_memory(self, chat_storage: ChatStorage, handle: TurnPersistence) -> _DurableMemory:
        """Build the shared hydration source and sequence allocator from the running ChatStorage."""
        # FILL IN: read `chat_storage.cold_backend` and `chat_storage.hot_redis_client` (public properties
        #          created by TASK-5579). Source is None when `cold_backend` is None (cold storage disabled),
        #          else ChatStorageHydrationSource(cold_backend). Allocator is
        #          RedisSequenceAllocator(hot_redis_client) when it is not None, else LocalSequenceAllocator().
        #          Bounded by spec §2 "Sequence allocation".
        raise NotImplementedError

    async def _start_turn_persistence(self, app: web.Application, chat_storage: ChatStorage) -> None:
        """Start the turn bus; on failure log ERROR and leave the server running (Q16)."""
        try:
            handle = await setup_turn_persistence(chat_storage)
        except Exception as exc:  # noqa: BLE001 - startup must never be blocked by the audit bus
            self.logger.error("Turn persistence not started, agents run without ChatStorage: %s", exc, exc_info=True)
            return
        app["turn_persistence"] = handle
        self._durable_memory = self._build_durable_memory(chat_storage, handle)
        for bot in list(self._bots.values()):  # bots loaded before the bus existed
            self._attach_durable_memory(bot)
        self.logger.info("Turn persistence started")

    async def _stop_turn_persistence(self, app: web.Application) -> None:
        """Detach and stop the turn bus BEFORE ChatStorage closes (preserves the outbox)."""
        handle = app.pop("turn_persistence", None)
        self._durable_memory = None
        if handle is None:
            return
        try:
            await shutdown_turn_persistence(handle)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Turn persistence shutdown failed: %s", exc)

    def _attach_durable_memory(self, bot: AbstractBot) -> None:
        """Set ``turn_publisher`` / ``hydration_source`` / ``sequence_allocator`` on ``bot`` (FEAT-886 M17).

        No-op when turn persistence is not running. A collaborator the bot already carries is kept.
        Registers one working-memory cleaner per bot with ChatStorage.
        """
        durable = self._durable_memory
        if durable is None or getattr(bot, "_durable_memory_attached", False):
            return
        if bot.turn_publisher is None:
            bot.turn_publisher = durable.handle.publisher
        if bot.hydration_source is None:
            bot.hydration_source = durable.hydration_source
        if bot.sequence_allocator is None:
            bot.sequence_allocator = durable.sequence_allocator
        durable.chat_storage.register_memory_cleaner(_memory_cleaner_for(bot))
        bot._durable_memory_attached = True  # noqa: SLF001 - idempotency marker, one cleaner per bot
```
**Why this shape**: `load_bots` runs before ChatStorage is initialized in `on_startup`, so `add_bot` alone
would leave every startup bot unattached; the sweep inside `_start_turn_persistence` closes that gap. The
`_durable_memory_attached` marker makes `add_bot` + sweep (or a repeated `add_bot`) register exactly one cleaner.
Do not rename `app["turn_persistence"]` (spec M17).

### `manager.py` (MODIFY) — call sites
```python
# add_bot. occurrences: 1 (verified: grep -c '        self._botdef[bot.name] = bot.__class__' S/manager/manager.py)
        self._botdef[bot.name] = bot.__class__
        self._attach_durable_memory(bot)                                   # NEW (manager.py:826)

# add_agent. occurrences: 1 (verified: grep -c '        self._bots[str(agent.chatbot_id)] = agent' S/manager/manager.py)
        self._bots[str(agent.chatbot_id)] = agent
        self._attach_durable_memory(agent)                                 # NEW (manager.py:1315)

# Lazy registrations — one `self._attach_durable_memory(<bot>)` line AFTER each (verify each is a managed bot):
#   occurrences: 1 (verified: grep -c '                    self._bots[agent_name] = instance' ...)   :459  -> (instance)
#   occurrences: 1 (verified: grep -c '            self._bots[new_name] = bot' ...)                   :924  -> (bot)
#   occurrences: 1 (verified: grep -c '        self._bots[name] = new_instance' ...)                  :1058 -> (new_instance)
# FILL IN: for :1058 (reload) the replaced instance's cleaner stays registered but is harmless
#          (`agent_id != bot.name` guard + stale bot); confirm and, if needed, note it in the Completion Note.

# on_startup. occurrences: 1 (verified: grep -c 'self.logger.info("ChatStorage initialized (Redis + DocumentDB)")' ...)  :3240
            self.logger.info("ChatStorage initialized (Redis + DocumentDB)")
            await self._start_turn_persistence(app, chat_storage)            # NEW, inside the existing try

# on_shutdown. occurrences: 1 (verified: grep -c '        # Close ChatStorage' ...)  :3277
        await self._stop_turn_persistence(app)                               # NEW, BEFORE the comment below
        # Close ChatStorage

# setup_registry_only. occurrences: 1 (verified: grep -c 'def setup_registry_only(' ...)  :3130
    def setup_registry_only(
        self,
        app: web.Application,
        *,
        import_modules: bool = False,
        load_definitions: bool = False,
        turn_persistence: bool = False,
    ) -> None:
# docstring Args: `turn_persistence: Also initialize ChatStorage and the turn bus at startup (FEAT-886).`
# occurrences: 1 (verified: grep -c '        app[_REGISTRY_ONLY_APP_KEY] = {"import_modules": import_modules, "load_definitions": load_definitions}' ...)
        app[_REGISTRY_ONLY_APP_KEY] = {
            "import_modules": import_modules,
            "load_definitions": load_definitions,
            "turn_persistence": turn_persistence,
        }
```
Registry-only hooks (NO new `app.on_*` registrations):
```python
# In _registry_only_startup, after `self._cleanup_task = asyncio.create_task(...)`
# (that line has 2 occurrences in the file — use the one inside _registry_only_startup, :3180):
        if opts.get("turn_persistence"):
            await self._start_registry_only_persistence(app)

# In _registry_only_shutdown, before the cleanup-task cancel block (:3182):
        await self._stop_turn_persistence(app)
        # FILL IN: close the ChatStorage this host created (only when registry-only created it) — bounded by
        #          "no leaked connections" and by on_shutdown's `chat_storage.close()` precedent.

# New helper next to the others (<= 15 lines):
    async def _start_registry_only_persistence(self, app: web.Application) -> None:
        """Registry-only hosts have no on_startup: create + initialize ChatStorage, then start the bus."""
        chat_storage = ChatStorage()
        try:
            await chat_storage.initialize()
        except Exception as exc:  # noqa: BLE001
            self.logger.error("ChatStorage initialization failed, turn persistence disabled: %s", exc)
            return
        app["chat_storage"] = chat_storage
        await self._start_turn_persistence(app, chat_storage)
```
**Why**: `setup_registry_only` must stay hook-count-neutral (`test_registry_only_hooks_once` asserts it) and
opt-in (a registry-only tenant host must not suddenly need a writable outbox directory).

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY)
```python
# 1. Imports. occurrences: 1 (verified: grep -c 'from ..memory import RedisConversation' S/handlers/agent.py)  :42
#    DELETE the line (TASK-5568 may already have; re-grep first). Also delete any now-unused `ChatStorage` import (none at baseline).

# 2. Stream persistence block — DELETE it entirely.
#    occurrences: 1 (verified: grep -c '^            # Persist chat turn via ChatStorage$' S/handlers/agent.py)
#    Delete from that comment through the line
#        self.logger.warning("Error scheduling streamed chat turn save: %s", ex)
#    (occurrences: 1, verified: grep -c 'Error scheduling streamed chat turn save' ...), :2807-2863.
#    Keep the `# FEAT-249 Mode B: publish structured outputs ...` block that follows it.

# 3. JSON persistence block — DELETE it entirely.
#    occurrences: 1 (verified: grep -c 'Persist chat turn via ChatStorage (hot + cold)' ...)
#    Delete from that comment through `self.logger.warning("Error scheduling chat turn save: %s", ex)`
#    (occurrences: 1, verified: grep -c 'Error scheduling chat turn save' ...), :3060-3093.
#    Keep the `# FEAT-103: Auto-save data artifact ...` block that follows it.

# 4. Memory plumbing. After TASK-5568, re-grep: `grep -n "memory=memory\|memory: Optional\[Any\]\|memory = None" S/handlers/agent.py`.
#    Baseline hits: :1733 `memory = None`, :1840/:1861/:1880 `memory=memory,`, :2684 `memory: Optional[Any],`,
#    :2738 `memory=memory,`. Remove EVERY remaining one (the bot then reads/writes its own store).
#    `_handle_stream_response` loses its `memory` parameter.

# 5. Forward the client message id. occurrences: 1 (verified: grep -c '                    response: AIMessage = await bot.ask(' ...)  :1869
#    Inside that call, after `output_mode=output_mode,` add:
                        turn_id=client_message_id,
#    and inside `bot.ask_stream(` (occurrences: 1, verified: grep -c '            async for chunk in bot.ask_stream(' ...) :2728
#    after `output_mode=output_mode,` add:
                turn_id=client_message_id,
#    Do NOT touch `bot.followup(...)`: it has its own `turn_id=followup_turn_id`.

# 6. Dead variables. After the deletions, `response_time_ms` is still used by the infographic and response
#    formatters (:2039, :2075, :2965); `tenant` is still forwarded (4 `tenant=tenant,` sites, asserted by
#    test_client_tenant_ignored_and_resolved_tenant_passed). FILL IN: delete only locals that became unused
#    in the two edited methods (check with `ruff check --select F841,F401 S/handlers/agent.py`).
```
**Why**: the bot is the only writer; the handler keeps only the UI-facing reads that live in
`chat_interaction.py` / `threads.py`. `turn_id=client_message_id` makes the id the UI minted the one stored in
ChatStorage (it used to be passed to `save_turn(turn_id=...)`).

### FILL IN checklist
- [ ] `manager.py::_build_durable_memory` — source/allocator selection from `cold_backend` / `hot_redis_client`; bounded by spec §2, §3 M17
- [ ] `manager.py` lazy sites (`:459`, `:924`, `:1058`) — one attach line each; bounded by AC `test_add_bot_attaches_durable_memory`
- [ ] `manager.py::_registry_only_shutdown` — close the ChatStorage this host created; bounded by `test_registry_only_turn_persistence`
- [ ] `handlers/agent.py` — remove only locals that became unused; bounded by `ruff --select F841,F401`
- [ ] `test_agenttalk_tenant_metadata.py` — rewrite per Test Specification; bounded by spec §7 "Test coupling"

---

## Acceptance Criteria

- [ ] `setup_registry_only(app, turn_persistence=True)` starts the bus at startup and stops it at cleanup; the default (`False`) touches neither ChatStorage nor the bus (spec §4 `test_registry_only_turn_persistence`).
- [ ] `test_registry_only_hooks_once` still passes unchanged (no new aiohttp hooks).
- [ ] After startup, `add_bot` / `add_agent` and the lazy registration sites attach publisher, hydration source and sequence allocator; a bot loaded before the bus started is attached by the sweep; a collaborator a bot already carries is kept; with persistence not running nothing is attached (spec §4 `test_add_bot_attaches_durable_memory`).
- [ ] Deleting a conversation through `ChatStorage.delete_conversation` also clears the registered bot's working memory.
- [ ] A bus that fails to start is logged at ERROR, `app["turn_persistence"]` is absent, bots stay unattached and the server finishes startup (Q16).
- [ ] `handlers/agent.py` calls no write method of `ChatStorage` (`store_turn`, `save_turn`, thread/turn writes), no `ConversationMemory` write (`add_turn`, `install_history`, `upsert_turn`) and constructs no `ConversationMemory` — enforced by an AST test (spec §4 `test_agenttalk_has_no_persistence_writes`, §5 "AgentTalk persistence-free").
- [ ] `bot.ask` and `bot.ask_stream` are called with `turn_id=client_message_id`; `bot.followup` is not changed.
- [ ] Mutation check A: re-add a `chat_storage.save_turn(` call (or a `RedisConversation()` construction) to `handlers/agent.py` -> the AST fence goes RED.
- [ ] Mutation check B: drop `self._attach_durable_memory(...)` from `add_bot` -> `test_add_bot_attaches_durable_memory` goes RED.
- [ ] Mutation check C: call `shutdown_turn_persistence` AFTER `chat_storage.close()` in `on_shutdown` (swap the order) -> the lifecycle-order assertion goes RED.
- [ ] `ruff check` is clean on touched files; the existing validation-contract tests listed below still pass.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/manager/test_turn_persistence_wiring.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_agenttalk_no_persistence_writes.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_registry_only.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/manager/test_turn_persistence_wiring.py
import inspect
import pytest
from aiohttp import web
from navigator_eventbus import EventBus

from parrot.bots.base import BaseBot
from parrot.manager.manager import BotManager
from parrot.memory import InMemoryConversation
from parrot.storage import ChatStorage
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.hydration import ChatStorageHydrationSource
from parrot.storage.turn_bus import setup_turn_persistence, shutdown_turn_persistence

pytestmark = pytest.mark.skipif(
    "transport" not in inspect.signature(EventBus.__init__).parameters,
    reason="navigator-eventbus >= 0.4.0 required (EventBus(transport=...))",
)


class _HotTier(InMemoryConversation):
    """Stand-in for the Redis hot tier (the one external service): same upsert contract."""

    async def upsert_turn(self, user_id, session_id, turn, chatbot_id=None):
        # FILL IN: replace-by-turn_id else append, on top of InMemoryConversation — bounded by spec §3 M9 upsert_turn.
        ...


def _manager() -> BotManager:
    return BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True, enable_swagger_api=False)


@pytest.fixture
async def storage(tmp_path):
    backend = ConversationSQLiteBackend(path=str(tmp_path / "conv.db"))
    await backend.initialize()
    return ChatStorage(redis_conversation=_HotTier(), dynamodb=backend)


@pytest.fixture
def wired(monkeypatch, storage):
    """Real manager seams: the ChatStorage factory and the bus (the external service) are injected."""
    calls = {"shutdown": []}
    bus = EventBus(transport="memory")

    async def _setup(cs, **kw):
        return await setup_turn_persistence(cs, bus=bus)

    async def _shutdown(handle):
        calls["shutdown"].append(handle)
        await shutdown_turn_persistence(handle)

    monkeypatch.setattr("parrot.manager.manager.ChatStorage", lambda: storage)
    monkeypatch.setattr("parrot.manager.manager.setup_turn_persistence", _setup)
    monkeypatch.setattr("parrot.manager.manager.shutdown_turn_persistence", _shutdown)
    return calls


async def test_registry_only_turn_persistence(wired):
    app, mgr = web.Application(), _manager()
    mgr.setup_registry_only(app, turn_persistence=True)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        assert app["turn_persistence"].subscription_ids
    finally:
        await runner.cleanup()
    assert len(wired["shutdown"]) == 1


async def test_flag_off_touches_nothing(wired):
    # FILL IN: setup_registry_only(app) (default) -> no "turn_persistence" key, wired["shutdown"] == [].


async def test_add_bot_attaches_durable_memory(wired):
    # FILL IN: after runner.setup(): bot = BaseBot(name="alpha", llm=<offline client>); mgr.add_bot(bot);
    #          bot.turn_publisher is app["turn_persistence"].publisher; isinstance(bot.hydration_source,
    #          ChatStorageHydrationSource); bot.sequence_allocator is not None.
    #          Also: a bot added BEFORE runner.setup() is attached by the sweep; a bot built with its own
    #          turn_publisher keeps it; a second add_bot of the same bot registers one cleaner only.


async def test_no_persistence_means_no_attachment():
    # FILL IN: setup_registry_only(app) without the flag; add_bot -> all three attributes stay None.


async def test_conversation_delete_clears_bot_working_memory(wired, storage):
    # FILL IN: bot with InMemoryConversation holding a history for ("u","s", chatbot_id=bot.memory_key_id);
    #          await storage.delete_conversation("u", "s", agent_id=bot.name) -> bot memory get_history is None.


async def test_bus_start_failure_does_not_block_startup(monkeypatch, caplog, storage):
    # FILL IN: patch parrot.manager.manager.setup_turn_persistence to raise RuntimeError("outbox unset");
    #          runner.setup() succeeds; "turn_persistence" not in app; an ERROR record is logged;
    #          add_bot leaves the three attributes None.


async def test_shutdown_stops_bus_before_closing_storage(wired, storage):
    # FILL IN: record call order of shutdown_turn_persistence vs storage.close(); bus first (mutation target C).
```
```python
# packages/ai-parrot-server/tests/handlers/test_agenttalk_no_persistence_writes.py
import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "handlers" / "agent.py"
_FORBIDDEN_CALLS = {"store_turn", "save_turn", "add_turn", "install_history", "upsert_turn",
                    "put_turn", "update_thread", "create_conversation", "update_conversation_title"}
_FORBIDDEN_NAMES = {"RedisConversation", "InMemoryConversation", "FileConversationMemory", "ConversationMemory"}


def _tree() -> ast.Module:
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def test_agenttalk_has_no_persistence_writes():
    """AST fence (spec §5 'AgentTalk persistence-free'): no write call, no memory construction/import."""
    tree = _tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in _FORBIDDEN_CALLS, f"line {node.lineno}: .{node.func.attr}()"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in _FORBIDDEN_NAMES, f"line {node.lineno}: {node.func.id}()"
        if isinstance(node, ast.ImportFrom):
            assert not _FORBIDDEN_NAMES & {a.name for a in node.names}, f"line {node.lineno}"
        if isinstance(node, ast.ClassDef):
            assert not _FORBIDDEN_NAMES & {getattr(b, "id", getattr(b, "attr", "")) for b in node.bases}


def test_bot_calls_forward_client_message_id_and_no_memory():
    """bot.ask / bot.ask_stream carry turn_id=client_message_id and no memory= kwarg."""
    # FILL IN: walk Call nodes whose func.attr in {"ask", "ask_stream"}; assert a keyword turn_id whose value is
    #          Name("client_message_id") and no keyword named "memory". `followup` is excluded on purpose.


async def test_stream_handler_forwards_turn_id_and_never_touches_storage():
    # FILL IN: reuse the _StreamResponse / _Bot / SimpleNamespace harness of test_agenttalk_tenant_metadata.py with a
    #          storage double whose every method raises AssertionError; call AgentTalk._handle_stream_response(
    #          ..., client_message_id="m-1") -> bot.calls[0]["turn_id"] == "m-1"; storage never touched.
```
```python
# packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py  (MODIFY)
# KEEP test_client_tenant_ignored_and_resolved_tenant_passed unchanged (tenant=tenant, count == 4).
# REPLACE test_save_turn_metadata_both_paths and test_stream_save_turn_receives_resolved_tenant_metadata:
async def test_tenant_and_usage_reach_the_turn_event_presentation():
    """The metadata the handler used to hand to save_turn now rides the bot's event presentation (spec §7)."""
    # FILL IN: real BaseBot (offline RecordingClient returning AIMessage(usage=CompletionUsage(prompt_tokens=3,
    #          completion_tokens=5, estimated_cost=0.42), model="test-model", provider="test-provider")) with a
    #          recording TurnPublisher; `await bot.ask("hello", user_id="u", session_id="s", tenant="acme")`;
    #          event.presentation["tenant"] == "acme"; ["model"] == "test-model"; ["provider"] == "test-provider";
    #          ["cost_usd"] == 0.42; ["usage"]["total_tokens"] == 8. Mutation: bind no tenant -> RED.


async def test_stream_handler_forwards_resolved_tenant_to_bot():
    # FILL IN: the first half of the old streaming test (bot.calls[0]["tenant"] == "acme") WITHOUT the chat_storage
    #          double; assert agent_module has no `save_turn` attribute use (covered by the AST test).
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at `sdd/specs/durable-conversation-memory.spec.md` (Module 17; §2 Piece 1; §7 "Studio and registry-only hosts", "Test coupling"; Q16)
3. **Check dependencies** — TASK-5568, TASK-5581, TASK-5582, TASK-5583 must be `"done"` in
   `sdd/tasks/index/durable-conversation-memory.json`
4. **Verify the Codebase Contract** — confirm imports/signatures; re-run every `# occurrences` grep
   (TASK-5568 already changed `handlers/agent.py`); update the contract FIRST if anything moved
5. **Update status** in the per-spec index -> `"in-progress"` (set `started_at`)
6. **Implement** from the Blueprint; complete every `# FILL IN:`
7. **Verify** all acceptance criteria, including the three mutation checks
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5584 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

BotManager: _DurableMemory + per-bot memory cleaner, _build_durable_memory / _start_turn_persistence / _stop_turn_persistence / _attach_durable_memory / _start_registry_only_persistence, setup_registry_only(turn_persistence=False) opt-in (hook count unchanged), attachment in add_bot / add_agent / the three lazy registration sites / a post-start sweep, bus stopped before ChatStorage closes (on_shutdown and registry-only shutdown, which also closes the ChatStorage it created), bus start failure logged at ERROR without blocking startup. AgentTalk: both chat_storage.save_turn blocks removed, turn_id=client_message_id forwarded to bot.ask / bot.ask_stream (followup untouched).

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-11-13
**Tests**: ai-parrot-server: test_turn_persistence_wiring 7 + test_agenttalk_no_persistence_writes 3 + test_agenttalk_tenant_metadata (rewritten) + test_agenttalk_memory_injection + test_registry_only (incl. hooks-once) = 22 passed; real BotManager on a real aiohttp app, real EventBus(transport="memory"), real SQLite cold tier; the hot tier is an in-file InMemoryConversation subclass (Redis is the external service). ruff (E9,F63,F7,F82,F401,F841) clean.
**Mutation evidence**: add_bot without attachment -> RED (2); ChatStorage closed before the bus -> RED; re-adding a RedisConversation import to the handler -> AST fence RED; dropping the on_startup start call was checked by hand (the startup path is only covered through the registry-only flag, i.e. test_registry_only_turn_persistence). Restored by re-applying edits.
**Notes**: (1) the old save_turn-metadata tests in test_agenttalk_tenant_metadata.py were rewritten: the usage/cost/tenant/agent metadata they pinned is now the bot's TurnPresentation (covered by TASK-5583 tests); the stream-handler test now asserts tenant + turn_id forwarding and that the handler touches no storage. (2) A reloaded bot (reload_agent) leaves the replaced instance's cleaner registered; it is harmless (same agent-name guard, the stale bot's memory just no longer matters). (3) The default `on_startup` path (non-registry-only) is wired but only exercised through code shared with the registry-only path.

**Deviations from spec**: none
