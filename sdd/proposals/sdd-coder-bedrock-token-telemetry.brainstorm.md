---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Empirical Token-Budget Sizing for sdd-coder Bedrock Seats

**Date**: 2026-09-12
**Author**: Jesus Lara / Claude
**Status**: accepted
**Recommended Option**: Option B (with Option A as a zero-cost day-0 step)

---

## Problem Statement

FEAT-550 gave `AbstractClient`/`AbstractBot` a cumulative per-question
`token_budget` covering Bedrock Converse and Bedrock Mantle. FEAT-549 runs the
`sdd-coder` agent on those same Mantle seats (`qwen` →
`qwen.qwen3-coder-480b-a35b-instruct`). **Nobody can pick a number for
`token_budget` on a coding seat, because nothing measures what a coding attempt
actually consumes.**

A coding attempt is not a chat question. It is a loop of up to
`LLMCodeDispatchProfile.max_turns` rounds (default 24, configured higher for
coder profiles), each one re-sending the full history — so consumption grows
super-linearly with turns and is dominated by *input* tokens, not output. The
right ceiling is therefore a property of the *task*, not of the model.

What exists today falls short in a specific way:

- Per-attempt usage **is** collected: `AttemptTelemetryCollector`
  (`sdd_coder/engine.py:91-136`) folds the `dispatch.completed` payload built by
  `LLMCodeDispatcher._completion_usage_payload` (`dispatchers/llm.py:584-617`)
  into `AttemptRecord.usage` (`sdd_coder/models.py:114-125`).
- It **is** written to disk: `SddCoderEngine._journal`
  (`sdd_coder/engine.py:472-488`) snapshots the whole `CoderJob` — including
  `tasks[*].attempts[*].usage` — to `<worktree>/.sdd-coder/jobs/<job_id>.json`.

But that journal **dies with the feature worktree** (`/sdd-done` runs
`git worktree remove`), is keyed by job rather than by task, carries no per-turn
detail, no task-size correlate, no outcome-linked view, and — most importantly —
no reading from the FEAT-550 ledger, so it cannot tell us how wrong the
`estimated` admission mode is. It is a debugging snapshot, not a longitudinal
dataset.

**Who is affected**: the operator configuring the `sdd-coder` roster; the
`sdd-worker` orchestrator that would surface a budget-exhausted attempt; and
anyone who wants to switch FEAT-550 enforcement on for a coding seat.

**Why now**: FEAT-550 landed on 2026-09-11 with `token_budget` defaulting to
`None` (disabled). Turning it on for a coder seat without data is guesswork, and
the failure mode is asymmetric: a mis-sized ceiling on a chat answer truncates
text, while a mis-sized ceiling on a coder leaves a **half-finished git
worktree** that `sdd-worker` must then adopt or discard.

---

## Constraints & Requirements

- **No behavior change by default.** Instrumentation is opt-in via an
  environment variable; a normal run must not route through the budgeted funnel.
- **One change, two seats.** The instrumentation belongs in
  `LLMCodeDispatcher`, so both in-process seats — `nova` (Mantle/Bedrock) and
  `google-compat` (Gemini) — are measured by the same code. The `codex` (CLI)
  and `haiku` (native Claude Code sub-agent) seats are **out of scope**: their
  usage arrives by a different path.
- **Shadow mode must not change what is sent.** The budgeted funnel overwrites
  the output cap with `reservation.output_cap`
  (`clients/openai_base.py:388`). With a deliberately huge ceiling this must
  resolve to exactly `profile.max_tokens` — a shadow run that silently shrinks
  the output cap would corrupt the very measurement it exists to take.
- **Counters only, never content.** No prompt text, no tool arguments, no
  diff bodies in the dataset — token counts, ids, timings and outcomes.
- **The dataset must outlive the worktree.** It is written to the **main
  repository's** `artifacts/logs/` (git-ignored at `.gitignore:283`, so it stays
  local unless the operator explicitly `git add -f`s a curated snapshot), never
  inside the ephemeral sub-worktree.
- **Append-only and concurrency-safe.** Up to `len(roster)` seats run
  concurrently inside one MCP-server process. Partitioning the dataset **one
  file per feature** removes the cross-process case entirely — a second
  `sdd-worker` in another terminal is working another feature, hence another
  file — leaving only single-process asyncio appends, handled with single-line
  `O_APPEND` writes and no read-modify-write.
- **Telemetry must never break a dispatch.** Every failure swallowed and logged
  at DEBUG — the same discipline `_apply_to_session_host`
  (`dispatchers/_shared.py:91-124`) already applies to its own shim.
- **Failed attempts are data too.** `failed` and `fidelity_violation` attempts
  must be recorded and distinguishable, because a ceiling is sized on
  *successful* attempts while the failures characterise the degenerate tail.
- **Zero new runtime dependencies.** `tiktoken` is already pulled in by the
  FEAT-550 adapters; `pandas` is already a project dependency for the analysis
  script.

---

## Options Explored

### Option A: Journal Harvester — read what is already on disk

A read-only script walks every `<worktree>/.sdd-coder/jobs/*.json` that still
exists (plus any copies preserved before worktree removal), validates each into
`CoderJob`, flattens `tasks[*].attempts[*]` into rows, and computes percentiles.
No change whatsoever to the dispatch path.

✅ **Pros:**
- Zero risk: nothing in the coding loop changes.
- Produces a first sample *today*, from runs that already happened.
- Tiny effort — one script, one Pydantic model already defined.

❌ **Cons:**
- **The sample is biased and perishable**: only features whose worktrees have
  not been removed are represented, so long-finished (i.e. successful) features
  are exactly the ones missing.
- No per-turn series — cannot distinguish "big task" from "degenerate loop".
- No `BudgetReport`, so no way to calibrate the `estimated` admission error or
  validate that the FEAT-550 adapter counts what the provider bills.
- No task-size correlate, so the ceiling can only be a single global number.
- `_completion_usage_payload` omits cache and cost fields, so the rows are
  `input`/`output`/`num_turns`/`duration_ms` and nothing else.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Re-validate journal JSON into `CoderJob` | already a core dependency |
| `pandas` | Percentiles and grouping | already a project dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:472-488` — `_journal` defines the file layout to read.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:114-125` — `AttemptRecord`, the row shape.

---

### Option B: Shadow Budget Scope + Attempt Telemetry Sink

Four parts, each small:

1. **Bind one root `BudgetScope` around the whole turn loop** of
   `LLMCodeDispatcher.dispatch`, opt-in by env var, with a ceiling large enough
   that it can never deny and an **absolute** `final_answer_reserve` of
   `2 × profile.max_tokens` rather than the 0.15 fractional default. Because
   `OpenAIBaseClient._chat_completion:262-264` checks
   `current_budget_scope()` on every wire call, every turn of the loop is then
   reserved and reconciled by the ledger — **the same machinery that would later
   enforce is the one that measures**. One attempt = one "question" = one
   ledger, which is exactly the semantic a coding task needs.
2. **Widen the completion payload**: `_completion_usage_payload` gains a compact
   per-turn series (input/output per round, already available from
   `_extract_usage` at `llm.py:331-333`) and, when a scope is bound, the
   `BudgetReport` dump from `scope.ledger.report()`.
3. **A telemetry sink in `SddCoderEngine`** writes two JSONL lines to
   `artifacts/logs/sdd-coder-usage/<FEAT-ID>.jsonl`: an `attempt` line when the attempt
   ends (from `AttemptRecord`, so the measurement is durable even if the server
   dies mid-consolidation) and an `outcome` line at consolidation, joined by
   `(feature_id, task_id, attempt)`.
4. **An analysis script** reads the JSONL, joins the two line kinds, filters to
   `merged` attempts, and emits p50/p95/p99 per **seat × task-size bucket**
   (bucket derived from `len(parse_task_files(task_md))`,
   `sdd_coder/fidelity.py:25`), plus a suggested `token_budget` per segment.

✅ **Pros:**
- Measures the exact quantity that will later be enforced, with the exact code
  that will enforce it — no parallel accounting implementation to drift.
- Records **both** sources side by side: the provider's own accumulated
  `CompletionUsage` and the ledger's estimated accounting. Their difference is
  the calibration signal for the safety margin, and the evidence for or against
  qualifying `budget_mode="strict"` (FEAT-550 §2.5).
- The per-turn series distinguishes a genuinely large task from a loop that
  wandered — which decides whether the answer is "raise the ceiling" or
  "compact the history / lower `max_turns`".
- One change covers two seats; the dataset survives worktree removal.
- Exercises the FEAT-550 Mantle adapter against real, long, tool-heavy
  workloads before anyone depends on it for enforcement.

❌ **Cons:**
- Touches the dispatch critical path. Mitigated by opt-in activation and
  swallowed failures, but it is a real difference between an instrumented and a
  normal run, and must be characterised rather than assumed away.
- **Measurement overhead grows quadratically over the loop, but the constant is
  small.** `MantleBudgetAdapter.count_input` (`amazon/budget.py:300-347`)
  serializes the whole wire body to canonical JSON and tokenizes it with
  `tiktoken` on *every physical attempt*. Measured on 2026-09-12
  (`artifacts/logs/sdd-coder-count-input-overhead-20260912.md`): 4.9 ms at turn 1,
  65 ms at turn 60, **2.77 s total for a 60-turn attempt reaching 148k tokens of
  history** — 0.1-0.5% of attempt wall-clock against 10-60 s network turns. Not a
  reason to restrict the scope to campaigns. The residual caveat is that
  `count_input` is declared `async` but counts synchronously (`budget.py:345`),
  so each seat's pass blocks the shared event loop; ~11 s per 4-seat wave, and a
  one-line `asyncio.to_thread` removes it if it ever matters.
- The `output_cap` overwrite (`openai_base.py:388`) means a mis-set shadow
  ceiling would silently shrink `max_tokens`; needs an explicit guard.
- In-process concurrent appends need `O_APPEND` discipline and a line small
  enough to be written atomically (the cross-process case is designed away by
  the per-feature partitioning).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tiktoken` | Input estimation inside the ledger | already used by the FEAT-550 adapters (`amazon/budget.py:44-60`) |
| `pandas` | Percentiles per segment | already a project dependency |
| `pydantic` | Row models for the JSONL lines | already a core dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/clients/budget_scope.py:131` — `BudgetRegistry.create(policy)`, the root-scope factory.
- `packages/ai-parrot/src/parrot/clients/budget_scope.py:80-107` — `BudgetScope.__aenter__/__aexit__`, which binds the ContextVar and closes the ledger.
- `packages/ai-parrot/src/parrot/clients/budget.py:280-283` — `QuestionBudget.report()`.
- `packages/ai-parrot/src/parrot/clients/openai_base.py:262-264` — the branch that makes the whole thing work without touching the client.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:584-617` — `_completion_usage_payload`, the payload to widen.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:91-136` — `AttemptTelemetryCollector`, which already receives everything added to that payload.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py:25` — `parse_task_files`, the task-size correlate.

---

### Option C: Lifecycle-Event Subscriber (reuse FEAT-397)

Attach a subscriber to the client's `EventRegistry`. FEAT-397 already defines
`ClientRoundEvent` (`core/events/lifecycle/events/client.py:189`) with
round number, per-round tokens and tool names, and `LLMCodeDispatcher` already
emits one per turn via `_safe_emit_round_event` (`llm.py:333-343`). The
subscriber writes the JSONL; the dispatcher is not modified at all.

✅ **Pros:**
- Per-round series for free, from plumbing built for exactly this purpose.
- The most decoupled option: telemetry lives entirely outside the coding loop.
- No budgeted funnel on the critical path, so no tokenizer overhead.

❌ **Cons:**
- **Measures only the easy half.** Without a bound scope there is no
  `BudgetReport`, so the estimation error — the thing that sets the safety
  margin and decides the `strict` question — stays invisible.
- The event carries `model`/`round_number`/`usage`/`tool_calls` but not
  `task_id`/`attempt`; identity must be threaded in out of band
  (the dispatch labels at `sdd_coder/engine.py:508-518` carry it, but the
  client-level event does not).
- Duplicates accounting that FEAT-550 already performs, creating two sources of
  truth for the same number with no way to reconcile them.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Event models | `ClientRoundEvent` already defined |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py:189-210` — `ClientRoundEvent`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:333-343` — the existing per-round emission point.

---

### Option D: Budget Elasticity Experiment (unconventional)

Instead of measuring consumption and deriving a ceiling from it, deliberately
run the *same* tasks at several different **real** ceilings and measure the
merged-rate at each. This answers a different and arguably better question: not
"what ceiling never interrupts?" but "what ceiling maximises merged tasks per
token?".

The hypothesis worth testing is that part of a coder's consumption is not
essential work but wandering, and that a tight ceiling — combined with FEAT-550's
tools-disabled finalization, which is functionally the same move as the existing
`max_turns` salvage at `llm.py:800-843` — produces *more* merges per token, not
fewer.

✅ **Pros:**
- Measures elasticity, which is what "ideal size" actually means.
- Would settle whether FEAT-550 finalization and the `max_turns` salvage should
  be unified into one closing mechanism instead of two.

❌ **Cons:**
- Burns real runs and real spend; needs each task repeated at several ceilings
  to control for task difficulty.
- Requires Option B's dataset anyway to interpret its own results.
- Not a shippable capability — an experiment, best run *after* B lands.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | — | reuses Option B's dataset and roster configuration |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:800-843` — the existing forced-`final_output` salvage, the natural counterpart of FEAT-550 finalization.

---

## Recommendation

**Option B** is recommended, with **Option A run first as a free day-0 step** and
**Option D recorded as the follow-up experiment** once a dataset exists.

The reasoning turns on one fact the other options cannot reach: the number we
need is not "how many tokens did the provider bill" — Option A and Option C both
give that — but "how many tokens will *the ledger that enforces the ceiling*
count, and how wrong is it". FEAT-550 admits requests in `estimated` mode
(`MantleBudgetAdapter` has no `strict` qualification yet,
`amazon/nova/mantle.py:87-89`), so the enforced quantity is a local `tiktoken`
estimate, not the provider's number. Sizing a ceiling against the provider's
number and then enforcing against an estimate would bake the estimation error
straight into the failure rate. Option B measures both and records their
difference; that difference *is* the safety margin.

The trade accepted is real and worth naming: Option B puts the budgeted funnel —
including a full-payload tokenizer pass per turn — on the coding loop's critical
path during a measurement campaign. That is why activation is opt-in and why
characterising the overhead is an acceptance criterion rather than a footnote.
Option C is genuinely more decoupled and would be the right answer if we only
wanted the provider's totals; it is rejected because it leaves the estimation
error unmeasured, which is precisely the gap.

Option A is not an alternative so much as a free head start: it costs a single
read-only script and yields a first sample from journals that already exist,
which is enough to sanity-check the order of magnitude before B is written.

---

## Feature Description

### User-Facing Behavior

The operator enables a measurement campaign with two environment variables read
through `navconfig` from `env/.env` (the convention the `sdd-coder` seats already
follow for their credentials):

- `PARROT_SDD_CODER_TELEMETRY=1` — turn on the JSONL sink.
- `PARROT_SDD_CODER_SHADOW_BUDGET=<int>` — optional ceiling for the shadow
  scope; omitted means "instrument, but bind no scope" (provider totals only).

Nothing else changes. `sdd-worker` runs exactly as documented in
`docs/dev_loop/sdd-coder-orchestrator.md`; the Completion Notes and the per-model
summary table keep the shape they have. In the background,
`artifacts/logs/sdd-coder-usage/<FEAT-ID>.jsonl` grows by two lines per attempt.

When enough attempts have accumulated, the operator runs the analysis script and
gets a table: for each seat and each task-size bucket, the number of merged
attempts, p50/p95/p99 of total tokens, the median estimation error, and a
suggested `token_budget`. Percentiles are always printed, but a segment with
fewer than **12 merged attempts** is marked unreliable and gets **no** suggested
ceiling: a p95 over five samples is noise wearing the costume of a number.

### Internal Behavior

**Instrumentation path.** `LLMCodeDispatcher.dispatch`, when telemetry is
enabled and a shadow ceiling is configured, creates a root scope from the
process-wide registry and holds it open around the entire turn loop. Every
`_chat_completion` inside that loop sees the scope in the ContextVar and routes
through the budgeted funnel for any client exposing a `budget_adapter_factory` —
today, Mantle. The loop keeps accumulating `CompletionUsage` exactly as it does
now; on exit it reads the ledger's report and folds both into the
`dispatch.completed` payload, alongside a per-turn array of
`(round, input, output)` triples. `AttemptTelemetryCollector` needs no change in
principle — it already copies known fields off the completion action — but its
field list widens to carry the new ones through to `AttemptRecord`.

**Persistence path.** The sink appends one `attempt` line as soon as
`_run_attempt` returns, carrying identity (feature, task, attempt, seat, backend,
model), timings, turn count, both accountings and the per-turn series. At
consolidation, `_consolidate`/`merge` appends one `outcome` line carrying the
same key plus the outcome, the declared-file count and any fidelity or conflict
detail. The two are joined at analysis time. Splitting them is what makes a
crashed MCP server cost one outcome line instead of a whole measurement.

**Analysis path.** The script globs `artifacts/logs/sdd-coder-usage/*.jsonl`,
joins the two line kinds, filters to `merged`, buckets by declared file count,
and reports percentiles per segment, treating estimation error as a distribution
rather than a constant. The suggested ceiling for a segment is derived from its
p95 plus a margin taken from that segment's own measured estimation error, and is
withheld below the 12-attempt threshold.

### Edge Cases & Error Handling

- **Registry exhausted** (`BudgetRegistryFull`, `budget_scope.py:136`): log
  once, run the attempt with no scope, record the row with the ledger fields
  absent. Never fail the dispatch for a measurement.
- **Attempt crashes before the loop starts** (worktree creation or dispatcher
  construction, which `engine.py:536-546` deliberately brings inside the `try`):
  the `attempt` line is written with zero turns and the error string.
- **Non-instrumented seats** (`codex`, `haiku`): no rows at all, rather than rows
  with null token fields that would silently skew percentiles.
- **Scope bound but client has no adapter** (the `google-compat` seat): the
  funnel is simply not taken (`openai_base.py:263` requires both), so the row
  carries provider totals and no ledger report. This is the intended comparison
  baseline, not a failure.
- **Fractional reserve against a huge ceiling**: `final_answer_reserve=0.15`
  against an 800k shadow ceiling would immobilise ~120k tokens to protect a
  `DevelopmentOutput` JSON of roughly 1k. The shadow policy therefore passes an
  absolute reserve (`2 × max_tokens`), which FEAT-550 already supports
  (`TokenBudgetPolicy.final_answer_reserve`, `models/token_budget.py:32`, int =
  absolute tokens).
- **Shadow ceiling too low**: the ledger would begin denying and shrink the
  output cap. Guarded by refusing to bind a shadow scope whose ceiling is not
  comfortably above `max_turns × max_tokens`, and by asserting the resolved
  `output_cap` still equals `profile.max_tokens`.
- **Concurrent appends** from parallel seats in one process and from a second
  `sdd-worker` process: single `O_APPEND` write per line, one line per write, no
  rewriting.
- **Orphan `outcome` line with no `attempt` line** (server restarted between the
  two): the analysis reports it as an incomplete pair and excludes it, rather
  than treating missing tokens as zero.
- **Budget exhaustion during a real (non-shadow) run**, once enforcement is
  eventually enabled: out of scope for this feature, but the dataset must be able
  to represent it — hence recording `budget_exhausted` and `overrun_tokens` from
  the report rather than only the totals.

---

## Capabilities

### New Capabilities

- `sdd-coder-token-telemetry`: per-attempt, durable, outcome-linked token
  accounting for the in-process coding seats, plus the analysis that turns it
  into a recommended `token_budget`.

### Modified Capabilities

- `token-budget-bedrock` (FEAT-550) — gains its first long-running, tool-heavy
  consumer and an empirical basis for choosing a ceiling; no contract change.
- `sdd-worker-subagents` (FEAT-549) — `AttemptRecord` widens and the engine
  gains a telemetry sink; no change to the MCP tool contracts.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/dev_loop/dispatchers/llm.py` | modifies | Optional scope binding around the turn loop; widened completion payload |
| `parrot/flows/dev_loop/dispatchers/nova.py` | depends on | Inherits the change; no local edit expected |
| `parrot/flows/dev_loop/sdd_coder/engine.py` | extends | Telemetry sink at attempt end and at consolidation |
| `parrot/flows/dev_loop/sdd_coder/models.py` | modifies | `AttemptRecord` gains the ledger fields and the per-turn series |
| `parrot/clients/budget_scope.py` | depends on | Uses `get_default_registry()` / `BudgetRegistry.create`; no change |
| `parrot/clients/openai_base.py` | depends on | Relies on the existing scope branch; no change |
| `packages/ai-parrot-client-amazon/.../budget.py` | depends on | `MantleBudgetAdapter` exercised under long loops for the first time |
| `scripts/` | new file | Analysis script producing the per-segment recommendation |
| `artifacts/logs/` | new artifact | `sdd-coder-usage.jsonl`, git-ignored by `.gitignore:283` |
| `docs/dev_loop/sdd-coder-orchestrator.md` | modifies | "Telemetry" section documents the campaign workflow |

No breaking changes. No new runtime dependency. Nothing changes for a run that
does not set the environment variables.

---

## Code Context

### User-Provided Code

None — the user described the problem in prose; every snippet below was read
from the repository during Step 4.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:91
class AttemptTelemetryCollector:
    def __init__(self, *, attempt: int, seat: RosterSeat) -> None: ...       # line 101
    def apply(self, action: Any, origin: Any = None) -> None: ...            # line 108
    def record(self) -> AttemptRecord: ...                                   # line 125
    # apply() copies ONLY these fields off a DispatchCompleted action (lines 113-123):
    #   input_tokens, output_tokens, cache_creation_input_tokens,
    #   cache_read_input_tokens, total_cost_usd, num_turns, duration_ms

# From packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:114
class AttemptRecord(BaseModel):
    attempt: int = Field(..., ge=1, le=3)     # line 117
    seat_label: str                            # line 118
    backend: str = ""                          # line 119
    model: str = ""                            # line 120
    started_at: str                            # line 121
    ended_at: str = ""                         # line 122
    duration_s: float = 0.0                    # line 123
    usage: Dict[str, Any] = Field(default_factory=dict)  # line 124
    error: str = ""                            # line 125

# From packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:472
async def _journal(self, worktree: str, job: CoderJob) -> None:
    """Write-only snapshot: <worktree>/.sdd-coder/jobs/<job_id>.json"""
    # callers: engine.py:646, :651, :661

# From packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:520
async def _run_attempt(
    self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *, attempt: int, job_id: str
) -> Tuple[AttemptRecord, Optional[DevelopmentOutput], str, SubWorktreeManager, str, str]: ...
# returns collector.record() at line 586 — the natural `attempt`-line write point

# From packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py:25
def parse_task_files(task_md: str) -> List[str]:
    """Paths listed under '## Files to Create / Modify'."""

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:584
@staticmethod
def _completion_usage_payload(
    accumulated: Optional[CompletionUsage], *, turns: int, started_at: float
) -> Dict[str, Any]: ...
# emits ONLY: num_turns, duration_ms, and (when accumulated) input_tokens/output_tokens

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:1089
@staticmethod
def _extract_usage(response: Any) -> tuple[Optional[CompletionUsage], Optional[Dict[str, Any]]]: ...
# per-round usage, accumulated at llm.py:331-333

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:973
async def _chat_completion(self, *, client: Any, model: str, messages: List[Dict[str, Any]], args: Dict[str, Any]) -> Any:
    method = getattr(client, "_chat_completion", None)   # line 981 — calls the CLIENT's funnel

# From packages/ai-parrot/src/parrot/clients/openai_base.py:228
async def _chat_completion(self, model: str, messages: Any, use_tools: bool = False, stream: bool = False, **kwargs) -> Any:
    _scope = current_budget_scope()                                        # line 262
    if _scope is not None and self.budget_adapter_factory is not None:     # line 263
        return await self._chat_completion_budgeted(...)                   # line 264
# _chat_completion_budgeted (line 334) overwrites the output cap at line 388:
#     kwargs[cap_key] = reservation.output_cap
# and uses an SDK view with max_retries=0 (line 349) while keeping tenacity retries (line 363-369)

# From packages/ai-parrot/src/parrot/clients/budget_scope.py:120
class BudgetRegistry:
    async def create(self, policy: TokenBudgetPolicy) -> BudgetScope: ...   # line 131
class BudgetScope:                                                          # line 38
    async def __aenter__(self) -> "BudgetScope": ...                        # line 80 (binds the ContextVar)
    async def __aexit__(self, exc_type, exc, tb) -> None: ...               # line 89 (closes the ledger on a root)
def current_budget_scope() -> Optional["BudgetScope"]: ...                  # line 33
def get_default_registry() -> BudgetRegistry: ...                           # line 297

# From packages/ai-parrot/src/parrot/clients/budget.py:280
async def report(self) -> BudgetReport:
    """Return an immutable consistent snapshot of current accounting."""

# From packages/ai-parrot/src/parrot/models/token_budget.py:110
class BudgetReport(BaseModel):
    operation_id: str; policy: TokenBudgetPolicy; state: OperationState      # lines 115-117
    input_tokens: int; output_tokens: int; total_tokens: int                 # lines 119-121
    in_flight_tokens: int; uncertain_tokens: int                             # lines 122-123
    remaining_work_tokens: int; remaining_total_tokens: int                  # lines 124-125
    counting_methods: tuple[str, ...] = ()                                   # line 126
    overrun_tokens: int = Field(0, ge=0)                                     # line 127
    accounting_complete: bool; budget_exhausted: bool                        # lines 128-129
    finalization_attempted: bool; finalized: bool; answer_complete: bool     # lines 130-132
    terminal_reason: Optional[str] = None                                    # line 133

# From packages/ai-parrot/src/parrot/models/token_budget.py:25
class TokenBudgetPolicy(BaseModel):
    token_budget: int = Field(..., ge=0)                                     # line 30
    budget_mode: BudgetMode = "estimated"                                    # line 31
    final_answer_reserve: int | float = Field(0.15)                          # line 32

# From packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py
budget_supported_methods = frozenset({"ask", "ask_stream", "resume", "invoke"})  # line 90
@staticmethod
def budget_adapter_factory(): ...                                            # line 93

# From packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget.py:289
class MantleBudgetAdapter:
    async def count_input(self, payload, *, route="chat_completions", mode="estimated",
                          registry=STRICT_QUALIFICATIONS, endpoint="") -> TokenEstimate: ...  # line 300
    def normalize_usage(self, raw: Any, *, route: str = "chat_completions") -> BudgetUsage: ... # line 349
# count_input tokenizes canonical_json(body) with a local tiktoken counter (line 345)

# From packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py:10
class LLMCodeDispatchProfile(BaseModel):
    subagent: Literal["sdd-worker", "sdd-coder"] = "sdd-worker"  # line 18
    llm: str = "nvidia:minimaxai/minimax-m3"                     # line 19
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)   # line 22
    max_turns: int = Field(default=24, ge=1, le=100)             # line 23
    max_tokens: int = Field(default=8192, ge=256, le=32768)      # line 24

# From packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py:189
class ClientRoundEvent(LifecycleEvent):
    """Emitted after each tool-execution round inside a client's ask() loop (FEAT-397)."""
    # client_name, model, round_number, input_tokens, output_tokens, total_tokens, tool_calls
```

#### Verified Imports

```python
# These imports have been confirmed to resolve:
from parrot.clients.budget_scope import current_budget_scope, get_default_registry  # budget_scope.py:33,297
from parrot.models.token_budget import TokenBudgetPolicy, BudgetReport              # models/token_budget.py:25,110
from parrot.flows.dev_loop.sdd_coder.fidelity import parse_task_files               # fidelity.py:25
from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord, TaskResult, CoderJob
from parrot.models.basic import CompletionUsage                                     # imported at llm.py:44
```

#### Key Attributes & Constants

- `AttemptRecord.usage` → `Dict[str, Any]` (`sdd_coder/models.py:124`) — the widening point; adding keys here needs no new model.
- `CoderJob.tasks` → `List[TaskResult]` (`sdd_coder/models.py`) — what `_journal` already writes to disk.
- `DispatchCompleted.{input_tokens,output_tokens,cache_creation_input_tokens,cache_read_input_tokens,total_cost_usd,num_turns,duration_ms}` → all `Optional` (`session_state.py:480-486`).
- `.gitignore:283` → `artifacts/` is ignored; files under it are tracked only when force-added.
- Roster seat labels and models: `docs/dev_loop/sdd-coder-orchestrator.md` "The roster" table — `qwen`/`nova`, `gemini`/`google-compat`, `codex-spark`/`codex`, `haiku`/native.

### Does NOT Exist (Anti-Hallucination)

- ~~`LLMCodeDispatchProfile.token_budget`~~ — the profile has `max_turns`, `max_tokens`, `timeout_seconds`, but **no** budget field (`models/llm.py:10-40`).
- ~~`AttemptRecord.turns`~~ / ~~`AttemptRecord.outcome`~~ — turns live inside `usage["num_turns"]`; the outcome lives on `TaskResult`, not on the attempt.
- ~~`artifacts/logs/sdd-coder-usage/`~~ and any telemetry writer in `sdd_coder/` — the only disk write is `_journal` (`engine.py:472-488`).
- ~~`BedrockMantleClient.budget_supported_methods` covering `_chat_completion`~~ — the frozenset is `{"ask", "ask_stream", "resume", "invoke"}` (`mantle.py:90`). The dispatcher loop is covered **only** because `_chat_completion` consults the ContextVar (`openai_base.py:262-264`), not because of that frozenset.
- ~~A strict-mode qualification for Mantle~~ — `MantleBudgetAdapter.count_input` raises `BudgetUnsupported` in `strict` mode unless an injected registry matches (`amazon/budget.py:326-330`). Shadow mode must use `budget_mode="estimated"`.
- ~~`scripts/telemetry/`~~ — no such package; `scripts/` holds flat modules plus `scripts/sdd/`, `scripts/bench/`, `scripts/matrix/`.
- ~~A `dispatch.completed` payload carrying cache or cost fields from the in-process loop~~ — `_completion_usage_payload` emits only `num_turns`, `duration_ms`, `input_tokens`, `output_tokens` (`llm.py:610-617`). Cache and cost keys exist on `DispatchCompleted` but are populated only by the CLI dispatchers.
- ~~A per-run bundle for `sdd-coder`~~ — `usage_report.py` and `run_bundle.py` belong to the dev-loop *flow*; the FEAT-549 MCP path is driven by Claude Code and produces no run bundle.

---

## Parallelism Assessment

- **Internal parallelism**: three lanes that are mostly independent — (1) the
  scope binding and widened payload in `dispatchers/llm.py`, (2) the JSONL sink
  and `AttemptRecord` widening in `sdd_coder/`, (3) the analysis script. Lanes 1
  and 2 share one contract: the set of keys added to the completion payload.
  Lane 3 depends only on the written row schema, not on either implementation.
- **Cross-feature independence**: touches files owned by two recently-closed
  features (FEAT-549 `sdd_coder/`, FEAT-550 `budget*`), but both are merged to
  `dev` and neither has in-flight work. The only shared-file risk is
  `dispatchers/llm.py`, which is also the dev-loop's main in-process dispatcher —
  a concurrent feature editing that loop would conflict.
- **Recommended isolation**: `per-spec`.
- **Rationale**: the lanes are small and the payload contract couples 1 and 2
  tightly enough that splitting them across worktrees would cost more in
  reconciliation than it saves in wall-clock. A single worktree with sequential
  tasks keeps the contract in one head. Lane 3 could run in parallel but is
  cheap enough not to justify the ceremony.

---

## Open Questions

<!-- All questions resolved 2026-09-12. Convention: [x] + answer after the final ':' -->

- [x] Which seats does the instrumentation cover? — *Owner: Jesus Lara*: All of `LLMCodeDispatcher` — `nova` (Mantle/Bedrock) and `google-compat` (Gemini) — so there is a comparison baseline; `codex` and `haiku` are out of scope.
- [x] Where does the dataset live? — *Owner: Jesus Lara*: Append-only JSONL under `artifacts/logs/sdd-coder-usage/<FEAT-ID>.jsonl` in the main repository, one file per feature (git-ignored; force-add a curated snapshot when it should be shared).
- [x] How is the shadow scope activated? — *Owner: Jesus Lara*: Opt-in environment variable; disabled by default so normal runs never touch the budgeted funnel.
- [x] Does the feature include the analysis tooling? — *Owner: Jesus Lara*: Yes — a percentile script that recommends a `token_budget` per seat × task-size segment.
- [x] How are consumption and outcome joined? — *Owner: Jesus Lara*: Two append-only lines (`attempt` at attempt end, `outcome` at consolidation) joined by `(feature_id, task_id, attempt)`, so a crash between them costs the outcome, never the measurement.
- [x] Aggregates only, or a per-turn series? — *Owner: Jesus Lara*: Aggregates plus a compact per-turn input/output series — it is what distinguishes a large task from a degenerate loop.
- [x] One accounting source or two? — *Owner: Jesus Lara*: Both side by side (provider `CompletionUsage` and the ledger's `BudgetReport`); their difference calibrates the margin.
- [x] What is the actual overhead of `count_input` over a long loop? — *Owner: Jesus Lara*: **Measured, not estimated** (2026-09-12, `artifacts/logs/sdd-coder-count-input-overhead-20260912.md`): 4.9 ms at turn 1, 65 ms at turn 60, 2.77 s total for a 60-turn attempt reaching 148k tokens of history — 0.1–0.5% of attempt wall-clock. Not a reason to restrict the shadow scope to campaigns. Residual caveat recorded: `count_input` counts synchronously on the event loop (`amazon/budget.py:345`), ~11 s of blocking per 4-seat wave, removable with one `asyncio.to_thread` if it ever matters.
- [x] Retention and rotation of the JSONL? — *Owner: Jesus Lara*: One file per feature, `artifacts/logs/sdd-coder-usage/<FEAT-ID>.jsonl`. No rotation logic; the analysis globs the directory. This also designs away the cross-process append race — two concurrent `sdd-worker` runs are two features, hence two files.
- [x] How many merged attempts per segment before a recommendation is trustworthy? — *Owner: Jesus Lara*: **n ≥ 12** to emit a suggested ceiling. Below that the script still prints the percentiles, marked unreliable, but withholds the recommendation.
- [x] Should `final_answer_reserve` keep its 0.15 default for a coder seat? — *Owner: Jesus Lara*: No — the shadow policy passes an **absolute** reserve of `2 × profile.max_tokens`. A coder's final output is a small `DevelopmentOutput` JSON; a fractional reserve against a large ceiling would immobilise ~120k tokens to protect ~1k. FEAT-550 already accepts an int as absolute tokens (`models/token_budget.py:32`).
- [x] Should FEAT-550 finalization and the `max_turns` salvage (`llm.py:800-843`) be unified? — *Owner: Jesus Lara*: Not here — recorded as the follow-up this feature's dataset would justify. They are the same gesture (force a tools-disabled close when a resource runs out) reached by two paths, but unifying them is a behavior change and this feature's value rests on changing nothing.

## Follow-ups (out of scope, recorded)

- **Option D — budget elasticity experiment**: once the dataset exists, run the same tasks at several *real* ceilings and measure merged-rate per token, to find the ceiling that maximises useful work rather than the one that never interrupts.
- **Unify the two finalization paths**: FEAT-550's tools-disabled finalization and `LLMCodeDispatcher`'s forced-`final_output` salvage.
- **`asyncio.to_thread` for `count_input`**: only if event-loop blocking during wide waves ever shows up in practice.
