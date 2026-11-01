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
The brainstorm asks for a correlation key and a single store, and concludes that neither
exists. Research refutes both halves: **two usage stores already ship with disjoint keys**,
and the key the brainstorm proposes is already implemented in one of them.
`parrot.observability` is a complete normalized usage plane — `UsageRecord` built once per
LLM call, a ContextVar correlation key, a `UsageRecordingSubscriber` fan-out to pluggable
sinks, `gen_ai.client.*` OTel metrics, and a shared `CostCalculator` over six versioned
price files — while `flows/dev_loop/sdd_coder/telemetry.py` already records per-attempt
tokens keyed by exactly `(feature_id, task_id, attempt_uid, execution_id, seat_label,
backend, resolved_model)` into a live 1090-attempt dataset. The real gap is therefore
narrower and sharper than the brainstorm's: the two stores share no key, price coverage is
**1.2%**, the codex seat reports ~zero tokens because `dispatchers/codex.py` streams
`codex exec --json` without ever reading usage, cache tokens are destroyed at the
`CompletionUsage` boundary, and the two CLI seats are outside `AbstractClient` entirely.
The recommended shape is consequently the opposite of the brainstorm's Option C: **extend
the attribution dimension of the pipeline that exists** — the merged, completed FEAT-228
pattern — and **do not build a usage plane in the ledger**, which is contradicted on five
independent counts.

---

--- original request ---

The original request, preserved verbatim at `sdd/state/FEAT-783/source.md`.

> Token usage and cost for one SDD spec are split across three seats that report to
> three different places, so nobody can answer "what did FEAT-123 cost?" with correct
> numbers. […] The gap is not a missing exporter. It is a missing **correlation key**
> shared by the three seats, and a missing **single store** that owns the per-spec
> numbers. […] Goal: one usage plane, written by all three seats, keyed by
> `(feat_id, task_id, attempt_uid, execution_id, seat, model)`, from which both
> `wikitoolkit usage report --feat FEAT-123` and the Grafana dashboards read.

**Initial signals** (extracted, not interpreted):
- Verbs: *extend, new, reuse, record, bind, resolve, price* → additive, feature-shaped, not a bug.
- Named entities: `LedgerEventKind`, `LedgerService`, `coder_feedback.py`, `coder_begin_execution` / `coder_end_execution`, `AbstractClient`, `sdd/state/<FEAT-ID>/state.json`, `prices.yaml`, `wikitoolkit usage`, `OTEL_RESOURCE_ATTRIBUTES`, `claude_code.api_request`, `SubagentStop`, `codex exec --json`, Grafana.
- Structure provided: a "Does NOT exist" list of 6 absence claims, a 13-row impact table, 4 groups of research directives, 5 spikes, 6 open questions.
- Acceptance criteria provided: no — but the spikes carry explicit pass criteria, one of which this research falsifies.

---

### Constraints and goals
1. **Cost is computed exactly once, at the origin.** FEAT-710 (merged, PR #1772) G5 exists
   because three subscribers each recomputed it; PR #1747 was **closed** for adding a
   fourth that "recomputed cost a fourth time… collided with the existing
   `parrot.observability.setup_telemetry`". *Implication*: a `usage.priced` event with its
   own price table is the shape review has already rejected. (F022)
2. **The PII and cardinality contract forbids the proposed key.** `UsageRecord` carries no
   `user_id`/`session_id` by documented contract, and `metrics.py:8` enforces
   *"`user_id`, `session_id`, prompt/completion content NEVER"* as metric labels.
   *Implication*: `feat_id`/`task_id` are bounded and acceptable; `session_id` is not. (F007)
3. **The ledger cannot host a usage plane.** No per-plane tables; `index.py` has no
   `CREATE TABLE`; `compact()` is issue-scoped and never truncates the log; events cap at
   4 KiB; the index replays from a byte cursor. *Implication*: "inherits
   `export_snapshot`/`compact`/`audit` for free" is false on every count, and per-request
   rows there is unbounded growth with no rollup facility. (F001, F002, F003, F016)
4. **A new event kind is a three-part change** (Literal member + payload model + reducer),
   and unknown kinds are **silently ignored**. *Implication*: adding `usage.*` without a
   reducer is accepted by the log and invisible to the index — a silent-failure mode. (F012, F027, F002)
5. **The dev-loop join is in-process, not inferable.** Every `coder_*` tool takes
   `execution_id`, and the engine owns a deterministic worktree→`execution_id` map.
   *Implication*: a hook-based `cwd → feat_id` heuristic is a weaker reconstruction of
   something already known exactly. (F004, F011, F017)
6. **`execution_id` is optional in practice** — 332 of 1090 rows have none (retrofitted by
   FEAT-559, "Empty for historical records") — and `coder_end_execution` has an open defect
   (`issue:cc372f700a47`) making it an unreliable settlement signal. (F005, F029)
7. **Cache tokens are destroyed at normalization.** `CompletionUsage` is three counters; a
   grep for `cache_read`/`cache_creation`/`cached_input` across `parrot/clients/` returns
   nothing; `ClientRoundEvent.raw_usage` is the only survivor. *Implication*: a four-counter
   model touches three layers — price table, budget models, telemetry row. (F015, F023)
8. **Price coverage, not price machinery, is the binding constraint.** Tier keys across all
   six files are exactly `input_per_1m`, `output_per_1m`, `cached_input_per_1m`,
   `valid_from`, `note` — **no cache-creation tier**; oldest file is **165 days** stale
   against its own 90-day warning; **13 of 1090 rows (1.2%)** use a priced model. (F006)
9. **The hook design is falsified by measurement.** `wikitoolkit` warm start is p50
   ~415–425 ms (`issue:f0a40d0853f2`) against the brainstorm's own S2 criterion of
   **< 150 ms** per sub-agent stop. (F028)
10. **A hook in the *user* setting source never fires for a sandboxed `sdd-worker`**
    (HOTFIX-6756c929a450) — precisely the seat this feature most wants to measure. (F021)
11. **Claude Code telemetry is off in this repo**, so Option A is not a zero-cost
    complement on a working pipeline; the pipeline must be turned on first. (F008)
12. **The docs leave the Claude Code join unstated** — neither the parent `session.id` on
    sub-agent `api_request`, nor `prompt.id` on those events (the declared *fallback*), nor
    what `query_source=auxiliary` covers. But `CLAUDE_CODE_SESSION_ID` **is** documented in
    Bash, hook and **stdio MCP server** subprocesses. (F031)
13. **"Seat" already means two different things** — sdd-coder roster seat (`"a"`/`"b"`/`"c"`
    + kind + backend) and observability seat (`"development.w1"`) — and the brainstorm adds
    a third. (F017, F007)
14. **Shareability is an unmade decision.** A `usage.*` kind must declare itself in
    `is_shareable`; sharing puts per-attempt token counts into git history on every machine,
    not sharing makes the plane per-machine. (F016)
15. **The ground is contended.** `TASK-4381` (HelixLedgerStore + `LedgerService` backend
    dispatch) is active, and `sdd_coder/engine.py` is the package's hottest file with open
    encapsulation defects at `begin_execution`. (F027, F019, F029)

### Recommended option / probable scope
**Scope statement.** Make per-spec usage and cost answerable by extending the attribution
dimension of the usage pipeline that already exists, closing the codex usage gap, and fixing
price coverage — not by building a ledger-owned usage plane.

### What's New
- **A usage read on the codex event stream.** `dispatchers/codex.py` already streams
  `codex exec --json`; `_usage_from_event` already knows how to parse it. Highest-leverage
  single change in the whole proposal: the codex seat is **60% of attempts and 0.0006% of
  recorded tokens**. Natural home is `dispatchers/_shared.py` — twelve siblings share the gap. (F009, F025)
- **Per-spec attribution ContextVars** (`current_feat_id` / `current_task_id` /
  `current_attempt_uid` / `current_execution_id`) beside `current_run_id` / `current_seat`,
  set by the engine, which already owns all four values. (F007, F011)
- **One `AbstractLogger` sink** persisting attributed `UsageRecord`s, following the
  `run_ledger.py` precedent: append-only, never merge, so retries do not overwrite each other. (F007)
- **A cache-creation/cache-write price tier**, plus entries for the models actually run
  (`gpt-5.6-terra`, `zai.glm-4.7-flash`, `qwen`, `minimax`, `mistral.devstral`) and the
  Claude 5 family. (F006)
- **A reader**: `wikitoolkit usage report --feat FEAT-NNN [--by task|seat|model]` and its
  paired MCP tool, following the TASK-4020 CLI+MCP-in-one-task pattern. (F028)
- **An OTLP ingestor for the two CLI seats.** Codex speaks `gen_ai.usage.*` natively and can
  share parrot's schema; Claude Code's `claude_code.*` names do not, so it is the odd one out. (F010, F031)

### What Changes
| Path | Change | Evidence |
|---|---|---|
| `observability/recorders/models.py` | Widen `UsageRecord` with the SDD attribution fields, honouring the PII contract (`feat_id`/`task_id` bounded; `session_id` stays out) | F007 |
| `observability/subscribers/metrics.py` | Add the new labels under the cardinality whitelist, exactly as FEAT-228 added `parrot.agent.name` | F007, F024 |
| `models/basic.py` | Widen `CompletionUsage` with `cache_read` / `cache_creation` (and consider Codex's `reasoning_output_tokens`) | F015, F023, F010 |
| `flows/dev_loop/sdd_coder/telemetry.py` | Add cache counters and cost — **or retire it** in favour of the observability sink; the repo currently has two parallel usage datasets with no shared key | F004, F005, F007 |
| `flows/dev_loop/dispatchers/codex.py` (+ `_shared.py`) | Read usage from the stream it already parses | F009 |
| `observability/cost/pricing/*.json` | Refresh, add the cache-creation tier, add the self-hosted and current-generation models | F006 |

### What's Untouched (Non-Goals)
- **`knowledge/wiki/ledger/`** — no `usage.*` kind, no usage plane, no new DDL. Contradicted
  on five counts (constraints 3, 4, 14, 15).
- **`clients/base.py` cost computation** — FEAT-710's G5 stands: computed once at the origin, read, never recomputed.
- **`memory/compaction` `report_usage`** — implemented, but never fires for coder attempts, Claude Code or Codex.
- **The existing session-level Grafana/OTel dashboards**, and FEAT-774's BigQuery sink landing upstream in `navigator-eventbus`.
- **A new `usage/prices.yaml`** — a second price table is two sources of truth for one number.

### Patterns to Follow
- **FEAT-228** — widen the attribution dimension of existing metrics. Shipped **complete**, 6/6 tasks, 2026-06-08. (F024)
- **FEAT-479 `run_ledger.py`** — a SINK, not an `EventProvider`; the existing subscriber owns the subscription. (F007)
- **FEAT-554 `telemetry.py`** — durable root resolved via git-common-dir to the main checkout and **refused** inside a worktree; fail-open writes that never change a dispatch outcome; per-event size cap; path-traversal guard on the id. (F004)
- **TASK-4020** — ship the CLI subcommand and its MCP tool in one task. (F028)

### Integration Risks
- Being a **fourth consumer** of `AfterClientCallEvent` is exactly what closed PR #1747. Ride the existing fan-out as a sink.
- **Two usage datasets already exist with disjoint keys.** Shipping a third without retiring or joining one makes the original problem worse.
- Both CLI seats are outside `AbstractClient` and neither exports telemetry today; enabling Claude Code's is an ops + prompt-privacy decision.
- Attributing cost to **abandoned attempts** (correct, and wanted) interacts with `issue:c4d0e7a028ca` — codex seats can never commit, so codex attempts are routinely abandoned and their cost is real.
- `cumulative_cost_usd` is **process-cumulative**: an `sdd-worker` outliving several tasks yields a rising number that must never be summed per task.
- `engine.py` is the hottest file in its package with open defects at the exact boundary.

---

### Verified code anchors (paths only — open them yourself)
observability/recorders/models.py
observability/recorders/subscriber.py
observability/cost/calculator.py
observability/cost/pricing/anthropic.json
observability/subscribers/metrics.py
clients/base.py
models/basic.py
flows/dev_loop/sdd_coder/telemetry.py
flows/dev_loop/dispatchers/codex.py
ai-parrot-client-openai/…/openai/codex_agent.py
flows/dev_loop/sdd_coder/engine.py
flows/dev_loop/sdd_coder/toolkit.py
knowledge/wiki/ledger/events.py
knowledge/wiki/ledger/index.py
knowledge/wiki/ledger/store.py
knowledge/wiki/ledger/log.py
knowledge/wiki/ledger/shared_log.py
knowledge/wiki/ledger/coder_feedback.py
clients/budget.py
memory/abstract.py
.claude/settings.json
knowledge/wiki/claude_code/installer.py
sdd/templates/state.schema.json
sdd/specs/parrot-telemetry-event-fanout.spec.md
sdd/specs/per-agent-cost-usage-metrics.spec.md

### Questions still open in the exploration document
- [ ] **S1 (gate, now in v1 scope)** — does a sub-agent's `claude_code.api_request` carry the
- [ ] **S3 remainder** — one captured `codex exec --json` run to confirm the stdout event's
- [ ] **S4** — the three-seat reconciliation run against provider dashboards. Deliberately
- [ ] Which of the two existing usage datasets survives — does `AttemptUsageRow` gain cache
- [ ] Which "seat" vocabulary wins, and what is the declared mapping for the other two?
- [ ] Does the binding path avoid the ~420 ms `wikitoolkit` warm start by being in-process,

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
