---
title: "Conversation Memory Subsystem Overview"
summary: "How AI Parrot stores, renders and compacts conversation history: ConversationMemory backends, the add_turn template method, render_history and per turn compaction."
---

# Conversation Memory Subsystem Overview

## Purpose

`parrot.memory` holds the conversation history of every bot. This page is the map of the
subsystem: which classes persist turns, how a turn travels from a bot into a backend, how a
stored history becomes provider neutral messages, and how the read path keeps that history
inside the model's context window.

Ownership rules in one paragraph (details in
[Conversation History Ownership](conversation-history-ownership.md)): `AbstractBot` is the
sole owner of history. It loads the history, renders it, hands the result to the client as
`history=`, and is the only writer, through `AbstractBot.save_conversation_turn()`. Clients
never load or persist history.

The pipeline has three stages:

1. **Write path (always on).** `ConversationMemory.add_turn()` normalizes, counts tokens,
   offloads oversized tool output, then delegates one write to the backend's `_store_turn()`.
2. **Read path (budgeted by default).** `AbstractBot.render_context_history()` runs the pure
   `compact_history()` pre-pass and feeds the resulting views to `render_history()`.
3. **Recovery.** Omitted tool output stays retrievable through the `read_omitted_content`
   tool, backed by an `OmissionStore`.

The full compaction design is in
[Per Turn Conversation Compaction](per-turn-conversation-compaction.md); this page does not
repeat it.

## Public API

Modules (all re-exported from `parrot.memory`):

- [`parrot.memory`](ref:parrot.memory) — package facade; exports the names below plus the
  episodic, unified and dream cycle memories (the dream cycle names resolve lazily via PEP 562).
- [`parrot.memory.abstract`](ref:parrot.memory.abstract) — `ConversationTurn`,
  `ConversationHistory`, `ConversationMemory` (the abstract base and template method).
- [`parrot.memory.render`](ref:parrot.memory.render) — `HistoryMessage` and `render_history`.
- [`parrot.memory.compaction`](ref:parrot.memory.compaction) — models (`ContextBudget`,
  `TurnView`, `CompactionResult`, `CompactionCommit`, `TurnState`, ...) and the omission stores.
- [`parrot.memory.compaction.compact`](ref:parrot.memory.compaction.compact) — `compact_history`,
  `render_tool_activity`.
- [`parrot.memory.compaction.budget`](ref:parrot.memory.compaction.budget) — `MODEL_WINDOWS`,
  `resolve_window`, `build_default_budget`, `compaction_disabled_by_env`.
- [`parrot.memory.compaction.omission`](ref:parrot.memory.compaction.omission) — `OmissionStore`
  and its `InMemoryOmissionStore`, `FileOmissionStore`, `RedisOmissionStore` implementations.
- [`parrot.memory.compaction.recover`](ref:parrot.memory.compaction.recover) —
  `bind_read_omitted_content`.
- [`parrot.bots.abstract`](ref:parrot.bots.abstract) — `AbstractBot`: `get_conversation_memory`,
  `context_budget`, `render_context_history`, `save_conversation_turn`.

### Backends

| Class | Module | Storage |
|---|---|---|
| `InMemoryConversation` | `parrot.memory.mem` | process-local dicts, lost on restart |
| `FileConversationMemory` | `parrot.memory.file` | one JSON file per session under `base_path` |
| `RedisConversation` | `parrot.memory.redis` | Redis hash (default) or string keys |

All three subclass `ConversationMemory` and implement its abstract methods:
`create_history`, `get_history`, `update_history`, `clear_history`, `list_sessions`,
`delete_history`, plus the private `_store_turn`.

### The add_turn template method

`ConversationMemory.add_turn` is concrete; backends never override it:

```python
async def add_turn(
    self, user_id: str, session_id: str, turn: ConversationTurn,
    chatbot_id: Optional[str] = None, *, compaction: Optional[CompactionCommit] = None,
) -> None
```

Order of work, as implemented:

1. Stage 0 normalization (`normalize_turn`), unless the instance was built with `normalize=False`.
2. Stage 0.5 token counting (`count_turn`), always on; stamps `turn.token_count`.
3. Write time offload: any `ToolInvocation.output` above `oversize_tool_tokens` goes to the
   omission store; the turn keeps a short preview and `inv.omitted["output"]` holds the
   `content_id`.
4. `turn.schema_version = 2`.
5. If `compaction` is given, fold it into the persisted `metadata["compaction"]` state
   (`apply_commit`: calibration EWMA, boundary, `stage2_needed`).
6. One backend write: `_store_turn(user_id, session_id, turn, chatbot_id, *, compaction_state=...)`.

Related helpers on the base class: `omission_key(user_id, session_id, chatbot_id)` returns
`"{chatbot_id}:{user_id}:{session_id}"` (`None` becomes `"_default"`), and
`report_usage(...)` folds a (estimate, provider) token observation into the calibration state
without writing a turn.

### Rendering

`render_history(history, *, max_turns=None, current_chatbot_id=None, include_other_agents=True,
other_agent_label="[agent:{chatbot_id}]") -> List[HistoryMessage]` is a pure function. It
accepts a `ConversationHistory` or a `Sequence[TurnView]`, guarantees strict user/assistant
alternation, merges same role neighbours with a blank line, skips turns with blank assistant
text, and prefixes turns from other agents with the label. `HistoryMessage` is a frozen
dataclass: `role`, `content`, `chatbot_id`, `turn_id`.

### Compaction

`compact_history(history, budget, *, policies=None, boundary_turn_id=None, counter=None,
calibration=1.0, current_chatbot_id=None, include_other_agents=True) -> CompactionResult`
is pure and synchronous. It walks newest to oldest and classifies each turn:

| Tier | `TurnState` | Meaning |
|---|---|---|
| Verbatim | `RAW` | full text plus a bounded `<tool-activity>` block |
| Pruned | `PRUNED` | tool output replaced by a short notice, bytes offloaded |
| Dropped | (not in views) | listed in `dropped_turn_ids`; sets `stage2_needed` |

`TurnState.SUMMARIZED` exists but is reserved for a future stage. `CompactionResult` carries
`views`, `omissions`, `history_estimate`, `boundary_turn_id`, `stage2_needed` and
`dropped_turn_ids`.

## Configuration & Parameters

**Choosing a backend.** `AbstractBot.get_conversation_memory(storage_type="memory", **kwargs)`
maps `"memory"`, `"file"` and `"redis"` to the three classes (anything else raises
`ValueError`). `configure_conversation_memory()` calls it with the bot's `memory_type` and
`memory_config`.

**Common keyword only constructor arguments** (all backends): `token_counter`,
`omission_store`, `normalize=True`. The base class additionally accepts `debug` and
`oversize_tool_tokens` (default `2_000`).

**Backend specific arguments:**

- `FileConversationMemory(base_path="./conversations", ...)`: omission store defaults to a
  `FileOmissionStore` sharing `base_path`.
- `RedisConversation(redis_url=None, key_prefix="conversation", use_hash_storage=True, ...,
  omission_ttl=None, history_ttl=None)`: `redis_url` defaults to `REDIS_HISTORY_URL` from
  `parrot.conf`; the default omission store is a `RedisOmissionStore` on the same client;
  `history_ttl` refreshes expiry on every write.

**`ContextBudget`** (frozen dataclass, validated in `__post_init__`):

| Field | Default |
|---|---|
| `window` | required (tokens) |
| `reserve_output` | `8_192` |
| `reserve_fixed` | `4_096` |
| `high_watermark` / `low_watermark` | `0.80` / `0.60` (low is reserved for a later stage) |
| `max_turns` | `30` |
| `verbatim_tokens` | `15_000` |
| `min_verbatim_turns` | `2` |
| `oversize_tool_tokens` | `2_000` |
| `tool_activity_limit` | `Limit()` (12 invocations, 200/400 chars, 1500 tokens) |

`budget.available` is `window - reserve_output - reserve_fixed`. `resolve_window(model)`
looks up the longest matching prefix in `MODEL_WINDOWS` and falls back to
`FALLBACK_WINDOW` (32,000).

**Bot level switches:** the `context_budget` kwarg (`False` disables, a `ContextBudget`
instance is used as given, `None`/`True` auto builds from the model) and the environment
variable `PARROT_COMPACTION_DISABLED=1`, which makes `context_budget` resolve to `None` so
render and save use the plain path.

## Usage Examples

Use a backend directly, outside a bot:

```python
import asyncio
from parrot.memory import ConversationTurn, InMemoryConversation, render_history


async def main() -> None:
    memory = InMemoryConversation()
    await memory.create_history("user-1", "session-1", chatbot_id="support")
    turn = ConversationTurn(
        turn_id="t1",
        user_id="user-1",
        user_message="What is the refund window?",
        assistant_response="Refunds are accepted within 30 days.",
        chatbot_id="support",
    )
    await memory.add_turn("user-1", "session-1", turn, chatbot_id="support")

    history = await memory.get_history("user-1", "session-1", chatbot_id="support")
    for message in render_history(history, current_chatbot_id="support"):
        print(message.role, "->", message.content)


asyncio.run(main())
```

Run the compaction pre-pass by hand and render the views:

```python
from parrot.memory import ContextBudget, compact_history, render_history

budget = ContextBudget(window=32_000, max_turns=10)
result = compact_history(history, budget, current_chatbot_id="support")
messages = render_history(result.views, current_chatbot_id="support")
print(len(result.dropped_turn_ids), result.stage2_needed)
```

Build the recovery function for a memory backend (a bot normally registers it for you):

```python
from parrot.memory.compaction.recover import bind_read_omitted_content

read_omitted_content = bind_read_omitted_content(memory)
```

## Gotchas

- **Never override `add_turn`.** Custom backends implement `_store_turn` only; overriding
  `add_turn` skips normalization, counting and the oversize offload.
- **`normalize=False` mutates the caller's turn.** With the default, `add_turn` works on a
  normalized copy; opting out makes the offload rewrite your `ToolInvocation` objects in place.
- **Default omission stores differ by backend.** `InMemoryConversation` uses a process-local
  store, so omitted bytes vanish on restart. If a backend has no store configured, the base
  class warns and falls back to an `InMemoryOmissionStore`.
- **`read_omitted_content` fails closed.** It needs the `current_memory_key_id`,
  `current_user_id` and `current_session_id` ContextVars; if any is `None` it returns a fixed
  "unavailable" message and never touches the store.
- **Single writer.** `save_conversation_turn` always stores under `self.memory_key_id`, and the
  turn's `chatbot_id` must equal it. Do not write turns from outside the bot.
- **Lazy exports.** `parrot.memory.compaction` resolves `compact_history`, `normalize_turn`,
  the policies and `bind_read_omitted_content` lazily to avoid an import cycle with
  `parrot.memory.abstract`. Import them from the submodule if you hit a bootstrap problem.
- **Compaction is never persisted in pruned form.** Only `metadata["compaction"]`
  (tokenizer, calibration, samples, boundary, `stage2_needed`) is stored; PRUNED and dropped
  are computed on every read.
- **Foreign turns.** In `render_history`, a turn whose `chatbot_id` is `None` (legacy) is
  always treated as belonging to the current agent.

## Related

- [Conversation History Ownership](conversation-history-ownership.md) — who loads, renders
  and writes history, the storage key, and the 0.29.0 breaking changes.
- [Per Turn Conversation Compaction](per-turn-conversation-compaction.md) — the three tiers,
  rendered text formats, tuning, kill switch and omitted content recovery in depth.
