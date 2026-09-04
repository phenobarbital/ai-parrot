# Conversation History Ownership

**FEAT-524** · shipped in **0.29.0** (breaking) ·
rationale and full design: [`sdd/specs/conversation-history-ownership.spec.md`](../../sdd/specs/conversation-history-ownership.spec.md)

Before FEAT-524, `AbstractClient` **and** `AbstractBot` both read and both wrote
the same conversation memory under the same key. Every stateful round persisted
**two** turns and sent the history to the provider **twice** — once as replayed
messages from the client, once as a text digest the bot injected into the system
prompt. This document describes the single-owner model that replaced it.

---

## Three layers, one owner each

| Layer | Owner | Responsibility |
|---|---|---|
| **Store + render** | `parrot.memory` | Persist `ConversationHistory`; render it into a provider-neutral `list[HistoryMessage]` via `render_history()`. Knows nothing about providers. |
| **Orchestrate + record** | `AbstractBot` / `BaseBot` | Load history, render it, pass it to the client as `history=`, build the `ConversationTurn` from the returned `AIMessage`, persist it through `save_conversation_turn()`. **The only writer.** |
| **Format + call** | `AbstractClient` subclasses | Accept `history`, convert it with `_format_history()` into the provider's message shape, append the current prompt, call the provider. **No memory, no ids.** |

```
user_id/session_id → BaseBot.ask / conversation / invoke / ask_stream
                         │ 1. get_history(chatbot_id=memory_key_id)
                         │ 2. render_history(...)          ┌──────────────────────┐
                         │ 3. history= ────────────────────▶ AbstractClient.ask() │
                         │                                 │  _format_history()   │
                         │ 4. AIMessage ◀──────────────────│  + current prompt    │
                         │ 5. ConversationTurn.from_ai_message()                  │
                         ▼                                 └──────────────────────┘
                    save_conversation_turn()   ← the single writer
```

---

## Storage key

Every history is keyed **per agent**: `(chatbot, user, session)`.

| Backend | Key |
|---|---|
| Redis | `conversation:{key_id}:{user}:{session}` |
| File | `{user}/{key_id}/{session}.json` |
| In-memory | `[user][key_id][session]` |

`key_id` is `AbstractBot.memory_key_id`:

> the explicit `chatbot_id` when one was supplied (constructor kwarg, or loaded
> from the database by `Chatbot`), and **`self.name` otherwise**.

It is deliberately *not* `self.chatbot_id`, whose default is a fresh
`uuid4().hex` per process — keying by that would start a new history on every
restart for any bot that never declared an id. Consequence accepted for v1: two
*different* bots created without a `chatbot_id` but with the same `name` share a
history.

The same value is stamped onto `ConversationTurn.chatbot_id`, and
`save_conversation_turn()` raises `ValueError` if the two disagree — attribution
and storage location are two views of one fact.

### Lazy legacy re-key

Histories written before FEAT-524 live under the un-segmented key
(`conversation:{user}:{session}`), and Redis history keys carry **no TTL**. On
Redis and File, `get_history(user, session, chatbot_id=...)` therefore falls back
to the legacy key when the segmented one is missing, copies the record under the
new key, and **leaves the legacy record in place** (rollback safety). One read,
no offline migration job. Copied turns keep `chatbot_id=None` — they predate
attribution, and `render_history` treats `None` as "belongs to the current agent".

---

## Calling a client standalone

A bare `AbstractClient` is the memory-less case by definition:

```python
from parrot.clients.gpt import OpenAIClient

async with OpenAIClient(model="gpt-5-mini") as client:
    answer = await client.ask("What is the capital of France?")
```

If you happen to have a history, render it and pass it in:

```python
from parrot.memory import render_history

rendered = render_history(history, current_chatbot_id="my-agent")
answer = await client.ask("And its population?", history=rendered)
```

```python
# parrot/clients/base.py
async def ask(self, prompt, model, max_tokens=None, temperature=0.7, files=None,
              system_prompt=None,
              history: Optional[Sequence[HistoryMessage]] = None,
              structured_output=None, tools=None, use_tools=None,
              deep_research=False, background=False,
              lazy_loading=False) -> MessageResponse: ...
```

Providers customise **only** `_format_history`; `_build_messages` composes and
must never re-implement `_prepare_messages` (the FEAT-302 guarantee: the current
turn is encoded exactly once, after the history):

```python
def _format_history(self, history: Sequence[HistoryMessage]) -> List[Dict[str, Any]]
def _build_messages(self, prompt: str, files=None, history=None) -> List[Dict[str, Any]]
```

Overridden by: **Bedrock Converse** (`{"role", "content": [{"text": ...}]}`) and
**Google** (`UserContent` / `ModelContent`; Google also keeps a `_dict_messages()`
helper because `resume()` re-parses `state["messages"]` as plain dicts).
`claude_agent.py` and `live.py` accept `history` for conformance but do **not**
replay it — both providers own their own server-side session.

---

## How a bot persists a turn

```python
turn = ConversationTurn.from_ai_message(
    user_message=question,
    response=response,              # the final AIMessage, post-guardrails
    user_id=user_id,
    chatbot_id=self.memory_key_id,
    context_used=vector_context,    # optional
    turn_id=None,                   # defaults to response.turn_id, then uuid4
    assistant_text=None,            # override; used by the streaming partial save
)
await self.save_conversation_turn(user_id, session_id, turn)
```

`from_ai_message` gives every turn one canonical metadata shape:
`{"model", "provider", "usage", "finish_reason", "response_time"}`, with
`tools_used` derived from `response.tool_calls`.

`save_conversation_turn(user_id, session_id, turn)` keys by `memory_key_id` and
emits FEAT-176's `MessageAddedEvent`. It takes **no** `chatbot_id` parameter, on
purpose: no caller may write into another agent's history.

---

## `render_history` — the extension point

This is where per-turn compaction (token budgeting, pruning, an omission store)
will hook in. It replaced `ConversationHistory.get_messages_for_api()`.

```python
# parrot/memory/render.py
@dataclass(frozen=True)
class HistoryMessage:
    role: Literal["user", "assistant"]
    content: str
    chatbot_id: Optional[str] = None
    turn_id: Optional[str] = None


def render_history(
    history: Optional[ConversationHistory],
    *,
    max_turns: Optional[int] = None,
    current_chatbot_id: Optional[str] = None,
    include_other_agents: bool = True,
    other_agent_label: str = "[agent:{chatbot_id}]",
) -> List[HistoryMessage]: ...
```

Guarantees, each with a unit test in
`packages/ai-parrot/tests/unit/memory/test_render_history.py`:

- **pure** — same inputs ⇒ same output; the input history is never mutated;
- roles **strictly alternate**, starting `user` and ending `assistant` (or empty);
- consecutive same-role messages are **merged** with a blank line;
- turns whose `assistant_response` is empty/whitespace are **skipped entirely** —
  never an empty assistant message;
- turns from a different `chatbot_id` are dropped when
  `include_other_agents=False`, otherwise their assistant text is prefixed with
  `other_agent_label`; a turn with `chatbot_id=None` is always "own agent";
- `max_turns` keeps the most recent N (`None` = all, `<= 0` = none).

`render.py` is a **leaf module**: it imports only from `parrot.memory.abstract`,
never a storage backend, so `parrot.clients` can type against `HistoryMessage`
without inheriting a Redis or aiofiles dependency.

---

## Breaking changes in 0.29.0

Hard cut — no deprecation shims, no compatibility kwargs.

**`AbstractClient`**
- `conversation_memory` constructor kwarg **removed** (and its
  `InMemoryConversation()` default).
- `user_id` / `session_id` **removed** from `ask()` and `ask_stream()` on the
  base class and all 19 concrete clients. Use `history=` instead. Per-call
  telemetry still resolves ids from the `parrot.observability.context`
  ContextVars, which `BaseBot` binds.
- `stateless` **removed** from `ask()` / `ask_stream()` — a stateless call is
  simply one with no `history`. (It survives on Google's non-`ask` multimodal
  helpers, where it still gates replay.)
- **Removed**: `start_conversation`, `get_conversation`, `clear_conversation`,
  `delete_conversation`, `list_user_conversations`, `_get_chatbot_key`,
  `_prepare_conversation_context`, `_update_conversation_memory`,
  `create_conversation_memory`.
- **Added**: `_format_history`, `_build_messages`, `_existing_files`.

**`parrot.memory`**
- `ConversationHistory.get_messages_for_api()` **removed** → `render_history()`.
- `ConversationTurn.chatbot_id` added (last field; legacy records deserialize to
  `None`). `ConversationTurn.from_ai_message()` added.
- `HistoryMessage` and `render_history` exported from `parrot.memory`.

**`AbstractBot`**
- `build_conversation_context()` **removed**, along with the
  `conversation_context` kwarg on `create_system_prompt()` / `_build_prompt()`
  and the `## Conversation Context:` section. History no longer appears in any
  system prompt.
- `save_conversation_turn()` lost its `chatbot_id` parameter.
- `_create_llm_client()` lost its `conversation_memory` parameter.
- `memory_key_id` property added.

**Callers**
- `parrot_tools/security/summarizer.py` no longer passes `stateless=True`.
