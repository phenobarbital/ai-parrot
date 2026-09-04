---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Per-Turn Conversation Compaction — Deterministic Stages (0 / 0.5 / 1)

**Date**: 2026-09-04
**Author**: Jesus Lara
**Status**: accepted (all open questions resolved by the author, 2026-09-04)
**Recommended Option**: A

> Source: `sdd/proposals/per-turn-conversation-compactation.proposal.md`
> (design concept, 2026-09-03). **Re-thought on 2026-09-04 against FEAT-524**
> (`sdd/specs/conversation-history-ownership.spec.md`, approved, 11 tasks in
> progress in `.claude/worktrees/feat-FEAT-524-conversation-history-ownership`,
> 3 of 11 done at `cdd3cee20`). FEAT-524 is a **hard prerequisite**: it
> removes client-side memory, makes `AbstractBot.save_conversation_turn` the
> single writer, replaces `get_messages_for_api()` with the pure
> `render_history()`, and keys every history by `(memory_key_id, user,
> session)`. Every design point below is expressed against that contract.
> An earlier draft of this brainstorm (same day) targeted the pre-FEAT-524
> code and is superseded in full.

---

## Problem Statement

After FEAT-524, a stateful bot round works like this: the bot loads the
`ConversationHistory`, renders it with `render_history(max_turns=…)` into
alternating `HistoryMessage`s, hands them to a memory-less client, and
persists exactly one `ConversationTurn` built by
`ConversationTurn.from_ai_message()`. That fixes the double write and the
double injection. Three problems remain, and they are the ones the
compaction proposal exists for:

1. **Unbounded growth, lossy relief.** `render_history` replays every kept
   turn verbatim; the only bound is `max_turns` (`AbstractBot.max_context_turns`,
   default 50 at `bots/abstract.py:590`; `Chatbot` default 5). Dropping
   whole turns is lossy and blind to size: five tool-heavy turns can cost
   more than fifty chatty ones.
2. **No token awareness.** Nothing in `parrot.memory` knows what a turn
   costs. `ContextAssembler` (`memory/unified/context.py`) and FEAT-380 use
   `len(text) // 4`. "Does this history fit the window?" cannot be answered
   without re-tokenizing the transcript, so nobody answers it.
3. **Tool activity is invisible and failures are forgotten.**
   `ConversationTurn.tools_used` stores tool *names* only (dev
   `abstract.py:18`; FEAT-524 keeps the field). Inputs, outputs, errors and
   timing — the bulk of the token mass in agentic sessions and the part an
   agent most needs to remember ("that query failed") — are discarded at
   write time, even though `AIMessage.tool_calls` carries them
   (`ToolCall.arguments/result/error/execution_time`, `models/basic.py:23-30`).

**Who is affected:** every stateful bot round (`BaseBot.conversation/invoke/
ask/ask_stream`, `DataAgent`, `VoiceBot`), operators paying for replayed
tool output, and developers who cannot reason about context-window
pressure deterministically.

**Why now:** FEAT-380 (execution-time tool-result compression) and FEAT-397
(honest provider token counts per call) are done; FEAT-524 gives the two
things the proposal was missing — a single writer to hook and a single pure
render function to extend. This brainstorm covers the deterministic plane
only (Stages 0, 0.5, 1). Stage 2 (LLM summary turns) stays out of scope
with hook points reserved.

---

## Constraints & Requirements

Carried from the proposal (§1, §8) and the two discovery rounds of
2026-09-04 (post-FEAT-524):

- **C1 Deterministic.** Same history + same config ⇒ same rendered bytes.
  No LLM call anywhere in Stages 0–1. Every transformation is a pure
  function testable with fixtures.
- **C2 Non-destructive storage.** History always stores the normalized raw
  turn — where "raw" means *recoverable byte for byte*, not *inline*: tool
  outputs above `oversize_tool_tokens` are offloaded at write time into the
  memory-owned omission store (content-addressed, indexed by `turn_id`),
  with a short preview left in the turn (v3 decision). Pruning is computed
  at render time; pruned forms are never persisted. The only persisted compaction state is
  `history.metadata["compaction"]` (tokenizer, calibration, prune
  boundary, `stage2_needed`).
- **C3 Default-on, size-aware retention (decision 2026-09-04, v3).**
  Every bot renders history through `compact_history` with a
  `ContextBudget` that always exists: built from `MODEL_WINDOWS` when the
  model is known, otherwise from a conservative fallback window (32k). Both
  tiers of the retention model (C10) and pruning into the omission store are
  **on by default**. The explicit escape hatch is `context_budget=False`
  (or `PARROT_COMPACTION_DISABLED=1`, mirroring FEAT-380's kill switch),
  which restores FEAT-524's plain `render_history(history,
  max_turns=self.max_context_turns, …)` byte for byte. Rationale: after
  FEAT-524 injects every kept turn verbatim, `max_turns=50` is the *unsafe*
  default; this spec is where it gets replaced. (Supersedes the earlier
  opt-in decision.) Stage 0 changes the *stored* bytes of new turns (NFC,
  ANSI/C0, trailing whitespace) in all modes; memory-level
  `normalize=False` escape hatch. See Open Questions.
- **C4 Write-once, in the memory layer.** Stage 0 normalization and Stage
  0.5 token counting run once, in a concrete
  `ConversationMemory.add_turn()` that delegates to a new abstract
  `_store_turn()`. Both are **always-on**: size-aware retention (C10)
  needs a `token_count` on every turn, so every memory instance counts —
  with `tiktoken` when importable, else the `"heuristic"` (`bytes/4`)
  counter, recorded by name. (Reverses the v2-F8 gating; cost is
  milliseconds per write.) This covers the FEAT-524 single writer, the separate
  `ChatStorage` tier (`storage/chat.py:202-211` calls
  `RedisConversation.add_turn` with `key_prefix="chat"`), voice transcripts,
  and any future writer. Backends rename their bodies; public API unchanged.
  (Round 1 v2.)
- **C5 Backward-compatible payloads.** Turn dicts without
  `tool_invocations`, `token_count`, `state`, `schema_version` deserialize
  unchanged (FEAT-524 already does this for `chatbot_id`). `tools_used`
  stays a real dataclass field (13 constructor sites, `from_dict`, and
  `from_ai_message` pass it by keyword).
- **C6 Lossless pruning.** Omitted content goes to an `OmissionStore`
  (content-addressed `om_` + blake2b-8, idempotent `put`) **owned by the
  `ConversationMemory` backend** (same Redis connection / same file root /
  same process dict), retrievable via a built-in `read_omitted_content`
  tool. Separate from the FEAT-380 working-memory tee. (Rounds 1 and 2 v2.)
- **C7 Errors survive.** Turn-level and tool-level errors are never
  omitted; tracebacks are condensed by Stage 0 rule 5 only.
- **C8 Uniform text rendering, appended to the assistant message.**
  `HistoryMessage` is text-only with roles `user`/`assistant` and a strict
  alternation guarantee (FEAT-524 `render.py`). Tool activity (RAW turns)
  and omission notices (PRUNED turns) render as a fenced block appended to
  the assistant content; no new role, no provider-native blocks. (Round 1
  v2.)
- **C9 Compaction is a pure pre-pass; `render_history` learns tool text.**
  `compact_history(history, budget, policies, boundary, counter) ->
  CompactionResult(views, omissions, history_estimate, boundary_turn_id,
  stage2_needed)` is a new pure, synchronous function. `render_history`'s
  first parameter is **widened** to `ConversationHistory | Sequence[TurnView]`
  (a type-level signature change — review v2 F3); behavior and output for a
  plain `ConversationHistory` are byte-identical to FEAT-524. **Purity
  boundary (falsifiable, review v2 F4):** a `TurnView` carries already
  materialized text (`assistant_suffix: str` — the tool-activity block or
  omission notices — plus the verbatim user/assistant text);
  `render_history` only concatenates it. It imports nothing from
  `parrot.memory.compaction`, computes no content ids, never touches an
  `OmissionStore`, never mutates a view. `render.py` stays a leaf module
  importing `.abstract` only. (Round 1 v2.)
- **C10 Tokens are the retention unit; turns are the atomic unit
  (decision 2026-09-04, v3).** The `AbstractBot` 50 / `Chatbot` 5
  discrepancy (`bots/abstract.py:590`; `bots/chatbot.py:236,406`) is
  resolved by one rule for every bot, walked newest → oldest over the
  per-turn calibrated token counts, never splitting a turn:
  1. **Verbatim tier** — recent turns render in full while their
     cumulative tokens stay under `verbatim_tokens` (default **15,000**);
     `min_verbatim_turns` (default **2**) are always verbatim so one huge
     answer cannot empty the window.
  2. **Pruned tier** — older turns render pruned (tool I/O and RAG context
     to the omission store) until the whole history reaches
     `high_watermark × available`.
  3. **Dropped tier** — beyond that, turns are not rendered; the boundary
     is the Stage 2 hook (`stage2_needed`).
  4. **Ceiling** — `max_turns` (default **30**, unified for `AbstractBot`
     and `Chatbot`) caps the walk as a safety net only. The `Chatbot` DB
     field `max_context_turns` keeps its meaning as a per-agent ceiling
     override; no schema change.
  **Oversize-result rule** (author, v3): a tool output above
  `oversize_tool_tokens` (default **2,000**) is pruned **even inside the
  verbatim tier**, except in the most recent turn — retaining a
  hundreds-of-rows dataset for ten or twenty turns is waste when the exact
  bytes are one tool call away. Its notice offers both recovery routes:
  `read_omitted_content(om_…)` (durable, this feature) and, when the
  `ToolCall.result` carried a FEAT-380 `_tee` pointer, the working-memory
  key for `wm_get_result`. Caveat: FEAT-380 tee keys are *not* keyed by the
  conversation `turn_id` (`tools/compression/tee.py:29-37` uses a
  per-`ToolManager` uuid) and working memory is process-local, so the
  omission store is the recovery path that survives a restart.
  Worked shape: 50 chat turns of ~150 tokens → all verbatim; 10 database
  turns of ~8k tokens → the latest verbatim, the rest pruned to a few
  hundred tokens each. Same defaults, right outcome both times. This
  supersedes "budget replaces the cap" and `keep_turns`, and closes review
  v2-F2 (text-only sessions are now bounded by `verbatim_tokens` +
  watermark + `max_turns`).
- **C11 Calibration pairing happens in `save_conversation_turn`.** The bot
  is the only layer that sees the rendered history, the system prompt, the
  prompt *and* the returned `AIMessage.usage`. It passes its prompt
  estimate into `save_conversation_turn`, which calls
  `memory.report_usage()`; the memory owns the EWMA. Clients are never
  involved. (Round 1 v2.)
- **C12 Session scoping via a new ContextVar.** `current_memory_key_id` is
  added to `parrot.observability.context` next to `current_agent_name` /
  `current_user_id` / `current_session_id` (`context.py:56-60`); bots set it
  where they set the other two (`bots/base.py:207-208, 628-629, 990-991,
  1622-1623`). `read_omitted_content` resolves `(memory_key_id, user_id,
  session_id)` from the four ContextVars. (Round 2 v2 — author's choice over
  a per-bot bound toolkit.) **Binding-order hazard (review v2 F1,
  verified):** today the bots bind `current_user_id`/`current_session_id`
  *before* defaulting the ids (`bots/base.py:990-991` binds; `:1016-1017`
  then does `session_id = session_id or uuid4()`, `user_id = user_id or
  "anonymous"`), so a call without ids would store omissions under the
  generated ids while the tool reads `None`. The spec must (a) bind the
  ContextVars **after** defaulting, at every entry point FEAT-524 M6
  touches, and (b) make the tool **fail closed** — any `None` component ⇒
  "unavailable in this context", never a fallback to an un-segmented key.
- **C13 Prompt-cache honesty.** Renders are monotonic: a turn that once
  rendered pruned always renders pruned (persisted boundary marker); the
  invalidation point is always at least `min_verbatim_turns` back and, in
  practice, `verbatim_tokens` back. The oversize-result rule is the one
  deliberate exception: it prunes a large output as soon as the *next*
  turn exists, which invalidates the provider cache at that turn once —
  the same cost the FEAT-380 tee already accepts.
- **C14 Sequencing.** Brainstorm and `/sdd-spec` are written now against
  the FEAT-524 contract; `/sdd-task` and the worktree wait until FEAT-524
  merges to `dev`, and every line number in the spec's Codebase Contract is
  re-verified on the merged code. (Round 2 v2.)
- **C15 No new heavy dependencies.** `tiktoken` 0.9.0 and `orjson` 3.12.0
  are already core (`packages/ai-parrot/pyproject.toml:61,164`);
  `hypothesis>=6.100` is already a dev dependency (`:702`).

---

## Options Explored

### Option A: Pure compaction pre-pass in `parrot.memory`, budget-aware bot, memory-owned omission store (recommended)

Storage keeps every turn normalized and token-counted (Stage 0 + 0.5 in
the `add_turn()` template method). Each bot entry point, when a
`ContextBudget` is configured, calls `compact_history()` instead of
capping by `max_turns`: the pure pre-pass sums calibrated token counts,
decides which turns fall below the prune boundary, applies per-tool
`PrunePolicy` rules to their `tool_invocations`, and returns turn views
plus the list of omissions (content id + bytes). The bot awaits
`memory.omission_store.put_many(omissions)` (idempotent), then calls
`render_history(views, current_chatbot_id=…)`, which appends a
`<tool-activity>` text block to each assistant message (full for RAW
views, notices for PRUNED views). After the client answers, the bot
builds the turn via `from_ai_message()` (now also filling
`tool_invocations` from `tool_calls`) and calls
`save_conversation_turn(user_id, session_id, turn, prompt_estimate=…)`,
which persists the turn, advances the boundary marker, and reports
`(estimate, usage.input_tokens)` to `memory.report_usage()` for the EWMA.
A single internal tool, `read_omitted_content`, is registered on the bot's
`ToolManager` whenever a budget is set — a bare
`register_tool(name=…, description=…, input_schema=…, function=…)` call
bound to the memory's omission store, exactly the shape of the existing
`search_tools` meta-tool (`tools/manager.py:349-370`). No `AbstractToolkit`
subclass, no `AbstractTool` class. It stays in the `ToolManager` because
that is the only place clients take tool schemas from
(`get_tool_schemas`, `manager.py:1152`) and dispatch through
(`AbstractClient._execute_tool`, `clients/base.py:1461`), and because
`execute_tool` is the single choke point for permissions, redaction,
FEAT-380 compression and tool telemetry.

✅ **Pros:**
- Honors every FEAT-524 boundary: memory renders, bot orchestrates and
  records, clients format. No client file is touched.
- Storage stays canonical and non-destructive; a prune-policy bug is fixed
  by changing the render, never by repairing Redis.
- Estimate and provider count meet in one method (`save_conversation_turn`)
  that FEAT-524 already made the single writer; every entry point inherits
  the hook.
- Everything except the two `await`s (flush, persist) is pure → fixture and
  property tests; idempotence via `hypothesis`.
- Coexists with FEAT-380: compression shrinks a payload at execution;
  pruning shrinks it again by *age*. Different triggers, different stores.

❌ **Cons:**
- Pruning work runs on each render once past the boundary (bounded: the
  boundary is monotonic, and the view for a pruned turn is a pure function
  of the stored turn — cacheable in-process per `(turn_id, norm_version,
  policy_version)` without persisting anything).
- Two recovery tools for the LLM (`wm_get_result` from FEAT-380,
  `read_omitted_content` here). Acceptable: each notice names the tool to
  call.
- Touches `bots/base.py` in the same four entry points FEAT-524 M6
  rewrites — hence the strict "after merge" sequencing (C14).

📊 **Effort:** Medium–High (6 modules + bot integration + tests).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tiktoken` 0.9.0 | BPE token estimator (`o200k_base`) | Core dep (`pyproject.toml:61`). Existing code uses `cl100k_base` in 3 places (`skills/parsers.py:29`, `knowledge/wiki/store.py:202`, `knowledge/pageindex/utils.py:53`); the counter records its encoding name per turn so mixed histories are detectable. `get_encoding` may hit the network on first use — cache lazily like `knowledge/wiki/store.py:187-202`, fall back to a `bytes/4` counter named `"heuristic"`. |
| `orjson` 3.12.0 | Canonical JSON (`OPT_SORT_KEYS`) for JSON-shaped strings and `ToolInvocation.input` | Core dep (`pyproject.toml:164`). |
| stdlib `unicodedata`, `re`, `hashlib.blake2b`, `contextvars` | NFC, ANSI/C0 stripping, content ids, session scoping | No new deps. |
| `hypothesis` ≥ 6.100 | Idempotence / purity property tests | Dev dep (`pyproject.toml:702`). |

🔗 **Existing Code to Reuse (dev unless marked FEAT-524):**
- `memory/abstract.py:135-210` — `ConversationMemory` ABC (template method, `report_usage`, store ownership).
- `memory/mem.py:65`, `memory/redis.py` `add_turn`, `memory/file.py:83` — bodies become `_store_turn`. FEAT-524 already adds the missing `super().__init__()` to Redis and File (worktree `redis.py:19`, `file.py:13`).
- **FEAT-524** `memory/render.py` — `HistoryMessage`, `render_history()`; extended, not replaced.
- **FEAT-524** `memory/abstract.py` `ConversationTurn.chatbot_id` + `from_ai_message(..., assistant_text=None)` — extended to fill `tool_invocations`.
- **FEAT-524** `bots/abstract.py` `memory_key_id` property + `save_conversation_turn(user_id, session_id, turn)` — the calibration hook.
- `models/basic.py:23-30` `ToolCall` — source of `ToolInvocation`; `:48-110` `CompletionUsage.input_tokens`.
- `models/responses.py:118,139` `AIMessage.usage`, `.tool_calls`.
- `observability/context.py:56-60` ContextVars + `invocation_context()` (gains a `memory_key_id` kwarg).
- `tools/manager.py:349-370` — `search_tools` meta-tool self-registration via `register_tool(name, description, input_schema, function=…)`: the template for `read_omitted_content`; `:608` excludes `search_tools` from its own results (same exclusion for the new tool).
- `security/groundedness/normalize.py` — style precedent for pure, stdlib-only normalizers.

---

### Option B: Mutate-at-write compaction (magic-compact style)

Pruning is applied to persisted state: `add_turn()` detects the high
watermark and rewrites older turns in place (omitting payloads into the
store), so `render_history` needs no compaction awareness at all.

✅ **Pros:**
- `render_history` untouched; the history *is* the rendered form.
- Redis payload shrinks over time (the only option that reduces storage).

❌ **Cons:**
- Destructive: raw turns survive only in the omission store; a policy bug
  corrupts every session it touched. Violates C2.
- Every prune rewrites the whole `turns` hash field (Redis `add_turn`
  re-serializes the full list) — an O(n) rewrite exactly when histories
  are largest.
- Write-time pruning cannot know the *current* bot's budget: the same
  history may be read by a crew member with a different window
  (`include_other_agents=True` case).
- Breaks the hot-copy assumption `ChatStorage` makes about Redis.

📊 **Effort:** Medium.

📦 **Libraries / Tools:** same as A.

🔗 **Existing Code to Reuse:** the three backends' `add_turn`; nothing in `render.py`.

---

### Option C: Bot-side wrapper only — compaction lives in `AbstractBot`, `parrot.memory` stays as FEAT-524 leaves it

`AbstractBot.render_for_llm()` selects turns by budget, calls
`render_history` on a filtered `ConversationHistory` copy, and post-edits
the resulting `HistoryMessage`s (appending notices). Token counts and the
omission store live in a bot mixin.

✅ **Pros:**
- Zero changes to `parrot.memory` beyond `report_usage`; FEAT-524's render
  contract is frozen.
- Fastest to prototype.

❌ **Cons:**
- Pruning logic that needs `ToolInvocation` data lives in the bot, but the
  data is stored by the memory layer — two packages must agree on a schema
  neither owns.
- Post-editing `HistoryMessage`s after `render_history` merged same-role
  runs loses the turn boundary (a merged message spans several turns), so
  notices cannot be attributed to the right turn.
- Duplicates `render_history`'s alternation logic in the bot the moment it
  needs to inject text — the exact split FEAT-524 was written to end.
- `ChatStorage`-tier histories never get normalized or counted.

📊 **Effort:** Medium, with high architectural debt.

📦 **Libraries / Tools:** same as A.

🔗 **Existing Code to Reuse:** FEAT-524 `render_history`, `AbstractBot.execute_llm_call` (`bots/abstract.py:1239`).

---

### Option D (unconventional): Reuse FEAT-380's compression pipeline and working-memory tee for aging

Add an age-based `FilterLevel` to `CompressionStage`, run it over stored
turns at render time, and use `CompressionTee` / `wm_get_result` as the
omission surface — no new store, no new tool.

✅ **Pros:**
- One recovery tool for the LLM, one codec registry, one TOML format.
- Reuses the latency budget / circuit breaker already built.

❌ **Cons:**
- `WorkingMemoryToolkit` is in-memory per session; nothing survives a
  restart, while Redis histories do — omissions would expire before the
  history that references them.
- FEAT-380 compresses on **fresh execution only** (`_compressed` marker)
  and has no turn concept (`tools/compression/tee.py:26-37` documents this
  explicitly); tee keys are counter-based, not content-addressed.
- Couples `parrot.memory` to `parrot.tools` — the render leaf module could
  no longer be imported by clients without pulling the tools package
  (FEAT-524 §7 "leaf module" rule).

📊 **Effort:** Medium, wrong layer.

📦 **Libraries / Tools:** none new.

🔗 **Existing Code to Reuse:** `tools/compression/{stage,tee,registry}.py`, `tools/working_memory/tool.py:208,259`.

---

## Recommendation

**Option A** is recommended because:

- It is the only option that satisfies C1 (deterministic), C2
  (non-destructive), C3 (byte-identical when off) and FEAT-524's layer
  split simultaneously. Option B trades C2 for a simpler read and cannot
  honor per-reader budgets; Option C re-splits rendering across two
  packages; Option D inherits an in-memory store and a no-turn-concept
  pipeline.
- The integration surface is exactly the two seams FEAT-524 created on
  purpose: `render_history` (documented in `render.py`'s module docstring as
  "the extension point for the forthcoming per-turn compaction work") and
  `save_conversation_turn` (the single writer).
- Both dependencies and the property-test tooling are already installed.

What we trade off: render-time CPU once past the boundary (bounded and
cacheable in-process), a fourth ContextVar to keep in sync, and a second
recovery tool alongside `wm_get_result`. All three are explicit and
tested.

---

## Feature Description

### User-Facing Behavior

- **Default-on.** Every bot gets size-aware retention with the defaults in
  C10 (`max_turns=30`, `verbatim_tokens=15_000`, `min_verbatim_turns=2`,
  `oversize_tool_tokens=2_000`, window from `MODEL_WINDOWS` or 32k). A
  support chat sees all its recent turns verbatim; a database agent sees
  its last answer verbatim and earlier datasets as notices.
- **Tuning:** `Agent(..., context_budget=ContextBudget(window=200_000,
  verbatim_tokens=…))` or the bot-config keys; `Chatbot.max_context_turns`
  from the DB acts as the turn ceiling. **Escape hatch:**
  `context_budget=False` / `PARROT_COMPACTION_DISABLED=1` → FEAT-524's
  plain render.
- Pruned turns keep user message and assistant text intact; tool I/O is
  replaced by `<tool-output-omitted tool="…" chars="…" id="om_…">` notices
  (plus the `wm_get_result` key when a FEAT-380 tee exists), RAG context by
  a one-line notice, errors kept condensed. Oversized tool outputs are
  pruned from every turn but the latest.
- Verbatim (RAW) turns render a compact `<tool-activity>` block after the
  assistant text — tool activity becomes visible in history for the first
  time.
- The agent gains `read_omitted_content(content_id)`: exact historical
  bytes, or a fixed "expired or unknown — re-run the tool" message.
- Operators read `history.metadata["compaction"]` (`tokenizer`,
  `calibration`, `boundary_turn_id`, `stage2_needed`).

### Internal Behavior

1. **Write (Stage 0 + 0.5, memory layer).** `ConversationMemory.add_turn()`
   becomes concrete: `normalize_turn(turn)` (NFC; ANSI/C0 strip; trailing
   whitespace strip; ≥3 blank lines → 2; canonical `orjson` for
   JSON-shaped strings and dict inputs; traceback condensation for error
   fields) → `count_turn(turn, counter)` (default `tiktoken` `o200k_base`,
   name recorded) → `await self._store_turn(...)` (renamed backend body).
   Recount only when `token_count is None` or the recorded tokenizer
   differs. Stamps `norm_version` and `schema_version = 2`. Legacy records
   deserialize with defaults; counted lazily at first compaction and
   stamped on their next write.
2. **Capture (FEAT-524 constructor, extended).** `from_ai_message()` also
   fills `tool_invocations` from `response.tool_calls`
   (`ToolCall.name/arguments/result/error/execution_time` →
   `ToolInvocation.tool_name/input/output/error/elapsed_ms`, `status =
   ERROR` when `error` is set) and `turn.error` when the round failed.
   `tools_used` stays a real field (FEAT-524 already derives it from
   `tool_calls`).
3. **Compact (pure, sync).** `compact_history(history, budget, policies,
   boundary, counter) -> CompactionResult`. `available = window −
   reserve_output − reserve_fixed`. Walk the last `max_turns` turns newest
   → oldest with `calibration × token_count.total`: (i) verbatim while the
   cumulative sum ≤ `verbatim_tokens`, with at least `min_verbatim_turns`;
   (ii) then pruned while the cumulative sum (using each turn's *pruned*
   size) ≤ `high_watermark × available`; (iii) the remainder is dropped and
   `stage2_needed` is set when anything was dropped. Turns at or before the
   persisted boundary always render pruned regardless of tier (monotonic,
   C13), and the new boundary is the oldest verbatim turn's predecessor.
   Independently, any `ToolInvocation` whose output exceeds
   `oversize_tool_tokens` is pruned in every turn except the newest
   (C10). For each pruned invocation `prune_turn(turn, policies)` applies
   the per-tool `PrunePolicy` (registry with `DefaultPolicy` fallback;
   built-ins for file write/read, shell, sub-agent, HTTP/search/DB) and
   *collects* omissions `(content_id, content)` — ids are hashes, so
   notices are renderable before storage. The pruned size of a turn is
   itself a pure function of the turn and the policies, so step (ii) needs
   no store access.
4. **Flush + render (bot, async).** `await memory.omission_store.put_many(
   session_key, result.omissions)`; on failure the bot renders the plain
   FEAT-524 path for this call (no notices pointing at unstored content)
   and logs a warning. Then `render_history(result.views,
   current_chatbot_id=self.memory_key_id)`: each view's tool text is
   appended to its assistant content before the FEAT-524 merge/alternation
   logic runs, so guarantees hold unchanged. `AIMessage.
   set_conversation_context_info()` is fed from `len(rendered)` as in
   FEAT-524.
5. **Record + calibrate (bot → memory).** `save_conversation_turn(user_id,
   session_id, turn, *, compaction: Optional[CompactionCommit] = None)`
   where the commit carries `prompt_estimate = tokens(rendered history) +
   tokens(system_prompt) + tokens(prompt)`, the new `boundary_turn_id`, and
   `stage2_needed`. **Ordering (review v2 F5):** the commit travels *into*
   `memory.add_turn(..., compaction=commit)` so each backend persists the
   turn and the updated `metadata.compaction` (boundary, flags, EWMA) in
   **one** write — a single `hset` with both `turns` and `metadata` fields
   on Redis (today `add_turn` writes `turns`/`updated_at` only, `redis.py`
   hash path), one file rewrite on File, one dict assignment in memory.
   `MessageAddedEvent` fires only after that write returns (FEAT-524 order
   preserved). If the write fails, nothing is persisted; on the next round
   `compact_history` recomputes the boundary deterministically from the
   stored history, so the worst case is a boundary that did not advance,
   never one that regresses. The EWMA update (α = 0.2, clamped to
   [0.5, 2.0]) uses `turn.metadata["usage"]["input_tokens"]` when present.
   Tool schemas and provider framing are not estimated; they become a
   stable per-agent bias the ratio absorbs (ratio > 1 ⇒ conservative
   budgeting).
6. **Recover.** A module-level async function in
   `parrot.memory.compaction` (`read_omitted_content(content_id)`), bound
   to the memory's store at registration time, resolves the session key
   from `current_memory_key_id` / `current_user_id` / `current_session_id`
   (fail closed on any `None`) and calls `memory.omission_store.get()`.
   The bot registers it with `self.tool_manager.register_tool(name=
   "read_omitted_content", description=…, input_schema=…, function=…)` at
   the point it enables the budget — the `search_tools` pattern
   (`tools/manager.py:349-370`) — and excludes it from `search_tools`
   results the way `search_tools` excludes itself (`:608`), since every
   omission notice already names the tool. No toolkit class, no client
   changes.
7. **Lifecycle.** `clear_history()` / `delete_history()` cascade to
   `omission_store.clear(session_key)`. Histories have no TTL today
   (`memory/redis.py:490` is commented out); because renders are monotonic,
   an omission that expires before its history leaves a notice that can
   never resolve (review v2 F7). Default `omission_ttl = None` (no expiry,
   same as the history), configurable for operators who accept the
   degradation; the notice text always says "may have expired — re-run the
   tool". **Foreign turns** (crew/flow shared history, review v2 F6): their
   omissions are stored under the key of the history being rendered (the
   current bot's `memory_key_id`), because the omission is a render
   artifact of *this* history; the producing agent's own history is never
   written to.

### Edge Cases & Error Handling

- **Kill switch** (`context_budget=False` / `PARROT_COMPACTION_DISABLED=1`)
  → the bot never enters the compaction path; a byte-equality test compares
  `HistoryMessage` lists against FEAT-524's plain render.
- **Unknown model** → fallback `window=32_000`; logged once per bot.
- **Single huge turn** (latest answer alone exceeds `verbatim_tokens`) →
  still verbatim (`min_verbatim_turns`), minus oversize tool outputs in
  older turns; if it alone exceeds `available`, `stage2_needed` is set and
  the turn renders anyway (never truncated here).
- **Legacy turns without `token_count`** → counted at first compaction with
  the current counter; never blocks rendering; stamped on next write.
- **Tokenizer mismatch** (`token_count.tokenizer != counter.name`) →
  recount that turn; log once per history.
- **`tiktoken` unavailable offline** → `"heuristic"` counter (`bytes/4`),
  warning once; calibration still converges on provider counts.
- **Flush failure** → plain FEAT-524 render for this call; boundary not
  advanced; warning.
- **Unknown/expired id** → fixed message steering the model to re-run the
  tool; no exception.
- **Cross-session probe** → store keys are
  `{prefix}_omitted:{memory_key_id}:{user}:{session}`; foreign ids are
  "unknown".
- **Degenerate usage reports** (`estimate == 0`, missing usage) → ignored;
  clamp keeps the EWMA in [0.5, 2.0].
- **Foreign turns** (`include_other_agents=True`, crew case) → pruned by
  the same rules; their notices carry the `[agent:…]` label FEAT-524 adds.
- **All prunables exhausted, still above high watermark** → render what we
  have, persist `stage2_needed = True`; no truncation introduced here.
- **Errors** (`ToolInvocation.status == ERROR`, `turn.error`) → never
  omitted; condensed by Stage 0 rule 5 only.
- **`ask_stream` partial save on error** (FEAT-524 keeps it) → goes through
  the same `save_conversation_turn`; no compaction commit (no estimate to
  pair).
- **`ChatStorage` tier** (`key_prefix="chat"`) → normalized and counted by
  C4 (always-on, v3), never compacted (no bot renders it through
  `compact_history`). Note for FEAT-524: `storage/chat.py:638` still calls the removed
  `get_messages_for_api()` in the worktree at `cdd3cee20`; it must switch
  to `render_history` there, not here. Flagged in Open Questions.

---

## Capabilities

### New Capabilities
- `conversation-turn-normalization`: Stage 0 ruleset v1, `norm_version`,
  idempotence guarantee, `normalize=False` escape hatch.
- `conversation-token-accounting`: `TokenCounter` protocol, `tiktoken`
  default + heuristic fallback, `TokenCount` per turn, tokenizer-name
  recording, lazy recount.
- `context-budget-policy`: `ContextBudget` with the three-tier,
  token-based retention walk (verbatim / pruned / dropped), unified
  `max_turns` ceiling, oversize-result rule, monotonic boundary,
  `MODEL_WINDOWS` + fallback window, default-on with kill switch.
- `deterministic-turn-compaction`: `compact_history`, `prune_turn`,
  `PrunePolicy` protocol + registry + built-ins, `CompactionResult`.
- `history-tool-text-rendering`: `render_history` renders `tool_invocations`
  and omission notices as an appended assistant block (views only).
- `omission-store`: `OmissionStore` ABC owned by `ConversationMemory`;
  `InMemory`/`Redis`/`File` backends; content-addressed ids; independent
  TTL; clear/delete cascade.
- `read-omitted-content-tool`: one internal function tool registered via
  `ToolManager.register_tool(function=…)` (the `search_tools` shape), scoped
  by the new `current_memory_key_id` ContextVar + existing user/session
  ContextVars; excluded from `search_tools` results.
- `usage-calibration-handshake`: `ConversationMemory.report_usage`, EWMA
  in history metadata, pairing inside `save_conversation_turn`.

### Modified Capabilities
- `conversation-history-ownership` (FEAT-524): `ConversationTurn` schema
  v2 (`tool_invocations`, `error`, `token_count`, `state`, `schema_version`,
  `norm_version`); `from_ai_message` fills invocations; `render_history`
  accepts turn views; `save_conversation_turn` gains an optional
  compaction commit; `AbstractBot` gains `context_budget`.
- `conversation-memory` backends: template-method `add_turn`/`_store_turn`;
  `token_counter`, `omission_store`, `normalize` constructor options.
- `per-agent-attribution` (FEAT-228 ContextVars): fourth ContextVar
  `current_memory_key_id`; `invocation_context()` gains a kwarg.
- `tool-result-compression` (FEAT-380) and `tokens-observability`
  (FEAT-397): unchanged; consumed.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `memory/abstract.py` `ConversationTurn` (FEAT-524 shape) | extends | new fields with defaults; `from_ai_message` fills `tool_invocations`/`error`; `to_dict`/`from_dict` carry them; `tools_used` unchanged |
| `memory/abstract.py` `ConversationMemory` | modifies | `add_turn` concrete (normalize → count → `_store_turn`); new abstract `_store_turn`; new `report_usage`, `commit_compaction_state`; constructor gains `token_counter`, `omission_store`, `normalize`; `clear_history`/`delete_history` cascade |
| `memory/mem.py`, `memory/redis.py`, `memory/file.py` | modifies | `add_turn` bodies → `_store_turn`; each constructs its matching `OmissionStore` |
| `memory/render.py` (FEAT-524) | extends | accept `Sequence[TurnView]`; append tool text to assistant content; guarantees and plain-history output unchanged |
| `memory/compaction/` (new package) | new | `models.py`, `normalize.py`, `tokens.py`, `budget.py`, `policies.py`, `compact.py`, `omission.py`; leaf-module rule: imports `.abstract` only |
| `memory/__init__.py` | extends | export `ContextBudget`, `CompactionResult`, `OmissionStore`, `TokenCounter`, `ToolInvocation`, `TurnState` |
| `bots/abstract.py:590` `max_context_turns` default 50; `bots/chatbot.py:236,406` default 5 | modifies | one default (`ContextBudget.max_turns=30`) as a ceiling; the `Chatbot` DB value overrides the ceiling only |
| `bots/abstract.py` (FEAT-524 shape) | extends | `context_budget` kwarg (default `None` ⇒ auto-built budget; `False` ⇒ kill switch); `save_conversation_turn(..., compaction=None)`; `register_tool(name="read_omitted_content", function=…)` on the bot's `ToolManager` when budgeted |
| `bots/base.py` four entry points (FEAT-524 M6 shape) | modifies | budget branch: `compact_history` → flush → `render_history(views)`; set `current_memory_key_id`; pass the commit into `save_conversation_turn` |
| `bots/data.py`, `bots/voice.py` (FEAT-524 M6 shape) | modifies | same budget branch where a history is rendered |
| `observability/context.py:56-60` | extends | `current_memory_key_id` ContextVar; `invocation_context(memory_key_id=…)` |
| `memory/compaction/recover.py` `read_omitted_content()` | new | plain async function; registered via `ToolManager.register_tool(function=…)` (`manager.py:714`, precedent `:349-370`); `search_tools` exclusion list extended (`:608`) |
| `tools/manager.py` | extends (one line) | exclude `read_omitted_content` from `search_tools` results alongside `search_tools` itself (`:608`) |
| `storage/chat.py:202-211` | depends on | its `RedisConversation.add_turn` calls inherit normalization/counting; no compaction |
| `parrot/clients/*` | **none** | memory-less after FEAT-524; `_format_history` sees longer assistant text only |
| `pyproject.toml` | none | `tiktoken`, `orjson`, `hypothesis` already present |

**Breaking changes:** none for callers. Internal: `ConversationMemory`
subclasses must implement `_store_turn` instead of `add_turn` (hard cut,
all three in-repo backends updated in-feature; no external consumers per
the author). New Redis keys `{prefix}_omitted:{key_id}:{user}:{session}`.

---

## Code Context

### User-Provided Code

```python
# Source: sdd/proposals/per-turn-conversation-compactation.proposal.md §2.1, §2.2, §4.3, §4.4, §5.3
# (design sketches, not yet in code; kept verbatim as the vocabulary for the spec)
class ToolStatus(str, Enum):
    COMPLETED = "completed"
    ERROR = "error"

@dataclass
class ToolInvocation:
    tool_name: str
    input: Dict[str, Any]
    output: Optional[str] = None
    status: ToolStatus = ToolStatus.COMPLETED
    error: Optional[str] = None
    elapsed_ms: Optional[int] = None
    omitted: Dict[str, str] = field(default_factory=dict)

class TurnState(str, Enum):
    RAW = "raw"
    PRUNED = "pruned"
    SUMMARIZED = "summarized"

async def report_usage(self, user_id: str, session_id: str,
                       estimated_prompt_tokens: int, provider_prompt_tokens: int,
                       chatbot_id: Optional[str] = None) -> None: ...

@dataclass(frozen=True)
class ContextBudget:            # proposal §4.4 as revised in this brainstorm (C10 v3)
    window: int                 # from MODEL_WINDOWS, else 32_000 fallback
    reserve_output: int = 8192
    reserve_fixed: int = 4096
    high_watermark: float = 0.80
    low_watermark: float = 0.60
    max_turns: int = 30         # unified ceiling (was AbstractBot 50 / Chatbot 5); Chatbot DB field overrides
    verbatim_tokens: int = 15_000
    min_verbatim_turns: int = 2
    oversize_tool_tokens: int = 2_000
    # keep_turns (proposal) is REMOVED — replaced by verbatim_tokens + min_verbatim_turns

class OmissionStore(ABC):
    async def put(self, session_key: str, content: str) -> str: ...
    async def get(self, session_key: str, content_id: str) -> Optional[str]: ...
    async def clear(self, session_key: str) -> None: ...
```

### Verified Codebase References

> Paths relative to `packages/ai-parrot/src/parrot/`. Two baselines:
> **dev** @ `f0a8b2256` (2026-09-04) for code that FEAT-524 does not touch,
> and **FEAT-524 worktree** @ `cdd3cee20` (TASK-2808/2809/2810 done) for the
> contract this feature builds on. Every FEAT-524 reference MUST be
> re-verified on `dev` after the merge (C14).

#### Classes & Signatures
```python
# ── FEAT-524 contract (worktree cdd3cee20; spec §2 "Data Models") ─────────────
# memory/render.py  (leaf module: imports only .abstract)
@dataclass(frozen=True)
class HistoryMessage:                                      # line 42
    role: Literal["user", "assistant"]                     # 56
    content: str                                           # 57
    chatbot_id: Optional[str] = None                       # 58
    turn_id: Optional[str] = None                          # 59
def render_history(history: Optional[ConversationHistory], *,
                   max_turns: Optional[int] = None,
                   current_chatbot_id: Optional[str] = None,
                   include_other_agents: bool = True,
                   other_agent_label: str = "[agent:{chatbot_id}]") -> List[HistoryMessage]  # 87-94
    # guarantees: strict alternation, starts user / ends assistant, same-role merge with "\n\n",
    # empty assistant_response → turn skipped, input never mutated. max_turns <= 0 → [].

# memory/abstract.py (worktree)
@dataclass
class ConversationTurn:                                    # existing fields unchanged
    chatbot_id: Optional[str] = None                       # line 30 (NEW in FEAT-524)
    @classmethod
    def from_ai_message(cls, *, user_message: str, response: "AIMessage", user_id: str,
                        chatbot_id: str, context_used: Optional[str] = None,
                        turn_id: Optional[str] = None,
                        assistant_text: Optional[str] = None) -> 'ConversationTurn'   # 63-73
        # tools_used=[tc.name for tc in response.tool_calls]; metadata={model, provider,
        # usage (model_dump), finish_reason, response_time}; chatbot_id stamped.  (:104-126)
    # get_messages_for_api() REMOVED (note at :149)

# bots/abstract.py (worktree)
@property
def memory_key_id(self) -> str                             # line 1806 — explicit chatbot_id else self.name
async def save_conversation_turn(self, user_id: str, session_id: str, turn: ConversationTurn) -> None  # ~1868
    # single writer; keys by memory_key_id; asserts turn.chatbot_id == memory_key_id (spec §2)

# memory/redis.py:19, memory/file.py:13 (worktree) — super().__init__() now called (was missing on dev)
# memory/__init__.py:13 (worktree) — from .render import HistoryMessage, render_history

# ── dev @ f0a8b2256 (unchanged by FEAT-524) ─────────────────────────────────────
# memory/abstract.py
class ConversationMemory(ABC):                             # line 135
    def __init__(self, debug: bool = False)                # 138  (self.logger, self._json = JSONContent())
    @abstractmethod async def add_turn(self, user_id, session_id, turn, chatbot_id=None) -> None  # 172
    @abstractmethod async def clear_history(...) / delete_history(...)                           # 183 / 202
# memory/mem.py  InMemoryConversation.add_turn                # line 65  (history.add_turn only)
# memory/redis.py RedisConversation.add_turn                 # hash mode: hget 'turns' → append to_dict() → hset
#   _get_key → "{prefix}:{chatbot_id}:{user}:{session}"; NO expire anywhere (:490 commented)
#   clear_history resets 'turns' only (:230); delete_history deletes key + session index (:266)
# memory/file.py  FileConversationMemory.add_turn            # line 83

# models/basic.py
class ToolCall(BaseModel):                                 # line 23
    id: str; name: str; arguments: Dict[str, Any]
    result: Optional[Any] = None; error: Optional[str] = None; execution_time: Optional[float] = None
class CompletionUsage(BaseModel):                          # line 48
    prompt_tokens: int  # 76 (alias input_tokens)   completion_tokens: int  # 79
    @property input_tokens(self) -> int  # 104        @property output_tokens(self) -> int  # 110

# models/responses.py
class AIMessage(BaseModel):                                # line 72
    usage: CompletionUsage  # 118     tool_calls: List[ToolCall]  # 139     turn_id: Optional[str]  # 163

# observability/context.py
current_agent_name / current_user_id / current_session_id: ContextVar[Optional[str]]   # 56 / 58 / 60
@contextmanager def agent_identity(name)                                                # 63
@contextmanager def invocation_context(agent_name, user_id=None, session_id=None)       # 91
# bots/base.py sets user/session ContextVars at :207-208, :628-629, :990-991, :1622-1623
#   (these lines move in FEAT-524 M6 — re-verify)

# bots/abstract.py (dev)
self.max_context_turns: int = kwargs.get('max_context_turns', 50)   # line 590
async def execute_llm_call(self, client, method="ask", **llm_kwargs)  # line 1239

# tools/manager.py
def register_tool(self, tool=None, name: str = None, description: str = None,
                  input_schema: Dict[str, Any] = None, function: Callable = None) -> None   # 714
# search_tools meta-tool self-registered via register_tool(name=..., input_schema=..., function=self.search_tools)  # 349-370
# search_tools() excludes the tool literally named "search_tools" from its results                                    # 608
def get_tool_schemas(self, provider_format: ToolFormat = ToolFormat.GENERIC) -> List[Dict[str, Any]]                # 1152
def add_result_hook(self, fn: Callable[[str, Any, Dict[str, Any]], None]) -> None                       # 2169

# tools/compression/tee.py  class CompressionTee            # 26 — docstring :29-37: ToolManager has no turn concept
# tools/working_memory/tool.py  WorkingMemoryToolkit        # 44; store_result :208; get_result :259

# storage/chat.py
HOT_TTL_HOURS = 48                                          # line 20 — declared, NOT applied to RedisConversation keys
# save_turn → RedisConversation(key_prefix="chat").add_turn(user_id, session_id, turn, chatbot_id=agent_id)  # :202-211
```

#### Verified Imports
```python
from parrot.memory import ConversationHistory, ConversationMemory, ConversationTurn   # memory/__init__.py:3
from parrot.memory import InMemoryConversation, RedisConversation, FileConversationMemory  # memory/__init__.py:10-12
from parrot.memory import HistoryMessage, render_history          # FEAT-524 worktree memory/__init__.py:13
from parrot.models.basic import ToolCall, CompletionUsage         # models/basic.py:23,48
from parrot.models.responses import AIMessage                     # models/responses.py:72
from parrot.tools.manager import ToolManager                      # tools/manager.py (register_tool :714, get_tool_schemas :1152)
from parrot.observability.context import (current_agent_name, current_user_id,
                                          current_session_id, invocation_context)   # context.py:56-60, 91
from datamodel.parsers.json import JSONContent                    # memory/abstract.py:6
import tiktoken   # 0.9.0 installed; pyproject.toml:61
import orjson     # 3.12.0 installed; pyproject.toml:164
```

#### Key Attributes & Constants
- `AbstractBot.memory_key_id` (FEAT-524) is the key segment **and** `turn.chatbot_id`; the omission-store key reuses it.
- `render_history` treats `chatbot_id is None` turns as the current agent's (legacy), and `max_turns <= 0` as "render nothing" — the budget path passes `views` and no `max_turns` (C10).
- `from_ai_message` already supports `assistant_text=` for the streaming partial-save path (worktree `abstract.py:72`).
- Existing `tiktoken` encodings in the codebase: `cl100k_base` at `skills/parsers.py:29`, `knowledge/wiki/store.py:202`, `knowledge/pageindex/utils.py:53`; lazy-cache precedent `knowledge/wiki/store.py:187-202`.
- `RedisConversation.key_prefix` default `"conversation"`; `ChatStorage` uses `"chat"` (`storage/chat.py:49`).

### Does NOT Exist (Anti-Hallucination)
- ~~`ConversationHistory.get_messages_for_api`~~ — **removed by FEAT-524 M2**; do not extend it. The extension point is `render_history`.
- ~~`AbstractClient.conversation_memory`~~, ~~`_prepare_conversation_context`~~, ~~`_update_conversation_memory`~~, ~~`user_id`/`session_id` on `ask()`~~ — removed by FEAT-524 M4/M5. Clients must not be touched by this feature.
- ~~`ConversationMemory.report_usage`~~, ~~`_store_turn`~~, ~~`commit_compaction_state`~~, ~~`omission_store` / `token_counter` attributes~~ — new here.
- ~~`ConversationTurn.tool_invocations` / `.error` / `.token_count` / `.state` / `.schema_version` / `.norm_version`~~ — new here (FEAT-524 adds only `chatbot_id`).
- ~~`TurnState`, `ToolInvocation`, `ToolStatus`, `TokenCount`, `TokenCounter`, `ContextBudget`, `Limit`, `PrunePolicy`, `CompactionResult`, `TurnView`, `OmissionStore` and backends~~ — none exist under `parrot/` (grep verified on dev and worktree).
- ~~`parrot.memory.compaction`~~ package — does not exist.
- ~~`compact_history()`~~ — does not exist; `render_history` has no `budget` parameter.
- ~~`AbstractBot.context_budget`~~, ~~`save_conversation_turn(..., compaction=)`~~ — new here; FEAT-524's signature is `(user_id, session_id, turn)`.
- ~~`current_memory_key_id`~~ ContextVar — does not exist; `context.py` defines exactly three plus `current_run_id`/`current_seat` for usage attribution.
- ~~TTL on Redis history keys~~ — none (`redis.py:490` commented). `omission_ttl` is independent, not "shorter than the history TTL".
- ~~`ToolManager.turn_id` / turn boundaries in `ToolManager`~~ — absent (`tools/compression/tee.py:29-37`).
- ~~`read_omitted_content` tool~~ — does not exist; `wm_get_result` (FEAT-380) is a different tool over a different store.
- ~~`ReadOmittedContentToolkit`~~ — never to be created; rejected in favor of a plain `register_tool(function=…)` registration (see Open Questions).
- ~~A client-side "internal tool" channel outside `ToolManager`~~ — does not exist; clients build the provider tools array only from `tool_manager.get_tool_schemas()` (`manager.py:1152`) and dispatch only via `AbstractClient._execute_tool` (`clients/base.py:1461`).
- ~~A `"tool"` role on `HistoryMessage`~~ — `role: Literal["user", "assistant"]` only; rejected by decision (C8).
- ~~`ContextAssembler` using `tiktoken`~~ — it uses `len(text) // 4` (`memory/unified/context.py`); out of scope.

---

## Adversarial Second Opinion (codex, 2026-09-04)

A neutral brief (proposal + fixed requirements + the pre-FEAT-524 seams)
was given to `codex exec --sandbox read-only`; its nine findings were
spot-checked against the code. Triage against the **post-FEAT-524** design:

| # | Finding (verified) | Disposition |
|---|---|---|
| F1 | Calibration ownership ambiguous; client helpers had no slot for estimate/usage | **MOOT** — clients are memory-less after FEAT-524; pairing moved to `save_conversation_turn` (C11). |
| F2 | `get_messages_for_api()` is sync; a "pure render" cannot `await` Redis puts (`abstract.py:70`, callers `base.py:2322`, `claude.py:1414`, `chat.py:638`) | **CONFIRM** → `compact_history` is pure/sync and *collects* omissions; the async bot flushes them before rendering (C9, step 4). |
| F3 | Persisting `state = PRUNED` / pruned forms contradicts "raw storage + render-time pruning" | **CONFIRM** → only `metadata.compaction` (boundary, calibration, flags) is persisted; pruned forms never are (C2). |
| F4 | "Byte-identical when off" vs write-time normalization changing stored bytes | **CONFIRM** → C3 now scopes the guarantee to the render of stored turns; normalization is always-on with a `normalize=False` escape hatch; open question kept. |
| F5 | `tools_used` as a property breaks `from_dict`/constructor callers (`abstract.py:36`, `base.py:2391`) | **CONFIRM** → `tools_used` stays a real field (C5); FEAT-524 `from_ai_message` already fills it from `tool_calls`. |
| F6 | Structured tool data never reached the memory boundary (`_update_conversation_memory` took names only) | **MOOT** — FEAT-524's `from_ai_message` receives the whole `AIMessage`; this feature extends it to fill `tool_invocations`. |
| F7 | Redis/File backends skip `super().__init__()`; template method cannot assume base state (`redis.py:13`, `file.py:12`) | **CONFIRM, already fixed upstream** — FEAT-524 worktree adds `super().__init__()` (`redis.py:19`, `file.py:13`); spec must list it as a dependency, not redo it. |
| F8 | Estimating inside `_prepare_conversation_context` misses system prompt, tools, current message added later (`openai_base.py:612-617`, `claude.py:537-547`) | **CONFIRM, relocated** → the bot estimates `tokens(rendered) + tokens(system_prompt) + tokens(prompt)`; tool schemas are an absorbed bias (step 5). |
| F9 | Omission TTL vs no history TTL; `clear_history`/`delete_history` do not cascade (`redis.py:230`, `:266`) | **CONFIRM** → memory-owned store with clear/delete cascade and independent `omission_ttl` (step 7). |

No finding was rejected; F1 and F6 are resolved by FEAT-524 rather than by
this design. The reviewer's line references were verified (`redis.py:13-20`
lacked `super().__init__()` on dev; `claude.py:641-659` fills
`tc.result/tc.error`; `openai_base.py:612-617` inserts system + user after
prepare).

### Round 2 (codex on this post-FEAT-524 brainstorm, 2026-09-04)

| # | Finding (verified) | Disposition |
|---|---|---|
| v2-F1 | ContextVars are bound before ids are defaulted (`bots/base.py:990-991` vs `:1016-1017`), so `read_omitted_content` could resolve `None` while omissions sit under generated ids | **CONFIRM** → bind after defaulting at every entry point; tool fails closed (C12). |
| v2-F2 | "Budget replaces `max_turns`" changes retention, not just sizing — text-only sessions expose all old prose (`render.py:126-131` slices by cap) | **ESCALATED, then CLOSED (v3)** → the author replaced the rule with the three-tier token model in C10: verbatim window in tokens, pruned tier to the watermark, unified `max_turns=30` ceiling. |
| v2-F8 (follow-up) | Counting gated on a configured counter | **REVERSED (v3)** → default-on retention needs counts on every turn; counting is always-on with the heuristic fallback (C4). |
| v2-F3 | Saying the `render_history` signature is "untouched" while passing views contradicts `render.py:87-94, 123-131` (reads `history.turns`) | **CONFIRM** → C9 now states the first parameter is widened to `ConversationHistory \| Sequence[TurnView]`. |
| v2-F4 | Purity of `render_history` under-specified once tool text is added (`render.py:11-17, 32` leaf/pure rules) | **CONFIRM** → falsifiable boundary in C9: views carry materialized text; render imports nothing from compaction, computes no ids, touches no store. |
| v2-F5 | Turn write, boundary/EWMA write and event emission are not atomic (`abstract.py` worktree `:1901-1915`; Redis `add_turn` writes `turns`/`updated_at` only) | **CONFIRM** → commit travels into `add_turn(..., compaction=)`; one backend write; event after; failure ⇒ deterministic recomputation, never regression (step 5). |
| v2-F6 | Foreign-turn omissions have an ambiguous owner key (`render.py:142-151`) | **CONFIRM** → stored under the rendered history's key (step 7). |
| v2-F7 | `omission_ttl` (7 days) vs monotonic pruning ⇒ permanently unresolvable notices | **CONFIRM** → default `omission_ttl = None`; configurable; open question updated. |
| v2-F8 | `ChatStorage` pulled into normalization/counting but never compacted (`chat.py:202-210`, `:634-638`) | **CONFIRM** → counting gated on a configured `token_counter`; normalization stays always-on; `chat.py:638` stale `get_messages_for_api` call flagged to FEAT-524. |

Evidence spot-checked: `bots/base.py:988-1018` (binding before defaulting),
FEAT-524 worktree `bots/abstract.py:1895-1916` (`add_turn` then
`MessageAddedEvent`), worktree `storage/chat.py:634-638` (still calls
`get_messages_for_api`).

---

## Parallelism Assessment

- **Internal parallelism**: three clusters after the shared models land.
  Cluster 1 (memory core): `ToolInvocation`/`TokenCount`/`ContextBudget`
  models + normalization + token counting → template-method
  `add_turn`/`_store_turn` in the three backends → `from_ai_message`
  extension. Cluster 2 (compaction + render): `PrunePolicy` registry +
  built-ins → `compact_history` → `render_history` view/tool-text
  extension. Cluster 3 (recovery + scoping): `OmissionStore` ABC +
  backends → `current_memory_key_id` ContextVar → `read_omitted_content` function tool.
  Clusters 2 and 3 depend only on Cluster 1's models task. Bot integration
  (`bots/abstract.py`, `bots/base.py`, `data.py`, `voice.py`) is last and
  depends on all three.
- **Cross-feature independence**:
  - **FEAT-524** (in progress, 3/11 done): hard prerequisite — this
    feature edits `memory/abstract.py`, `memory/render.py`, `bots/abstract.py`
    and the four `bots/base.py` entry points that FEAT-524 M2/M3/M6 are
    rewriting. No worktree before FEAT-524 merges (C14).
  - **FEAT-523** `pep-420-llm-clients` (draft, waits for FEAT-524): moves
    client files; this feature touches **no** client file → independent.
  - **FEAT-380** (`tools/compression/`, done) and **FEAT-397** (client tool
    loops, done): consumed, not modified.
  - `observability/context.py` has no in-flight edits (the four active
    fireflies tasks TASK-2665..2669 cite `clients/base.py:1747` as a
    contract only).
- **Recommended isolation**: `per-spec` — one worktree branched from `dev`
  after the FEAT-524 merge, tasks sequential; Clusters 2 and 3 may be
  interleaved but not split into separate worktrees.
- **Rationale**: nearly every task edits `memory/abstract.py` or its tests,
  and the bot integration must land as one commit after all three
  clusters; separate worktrees would conflict on the same dataclass and
  the same four entry points.

---

## Open Questions

- [x] Regular feature or hotfix, and base branch? — *Owner: Jesus Lara*: feature on `dev`.
- [x] Relationship between the Stage 1 omission store and the FEAT-380 working-memory tee? — *Owner: Jesus Lara*: separate `OmissionStore` ABC; coexist (execution-time vs age triggers, different stores).
- [x] Where do Stage 0/0.5 run after FEAT-524's single writer? — *Owner: Jesus Lara (2026-09-04, v2)*: memory layer — concrete `ConversationMemory.add_turn()` normalizes + counts, then awaits abstract `_store_turn()`; covers the bot writer, `ChatStorage`, voice transcripts.
- [x] How does compaction plug into FEAT-524's `render_history`? — *Owner: Jesus Lara (v2)*: pure pre-pass `compact_history()` producing turn views + omissions; `render_history` accepts views and renders tool text; its FEAT-524 signature and plain-history output unchanged.
- [x] Where does tool-invocation / omission text go in a text-only, strictly alternating `HistoryMessage` list? — *Owner: Jesus Lara (v2)*: appended to the assistant message content as a fenced block; no new role.
- [x] Where does the estimate/provider pairing happen now that clients are memory-less? — *Owner: Jesus Lara (v2)*: inside `save_conversation_turn`, which calls `memory.report_usage()`; memory owns the EWMA.
- [x] Sequencing vs FEAT-524? — *Owner: Jesus Lara (v2)*: brainstorm + spec now against the FEAT-524 contract; `/sdd-task` and the worktree only after FEAT-524 merges to `dev`, with Codebase Contract re-verified.
- [x] Turn cap vs token budget? — *Owner: Jesus Lara (v2, superseded v3)*: first "budget replaces the cap"; **revised 2026-09-04**: tokens are the retention unit, turns the atomic unit — three-tier walk (verbatim ≤ `verbatim_tokens`, pruned ≤ high watermark, dropped) under a unified `max_turns=30` ceiling; `Chatbot.max_context_turns` stays a ceiling override (C10).
- [x] Defaults for the retention model? — *Owner: Jesus Lara (v3)*: `max_turns=30`, `verbatim_tokens=15_000`, `min_verbatim_turns=2`, fallback `window=32_000` when the model is unknown; `oversize_tool_tokens=2_000` proposed by the assistant, accepted in principle (number to confirm in spec).
- [x] Oversized tool results in recent turns? — *Owner: Jesus Lara (v3)*: prune big datasets from every turn but the newest even inside the verbatim tier; recovery via `read_omitted_content` and, when present, the FEAT-380 working-memory `_tee` key.
- [x] Who owns the `OmissionStore`? — *Owner: Jesus Lara (v2)*: the `ConversationMemory` backend (same connection; clear/delete cascade); bot reaches it via `memory.omission_store`.
- [x] How does `read_omitted_content` resolve its session key? — *Owner: Jesus Lara (v2)*: new ContextVar `current_memory_key_id` set by bots alongside user/session; the tool function is bot-agnostic.
- [x] Does `read_omitted_content` need an `AbstractToolkit`? — *Owner: Jesus Lara (2026-09-04, post-brainstorm review)*: **No.** It is an internal, LLM-only tool: one plain function registered with `ToolManager.register_tool(function=…)`, the `search_tools` meta-tool shape (`tools/manager.py:349-370`). It stays in the `ToolManager` (not attached to clients) because clients take schemas from `get_tool_schemas` and dispatch through `execute_tool`, which also keeps permissions, redaction, FEAT-380 compression and telemetry on the path and keeps clients memory-less per FEAT-524.
- [x] Opt-in or default-on? — *Owner: Jesus Lara (v1 opt-in, **revised v3 2026-09-04**)*: **default-on**, size-aware retention *and* pruning into the omission store, with a `ContextBudget` always present (`MODEL_WINDOWS` or 32k fallback); escape hatch `context_budget=False` / `PARROT_COMPACTION_DISABLED=1` restores FEAT-524's plain render (C3).
- [x] `keep_turns` / text-only retention (review v2 F2). — *Owner: Jesus Lara (v3)*: both closed by C10 — `keep_turns` is replaced by `verbatim_tokens` + `min_verbatim_turns`, and prose-only sessions are bounded by the verbatim window, the watermark and the `max_turns=30` ceiling.
- [x] **Write-time offload of oversized outputs.** — *Owner: Jesus Lara (2026-09-04, v3)*: **yes, in v1.** `add_turn()` moves any `ToolInvocation.output` above `oversize_tool_tokens` into the omission store at write time, leaving a short preview in the turn plus `omitted["output"] = om_…`. Lossless (same durable, content-addressed, deduplicated store), keeps Redis turn records small; recorded as a refinement of C2 ("raw" means *recoverable*, not *inline*). Precedent named by the author: the `ChatStorage` cold tier already stores and recovers per turn by `(user, agent, session, turn_id)` (`storage/chat.py` `_save_to_dynamodb` → `put_turn(..., turn_id=…)`, `query_turns`, `delete_turn`).
- [x] **Linking omissions to `turn_id`.** — *Owner: Jesus Lara (v3)*: **yes.** Secondary index `session_key → turn_id → [content_id]` (one Redis hash per session; dict/file equivalents) so an agent or operator can recover a whole turn's outputs by `turn_id` without knowing the hashes; `clear`/`delete` cascade covers it. FEAT-380 tee keys cannot serve this (not keyed by conversation `turn_id`, `tee.py:29-37`). `read_omitted_content` accepts either a `content_id` or a `turn_id` (returns the turn's outputs list in the latter case).
- [x] **`context_used` accounting.** Never rendered by `render_history`, costs storage only. — *Owner: Jesus Lara (2026-09-04, accepted as proposed)*: excluded from `TokenCount.total` and the budget sum; omitted on prune for storage hygiene.
- [x] **Stage 0 always-on vs gated.** — *Owner: Jesus Lara (2026-09-04, accepted as proposed)*: always-on for every writer (including the `ChatStorage` tier), memory-level `normalize=False` escape hatch.
- [x] **`ChatStorage` tier.** — *Owner: Jesus Lara (2026-09-04, accepted as proposed)*: normalized + counted, never compacted in v1; a budgeted `ChatStorage.get_context_for_agent` is a follow-up. Its stale `get_messages_for_api` call (`storage/chat.py:638`) belongs to FEAT-524.
- [x] **Tokenizer.** — *Owner: Jesus Lara (2026-09-04)*: **`o200k_base`** for the memory counter, name recorded per turn and in history metadata. Measured with `tiktoken` 0.9.0 on representative samples: identical counts to `cl100k_base` on English prose, Python source and compact JSON rows; 23% fewer tokens on Spanish prose, 33% fewer on Japanese — the 200k vocabulary is spent on non-English text, which makes the estimator's ratio to Claude/Gemini counts more stable across languages. **Follow-up (author):** the three existing `cl100k_base` sites — LLM wiki (`knowledge/wiki/store.py:202`), Skills (`skills/parsers.py:29`), PageIndex (`knowledge/pageindex/utils.py:53`) — also count non-English content and should migrate to `o200k_base` in a separate feature; not in this spec.
- [x] **`omission_ttl` default.** — *Owner: Jesus Lara (2026-09-04, accepted as proposed)*: `None` (no expiry) by default, matching the history key; configurable; notice text says "may have expired".
- [x] Token counting opt-in (review v2 F8)? — *Owner: Jesus Lara (v3, implied by default-on retention)*: **always-on** for every memory instance (`tiktoken` else heuristic); the `ChatStorage` tier is counted too.
- [x] **Tool-text format.** — *Owner: Jesus Lara (accepted in principle); exact schema: implementer (spec)*: appended `<tool-activity>` block, one line per invocation (name, status, elapsed, truncated input summary), omission notices inline, with a `Limit` for RAW turns so a chatty recent turn cannot blow the budget by itself.
- [x] **Per-tool `PrunePolicy` declaration.** — *Owner: Jesus Lara (2026-09-04, accepted as proposed)*: v1 = registry keyed by tool name (built-ins + `register_policy()`); a `prune_policy` attribute on `AbstractTool` is a follow-up.
- [x] **Stage 2 trigger surface.** — *Owner: Jesus Lara (2026-09-04, accepted as proposed)*: persist `stage2_needed` in `metadata.compaction` **and** emit a FEAT-176-style lifecycle event when it first flips, so operators see sessions that outgrew deterministic pruning.
