---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Per-Turn Conversation Compaction — Deterministic Stages (0 / 0.5 / 1)

**Feature ID**: FEAT-525
**Date**: 2026-09-04
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.30.0 (the minor after FEAT-524's 0.29.0 — this feature cannot ship before FEAT-524 merges)

> **Source documents**: `sdd/proposals/per-turn-conversation-compaction.brainstorm.md`
> (accepted, all 26 open questions resolved by the author on 2026-09-04,
> Recommended Option A) and
> `sdd/proposals/per-turn-conversation-compactation.proposal.md` (design
> concept, 2026-09-03).
>
> **Hard prerequisite — FEAT-524 `conversation-history-ownership`**
> (`sdd/specs/conversation-history-ownership.spec.md`, approved, 11 tasks
> in progress on a remote machine). FEAT-524 removes client-side memory,
> makes `AbstractBot.save_conversation_turn` the single writer, replaces
> `ConversationHistory.get_messages_for_api()` with the pure
> `render_history()`, and keys every history by `(memory_key_id, user,
> session)`. Every design point below is expressed against that contract.
> Per resolved constraint C14, **`/sdd-task` and the worktree for this
> feature wait until FEAT-524 merges to `dev`**, and every FEAT-524
> reference in §6 is re-verified on the merged code at that time.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

After FEAT-524, a stateful bot round works like this: the bot loads the
`ConversationHistory`, renders it with `render_history(max_turns=…)` into
alternating `HistoryMessage`s, hands them to a memory-less client, and
persists exactly one `ConversationTurn` built by
`ConversationTurn.from_ai_message()`. That fixes the double write and the
double injection. Three problems remain, and they are the ones this feature
exists for:

1. **Unbounded growth, lossy relief.** `render_history` replays every kept
   turn verbatim; the only bound is `max_turns` (`AbstractBot.max_context_turns`,
   default 50 at `bots/abstract.py:590`; `Chatbot` default 5 at
   `bots/chatbot.py:236,406`). Dropping whole turns is lossy and blind to
   size: five tool-heavy turns can cost more than fifty chatty ones.
2. **No token awareness.** Nothing in `parrot.memory` knows what a turn
   costs. `ContextAssembler` (`memory/unified/context.py`) and FEAT-380 use
   `len(text) // 4`. "Does this history fit the window?" cannot be answered
   without re-tokenizing the transcript, so nobody answers it.
3. **Tool activity is invisible and failures are forgotten.**
   `ConversationTurn.tools_used` stores tool *names* only
   (`memory/abstract.py:18`; FEAT-524 keeps the field). Inputs, outputs,
   errors and timing — the bulk of the token mass in agentic sessions and
   the part an agent most needs to remember ("that query failed") — are
   discarded at write time, even though `AIMessage.tool_calls` carries them
   (`ToolCall.arguments/result/error/execution_time`, `models/basic.py:23-30`).

**Who is affected:** every stateful bot round (`BaseBot.conversation/invoke/
ask/ask_stream`, `DataAgent`, `VoiceBot`), operators paying for replayed
tool output, and developers who cannot reason about context-window
pressure deterministically.

**Why now:** FEAT-380 (execution-time tool-result compression) and FEAT-397
(honest provider token counts per call) are done; FEAT-524 gives the two
things the proposal was missing — a single writer to hook and a single pure
render function to extend. This spec covers the deterministic plane only
(Stages 0, 0.5, 1). Stage 2 (LLM summary turns) stays out of scope with
hook points reserved.

### Goals

Each goal is a resolved brainstorm constraint (C-number kept for traceability):

- **G1 / C1 — Deterministic.** Same history + same config ⇒ same rendered
  bytes. No LLM call anywhere in Stages 0–1. Every transformation is a pure
  function testable with fixtures.
- **G2 / C2 — Non-destructive storage.** History always stores the
  normalized raw turn, where "raw" means *recoverable byte for byte*, not
  *inline*: tool outputs above `oversize_tool_tokens` are offloaded at write
  time into the memory-owned omission store (content-addressed, indexed by
  `turn_id`) with a short preview left in the turn. Pruning is computed at
  render time; pruned forms are never persisted. The only persisted
  compaction state is `history.metadata["compaction"]`.
- **G3 / C3 — Default-on, size-aware retention with a kill switch.** Every
  bot renders history through `compact_history` with a `ContextBudget` that
  always exists (from `MODEL_WINDOWS` when the model is known, else a 32k
  fallback). `context_budget=False` or `PARROT_COMPACTION_DISABLED=1`
  restores FEAT-524's plain `render_history(history, max_turns=…)` byte for
  byte.
- **G4 / C4 — Write-once, in the memory layer.** Stage 0 normalization and
  Stage 0.5 token counting run once, in a concrete
  `ConversationMemory.add_turn()` that delegates to a new abstract
  `_store_turn()`. Both are always-on for every writer (bot, `ChatStorage`
  tier, voice transcripts).
- **G5 / C5 — Backward-compatible payloads.** Turn dicts without the new
  fields deserialize unchanged; `tools_used` stays a real dataclass field.
- **G6 / C6 — Lossless pruning.** Omitted content goes to an
  `OmissionStore` owned by the `ConversationMemory` backend, retrievable
  via the built-in `read_omitted_content` tool. Separate from the FEAT-380
  working-memory tee.
- **G7 / C7 — Errors survive.** Turn-level and tool-level errors are never
  omitted; tracebacks are condensed by Stage 0 rule 5 only.
- **G8 / C8 — Uniform text rendering, appended to the assistant message.**
  Tool activity and omission notices render as a fenced block appended to
  the assistant content; no new `HistoryMessage` role, no provider-native
  blocks.
- **G9 / C9 — Compaction is a pure pre-pass; `render_history` learns tool
  text.** `compact_history()` is pure and synchronous; `render_history`'s
  first parameter widens to `ConversationHistory | Sequence[TurnView]`,
  with byte-identical output for a plain `ConversationHistory`.
- **G10 / C10 — Tokens are the retention unit; turns are the atomic unit.**
  Three tiers walked newest → oldest (verbatim ≤ `verbatim_tokens`, pruned ≤
  `high_watermark × available`, dropped), unified `max_turns=30` ceiling,
  oversize-result rule (`oversize_tool_tokens=2_000`, every turn but the
  newest).
- **G11 / C11 — Calibration pairing in `save_conversation_turn`.** The bot
  passes its prompt estimate; the memory owns the EWMA. Clients are never
  involved.
- **G12 / C12 — Session scoping via a new ContextVar** `current_memory_key_id`,
  bound *after* ids are defaulted; the recovery tool fails closed.
- **G13 / C13 — Prompt-cache honesty.** Renders are monotonic (persisted
  boundary); the oversize-result rule is the one deliberate exception.
- **G14 / C14 — Sequencing.** Spec now; `/sdd-task` and worktree after the
  FEAT-524 merge with §6 re-verified.
- **G15 / C15 — No new heavy dependencies.** `tiktoken`, `orjson` and
  `hypothesis` are already present.

### Non-Goals (explicitly out of scope)

- **Stage 2 (LLM summary turns).** Only the hook points are reserved:
  `stage2_needed` in `metadata.compaction`, `TurnState.SUMMARIZED`, and the
  lifecycle event that fires when a session outgrows deterministic pruning.
- **Compacting the `ChatStorage` tier** (`storage/chat.py`, `key_prefix="chat"`).
  It is normalized and counted (G4) but never compacted in v1; a budgeted
  `ChatStorage.get_context_for_agent` is a follow-up. Its stale
  `get_messages_for_api()` call at `storage/chat.py:638` belongs to FEAT-524.
- **Migrating the three existing `cl100k_base` sites** (`skills/parsers.py:29`,
  `knowledge/wiki/store.py:202`, `knowledge/pageindex/utils.py:53`) to
  `o200k_base` — separate feature (author, 2026-09-04).
- **`ContextAssembler`** (`memory/unified/context.py`) keeps `len(text) // 4`.
- **A `prune_policy` attribute on `AbstractTool`.** v1 uses a registry keyed
  by tool name; the attribute is a follow-up.
- **Any change to `parrot/clients/*`.** Clients are memory-less after
  FEAT-524; they only see longer assistant text.
- **A TTL on history keys**, an offline Redis migration, or shrinking stored
  histories. Rejected in brainstorm: Option B (mutate-at-write pruning),
  Option C (bot-side wrapper), Option D (reusing the FEAT-380 tee as the
  omission surface) — see the brainstorm's Options Explored.
- **A `"tool"` role on `HistoryMessage`** (rejected, C8).
- **An `AbstractToolkit` for `read_omitted_content`** (rejected — one plain
  function registered on `ToolManager`).

---

## 2. Architectural Design

### Overview

Option A from the brainstorm: **pure compaction pre-pass in `parrot.memory`,
budget-aware bot, memory-owned omission store.**

Storage keeps every turn normalized and token-counted (Stage 0 + 0.5 in the
`add_turn()` template method), offloading oversized tool outputs to the
omission store at write time. Each bot entry point, unless the kill switch
is set, calls `compact_history()` instead of capping by `max_turns`: the
pure pre-pass sums calibrated token counts, walks the three retention tiers,
applies per-tool `PrunePolicy` rules to the `tool_invocations` of pruned
turns, and returns turn views plus the list of omissions (content id +
bytes). The bot awaits `memory.omission_store.put_many(...)` (idempotent),
then calls `render_history(views, current_chatbot_id=…)`, which appends a
`<tool-activity>` text block to each assistant message (full for RAW views,
notices for PRUNED views). After the client answers, the bot builds the turn
via `from_ai_message()` (now also filling `tool_invocations` from
`tool_calls`) and calls `save_conversation_turn(user_id, session_id, turn,
compaction=CompactionCommit(...))`, which persists the turn **and** the
updated `metadata.compaction` (boundary, flags, EWMA) in one backend write.
A single internal tool, `read_omitted_content`, is registered on the bot's
`ToolManager` via `register_tool(name=…, description=…, input_schema=…,
function=…)` — the exact shape of the existing `search_tools` meta-tool
(`tools/manager.py:349-370`).

**Resolved decisions carried from the brainstorm** (authoritative; each one
is also echoed in §8):

- **Default-on.** Every bot gets size-aware retention with `max_turns=30`,
  `verbatim_tokens=15_000`, `min_verbatim_turns=2`,
  `oversize_tool_tokens=2_000`, window from `MODEL_WINDOWS` or `32_000`.
  Escape hatch: `context_budget=False` / `PARROT_COMPACTION_DISABLED=1`
  (mirrors FEAT-380's `PARROT_COMPRESSION_DISABLED` at
  `tools/compression/stage.py:148`).
- **Turn cap vs token budget.** Tokens are the retention unit, turns the
  atomic unit (three-tier walk); `max_turns=30` is a safety ceiling only.
  `Chatbot.max_context_turns` from the DB overrides the ceiling; no schema
  change.
- **Oversized tool results.** Pruned from every turn but the newest, even
  inside the verbatim tier; the notice offers both `read_omitted_content`
  and, when present, the FEAT-380 `_tee` working-memory key.
- **Write-time offload** of outputs above `oversize_tool_tokens` into the
  omission store, leaving a preview + `omitted["output"] = om_…` in the turn.
- **Omissions linked to `turn_id`** through a secondary index;
  `read_omitted_content` accepts a `content_id` or a `turn_id`.
- **Omission store owner:** the `ConversationMemory` backend (same Redis
  connection / file root / process dict); `clear_history` / `delete_history`
  cascade.
- **Omission TTL default `None`** (no expiry, like the history);
  configurable; notice text says "may have expired — re-run the tool".
- **Stage 0 always-on** for every writer; memory-level `normalize=False`
  escape hatch. **Token counting always-on** (`tiktoken` else heuristic).
- **Tokenizer:** `o200k_base`, name recorded per turn and in history
  metadata.
- **`context_used`:** excluded from `TokenCount.total` and the budget sum;
  never rendered in any tier (FEAT-524's `render_history` never rendered it).
- **Tool-text format:** appended `<tool-activity>` block, one line per
  invocation, omission notices inline, with a `Limit` for RAW turns (exact
  schema defined in Data Models below — the implementer decision the
  brainstorm delegated to this spec).
- **Per-tool `PrunePolicy`:** registry keyed by tool name, built-ins +
  `register_policy()`.
- **Stage 2 trigger surface:** `stage2_needed` persisted in
  `metadata.compaction` **and** a FEAT-176-style lifecycle event when it
  first flips.
- **`read_omitted_content` is a plain function**, no toolkit, registered on
  `ToolManager`, scoped by `current_memory_key_id` + user/session
  ContextVars, excluded from `search_tools` results.
- **Calibration pairing** inside `save_conversation_turn`, memory owns the
  EWMA; **commit travels into `add_turn(..., compaction=)`** so turn +
  state land in one write.
- **`oversize_tool_tokens = 2_000`** — proposed by the assistant, accepted in
  principle in the brainstorm; **confirmed here as the default** (a
  2k-token dataset is ~8 KB of JSON, well past what a later turn needs
  inline; the notice retrieves the exact bytes on demand).

**Derived decision (this spec):** `Chatbot` currently reads
`max_context_turns` from the DB with `default=5` (`bots/chatbot.py:406`).
Under G10 an *absent* DB value must mean "use `ContextBudget.max_turns`
(30)", so the DB read defaults to `None` and only an explicit DB value
becomes the ceiling override. The class-level fallback at `chatbot.py:236`
follows the same rule. This is the only reading consistent with "unified
`max_turns=30` for `AbstractBot` and `Chatbot`; DB value overrides".

**User-facing behavior**

- A support chat sees all its recent turns verbatim; a database agent sees
  its last answer verbatim and earlier datasets as notices.
- Tuning: `Agent(..., context_budget=ContextBudget(window=200_000,
  verbatim_tokens=…))` or bot-config keys; `Chatbot.max_context_turns`
  from the DB acts as the turn ceiling.
- Pruned turns keep user message and assistant text intact; tool I/O is
  replaced by `<tool-output-omitted …/>` notices; errors kept condensed.
- Verbatim (RAW) turns render a compact `<tool-activity>` block after the
  assistant text — tool activity becomes visible in history for the first
  time.
- The agent gains `read_omitted_content(content_id | turn_id)`: exact
  historical bytes, or a fixed "expired or unknown — re-run the tool"
  message.
- Operators read `history.metadata["compaction"]` (`tokenizer`,
  `calibration`, `boundary_turn_id`, `stage2_needed`).

### Component Diagram

```
 WRITE PATH (every writer: bot, ChatStorage tier, voice)                     READ PATH (budgeted bot round)
 ───────────────────────────────────────────────────────                     ────────────────────────────────
 ConversationTurn.from_ai_message(response)                                  memory.get_history(user, session, memory_key_id)
   ├─ tools_used      = [tc.name …]            (FEAT-524)                            │ ConversationHistory (+ metadata.compaction)
   ├─ tool_invocations= [ToolInvocation …]     (NEW)                                 ▼
   └─ error                                     (NEW)                       compact_history(history, budget, policies,
         │                                                                             boundary, counter, calibration)   ← pure, sync
         ▼                                                                             │ CompactionResult(views, omissions,
 ConversationMemory.add_turn(user, session, turn, chatbot_id,                          │   history_estimate, boundary_turn_id,
                             compaction=CompactionCommit|None)   ← concrete           │   stage2_needed)
   1. normalize_turn(turn)          Stage 0   (unless normalize=False)                 ▼
   2. count_turn(turn, counter)     Stage 0.5 (tiktoken o200k_base | heuristic)  await memory.omission_store.put_many(key, omissions)
   3. offload oversize outputs  →  OmissionStore.put(key, content, turn_id=…)          │ (failure ⇒ plain FEAT-524 render, warn)
   4. next_state = apply_commit(metadata.compaction, commit)  (EWMA, boundary)         ▼
   5. await self._store_turn(user, session, turn, chatbot_id,               render_history(views, current_chatbot_id=…)
                             compaction_state=next_state)    ← abstract, 1 write       │ list[HistoryMessage]  (assistant += suffix)
         │                                                                             ▼
         ├─ InMemoryConversation._store_turn                                   client.ask(prompt, history=…)  (memory-less)
         ├─ RedisConversation._store_turn   (hset turns+updated_at+metadata)          │ AIMessage(usage, tool_calls)
         └─ FileConversationMemory._store_turn                                          ▼
                                                                               AbstractBot.save_conversation_turn(user, session, turn,
 OmissionStore (owned by the memory backend)                                        compaction=CompactionCommit(prompt_estimate,
   InMemory | Redis {prefix}_omitted:{key_id}:{user}:{session} | File               boundary_turn_id, stage2_needed))
   content_id = "om_" + blake2b(content, 8).hexdigest()                                │
   index: turn_id → [content_id]                                                        ├─ memory.add_turn(..., compaction=commit)
   clear/delete cascade from ConversationMemory                                         ├─ MessageAddedEvent (after the write)
         ▲                                                                              └─ Stage2CompactionNeededEvent (first flip only)
         │ get(key, content_id) / get_by_turn(key, turn_id)
 read_omitted_content(content_id=None, turn_id=None)   ← plain async fn, ToolManager.register_tool(function=…)
   key ← (current_memory_key_id, current_user_id, current_session_id)   fail closed on any None
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `memory/abstract.py` `ConversationTurn` (FEAT-524 shape) | extends | new fields with defaults (`tool_invocations`, `error`, `token_count`, `state`, `schema_version`, `norm_version`); `from_ai_message` fills `tool_invocations`/`error`; `to_dict`/`from_dict` carry them; `tools_used` unchanged. |
| `memory/abstract.py` `ConversationMemory` | modifies | `add_turn` becomes concrete (normalize → count → offload → `_store_turn`); new abstract `_store_turn`; new `report_usage`, `omission_key`; constructor gains `token_counter`, `omission_store`, `normalize`; `clear_history`/`delete_history` cascade to the omission store (template wrappers around new abstract `_clear_history`/`_delete_history` **or** an explicit cascade call in each backend — implementer's choice, tested either way). |
| `memory/mem.py`, `memory/redis.py`, `memory/file.py` | modifies | `add_turn` bodies renamed `_store_turn` and extended to persist `compaction_state` into `metadata` in the same write; each constructs its matching `OmissionStore`. Redis: one `hset` with `turns`, `updated_at`, `chatbot_id`, `metadata`. |
| `memory/render.py` (FEAT-524) | extends | first parameter widened to `ConversationHistory \| Sequence[TurnView]`; appends `TurnView.assistant_suffix` to assistant content before the merge/alternation logic; plain-history output byte-identical; still imports only `.abstract` (and the `TurnView` type from `.compaction.models` under `TYPE_CHECKING` only — see §7). |
| `memory/compaction/` (new package) | new | `models.py`, `normalize.py`, `tokens.py`, `budget.py`, `policies.py`, `compact.py`, `omission.py`, `recover.py`. Leaf rule: imports `parrot.memory.abstract` and stdlib/`orjson`/`tiktoken` only; never `parrot.tools`, never `parrot.bots`. |
| `memory/__init__.py` | extends | export `ContextBudget`, `CompactionResult`, `CompactionCommit`, `OmissionStore`, `TokenCounter`, `TokenCount`, `ToolInvocation`, `ToolStatus`, `TurnState`, `TurnView`, `compact_history`. |
| `bots/abstract.py:590` `max_context_turns` default 50; `bots/chatbot.py:236,406,578,626` default 5 | modifies | one default (`ContextBudget.max_turns=30`) as a ceiling; `max_context_turns` default becomes `None` at both classes; an explicit value (kwarg or DB) overrides the ceiling only. |
| `bots/abstract.py` (FEAT-524 shape) | extends | `context_budget` kwarg (`None` ⇒ auto-built; `ContextBudget` ⇒ as given; `False` ⇒ disabled); `context_budget` property; `render_context_history()` helper; `save_conversation_turn(..., compaction=None)`; `register_tool(name="read_omitted_content", function=…)` on the bot's `ToolManager` when budgeted; Stage-2 event emission. |
| `bots/base.py` four entry points (FEAT-524 M6 shape) | modifies | budget branch via `render_context_history()`; bind `current_memory_key_id` alongside user/session **after** defaulting the ids; pass the commit into `save_conversation_turn`. |
| `bots/data.py`, `bots/voice.py` (FEAT-524 M6 shape) | modifies | same budget branch where a history is rendered; same binding order. |
| `observability/context.py:56-60, 91` | extends | `current_memory_key_id` ContextVar; `invocation_context(..., memory_key_id=None)`; `__all__` updated. |
| `memory/compaction/recover.py` `read_omitted_content()` | new | plain async function; bound to a memory at registration; registered via `ToolManager.register_tool(function=…)` (`tools/manager.py:714`, precedent `:349-370`). |
| `tools/manager.py:608` | extends (one line) | exclude `read_omitted_content` from `search_tools` results alongside `search_tools` itself (a small module-level frozenset of internal names). The `clone()` gate at `:2109` keys on `include_search_tool` only and is **not** changed — the recovery tool must survive `clone()` because the bot registers it once. |
| `core/events/lifecycle/events/` | extends | new `Stage2CompactionNeededEvent(LifecycleEvent)` in a new `memory.py`, exported from `events/__init__.py`; emitted by `AbstractBot.save_conversation_turn` via `await self.events.emit(...)` (same call shape as `MessageAddedEvent`, `bots/abstract.py:1863`). |
| `storage/chat.py:54, 209` | depends on | `RedisConversation(key_prefix="chat").add_turn` inherits normalization/counting/offload; never compacted. |
| FEAT-380 `tools/compression/tee.py` | consumed | when a `ToolCall.result` dict carries a `_tee` block (`attach_tee_pointer`, `tee.py:161-182`), its `key` is copied into the omission notice as `wm="…"`. Nothing in FEAT-380 is modified. |
| FEAT-397 `AIMessage.usage` (`CompletionUsage.input_tokens`) | consumed | provider prompt tokens for calibration. |
| `parrot/clients/*` | **none** | memory-less after FEAT-524; `_format_history` sees longer assistant text only. |
| `pyproject.toml` | none | `tiktoken`, `orjson`, `hypothesis` already present. |

**Breaking changes:** none for callers. Internal: `ConversationMemory`
subclasses must implement `_store_turn` instead of `add_turn` (hard cut; all
three in-repo backends updated in-feature; no external consumers per the
author). New Redis keys `{prefix}_omitted:{key_id}:{user}:{session}` and
`{prefix}_omitted_turns:{key_id}:{user}:{session}`.

### Data Models

All new models are `@dataclass(frozen=True)` unless they must be mutated by
the storage layer (`ToolInvocation`, `ConversationTurn`). They live in
`parrot/memory/compaction/models.py` unless stated otherwise. Pydantic is
**not** used here on purpose: `ConversationTurn`/`ConversationHistory` are
stdlib dataclasses with hand-written `to_dict`/`from_dict`
(`memory/abstract.py:22-47`), and the compaction models must round-trip
through the same `JSONContent`/`orjson` path without a second serializer.

```python
# parrot/memory/compaction/models.py

class ToolStatus(str, Enum):
    COMPLETED = "completed"
    ERROR = "error"


class TurnState(str, Enum):
    RAW = "raw"              # storage always writes RAW in v1
    PRUNED = "pruned"        # view-only state produced by compact_history
    SUMMARIZED = "summarized"  # reserved for Stage 2 — never produced here


@dataclass
class ToolInvocation:
    """One tool call captured from ``AIMessage.tool_calls`` (models/basic.py:23-30)."""
    tool_name: str
    input: Dict[str, Any]                       # canonical (orjson OPT_SORT_KEYS) after Stage 0
    output: Optional[str] = None                # full text, or the preview when omitted["output"] is set
    status: ToolStatus = ToolStatus.COMPLETED
    error: Optional[str] = None                 # never omitted; condensed by Stage 0 rule 5
    elapsed_ms: Optional[int] = None
    output_chars: Optional[int] = None          # length of the ORIGINAL output (set before any offload)
    omitted: Dict[str, str] = field(default_factory=dict)   # field name -> content_id ("om_…"); v1 uses "output" only
    wm_key: Optional[str] = None                # FEAT-380 tee key copied from result["_tee"]["key"] when present

    def to_dict(self) -> Dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolInvocation": ...   # tolerant: missing keys → defaults


@dataclass(frozen=True)
class TokenCount:
    """Per-turn token accounting. ``context_used`` is deliberately NOT counted."""
    user: int
    assistant: int
    tools: int                 # sum over invocations: canonical input JSON + output (preview if offloaded) + error
    total: int                 # user + assistant + tools
    tokenizer: str             # counter name, e.g. "o200k_base" or "heuristic"

    def to_dict(self) -> Dict[str, int | str]: ...
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TokenCount": ...


@dataclass(frozen=True)
class Limit:
    """Bound on the RAW ``<tool-activity>`` block so a chatty recent turn cannot blow the budget by itself."""
    max_invocations: int = 12
    max_input_chars: int = 200        # per-invocation input summary
    max_output_chars: int = 400       # per-invocation output excerpt in RAW views
    max_block_tokens: int = 1_500     # whole block; beyond it the remaining lines collapse to "… +N more"


@dataclass(frozen=True)
class ContextBudget:
    window: int                        # from MODEL_WINDOWS, else FALLBACK_WINDOW (32_000)
    reserve_output: int = 8_192
    reserve_fixed: int = 4_096         # system prompt + tool schemas + provider framing allowance
    high_watermark: float = 0.80
    low_watermark: float = 0.60        # reserved for Stage 2 (target after summarization); unused by the walk
    max_turns: int = 30                # unified ceiling (was AbstractBot 50 / Chatbot 5)
    verbatim_tokens: int = 15_000
    min_verbatim_turns: int = 2
    oversize_tool_tokens: int = 2_000
    tool_activity_limit: Limit = Limit()

    @property
    def available(self) -> int:        # window - reserve_output - reserve_fixed (never < 0)
        ...
    # __post_init__ validates: window > reserve_output + reserve_fixed, 0 < watermarks <= 1,
    # max_turns >= min_verbatim_turns >= 1, verbatim_tokens >= 0, oversize_tool_tokens > 0.


FALLBACK_WINDOW: int = 32_000

# parrot/memory/compaction/budget.py
MODEL_WINDOWS: Dict[str, int]   # NEW — longest-prefix match on the model name (lower-cased), e.g.
                                # {"claude-": 200_000, "gpt-4o": 128_000, "gpt-4.1": 1_047_576, "gpt-5": 400_000,
                                #  "o1": 200_000, "o3": 200_000, "gemini-": 1_048_576, "llama-3.1": 131_072, …}
                                # Implementer keeps it small and tested; unknown → FALLBACK_WINDOW.

def resolve_window(model: Optional[str]) -> int: ...
def build_default_budget(model: Optional[str], *, max_turns: Optional[int] = None) -> ContextBudget: ...
def compaction_disabled_by_env() -> bool: ...          # os.getenv("PARROT_COMPACTION_DISABLED") == "1"


@dataclass(frozen=True)
class CompactionState:
    """Persisted as ``history.metadata["compaction"]`` (dict form). The ONLY persisted compaction state."""
    tokenizer: str
    calibration: float = 1.0           # EWMA of provider_prompt_tokens / prompt_estimate, clamped [0.5, 2.0]
    samples: int = 0
    boundary_turn_id: Optional[str] = None   # turns at/before it always render PRUNED (monotonic)
    stage2_needed: bool = False
    updated_at: Optional[str] = None   # ISO-8601

EWMA_ALPHA: float = 0.2
CALIBRATION_MIN, CALIBRATION_MAX = 0.5, 2.0

def apply_usage(state: CompactionState, prompt_estimate: int,
                provider_prompt_tokens: Optional[int]) -> CompactionState: ...   # pure; ignores estimate<=0 / None usage
def apply_commit(state: Optional[CompactionState], commit: "CompactionCommit",
                 tokenizer: str) -> CompactionState: ...                          # pure; boundary never regresses


@dataclass(frozen=True)
class Omission:
    content_id: str            # "om_" + blake2b(content.encode(), digest_size=8).hexdigest()
    content: str
    turn_id: str
    tool_name: str
    field: str                 # "output" in v1


@dataclass(frozen=True)
class TurnView:
    """Materialized text for one turn. ``render_history`` only concatenates it."""
    turn_id: str
    chatbot_id: Optional[str]
    user_text: str
    assistant_text: str
    assistant_suffix: str      # "" | "\n\n<tool-activity>…</tool-activity>" — already rendered
    state: TurnState           # RAW | PRUNED
    estimated_tokens: int      # calibrated size actually charged to the budget


@dataclass(frozen=True)
class CompactionResult:
    views: Tuple[TurnView, ...]            # oldest → newest, ready for render_history
    omissions: Tuple[Omission, ...]        # to flush before rendering (idempotent put_many)
    history_estimate: int                  # sum of views' estimated_tokens
    boundary_turn_id: Optional[str]        # new monotonic boundary (>= persisted one)
    stage2_needed: bool
    dropped_turn_ids: Tuple[str, ...]


@dataclass(frozen=True)
class CompactionCommit:
    """What the bot hands to save_conversation_turn after the round."""
    prompt_estimate: int                   # tokens(rendered history) + tokens(system_prompt) + tokens(prompt)
    boundary_turn_id: Optional[str]
    stage2_needed: bool
```

```python
# parrot/memory/abstract.py — ConversationTurn (FEAT-524 shape, extended)
@dataclass
class ConversationTurn:
    turn_id: str
    user_id: str
    user_message: str
    assistant_response: str
    context_used: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)          # UNCHANGED (real field, C5)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    chatbot_id: Optional[str] = None                             # FEAT-524
    tool_invocations: List[ToolInvocation] = field(default_factory=list)   # NEW
    error: Optional[str] = None                                  # NEW — round-level failure text (condensed)
    token_count: Optional[TokenCount] = None                     # NEW — stamped by add_turn
    state: TurnState = TurnState.RAW                             # NEW — storage always RAW in v1
    schema_version: int = 1                                      # NEW — 2 once written by add_turn
    norm_version: Optional[str] = None                           # NEW — NORM_VERSION stamped by add_turn

    # to_dict emits every field; from_dict tolerates absence of every NEW field (legacy → defaults).
    @classmethod
    def from_ai_message(cls, *, user_message, response, user_id, chatbot_id,
                        context_used=None, turn_id=None, assistant_text=None,
                        error: Optional[str] = None) -> "ConversationTurn":   # FEAT-524 + `error`
        # tool_invocations = [ToolInvocation(tool_name=tc.name, input=tc.arguments,
        #                     output=_stringify(tc.result), status=ERROR if tc.error else COMPLETED,
        #                     error=tc.error, elapsed_ms=int(tc.execution_time*1000) if tc.execution_time else None,
        #                     wm_key=_tee_key(tc.result)) for tc in response.tool_calls]
        ...
```

```python
# parrot/memory/compaction/tokens.py
class TokenCounter(Protocol):
    name: str
    def count(self, text: str) -> int: ...

class TiktokenCounter:          # name == encoding name ("o200k_base"); lazy module-level cache of the encoding
    def __init__(self, encoding: str = "o200k_base") -> None: ...
class HeuristicCounter:         # name == "heuristic"; len(text.encode("utf-8")) // 4, minimum 1 for non-empty
    ...
def get_default_counter() -> TokenCounter: ...    # tiktoken if importable AND encoding loads, else heuristic; warns once
def count_turn(turn: ConversationTurn, counter: TokenCounter) -> TokenCount: ...
def needs_recount(turn: ConversationTurn, counter: TokenCounter) -> bool: ...   # None or tokenizer mismatch


# parrot/memory/compaction/normalize.py
NORM_VERSION: str = "1"
def normalize_text(text: str) -> str: ...                      # rules 1-3
def canonical_json_text(text: str) -> str: ...                  # rule 4 (returns input unchanged if not JSON object/array)
def condense_traceback(text: str, *, keep_frames: int = 3) -> str: ...   # rule 5
def normalize_invocation(inv: ToolInvocation) -> ToolInvocation: ...
def normalize_turn(turn: ConversationTurn) -> ConversationTurn: ...   # returns a NEW turn; idempotent; stamps norm_version


# parrot/memory/compaction/policies.py
@dataclass(frozen=True)
class PrunedInvocation:
    notice: str                            # one line, e.g. <tool-output-omitted tool="…" chars="…" id="om_…" wm="…"/>
    omissions: Tuple[Omission, ...]

class PrunePolicy(Protocol):
    name: str
    def prune(self, inv: ToolInvocation, *, turn_id: str) -> PrunedInvocation: ...

POLICY_VERSION: str = "1"
class DefaultPolicy: ...          # omit output → notice; keep input summary (Limit.max_input_chars); keep error verbatim
class FileWritePolicy: ...        # keep path + byte count; omit content
class FileReadPolicy: ...         # keep path; omit content
class ShellPolicy: ...            # keep command + exit code; omit stdout/stderr (errors kept)
class SubAgentPolicy: ...         # keep task line; omit transcript
class QueryPolicy: ...            # HTTP / search / DB: keep query/url + row/hit count; omit body
def register_policy(tool_name: str, policy: PrunePolicy) -> None: ...
def get_policy(tool_name: str) -> PrunePolicy: ...            # exact name → built-in alias table → DefaultPolicy
def prune_turn(turn: ConversationTurn, *, policies=None) -> Tuple[str, Tuple[Omission, ...]]: ...
    # returns (assistant_suffix for a PRUNED view, omissions); pure; content ids computed here


# parrot/memory/compaction/compact.py
def render_tool_activity(turn: ConversationTurn, limit: Limit) -> str: ...   # RAW view suffix; "" when no invocations
def compact_history(
    history: ConversationHistory,
    budget: ContextBudget,
    *,
    policies: Optional[Mapping[str, PrunePolicy]] = None,
    boundary_turn_id: Optional[str] = None,
    counter: Optional[TokenCounter] = None,        # used only for turns lacking a (matching) token_count
    calibration: float = 1.0,
    current_chatbot_id: Optional[str] = None,
    include_other_agents: bool = True,
) -> CompactionResult: ...


# parrot/memory/compaction/omission.py
def content_id(content: str) -> str: ...
class OmissionStore(ABC):
    ttl: Optional[int]                      # seconds; None = no expiry (default)
    @abstractmethod async def put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str: ...
    async def put_many(self, session_key: str, omissions: Sequence[Omission]) -> None: ...   # default: loop over put
    @abstractmethod async def get(self, session_key: str, content_id: str) -> Optional[str]: ...
    @abstractmethod async def list_by_turn(self, session_key: str, turn_id: str) -> List[str]: ...   # content ids
    @abstractmethod async def clear(self, session_key: str) -> None: ...
class InMemoryOmissionStore(OmissionStore): ...
class RedisOmissionStore(OmissionStore): ...   # shares the RedisConversation client; hash per session + turn index hash
class FileOmissionStore(OmissionStore): ...    # {base_path}/_omitted/{session_key_safe}/{content_id}.txt + index.json

EXPIRED_MESSAGE: str = "Omitted content om_… is unknown or may have expired — re-run the tool to regenerate it."


# parrot/memory/compaction/recover.py
READ_OMITTED_CONTENT_SCHEMA: Dict[str, Any]     # {"type":"object","properties":{"content_id":{…},"turn_id":{…}}}
def bind_read_omitted_content(memory: ConversationMemory) -> Callable[..., Awaitable[str]]: ...
    # returns `async def read_omitted_content(content_id: Optional[str] = None, turn_id: Optional[str] = None) -> str`
    # resolves (current_memory_key_id, current_user_id, current_session_id); any None ⇒ fixed
    # "unavailable in this context" text; content_id ⇒ bytes or EXPIRED_MESSAGE; turn_id ⇒ concatenated
    # "<omitted id=…>\n…\n</omitted>" blocks for that turn (or the same fixed message when none).
```

```python
# parrot/memory/abstract.py — ConversationMemory (extended)
class ConversationMemory(ABC):
    def __init__(self, debug: bool = False, *,
                 token_counter: Optional[TokenCounter] = None,   # default: get_default_counter()
                 omission_store: Optional[OmissionStore] = None, # default: backend-specific (see backends)
                 normalize: bool = True,
                 oversize_tool_tokens: int = 2_000) -> None: ...  # write-time offload threshold (same default as ContextBudget)

    @property
    def omission_store(self) -> OmissionStore: ...
    @property
    def token_counter(self) -> TokenCounter: ...
    def omission_key(self, user_id: str, session_id: str, chatbot_id: Optional[str]) -> str: ...
        # "{memory_key_id}:{user}:{session}" — backends prefix it ("{prefix}_omitted:")

    async def add_turn(self, user_id: str, session_id: str, turn: ConversationTurn,
                       chatbot_id: Optional[str] = None, *,
                       compaction: Optional[CompactionCommit] = None) -> None:   # CONCRETE template method
        # 1. if self._normalize: turn = normalize_turn(turn)
        # 2. if needs_recount(turn, counter): turn.token_count = count_turn(turn, counter)
        # 3. for inv in turn.tool_invocations: if counter.count(inv.output) > oversize_tool_tokens and "output" not in inv.omitted:
        #        cid = await store.put(key, inv.output, turn_id=turn.turn_id); inv.output_chars = len(inv.output)
        #        inv.output = preview(inv.output); inv.omitted["output"] = cid; (recount tools/total)
        # 4. turn.schema_version = 2
        # 5. state = apply_commit(existing metadata.compaction, compaction, counter.name) if compaction else None
        # 6. await self._store_turn(user_id, session_id, turn, chatbot_id, compaction_state=state)

    @abstractmethod
    async def _store_turn(self, user_id: str, session_id: str, turn: ConversationTurn,
                          chatbot_id: Optional[str] = None, *,
                          compaction_state: Optional[Dict[str, Any]] = None) -> None: ...
        # persists the turn AND (when given) metadata["compaction"] in ONE backend write

    async def report_usage(self, user_id: str, session_id: str, *,
                           estimated_prompt_tokens: int, provider_prompt_tokens: Optional[int],
                           chatbot_id: Optional[str] = None) -> None: ...
        # standalone calibration update (no turn write) — used by ask_stream partial-save paths and tests;
        # the normal path folds the same apply_usage() into add_turn(compaction=…)

    # clear_history / delete_history: every backend calls
    #   await self.omission_store.clear(self.omission_key(user_id, session_id, chatbot_id))
    # after its own clear/delete (tested for all three).
```

```python
# parrot/bots/abstract.py — AbstractBot (FEAT-524 shape, extended)
class AbstractBot(...):
    def __init__(self, ..., context_budget: Optional[ContextBudget | bool] = None,
                 max_context_turns: Optional[int] = None, ...): ...
        # self._context_budget_raw = context_budget
        # self.max_context_turns: Optional[int] = kwargs.get('max_context_turns')   # None ⇒ budget.max_turns

    @property
    def context_budget(self) -> Optional[ContextBudget]:
        # False or PARROT_COMPACTION_DISABLED=1 ⇒ None (disabled)
        # ContextBudget ⇒ as given (max_turns overridden by an explicit self.max_context_turns)
        # None ⇒ build_default_budget(self._llm_model, max_turns=self.max_context_turns); unknown model logged once

    async def render_context_history(
        self, history: Optional[ConversationHistory],
    ) -> Tuple[List[HistoryMessage], Optional[CompactionResult]]:
        # budget is None  ⇒ (render_history(history, max_turns=self.max_context_turns or 30,
        #                                    current_chatbot_id=self.memory_key_id), None)   ← FEAT-524 plain path
        # else            ⇒ result = compact_history(history, budget, boundary_turn_id=…, calibration=…,
        #                                            counter=memory.token_counter, current_chatbot_id=self.memory_key_id)
        #                    try: await memory.omission_store.put_many(key, result.omissions)
        #                    except Exception: warn; return plain path, None
        #                    return render_history(result.views, current_chatbot_id=self.memory_key_id), result

    async def save_conversation_turn(self, user_id: str, session_id: str, turn: ConversationTurn, *,
                                     compaction: Optional[CompactionCommit] = None) -> None:
        # FEAT-524 body (keys by memory_key_id; asserts turn.chatbot_id) + passes compaction into add_turn;
        # provider_prompt_tokens read from turn.metadata["usage"]["input_tokens"] when present;
        # MessageAddedEvent after the write; Stage2CompactionNeededEvent when stage2_needed flips False→True.

    def _register_recovery_tool(self) -> None:
        # called once when a budget is active and conversation memory is configured:
        # self.tool_manager.register_tool(name="read_omitted_content", description=…,
        #                                 input_schema=READ_OMITTED_CONTENT_SCHEMA,
        #                                 function=bind_read_omitted_content(self.conversation_memory))
```

```python
# parrot/observability/context.py (extended)
current_memory_key_id: ContextVar[Optional[str]] = ContextVar("parrot_current_memory_key_id", default=None)

@contextmanager
def invocation_context(agent_name, user_id=None, session_id=None, memory_key_id=None) -> Iterator[None]: ...
# __all__ += ["current_memory_key_id"]


# parrot/core/events/lifecycle/events/memory.py (NEW)
@dataclass(frozen=True)
class Stage2CompactionNeededEvent(LifecycleEvent):
    """Emitted once per session when deterministic pruning can no longer fit the history."""
    agent_name: str = ""
    session_id: str = ""
    history_estimate: int = 0
    available: int = 0
    dropped_turns: int = 0
```

**Rendered text formats (normative):**

```
# RAW view — appended to the assistant content after "\n\n"
<tool-activity>
- query_database ok 1.2s in={"sql":"SELECT * FROM sales WHERE …"} out=3 rows: [{"id":1,…}] …(+48,213 chars)
- write_file ok 0.1s in={"path":"report.md"} out=written 2,140 bytes
- fetch_url error 3.0s in={"url":"https://…"} error=HTTPError 503 (condensed)
… +4 more
</tool-activity>

# PRUNED view — same wrapper, one notice line per invocation (from its PrunePolicy)
<tool-activity>
- query_database ok 1.2s in={"sql":"SELECT * FROM sales …"} <tool-output-omitted tool="query_database" chars="48213" id="om_3f9a1c2b7d4e5f60" wm="__tee__:query_database:…"/>
- write_file ok 0.1s in={"path":"report.md"} <tool-output-omitted tool="write_file" chars="2140" id="om_…"/>
- fetch_url error 3.0s in={"url":"https://…"} error=HTTPError 503 (condensed)
</tool-activity>
Omitted content can be recovered with read_omitted_content(content_id) or read_omitted_content(turn_id="…").
```

Rules: `in=` is the canonical JSON of `ToolInvocation.input` truncated to
`Limit.max_input_chars`; `out=` is the output excerpt truncated to
`Limit.max_output_chars` with `…(+N chars)`; `error=` is always present when
set and never truncated beyond Stage 0 rule 5; `wm=` appears only when
`ToolInvocation.wm_key` is set; the trailing recovery hint line appears once
per PRUNED view. Turns with no invocations get an empty suffix (`""`) in
both tiers — so text-only histories render **byte-identically** to
FEAT-524 in every tier.

### New Public Interfaces

```python
# parrot/memory/__init__.py (additions)
from .compaction import (
    CompactionCommit, CompactionResult, ContextBudget, Limit, OmissionStore,
    TokenCount, TokenCounter, ToolInvocation, ToolStatus, TurnState, TurnView,
    compact_history,
)

# Bot construction
Agent(..., context_budget=ContextBudget(window=200_000, verbatim_tokens=20_000))
Agent(..., context_budget=False)                      # kill switch (or PARROT_COMPACTION_DISABLED=1)
Chatbot(..., max_context_turns=12)                    # ceiling override only; also from the DB record

# Memory construction
RedisConversation(redis_url, key_prefix="conversation", use_hash_storage=True,
                  token_counter=None, omission_store=None, normalize=True, omission_ttl=None)
FileConversationMemory(base_path, token_counter=None, omission_store=None, normalize=True)
InMemoryConversation(token_counter=None, omission_store=None, normalize=True)

# LLM-facing tool (registered automatically; not user-constructed)
read_omitted_content(content_id: str | None = None, turn_id: str | None = None) -> str
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2. Paths are relative to
> `packages/ai-parrot/src/parrot/` unless they start with `packages/` or `docs/`.

### Module 1: Compaction data models + `ConversationTurn` schema v2
- **Path**: `memory/compaction/__init__.py`, `memory/compaction/models.py`,
  `memory/abstract.py` (`ConversationTurn`)
- **Responsibility**: `ToolStatus`, `TurnState`, `ToolInvocation`,
  `TokenCount`, `Limit`, `ContextBudget` (+ validation), `CompactionState`,
  `Omission`, `TurnView`, `CompactionResult`, `CompactionCommit` exactly as
  in §2. Add the six new `ConversationTurn` fields with defaults; extend
  `to_dict`/`from_dict` (legacy dicts → defaults); extend
  `from_ai_message` to fill `tool_invocations` (incl. `wm_key` from a
  `_tee` block) and the new `error` kwarg. `tools_used` untouched.
- **Depends on**: FEAT-524 M2 (`chatbot_id`, `from_ai_message`).

### Module 2: Stage 0 normalization
- **Path**: `memory/compaction/normalize.py`
- **Responsibility**: `NORM_VERSION = "1"` and the five rules: (1) NFC;
  (2) strip ANSI escape sequences and C0 controls except `\n`/`\t`; (3)
  strip trailing whitespace per line, collapse ≥3 blank lines to 2; (4)
  canonical `orjson` (`OPT_SORT_KEYS`) for strings that parse as a JSON
  object/array and for `ToolInvocation.input`; (5) traceback condensation
  for `ToolInvocation.error` and `turn.error` (first line + last
  `keep_frames` frames + exception line). Pure, stdlib + `orjson` only,
  style of `security/groundedness/normalize.py`. `normalize_turn` returns a
  new turn and stamps `norm_version`. Idempotence is a property test.
- **Depends on**: Module 1.

### Module 3: Stage 0.5 token counting
- **Path**: `memory/compaction/tokens.py`
- **Responsibility**: `TokenCounter` protocol, `TiktokenCounter("o200k_base")`
  with a lazy module-level encoding cache (precedent
  `knowledge/wiki/store.py:187-202`), `HeuristicCounter`,
  `get_default_counter()` (warn once on fallback), `count_turn()`
  (`context_used` excluded), `needs_recount()`.
- **Depends on**: Module 1.

### Module 4: Omission store
- **Path**: `memory/compaction/omission.py`
- **Responsibility**: `content_id()`, `OmissionStore` ABC with `put` /
  `put_many` / `get` / `list_by_turn` / `clear`, `ttl`, `EXPIRED_MESSAGE`;
  `InMemoryOmissionStore`, `RedisOmissionStore` (accepts an existing Redis
  client; keys `{prefix}_omitted:{key}` hash `content_id → content` and
  `{prefix}_omitted_turns:{key}` hash `turn_id → JSON list of ids`; `expire`
  only when `ttl` is set), `FileOmissionStore`. `put` is idempotent
  (content-addressed). Cross-session ids are "unknown" by construction.
- **Depends on**: Module 1.

### Module 5: `ConversationMemory` template method + backend rename
- **Path**: `memory/abstract.py` (`ConversationMemory`), `memory/mem.py`,
  `memory/redis.py`, `memory/file.py`
- **Responsibility**: constructor options (`token_counter`, `omission_store`,
  `normalize`, `oversize_tool_tokens`); concrete `add_turn(...,
  compaction=)` implementing steps 1–6 of §2 (normalize → recount if needed
  → write-time offload with preview → `schema_version=2` → `apply_commit`
  → `_store_turn`); abstract `_store_turn(..., compaction_state=)`;
  `report_usage()`; `omission_key()`. Rename the three `add_turn` bodies
  (`mem.py:65`, `redis.py:193`, `file.py:83`) to `_store_turn` and make each
  persist `compaction_state` into the history's `metadata["compaction"]` in
  the **same** write (Redis: single `hset` with `turns`, `updated_at`,
  `chatbot_id`, `metadata`; File: one rewrite; InMemory: one assignment).
  Each backend constructs its default `OmissionStore` (Redis shares
  `self.redis`; File uses `base_path`; InMemory a dict) and cascades
  `clear_history`/`delete_history` to `omission_store.clear()`. Legacy turns
  without `token_count` are counted lazily by `compact_history` and stamped
  on their next write.
- **Depends on**: Modules 1–4; FEAT-524 (`super().__init__()` already added
  to Redis/File by FEAT-524 — do not redo, verify).

### Module 6: Budget resolution
- **Path**: `memory/compaction/budget.py`
- **Responsibility**: `MODEL_WINDOWS` (new, prefix-matched), `FALLBACK_WINDOW`,
  `resolve_window()`, `build_default_budget()`, `compaction_disabled_by_env()`,
  `EWMA_ALPHA`, clamp bounds, pure `apply_usage()` / `apply_commit()`
  (boundary never regresses; degenerate usage ignored).
- **Depends on**: Module 1.

### Module 7: Prune policies
- **Path**: `memory/compaction/policies.py`
- **Responsibility**: `PrunePolicy` protocol, `PrunedInvocation`,
  `POLICY_VERSION`, built-ins (`DefaultPolicy`, `FileWritePolicy`,
  `FileReadPolicy`, `ShellPolicy`, `SubAgentPolicy`, `QueryPolicy`) with a
  small alias table mapping known tool names to policies, `register_policy`
  / `get_policy`, `prune_turn()` producing the PRUNED-view suffix (normative
  format in §2) and the `Omission`s. Errors never omitted. Already-offloaded
  outputs (`inv.omitted["output"]`) reuse the stored id and produce no new
  omission.
- **Depends on**: Modules 1, 3.

### Module 8: `compact_history` — the pure pre-pass
- **Path**: `memory/compaction/compact.py`
- **Responsibility**: `render_tool_activity()` (RAW suffix under `Limit`) and
  `compact_history()`: `available = window − reserve_output − reserve_fixed`;
  take the last `max_turns` turns (respecting `include_other_agents`), walk
  newest → oldest with `calibration × token_count.total`: (i) verbatim while
  cumulative ≤ `verbatim_tokens`, at least `min_verbatim_turns`; (ii) pruned
  (using each turn's pruned size, itself pure) while cumulative ≤
  `high_watermark × available`; (iii) dropped → `stage2_needed=True`. Turns
  at/before `boundary_turn_id` always PRUNED; new boundary = predecessor of
  the oldest verbatim turn (never regresses). Oversize rule: any invocation
  whose (preview or full) output exceeds `oversize_tool_tokens` is pruned in
  every turn except the newest, even in the verbatim tier. Views carry
  materialized `assistant_suffix`; omissions collected, not stored.
  Single huge newest turn renders anyway (never truncated). Deterministic
  and pure — property-tested with `hypothesis`.
- **Depends on**: Modules 1, 3, 6, 7.

### Module 9: `render_history` accepts views
- **Path**: `memory/render.py` (FEAT-524)
- **Responsibility**: widen the first parameter to
  `Optional[ConversationHistory] | Sequence[TurnView]`; for views, build
  the assistant content as `assistant_text + assistant_suffix` **before**
  the existing merge/alternation logic, ignore `max_turns`, honor
  `current_chatbot_id`/`include_other_agents`/`other_agent_label` exactly
  as for turns. Plain-history output byte-identical (regression test
  against FEAT-524 fixtures). Purity boundary: imports nothing from
  `parrot.memory.compaction` at runtime (`TYPE_CHECKING` import of
  `TurnView` only; runtime dispatch by duck-typing on `assistant_suffix`),
  computes no ids, touches no store, mutates no view.
- **Depends on**: Module 1; FEAT-524 M2.

### Module 10: `current_memory_key_id` ContextVar + binding order
- **Path**: `observability/context.py`; `bots/base.py` (four entry points),
  `bots/data.py`, `bots/voice.py` (FEAT-524 M6 shape)
- **Responsibility**: add the ContextVar, the `invocation_context(...,
  memory_key_id=)` kwarg, `__all__`. In every entry point move the
  `current_user_id`/`current_session_id` binding **after** the
  `session_id = session_id or uuid4()` / `user_id = user_id or "anonymous"`
  defaults (today binding precedes defaulting: `bots/base.py:206-208` vs
  `:283`, `:627-629` vs `:634-635`, `:989-991` vs `:1016-1017`,
  `:1621-1623` vs `:1631-1632`) and bind `current_memory_key_id =
  self.memory_key_id` in the same place; reset all tokens in the existing
  `finally`. Test: a call without ids stores omissions and resolves the
  tool under the *same* generated ids.
- **Depends on**: FEAT-524 M3/M6 (`memory_key_id`, entry-point rewrite).

### Module 11: `read_omitted_content` recovery tool
- **Path**: `memory/compaction/recover.py`, `tools/manager.py:608`
- **Responsibility**: `READ_OMITTED_CONTENT_SCHEMA`,
  `bind_read_omitted_content(memory)` returning the async function (fail
  closed on any `None` ContextVar; `content_id` → bytes or
  `EXPIRED_MESSAGE`; `turn_id` → all of that turn's omitted blocks). One-line
  change in `ToolManager.search_tools`'s scoring loop to skip a
  module-level `_INTERNAL_TOOL_NAMES = frozenset({"search_tools",
  "read_omitted_content"})`. No toolkit class; no client change; `clone()`
  untouched.
- **Depends on**: Modules 4, 10.

### Module 12: Bot integration
- **Path**: `bots/abstract.py`, `bots/base.py`, `bots/chatbot.py`,
  `bots/data.py`, `bots/voice.py`
- **Responsibility**: `context_budget` kwarg + property; `max_context_turns`
  default `None` at `abstract.py:590` and `chatbot.py:236/406` (explicit
  value = ceiling override; `:578/:626` serialize `None` safely);
  `render_context_history()`; every FEAT-524 render site switched to it
  (`history=` unchanged for the client; `set_conversation_context_info`
  fed from `len(rendered)`); prompt estimate =
  `counter.count(rendered) + counter.count(system_prompt) + counter.count(prompt)`
  using `memory.token_counter`; `save_conversation_turn(..., compaction=)`
  building `CompactionCommit` and passing it into `add_turn`;
  `ask_stream` partial-save on error passes no commit; `_register_recovery_tool()`
  once per bot when budgeted and memory is configured; Stage-2 event on
  first flip. Kill-switch path is FEAT-524's plain render, byte for byte.
- **Depends on**: Modules 1–11; FEAT-524 M3/M6.

### Module 13: Stage-2 lifecycle event, exports, docs
- **Path**: `core/events/lifecycle/events/memory.py` (new),
  `core/events/lifecycle/events/__init__.py`, `memory/__init__.py`,
  `docs/memory/per-turn-conversation-compaction.md` (new; sibling of
  FEAT-524's `docs/memory/conversation-history-ownership.md`),
  `.agent/CONTEXT.md` (memory entry)
- **Responsibility**: `Stage2CompactionNeededEvent`; public exports listed
  in §2; a guide covering the three tiers with the worked shape (50 chat
  turns → all verbatim; 10 database turns → latest verbatim, rest pruned),
  the kill switch, tuning keys, the two recovery tools, operator metadata,
  and the `_store_turn` contract for custom backends.
- **Depends on**: Modules 1, 12.

---

## 4. Test Specification

All new tests live under `packages/ai-parrot/tests/unit/memory/compaction/`
(the parent `tests/unit/memory/` is created by FEAT-524 M1). Property tests
use `hypothesis` (already a dev dependency). Redis-backed tests follow the
fixture strategy of `packages/ai-parrot/tests/test_chat_storage.py` and are
skipped when no Redis is reachable.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_turn_roundtrip_v2` | M1 | `to_dict`/`from_dict` round-trips every new field; `schema_version` preserved |
| `test_turn_legacy_dict_defaults` | M1 | a FEAT-524-shaped dict (no new keys) deserializes with defaults; `tools_used` intact |
| `test_from_ai_message_fills_invocations` | M1 | `AIMessage.tool_calls` → `ToolInvocation`s (status ERROR when `error` set; `elapsed_ms`; `wm_key` from `_tee`) |
| `test_context_budget_validation` | M1 | invalid combinations raise `ValueError`; `available` never negative |
| `test_normalize_rules_1_to_5` | M2 | fixtures per rule (NFC, ANSI/C0, whitespace, canonical JSON, traceback) |
| `test_normalize_idempotent` (property) | M2 | `normalize_turn(normalize_turn(t)) == normalize_turn(t)` for generated turns |
| `test_normalize_off_escape_hatch` | M2/M5 | `normalize=False` stores bytes unchanged; `norm_version` stays `None` |
| `test_counter_tiktoken_o200k` | M3 | name recorded; deterministic counts; lazy cache used once |
| `test_counter_heuristic_fallback` | M3 | `tiktoken` import failure (monkeypatched) → `"heuristic"`, single warning |
| `test_count_turn_excludes_context_used` | M3 | `context_used` does not change `total` |
| `test_needs_recount_on_mismatch` | M3 | `None` or tokenizer-name mismatch ⇒ recount |
| `test_content_id_stable` | M4 | `om_` + 16 hex; same content ⇒ same id; `put` idempotent |
| `test_omission_store_backends` (parametrized ×3) | M4 | put/get/list_by_turn/clear; unknown id ⇒ `None`; cross-session key ⇒ `None` |
| `test_omission_ttl_none_default` | M4 | Redis backend calls no `expire` when `ttl is None`; calls it when set |
| `test_add_turn_template_order` | M5 | normalize → count → offload → `_store_turn` called once with `compaction_state` |
| `test_write_time_offload_preview` | M5 | output > threshold ⇒ stored in omission store, preview left, `omitted["output"]`, `output_chars` set, `tools` recounted |
| `test_single_write_with_metadata` (×3 backends) | M5 | turn and `metadata["compaction"]` land in one write (Redis: one `hset` mapping containing both) |
| `test_clear_delete_cascade` (×3 backends) | M5 | `clear_history`/`delete_history` empty the omission store for that key |
| `test_chat_storage_tier_counted_not_compacted` | M5 | `RedisConversation(key_prefix="chat")` turns get `token_count`; nothing prunes |
| `test_resolve_window_prefix_and_fallback` | M6 | known prefixes; unknown ⇒ 32 000; `None` ⇒ 32 000 |
| `test_env_kill_switch` | M6 | `PARROT_COMPACTION_DISABLED=1` ⇒ `compaction_disabled_by_env()` |
| `test_apply_usage_ewma_clamped` | M6 | α=0.2; clamp [0.5, 2.0]; estimate ≤ 0 or `None` usage ignored |
| `test_apply_commit_boundary_monotonic` | M6 | boundary never moves to an older turn |
| `test_policy_registry_and_default` | M7 | exact name → policy; unknown ⇒ `DefaultPolicy`; `register_policy` overrides |
| `test_policies_keep_errors` | M7 | every built-in keeps `error` verbatim; notices carry `tool`, `chars`, `id`, optional `wm` |
| `test_prune_turn_reuses_offloaded_id` | M7 | already-offloaded output yields the stored id and no new `Omission` |
| `test_three_tier_walk_chatty` | M8 | 50 × ~150-token turns ⇒ all RAW; no omissions; `stage2_needed=False` |
| `test_three_tier_walk_database` | M8 | 10 × ~8k-token turns ⇒ newest RAW, rest PRUNED; sizes ≤ watermark |
| `test_min_verbatim_turns_guard` | M8 | one huge latest turn stays RAW; still ≥ `min_verbatim_turns` RAW |
| `test_oversize_rule_inside_verbatim_tier` | M8 | oversize output pruned in every turn but the newest |
| `test_persisted_boundary_forces_pruned` | M8 | turns at/before boundary PRUNED even if the budget would allow RAW |
| `test_dropped_sets_stage2` | M8 | overflow beyond watermark ⇒ `dropped_turn_ids`, `stage2_needed=True`, no truncation |
| `test_compact_is_pure_and_deterministic` (property) | M8 | same inputs ⇒ equal `CompactionResult`; input history unchanged |
| `test_legacy_turn_counted_lazily` | M8 | turn without `token_count` is counted with the passed counter |
| `test_render_views_appends_suffix` | M9 | suffix appended before merge; alternation guarantees hold |
| `test_render_plain_history_byte_identical` | M9 | FEAT-524 fixtures render identically through the widened signature |
| `test_render_text_only_views_identical_to_plain` | M9 | views with empty suffix ⇒ same bytes as plain render |
| `test_render_imports_no_compaction` | M9 | `parrot.memory.render` has no runtime import of `parrot.memory.compaction` |
| `test_contextvar_and_invocation_context` | M10 | new ContextVar restored on exit; kwarg works |
| `test_bind_after_defaulting` (×4 entry points) | M10 | call without ids ⇒ ContextVars hold the generated ids |
| `test_read_omitted_content_fail_closed` | M11 | any `None` ContextVar ⇒ fixed unavailable message, no store access |
| `test_read_omitted_content_by_id_and_turn` | M11 | bytes for a known id; concatenated blocks for a `turn_id`; `EXPIRED_MESSAGE` for unknown |
| `test_recovery_tool_registered_and_hidden` | M11/M12 | present in `get_tool_schemas()`; absent from `search_tools()` results; survives `clone()` |
| `test_kill_switch_byte_equality` | M12 | `context_budget=False` and env var ⇒ `HistoryMessage` list equals FEAT-524 plain render |
| `test_default_budget_from_model` | M12 | known model ⇒ `MODEL_WINDOWS`; unknown ⇒ 32k logged once |
| `test_max_context_turns_ceiling_override` | M12 | `Chatbot` DB value 12 ⇒ `budget.max_turns == 12`; absent ⇒ 30 |
| `test_calibration_pairing_in_save_turn` | M12 | commit + `usage.input_tokens` ⇒ `metadata.compaction.calibration` updated in the turn's write |
| `test_flush_failure_falls_back_to_plain` | M12 | `put_many` raising ⇒ plain render, warning, boundary unchanged |
| `test_stage2_event_emitted_once` | M12/M13 | `Stage2CompactionNeededEvent` on first flip only |
| `test_ask_stream_partial_save_no_commit` | M12 | error mid-stream ⇒ turn saved, `compaction=None` |

### Integration Tests
| Test | Description |
|---|---|
| `test_round_trip_database_agent_session` | 12 rounds with a stub client returning 8k-token tool results: after round 3 older datasets are notices, `read_omitted_content` returns the exact original bytes, prompt size stays under `high_watermark × available`, `metadata.compaction` advances monotonically |
| `test_round_trip_chat_session_unchanged` | 40 text-only rounds render byte-identically with and without the budget |
| `test_redis_end_to_end` (skip without Redis) | Redis memory + Redis omission store: single `hset` per turn, omission keys under the session, cascade on `delete_history` |
| `test_full_suite_green` | `timeout -s KILL 600 pytest tests/unit -q` and `pytest packages/ai-parrot/tests -q` pass (unit suite may hang after summary — always wrap in `timeout`, see FEAT-524 §7) |

### Test Data / Fixtures
```python
@pytest.fixture
def counter() -> TokenCounter:
    return HeuristicCounter()          # deterministic, no network, no tiktoken download in CI

@pytest.fixture
def budget() -> ContextBudget:
    return ContextBudget(window=32_000)  # defaults: available = 19_712, verbatim 15_000, max_turns 30

def make_turn(i: int, *, tokens: int = 150, tool_output_chars: int = 0, chatbot_id="bot") -> ConversationTurn:
    ...  # deterministic text of the requested size; optional one ToolInvocation with a big output

@pytest.fixture
def chatty_history() -> ConversationHistory: ...     # 50 × make_turn(tokens=150)
@pytest.fixture
def database_history() -> ConversationHistory: ...   # 10 × make_turn(tokens=8_000, tool_output_chars=30_000)

@pytest.fixture
def stub_client():  # records history=/system_prompt received; returns AIMessage with usage + tool_calls
    ...

# hypothesis strategies: st_text (unicode incl. combining marks + ANSI), st_invocation, st_turn, st_history
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass: `timeout -s KILL 600 pytest tests/unit -q` and `pytest packages/ai-parrot/tests -q`.
- [ ] **C1** `compact_history`, `prune_turn`, `normalize_turn`, `count_turn`, `apply_usage`, `apply_commit` are pure and synchronous; the `hypothesis` determinism/idempotence properties pass; no LLM call exists in `parrot/memory/compaction/`.
- [ ] **C2** No backend ever persists a PRUNED form; the only persisted compaction state is `history.metadata["compaction"]` (tokenizer, calibration, samples, boundary_turn_id, stage2_needed, updated_at). Outputs above `oversize_tool_tokens` are offloaded at write time with a preview + `omitted["output"]` and are recoverable byte for byte.
- [ ] **C3** A bot with no `context_budget` argument compacts by default with `max_turns=30`, `verbatim_tokens=15_000`, `min_verbatim_turns=2`, `oversize_tool_tokens=2_000`, window from `MODEL_WINDOWS` or `32_000`. `context_budget=False` and `PARROT_COMPACTION_DISABLED=1` each produce a `HistoryMessage` list byte-equal to FEAT-524's plain `render_history`.
- [ ] **C4** `ConversationMemory.add_turn` is concrete and every in-repo backend implements `_store_turn`; every written turn (including the `ChatStorage` `key_prefix="chat"` tier and voice transcripts) carries `token_count` with the tokenizer name and `norm_version`; `normalize=False` disables Stage 0 only.
- [ ] **C5** FEAT-524-shaped turn dicts deserialize unchanged; `tools_used` remains a dataclass field used by `from_dict` and `from_ai_message`.
- [ ] **C6** `OmissionStore` (InMemory/Redis/File) is owned by the memory backend, content-addressed (`om_` + blake2b-8), idempotent on `put`, indexed by `turn_id`, and cleared by `clear_history`/`delete_history`; `read_omitted_content` returns the exact bytes for a known id and `EXPIRED_MESSAGE` for an unknown or foreign one.
- [ ] **C7** No built-in policy and no tier omits `ToolInvocation.error` or `turn.error`; both survive Stage 0 rule 5 in condensed form.
- [ ] **C8** `HistoryMessage.role` is still `Literal["user", "assistant"]`; tool activity and notices appear only inside the assistant content as the normative `<tool-activity>` block.
- [ ] **C9** `render_history` accepts `Sequence[TurnView]`; `parrot.memory.render` has no runtime import of `parrot.memory.compaction`, computes no ids, touches no store, mutates no view; plain-history output is byte-identical to FEAT-524.
- [ ] **C10** The three-tier walk and the oversize rule behave as specified on the chatty and database fixtures; `AbstractBot` and `Chatbot` share one ceiling default (30) and an explicit `max_context_turns` (kwarg or DB) overrides it only.
- [ ] **C11** `save_conversation_turn(..., compaction=)` is the only place the prompt estimate meets `usage.input_tokens`; the EWMA (α=0.2, clamp [0.5, 2.0]) is updated by the memory inside the same write as the turn; no client file is modified (verified by `git diff --stat` on `parrot/clients/`).
- [ ] **C12** `current_memory_key_id` exists in `parrot.observability.context`; every entry point binds the three ContextVars after defaulting ids; `read_omitted_content` fails closed on any `None` component.
- [ ] **C13** A turn that once rendered PRUNED never renders RAW again for that history (persisted boundary; test `test_persisted_boundary_forces_pruned`), except for the documented oversize-rule exception.
- [ ] **C14** The worktree for this feature was created after FEAT-524 merged to `dev`, and every FEAT-524 entry in §6 was re-verified with line numbers on the merged code before `/sdd-task` ran (recorded in the task index's completion notes).
- [ ] **C15** `pyproject.toml` dependencies unchanged.
- [ ] `read_omitted_content` is registered through `ToolManager.register_tool(function=…)`, appears in `get_tool_schemas()`, is absent from `search_tools()` results, and survives `ToolManager.clone()`; no `AbstractToolkit`/`AbstractTool` subclass was added for it.
- [ ] `Stage2CompactionNeededEvent` is emitted exactly once per session on the first `False → True` flip of `stage2_needed`.
- [ ] Omission-store flush failure falls back to the plain render for that call with a warning and does not advance the boundary.
- [ ] Docs: `docs/memory/per-turn-conversation-compaction.md` written; `.agent/CONTEXT.md` memory entry updated; `memory/__init__.py` exports the public names in §2.
- [ ] No breaking changes to any public API other than the documented internal `ConversationMemory._store_turn` hard cut.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

> **Two baselines.** Paths are relative to `packages/ai-parrot/src/parrot/`.
> - **dev @ `a824f6535`** (verified 2026-09-04 by reading the files; the
>   later `2175ccdc0 navrules` and `7f32f2620` ledger commits touch no
>   `parrot/` file). These references are current **today**.
> - **FEAT-524 contract** — taken from the approved
>   `sdd/specs/conversation-history-ownership.spec.md` §2 "Data Models" /
>   "New Public Interfaces". **The FEAT-524 worktree named in the brainstorm
>   (`cdd3cee20`) is not reachable from this clone — it is being built on a
>   remote machine — so none of these could be verified in code here.**
>   Every entry marked *(FEAT-524 — unverified in code)* MUST be re-verified
>   with line numbers on `dev` after the merge, before `/sdd-task` (C14).
>   Where FEAT-524 changes a dev line cited below (e.g. `bots/base.py`
>   entry points, `save_conversation_turn`), the dev line is the *current*
>   location, not the final one.

### Verified Imports
```python
# dev — verified
from parrot.memory import ConversationHistory, ConversationMemory, ConversationTurn   # memory/__init__.py:3
from parrot.memory import InMemoryConversation, RedisConversation, FileConversationMemory  # memory/__init__.py:10-12
from parrot.memory.abstract import ConversationTurn, ConversationHistory, ConversationMemory  # memory/abstract.py:11, 51, 135
from parrot.models.basic import ToolCall, CompletionUsage                    # models/basic.py:23, 48
from parrot.models.responses import AIMessage                                # models/responses.py:72
from parrot.tools.manager import ToolManager                                 # tools/manager.py (register_tool :714)
from parrot.observability.context import (current_agent_name, current_user_id,
                                          current_session_id, invocation_context)   # context.py:56, 58, 60, 91
from parrot.core.events.lifecycle.events import MessageAddedEvent           # events/__init__.py:39
from navigator_eventbus.lifecycle.base import LifecycleEvent                # events/message.py:8 (external package)
from parrot.tools.compression.tee import attach_tee_pointer, CompressionTee # tee.py:161, 26
from datamodel.parsers.json import JSONContent                               # memory/abstract.py:6
import tiktoken   # 0.9.0 installed; pyproject.toml:61 ("tiktoken>=0.9.0"), pinned :529; o200k_base loads (verified)
import orjson     # 3.12.0 installed; pyproject.toml:164 ("orjson>=3.9")
import hypothesis # 6.165.10 installed; pyproject.toml:702 (dev extra, "hypothesis>=6.100")

# FEAT-524 — unverified in code (spec §2 "New Public Interfaces")
from parrot.memory import HistoryMessage, render_history                    # memory/__init__.py (FEAT-524 M2)
from parrot.memory.render import HistoryMessage, render_history             # memory/render.py (new in FEAT-524)
```

### Existing Class Signatures
```python
# ── dev @ a824f6535 — verified ────────────────────────────────────────────────

# memory/abstract.py
@dataclass
class ConversationTurn:                                                     # line 10-11
    turn_id: str; user_id: str; user_message: str; assistant_response: str  # 13-16
    context_used: Optional[str] = None                                      # 17
    tools_used: List[str] = field(default_factory=list)                     # 18
    timestamp: datetime = field(default_factory=datetime.now)               # 19
    metadata: Dict[str, Any] = field(default_factory=dict)                  # 20
    def to_dict(self) -> Dict[str, Any]                                     # 22 (keys: turn_id,user_id,user_message,
                                                                            #     assistant_response,context_used,tools_used,timestamp,metadata)
    @classmethod def from_dict(cls, data) -> 'ConversationTurn'             # 36 (tools_used=data.get('tools_used', []))

@dataclass
class ConversationHistory:                                                  # 50-51
    session_id: str; user_id: str                                           # 53-54
    chatbot_id: Optional[str] = None                                        # 55
    turns: List[ConversationTurn] = field(default_factory=list)             # 56
    created_at / updated_at: datetime                                       # 57-58
    metadata: Dict[str, Any] = field(default_factory=dict)                  # 59  ← home of metadata["compaction"]
    def add_turn(self, turn) -> None                                        # 61
    def get_recent_turns(self, count=5)                                     # 66
    def get_messages_for_api(self, model='claude')                          # 70  ← REMOVED by FEAT-524 M2
    def clear_turns(self) -> None                                           # 100
    def to_dict / from_dict                                                 # 105 / 118

class ConversationMemory(ABC):                                              # 135
    def __init__(self, debug: bool = False)                                 # 138  (self.logger, self._json = JSONContent(), self.debug)
    @abstractmethod async def create_history(self, user_id, session_id, metadata=None, chatbot_id=None)   # 146
    @abstractmethod async def get_history(self, user_id, session_id, chatbot_id=None)                     # 157
    @abstractmethod async def update_history(self, history) -> None                                       # 167
    @abstractmethod async def add_turn(self, user_id, session_id, turn, chatbot_id=None) -> None          # 172  ← becomes concrete
    @abstractmethod async def clear_history(self, user_id, session_id, chatbot_id=None) -> None           # 183
    @abstractmethod async def list_sessions(self, user_id, chatbot_id=None) -> List[str]                  # 193
    @abstractmethod async def delete_history(self, user_id, session_id, chatbot_id=None) -> bool          # 202

# memory/mem.py
class InMemoryConversation(ConversationMemory):                             # 5
    def __init__(self)                                                      # 8   (no super().__init__() on dev)
    def _get_chatbot_key(self, chatbot_id) -> str                           # 12  ("_default" when None)
    async def add_turn(self, user_id, session_id, turn, chatbot_id=None)    # 65-75  → body becomes _store_turn

# memory/file.py
class FileConversationMemory(ConversationMemory):                           # 9
    def __init__(self, base_path: str = "./conversations")                  # 12-15 (no super().__init__() on dev; FEAT-524 adds it)
    def _get_file_path(...)                                                 # 17
    async def add_turn(...)                                                 # 83-94  → body becomes _store_turn (get_history → add → update_history)

# memory/redis.py
class RedisConversation(ConversationMemory):                                # 10
    def __init__(self, redis_url=None, key_prefix="conversation", use_hash_storage=True)   # 13-28 (no super().__init__() on dev; FEAT-524 adds it)
    self.redis = Redis.from_url(..., decode_responses=True)                 # 22-28
    def _get_key(self, user_id, session_id, chatbot_id=None) -> str         # 31-42  "{prefix}[:{chatbot_id}]:{user}:{session}"
    def _get_user_sessions_key(...)                                         # 44
    def _serialize_data / _deserialize_data                                 # 56 / 66
    async def add_turn(...)                                                 # 193-228  hash mode: hget 'turns' → append to_dict() →
                                                                            #   hset mapping {'turns','updated_at'[, 'chatbot_id']}  (:222)
    async def clear_history(...)                                            # 230-252  resets 'turns' only
    async def delete_history(...) -> bool                                   # 266-279  delete key + srem sessions set
    # NO expire on history keys anywhere; :490 is a commented-out expire on an index key

# models/basic.py
class ToolCall(BaseModel):                                                  # 23
    id: str; name: str; arguments: Dict[str, Any]                           # 24-27
    result: Optional[Any] = None; error: Optional[str] = None               # 28-29
    execution_time: Optional[float] = None                                  # 30  (seconds)
class CompletionUsage(BaseModel):                                           # 48
    prompt_tokens: int  (alias input_tokens)                                # 76
    completion_tokens: int  (alias output_tokens)                           # 79
    @property input_tokens -> int                                           # 104
    @property output_tokens -> int                                          # 110

# models/responses.py
class AIMessage(BaseModel):                                                 # 72
    usage: CompletionUsage                                                  # 118
    tool_calls: List[ToolCall]                                              # 139
    turn_id: Optional[str]                                                  # 163
    def to_text(self) -> str                                                # 267
    def set_conversation_context_info(...)                                  # 361

# observability/context.py
__all__ = [...]                                                             # 45-54  (add "current_memory_key_id")
current_agent_name: ContextVar[Optional[str]]                               # 56
current_user_id: ContextVar[Optional[str]]                                  # 58
current_session_id: ContextVar[Optional[str]]                               # 60
@contextmanager def agent_identity(name)                                    # 63
@contextmanager def invocation_context(agent_name, user_id=None, session_id=None)   # 91  (token set/reset, LIFO)

# core/events/lifecycle/events/message.py
@dataclass(frozen=True)
class MessageAddedEvent(LifecycleEvent):                                    # 11-12  fields: agent_name, role, content_length, has_tool_calls
# events/__init__.py re-exports every concrete event and lists it in __all__ (:39, :51-…)

# bots/abstract.py
self.chatbot_id: uuid.UUID = kwargs.get('chatbot_id', ...)                  # 353  (random uuid default — FEAT-524 adds memory_key_id)
self.tool_manager: ToolManager = ToolManager(...)                           # 386
self._llm_model = _explicit_llm_model or self.default_model                 # 506  (model name source for MODEL_WINDOWS)
self.max_context_turns: int = kwargs.get('max_context_turns', 50)           # 590  → default None (ceiling override only)
def _create_llm_client(...)                                                 # 1028
def get_client(self) -> AbstractClient                                      # 1226
async def execute_llm_call(self, client, method="ask", **llm_kwargs)        # 1239
def configure_conversation_memory(self) -> None                             # 1263
async def get_conversation_history(...)                                     # 1798
async def create_conversation_history(...)                                  # 1816
async def save_conversation_turn(self, user_id, session_id, turn, chatbot_id=None) -> None   # 1836-1871 (dev shape; FEAT-524 removes chatbot_id)
    await self.conversation_memory.add_turn(user_id, session_id, turn, chatbot_id=chatbot_key)   # 1849
    await self.events.emit(MessageAddedEvent(trace_context=..., agent_name=self.name, role="turn", ...))   # 1863  ← emission pattern to copy
async def clear_conversation_history(...) / delete_conversation_history(...)   # 1873 / 1897

# bots/base.py (dev — FEAT-524 M6 rewrites these four entry points; re-verify)
async def conversation(...)   # 156   binds ContextVars :206-208   defaults user_id :283
async def invoke(...)         # 600   binds :627-629                defaults :634-635
async def ask(...)            # 932   binds :989-991                defaults :1016-1017
async def ask_stream(...)     # 1597  binds :1621-1623              defaults :1631-1632
# hand-rolled memory.add_turn writes at :539, :757, :1349, :1853 (FEAT-524 routes them through save_conversation_turn)

# bots/chatbot.py
self.max_context_turns = getattr(self, 'max_context_turns', 5)              # 236
self.max_context_turns = self._from_db(bot, 'max_context_turns', default=5) # 406
'max_context_turns': getattr(self, 'max_context_turns', 5)                  # 578, 626 (serialization)

# bots/data.py:2102, bots/voice.py:642, :683 — add_turn writes (FEAT-524 M6 routes them)

# tools/manager.py
self.register_tool(name="search_tools", description=..., input_schema={...}, function=self.search_tools)   # 349-370 (template)
def search_tools(self, query: str, limit: int = 15) -> str                  # 620
    if name == "search_tools": continue                                     # 608  ← extend to a frozenset incl. read_omitted_content
def register_tool(self, tool=None, name: str = None, description: str = None,
                  input_schema: Dict[str, Any] = None, function: Callable = None) -> None   # 714-720
def get_tool_schemas(self, provider_format=ToolFormat.GENERIC) -> List[Dict[str, Any]]      # 1152
def get_tool(self, tool_name) / list_tools(self) / remove_tool(self, tool_name)             # 1231 / 1251 / 1286
async def execute_tool(...)                                                 # 1504
def clone(...): if tool_name == "search_tools" and not include_search_tool: continue        # 2109 (NOT changed)
def add_result_hook(self, fn) -> None                                       # 2169

# tools/compression/tee.py
class CompressionTee                                                        # 26  (docstring :29-37: ToolManager has no turn concept)
    key = f"__tee__:{tool_name}:{self._turn_id()}:{self._next_counter(tool_name)}"   # 117
def attach_tee_pointer(payload, key, reason) -> Any                         # 161  dict → {**payload, "_tee": pointer} (:181); else {"result": payload, "_tee": pointer} (:182)
# tools/compression/stage.py:148  if os.getenv("PARROT_COMPRESSION_DISABLED") == "1":   ← kill-switch precedent
# tools/working_memory/tool.py  class WorkingMemoryToolkit :44; store_result :208; get_result :259

# storage/chat.py
HOT_TTL_HOURS = 48                                                          # 20  (declared, not applied to RedisConversation keys)
self._redis = RedisConversation(key_prefix="chat")                          # 54
async def save_turn(...)  →  await self._redis.add_turn(...)                # 106 → 209
async def _save_to_dynamodb(...)  →  put_turn(..., turn_id=…)               # 225 → 258   (per-turn cold-tier precedent)
query_turns :340 ; async def delete_turn :579 (dynamo :597)
async def get_context_for_agent(...)                                        # 618  ← :638 still calls history.get_messages_for_api() (FEAT-524's job)

# security/groundedness/normalize.py — pure, sync, stdlib-only normalizers (re, unicodedata, datetime)   # 1-14 (style precedent)
# knowledge/wiki/store.py:187-202 — lazy module-level tiktoken encoding cache with network caveat (precedent)
# cl100k_base sites (NOT migrated here): skills/parsers.py:29, knowledge/wiki/store.py:202, knowledge/pageindex/utils.py:53

# ── FEAT-524 contract — unverified in code (spec §2) ─────────────────────────
# memory/render.py (new; leaf module importing only .abstract)
@dataclass(frozen=True)
class HistoryMessage: role: Literal["user","assistant"]; content: str; chatbot_id: Optional[str]=None; turn_id: Optional[str]=None
def render_history(history: Optional[ConversationHistory], *, max_turns: Optional[int]=None,
                   current_chatbot_id: Optional[str]=None, include_other_agents: bool=True,
                   other_agent_label: str="[agent:{chatbot_id}]") -> list[HistoryMessage]
    # guarantees: strict alternation, starts user / ends assistant, same-role merge with "\n\n",
    # empty assistant_response → turn skipped, input never mutated; max_turns keeps the most recent N.

# memory/abstract.py
ConversationTurn.chatbot_id: Optional[str] = None
@classmethod ConversationTurn.from_ai_message(*, user_message, response, user_id, chatbot_id,
                                              context_used=None, turn_id=None, assistant_text=None)
    # tools_used=[tc.name …]; metadata={model, provider, usage (dict), finish_reason, response_time}
# ConversationHistory.get_messages_for_api REMOVED.
# RedisConversation / FileConversationMemory call super().__init__() (spec §7 / brainstorm review F7).
# get_history() lazy legacy re-key (M2b).

# bots/abstract.py
@property def memory_key_id(self) -> str            # explicit chatbot_id else self.name
async def save_conversation_turn(self, user_id, session_id, turn) -> None   # keys by memory_key_id; asserts turn.chatbot_id
# build_conversation_context / conversation_context kwarg / "## Conversation Context:" REMOVED.

# clients/base.py
async def ask(..., history: Optional[Sequence[HistoryMessage]] = None, ...)   # user_id/session_id REMOVED
def _format_history(self, history) -> List[Dict[str, Any]]
# conversation_memory kwarg and all *_conversation helpers REMOVED.

# tests: packages/ai-parrot/tests/unit/memory/test_history_ownership.py (M1) creates tests/unit/memory/
# docs: docs/memory/conversation-history-ownership.md (M8)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ConversationTurn.from_ai_message` (extended) | `AIMessage.tool_calls`, `ToolCall.{name,arguments,result,error,execution_time}` | attribute reads | `models/responses.py:139`, `models/basic.py:23-30` (dev); FEAT-524 constructor (unverified) |
| `ToolInvocation.wm_key` | FEAT-380 `_tee` block on dict results | `result["_tee"]["key"]` | `tools/compression/tee.py:161-182` (dev) |
| `ConversationMemory.add_turn` (concrete) | `_store_turn` in `mem.py`/`redis.py`/`file.py` | template method | `memory/mem.py:65`, `memory/redis.py:193`, `memory/file.py:83` (dev bodies to rename) |
| `RedisConversation._store_turn` | `self.redis.hset(key, mapping=…)` | one mapping incl. `metadata` | `memory/redis.py:222` (dev writes turns/updated_at/chatbot_id) |
| `RedisOmissionStore` | `RedisConversation.redis` | shared client | `memory/redis.py:22-28` |
| `apply_usage` | `turn.metadata["usage"]["input_tokens"]` | dict read (FEAT-524 metadata shape) / `CompletionUsage.input_tokens` | `models/basic.py:104` (dev); metadata shape FEAT-524 (unverified) |
| `compact_history` → `render_history(views)` | `memory/render.py` | widened first parameter | FEAT-524 `render_history` (unverified) |
| `AbstractBot.render_context_history` | every FEAT-524 render site in `bots/base.py`, `bots/data.py`, `bots/voice.py` | method call | FEAT-524 M6 (unverified; dev sites `base.py:539,757,1349,1853`, `data.py:2102`, `voice.py:642,683`) |
| `AbstractBot.save_conversation_turn(compaction=)` | `ConversationMemory.add_turn(compaction=)` | kwarg pass-through | `bots/abstract.py:1849` (dev call site) |
| `Stage2CompactionNeededEvent` | `self.events.emit(...)` | same shape as `MessageAddedEvent` | `bots/abstract.py:1863` (dev) |
| `read_omitted_content` | `ToolManager.register_tool(name=…, description=…, input_schema=…, function=…)` | bare function registration | `tools/manager.py:714-720`; precedent `:349-370` |
| `search_tools` exclusion | `ToolManager.search_tools` loop | frozenset membership | `tools/manager.py:608` |
| `current_memory_key_id` | `bots/base.py` entry points | `ContextVar.set/reset` next to user/session | `bots/base.py:206-208, 627-629, 989-991, 1621-1623` (dev; move after `:283`, `:634-635`, `:1016-1017`, `:1631-1632`) |
| `build_default_budget(self._llm_model)` | `AbstractBot._llm_model` | attribute read | `bots/abstract.py:506` |
| `compaction_disabled_by_env` | `os.getenv("PARROT_COMPACTION_DISABLED")` | mirrors FEAT-380 | `tools/compression/stage.py:148` |
| `ChatStorage` tier | `RedisConversation(key_prefix="chat").add_turn` | inherits template | `storage/chat.py:54, 209` |

### Does NOT Exist (Anti-Hallucination)
- ~~`MODEL_WINDOWS`~~ — **does not exist anywhere in the repo** (grep over `*.py`/`*.md` outside `sdd/proposals/`); the brainstorm refers to it as if present. It is **new** in `memory/compaction/budget.py`. There is also no per-model context-window table in `parrot/clients/*` to reuse (only unrelated constants: `clients/claude.py:88` comment, `clients/google/client.py:1328 MAX_TOOL_RESULT_CHARS`).
- ~~`packages/ai-parrot/tests/unit/memory/`~~ — does not exist on dev; FEAT-524 M1 creates it. Existing memory-touching tests: `tests/test_chat_storage.py`, `tests/memory/unified/test_imports.py`.
- ~~`ConversationHistory.get_messages_for_api`~~ — removed by FEAT-524 M2; do not extend it. The extension point is `render_history`.
- ~~`AbstractClient.conversation_memory`~~, ~~`_prepare_conversation_context`~~, ~~`_update_conversation_memory`~~, ~~`user_id`/`session_id` on `ask()`~~ — removed by FEAT-524 M4/M5. Clients must not be touched by this feature.
- ~~`ConversationMemory.report_usage`~~, ~~`_store_turn`~~, ~~`omission_store` / `token_counter` / `omission_key`~~ — new here.
- ~~`ConversationTurn.tool_invocations` / `.error` / `.token_count` / `.state` / `.schema_version` / `.norm_version`~~ — new here (FEAT-524 adds only `chatbot_id`).
- ~~`TurnState`, `ToolInvocation`, `ToolStatus`, `TokenCount`, `TokenCounter`, `ContextBudget`, `Limit`, `PrunePolicy`, `CompactionResult`, `CompactionCommit`, `CompactionState`, `TurnView`, `Omission`, `OmissionStore` and backends~~ — none exist under `parrot/`.
- ~~`parrot.memory.compaction`~~ package — does not exist.
- ~~`compact_history()`~~, ~~`prune_turn()`~~, ~~`normalize_turn()`~~, ~~`count_turn()`~~ — do not exist; `render_history` has no `budget` parameter.
- ~~`AbstractBot.context_budget`~~, ~~`render_context_history`~~, ~~`_register_recovery_tool`~~, ~~`save_conversation_turn(..., compaction=)`~~ — new here; dev signature is `(user_id, session_id, turn, chatbot_id=None)`, FEAT-524's is `(user_id, session_id, turn)`.
- ~~`AbstractBot.memory_key_id`~~ — does **not** exist on dev (`grep` confirmed); it is FEAT-524 M3. Do not implement it here; depend on it.
- ~~`current_memory_key_id`~~ ContextVar — does not exist; `context.py` defines exactly `current_agent_name`, `current_user_id`, `current_session_id` plus `current_run_id`/`current_seat` for usage attribution.
- ~~`Stage2CompactionNeededEvent`~~, ~~`core/events/lifecycle/events/memory.py`~~ — new here. Existing event files: `agent.py`, `client.py`, `flow.py`, `invoke.py`, `message.py`, `tool.py`.
- ~~TTL on Redis history keys~~ — none (`redis.py:490` is a commented-out `expire` on an *index* key). `omission_ttl` is independent, default `None`.
- ~~`ToolManager.turn_id` / turn boundaries in `ToolManager`~~ — absent (`tools/compression/tee.py:29-37`).
- ~~`read_omitted_content` tool~~ — does not exist; `wm_get_result` (FEAT-380 `WorkingMemoryToolkit.get_result`, `tools/working_memory/tool.py:259`) is a different tool over a process-local store.
- ~~`ReadOmittedContentToolkit`~~ / any `AbstractTool` subclass for recovery — never to be created (resolved: plain `register_tool(function=…)`).
- ~~A client-side "internal tool" channel outside `ToolManager`~~ — clients build the provider tools array only from `tool_manager.get_tool_schemas()` (`clients/base.py:1419`) and dispatch only via `AbstractClient._execute_tool` (`clients/base.py:1461`).
- ~~A `"tool"` role on `HistoryMessage`~~ — `role: Literal["user", "assistant"]` only (C8).
- ~~`ContextAssembler` using `tiktoken`~~ — it uses `len(text) // 4` (`memory/unified/context.py`); out of scope.
- ~~`PARROT_COMPACTION_DISABLED`~~ — does not exist yet; only `PARROT_COMPRESSION_DISABLED` (`tools/compression/stage.py:148`) does. Do not reuse the FEAT-380 variable — they are different features with different kill switches.
- ~~Pydantic models for turns~~ — `ConversationTurn`/`ConversationHistory` are stdlib dataclasses with hand-written `to_dict`/`from_dict`; new compaction models follow the same convention (see §2 Data Models note).
- ~~`ConversationMemory.__init__` being called by Redis/File on dev~~ — it is **not** (`redis.py:13-28`, `file.py:12-15`); FEAT-524 adds `super().__init__()`. The template method must not be merged before that lands.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Leaf-module rule.** `parrot.memory.render` imports only `.abstract` at
  runtime (FEAT-524 §7); `parrot.memory.compaction.*` imports
  `parrot.memory.abstract`, stdlib, `orjson`, `tiktoken` — never
  `parrot.tools`, `parrot.bots`, `parrot.clients`. The only crossing is
  `bots/abstract.py` importing from `parrot.memory` (already true on dev).
- **Pure functions first.** Everything except the two `await`s (omission
  flush, turn persist) is a pure function of its inputs. Follow the style of
  `security/groundedness/normalize.py` (module docstring stating purity,
  stdlib-only, compiled regexes at module level).
- **Template method.** `add_turn` is the FEAT-391-style "concrete public,
  abstract private" pattern; backends implement `_store_turn` only.
- **Meta-tool registration.** Copy the `search_tools` shape at
  `tools/manager.py:349-370` exactly: `register_tool(name=…, description=…,
  input_schema=…, function=…)`; the function is a closure over the memory,
  not a method on the bot.
- **Event emission.** Copy `bots/abstract.py:1863` (`await self.events.emit(
  Event(trace_context=…, agent_name=self.name, ..., source_type="agent",
  source_name=self.name))`) for `Stage2CompactionNeededEvent`.
- **ContextVars.** Token-based `set()`/`reset()` in `finally`, LIFO order,
  as in `observability/context.py:91-121`.
- **Lazy `tiktoken`.** Module-level cache guarded like
  `knowledge/wiki/store.py:187-202`; never download an encoding at import
  time; unit tests use `HeuristicCounter`.
- **Canonical JSON.** `orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)`;
  only strings that parse as a JSON object/array are rewritten (rule 4).
- **Redis writes.** Keep `use_hash_storage=True` semantics: one `hset` with
  a mapping; `metadata` serialized with the existing `_serialize_data`.
- **Google-style docstrings and strict type hints** on every new function
  and class; `self.logger` (never `print`).
- **Tests wrapped in `timeout`** (see FEAT-524 §7 "Test suite hang").

### Known Risks / Gotchas
- **FEAT-524 not merged.** This spec's §6 FEAT-524 entries are from the
  spec, not code. Mitigation: C14 — no `/sdd-task`, no worktree until the
  merge; re-verify every entry (line numbers *and* signatures) first.
  Nothing in `memory/abstract.py`'s template method may land before
  `super().__init__()` exists on Redis/File.
- **Binding-order hazard (review v2 F1, verified on dev).** Bots bind
  `current_user_id`/`current_session_id` *before* defaulting the ids
  (`bots/base.py:989-991` vs `:1016-1017`), so a call without ids would
  store omissions under the generated ids while the tool reads `None`.
  Mitigation: M10 binds after defaulting at every entry point; the tool
  fails closed on any `None` (never an un-segmented key).
- **Write ordering (review v2 F5).** Turn, boundary/EWMA and event must not
  be three writes. Mitigation: the commit travels into `add_turn` and
  `_store_turn` persists turn + `metadata.compaction` in one write;
  `MessageAddedEvent` fires after it returns. On failure nothing is
  persisted; the next round recomputes the boundary deterministically
  (never regresses).
- **Prompt-cache invalidation (C13).** Monotonic renders keep the provider
  cache stable except at the oversize-rule point, which invalidates once at
  that turn — the same cost the FEAT-380 tee already accepts. Do not "fix"
  this by re-rendering pruned turns verbatim.
- **Omission TTL vs no history TTL (review v2 F7).** An omission that
  expires before its history leaves a notice that can never resolve.
  Mitigation: default `omission_ttl=None`; the notice text always says "may
  have expired — re-run the tool".
- **Foreign turns (review v2 F6).** Omissions of turns from another agent
  (`include_other_agents=True`) are stored under the key of the history
  being rendered (current bot's `memory_key_id`); the producing agent's
  history is never written to. Their notices carry the `[agent:…]` label
  FEAT-524 adds.
- **FEAT-380 tee keys are not turn-keyed and process-local**
  (`tee.py:29-37`, `:117`). The `wm=` hint in a notice is best-effort; the
  omission store is the recovery path that survives a restart.
- **Legacy histories.** Turns without `token_count` are counted lazily at
  first compaction (never block rendering) and stamped on their next write;
  tokenizer mismatch ⇒ recount that turn, log once per history.
- **`tiktoken` offline.** `get_encoding` may hit the network on first use;
  fall back to `"heuristic"` with one warning; calibration still converges
  on provider counts.
- **Unknown model.** `resolve_window` falls back to `32_000`; log once per
  bot, not per call.
- **Single huge newest turn.** Renders anyway (`min_verbatim_turns`); if it
  alone exceeds `available`, `stage2_needed` is set; never truncated here.
- **All prunables exhausted, still above the watermark.** Render what fits,
  persist `stage2_needed=True`; no truncation introduced here.
- **`ask_stream` partial save on error** (FEAT-524 keeps it): goes through
  `save_conversation_turn` with `compaction=None` (no estimate to pair).
- **`ChatStorage` tier** (`key_prefix="chat"`): normalized and counted,
  never compacted; `storage/chat.py:638` still calls the removed
  `get_messages_for_api()` on dev — FEAT-524 must fix it, not this feature.
- **`Chatbot` DB default.** Changing `default=5` to `None` at
  `chatbot.py:406` changes behavior for agents whose DB record has no
  value (they get the 30-turn ceiling under a token budget instead of a
  5-turn verbatim replay). This is the intended G10 outcome; call it out in
  the docs.
- **`clone()` must keep the recovery tool.** `ToolManager.clone()` gates
  only `search_tools` (`manager.py:2109`); do not add
  `read_omitted_content` to that gate.
- **Two recovery tools for the LLM** (`wm_get_result`, `read_omitted_content`).
  Acceptable: each notice names the tool to call.
- **Render-time CPU.** Pruning work runs on each render once past the
  boundary. Bounded (boundary is monotonic) and cacheable in-process per
  `(turn_id, norm_version, POLICY_VERSION)` without persisting anything —
  optional optimization, not required for v1.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `tiktoken` | `>=0.9.0` (core, `pyproject.toml:61`; pinned `==0.9.0` at `:529`) | `o200k_base` BPE estimator; lazy cache; heuristic fallback |
| `orjson` | `>=3.9` (core, `pyproject.toml:164`; 3.12.0 installed) | canonical JSON (`OPT_SORT_KEYS`) for Stage 0 rule 4 and `ToolInvocation.input` |
| `hypothesis` | `>=6.100` (dev, `pyproject.toml:702`) | idempotence / determinism property tests |
| stdlib `unicodedata`, `re`, `hashlib.blake2b`, `contextvars`, `os` | — | NFC, ANSI/C0 stripping, content ids, session scoping, kill switch |
| `navigator_eventbus` | already required by FEAT-176 | `LifecycleEvent` base for the Stage-2 event |

No dependency is added or bumped (C15).

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.
> Resolved items are carried forward verbatim from the brainstorm and are
> reflected in the spec body (§1 Goals, §2 Overview/Data Models, §3, §5, §7).

- [x] Regular feature or hotfix, and base branch? — *Resolved in brainstorm*: feature on `dev`.
- [x] Relationship between the Stage 1 omission store and the FEAT-380 working-memory tee? — *Resolved in brainstorm*: separate `OmissionStore` ABC; coexist (execution-time vs age triggers, different stores).
- [x] Where do Stage 0/0.5 run after FEAT-524's single writer? — *Resolved in brainstorm (v2)*: memory layer — concrete `ConversationMemory.add_turn()` normalizes + counts, then awaits abstract `_store_turn()`; covers the bot writer, `ChatStorage`, voice transcripts.
- [x] How does compaction plug into FEAT-524's `render_history`? — *Resolved in brainstorm (v2)*: pure pre-pass `compact_history()` producing turn views + omissions; `render_history` accepts views and renders tool text; its FEAT-524 signature and plain-history output unchanged.
- [x] Where does tool-invocation / omission text go in a text-only, strictly alternating `HistoryMessage` list? — *Resolved in brainstorm (v2)*: appended to the assistant message content as a fenced block; no new role.
- [x] Where does the estimate/provider pairing happen now that clients are memory-less? — *Resolved in brainstorm (v2)*: inside `save_conversation_turn`, which calls `memory.report_usage()`; memory owns the EWMA. (Spec refinement per review v2 F5: the commit travels into `add_turn(compaction=)` so the EWMA lands in the turn's write; `report_usage` remains for standalone updates.)
- [x] Sequencing vs FEAT-524? — *Resolved in brainstorm (v2)*: brainstorm + spec now against the FEAT-524 contract; `/sdd-task` and the worktree only after FEAT-524 merges to `dev`, with Codebase Contract re-verified.
- [x] Turn cap vs token budget? — *Resolved in brainstorm (v2, superseded v3)*: first "budget replaces the cap"; **revised 2026-09-04**: tokens are the retention unit, turns the atomic unit — three-tier walk (verbatim ≤ `verbatim_tokens`, pruned ≤ high watermark, dropped) under a unified `max_turns=30` ceiling; `Chatbot.max_context_turns` stays a ceiling override (C10).
- [x] Defaults for the retention model? — *Resolved in brainstorm (v3)*: `max_turns=30`, `verbatim_tokens=15_000`, `min_verbatim_turns=2`, fallback `window=32_000` when the model is unknown; `oversize_tool_tokens=2_000` proposed by the assistant, accepted in principle (number to confirm in spec). **Confirmed in this spec: 2,000.**
- [x] Oversized tool results in recent turns? — *Resolved in brainstorm (v3)*: prune big datasets from every turn but the newest even inside the verbatim tier; recovery via `read_omitted_content` and, when present, the FEAT-380 working-memory `_tee` key.
- [x] Who owns the `OmissionStore`? — *Resolved in brainstorm (v2)*: the `ConversationMemory` backend (same connection; clear/delete cascade); bot reaches it via `memory.omission_store`.
- [x] How does `read_omitted_content` resolve its session key? — *Resolved in brainstorm (v2)*: new ContextVar `current_memory_key_id` set by bots alongside user/session; the tool function is bot-agnostic.
- [x] Does `read_omitted_content` need an `AbstractToolkit`? — *Resolved in brainstorm (2026-09-04, post-brainstorm review)*: **No.** It is an internal, LLM-only tool: one plain function registered with `ToolManager.register_tool(function=…)`, the `search_tools` meta-tool shape (`tools/manager.py:349-370`). It stays in the `ToolManager` (not attached to clients) because clients take schemas from `get_tool_schemas` and dispatch through `execute_tool`, which also keeps permissions, redaction, FEAT-380 compression and telemetry on the path and keeps clients memory-less per FEAT-524.
- [x] Opt-in or default-on? — *Resolved in brainstorm (v1 opt-in, revised v3 2026-09-04)*: **default-on**, size-aware retention *and* pruning into the omission store, with a `ContextBudget` always present (`MODEL_WINDOWS` or 32k fallback); escape hatch `context_budget=False` / `PARROT_COMPACTION_DISABLED=1` restores FEAT-524's plain render (C3).
- [x] `keep_turns` / text-only retention (review v2 F2). — *Resolved in brainstorm (v3)*: both closed by C10 — `keep_turns` is replaced by `verbatim_tokens` + `min_verbatim_turns`, and prose-only sessions are bounded by the verbatim window, the watermark and the `max_turns=30` ceiling.
- [x] Write-time offload of oversized outputs. — *Resolved in brainstorm (2026-09-04, v3)*: **yes, in v1.** `add_turn()` moves any `ToolInvocation.output` above `oversize_tool_tokens` into the omission store at write time, leaving a short preview in the turn plus `omitted["output"] = om_…`. Lossless, keeps Redis turn records small; recorded as a refinement of C2 ("raw" means *recoverable*, not *inline*). Precedent: the `ChatStorage` cold tier stores and recovers per turn by `(user, agent, session, turn_id)` (`storage/chat.py` `_save_to_dynamodb` → `put_turn(..., turn_id=…)`, `query_turns`, `delete_turn`).
- [x] Linking omissions to `turn_id`. — *Resolved in brainstorm (v3)*: **yes.** Secondary index `session_key → turn_id → [content_id]` (one Redis hash per session; dict/file equivalents) so an agent or operator can recover a whole turn's outputs by `turn_id` without knowing the hashes; `clear`/`delete` cascade covers it. FEAT-380 tee keys cannot serve this (not keyed by conversation `turn_id`, `tee.py:29-37`). `read_omitted_content` accepts either a `content_id` or a `turn_id`.
- [x] `context_used` accounting. — *Resolved in brainstorm (2026-09-04, accepted as proposed)*: excluded from `TokenCount.total` and the budget sum; omitted on prune for storage hygiene. (Spec reading: `render_history` never rendered `context_used`, so no tier renders it and no notice is emitted for it; `TurnView` carries no `context_used`.)
- [x] Stage 0 always-on vs gated. — *Resolved in brainstorm (2026-09-04, accepted as proposed)*: always-on for every writer (including the `ChatStorage` tier), memory-level `normalize=False` escape hatch.
- [x] `ChatStorage` tier. — *Resolved in brainstorm (2026-09-04, accepted as proposed)*: normalized + counted, never compacted in v1; a budgeted `ChatStorage.get_context_for_agent` is a follow-up. Its stale `get_messages_for_api` call (`storage/chat.py:638`) belongs to FEAT-524.
- [x] Tokenizer. — *Resolved in brainstorm (2026-09-04)*: **`o200k_base`** for the memory counter, name recorded per turn and in history metadata (identical counts to `cl100k_base` on English prose, Python and compact JSON; 23% fewer tokens on Spanish, 33% fewer on Japanese). Follow-up (separate feature): migrate the three `cl100k_base` sites.
- [x] `omission_ttl` default. — *Resolved in brainstorm (2026-09-04, accepted as proposed)*: `None` (no expiry) by default, matching the history key; configurable; notice text says "may have expired".
- [x] Token counting opt-in (review v2 F8)? — *Resolved in brainstorm (v3, implied by default-on retention)*: **always-on** for every memory instance (`tiktoken` else heuristic); the `ChatStorage` tier is counted too.
- [x] Tool-text format. — *Resolved in brainstorm (accepted in principle); exact schema: implementer (spec)*: appended `<tool-activity>` block, one line per invocation (name, status, elapsed, truncated input summary), omission notices inline, with a `Limit` for RAW turns. **Exact schema defined in §2 "Rendered text formats (normative)".**
- [x] Per-tool `PrunePolicy` declaration. — *Resolved in brainstorm (2026-09-04, accepted as proposed)*: v1 = registry keyed by tool name (built-ins + `register_policy()`); a `prune_policy` attribute on `AbstractTool` is a follow-up.
- [x] Stage 2 trigger surface. — *Resolved in brainstorm (2026-09-04, accepted as proposed)*: persist `stage2_needed` in `metadata.compaction` **and** emit a FEAT-176-style lifecycle event when it first flips (`Stage2CompactionNeededEvent`, §2).
- [x] `Chatbot` DB `max_context_turns` default when the record has no value. — *Derived in this spec from the C10 resolution*: `None` ⇒ `ContextBudget.max_turns` (30); only an explicit DB value overrides. (Flagged for the author's confirmation at spec review; changes behavior for records without a value.)
- [ ] `MODEL_WINDOWS` initial table contents (which model-name prefixes and window sizes ship in v1) — *Owner: implementer, decide during Module 6*; unknown names fall back to 32k, so an incomplete table is safe.
- [ ] Whether `clear_history`/`delete_history` cascade is implemented as template wrappers (`_clear_history`/`_delete_history` abstract) or as an explicit `omission_store.clear()` call in each backend — *Owner: implementer, decide during Module 5*; both satisfy C6 and the cascade tests.

---

## Worktree Strategy

- **Default isolation**: `per-spec` — one worktree
  `.claude/worktrees/feat-FEAT-525-per-turn-conversation-compaction`
  branched from `dev` **after FEAT-524 merges**, tasks sequential.
- **Parallelizable inside the worktree** (three clusters after Module 1
  lands):
  - Cluster 1 (memory core): M2 normalization ∥ M3 token counting ∥ M4
    omission store ∥ M6 budget → M5 template method (needs M2–M4, M6).
  - Cluster 2 (compaction + render): M7 policies → M8 `compact_history`;
    M9 `render_history` views (needs only M1) may run alongside.
  - Cluster 3 (recovery + scoping): M10 ContextVar/binding order ∥ M4 → M11
    recovery tool.
  - M12 bot integration is last and depends on all three; M13 closes.
- **Order**: M1 → {M2, M3, M4, M6, M9, M10} → {M5, M7} → {M8, M11} → M12 → M13.
- **Cross-feature dependencies**:
  - **FEAT-524 `conversation-history-ownership`** (approved, 11 tasks in
    progress on a remote machine): **hard prerequisite** — this feature edits
    `memory/abstract.py`, `memory/render.py`, `bots/abstract.py` and the four
    `bots/base.py` entry points that FEAT-524 M2/M3/M6 rewrite. No worktree
    before its merge (C14).
  - **FEAT-523 `pep-420-llm-clients`** (draft, waits for FEAT-524): moves
    client files; this feature touches **no** client file → independent
    either way.
  - **FEAT-380** (`tools/compression/`, done) and **FEAT-397** (client tool
    loops, done): consumed, not modified.
  - `observability/context.py` has no in-flight edits (the fireflies tasks
    TASK-2665..2669 cite `clients/base.py:1747` as a contract only).
- **Rationale**: nearly every task edits `memory/abstract.py` or its tests,
  and the bot integration must land as one commit after all three clusters;
  separate worktrees would conflict on the same dataclass and the same four
  entry points.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-04 | Jesus Lara | Initial draft from the accepted brainstorm (Option A, v3 decisions); Codebase Contract verified on dev `a824f6535`; FEAT-524 entries cited from its approved spec pending merge |
