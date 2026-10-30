---
id: FEAT-783
title: "Unified usage & cost metrics per SDD spec: extend the existing attribution dimension rather than build a new usage plane"
slug: unified-usage
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-30
  summary_oneline: "Unified usage & cost metrics per SDD spec: one correlation key and one owner for per-spec token and cost numbers across three seats"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-client-openai, dev-loop, sdd-tooling, docs]
tags: [usage-metrics, cost-attribution, observability, telemetry, sdd-coder, otel, pricing]
research_state: sdd/state/FEAT-783/
created: 2026-10-30
updated: 2026-10-31
---

# FEAT-783 — Unified usage & cost metrics per SDD spec

> **Mode**: enrichment
> **Confidence**: medium (localization high and probe-verified; scope medium — spike S1 is an open empirical gate and all three seats are in v1)
> **Source**: `file: sdd/proposals/unified-usage.proposal.md` — the brainstorm committed on `dev` as `282d95d0c6` (2026-10-30), preserved verbatim at `sdd/state/FEAT-783/source.md`
> **Audit**: [`sdd/state/FEAT-783/`](../state/FEAT-783/)

---

## 0. Origin

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

## 1. Synthesis Summary

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

## 2. Codebase Findings

31 findings (36 raw, 5 merged; originals under `findings/.audit/`). Every path below was
re-verified by two independent `sdd-contract-probe` runs (45 checks, 0 stale, 0 missing)
plus four manual re-verifications where a probe's fixed command applied a `--include=*.py`
filter to a `.json` target.

### 2.1 Localization

| Path · Symbol | Role | Evidence |
|---|---|---|
| `observability/recorders/models.py::UsageRecord` (22-75) | The normalized, PII-free per-call usage record: tokens, `cost_usd`, and FEAT-479's `run_id`/`seat`/`node_id`/`cycle` — **but no `feat_id`/`task_id`/`attempt_uid`** | F007, F022 |
| `observability/recorders/subscriber.py::UsageRecordingSubscriber` (47) | Subscribes to `AfterClientCallEvent` and fans records out to every configured `AbstractLogger`. The merged precedent for adding a consumer **as a sink, not a subscriber** | F007, F022 |
| `observability/cost/calculator.py::CostCalculator.cost_usd` (135-238) | The existing shared price engine; returns `None` rather than guessing for an unpriced pair | F006, F022 |
| `observability/cost/pricing/anthropic.json` (1-123) | The existing versioned price table: `input_per_1m` / `output_per_1m` / `cached_input_per_1m` / `valid_from` — **no cache-creation tier** | F006 |
| `observability/subscribers/metrics.py::MetricsSubscriber` (8-10, 96-134, 198-339) | The `gen_ai.client.*` metric surface, the cardinality whitelist, and the ten FEAT-228 `parrot.agent.name` sites — the precedent being extended | F007, F024 |
| `clients/base.py::_compute_call_cost` (682-814) | FEAT-710's single cost computation at the origin; also `_emit_round`, where `raw_usage` (the only surviving cache-token carrier) passes through | F015, F006, F022 |
| `models/basic.py::CompletionUsage` (48) | The three-counter object every provider funnels into — the boundary at which cache tokens are destroyed | F023, F015 |
| `flows/dev_loop/sdd_coder/telemetry.py::AttemptUsageRow` (40-116, 268-311) | The already-shipped per-attempt dataset carrying the brainstorm's exact key, written to a main-checkout-resolved append-only JSONL, gated behind `DEV_LOOP_CODER_TELEMETRY` | F004, F005 |
| `flows/dev_loop/dispatchers/codex.py` (5, 453, 544) | Already builds and streams `codex exec --json`; **contains no usage extraction at all** | F009 |
| `ai-parrot-client-openai/…/openai/codex_agent.py::_usage_from_event` (603-632) | Already maps Codex event-stream tokens onto `CompletionUsage` — the parser the dispatcher is missing | F025 |
| `flows/dev_loop/sdd_coder/engine.py::begin_execution` (482-667) | Owns the caller-generated `execution_id` and a deterministic canonical-worktree-path → `execution_id` map | F011, F029 |
| `flows/dev_loop/sdd_coder/toolkit.py::coder_end_execution` (304-438) | Every per-task `coder_*` tool already takes `execution_id` — the key is already threaded through the MCP boundary | F017 |
| `knowledge/wiki/ledger/events.py::LedgerEventKind` (7-20, 88-122) | A 12-member `Literal` with no `usage.*` kind; envelope has **no `worktree` field**; `compute_event_id` hashes `ts`, so it cannot express `(seat, source_ref)` dedup | F001 |
| `knowledge/wiki/ledger/index.py::apply_event` / `compact` (107-128, 536-563) | Reduces six `issue.*` kinds into wiki `pages`, **silently ignores unknown kinds**, compacts only `category='issue'`, never truncates `events.jsonl` | F002 |
| `knowledge/wiki/ledger/store.py::LedgerStore` (24-123) | The ledger's **only** DDL is a two-column `ledger_state` cursor | F003 |
| `knowledge/wiki/ledger/log.py::LedgerLog.append` (21-111) | `O_APPEND` atomic write **capped at 4 KiB**, replayed from a byte cursor | F016 |
| `knowledge/wiki/ledger/shared_log.py::is_shareable` (73-144) | Decides whether a kind is published into the git-committed `sdd/ledger/` | F016 |
| `knowledge/wiki/ledger/coder_feedback.py::feedback_id` (66-96) | The dedup rule the source quotes correctly — but keyed `(backend, model, task_id, attempt_uid, pattern)`, **without `execution_id`**, on a semantic pattern rather than a request id | F012 |
| `clients/budget.py` (1-236) | FEAT-550's reservation ledger: `reserved`/`settled`/`uncertain`/`released`, with a real enforcement path | F013, F026 |
| `memory/abstract.py::report_usage` (561-593) | Implemented, but a prompt-token calibration hook keyed `(user_id, session_id, chatbot_id)` | F014 |
| `.claude/settings.json` (12) | One `PreToolUse` hook; env is only `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS` — **Claude Code telemetry is not enabled here** | F008 |
| `knowledge/wiki/claude_code/installer.py::_merge_hook` (191-249) | parrot already owns an idempotent Claude Code hook installer + runtime, hardcoded to `PreToolUse` | F008 |
| `sdd/templates/state.schema.json` | Fourteen properties, **none** of them `current_task`, `task_id` or `attempt_uid` | F011 |
| `sdd/specs/parrot-telemetry-event-fanout.spec.md` (57) | FEAT-710's G5 and the recorded rejection of PR #1747 | F022 |
| `sdd/specs/per-agent-cost-usage-metrics.spec.md` (1-459) | FEAT-228 — the **completed** precedent for this exact shape of change | F024 |

### 2.2 Constraints Discovered

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

### 2.3 Recent History (Relevant)

- **Ledger** (30 commits/90d): all FEAT-694 shared-log and FEAT-758 outbox. Nothing touches
  usage or cost; no unmerged branch touches `ledger/`. A usage plane would not collide — it
  would simply be the first component in the package to need its own DDL. (F018)
- **sdd_coder**: `engine.py` is the hottest file, touched the same day and by two HOTFIX
  briefs the week before. `telemetry.py`, `roster.py` and `evidence.py` have **zero**
  commits in 90 days. `TASK-4542` retired "the dead escalation-ledger writes" — a prior
  dev-loop→ledger write path that was built and then deleted. (F019)
- **Clients**: `base.py` already emits `cost_usd` (FEAT-710, TASK-4548, 2026-10-22) and is
  otherwise quiet (4 commits/90d). FEAT-550 built the budget ledger in September. (F020)
- **Hooks**: `.claude/settings.json` untouched since 2026-09-10; three hook scripts ever
  added, one per commit. Adding `SessionStart`/`SubagentStop` is low-risk mechanically. (F021)
- **Prior attempts — three, not zero.** FEAT-550 (merged) built the token budget;
  **FEAT-775's in-process `TelemetryBridge` was closed as PR #1747**; FEAT-710 (merged,
  PR #1772) replaced it with single-cost-at-origin. The only unmerged branch,
  `origin/sdd/FEAT-774-775-telemetry`, is **specs only** and its FEAT-775 half is explicitly
  superseded; those two ids are **cross-repo ids from fieldsync's ledger** and collide with
  this repo's own FEAT-774/778. (F022)

---

## 3. Probable Scope

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

## 4. Confidence Map

Full 30-claim map in `sdd/state/FEAT-783/synthesis.json`. Distribution: **23 high, 7 medium, 0 low.**

| | Claim | Conf | Evidence |
|---|---|---|---|
| ✓ | No `usage.*` kind exists; `LedgerEventKind` is a 12-member `Literal` | high | F001 |
| ✓ | The `LedgerEvent` envelope has **no `worktree` field** | high | F001 |
| ✓ | The ledger has no per-plane tables; `index.py` has no `CREATE TABLE` | high | F002, F003 |
| ✓ | `compact()` is issue-scoped and never truncates `events.jsonl` | high | F002 |
| ✓ | `LedgerService` has no generic plane API — nothing is inherited for free | high | F012 |
| ✓ | A per-attempt dataset with the proposed key already ships: 1090 attempts, 55 features, 148.7M input tokens | high | F004, F005 |
| ✓ | codex = 660 of 1090 attempts but **910** of 148.7M input tokens | high | F005 |
| ✓ | `dispatchers/codex.py` streams `--json` with **no** usage extraction | high | F009 |
| ✓ | A Codex usage parser already exists at `codex_agent.py:603` | high | F025 |
| ✓ | A versioned price table + shared `CostCalculator` already ship | high | F006, F022 |
| ✓ | **1.2%** price coverage; oldest table **165 days** stale | high | F006, F005 |
| ✓ | **No cache-creation tier** in any price file | high | F006 |
| ✓ | `parrot.observability` is already a normalized usage plane | high | F007 |
| ✓ | It forbids `session_id`/`user_id` by PII contract and cardinality whitelist | high | F007 |
| ✓ | FEAT-710 G5: cost computed once at origin; PR #1747 closed for a fourth subscriber | high | F022 |
| ✓ | FEAT-228 is **complete** (6/6, 2026-06-08) — the precedent | high | F024 |
| ✓ | Cache tokens destroyed at normalization; `raw_usage` the only survivor | high | F015, F023 |
| ✓ | `state.json` has no `current_task` / `task_id` / `attempt_uid` | high | F011 |
| ✓ | The engine owns a deterministic worktree → `execution_id` map | high | F011, F017 |
| ✓ | Claude Code telemetry is **not** enabled in this repo | high | F008 |
| ✓ | Docs do not state the parent `session.id` join, `prompt.id` on sub-agent events, or `auxiliary` | high | F031 |
| ✓ | `report_usage` is implemented and is calibration-only | high | F014 |
| ✓ | "Seat" already has two incompatible meanings | high | F017, F007 |
| ◐ | `CLAUDE_CODE_SESSION_ID` reaches stdio MCP subprocesses → the MCP server can self-bind | medium | F031 |
| ◐ | Codex 0.164.0 emits `gen_ai.usage.*`, `codex.turn.cost_microusd`, `auth_mode` | medium | F010, F030 |
| ◐ | Codex reports `reasoning_output_tokens` — a counter with no slot in the proposed schema | medium | F010 |
| ◐ | A `wikitoolkit`-shelling hook costs ~415–425 ms vs the S2 criterion of < 150 ms | medium | F028 |
| ◐ | `execution_id` is optional (332/1090 empty); `coder_end_execution` unreliable as settlement | medium | F005, F029 |
| ◐ | Usage events would force an explicit shareability decision | medium | F016 |
| ◐ | The FEAT-774/775 ids are cross-repo and collide with this repo's numbering | medium | F022 |

**Why not high overall**: the three medium Codex claims rest on symbol extraction from a
release binary rather than a documented contract or a captured run; spike S1 is still open;
and U2 put all three seats in v1.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Ride FEAT-710's stream, or open a separate priced path?**
      → **Ride FEAT-710.** Widen `UsageRecord` + per-spec ContextVars + one `AbstractLogger`
      sink, reading the origin's `cost_usd`. Follows the completed FEAT-228 precedent and
      avoids the shape closed in PR #1747.
- [x] **U2 — Which seats are in v1?**
      → **All three.** Consequence accepted explicitly: spike **S1 becomes a v1 gate with no
      documented fallback**, and Claude Code's telemetry pipeline must be switched on in this
      repo — an ops and prompt-privacy decision, not a code one.
- [x] **U3 — Who owns the price table?**
      → **Extend the existing files, and treat coverage as a BLOCKING prerequisite.** Refresh
      `observability/cost/pricing/*.json`, add the cache-creation tier and the
      self-hosted/current-generation models. The 1.2% gap gates any cost claim rather than trailing it.
- [x] **U4 — How does a subscription seat appear?**
      → **Zero marginal cost, with list price as a separate `equivalent_usd` column**, derived
      per seat from `auth_mode` / `plan_type` rather than hand-configured. Prevents a
      plan-based `sdd-worker` run from inflating a spec with money never spent.
- [x] **U5 — Reporting or enforcement?**
      → **Reporting only in v1, designed enforcement-ready**: the read path is shaped so
      binding a per-spec `BudgetScope` later is a configuration change, not a redesign.

### Unresolved (defer to spec / implementation)

- [ ] **S1 (gate, now in v1 scope)** — does a sub-agent's `claude_code.api_request` carry the
      parent `session.id`, an `agent_id` matching `SubagentStop`, and `agent.name=sdd-coder`?
      The docs state neither this nor its declared `prompt.id` fallback, so a failure leaves
      no fallback standing. Needs one captured run under an OTLP file exporter.
- [ ] **S3 remainder** — one captured `codex exec --json` run to confirm the stdout event's
      token field names (the OTel side is answered; the stdout side is not).
- [ ] **S4** — the three-seat reconciliation run against provider dashboards. Deliberately
      not run here: it costs real spend.
- [ ] Which of the two existing usage datasets survives — does `AttemptUsageRow` gain cache
      counters and cost, or is it retired into the observability sink?
- [ ] Which "seat" vocabulary wins, and what is the declared mapping for the other two?
- [ ] Does the binding path avoid the ~420 ms `wikitoolkit` warm start by being in-process,
      a direct file append, or batched — and how does it survive HOTFIX-6756c929a450, where a
      user-source hook never fires for a sandboxed `sdd-worker`?

---

## 6. Recommended Next Step

```
/sdd-spec FEAT-783
```

**Rationale**: U1 resolved the one architectural fork, so the remaining uncertainty is
empirical rather than architectural — spike S1 gates one lane of three, not the design.

**Preconditions the spec must carry:**
1. **S1 before the Claude Code lane's join is specified.** The docs state neither the join nor its fallback.
2. **The price-table refresh + cache-creation tier is a blocking prerequisite** (U3), not a follow-up. Without it 98.8% of attempts price to `None`.
3. **One captured `codex exec --json` run** to confirm the stdout event field names.

### Alternatives
- `/sdd-brainstorm FEAT-783` — was the pre-Q&A recommendation, when Option C was refuted and
  three shapes were live. **Superseded**: U1 chose one, so a second brainstorm would
  re-litigate a settled decision.
- **Split the feature.** The codex usage parser and the price-table refresh are
  well-bounded, high-value and independent of S1; they could ship as their own spec while the
  CLI-seat ingestor waits on the spike.
- `manual-review` — not indicated: research was not truncated and no finding contradicted another after probe verification.

---

## 7. Research Audit

| Artifact | Path |
|---|---|
| State checkpoints | `sdd/state/FEAT-783/state.json` |
| Source (raw) | `sdd/state/FEAT-783/source.md` |
| Research plan | `sdd/state/FEAT-783/research_plan.json` |
| Findings (31 canonical) | `sdd/state/FEAT-783/findings/F001-*.md` … `F031-*.md` |
| Lane originals (36) | `sdd/state/FEAT-783/findings/.audit/` |
| Synthesis (JSON) | `sdd/state/FEAT-783/synthesis.json` |

**Budget consumed**: files read 32/40 · grep 23/25 · git 10/10 · depth 2/2 · **truncated: no**

**Execution**: 3 parallel lanes (codebase 17 findings / git 5 / wiki 11) + 3 external probes
(3 findings). Merge: 36 → 31, 5 merged, originals archived.

**Verification**: 45 citation checks across two independent `sdd-contract-probe` runs —
**0 stale, 0 missing**. Four manual re-verifications where a probe's fixed command applied a
`--include=*.py` filter to a `.json` target (price tiers, `state.schema.json`,
`.claude/settings.json`) and one direct recomputation of the telemetry dataset totals.
**One inter-lane contradiction resolved**: the wiki lane claimed
`ConversationMemory.report_usage` does not exist as a surface; the codebase lane's direct
read and a symbol probe both place it at `memory/abstract.py:561` — the direct evidence wins.

**Mode determination**: `auto` → `enrichment` (additive verbs, a recommended option, an
explicit absence list to confirm or refute).

**Spikes deliberately not run**: S1 (live Claude Code OTel capture) and S4 (three-seat
reconciliation) cost real token spend and remain gates.

---

## 8. Provenance

| Field | Value |
|---|---|
| Generated by | `/sdd-proposal` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md` |
| Plan prompt | `sdd/templates/research_plan.prompt.md` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Source commit | `282d95d0c6` (brainstorm, preserved verbatim) |
| Pinned versions | Claude Code 2.1.314 · codex-cli 0.164.0 |
| Operator | Jesus Lara |
