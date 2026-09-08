# TASK-2826: `ConversationMemory.add_turn` template method + backend `_store_turn` (normalize → count → offload → one write)

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2820, TASK-2821, TASK-2822, TASK-2823
**Assigned-to**: unassigned

> ✅ **FEAT-524 merged** (PR #1310, merge `729ef7367`, 2026-09-04). Every
> FEAT-524 anchor below was re-verified on `dev` @ `198e6fecd` (after the
> post-merge `black` reformat `4831528a4`); `memory/render.py`,
> `ConversationTurn.from_ai_message` and `AbstractBot.memory_key_id` exist.

---

## Context

Spec §2 "Component Diagram" (write path), §3 Module 5, goals G2/G4/G11 and
the resolved decisions "Write-time offload", "Calibration pairing" and
"commit travels into `add_turn`". This is the FEAT-391-style "concrete
public, abstract private" template: every writer (bot, `ChatStorage`
`key_prefix="chat"` tier, voice transcripts) gets Stage 0 + Stage 0.5 +
oversize offload for free, and the turn plus `metadata["compaction"]` land
in **one** backend write.

---

## Scope

- `memory/abstract.py` — `ConversationMemory`:
  - `__init__(self, debug: bool = False, *, token_counter: Optional[TokenCounter] = None,
    omission_store: Optional[OmissionStore] = None, normalize: bool = True,
    oversize_tool_tokens: int = 2_000)`; store `self._token_counter`
    (default `get_default_counter()`), `self._omission_store` (may stay
    `None` until the backend sets its default), `self._normalize`,
    `self._oversize_tool_tokens`. Keep `self.logger`, `self._json`, `self.debug`.
  - properties `token_counter` and `omission_store` (the latter falls back to
    a lazily-created `InMemoryOmissionStore` with a warning if a backend never
    set one).
  - `omission_key(user_id, session_id, chatbot_id) -> str` =
    `f"{chatbot_id or '_default'}:{user_id}:{session_id}"`.
  - **Concrete** `async def add_turn(self, user_id, session_id, turn, chatbot_id=None, *,
    compaction: Optional[CompactionCommit] = None) -> None` implementing, in
    order: (1) `if self._normalize: turn = normalize_turn(turn)`;
    (2) `if needs_recount(turn, counter): turn.token_count = count_turn(turn, counter)`;
    (3) for each `inv` in `turn.tool_invocations` with `inv.output` and
    `"output" not in inv.omitted` and `counter.count(inv.output) > self._oversize_tool_tokens`:
    `cid = await self.omission_store.put(key, inv.output, turn_id=turn.turn_id)`;
    `inv.output_chars = len(inv.output)`; `inv.output = _preview(inv.output)`;
    `inv.omitted["output"] = cid`; then recount (`turn.token_count = count_turn(...)`);
    (4) `turn.schema_version = 2`; (5) `state = None`; if `compaction` is
    given: `prev = await self._get_compaction_state(user_id, session_id, chatbot_id)`;
    `state = apply_commit(CompactionState.from_dict(prev) if prev else None, compaction,
    counter.name, _provider_prompt_tokens(turn)).to_dict()`;
    (6) `await self._store_turn(user_id, session_id, turn, chatbot_id, compaction_state=state)`.
  - `_preview(text: str, max_chars: int = 200) -> str` module-level helper:
    `text[:max_chars] + f" …(+{len(text) - max_chars:,} chars)"` when longer, else unchanged.
  - `_provider_prompt_tokens(turn) -> Optional[int]`: `turn.metadata.get("usage")`
    → `usage.get("input_tokens")` else `usage.get("prompt_tokens")` (FEAT-524
    stores `CompletionUsage.model_dump()`, which emits both names); non-dict / missing → `None`.
  - **Abstract** `async def _store_turn(self, user_id, session_id, turn, chatbot_id=None, *,
    compaction_state: Optional[Dict[str, Any]] = None) -> None`.
  - Concrete, overridable `async def _get_compaction_state(self, user_id, session_id, chatbot_id) -> Optional[Dict[str, Any]]`:
    default `history = await self.get_history(...)`; return `history.metadata.get("compaction")` or `None`.
  - `async def report_usage(self, user_id, session_id, *, estimated_prompt_tokens: int,
    provider_prompt_tokens: Optional[int], chatbot_id=None) -> None`:
    load history, `state = apply_usage(CompactionState.from_dict(prev) if prev else
    CompactionState(tokenizer=counter.name), estimated_prompt_tokens, provider_prompt_tokens)`,
    write `history.metadata["compaction"] = state.to_dict()`, `await self.update_history(history)`.
  - `clear_history` / `delete_history` cascade — **decision for this task
    (spec §8 open item)**: keep them abstract; each backend calls
    `await self.omission_store.clear(self.omission_key(user_id, session_id, chatbot_id))`
    after its own clear/delete. (Template wrappers are the alternative; either is acceptable, tested the same way.)
- `memory/mem.py`: rename `add_turn` → `_store_turn` (+ `compaction_state`:
  `history.metadata["compaction"] = compaction_state` when not `None`, same
  assignment step); `__init__(self, *, token_counter=None, omission_store=None, normalize=True)`
  passing through to `super().__init__` with `omission_store or InMemoryOmissionStore()`;
  cascade in `clear_history`/`delete_history`.
- `memory/redis.py`: `__init__(..., token_counter=None, omission_store=None, normalize=True, omission_ttl=None)`;
  default `RedisOmissionStore(self.redis, key_prefix=self.key_prefix, ttl=omission_ttl)`
  (constructed **after** `self.redis`); rename `add_turn` → `_store_turn`;
  hash mode: `hget turns` → append → `mapping = {'turns', 'updated_at'[, 'chatbot_id']}` and, when
  `compaction_state` is not `None`: `meta = self._deserialize_data(await self.redis.hget(key, 'metadata') or '{}')`,
  `meta['compaction'] = compaction_state`, `mapping['metadata'] = self._serialize_data(meta)`;
  **exactly one `hset`**. Non-hash mode: `get_history` → `add_turn` → set metadata → `update_history` (one `set`).
  Override `_get_compaction_state` with a single `hget(key, 'metadata')` in hash mode (optional but recommended).
  Cascade in `clear_history`/`delete_history`.
- `memory/file.py`: `__init__(self, base_path="./conversations", *, token_counter=None, omission_store=None, normalize=True)`;
  default `FileOmissionStore(self.base_path)`; rename `add_turn` → `_store_turn` (get → add → metadata → `update_history`, one file rewrite); cascade.
- Tests in `packages/ai-parrot/tests/unit/memory/compaction/test_memory_template.py`
  (parametrized over the three backends; Redis via a recording fake client
  injected as `RedisConversation.redis` or skipped when unreachable — follow
  `tests/test_chat_storage.py`).

**NOT in scope**: the bot side (`save_conversation_turn(compaction=)`,
TASK-2830); `compact_history` (TASK-2828); any change to `storage/chat.py`
(it inherits everything via `RedisConversation(key_prefix="chat")`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/abstract.py` | MODIFY | `ConversationMemory` constructor options, properties, `omission_key`, concrete `add_turn`, abstract `_store_turn`, `_get_compaction_state`, `report_usage`, helpers |
| `packages/ai-parrot/src/parrot/memory/mem.py` | MODIFY | `_store_turn`, constructor kwargs, cascade |
| `packages/ai-parrot/src/parrot/memory/redis.py` | MODIFY | `_store_turn` (one `hset` incl. `metadata`), constructor kwargs + `omission_ttl`, `_get_compaction_state`, cascade |
| `packages/ai-parrot/src/parrot/memory/file.py` | MODIFY | `_store_turn`, constructor kwargs, cascade |
| `packages/ai-parrot/tests/unit/memory/compaction/test_memory_template.py` | CREATE | order, offload/preview, single write, cascade, `normalize=False`, chat tier counted-not-compacted, `report_usage` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use only what is listed here. Verify anything else before using it.

### Verified Imports
```python
from parrot.memory.abstract import ConversationMemory, ConversationHistory, ConversationTurn   # dev 198e6fecd: memory/abstract.py:191, 130, 16
from parrot.memory import InMemoryConversation, RedisConversation, FileConversationMemory       # dev: memory/__init__.py:10-12
from parrot.memory.compaction.models import CompactionCommit, CompactionState, ToolInvocation, TokenCount   # TASK-2819
from parrot.memory.compaction.normalize import normalize_turn                                    # TASK-2820
from parrot.memory.compaction.tokens import TokenCounter, count_turn, needs_recount, get_default_counter, HeuristicCounter   # TASK-2821
from parrot.memory.compaction.omission import OmissionStore, InMemoryOmissionStore, RedisOmissionStore, FileOmissionStore   # TASK-2822
from parrot.memory.compaction.budget import apply_commit, apply_usage                            # TASK-2823
from datamodel.parsers.json import JSONContent                                                   # dev: memory/abstract.py:6 (self._json)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/abstract.py  (dev @ 198e6fecd — FEAT-524 merged)
class ConversationMemory(ABC):                                                  # :191
    def __init__(self, debug: bool = False)                                     # :194  self.logger (:195), self._json = JSONContent() (:196), self.debug
    @abstractmethod async def create_history(self, user_id, session_id, metadata=None, chatbot_id=None)   # :200
    @abstractmethod async def get_history(self, user_id, session_id, chatbot_id=None)                     # :207
    @abstractmethod async def update_history(self, history) -> None                                       # :214
    @abstractmethod async def add_turn(self, user_id, session_id, turn, chatbot_id=None) -> None          # :219  ← becomes concrete
    @abstractmethod async def clear_history(self, user_id, session_id, chatbot_id=None) -> None           # :226
    @abstractmethod async def list_sessions(self, user_id, chatbot_id=None) -> List[str]                  # :231
    @abstractmethod async def delete_history(self, user_id, session_id, chatbot_id=None) -> bool          # :236
class ConversationHistory: metadata: Dict[str, Any] = field(default_factory=dict)   # :139 — home of metadata["compaction"]; add_turn(turn) :141

# packages/ai-parrot/src/parrot/memory/mem.py  (dev)
class InMemoryConversation(ConversationMemory):                                # :5
    def __init__(self): super().__init__(); self._histories = {}              # :8-10
    def _get_chatbot_key(self, chatbot_id) -> str   # "_default" when None     # :12
    async def add_turn(self, user_id, session_id, turn, chatbot_id=None)       # :65-75  history = await self.get_history(...); history.add_turn(turn)
    async def clear_history(...)                                               # :77-86
    async def delete_history(...) -> bool                                      # :107

# packages/ai-parrot/src/parrot/memory/redis.py  (dev @ 198e6fecd — FEAT-524 merged)
class RedisConversation(ConversationMemory):                                   # :10
    def __init__(self, redis_url=None, key_prefix="conversation", use_hash_storage=True)   # :13  super().__init__() :14 ; self.redis = Redis.from_url(..., decode_responses=True) :18-23
    def _get_key(self, user_id, session_id, chatbot_id=None) -> str           # :27
    def _serialize_data(self, data) -> str / _deserialize_data(self, data)    # :43 / :53
    async def get_history(...)   # :107-147  FEAT-524 lazy legacy re-key: when the segmented key is empty it reads the legacy key via
                                 #   _load_history(user_id, session_id, None) (:149) and WRITES it back under the segmented key (update_history :142)
    async def update_history(history)   # :200-221  hash mode mapping incl. 'metadata': self._serialize_data(...) ; one hset (:217)
    async def add_turn(...)      # :223-251  hash mode: hget 'turns' → append → hset mapping {'turns','updated_at'[,'chatbot_id']} (:245)
    async def clear_history(...) # :253-273  hash mode resets 'turns' via hset (:262)
    async def delete_history(...) -> bool   # :275  delete key + srem sessions set

# packages/ai-parrot/src/parrot/memory/file.py  (dev @ 198e6fecd)
class FileConversationMemory(ConversationMemory):                              # :9
    def __init__(self, base_path: str = "./conversations")                     # :12-16  super().__init__() :13; self.base_path = Path(...) :14; self._lock = asyncio.Lock() :16
    async def get_history(...)          # :41-76  same lazy legacy re-key as Redis (_read_history :78 / _write_history :104)
    async def update_history(history)   # :114-117 → _write_history (:104, async with self._lock: aiofiles write)
    async def add_turn(...)             # :119-126  get_history → history.add_turn → update_history
    async def clear_history(...) :128 ; async def delete_history(...) :165

# packages/ai-parrot/src/parrot/storage/chat.py (dev): self._redis = RedisConversation(key_prefix="chat") :55 ;
#   await self._redis.add_turn(user_id, session_id, turn, chatbot_id=agent_id) :204  ← chat tier passes chatbot_id=agent_id (omission_key uses it)
#   get_context_for_agent now uses render_history (:636) — FEAT-524 fixed the stale get_messages_for_api call
# packages/ai-parrot/src/parrot/models/basic.py: CompletionUsage.model_dump() emits BOTH prompt_tokens and input_tokens (docstring :48-62; populate_by_name :72)
# Redis test precedent: packages/ai-parrot/tests/test_chat_storage.py (skip when Redis unreachable)
```

### Does NOT Exist
- ~~`ConversationMemory._store_turn` / `report_usage` / `omission_store` / `token_counter` / `omission_key` / `_get_compaction_state`~~ — new here.
- ~~`ConversationMemory.add_turn` being concrete~~ — abstract on dev (:172); this task makes it concrete. After this task, **no subclass may override `add_turn`** (hard cut; all three in-repo backends updated here; no external consumers).
- ~~`RedisConversation(omission_ttl=…)`~~ / ~~`InMemoryConversation(token_counter=…)`~~ — kwargs added here.
- ~~A TTL on Redis history keys~~ — none; `omission_ttl` applies to the omission store only.
- ~~`ChatStorage` compaction~~ — never; the chat tier is normalized + counted + offloaded only (non-goal).
- ~~`apply_commit(state, commit, tokenizer)` with three params~~ — TASK-2823 defines `apply_commit(state, commit, tokenizer, provider_prompt_tokens)`; pass the provider count read from `turn.metadata["usage"]`.

---

## Implementation Notes

### Pattern to Follow
```python
# abstract.py — import cycle guard: compaction.normalize/tokens/omission/budget import
# ConversationTurn from THIS module, so import them lazily inside the methods (or at
# the bottom of the module), never at the top.
async def add_turn(self, user_id, session_id, turn, chatbot_id=None, *, compaction=None) -> None:
    from .compaction.normalize import normalize_turn
    from .compaction.tokens import count_turn, needs_recount
    from .compaction.budget import apply_commit
    from .compaction.models import CompactionState
    counter = self.token_counter
    if self._normalize:
        turn = normalize_turn(turn)
    if needs_recount(turn, counter):
        turn.token_count = count_turn(turn, counter)
    key = self.omission_key(user_id, session_id, chatbot_id)
    offloaded = False
    for inv in turn.tool_invocations:
        if inv.output and "output" not in inv.omitted and counter.count(inv.output) > self._oversize_tool_tokens:
            cid = await self.omission_store.put(key, inv.output, turn_id=turn.turn_id)
            inv.output_chars = len(inv.output); inv.output = _preview(inv.output); inv.omitted["output"] = cid
            offloaded = True
    if offloaded:
        turn.token_count = count_turn(turn, counter)
    turn.schema_version = 2
    state = None
    if compaction is not None:
        prev = await self._get_compaction_state(user_id, session_id, chatbot_id)
        state = apply_commit(CompactionState.from_dict(prev) if prev else None, compaction,
                             counter.name, _provider_prompt_tokens(turn)).to_dict()
    await self._store_turn(user_id, session_id, turn, chatbot_id, compaction_state=state)
```

### Key Constraints
- `normalize_turn` returns a **new** turn (TASK-2820) — rebind `turn`; the caller's object is not mutated by Stage 0, but the offload step mutates `ToolInvocation`s of the (new) turn — acceptable, they belong to the stored copy.
- `CompactionState.to_dict/from_dict` — reuse whatever TASK-2819/2823 provided; do not add a third serializer.
- Redis: **one** `hset` per `_store_turn`; assert with a recording fake (`hset` called once, mapping contains both `turns` and `metadata` when a commit is given).
- `_preview` keeps the first 200 chars so notices and RAW excerpts still show the head of the output.
- Google-style docstrings; `self.logger`, never `print`.
- The default `_get_compaction_state` goes through `get_history`, which may perform the FEAT-524 lazy legacy re-key (a write). Harmless, but the Redis override via `hget(key, 'metadata')` avoids it — implement the override.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/abstract.py` — FEAT-391 `execute()` → `_execute()` template-method precedent.
- `packages/ai-parrot/src/parrot/memory/redis.py:200-221` — hash-mode mapping incl. `metadata`.

---

## Acceptance Criteria

- [ ] `ConversationMemory.add_turn` is concrete; `InMemoryConversation`, `RedisConversation`, `FileConversationMemory` implement `_store_turn` and no longer define `add_turn`.
- [ ] Order test: a spy subclass records `normalize_turn` → `count_turn` → `omission_store.put` → `_store_turn` (called once, with `compaction_state` when a commit is given).
- [ ] Offload: an invocation whose output exceeds `oversize_tool_tokens` is stored (`get` returns the full bytes), the turn keeps a ≤ 200-char preview + ` …(+N chars)`, `omitted["output"] == content_id(original)`, `output_chars == len(original)`, `token_count.tools` is recounted from the preview.
- [ ] Single write (×3 backends): turn **and** `metadata["compaction"]` land together — Redis fake sees exactly one `hset` whose mapping has both `turns` and `metadata`; file backend one write; in-memory one assignment.
- [ ] Cascade (×3): `clear_history`/`delete_history` empty the omission store for that key (`list_by_turn` → `[]`, `get` → `None`).
- [ ] `normalize=False` stores bytes unchanged and leaves `norm_version is None`; `token_count` is still set (counting is always-on).
- [ ] `RedisConversation(key_prefix="chat")` turns get `token_count` + `norm_version`; nothing else changes (chat tier counted, not compacted).
- [ ] `report_usage(...)` updates `metadata["compaction"].calibration` via `apply_usage` without writing a turn.
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/compaction/test_memory_template.py packages/ai-parrot/tests/test_chat_storage.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/abstract.py packages/ai-parrot/src/parrot/memory/mem.py packages/ai-parrot/src/parrot/memory/redis.py packages/ai-parrot/src/parrot/memory/file.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/memory/compaction/test_memory_template.py
import pytest
from parrot.memory import InMemoryConversation, FileConversationMemory, RedisConversation
from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import CompactionCommit, ToolInvocation
from parrot.memory.compaction.omission import content_id
from parrot.memory.compaction.tokens import HeuristicCounter


class _FakeRedis:
    """async hget/hset/hgetall/delete/srem/expire over dicts; records every hset call."""
    ...


@pytest.fixture(params=["memory", "file", "redis"])
def memory(request, tmp_path):
    counter = HeuristicCounter()
    if request.param == "memory": return InMemoryConversation(token_counter=counter)
    if request.param == "file": return FileConversationMemory(str(tmp_path), token_counter=counter)
    m = RedisConversation(redis_url="redis://unused", token_counter=counter); m.redis = _FakeRedis()
    m._omission_store = None  # force default RedisOmissionStore rebuild on the fake client, or construct explicitly
    return m


async def test_write_time_offload_preview(memory):
    big = "x" * 40_000                                               # 10_000 heuristic tokens > 2_000
    turn = ConversationTurn(turn_id="t1", user_id="u", user_message="q", assistant_response="a", chatbot_id="bot",
                            tool_invocations=[ToolInvocation(tool_name="query", input={}, output=big)])
    await memory.create_history("u", "s", chatbot_id="bot")
    await memory.add_turn("u", "s", turn, chatbot_id="bot")
    stored = (await memory.get_history("u", "s", chatbot_id="bot")).turns[-1]
    inv = stored.tool_invocations[0]
    assert inv.omitted["output"] == content_id(big) and inv.output_chars == 40_000 and inv.output.startswith("x" * 200)
    assert await memory.omission_store.get(memory.omission_key("u", "s", "bot"), inv.omitted["output"]) == big
    assert stored.schema_version == 2 and stored.token_count.tokenizer == "heuristic" and stored.norm_version == "1"


async def test_single_write_with_metadata_redis():
    m = RedisConversation(redis_url="redis://unused"); fake = m.redis = _FakeRedis(); ...
    await m.add_turn("u", "s", turn, chatbot_id="bot", compaction=CompactionCommit(100, "t0", False))
    assert len(fake.hset_calls) == 1 and {"turns", "metadata"} <= set(fake.hset_calls[0]["mapping"])


async def test_clear_delete_cascade(memory):
    ...  # offload one output, then clear_history → list_by_turn == [] ; repeat with delete_history


async def test_normalize_off_escape_hatch(tmp_path):
    m = InMemoryConversation(normalize=False, token_counter=HeuristicCounter())
    ...  # user_message with trailing spaces survives; norm_version is None; token_count set
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2820, 2821, 2822, 2823 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2826-memory-template-method-store-turn.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below (record the §8 cascade decision you took)

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-04
**Notes**: Made `ConversationMemory.add_turn` concrete (normalize → count
→ offload oversized outputs → `schema_version=2` → `apply_commit` →
`_store_turn`); added abstract `_store_turn`, concrete overridable
`_get_compaction_state`, `report_usage`, `token_counter`/`omission_store`
properties (lazy default resolution), `omission_key`. Cascade decision
(spec §8 open item): **explicit `omission_store.clear()` call in each
backend's `clear_history`/`delete_history`** (not template wrappers) —
simpler, and the three backends' clear/delete bodies already differ
enough (hash-mode vs full-rewrite) that a shared wrapper would need its
own backend hook anyway. Renamed `add_turn` → `_store_turn` in
`mem.py`/`redis.py`/`file.py`; Redis does exactly one `hset` per write
(read-modify-write on the existing `metadata` blob for `compaction_state`)
and overrides `_get_compaction_state` with a single targeted `hget` to
skip the FEAT-524 lazy legacy re-key. Constructors gained
`token_counter`/`omission_store`/`normalize` (+ Redis `omission_ttl`);
each backend builds its matching default store (`InMemoryOmissionStore`/
`RedisOmissionStore(self.redis, ...)`/`FileOmissionStore(self.base_path)`).
Resolved the `abstract.py` import-cycle guard: `CompactionCommit`/
`CompactionState`/`OmissionStore`/`InMemoryOmissionStore`/`apply_commit`/
`apply_usage` (none of their modules import `abstract.py`) are imported
at module level; `normalize_turn`/`count_turn`/`needs_recount`/
`get_default_counter`/`TokenCounter` (whose modules import
`ConversationTurn` from `abstract.py`) are lazy-imported inside methods,
with `TokenCounter` under `TYPE_CHECKING` for the type hints. All 13
task-specified tests pass (×3 backends parametrized + Redis-specific +
escape-hatch + chat-tier + report_usage); full `tests/unit/memory/`
regression suite (108 tests) green; `ruff check` clean.

**Deviations from spec**: `tests/test_chat_storage.py` (the task's other
named acceptance-criteria test target) was NOT run as part of the
acceptance gate — it fails to even collect on `dev` before this feature
touched anything (`ImportError: cannot import name
'CONVERSATIONS_COLLECTION' from 'parrot.storage.chat'`), confirmed via
`git show` on the merged FEAT-524 commit `198e6fecd`. Pre-existing,
unrelated to FEAT-525; not fixed here (out of scope — this task does not
touch `storage/chat.py`).
