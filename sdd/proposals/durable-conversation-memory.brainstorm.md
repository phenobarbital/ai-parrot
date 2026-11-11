---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [memory, conversation-history, chat-storage, compaction, stage-2, dynamodb]
---

# Brainstorm: Durable conversation memory — ChatStorage as the agent's memory, Stage 2 summaries

**Date**: 2026-11-11
**Author**: Juan Ruffato (with Claude) — for review by Jesus Lara (author of FEAT-524 / FEAT-525)
**Status**: exploration
**Recommended Option**: A

> Context of origin: Agent Studio (navigator-agent-studio) is moving every agent chat onto the official
> `AgentChat.svelte`, whose history sidebar reads `ChatStorage` (`/api/v1/chat/interactions`). Designing that
> exposed that what the sidebar shows and what the agent actually remembers come from two different stores with
> two different lifetimes. This brainstorm is about the parrot side; it changes nothing in Studio by itself.

---

## Problem Statement

A user looks at a conversation in the UI and keeps talking to the agent. Today there is no guarantee that the
agent remembers any of what the user is looking at.

1. **Two stores, two lifetimes.**
   - What the UI shows: `ChatStorage` (`storage/chat.py:25`). Its hot tier is a `RedisConversation` with
     `key_prefix="chat"` and no TTL. Its cold tier is a pluggable `ConversationBackend`: sqlite by default,
     DynamoDB in AWS production, with a 180-day item TTL. Only AgentTalk writes it, via `save_turn`, as a
     background task (`ai-parrot-server/.../handlers/agent.py:2807-2846`, `:3060-3097`).
   - What the agent remembers: its `ConversationMemory`, picked by `memory_type`. The default is `"memory"`,
     i.e. process RAM (`bots/abstract.py:616`, `bots/chatbot.py:225`, BotModel DDL default `'memory'`).
     Registry agents (`@register_agent`) get that default, and no global setting changes it.
   - Consequence: a restart, a deploy, another pod or another worker loses the agent's context, while the
     sidebar keeps showing the conversation.
2. **Nothing reloads one from the other.** `ChatStorage.get_context_for_agent` (`storage/chat.py:613`) has no
   caller outside tests. FEAT-524 deliberately left `ChatStorage` "untouched — separate tier"
   (`sdd/specs/conversation-history-ownership.spec.md:111`). FEAT-525 listed "a budgeted
   `get_context_for_agent`" as a follow-up (`per-turn-conversation-compaction.spec.md:142-145`).
3. **AgentTalk reads history from one store and writes it to another** (verified statically, not yet at
   runtime).
   - On every request with a `session_id`, `handlers/agent.py:1733-1736` builds a fresh `RedisConversation()`
     (prefix `"conversation"`, no TTL) and passes it as `memory=`.
   - The bot reads history from it: `memory = memory or self.conversation_memory`, at `bots/base.py:765`,
     `:1261`, `:2006` and `bots/data.py:1427` (PandasAgent).
   - But `save_conversation_turn` always writes to `self.conversation_memory` (`bots/abstract.py:2641-2660`).
   - So a default `memory_type="memory"` agent called over HTTP reads an empty Redis key every round. It
     probably sees **no prior turns at all**, even inside one pod's lifetime. Example: `pokemon_finance`
     (`PandasAgent`) on navigator-agent-server.
4. **Old turns are forgotten silently.**
   - FEAT-525 compaction is deterministic only (Stages 0, 0.5 and 1). Past the budget or `max_turns` (30),
     older turns simply drop out of the prompt.
   - Stage 2 (LLM summary turns) is reserved and not implemented. `TurnState.SUMMARIZED` is never produced
     (`memory/compaction/models.py:31-42`), and `Stage2CompactionNeededEvent`
     (`core/events/lifecycle/events/memory.py:14`) has no subscribers.
   - FEAT-538 task recall is a deterministic task snapshot, explicitly "not a summary of the conversation".
5. **What `ChatStorage` stores cannot rebuild an agent turn.**
   - The hot tier stores only tool *names*.
   - The cold tier's `tool_calls` are built with `getattr(t, "status", "completed")` / `getattr(t, "output",
     None)` (`handlers/agent.py:2827-2834`, `:3077-3085`). But `parrot.models.ToolCall` has `result`, `error`,
     `execution_time` (`models/basic.py:23-30`), so every persisted tool call is `status="completed"` with
     `output=None`.
   - FEAT-525 fields (`tool_invocations`, `error`, `token_count`, `state`) are not persisted to the cold tier.
6. **Smaller defects found on the way.**
   - `ask_stream` saves turns without `compaction=` (`bots/base.py:2234`), so streamed rounds never update
     boundary, calibration or `stage2_needed`.
   - `HOT_TTL_HOURS = 48` (`storage/chat.py:20`) is defined and never used.
   - `ChatStorage.delete_turn` deletes only from the cold tier.
   - The FEAT-525 spec's note about a stale `get_messages_for_api()` call at `chat.py:638` is outdated:
     FEAT-524 already replaced it.

The reference model is how a long-running assistant such as Claude Code works:
- the full transcript is durable;
- the working context is a summary of the old part plus the recent turns;
- the summary itself is durable;
- an exact detail can be re-read from the transcript.

Parrot has the durable transcript (cold tier), the recent-turn window and the re-read tool
(`read_omitted_content`). It is missing the bridge between transcript and working memory, and the summary.

## Constraints & Requirements

- **One source of truth per conversation.** What the UI lists for `(user, session, agent)` and what the agent
  is given as context must come from the same records.
- **Survive restarts, deploys, multi-pod and multi-worker**, without sticky sessions.
- **Keep FEAT-524 / FEAT-525 contracts.**
  - The bot owns history; clients stay memory-less.
  - `add_turn` stays the single write path (Stage 0 normalize, 0.5 count, offload).
  - `metadata.compaction` is written atomically with the turn.
  - `PARROT_COMPACTION_DISABLED` / `context_budget=False` keep the plain path.
- **No silent forgetting.** When old turns leave the prompt, a summary of them must take their place, and
  the exact content must stay recoverable.
- **Backend-agnostic.** Use FEAT-116 `ConversationBackend` (sqlite / postgres / mongo / dynamodb). DynamoDB is
  what AWS production uses.
- **Bounded cost.**
  - No full-history read on every round once warm.
  - A summary costs one extra LLM call per compaction event, not per turn.
- **Tenant and user isolation.** Keys stay scoped by `(chatbot_id, user_id, session_id)`, as they are today.
- **Backwards-safe rollout.** Existing `memory`/`file`/`redis` users keep working. A new default needs an
  explicit decision (open question).

---

## Options Explored

### Option A: `ChatStorage` becomes the agent's memory (one write path, rehydrate on miss)

Add a `ConversationMemory` backend over `ChatStorage`, e.g. `memory_type="chat_storage"`. Every turn the bot
saves goes through `add_turn` once, which writes:
- the hot tier: the existing `RedisConversation(key_prefix="chat")`, with turn and compaction state together;
- the cold tier: `ConversationBackend.put_turn` with the **full** `ConversationTurn` payload
  (`tool_invocations`, `error`, `token_count`, `state`, `schema_version`, `metadata.compaction`).

Reads go to the hot tier. On a miss, the conversation is rehydrated from the cold tier into the hot tier (only
the turns after the last summary boundary plus the summary turn, see Stage 2), and then served.

AgentTalk stops its separate `save_turn` and stops injecting a throw-away `RedisConversation()`. The handler
and the bot then read and write the same store. The UI endpoints (`chat_interaction.py`, `threads.py`) keep
reading `ChatStorage`, and now see exactly what the agent remembers.

Stage 2 lives inside this option:
- **Trigger.** When `stage2_needed` flips (the existing persisted flag and `Stage2CompactionNeededEvent`),
  turns older than the boundary are summarized by an LLM.
- **Storage.** The summary is stored as a `ConversationTurn(state=SUMMARIZED)` covering a turn range, in both
  tiers.
- **Rendering.** `compact_history` renders the summary turn in place of the dropped turns.
- **Exact content.** It stays in the cold tier and can be re-read through `read_omitted_content`.
- **Omissions.** The omission store gets a cold-tier implementation, so offloaded tool outputs survive the
  Redis key.

✅ **Pros:**
- One write path and one source of truth; UI and agent cannot diverge.
- Removes the AgentTalk read/write mismatch by construction.
- Survives restarts and multi-pod deployments (hot tier shared, cold tier durable).
- Reuses almost everything: `RedisConversation`, `ConversationBackend`, `add_turn`, compaction state, the
  Stage-2 flag and event, `read_omitted_content`.

❌ **Cons:**
- Touches the hottest path (every bot round) and the `ChatStorage` contract that FEAT-524 kept separate.
- The cold-tier turn schema grows (full turn payload). Existing rows are old-shape and need a tolerant reader.
- Needs `app["chat_storage"]` (or an equivalent) wherever bots run, including registry-only hosts such as Agent
  Studio, where `setup_registry_only` (`manager/manager.py:3130`) does not install it.
- `RedisConversation` appends with an O(n) read-modify-write of the whole turn list (`memory/redis.py:493-608`).
  Fine with Stage 2 bounding the live window; worth measuring.

📊 **Effort:** High (phased; see Recommendation)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | `RedisConversation`, FEAT-116 backends, FEAT-525 compaction already exist |

🔗 **Existing Code to Reuse:**
- `parrot/storage/chat.py` — `ChatStorage` hot/cold wiring, `load_conversation` (Redis-first, cold fallback).
- `parrot/memory/redis.py` — `RedisConversation` (hash layout, CAS append, `history_ttl`).
- `parrot/storage/backends/*` — `ConversationBackend.put_turn` / `query_turns`.
- `parrot/memory/abstract.py:440-535` — `add_turn` template + `_store_turn(..., compaction_state=)`.
- `parrot/memory/compaction/*` — budget, boundary, `stage2_needed`, omission stores, `read_omitted_content`.
- `parrot/core/events/lifecycle/events/memory.py:14` — `Stage2CompactionNeededEvent`.

---

### Option B: Keep two stores; bridge them read-only (rehydrate agent memory from `ChatStorage`)

Leave writes as they are, with the agent's own memory and AgentTalk's `save_turn` both in place. On a miss in
the agent's memory, seed it from `ChatStorage.load_conversation` (the "budgeted `get_context_for_agent`"
follow-up of FEAT-525). Implement Stage 2 on the agent-memory side only. Fix the AgentTalk mismatch separately.

✅ **Pros:**
- Smaller change, and leaves the hot path's write untouched.
- Matches the follow-up literally as FEAT-525 worded it.

❌ **Cons:**
- Two copies stay, with drift by design:
  - TTLs differ;
  - deletes differ (`delete_turn` is cold-only);
  - summaries would exist only on one side.
- A rehydrated history is lossy, because `ChatStorage` lacks tool outputs, errors and FEAT-525 fields (Problem
  5). So the agent "remembers" a degraded version of its own past.
- Default `memory_type="memory"` agents still lose everything that was not rehydrated, and still differ per
  pod.

📊 **Effort:** Medium

🔗 **Existing Code to Reuse:**
- `ChatStorage.get_context_for_agent` / `load_conversation`.

---

### Option C: Make Redis the default memory and fix AgentTalk; no cold tier for agents

Switch the default `memory_type` to `redis`, using one prefix shared by handler and bot. Fix the AgentTalk
mismatch, implement Stage 2 over Redis, and leave `ChatStorage` as the UI's separate record.

✅ **Pros:**
- Smallest change that fixes multi-pod and restart loss for most agents.

❌ **Cons:**
- Redis has no durable, long-lived conversation; the UI (cold tier, 180 days) still outlives the agent's
  memory.
- Still two stores, so the original problem stays: the UI shows what the agent does not know.

📊 **Effort:** Low–Medium

---

## Recommendation

**Option A** is recommended, delivered in phases so each phase is useful on its own:

| Phase | Content | Why first / standalone |
|---|---|---|
| **P0 — correctness fixes** | (a) AgentTalk stops injecting a throw-away `RedisConversation()`, so the bot reads what it writes. (b) `tool_calls` serialization uses `ToolCall.result` / `error` / `execution_time`. (c) `ask_stream` passes `compaction=` like `ask`. (d) Drop or use `HOT_TTL_HOURS`; `delete_turn` also deletes from the hot tier | Bugs in production today, independent of the design choice |
| **P1 — `chat_storage` memory backend** | One write path, full turn payload in the cold tier, rehydrate on hot miss, AgentTalk's separate `save_turn` removed, tolerant reader for old rows | The single source of truth |
| **P2 — Stage 2 summaries** | Summarize turns before the boundary into a `SUMMARIZED` turn, persisted in both tiers, rendered by `compact_history`, triggered by the existing flag/event | Ends silent forgetting; also bounds the hot window that P1 rehydrates |
| **P3 — durable omissions** | Cold-tier `OmissionStore` (FEAT-116 backend or the overflow store) | `read_omitted_content` survives Redis expiry |

Trade-off accepted: Option A changes the contract FEAT-524 deliberately kept ("`ChatStorage` untouched —
separate tier"). We think the reason for keeping them separate (not mixing UI records with model context) is
outweighed by the user-visible failure: "the agent shows the conversation but has no context". This is the
first question for the FEAT-524/525 author.

---

## Feature Description

### User-Facing Behavior

- Any conversation the history sidebar lists can be continued with full context. This holds after a restart, a
  deploy, on another pod, and days later (within the cold tier's retention).
- A long conversation keeps a summary of its early part instead of silently dropping it. Asking about
  something from the beginning works, either from the summary or by the agent re-reading the exact turn.
- Deleting a conversation in the UI deletes the agent's memory of it too.

### Internal Behavior

1. **Round start.**
   - The bot asks its memory for `(chatbot_id, user, session)`.
   - Hot hit: same as today.
   - Hot miss: the backend loads from the cold tier the last `SUMMARIZED` turn plus all turns after its range
     (bounded by the budget), writes them to the hot tier, and returns the history.
2. **Render.** `render_context_history` runs as today. A `SUMMARIZED` turn renders as one assistant-side
   context block (exact rendering is a spec decision) in place of the turns it covers.
3. **Round end.**
   - `save_conversation_turn` calls `add_turn(..., compaction=)`, which writes hot and cold with the full turn
     and the compaction state.
   - The cold write may be async, but it must be ordered per session (open question).
4. **Stage 2.**
   - **Trigger.** When the persisted `stage2_needed` flips, a summarizer runs: inline before the next render,
     or in the background on the event (open question).
   - **Input and output.** It takes the turns before `boundary_turn_id` (and the previous summary, if any) and
     produces a new `SUMMARIZED` turn covering `[first_turn_id, boundary_turn_id]`.
   - **Persistence.** The summary is persisted in both tiers, and the boundary/state is updated atomically
     with it.
5. **UI reads.** The `chat_interaction` / `threads` handlers keep reading `ChatStorage`; `SUMMARIZED` turns are
   hidden from the transcript view, which shows raw turns.

### Edge Cases & Error Handling

- **Cold tier unavailable.** Writes keep going to hot with a warning (today's behaviour). Rehydration falls
  back to an empty history and logs; it never fails the round.
- **Old-shape cold rows** (pre-P1, tool outputs `None`): the reader tolerates missing fields and marks them
  `schema_version=1`.
- **Summarizer failure.** Keep the deterministic Stage 1 result, leave `stage2_needed` set, and retry on the
  next round. Never block the answer.
- **Concurrent rounds on one session** (two tabs): the existing CAS on the hot tier, plus ordered cold writes.
- **Studio and other registry-only hosts:** the `ChatStorage` install must not require `BotManager.setup()`.

---

## Capabilities

### New Capabilities
- `chat-storage-conversation-memory`: a `ConversationMemory` backend over `ChatStorage` (hot + cold,
  rehydrate on miss).
- `stage2-conversation-summaries`: LLM summary turns (`TurnState.SUMMARIZED`) driven by `stage2_needed`.
- `durable-omission-store`: cold-tier `OmissionStore`.

### Modified Capabilities
- `conversation-history-ownership` (FEAT-524): `ChatStorage` is no longer a separate tier.
- `per-turn-conversation-compaction` (FEAT-525): Stage 2 implemented; streaming path commits compaction.
- AgentTalk (`handlers/agent.py`): no injected memory, no separate `save_turn`, correct tool-call
  serialization.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/memory/` (new backend, `get_conversation_memory` factory) | extends | new `memory_type` value |
| `parrot/storage/chat.py` | modifies | becomes the backend's engine; full turn payload; hot-tier delete |
| `parrot/storage/backends/*` | extends | turn payload schema; maybe omission storage |
| `parrot/memory/compaction/*` | extends | summary turn rendering, Stage 2 runner |
| `parrot/bots/base.py`, `bots/data.py` | modifies | streaming commit; read/write same memory |
| `ai-parrot-server/handlers/agent.py` | modifies | remove injected `RedisConversation()` and `save_turn`; tool-call fields |
| `ai-parrot-server/manager/manager.py` | modifies | `ChatStorage` available to registry-only hosts |
| Agent Studio (navigator-agent-studio FEAT-013) | depends on | its chat route uses this backend instead of `studio_conversation` Redis |
| navigator-agent-server agents | depends on | get durable memory by config/default change |

---

## Code Context

### Verified Codebase References (dev @ `8767acbaeb`, 2026-11-11)

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/memory/abstract.py
class ConversationTurn:            # :101-132 (+ FEAT-525 fields tool_invocations, error, token_count, state, schema_version, norm_version)
class ConversationHistory:         # :273-283
class ConversationMemory:
    async def create_history(self, user_id, session_id, metadata=None, chatbot_id=None) -> ConversationHistory  # :421
    async def get_history(self, user_id, session_id, chatbot_id=None) -> Optional[ConversationHistory]          # :428
    async def update_history(self, history) -> None                                                             # :435
    async def add_turn(...)                                                                                      # :440-513 template
    async def _store_turn(self, user_id, session_id, turn, chatbot_id=None, *, compaction_state=None)           # :515-535
    # clear_history :595, list_sessions :600, delete_history :605

# packages/ai-parrot/src/parrot/memory/redis.py
class RedisConversation(ConversationMemory):
    def __init__(self, redis_url=REDIS_HISTORY_URL, key_prefix="conversation", use_hash_storage=True, *,
                 token_counter=None, omission_store=None, normalize=True, omission_ttl=None, history_ttl=None)  # :47

# packages/ai-parrot/src/parrot/storage/chat.py
HOT_TTL_HOURS = 48                                   # :20 (unused)
class ChatStorage:                                   # :25
    self._redis = RedisConversation(key_prefix="chat")   # :55
    async def save_turn(self, *, turn_id=None, user_id, session_id, agent_id, user_message, assistant_response,
                        output=None, output_mode=None, data=None, code=None, model=None, provider=None,
                        response_time_ms=None, tool_calls=None, sources=None, metadata=None) -> str   # :106
    async def load_conversation(self, user_id, session_id, agent_id=None, limit=50)                # :281
    async def get_context_for_agent(self, user_id, session_id, agent_id=None, max_turns=10, model="claude")  # :613 (no callers)

# packages/ai-parrot/src/parrot/models/basic.py:23-30
class ToolCall(BaseModel): id; name; arguments; result=None; error=None; execution_time=None

# packages/ai-parrot/src/parrot/memory/compaction/models.py
class TurnState(str, Enum): RAW; PRUNED; SUMMARIZED   # :31-42 (SUMMARIZED never produced)
class CompactionState: ... boundary_turn_id; stage2_needed=False   # :226-240

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py:14
class Stage2CompactionNeededEvent(LifecycleEvent)   # no subscribers

# packages/ai-parrot/src/parrot/bots/abstract.py
self.memory_type = kwargs.get("memory_type", "memory")          # :616
def get_conversation_memory(self, storage_type="memory", **kw)  # :2004-2013 (memory | file | redis)
async def save_conversation_turn(self, user_id, session_id, turn, *, compaction=None)  # :2608-2698, writes self.conversation_memory

# packages/ai-parrot/src/parrot/bots/base.py
memory = memory or self.conversation_memory     # :765, :1261, :2006 (read side)
await self.save_conversation_turn(user_id, session_id, turn)   # :2234 ask_stream, no compaction=
# packages/ai-parrot/src/parrot/bots/data.py:1427 same read pattern (PandasAgent)

# packages/ai-parrot-server/src/parrot/handlers/agent.py
memory = RedisConversation()   # :1733-1736, per request when user_id and session_id
# save_turn background tasks: :2807-2846 (stream), :3060-3097 (json); tool_calls via getattr(t,"status"/"output") :2827-2834, :3077-3085

# packages/ai-parrot-server/src/parrot/manager/manager.py
def setup_registry_only(...)            # :3130 (no ChatStorage)
async def on_startup(self, app)         # :3194; ChatStorage() :3237; app["chat_storage"] :3246
```

#### Key Attributes & Constants
- Cold backend selection: `PARROT_STORAGE_BACKEND` (default `sqlite`; AWS prod must set `dynamodb`),
  `DYNAMODB_CONVERSATIONS_TABLE` (default `parrot-conversations`), DynamoDB item TTL 180 days
  (`storage/backends/dynamodb.py:39-40`).
- Studio's own memory: `STUDIO_CONVERSATION_BACKEND` (`memory` default, `redis`), prefix
  `studio_conversation`, `STUDIO_CONVERSATION_TTL_SECONDS` default 86400
  (`ai-parrot-server/.../handlers/studio/conversation.py`).

### Does NOT Exist (Anti-Hallucination)
- ~~A `chat_storage` / DynamoDB `memory_type`~~. The factory knows only `memory`, `file` and `redis`.
- ~~Any producer of `TurnState.SUMMARIZED`~~ or subscriber of `Stage2CompactionNeededEvent`.
- ~~Any caller of `ChatStorage.get_context_for_agent`~~ outside tests.
- ~~A global env var for `memory_type`~~.
- ~~`ToolCall.status` / `ToolCall.output`~~ on `parrot.models.ToolCall`.
- ~~A spec, proposal or active task for LLM Stage 2 or ChatStorage-backed agent memory~~ (searched `sdd/`,
  task indexes and remote branches on 2026-11-11).

---

## Parallelism Assessment

- **Internal parallelism:** P0 items (a)–(d) are independent small fixes. P1 and P2 share
  `memory/compaction` and the turn schema, so they should be sequential. P3 is independent once P1 fixes the
  cold-tier schema.
- **Cross-feature independence:**
  - FEAT-571 (memory-dynamics) explicitly excludes history/compaction; no overlap.
  - FEAT-538 task recall touches `_maybe_inject_task_recall`, which P2 must coexist with.
  - Agent Studio FEAT-013 (other repo) consumes P1.
- **Recommended isolation:** per-spec. P0 can be its own small spec or brief, ahead of the rest.
- **Rationale:** P0 fixes live bugs and should not wait for the design discussion of P1/P2.

---

## Open Questions

- [ ] Q1 — Is it acceptable to end FEAT-524's "ChatStorage is a separate tier" and make it the agent's memory
  (Option A), or should the UI record and model context stay separate (Option B)? — *Owner: Jesus Lara*
- [ ] Q2 — Should `chat_storage` become the **default** `memory_type` (registry agents, database bots, Studio),
  or stay opt-in per agent? — *Owner: Jesus Lara*
- [ ] Q3 — Stage 2 timing: summarize inline before the next render (adds latency to one round), or in the
  background on `Stage2CompactionNeededEvent` (the next round may still render without the summary)? —
  *Owner: Jesus Lara*
- [ ] Q4 — Stage 2 model: the agent's own LLM, or a fixed cheap summarizer model (config key)? Whose key pays
  (server vs BYOK)? — *Owner: Jesus Lara*
- [ ] Q5 — Rendering of a `SUMMARIZED` turn: an assistant-side context message, a system-adjacent block, or a
  pseudo user/assistant pair? It must not break FEAT-524's strict alternation. — *Owner: Jesus Lara*
- [ ] Q6 — Cold write ordering: keep fire-and-forget (today) or make it awaited/ordered per session, so that a
  rehydrate never misses the last turn? — *Owner: Jesus Lara*
- [ ] Q7 — Hot-tier TTL: use `HOT_TTL_HOURS` (48 h) once rehydration exists, or keep no TTL? — *Owner: Jesus
  Lara*
- [ ] Q8 — Should P0 ship first as an independent fix (it changes live behaviour of every AgentTalk agent with a
  `session_id`)? Verify finding 3 at runtime first. — *Owner: Juan Ruffato / Jesus Lara*
- [ ] Q9 — Key alignment: AgentTalk uses `agent_name` as `agent_id`, the bot uses `memory_key_id`. Are they
  always equal (database bots, registry agents, Studio `chatbot_id=str(agent_id)`)? — *Owner: Jesus Lara*
