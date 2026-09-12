<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
artifacts/logs/sdd-coder-usage/
docs/dev_loop/sdd-coder-orchestrator.md
packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget.py
packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py
packages/ai-parrot/src/parrot/clients/budget.py
packages/ai-parrot/src/parrot/clients/budget_scope.py
packages/ai-parrot/src/parrot/clients/openai_base.py
packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
packages/ai-parrot/src/parrot/models/token_budget.py
scripts/bench/
scripts/matrix/
scripts/sdd/
scripts/telemetry/

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
