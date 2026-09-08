# Per-Turn Conversation Compaction

**FEAT-525** · shipped in **0.30.0** ·
rationale and full design: [`sdd/specs/per-turn-conversation-compaction.spec.md`](../../sdd/specs/per-turn-conversation-compaction.spec.md)

FEAT-524 gave every stateful bot round a single writer
(`AbstractBot.save_conversation_turn`) and a single pure renderer
(`render_history`). Two problems remained: `render_history` replays every
kept turn **verbatim**, bounded only by a turn count — five tool-heavy
turns can cost more than fifty chatty ones — and nothing in `parrot.memory`
knew what a turn *cost*, or remembered a tool call's inputs, outputs, or
errors beyond its name. This feature adds a deterministic (no LLM call
anywhere in it) three-tier retention pass, a token-aware write path, and a
lossless recovery mechanism for anything it prunes.

---

## The three tiers

Every budgeted round walks the kept turns **newest → oldest**, classifying
each one:

1. **Verbatim (RAW)** — full text, full tool activity (via a compact
   `<tool-activity>` block), while the cumulative calibrated token count
   stays within `verbatim_tokens` *and* the high-watermark budget, or
   while fewer than `min_verbatim_turns` have been kept so far (a floor,
   not a ceiling — the newest turn is always verbatim even if it alone
   exceeds every threshold).
2. **Pruned (PRUNED)** — user message and assistant text stay **intact**;
   each tool invocation's input/output is replaced by a one-line
   `<tool-output-omitted .../>` notice, while the cumulative size stays
   within the high watermark.
3. **Dropped** — beyond that. Tiers are contiguous (once pruning starts,
   nothing newer-processed-later can go back to RAW), and a drop sets
   `stage2_needed=True` — the reserved trigger for a future LLM-summary
   stage (out of scope here).

**Oversize exception**: any tool output whose token count exceeds
`oversize_tool_tokens` (default 2,000) is pruned to a notice in *every*
turn but the newest — even inside the verbatim tier. A turn with an
oversized invocation can never be classified RAW; that is what keeps a
50-turn chat session and a 10-turn database session from needing
different tuning.

**Worked shapes** (`ContextBudget(window=32_000)` defaults — see
`tests/unit/memory/compaction/test_compact.py`):

- **50 chatty turns**, ~150 tokens each, no tool calls → all 30 kept
  turns (ceiling `max_turns=30`) render **RAW**; zero omissions.
- **10 database turns**, each carrying one ~30,000-character (oversized)
  query result → only the **newest renders RAW**; the other 9 render
  **PRUNED**, each with a `<tool-output-omitted>` notice and one
  `Omission`.

A persisted `boundary_turn_id` (see [Operator metadata](#operator-metadata))
makes this **monotonic**: a turn that once rendered PRUNED never renders
RAW again for that history, even if the budget would technically allow it.

---

## Rendered text formats

Appended to the assistant message content — no new `HistoryMessage` role,
no provider-native `tool_use`/`tool_result` blocks (spec G8):

```
# RAW view
<tool-activity>
- query_database ok 1.2s in={"sql":"SELECT * FROM sales WHERE …"} out=3 rows: [{"id":1,…}] …(+48,213 chars)
- write_file ok 0.1s in={"path":"report.md"} out=written 2,140 bytes
- fetch_url error 3.0s in={"url":"https://…"} error=HTTPError 503 (condensed)
</tool-activity>

# PRUNED view — same wrapper, one notice per invocation
<tool-activity>
- query_database ok 1.2s in={"sql":"SELECT * FROM sales …"} <tool-output-omitted tool="query_database" chars="48213" id="om_3f9a1c2b7d4e5f60" wm="__tee__:query_database:…"/>
- fetch_url error 3.0s in={"url":"https://…"} error=HTTPError 503 (condensed)
</tool-activity>
Omitted content can be recovered with read_omitted_content(content_id) or read_omitted_content(turn_id="…").
```

Errors are **never** omitted (G7) — every built-in `PrunePolicy` keeps
`error=…` verbatim, condensed only by Stage 0 rule 5 (traceback
condensation). A turn with no tool invocations renders an empty suffix in
either tier, so text-only histories render byte-identically to FEAT-524's
plain `render_history`.

---

## The write path — always on

Every writer (a bot round, the `ChatStorage` cold tier, voice transcripts)
goes through the same template method:

```python
# parrot/memory/abstract.py
class ConversationMemory(ABC):
    async def add_turn(self, user_id, session_id, turn, chatbot_id=None, *,
                       compaction: Optional[CompactionCommit] = None) -> None:
        ...  # CONCRETE — normalize → count → offload → _store_turn (one write)

    @abstractmethod
    async def _store_turn(self, user_id, session_id, turn, chatbot_id=None, *,
                          compaction_state: Optional[Dict[str, Any]] = None) -> None: ...
```

`add_turn` (concrete, hard cut — no subclass overrides it anymore):

1. **Stage 0 — normalize** (`normalize=True` by default, per-instance
   escape hatch): NFC, strip ANSI/C0, trailing-whitespace/blank-run
   cleanup, canonical JSON (`orjson`, sorted keys) for JSON-shaped text
   and every `ToolInvocation.input`, traceback condensation for errors.
   Pure, stdlib + `orjson` only.
2. **Stage 0.5 — count** (always on, never gated): `tiktoken`'s
   `o200k_base` encoding when importable and loadable, else a heuristic
   (`bytes // 4`, named `"heuristic"`). `context_used` is deliberately
   excluded from every count.
3. **Write-time offload**: any `ToolInvocation.output` above
   `oversize_tool_tokens` is moved to the memory's `OmissionStore`
   (content-addressed: `"om_" + blake2b(content, 8).hexdigest()`),
   leaving a ≤ 200-char preview plus `omitted["output"] = "om_…"` in the
   stored turn. Idempotent — the same content always gets the same id.
4. `schema_version = 2`; if a `CompactionCommit` was passed, the EWMA
   calibration/boundary/`stage2_needed` state is folded in via
   `apply_commit` and persisted **in the same write** as the turn.

Storage always writes the turn `RAW` — a pruned form is **never**
persisted (G2). The only persisted compaction state is
`history.metadata["compaction"]`.

### Implementing a custom `ConversationMemory` backend

Implement `_store_turn(user_id, session_id, turn, chatbot_id=None, *,
compaction_state=None)`, persisting `turn` **and** (when given)
`history.metadata["compaction"] = compaction_state` in one write. Build
your own `OmissionStore` (or accept the `InMemoryOmissionStore` fallback)
and cascade `omission_store.clear(self.omission_key(...))` from your
`clear_history`/`delete_history`. See `memory/mem.py` (in-memory),
`memory/file.py` (`aiofiles`), and `memory/redis.py` (one `hset` per
write, `metadata` read-modify-written alongside `turns`) for the three
shipped implementations.

---

## The read path — budgeted by default

```python
# parrot/bots/abstract.py — AbstractBot
async def render_context_history(
    self, history: Optional[ConversationHistory]
) -> Tuple[List[HistoryMessage], Optional[CompactionResult]]: ...
```

With an active `context_budget`, this runs the pure
`compact_history(history, budget, ...)` pre-pass, flushes its omissions
(`await memory.omission_store.put_many(...)`), and renders the resulting
`TurnView`s via `render_history(views, current_chatbot_id=...)`. **A
flush failure degrades to the plain FEAT-524 render for that call only**
— logged at WARNING, boundary left untouched, no commit built. Every
`BaseBot`/`PandasAgent` entry point (`conversation`, `invoke`, `ask`,
`ask_stream`) calls this instead of `render_history` directly; the
resulting `CompactionCommit` (via `estimate_prompt_tokens` +
`build_compaction_commit`) is passed into
`save_conversation_turn(..., compaction=commit)` so the turn, the new
boundary, and the calibration update land in one backend write.
`ask_stream`'s single (completed-or-partial) save site always passes
`compaction=None` — there is no rendered-prompt estimate to pair for a
stream that may have died mid-way.

`VoiceBot.ask` renders through the same budgeted path but has no save
site of its own (no rendered prompt to pair for calibration), so its
`CompactionResult` is discarded after the omission flush.

---

## The kill switch

```python
Agent(..., context_budget=False)          # per-instance
```
```bash
PARROT_COMPACTION_DISABLED=1              # process-wide (mirrors FEAT-380's
                                           # PARROT_COMPRESSION_DISABLED — a
                                           # different variable for a different
                                           # feature; do not confuse the two)
```

Either one makes `AbstractBot.context_budget` resolve to `None`, and every
render/save call takes FEAT-524's plain path — **byte-identical** output,
verified by `test_kill_switch_byte_equality` across all four `BaseBot`
entry points.

---

## Tuning

```python
Agent(
    ...,
    context_budget=ContextBudget(
        window=200_000,          # else MODEL_WINDOWS[prefix] or the 32k fallback
        verbatim_tokens=20_000,  # default 15_000
        min_verbatim_turns=2,    # default 2 — floor, not ceiling
        oversize_tool_tokens=2_000,
        max_turns=30,            # unified ceiling for AbstractBot AND Chatbot
    ),
)
Chatbot(..., max_context_turns=12)  # ceiling OVERRIDE only — the retention
                                     # tier assignment is still token-driven
```

`ContextBudget.max_turns` (default **30**) replaced the old, disjoint
defaults (`AbstractBot` 50, `Chatbot` 5 from the DB). `max_context_turns`
is `None` by default on every bot now — `None` means "use the budget's
ceiling"; an explicit constructor kwarg *or* a `Chatbot` DB record value
overrides it. **Behavior change worth knowing**: a `Chatbot` DB record
that never set `max_context_turns` used to mean "5-turn verbatim replay";
it now means "30-turn ceiling under a token budget" — strictly more
context, token-bounded rather than count-bounded.

---

## Recovering omitted content

Two independent recovery tools coexist by design — each notice names the
one to use:

- **`read_omitted_content(content_id=None, turn_id=None)`** (this
  feature) — a plain function bound to the bot's memory and registered
  like the `search_tools` meta-tool (`ToolManager.register_tool(function=…)`,
  no `AbstractToolkit`). Resolves its session key from three ContextVars
  (`current_memory_key_id`, `current_user_id`, `current_session_id`,
  bound *after* the entry point defaults `user_id`/`session_id` — the
  "binding-order hazard" this feature closed) and **fails closed**
  (`UNAVAILABLE_MESSAGE`) on any `None`, never touching the store. A
  `content_id` returns the exact original bytes or
  `"...unknown or may have expired — re-run the tool..."`; a `turn_id`
  returns every block omitted from that turn. Excluded from
  `rank_tools`/`search_tools` results (a small `_INTERNAL_TOOL_NAMES`
  frozenset in `tools/manager.py`), but fully callable and present in
  `get_tool_schemas()`/`list_tools()`, and it survives `ToolManager.clone()`
  (that gate keys only on `search_tools`).
- **`wm_get_result`** (FEAT-380, `WorkingMemoryToolkit`) — a
  process-local, execution-time working-memory tee, unrelated to
  conversation history. When a tool result carries a FEAT-380 `_tee`
  pointer, its notice also prints `wm="…"` as a best-effort hint; the
  omission store (this feature) is the one that survives a restart.

---

## Operator metadata

`history.metadata["compaction"]` is the **only** persisted compaction
state:

```python
{
    "tokenizer": "o200k_base",       # or "heuristic"
    "calibration": 1.05,             # EWMA (α=0.2, clamped [0.5, 2.0]) of
                                      # provider_prompt_tokens / prompt_estimate
    "samples": 12,
    "boundary_turn_id": "t-abc123",  # monotonic — turns at/before it always PRUNED
    "stage2_needed": false,
    "updated_at": "2026-09-04T12:00:00+00:00",
}
```

`Stage2CompactionNeededEvent` (`parrot.core.events.lifecycle.events`)
fires exactly once per session, on the first `False → True` flip of
`stage2_needed`, carrying `history_estimate`, `available`, and
`dropped_turns` — the reserved hook for a future Stage 2 (LLM summary
turns; out of scope here).

---

## Non-goals (v1)

- **Stage 2** (LLM summary turns) — only the hook points
  (`stage2_needed`, `TurnState.SUMMARIZED`, `Stage2CompactionNeededEvent`)
  are reserved.
- **`ChatStorage`** (`storage/chat.py`, `key_prefix="chat"`) — normalized
  and counted like any writer, but **never compacted**; a budgeted
  `ChatStorage.get_context_for_agent` is a follow-up.
- **`ContextAssembler`** (`memory/unified/context.py`) keeps
  `len(text) // 4`.
- Migrating the three existing `cl100k_base` sites
  (`skills/parsers.py`, `knowledge/wiki/store.py`,
  `knowledge/pageindex/utils.py`) to `o200k_base` — a separate feature.
