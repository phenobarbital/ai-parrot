---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Conversation History Ownership

**Feature ID**: FEAT-524
**Date**: 2026-09-04
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.29.0 (breaking — hard cut on `AbstractClient.ask()` / `ask_stream()` signatures)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`ConversationHistory` is one of the oldest subsystems in ai-parrot and it is
touched at **two levels at once**: `AbstractClient` and `AbstractBot` both
read and both write the same `ConversationMemory` object, under the same
storage key.

Verified by code reading (not yet by a runtime test — Module 1 makes it a
test):

1. `AbstractBot` creates the memory (`configure_conversation_memory`,
   `bots/abstract.py:1263`) and injects **the same object** into the client
   (`_create_llm_client`, `bots/abstract.py:1035-1036` and `:1055`).
2. Every bot entry point (`BaseBot.conversation`/`invoke`/`ask`/`ask_stream`)
   passes `user_id` and `session_id` into the client call
   (`bots/base.py:445-446`, `:705-706`, `:1285-1286`, `:1776`).
3. With both ids present the client loads the history and replays every turn
   as provider messages (`clients/base.py:2310-2322`), then **writes a
   `ConversationTurn`** after the completion (`_update_conversation_memory`,
   `clients/base.py:2375-2407`). Nine clients call that helper; `grok.py`
   carries its own third copy (`clients/grok.py:265`, `:423`, `:505`, `:570`).
4. The bot, in parallel, loads the same history, condenses it into a ≤1500
   char text block injected into the **system prompt**
   (`build_conversation_context`, `bots/abstract.py:2912`; rendered at
   `:3162-3163`), and **writes its own `ConversationTurn`** at four sites in
   `bots/base.py` (539, 757, 1349, 1853), plus `bots/voice.py:642/683` and
   `bots/data.py:2102`.
5. Both writes resolve to the same storage key — neither the bot's
   `memory.add_turn(user_id, session_id, turn)` nor the client's
   `chatbot_id=self._get_chatbot_key()` (which is `None`: no client ever
   sets `chatbot_id`) carries a chatbot segment, so `InMemoryConversation`
   maps both to `"_default"` (`memory/mem.py:13`) and `RedisConversation`
   omits the segment (`memory/redis.py:39`).

Net effect per stateful round: **two turns persisted** with different
`turn_id`s, and the history reaches the provider **twice** (once as replayed
messages, once as a text digest in the system prompt). Every later round
replays the doubled history. This is a hard precondition for
`sdd/proposals/per-turn-conversation-compactation.proposal.md`: any token
budget computed over a doubled history counts double.

Beyond the duplication, ownership is wrong in principle:

- The LLM client can change **inside** a round: `ModelSwitchingMixin`
  (`bots/mixins/model_switching.py:57`, `execute_llm_call` at `:169`) retries
  on a secondary client in `fallback` mode and runs two clients concurrently
  in `contrastive` mode. Client-side persistence records the failed attempt
  or two answers. Only the bot knows which answer is *the* answer.
- The canonical answer only exists in the bot: guardrails, redaction, the
  formatter and streaming flush all run **after** the client returns. The
  client's turn stores pre-guardrail text.
- Using an `AbstractClient` directly is, by design, the memory-less case:
  there is no user, no session, no agent. Twenty-plus direct callers across
  `parrot_tools`, `handlers`, `advisors`, `a2a` and `bots/*` call
  `client.ask(prompt)` with no ids (see §6 Integration Points).
- `AbstractBot.save_conversation_turn` (`bots/abstract.py:1836`) already
  exists as the intended single writer and even emits `MessageAddedEvent`
  (FEAT-176), but it has **zero callers** — every bot site hand-rolls its own
  `ConversationTurn` with divergent metadata.

### Goals

- **Single owner**: `ConversationHistory` and turn recording live exclusively
  in `AbstractBot`. One writer: `save_conversation_turn`.
- **Memory-less clients**: `AbstractClient` has no `conversation_memory`, no
  `user_id`/`session_id` on `ask()`/`ask_stream()`, and never imports
  `parrot.memory` storage. It receives an already rendered history and only
  formats it for its provider.
- **Single injection path**: history reaches the provider as alternating
  `user`/`assistant` messages produced by a pure render function in
  `parrot.memory`. The system-prompt text digest is removed.
- **Attribution**: every `ConversationTurn` carries the `chatbot_id` of the
  agent that produced it.
- **Hard cut**: no deprecation shims, no compatibility kwargs. ai-parrot has
  no external API consumers and no user agent overrides `ask()` (stated by
  the author, 2026-09-04). Every internal caller is updated in this feature.
- Provide the single extension point (`render_history`) that the compaction
  brainstorm will be re-run against once this lands on `dev`.

### Non-Goals (explicitly out of scope)

- Token budgeting, pruning, normalization or the omission store — that is
  the compaction proposal, to be re-brainstormed **after** this feature.
- A bulk **Redis key migration job**. The key layout *does* change (every
  history is keyed per agent, §2 "Storage key"), but existing histories are
  re-keyed lazily on first read (M2b), not by an offline script.
- Replaying **file attachments** or provider-native `tool_use`/`tool_result`
  blocks from earlier turns. `ConversationTurn` stores text only; that stays.
- Touching `parrot.storage.ChatStorage` / `storage/models.py::ChatMessage`
  (the DocumentDB/Redis per-message persistence tier, FEAT-agent-artifact
  lineage). It has its own writer (`storage/chat.py:209`) keyed by
  `agent_id`, and is not part of the bot↔client turn loop.
- Moving client files into satellite packages (FEAT-523,
  `pep-420-llm-clients.spec.md`) — but see Worktree Strategy for sequencing.
- Provider-side conversation state (OpenAI Responses `previous_response_id`,
  Google Live sessions). `live.py` keeps its own session model; it only
  loses the `conversation_memory` constructor kwarg.

---

## 2. Architectural Design

### Overview

Three layers, each with one owner:

| Layer | Owner | Responsibility |
|---|---|---|
| **Store + render** | `parrot.memory` | Persist `ConversationHistory`; render it into a provider-neutral `list[HistoryMessage]` via the pure function `render_history()`. Knows nothing about providers. |
| **Orchestrate + record** | `AbstractBot` / `BaseBot` | Load history, call `render_history`, pass the result to the client as `history=`, build the `ConversationTurn` from the returned `AIMessage`, persist it through `save_conversation_turn`. The only writer. |
| **Format + call** | `AbstractClient` subclasses | Accept `history: Sequence[HistoryMessage] | None`, convert it with `_format_history()` into the provider's message shape, append the current prompt, call the provider. No memory, no ids. |

Resolved design decisions carried from the 2026-09-04 discussion (no
brainstorm document exists for this slug; these are the authoritative
answers):

- **History lives in `AbstractBot`.** The client receives it, never fetches
  it. — *Resolved: author.*
- **Clients are memory-less.** `conversation_memory`, `user_id`, `session_id`
  and all `*_conversation()` helpers are removed from `AbstractClient`. —
  *Resolved: author.*
- **Every turn carries `chatbot_id`.** New field on `ConversationTurn`,
  always set by the bot. — *Resolved: author.*
- **Injection = alternating messages, neutral intermediate, provider
  formatting in the client.** System-prompt digest removed. — *Proposed by
  assistant, accepted by author.*
- **Removal is a hard cut.** No deprecation period. — *Resolved: author.*
- **Storage key is unified to `(chatbot, user, session)` now.** Every
  history — `BaseBot`, `DataAgent`, `VoiceBot` alike — is keyed per agent
  (Redis `conversation:{key_id}:{user}:{session}`, file
  `{user}/{key_id}/{session}.json`, in-memory `[user][key_id][session]`).
  Attribution (`turn.chatbot_id`) and key segment carry the same value. —
  *Resolved: author, 2026-09-04 (spec review).* Two safeguards follow from
  it, both in scope:
  - **Stable key identity.** `chatbot_id` defaults to a random uuid per
    process when not configured (`bots/abstract.py:353-359`), which would
    lose history on every restart for ad-hoc bots. New property
    `AbstractBot.memory_key_id -> str`: the explicit `chatbot_id` when one
    was passed or loaded from DB, otherwise `self.name`. Both the key and
    `turn.chatbot_id` use it.
  - **Lazy legacy re-key (M2b).** Redis history keys have no TTL
    (`memory/redis.py:490` is commented out), so histories written under
    the old un-segmented key would be orphaned forever. `get_history()` on
    Redis/File falls back to the legacy key when the segmented key is
    missing, copies the record under the new key, and leaves the old one
    in place. One read, no offline job.
- **`render_history(include_other_agents=True)`** with the
  `[agent:{chatbot_id}]` label. With per-agent keys foreign turns only
  appear when a crew/flow writes into another agent's history on purpose;
  the label keeps that case readable. — *Resolved: author.*
- **FEAT-524 lands before FEAT-523** starts moving client files. —
  *Resolved: author.*
- **`stateless=True`** at the two `summarizer.py` call sites is deleted;
  no no-op kwarg survives on `ask()`. — *Resolved: author.*

### Component Diagram

```
                       ┌──────────────────────────────────────────────┐
  user_id/session_id → │ BaseBot.ask / invoke / conversation / stream │
                       └───────┬───────────────────────────┬──────────┘
                               │ 1. get_history()          │ 5. save_conversation_turn()
                               ▼                           ▼
                    ┌────────────────────┐        ┌────────────────────────┐
                    │ ConversationMemory │        │ ConversationTurn       │
                    │ (InMemory/File/    │◀───────│  .from_ai_message()    │
                    │  Redis)            │ add_turn│  chatbot_id = bot id  │
                    └─────────┬──────────┘        └────────────────────────┘
                              │ ConversationHistory              ▲
                              ▼                                  │ AIMessage
                    ┌────────────────────┐                       │
                    │ render_history()   │  2. pure, in parrot.memory
                    │ → list[HistoryMsg] │                       │
                    └─────────┬──────────┘                       │
                              │ history=                         │
                              ▼                                  │
                    ┌────────────────────────────────────────────┴──┐
                    │ AbstractClient.ask(prompt, system_prompt,     │
                    │                    history=..., ...)          │
                    │   3. _format_history(history) → provider msgs │
                    │   4. + current prompt → provider call         │
                    └───────────────────────────────────────────────┘
                    (no conversation_memory, no user_id/session_id)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.memory.ConversationTurn` | extends | new field `chatbot_id: Optional[str]`; new classmethod `from_ai_message()`; `to_dict`/`from_dict` carry the field (missing key → `None`, so old records deserialize). |
| `parrot.memory.ConversationHistory` | modifies | `get_messages_for_api()` **removed** (hard cut); replaced by module-level `render_history()`. |
| `parrot.memory` (`__init__.py`) | extends | exports `HistoryMessage`, `render_history`. |
| `AbstractBot.save_conversation_turn` | modifies | becomes the single writer; always keys by `self.memory_key_id` (the `chatbot_id` parameter is removed); all hand-rolled `ConversationTurn` sites route through it. |
| `AbstractBot.memory_key_id` | adds | property: explicit `chatbot_id` if configured, else `self.name`; used for the storage key **and** `turn.chatbot_id`. |
| `RedisConversation.get_history` / `FileConversationMemory.get_history` | modifies | lazy legacy re-key: when the segmented key is missing and a `chatbot_id` was given, read the un-segmented legacy key, copy under the new key, return it (M2b). `InMemoryConversation` needs nothing (no persistence). |
| `AbstractBot.build_conversation_context` | removes | and the `conversation_context` kwarg of `create_system_prompt` (`abstract.py:3076`) and `_build_prompt` (`:1382`, kwarg at `:1386`, `"chat_history"` slot at `:1440`), plus the `## Conversation Context:` section at `:3162`. |
| `AbstractBot._create_llm_client` | modifies | no longer injects `conversation_memory` into the client (`abstract.py:1031-1036`, `:1055`). |
| `AbstractClient.__init__` | modifies | `conversation_memory` kwarg and `InMemoryConversation()` default removed (`clients/base.py:362`, `:406`). |
| `AbstractClient.ask` / `ask_stream` | modifies | `user_id`, `session_id` removed; `history: Optional[Sequence[HistoryMessage]] = None` added. Same for all 13 subclass overrides (§3 M5). |
| `AbstractClient._prepare_conversation_context` | replaces | with `_build_messages(prompt, files, history)` (no memory access, no system-prompt synthesis). |
| `AbstractClient._update_conversation_memory` | removes | and `_get_chatbot_key`, `start_conversation`, `get_conversation`, `clear_conversation`, `delete_conversation`, `list_user_conversations`. |
| `AbstractClient._format_history` | adds | default implementation (text content blocks); providers override where their shape differs (Google `UserContent`/`ModelContent`, Bedrock Converse). |
| `ModelSwitchingMixin.execute_llm_call` | uses | passes `**llm_kwargs` through unchanged; `history=` flows to both primary and secondary clients with no code change. |
| `BaseBot` (4 entry points), `DataAgent.ask`, `DatabaseAgent.ask`, `VoiceBot.ask/ask_voice/ask_stream`, `AbstractBot.get_infographic`, `flows/core/storage/synthesis.py` | modifies | stop passing ids to the client; pass `history=` where a history exists; record turns via `save_conversation_turn`. |
| FEAT-176 `MessageAddedEvent` | benefits | emitted for every persisted turn for the first time (today `save_conversation_turn` is never called). |
| FEAT-112 per-loop client cache | benefits | cached clients no longer hold per-session state; sharing a client across loops is safe by construction. |

### Data Models

```python
# parrot/memory/abstract.py (extended)
@dataclass
class ConversationTurn:
    turn_id: str
    user_id: str
    user_message: str
    assistant_response: str
    context_used: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    chatbot_id: Optional[str] = None          # NEW — agent that produced this turn

    @classmethod
    def from_ai_message(
        cls,
        *,
        user_message: str,
        response: "AIMessage",
        user_id: str,
        chatbot_id: str,
        context_used: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> "ConversationTurn": ...
    # assistant_response = response.to_text (falls back to str(response.content))
    # tools_used        = [tc.name for tc in response.tool_calls]
    # metadata          = {"model", "provider", "usage" (dict), "finish_reason",
    #                      "response_time"} — one canonical shape for all sites
    # turn_id           = turn_id or response.turn_id or uuid4()


# parrot/memory/render.py (NEW)
@dataclass(frozen=True)
class HistoryMessage:
    """Provider-neutral rendered message. Text only."""
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
) -> list[HistoryMessage]:
    """Pure: same inputs ⇒ same output. Guarantees (tested):
    - strict user/assistant alternation, starts with user, ends with assistant;
    - consecutive same-role messages merged with "\n\n";
    - turns with empty/whitespace assistant_response are skipped entirely
      (never an empty assistant message);
    - turns from a different chatbot_id are dropped when
      include_other_agents=False, otherwise their assistant content is
      prefixed with other_agent_label;
    - max_turns keeps the most recent N turns (None = all).
    """
```

### New Public Interfaces

```python
# parrot/memory/__init__.py
from .render import HistoryMessage, render_history

# parrot/clients/base.py — AbstractClient (signature deltas only)
class AbstractClient(EventEmitterMixin, ABC):
    def __init__(self, preset=None, tools=None, use_tools=False, debug=True,
                 tool_manager=None, **kwargs): ...          # conversation_memory GONE

    async def ask(self, prompt: str, model: str, max_tokens=None, temperature=0.7,
                  files=None, system_prompt=None, structured_output=None,
                  history: Optional[Sequence[HistoryMessage]] = None,   # NEW
                  tools=None, use_tools=None, deep_research=False,
                  background=False, lazy_loading=False) -> MessageResponse: ...
                  # user_id / session_id GONE — same delta on ask_stream()

    def _format_history(self, history: Sequence[HistoryMessage]) -> List[Dict[str, Any]]:
        """Default: [{"role": m.role, "content": [{"type": "text", "text": m.content}]}]."""

    def _build_messages(self, prompt: str, files, history) -> List[Dict[str, Any]]:
        """_format_history(history or ()) + _prepare_messages(prompt, files)[0]."""

# parrot/bots/abstract.py — AbstractBot
@property
def memory_key_id(self) -> str:
    """Stable per-agent key segment: explicit chatbot_id, else self.name."""

async def save_conversation_turn(
    self, user_id: str, session_id: str, turn: ConversationTurn,
) -> None: ...
    # keys by self.memory_key_id; asserts turn.chatbot_id == self.memory_key_id
    # (chatbot_id parameter REMOVED — no caller may choose a different key)
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: Regression test — one turn per round, history once
- **Path**: `packages/ai-parrot/tests/unit/memory/test_history_ownership.py` (new)
- **Responsibility**: Prove the current double-write with a `BaseBot`
  wired to `InMemoryConversation` and a stub `AbstractClient` subclass that
  records the `messages`/`system_prompt` it receives and returns a canned
  `AIMessage`. Assertions: after two rounds the history holds exactly 2
  turns; the second call's provider messages contain the first round once;
  the system prompt contains no `## Conversation Context:` section. Written
  first, red on `dev` today, green after M3–M6.
- **Depends on**: nothing.

### Module 2: `parrot.memory` render layer + turn attribution
- **Path**: `packages/ai-parrot/src/parrot/memory/render.py` (new),
  `packages/ai-parrot/src/parrot/memory/abstract.py`,
  `packages/ai-parrot/src/parrot/memory/__init__.py`
- **Responsibility**: `HistoryMessage`, `render_history()` with the
  guarantees in §2; `ConversationTurn.chatbot_id` + `from_ai_message()`;
  `to_dict`/`from_dict` round-trip the new field; **remove**
  `ConversationHistory.get_messages_for_api()` (`abstract.py:70-98`).
  Backends serialize `turn.to_dict()` and are agnostic to the new field;
  their only change is M2b.
- **Depends on**: nothing (parallel with M1).

### Module 2b: Lazy legacy re-key in persistent backends
- **Path**: `packages/ai-parrot/src/parrot/memory/redis.py` (`get_history`
  `:126`, `_get_key` `:31`), `packages/ai-parrot/src/parrot/memory/file.py`
  (`get_history` `:52`, `_get_file_path` `:17`)
- **Responsibility**: when `get_history(user_id, session_id, chatbot_id)` is
  called with a truthy `chatbot_id` and the segmented key/path does not
  exist, look up the legacy un-segmented key/path
  (`conversation:{user}:{session}` / `{user}/{session}.json`). If found:
  deserialize, set `history.chatbot_id = chatbot_id`, persist it under the
  segmented key (`update_history`/`create_history` path), **leave the legacy
  record untouched**, log at INFO once per key, return the history. Turns
  copied this way keep `turn.chatbot_id = None` (they predate attribution).
  No offline migration script; no TTL added. `InMemoryConversation` is
  process-local and needs nothing.
- **Depends on**: Module 2 (for the `chatbot_id` field on turns).

### Module 3: `AbstractBot` single writer + system-prompt digest removal
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**:
  - New property `memory_key_id`: returns `str(self.chatbot_id)` when a
    `chatbot_id` was passed explicitly (kwarg at `abstract.py:353`, or set by
    `Chatbot` from the DB record, `bots/chatbot.py:150-161`) and `self.name`
    otherwise. Requires remembering whether the id was explicit (a private
    flag set at `:353-359`; the random `uuid4().hex` default is never used
    as a key). Read-side helpers (`get_conversation_history` `:1798`,
    `create_conversation_history` `:1816`, `clear_conversation_history`
    `:1873`, `delete_conversation_history` `:1897`) pass
    `chatbot_id=self.memory_key_id`.
  - `save_conversation_turn` becomes the only persistence path. Its
    `chatbot_id` parameter is **removed**; it always keys by
    `self.memory_key_id` and raises `ValueError` if
    `turn.chatbot_id != self.memory_key_id` (attribution and key must agree).
    The old fallback `chatbot_id or self.chatbot_id` (`abstract.py:1847`)
    disappears with the parameter. `VoiceBot` (`voice.py:645`) already keyed
    by `str(self.chatbot_id)`; it now goes through the same property.
  - Remove `build_conversation_context` (`:2912`) and its `print` debug
    lines; remove the `conversation_context` kwarg from
    `create_system_prompt` (`:3076`) and `_build_prompt` (`:1382`, kwarg `:1386`),
    the `"chat_history"` template slot (`:1440`) and the
    `## Conversation Context:` block (`:3162-3163`).
  - `_create_llm_client` (`:1028`) no longer takes or injects
    `conversation_memory`; the call at `:1534` drops the second argument.
  - `get_infographic` (`:4330`, call at `:4412`) stops passing ids.
- **Depends on**: Module 2.

### Module 4: `AbstractClient` hard cut
- **Path**: `packages/ai-parrot/src/parrot/clients/base.py`
- **Responsibility**: remove `conversation_memory` (`:362`, `:406`) and the
  `ConversationHistory`/`ConversationMemory`/`InMemoryConversation`/
  `FileConversationMemory` imports (`:28-31`); remove `_get_chatbot_key`
  (`:1174`), `start_conversation` (`:1179`), `get_conversation` (`:1191`),
  `clear_conversation` (`:1201`), `delete_conversation` (`:1208`),
  `list_user_conversations` (`:1216`), `_prepare_conversation_context`
  (`:2269`), `_update_conversation_memory` (`:2375`). Add `_format_history`
  and `_build_messages`. Change `ask` (`:1638`) and `ask_stream` (`:1679`)
  signatures. `stateless: bool` kwarg of the old helper disappears with it
  (its only remaining effect was the system-prompt digest).
- **Depends on**: Module 2 (imports `HistoryMessage` for typing only —
  `parrot.memory.render` must not import storage backends, to keep clients
  free of Redis/file deps).

### Module 5: Per-client migration (13 clients + Google analysis mixin)
- **Path**: `clients/bedrock.py` (ask `:701`, stream `:1078`; context calls
  `:788`, `:1139`; memory updates `:1029`, `:1299`), `clients/claude.py`
  (`:446`, `:894`; `:487`, `:943`; `:730`, `:1193`, `:1542`; **plus**
  `ask_to_image` `:1350` which calls `get_messages_for_api()` directly at
  `:1414`), `clients/claude_agent.py` (`:555`, `:730`), `clients/gemma4.py`
  (`:463`, `:668`; `:510`; `:630`), `clients/google/client.py` (`:2975`,
  `:3901`; `:3095`, `:3992`, `:5031`; `:3714`, `:4434`, `:5164`),
  `clients/google/analysis.py` (`:259`, `:808`; `:476`, `:900`; hand-built
  `UserContent`/`ModelContent` history at `:282-292`, `:821-823`),
  `clients/gpt.py` (`:683`, `:1031`; `:746`, `:1079`, `:1501`; `:974`,
  `:1458`, `:1572`), `clients/grok.py` (`:191`, `:440`; own memory logic
  `:265`, `:423`, `:505`, `:570`), `clients/groq.py` (`:333`, `:748`; 5
  context calls `:358`…`:1306`; 5 updates `:696`…`:1342`), `clients/hf.py`
  (`:355`, `:523`; `:394`; `:488`), `clients/live.py` (`:1492`, `:1699`;
  constructor kwarg `:558`, `:593`), `clients/openai_base.py` (`:522`,
  `:904`; `:582`, `:956`; `:727`, `:1170`), `clients/zai.py` (`:408`,
  `:624`; `:137`; `:557`, `:850`).
- **Responsibility**: each override drops `user_id`/`session_id`, accepts
  `history`, replaces the `_prepare_conversation_context` call with
  `_build_messages`, deletes the `_update_conversation_memory` call, and
  overrides `_format_history` only where the provider shape differs
  (Google: `UserContent`/`ModelContent`; Bedrock Converse:
  `{"role", "content": [{"text": ...}]}`). Any `turn_id` the client still
  generates is kept **only** for `AIMessage.turn_id`.
- **Depends on**: Module 4. Files are disjoint → parallelizable *within*
  the single worktree (one commit per client is fine).

### Module 6: Bot-side callers
- **Path**: `bots/base.py` (`conversation` `:156` → kwargs `:445`, write
  `:525-539`; `invoke` `:600` → `:705`, `:743-757`; `ask` `:932` → `:1285`,
  `:1335-1349`; `ask_stream` `:1597` → `:1776`, `:1841-1853`; history loads
  `:326`, `:684`, `:1099`, `:1690`), `bots/data.py` (`ask` `:1294` → kwargs
  `:1471`, call `:1541`, write `:2088-2102`), `bots/database/agent.py`
  (`ask` `:362` → kwargs `:501`, call `:534`), `bots/voice.py` (`ask_voice`
  `:697` → `:724`; `ask` `:750` → `:828`; `ask_stream` `:486` writes
  `:636-645`, `:683`), `bots/flows/core/storage/synthesis.py`
  (`_synthesize_results` `:49` → `:112`; `synthesize_results` `:139` →
  `:205`).
- **Responsibility**: every history load
  (`memory.get_history(user_id, session_id)` at `base.py:326/684/1099/1690`
  and the matching `create_history` fallbacks) passes
  `chatbot_id=self.memory_key_id`; replace
  `conversation_context = self.build_conversation_context(...)` with
  `rendered = render_history(history, max_turns=self.max_context_turns,
  current_chatbot_id=self.memory_key_id)`; pass `history=rendered` in
  `llm_kwargs`; drop `"user_id"`/`"session_id"` from `llm_kwargs`; replace
  every hand-rolled `ConversationTurn(...)` + `memory.add_turn(...)` with
  `ConversationTurn.from_ai_message(..., chatbot_id=self.memory_key_id)` +
  `await self.save_conversation_turn(user_id, session_id, turn)`.
  The `ask_stream` partial-on-error save (`base.py:1841`) keeps its
  semantics (persist accumulated text) via the same helper with a
  synthesized `AIMessage` or explicit fields. Voice transcripts (`voice.py:636`)
  build the turn directly (no `AIMessage`) but still go through
  `save_conversation_turn` with `chatbot_id=self.memory_key_id` on the turn.
  Delete `stateless=True` at `parrot_tools/security/summarizer.py:272` and
  `:416`.
- **Depends on**: Modules 3, 4.

### Module 7: Test suite migration
- **Path**: `tests/clients/test_base_fallback.py`,
  `tests/clients/test_anthropic_fallback.py`,
  `tests/clients/test_openai_base_parity.py`,
  `tests/clients/test_anthropic_sdk_097.py`, `tests/clients/test_claude_agent.py`,
  `tests/clients/test_moonshot_client.py`,
  `tests/clients/test_openai_compatible_defaults.py`,
  `tests/unit/test_anthropic_invoke.py`, `tests/unit/test_stream_contract.py`,
  `tests/unit/test_google_document_understanding.py`,
  `packages/ai-parrot/tests/test_google_client.py`,
  `packages/ai-parrot/tests/clients/test_bedrock_*.py` (6 files),
  `packages/ai-parrot/tests/clients/test_nova.py`,
  `packages/ai-parrot/tests/unit/clients/test_*_multiround_usage.py` (6 files),
  `packages/ai-parrot/tests/unit/clients/test_codex_agent.py`,
  `packages/ai-parrot/tests/bots/test_rag_conversation_integration.py`,
  `packages/ai-parrot/tests/bots/test_vector_context_integration.py`,
  `packages/ai-parrot/tests/bots/test_voicebot_contract.py`,
  `packages/ai-parrot/tests/memory/unified/test_bot_integration.py`.
- **Responsibility**: tests that construct a client with
  `conversation_memory=` or call `client.ask(..., user_id=, session_id=)`
  move to `history=[HistoryMessage(...)]`; tests that asserted client-side
  memory writes now assert `_format_history` output instead. Tests listed
  from `grep` — re-verify the list at task time (server/integrations tests
  that matched only on `InMemoryConversation` for bot setup need no change).
- **Depends on**: Modules 4, 5, 6.

### Module 8: Documentation
- **Path**: `docs/memory/conversation-history-ownership.md` (new),
  `.agent/CONTEXT.md` (AbstractClient section: "memory-less; receives
  `history=`"; fix the stale `parrot/clients/abstract_client.py` path — the
  real file is `parrot/clients/base.py`), `sdd/proposals/per-turn-conversation-compactation.proposal.md`
  (one-line pointer: render extension point is `render_history`, not
  `get_messages_for_api(budget=)`).
- **Depends on**: Module 6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_bot_round_persists_exactly_one_turn` | M1 | Two `bot.ask()` rounds with `InMemoryConversation` ⇒ `len(history.turns) == 2` |
| `test_history_reaches_provider_once` | M1 | Stub client captures `messages`; round-1 text appears exactly once in round-2 messages |
| `test_system_prompt_has_no_history_digest` | M1 | `"## Conversation Context"` not in captured system prompt |
| `test_render_alternation` | M2 | Output roles strictly alternate `user, assistant, …` and end with `assistant` |
| `test_render_merges_consecutive_same_role` | M2 | Two user turns w/o assistant reply collapse into one user message |
| `test_render_skips_empty_assistant` | M2 | Turn with `assistant_response=""` produces no messages |
| `test_render_other_agent_label_and_filter` | M2 | `include_other_agents=False` drops foreign turns; `True` prefixes label |
| `test_render_max_turns` | M2 | `max_turns=2` keeps the last two turns only |
| `test_render_is_pure` | M2 | Same history rendered twice ⇒ equal lists; input history unmodified |
| `test_turn_chatbot_id_roundtrip` | M2 | `to_dict()`/`from_dict()` keep `chatbot_id`; legacy dict without key ⇒ `None` |
| `test_from_ai_message_metadata_shape` | M2 | Canonical metadata keys present; `tools_used` from `tool_calls` |
| `test_get_messages_for_api_removed` | M2 | `not hasattr(ConversationHistory, "get_messages_for_api")` |
| `test_memory_key_id_explicit_vs_name` | M3 | explicit `chatbot_id` ⇒ that id; none ⇒ `self.name`; two instances of the same unnamed-id bot share the key across "restarts" |
| `test_save_conversation_turn_keys_by_memory_key_id` | M3 | turn lands under `[user][memory_key_id][session]`; `turn.chatbot_id` mismatch ⇒ `ValueError` |
| `test_legacy_key_rekey_redis` | M2b | fakeredis: history under `conversation:u:s` only ⇒ `get_history(u, s, "bot")` returns it, writes `conversation:bot:u:s`, leaves legacy key; second call reads segmented key only |
| `test_legacy_key_rekey_file` | M2b | same contract on `FileConversationMemory` paths |
| `test_legacy_rekey_noop_when_segmented_exists` | M2b | segmented record present ⇒ legacy record never read |
| `test_save_conversation_turn_emits_event` | M3 | `MessageAddedEvent` emitted once per save |
| `test_create_llm_client_does_not_inject_memory` | M3 | Client instance has no `conversation_memory` attribute |
| `test_client_has_no_memory_surface` | M4 | `AbstractClient` lacks `conversation_memory`, `_prepare_conversation_context`, `_update_conversation_memory`, `start_conversation`, … |
| `test_format_history_default_shape` | M4 | Default `_format_history` emits text content blocks in order |
| `test_build_messages_history_then_prompt` | M4 | `[*history_msgs, current_user_msg]` ordering; files encoded once |
| `test_all_client_ask_signatures` | M5 | Parametrized over every concrete client class: `inspect.signature(ask)` has `history`, lacks `user_id`/`session_id`; same for `ask_stream` |
| `test_google_format_history` | M5 | `UserContent`/`ModelContent` mapping |
| `test_bedrock_format_history` | M5 | Converse `{"role","content":[{"text"}]}` mapping |
| `test_grok_has_no_private_memory_path` | M5 | No `conversation_memory` reference in `grok.py` (AST/grep test) |
| `test_basebot_llm_kwargs_carry_history_not_ids` | M6 | Stub client asserts `history` present and `user_id` absent for all four entry points |
| `test_ask_stream_partial_save_on_error` | M6 | Mid-stream exception ⇒ one turn saved with accumulated text (existing behaviour preserved) |
| `test_voicebot_turn_key_uses_memory_key_id` | M6 | Voice turn stored under `memory_key_id`-segmented key, same as `BaseBot` |
| `test_basebot_reads_history_with_key_id` | M6 | Stub memory asserts every `get_history`/`create_history` call carries `chatbot_id=bot.memory_key_id` |
| `test_model_switching_contrastive_single_turn` | M6 | `contrastive` mode ⇒ exactly one turn persisted per round |

### Integration Tests
| Test | Description |
|---|---|
| `test_redis_roundtrip_with_chatbot_id` | `RedisConversation` (fakeredis or marked `redis`) stores/loads a turn with `chatbot_id` under `conversation:{key_id}:{user}:{session}`; legacy record without the field loads as `None` |
| `test_two_agents_same_session_are_isolated` | Two bots, same `(user, session)`, different `memory_key_id` ⇒ two histories; neither sees the other's turns |
| `test_crew_shared_history_render_labels_foreign_turns` | A history that explicitly holds turns from two `chatbot_id`s (crew/flow case) renders foreign assistant turns with the `[agent:<id>]` label |
| `test_restart_keeps_history_for_unnamed_id_bot` | Bot without explicit `chatbot_id` re-instantiated with the same `name` ⇒ same key ⇒ history continues |
| `test_full_suite_green` | `timeout -s KILL 600 pytest tests/unit -q` and `pytest packages/ai-parrot/tests -q` pass (see memory note: unit suite hangs after summary — always wrap in `timeout`) |

### Test Data / Fixtures
```python
@pytest.fixture
def memory() -> InMemoryConversation:
    return InMemoryConversation()

class RecordingClient(AbstractClient):
    """Stub: records kwargs, returns a canned AIMessage. No network."""
    client_type = "recording"
    def __init__(self, reply: str = "ok", **kw):
        super().__init__(**kw); self.calls: list[dict] = []; self.reply = reply
    async def ask(self, prompt, model=None, *, system_prompt=None, history=None, **kw):
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt,
                           "history": list(history or ())})
        return AIMessage(input=prompt, output=self.reply, model="stub", provider="stub",
                         usage=CompletionUsage(), turn_id=str(uuid.uuid4()))
    async def ask_stream(self, prompt, **kw):
        yield self.reply

@pytest.fixture
def bot(memory) -> BaseBot:
    b = BaseBot(name="t", llm=RecordingClient(), memory_type="memory")
    b.conversation_memory = memory
    return b

@pytest.fixture
def two_agent_history() -> ConversationHistory:
    h = ConversationHistory(session_id="s", user_id="u")
    h.add_turn(ConversationTurn("t1", "u", "hi", "hello", chatbot_id="A"))
    h.add_turn(ConversationTurn("t2", "u", "more", "sure", chatbot_id="B"))
    return h
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] M1 regression test exists, is committed **red** against the pre-change
      code (evidence in `artifacts/logs/`), and is green at feature end.
- [ ] Exactly one `ConversationTurn` is persisted per bot round on every
      `BaseBot` entry point (`conversation`, `invoke`, `ask`, `ask_stream`),
      `DataAgent.ask`, `VoiceBot.ask_stream`.
- [ ] `grep -rn "conversation_memory\|_update_conversation_memory\|_prepare_conversation_context\|get_messages_for_api" packages/ai-parrot/src/parrot/clients/` returns **zero** lines.
- [ ] `grep -rn "user_id\|session_id" packages/ai-parrot/src/parrot/clients/*.py packages/ai-parrot/src/parrot/clients/google/` returns zero lines inside `ask`/`ask_stream` signatures (a parametrized `inspect.signature` test enforces this for every concrete client).
- [ ] No `parrot.memory` storage backend is imported from `parrot/clients/` (only `parrot.memory.render` types).
- [ ] `AbstractBot.build_conversation_context` and the `conversation_context` kwarg no longer exist; no system prompt produced by the bot contains `## Conversation Context`.
- [ ] `ConversationTurn.chatbot_id` is set (non-`None`) on every turn written by a bot; legacy records without the key still deserialize.
- [ ] `render_history` guarantees (alternation, merge, skip-empty, label/filter, `max_turns`, purity) each have a passing unit test.
- [ ] Every history read and write from any bot goes through the `(memory_key_id, user_id, session_id)` key on all three backends; no bot code path calls `get_history`/`create_history`/`add_turn` without `chatbot_id` (grep + stub-memory test M6).
- [ ] `memory_key_id` is stable across process restarts for bots without an explicit `chatbot_id` (equals `self.name`); the random `uuid4().hex` default never appears in a storage key.
- [ ] Legacy un-segmented Redis/File histories are transparently re-keyed on first read and the legacy record is left untouched (M2b tests); a segmented record present ⇒ legacy never consulted.
- [ ] `stateless=True` no longer appears in `packages/ai-parrot-tools/src/parrot_tools/security/summarizer.py` and `ask()` accepts no `stateless` parameter on any client.
- [ ] `MessageAddedEvent` is emitted once per persisted turn.
- [ ] `ModelSwitchingMixin` `fallback` and `contrastive` modes persist exactly one turn per round.
- [ ] Every direct `client.ask(...)` caller listed in §6 still compiles and its tests pass (none of them passed ids except those migrated in M6).
- [ ] All unit tests pass: `timeout -s KILL 600 pytest tests/unit -q` and `pytest packages/ai-parrot/tests -q`.
- [ ] `ruff check` clean on every touched file; the `print("DEBUG: …")` lines in `build_conversation_context` are gone with the method.
- [ ] Docs: `docs/memory/conversation-history-ownership.md` written; `.agent/CONTEXT.md` AbstractClient entry updated and the stale `abstract_client.py` path fixed.
- [ ] **Breaking change acknowledged**: `ask()`/`ask_stream()` signature change and removal of client-side memory are listed in the release notes for 0.29.0. (Hard cut — no shim, by decision.)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All line numbers verified on `dev` @ 2026-09-04 (after commit `27f0881e9`).
> Paths are relative to `packages/ai-parrot/src/`.

### Verified Imports
```python
from parrot.memory import ConversationHistory, ConversationMemory, ConversationTurn  # parrot/memory/__init__.py:3
from parrot.memory import FileConversationMemory   # parrot/memory/__init__.py:10
from parrot.memory import InMemoryConversation     # parrot/memory/__init__.py:11
from parrot.memory import RedisConversation        # parrot/memory/__init__.py:12
from parrot.models import AIMessage, AIMessageFactory  # parrot/models/__init__.py:9,11 (exported in __all__ :138)
from parrot.clients.base import AbstractClient     # parrot/clients/base.py:230
from parrot.bots.abstract import AbstractBot       # parrot/bots/abstract.py:187
from parrot.bots.base import BaseBot               # parrot/bots/base.py:71
from parrot.bots.mixins.model_switching import ModelSwitchingMixin  # bots/mixins/model_switching.py:57
```

### Existing Class Signatures
```python
# parrot/memory/abstract.py
@dataclass
class ConversationTurn:                                   # line 11
    turn_id: str; user_id: str; user_message: str; assistant_response: str
    context_used: Optional[str] = None; tools_used: List[str] = ...
    timestamp: datetime = ...; metadata: Dict[str, Any] = ...
    def to_dict(self) -> Dict[str, Any]                    # line 22
    @classmethod from_dict(cls, data) -> 'ConversationTurn' # line 36
    # NO chatbot_id field today.

@dataclass
class ConversationHistory:                                # line 51
    session_id: str; user_id: str; chatbot_id: Optional[str] = None
    turns: List[ConversationTurn]; created_at; updated_at; metadata
    def add_turn(self, turn) -> None                       # line 61
    def get_recent_turns(self, count: int = 5)             # line 66
    def get_messages_for_api(self, model: str = 'claude')  # line 70  ← REMOVE (M2)
    def clear_turns(self) -> None                          # line 100
    def to_dict / from_dict                                # lines 105 / 118

class ConversationMemory(ABC):                            # line 135
    def __init__(self, debug: bool = False)                # line 138
    async def create_history(user_id, session_id, metadata=None, chatbot_id=None)  # line 146
    async def get_history(user_id, session_id, chatbot_id=None)                    # line 157
    async def update_history(self, history) -> None                                # line 167
    async def add_turn(user_id, session_id, turn, chatbot_id=None) -> None         # line 172
    async def clear_history(...) / list_sessions(...) / delete_history(...)        # lines 183 / 193 / 202

# parrot/memory/mem.py
class InMemoryConversation(ConversationMemory):           # line 5
    def _get_chatbot_key(self, chatbot_id) -> str          # line 12  → str(id) if id else "_default"
    async def add_turn(...)                                # line 65  → get_history(...).add_turn(turn)
# parrot/memory/file.py
class FileConversationMemory(ConversationMemory):         # line 9;  add_turn line 83
# parrot/memory/redis.py
class RedisConversation(ConversationMemory):              # line 10
    def _get_key(self, user_id, session_id, chatbot_id=None) -> str  # line 31  (segment only if chatbot_id truthy, :39)
    async def add_turn(...)                                # line 193 (hash mode appends turn.to_dict() to 'turns')

# parrot/models/responses.py
class MessageResponse(TypedDict)                          # line 60
class AIMessage(BaseModel):                               # line 72
    input: str; output: Any                                # lines 76, 79
    model: str; provider: str; usage: CompletionUsage      # lines 111, 114, 118
    finish_reason: Optional[str]; tool_calls: List[ToolCall]  # lines 135, 139
    response_time: Optional[float]; session_id: Optional[str]; turn_id: Optional[str]  # 151, 160, 163
    @property content(self) -> Any  (+ setter)             # lines 245 / 257
    @property to_text(self) -> str                         # line 267
    used_conversation_history: bool                        # line 172 (metadata flag, keep)
    conversation_context_length via set_conversation_context_info()  # line 361 (keep; bot sets it)

# parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):             # line 230
    def __init__(self, conversation_memory: Optional[ConversationMemory] = None, preset=None,
                 tools=None, use_tools=False, debug=True, tool_manager=None, **kwargs)   # line 360
        self.conversation_memory = conversation_memory or InMemoryConversation()        # line 406
    def _get_chatbot_key(self, chatbot_id=None) -> Optional[str]      # line 1174 (getattr(self,'chatbot_id',None) — never set)
    async def start_conversation(...)                                  # line 1179
    async def get_conversation(...)                                    # line 1191
    async def clear_conversation(...)                                  # line 1201
    async def delete_conversation(...)                                 # line 1208
    async def list_user_conversations(...)                             # line 1216
    def _prepare_messages(self, prompt, files=None) -> List[Dict]      # line 1582 (KEEP — encodes current turn + files)
    async def ask(self, prompt, model, max_tokens=None, temperature=0.7, files=None, system_prompt=None,
                  structured_output=None, user_id=None, session_id=None, tools=None, use_tools=None,
                  deep_research=False, background=False, lazy_loading=False) -> MessageResponse   # line 1638
    async def ask_stream(...)                                          # line 1679
    async def _prepare_conversation_context(self, prompt, files, user_id, session_id, system_prompt,
                  stateless=False) -> tuple[List[Dict], Optional[ConversationHistory], Optional[str]]   # line 2269
    async def _update_conversation_memory(self, user_id, session_id, conversation_history, messages,
                  system_prompt, turn_id, original_prompt, assistant_response, tools_used=None)         # line 2375
    # provider HTTP for the generic path: self.session.post(endpoint, json=payload)  # line 2261

# parrot/bots/abstract.py
class AbstractBot(...):                                   # line 187
    self.chatbot_id = str(uuid.uuid4().hex)  (when not given)   # line 358
    self.conversation_memory: Optional[ConversationMemory] = None # line 585
    self.max_context_turns: int = kwargs.get('max_context_turns', 50)  # line 590
    def _create_llm_client(self, config: LLMConfig, conversation_memory=None) -> AbstractClient  # line 1028
        # injects memory into existing instance :1035-1036, into new client :1055; called at :1534
    def get_client(self) -> AbstractClient                 # line 1226
    async def execute_llm_call(self, client, method="ask", **llm_kwargs) -> Any  # line 1239
    def configure_conversation_memory(self) -> None        # line 1263
    def _build_prompt(..., conversation_context: str = "", ...)  # line 1382 (kwarg :1386); "chat_history" slot :1440
    def get_conversation_memory(self, storage_type="memory", **kwargs) -> ConversationMemory  # line 1781
    async def get_conversation_history(...)                # line 1798
    async def create_conversation_history(...)             # line 1816
    async def save_conversation_turn(self, user_id, session_id, turn, chatbot_id=None) -> None  # line 1836
        # chatbot_key = chatbot_id or getattr(self,'chatbot_id',None) :1847 ; emits MessageAddedEvent :1857+
        # ZERO callers in packages/*/src today.
    async def clear_conversation_history(...) / delete_conversation_history(...)  # lines 1873 / 1897
    def build_conversation_context(self, history, max_chars_per_message=200, max_total_chars=1500, ...) -> str  # line 2912 (print() debug :2922, :2926, :2929)
    async def create_system_prompt(self, user_context="", vector_context="", conversation_context="", kb_context="",
                  pageindex_context="", metadata=None, memory_context=None, **kwargs) -> Union[str, List]  # line 3072
        # "## Conversation Context:" section :3162-3163
    def __call__(self, question, **kwargs) -> self.ask(question, **kwargs)  # line 4183
    async def get_infographic(...)  client.ask(... session_id=, user_id=) # line 4330, call :4412

# parrot/bots/base.py
class BaseBot(AbstractBot):                               # line 71
    async def conversation(...)   # line 156 ; memory :323 ; get_history :326 ; build_conversation_context :329 ; ids in kwargs :445-446 ; ConversationTurn :525 ; add_turn :539
    async def invoke(...)         # line 600 ; :681 ; :684 ; :687 ; :705-706 ; :743 ; :757
    async def ask(...)            # line 932 ; :1095 ; :1099 ; :1102 ; :1285-1286 ; :1335 ; :1349
    async def ask_stream(...)     # line 1597 ; :1687 ; :1690 ; :1693 ; :1776 ; client.ask_stream(**llm_kwargs) :1804 ; partial save :1841-1853

# parrot/bots/mixins/model_switching.py
class ModelSwitchMode(str, Enum)                          # line 50
class ModelSwitchingMixin:                                # line 57
    async def execute_llm_call(self, client, method="ask", **llm_kwargs)  # line 169 (passes kwargs through)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `render_history()` | `ConversationHistory.turns` | reads dataclass fields | `memory/abstract.py:51-59` |
| `ConversationTurn.from_ai_message()` | `AIMessage.to_text`, `.tool_calls`, `.usage`, `.model`, `.provider`, `.finish_reason`, `.response_time`, `.turn_id` | attribute reads | `models/responses.py:111-163, 267` |
| `BaseBot.*` | `AbstractBot.save_conversation_turn()` | `await self.save_conversation_turn(user_id, session_id, turn)` (keys by `self.memory_key_id`) | `bots/abstract.py:1836` |
| `BaseBot.*` | `ConversationMemory.get_history()/create_history()` | `chatbot_id=self.memory_key_id` on every call | `bots/base.py:326, 684, 1099, 1690` |
| `BaseBot.*` | `AbstractClient.ask(history=...)` | `llm_kwargs["history"] = rendered` → `execute_llm_call` | `bots/base.py:445, 705, 1285, 1776`; `bots/abstract.py:1239` |
| `AbstractClient._build_messages()` | `AbstractClient._prepare_messages()` | appends current turn after formatted history | `clients/base.py:1582` |
| `GoogleClient._format_history()` | `google.genai.types.UserContent/ModelContent` | already used by hand at | `clients/google/analysis.py:282-292, 821-823` |
| `VoiceBot.ask_stream` | `save_conversation_turn(user_id, session_id, turn)` | replaces the direct `conversation_memory.add_turn(..., chatbot_id=str(self.chatbot_id))`; key now via `memory_key_id` | `bots/voice.py:642-645` |
| `DataAgent.ask` | `save_conversation_turn` | replaces hand-rolled turn | `bots/data.py:2088-2102` |
| `DatabaseAgent.ask` | `self._llm.ask(**call_kwargs)` — drop ids from `call_kwargs` | | `bots/database/agent.py:501, 534` |
| `synthesis.py` | `client.ask(...)` — drop ids | | `bots/flows/core/storage/synthesis.py:112, 205` |
| `storage/chat.py` (`ChatStorage`) | `RedisConversation.add_turn(..., chatbot_id=agent_id)` | **untouched** — separate tier | `storage/chat.py:202-211` |

**Direct `client.ask()` callers that pass NO ids today** (must keep
compiling; no change expected — verify at task time):
`handlers/llm.py:217`, `handlers/prompt.py:492` (ai-parrot-server);
`advisors/generator.py:300`; `parrot_tools/code_toolkit.py:231`,
`parrot_tools/db.py:826,1710`, `parrot_tools/security/summarizer.py:272,416`
(passes `stateless=True` — **this kwarg must survive or be removed at the
call sites; verify `ask` accepts it via `**kwargs` today**),
`parrot_tools/research/router.py:276`, `parrot_tools/codeinterpreter/tool.py:235`,
`parrot_tools/graphindex/toolkit.py:678`; core: `a2a/orchestrator.py:654`,
`bots/voice.py:391`, `bots/search.py:170-213` (delegates to `super().ask`),
`bots/kb.py:89`, `bots/scraper/scraper.py:103,432,760,859,930,1249`.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/clients/abstract_client.py`~~ — does not exist; `.agent/CONTEXT.md` is stale. `AbstractClient` lives in `parrot/clients/base.py:230`.
- ~~`parrot.memory.HistoryMessage`~~, ~~`parrot.memory.render`~~, ~~`render_history`~~ — to be created in M2.
- ~~`ConversationTurn.chatbot_id`~~, ~~`ConversationTurn.from_ai_message`~~ — to be created in M2.
- ~~`AbstractClient._format_history`~~, ~~`AbstractClient._build_messages`~~, ~~`history=` kwarg on `ask`~~ — to be created in M4.
- ~~`AbstractClient.chatbot_id`~~ — never assigned anywhere; `_get_chatbot_key` always resolves `None`.
- `ChatMessage` **exists twice but is NOT the neutral render type**: `parrot/storage/models.py:73` (per-message persistence unit with `message_id/session_id/agent_id/...`) and `ai-parrot-server/.../handlers/openai_compat.py:79` (HTTP schema). Do not reuse either; the new type is `HistoryMessage` precisely to avoid this collision.
- ~~`parrot.memory.ConversationSession`~~ — legacy name mentioned in a docstring (`abstract.py:52`); no such class.
- ~~`AbstractBot._record_turn`~~, ~~`AbstractBot._save_turn`~~ — do not exist; the single writer is `save_conversation_turn`.
- ~~`AbstractBot.memory_key_id`~~ — to be created in M3. Today there is no notion of "was `chatbot_id` explicit": `abstract.py:353-359` assigns `kwargs.get('chatbot_id', str(uuid.uuid4().hex))` and re-randomizes on `None`.
- ~~legacy-key fallback in `RedisConversation.get_history` / `FileConversationMemory.get_history`~~ — does not exist; `get_history` returns `None` when the exact key/path is missing (`redis.py:126`, `file.py:52`). To be created in M2b.
- ~~TTL on Redis history keys~~ — none; the only `expire` call is commented out (`redis.py:490`).
- ~~`ConversationMemory.get_messages_for_api`~~ — it was on `ConversationHistory`, not the memory backend, and is removed by M2.
- No client defines `_format_history` or accepts `history` today; `google/analysis.py` builds `UserContent`/`ModelContent` inline instead.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first throughout; `self.logger`, never `print` (the removed
  `build_conversation_context` is the last `print` debug in `abstract.py`
  for this path).
- Dataclasses for `parrot.memory` types (matches `ConversationTurn`/
  `ConversationHistory`); Pydantic stays for `AIMessage`.
- `render_history` is a **pure function**: no I/O, no logging side-effects
  that change output, no mutation of the input history. Property-style
  tests (purity, monotonic `max_turns`) as in the compaction proposal §7.
- Keep `_prepare_messages()` as the single place that encodes the current
  turn and files (FEAT-302 fix); `_build_messages` composes, never
  re-implements.
- One commit per module; M5 may be one commit per client. TDD: M1 red
  first, evidence in `artifacts/logs/`.
- Use `parrot.memory.render` as a **leaf module**: it may import
  `ConversationHistory`/`ConversationTurn` from `.abstract` only — never
  `.redis`/`.file`/`.mem` — so `parrot.clients` can import it without
  pulling storage backends.

### Known Risks / Gotchas
- **Key unification moves every `BaseBot` history to a new Redis key.**
  Today `BaseBot` writes `conversation:{user}:{session}`; after this feature
  it writes `conversation:{key_id}:{user}:{session}`. Redis history keys
  carry **no TTL** (`memory/redis.py:490` is commented out), so without M2b
  every live conversation would silently restart. M2b's lazy re-key is
  therefore mandatory, not optional; the legacy record is left in place so
  a rollback still finds it.
- **Random `chatbot_id` default.** `AbstractBot.__init__` assigns
  `uuid4().hex` when no `chatbot_id` is given (`abstract.py:353-359`). Keying
  by it would give ad-hoc bots (scripts, tools, tests, most `BaseBot`
  instances outside the DB-backed `Chatbot`) a fresh history per process.
  `memory_key_id` falls back to `self.name` for that reason. Consequence to
  accept: two *different* unnamed-id bots that share a `name` share a
  history. Bots loaded from the DB (`bots/chatbot.py:150-161`) always have
  an explicit id and are unaffected.
- **Re-key race.** Two concurrent first reads of the same legacy history
  may both copy it; the copy is idempotent (same content, `update_history`
  overwrites) so the race is benign. Do not add locking.
- **FEAT-523 (`pep-420-llm-clients`) moves the same 13 client files** into
  satellite packages and states "no in-flight specs touch `parrot/clients/`"
  — that is no longer true once this spec is approved. Sequence explicitly
  (see Worktree Strategy). Rebasing signature changes across a file move
  is error-prone; whichever lands second must re-run the M5 signature test.
- **Streaming partial save.** `ask_stream` persists accumulated text on
  mid-stream error (`base.py:1841`). `from_ai_message` needs an `AIMessage`;
  either synthesize one (the fallback path at `:1856+` already does) or
  give `from_ai_message` an `assistant_text` override. Do not lose this
  behaviour.
- **`stateless=True` callers.** `parrot_tools/security/summarizer.py:272,416`
  pass `stateless=True` to `ask`. Confirm whether that reaches `**kwargs`
  or a named parameter on the concrete client before deleting the concept;
  remove at the call sites if it becomes meaningless.
- **`AIMessage.used_conversation_history` / `set_conversation_context_info`**
  (`responses.py:172`, `:361`) are metadata flags the bot sets from
  `conversation_context`. Keep them, fed from `len(rendered)`.
- **Google `analysis.py`** hand-builds provider history from
  `conversation_history.turns` in two places (`:282-292`, `:821-823`). Both
  must switch to `self._format_history(history)`; easy to miss because they
  do not call `get_messages_for_api`.
- **`claude.py::ask_to_image` (`:1350`)** is the one non-`ask` path that
  calls `get_messages_for_api()` directly (`:1414`). It must take `history=`
  too or drop history support explicitly.
- **`live.py`** advertises "reuses conversation_memory" in its module and
  class docstrings (`:9`, `:503-507`); update the docs, not just the
  constructor.
- **Legacy Redis records** lack `chatbot_id`; `from_dict` must default it
  to `None` (`data.get('chatbot_id')`) — covered by the round-trip test.
- **Test suite hang.** `pytest tests/unit` finishes and then never exits
  in this environment; wrap in `timeout -s KILL` (memory note).
- **Concurrent sessions on `dev`.** Stage explicit paths only; never
  `git add -A` (memory note on SDD-session hazards).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | No new runtime dependencies. `fakeredis` (already a test extra) optional for the Redis round-trip test. |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Who owns turn recording — client or bot? — *Resolved (author, 2026-09-04)*: **AbstractBot exclusively**, turn built from the `AIMessage` after the client returns.
- [x] Should clients keep any conversation-memory logic for standalone use? — *Resolved (author)*: **No.** A bare client is the memory-less case by definition; it only receives history to build the provider messages.
- [x] Deprecation period for `user_id`/`session_id` on `ask()`? — *Resolved (author)*: **Hard cut.** No external consumers, no user overrides of `ask()`.
- [x] Must every message carry the invoking agent? — *Resolved (author)*: **Yes**, `ConversationTurn.chatbot_id`, always set by the bot.
- [x] History injection mechanism? — *Resolved (proposed by assistant, accepted)*: alternating messages via a neutral `HistoryMessage` list rendered in `parrot.memory`; provider formatting in the client; system-prompt digest removed.
- [x] **Storage key unification.** — *Resolved (author, 2026-09-04 spec review)*: **unify now to `(chatbot, user, session)`** on all backends. Consequences folded into §2 (Storage key), M2b (lazy legacy re-key, no TTL on Redis keys) and M3 (`memory_key_id` = explicit `chatbot_id` else `self.name`, because the default id is a random uuid per process).
- [x] **Default for `include_other_agents`** in `render_history`. — *Resolved (author)*: **`True`**, foreign assistant turns prefixed with `[agent:{chatbot_id}]`.
- [x] **Sequencing vs FEAT-523.** — *Resolved (author)*: **FEAT-524 first.** FEAT-523 (`pep-420-llm-clients`) does not create its worktree until this feature is merged to `dev`; its spec's "no in-flight specs touch `parrot/clients/`" claim should be amended to reference FEAT-524.
- [x] **`stateless=True` at `summarizer.py`.** — *Resolved (author)*: **delete at the two call sites** (`parrot_tools/security/summarizer.py:272`, `:416`); no no-op kwarg on `ask()`.
- [ ] **Shared `name` collision for unnamed-id bots.** Two distinct bots instantiated without `chatbot_id` but with the same `name` will share a history under the new key rule. Acceptable for v1 (today they share the *un-segmented* key anyway, which is strictly worse)? Revisit if a real collision is reported. — *Owner: Jesus Lara (non-blocking)*

---

## Worktree Strategy

- **Default isolation**: `per-spec` — one worktree
  `.claude/worktrees/feat-FEAT-524-conversation-history-ownership`, tasks
  sequential.
- **Parallelizable inside the worktree**: M1 ∥ M2 (disjoint files); within
  M5 the 13 client files are disjoint and may be split across agents, but
  all after M4 and all before M6 (M6 needs every client to accept `history`
  or `BaseBot` breaks for that provider).
- **Order**: M1 (red) → M2 → M2b → M3 → M4 → M5 → M6 → M7 → M8 → M1 (green).
  M2b ∥ M3 is possible (memory backends vs bot), both after M2.
- **Cross-feature dependencies**:
  - **FEAT-523 `pep-420-llm-clients`** (draft): touches the same
    `parrot/clients/*.py` files by *moving* them. **Decided: FEAT-524 merges
    to `dev` first; FEAT-523 creates its worktree only after that merge**
    and re-runs `test_all_client_ask_signatures` on the relocated files.
  - **FEAT-112 `per-loop-llm-client-cache`** (approved): its
    `conversation_memory` constructor reference (`spec:455`) becomes stale;
    no code dependency — cached clients simply become stateless.
  - **Compaction proposal** (`per-turn-conversation-compactation.proposal.md`,
    no FEAT yet): **must wait** for this feature to land on `dev`, then
    re-run `/sdd-brainstorm` against `render_history` as the extension
    point.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-04 | Jesus Lara | Initial draft from the 2026-09-04 design discussion (no brainstorm doc; decisions recorded in §2 and §8) |
| 0.2 | 2026-09-04 | Jesus Lara | Spec review: resolved the four §8 questions. Storage key unified to `(chatbot, user, session)` now → added `memory_key_id` (M3), lazy legacy re-key (M2b), new tests/criteria/risks; FEAT-524 sequenced before FEAT-523; `stateless=True` deleted at call sites; `include_other_agents=True`. |
