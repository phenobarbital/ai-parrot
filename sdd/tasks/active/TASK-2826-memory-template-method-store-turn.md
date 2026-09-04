# TASK-2826: `ConversationMemory.add_turn` template method + backend `_store_turn` (normalize → count → offload → one write)

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2820, TASK-2821, TASK-2822, TASK-2823 *(external prerequisite: FEAT-524 merged — see banner)*
**Assigned-to**: unassigned

> ⚠️ **FEAT-524 prerequisite (spec C14 / §7 "Known Risks").** The template
> method calls `super().__init__()`-initialised state. On `dev` (2026-09-04)
> `RedisConversation.__init__` (:13-28) and `FileConversationMemory.__init__`
> (:12-15) do **not** call `super().__init__()`; FEAT-524 adds it
> (FEAT-524 branch: `redis.py:19`, `file.py:13`, `mem.py:9`). Confirm all
> three call `super().__init__()` on your branch before starting; if not,
> STOP — this task must not land before FEAT-524.

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
from parrot.memory.abstract import ConversationMemory, ConversationHistory, ConversationTurn   # dev: memory/abstract.py:135, 51, 11 (FEAT-524 branch :189, :130, :17)
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
# packages/ai-parrot/src/parrot/memory/abstract.py  (dev @ f3a5fe7ea)
class ConversationMemory(ABC):                                                  # :135
    def __init__(self, debug: bool = False)                                     # :138  self.logger (:139), self._json = JSONContent() (:142), self.debug
    @abstractmethod async def create_history(self, user_id, session_id, metadata=None, chatbot_id=None)   # :146
    @abstractmethod async def get_history(self, user_id, session_id, chatbot_id=None)                     # :157
    @abstractmethod async def update_history(self, history) -> None                                       # :167
    @abstractmethod async def add_turn(self, user_id, session_id, turn, chatbot_id=None) -> None          # :172  ← becomes concrete
    @abstractmethod async def clear_history(self, user_id, session_id, chatbot_id=None) -> None           # :183
    @abstractmethod async def list_sessions(self, user_id, chatbot_id=None) -> List[str]                  # :193
    @abstractmethod async def delete_history(self, user_id, session_id, chatbot_id=None) -> bool          # :202
class ConversationHistory: metadata: Dict[str, Any] = field(default_factory=dict)   # :59 — home of metadata["compaction"]; add_turn(turn) :61

# packages/ai-parrot/src/parrot/memory/mem.py  (dev)
class InMemoryConversation(ConversationMemory):                                # :5
    def __init__(self): super().__init__(); self._histories = {}              # :8-10
    def _get_chatbot_key(self, chatbot_id) -> str   # "_default" when None     # :12
    async def add_turn(self, user_id, session_id, turn, chatbot_id=None)       # :65-75  history = await self.get_history(...); history.add_turn(turn)
    async def clear_history(...)                                               # :77-86
    async def delete_history(...) -> bool                                      # :107

# packages/ai-parrot/src/parrot/memory/redis.py  (dev)
class RedisConversation(ConversationMemory):                                   # :10
    def __init__(self, redis_url=None, key_prefix="conversation", use_hash_storage=True)   # :13-28  self.redis = Redis.from_url(..., decode_responses=True) :22
    def _get_key(self, user_id, session_id, chatbot_id=None) -> str           # :31
    def _serialize_data(self, data) -> str / _deserialize_data(self, data)    # :56 / :66
    async def get_history(...)   # hash mode: hgetall; 'metadata': self._deserialize_data(data.get('metadata','{}'))   # :126-150
    async def update_history(history)   # hash mode mapping incl. 'metadata': self._serialize_data(...) ; one hset   # :170-191
    async def add_turn(...)      # :193-228  hash mode: hget 'turns' → append → hset mapping {'turns','updated_at'[,'chatbot_id']} (:222)
    async def clear_history(...) # :230-252  hash mode resets 'turns' via hset
    async def delete_history(...) -> bool   # :266-279  delete key + srem sessions set
# FEAT-524 branch: __init__ calls super().__init__() at :19; add_turn at :255 (lines shift) — re-verify

# packages/ai-parrot/src/parrot/memory/file.py  (dev)
class FileConversationMemory(ConversationMemory):                              # :9
    def __init__(self, base_path: str = "./conversations")                     # :12-15  self.base_path = Path(...); self._lock = asyncio.Lock()
    async def update_history(history)   # async with self._lock: aiofiles write json.dumps(history.to_dict(), default=str)   # :72-81
    async def add_turn(...)             # :83-94  get_history → history.add_turn → update_history
    async def clear_history(...) :96 ; async def delete_history(...) :142
# FEAT-524 branch: super().__init__() at :13; add_turn at :144 — re-verify

# packages/ai-parrot/src/parrot/storage/chat.py (dev): self._redis = RedisConversation(key_prefix="chat") :54 ; await self._redis.add_turn(...) :209
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
- Google-style docstrings; `self.logger`, never `print` (the existing `print` in `redis.py:150` is pre-existing — leave it).

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/abstract.py` — FEAT-391 `execute()` → `_execute()` template-method precedent.
- `packages/ai-parrot/src/parrot/memory/redis.py:170-191` — hash-mode mapping incl. `metadata`.

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
2. **Check dependencies** — TASK-2820, 2821, 2822, 2823 in `sdd/tasks/completed/`; FEAT-524 merged (banner)
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2826-memory-template-method-store-turn.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below (record the §8 cascade decision you took)

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
