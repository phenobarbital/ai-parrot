---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-client-openai, dev-loop, sdd-tooling, docs]
tags: [usage-metrics, cost-attribution, observability, telemetry, sdd-coder, otel, pricing]
---

# Feature Specification: Unified usage & cost metrics per SDD spec

**Feature ID**: FEAT-783
**Date**: 2026-10-31
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.3.0

---

## 1. Motivation & Business Requirements

### Problem Statement

Token usage and cost for one SDD spec are split across seats that report to
different places, so nobody can answer "what did FEAT-123 cost?" with correct
numbers. The research behind this spec (`sdd/proposals/unified-usage.proposal.md`,
FEAT-783, 31 findings, 45 citation probes) established that this is **not** a
missing store or a missing exporter. Two usage stores already ship with disjoint
keys — `parrot.observability` (per-call `UsageRecord`, a shared `CostCalculator`,
`gen_ai.client.*` metrics, and an existing `UsageReport` renderer) and
`flows/dev_loop/sdd_coder/telemetry.py` (per-attempt `AttemptUsageRow`, 1090 live
attempts already keyed by `feature_id`/`task_id`/`attempt_uid`/`execution_id`).

What is actually missing is five concrete things:

1. The two stores share no key, and `UsageRecord` carries no SDD identity at all.
2. Price coverage is **1.2%** (13 of 1090 recorded attempts use a priced model);
   the oldest price file is 165 days stale; **no file has a cache-creation tier**.
3. The codex seat is **60% of attempts and 0.0006% of recorded tokens**, because
   `dispatchers/codex.py` streams `codex exec --json` and never reads usage.
4. Cache counters and provider-reported cost are **discarded at a boundary that
   already has them** — `dispatchers/claude.py` extracts
   `cache_creation_input_tokens`, `cache_read_input_tokens` and `total_cost_usd`,
   then drops them because `AfterClientCallEvent` has no slots for them.
5. The only durable per-run store, `RunLedgerRecorder`, is **in-memory with a
   no-op `aclose()`**, so no separate reporting process can ever read it.

### Goals

- G1. One immutable attribution object (`UsageAttribution`) created by the
  sdd-coder engine and carried **on the lifecycle event**, not only in a
  subscriber-read ContextVar.
- G2. `UsageRecord` carries SDD identity (`feat_id`, `task_id`, `attempt_uid`,
  `execution_id`) alongside the existing FEAT-479 `run_id`/`seat` fields.
- G3. Four-counter usage (`input`, `output`, `cache_read`, `cache_creation`) plus
  `reasoning_output`, normalized **before** fan-out, with provider-reported cost
  retained as `source_cost_usd` for reconciliation only.
- G4. Cost stays computed **exactly once at the origin** (FEAT-710 G5); every
  computed cost records the price revision and effective interval that produced it.
- G5. A durable per-spec usage store that a separate process can read.
- G6. The codex seat reports real tokens.
- G7. `wikitoolkit usage report --feat FEAT-NNN` and a paired MCP tool.
- G8. Price coverage sufficient that a per-spec cost number is meaningful —
  a **blocking** prerequisite, not a follow-up.

### Non-Goals (explicitly out of scope)

- **No `usage.*` event kind and no usage plane in `knowledge/wiki/ledger/`.** The
  ledger has no per-plane tables (its only DDL is a two-column `ledger_state`
  cursor), `compact()` is hard-scoped to `category='issue'` and never truncates
  `events.jsonl`, events cap at 4 KiB, and `LedgerService` exposes no generic
  plane seam. Option C of the brainstorm was rejected on these five counts — see
  `sdd/proposals/unified-usage.proposal.md` §2.2.
- **No second price table.** No `usage/prices.yaml`; the existing
  `observability/cost/pricing/*.json` files are extended.
- **No fourth in-process subscriber.** The new sink is an `AbstractLogger`
  registered with the existing `UsageRecordingSubscriber` fan-out. PR #1747 was
  closed for adding a subscriber that recomputed cost.
- **No mid-run budget enforcement in v1** (U5) — the read path is shaped so
  binding a per-spec `BudgetScope` later is configuration, not redesign.
- **No parsing of Claude Code transcripts** (`~/.claude/projects/*.jsonl`) — the
  format is documented as internal.
- `attempt_uid` and `execution_id` are **never metric labels** (unbounded
  cardinality); they live in the durable store and on spans.

---

## 2. Architectural Design

### Overview

Extend the attribution dimension of the usage pipeline that already exists —
precisely the shape FEAT-228 (per-agent cost metrics) shipped complete on
2026-06-08 — rather than build a parallel plane.

The sdd-coder engine already owns every identifier the report needs: it receives
a caller-generated `execution_id`, mints `attempt_uid`, and keeps a deterministic
canonical-worktree-path → `execution_id` map. M1 turns those into one immutable
`UsageAttribution`, binds it for the dispatch, and — following the pattern
`AfterClientCallEvent` already uses for `agent_name`/`user_id`/`session_id` —
**snapshots it onto the event at construction** so forwarded or cross-registry
delivery cannot attach a call to the wrong task. A subscriber-side ContextVar
read remains only as a compatibility fallback.

A correction the research surfaced, and which materially narrows the risk of
putting all three seats in v1: **the dispatched Claude coder seat is already
wired.** `dispatchers/claude.py` drives the Claude Agent SDK out of process and
FEAT-479 Module 6 already harvests terminal usage into an `AfterClientCallEvent`
(`_emit_usage_event`, claude.py:977). It therefore needs no hook and no OTLP —
only the cache/cost fields it already extracts carried through. Spike S1 (the
undocumented sub-agent `session.id` join) gates **only the interactive Claude Code
session**, which is an opt-in reconciliation source, never the primary one.

"Seat" is deliberately **not** reused as a single field: the codebase already
gives the word two incompatible meanings (sdd-coder roster seat `"a"`/`"b"`/`"c"`,
observability accounting seat `"development.w1"`), so `UsageAttribution` records
`dispatch_kind`, `roster_seat` and `accounting_seat` as separate fields.

### Component Diagram

```
sdd_coder/engine.py  begin_execution(feature, worktree, execution_id)
        │  builds UsageAttribution(feat_id, task_id, attempt_uid, execution_id,
        │                          dispatch_kind, roster_seat, accounting_seat)
        ▼
observability/context.py  usage_attribution(...)  ──┐ (fallback only)
        │                                            │
        ├─ dispatchers/claude.py  (Agent SDK, out of process)
        ├─ dispatchers/codex.py   (codex exec --json)  ← M4 codec
        └─ clients/base.py        (in-process AbstractClient)
                 │  all three construct ───────────────┘
                 ▼
   AfterClientCallEvent / ClientCallFailedEvent
     + attribution snapshot  + four-counter usage  + source_cost_usd
     + cost_usd (computed ONCE at origin) + price_revision
                 │
                 ▼
   UsageRecordingSubscriber  (existing — unchanged subscription)
                 │  fans out to every AbstractLogger
    ┌────────────┼──────────────┬───────────────────┐
    ▼            ▼              ▼                   ▼
 Prometheus   OpenLit   RunLedgerRecorder    SpecUsageRecorder  ← M5 (new, durable)
                        (in-memory, per-run)        │
                                                    ▼
                           usage_report.py (per-feat/task roll-up)  ← M8
                           sdd_coder/telemetry.py AttemptUsageRow  ← M6 (derived)
                           wikitoolkit usage report  +  MCP tool    ← M8
```

### Integration Points

| Existing component | How this feature integrates | Verified |
|---|---|---|
| `UsageRecordingSubscriber` (`recorders/subscriber.py:47`) | Registers one more `AbstractLogger` sink; the subscription itself is untouched | subscriber.py:47 |
| `AbstractLogger` (`recorders/base.py`) | `SpecUsageRecorder` implements `async def record(UsageRecord)` | base.py:16-37 |
| `build_recorders_from_config` (`recorders/factory.py`) | New backend branch, same shape as the Prometheus/OpenLit branches | factory.py:22-83 |
| `CostCalculator.cost_usd` (`cost/calculator.py:190`) | Gains `cache_creation_tokens`, honours `valid_from`, returns the price revision | calculator.py:190-238 |
| `_compute_call_cost` (`clients/base.py:792`) | Unchanged contract — still the ONE cost computation (FEAT-710 G5) | base.py:792 |
| `usage_attribution()` (`context.py:162`) | Extended to bind the full attribution object | context.py:162 |
| `_emit_usage_event` (`dispatchers/claude.py:977`) | Stops dropping the cache/cost it already extracts at claude.py:965-967 | claude.py:965-977 |
| `begin_execution` (`sdd_coder/engine.py:623`) | Builds and binds the attribution | engine.py:623 |
| `build_usage_report` (`flows/dev_loop/usage_report.py:125`) | Gains a per-feat/task grouping beside the per-seat one | usage_report.py:125 |
| `@wiki.group(name="ledger")` (`knowledge/wiki/cli.py:3229`) | A sibling `usage` click group | cli.py:3229 |

### Data Models

```python
# parrot/observability/attribution.py  (new)
class UsageAttribution(BaseModel):
    """Immutable SDD attribution for one dispatched unit of work."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    feat_id: Optional[str] = None
    task_id: Optional[str] = None
    attempt_uid: Optional[str] = None
    execution_id: Optional[str] = None
    dispatch_kind: Optional[str] = None     # "in-process" | "cli" | "sdk"
    roster_seat: Optional[str] = None       # sdd-coder roster label: "a"/"b"/"c"
    accounting_seat: Optional[str] = None   # observability seat: "development.w1"
```

### New Public Interfaces

- `parrot.observability.attribution.UsageAttribution`
- `parrot.observability.recorders.spec_usage.SpecUsageRecorder`
- `parrot.observability.cost.policy.PricingPolicy`
- `parrot.flows.dev_loop.dispatchers.codex_usage.CodexUsageCodec`
- `wikitoolkit usage report --feat FEAT-NNN [--by task|model|seat]`

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Attribution model & event carriage | yes | Field list fixed in §2 Data Models; event snapshot follows `events/client.py:58-65` | — |
| M2: Four-counter usage normalization | yes | Counter names fixed; `CompletionUsage` alias pattern already established | — |
| M3: Price tier, refresh & revisioning | no | Which models to price and at what rates is a data/judgement call, not mechanical | Needs current vendor pricing |
| M4: Codex usage codec | yes | Codec seam fixed by S7; fixture cases enumerated | — |
| M5: Durable per-spec sink | yes | `AbstractLogger` contract + FEAT-554 durable-root pattern both fixed | — |
| M6: Attempt roll-up derived | yes | Aggregate-by-`attempt_uid` rule fixed by S3 | — |
| M7: Engine binding & opt-in ingestion | no | The interactive Claude Code join is gated by spike S1 | S1 unresolved |
| M8: Reader (report + CLI + MCP) | yes | `build_usage_report` signature + click group pattern fixed | — |
| M9: Pricing policy | yes | Policy triple and `equivalent_usd` fixed by U4 | — |

### Module 1: Attribution model & event carriage
- **Path**: `packages/ai-parrot/src/parrot/observability/attribution.py` (new)
- **Responsibility**: One immutable attribution object; bind it; carry it on the event; widen `UsageRecord`.
- **Depends on**: existing `observability/context.py`, `core/events/lifecycle/events/client.py`
- **Interface Skeleton**:
  ```python
  # parrot/observability/attribution.py  (new)
  class UsageAttribution(BaseModel):
      """Immutable SDD attribution for one dispatched unit of work."""
      model_config = ConfigDict(frozen=True, extra="forbid")
      feat_id: Optional[str] = None
      task_id: Optional[str] = None
      attempt_uid: Optional[str] = None
      execution_id: Optional[str] = None
      dispatch_kind: Optional[str] = None
      roster_seat: Optional[str] = None
      accounting_seat: Optional[str] = None

  # parrot/observability/context.py  (modifies context.py:156-189)
  current_usage_attribution: ContextVar[Optional[UsageAttribution]]  # beside current_run_id:156

  @contextmanager
  def usage_attribution(                       # verified: context.py:162
      run_id: Optional[str],
      seat: Optional[str] = None,
      attribution: Optional[UsageAttribution] = None,
  ) -> Iterator[None]:
      """Bind run/seat AND full SDD attribution; token-based, nesting-safe."""

  # parrot/core/events/lifecycle/events/client.py  (modifies client.py:70-75)
  class AfterClientCallEvent(LifecycleEvent):   # verified: client.py:45
      attribution: Optional[UsageAttribution] = None
      """Snapshotted at construction from current_usage_attribution, exactly as
      agent_name/user_id/session_id already are (client.py:58-65)."""

  # parrot/observability/recorders/models.py  (modifies models.py:76-85)
  class UsageRecord(BaseModel):                 # verified: models.py:22
      feat_id: Optional[str] = None
      task_id: Optional[str] = None
      attempt_uid: Optional[str] = None
      execution_id: Optional[str] = None
      dispatch_kind: Optional[str] = None
      roster_seat: Optional[str] = None
  ```

### Module 2: Four-counter usage normalization
- **Path**: `packages/ai-parrot/src/parrot/models/basic.py` (modifies)
- **Responsibility**: Carry cache/reasoning counters and provider cost end to end instead of dropping them.
- **Depends on**: Module 1 (shares `events/client.py`)
- **Interface Skeleton**:
  ```python
  # parrot/models/basic.py  (modifies basic.py:48)
  class CompletionUsage(BaseModel):             # verified: basic.py:48
      cache_read_tokens: int = Field(0, validation_alias=AliasChoices(
          "cache_read_tokens", "cache_read_input_tokens", "cached_input_tokens"))
      cache_creation_tokens: int = Field(0, validation_alias=AliasChoices(
          "cache_creation_tokens", "cache_creation_input_tokens", "cache_write_input_tokens"))
      reasoning_output_tokens: int = 0
      """Codex reports this; no slot existed before. __add__ sums it field-wise."""

  # parrot/core/events/lifecycle/events/client.py  (modifies client.py:70-75)
      cache_read_tokens: Optional[int] = None
      cache_creation_tokens: Optional[int] = None
      reasoning_output_tokens: Optional[int] = None
      source_cost_usd: Optional[float] = None
      """Provider-reported cost (Claude SDK total_cost_usd, codex.turn.cost_microusd).
      Reconciliation input ONLY — never the reported value (FEAT-710 G5)."""

  # parrot/flows/dev_loop/dispatchers/claude.py  (modifies claude.py:977)
      async def _emit_usage_event(self, usage_detail, *, run_id, node_id, profile) -> None:
          """Now forwards cache_creation_input_tokens / cache_read_input_tokens /
          total_cost_usd already extracted at claude.py:965-967."""
  ```

### Module 3: Price tier, refresh & revisioning
- **Path**: `packages/ai-parrot/src/parrot/observability/cost/calculator.py` (modifies)
- **Responsibility**: Add a cache-creation tier, honour `valid_from`, stamp every cost with the price revision, refresh coverage.
- **Depends on**: Module 2
- **Interface Skeleton**:
  ```python
  # parrot/observability/cost/calculator.py  (modifies calculator.py:190)
  class PricedCost(BaseModel):
      usd: Optional[float]
      price_revision: Optional[str]   # content hash of the provider file
      valid_from: Optional[str]
      priced: bool

  class CostCalculator:                         # verified: calculator.py:135
      def cost_usd(                             # verified: calculator.py:190
          self, *, provider: str, model: str, input_tokens: int, output_tokens: int,
          cached_input_tokens: int = 0, cache_creation_tokens: int = 0,
          at: Optional[date] = None,
      ) -> Optional[float]:
          """Unchanged return contract. `at` selects the entry whose valid_from
          window covers it; None still means 'not priced', never a guess."""

      def price_call(self, **kwargs: Any) -> PricedCost:
          """Same arithmetic, plus the revision that produced it (S9)."""
  ```
  Price-file entries gain `cache_creation_per_1m`; every provider file is refreshed
  and extended with the models actually run (`gpt-5.6-terra`, `gpt-5.6-sol`,
  `zai.glm-4.7-flash`, `qwen`, `minimax.minimax-m2.5`, `mistral.devstral-2-123b`,
  `gemini-3.5-flash`, the Claude 5 family).

### Module 4: Codex usage codec
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex_usage.py` (new)
- **Responsibility**: Parse exactly one terminal usage observation out of the `codex exec --json` stream.
- **Depends on**: Module 2
- **Interface Skeleton**:
  ```python
  # parrot/flows/dev_loop/dispatchers/codex_usage.py  (new)
  class CodexUsageCodec:
      """Decode codex exec --json usage events. Deliberately NOT in _shared.py:
      twelve sibling dispatchers import that module, and dev_loop must not import
      ai-parrot-client-openai merely to parse CLI output (design review S7)."""
      def observe(self, event: dict[str, Any]) -> None:
          """Fold one stream event; last terminal observation wins."""
      def result(self) -> Optional[CompletionUsage]:
          """The single aggregated usage for the turn, or None if never reported."""

  # parrot/flows/dev_loop/dispatchers/codex.py  (modifies codex.py:544)
      # emits AfterClientCallEvent from the codec, mirroring claude.py:977
  ```

### Module 5: Durable per-spec usage sink
- **Path**: `packages/ai-parrot/src/parrot/observability/recorders/spec_usage.py` (new)
- **Responsibility**: Persist attributed records so a separate process can read them.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # parrot/observability/recorders/spec_usage.py  (new)
  class SpecUsageRecorder(AbstractLogger):      # AbstractLogger verified: recorders/base.py:16
      """Durable per-feature usage sink. A SINK, not an EventProvider — the existing
      UsageRecordingSubscriber owns the subscription (run_ledger.py:1-14 pattern).

      Root resolution reuses FEAT-554's rule: derived from
      `git rev-parse --path-format=absolute --git-common-dir` so it lands in the
      MAIN checkout, and REFUSED if it resolves inside the worktree base — the
      dataset must outlive `git worktree remove` (telemetry.py:107-148).
      """
      name: str = "spec_usage"
      def __init__(self, root: Optional[Path] = None, *, worktree_base_path: str) -> None: ...
      async def record(self, record: UsageRecord) -> None:
          """Append one JSONL row keyed by feat_id. Fail-open: never raises, warns
          once (telemetry.py:308-311 posture)."""
      async def aclose(self) -> None:
          """Flush. Unlike RunLedgerRecorder.aclose this is NOT a no-op (S4)."""
  ```

### Module 6: Attempt roll-up derived from the sink
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py` (modifies)
- **Responsibility**: `AttemptUsageRow` becomes a derived roll-up, not an independent writer; aggregate by `attempt_uid` before counting cycles.
- **Depends on**: Module 5
- **Interface Skeleton**:
  ```python
  # parrot/flows/dev_loop/sdd_coder/telemetry.py  (modifies telemetry.py:160)
  def build_attempt_row(...) -> AttemptUsageRow:     # verified: telemetry.py:160
      """Now derives provider counters from the SpecUsageRecorder rows for this
      attempt_uid instead of reading record.usage directly. ledger_* fields and
      calibration_eligible are unchanged."""

  # parrot/observability/recorders/run_ledger.py  (modifies run_ledger.py:134)
      def by_seat(self) -> list[SeatUsage]:           # verified: run_ledger.py:134
          """Aggregates records by attempt_uid BEFORE counting cycles. Previously
          `rounds=len(cycles)` counted a harvested usage event and its paired
          ClientCallFailedEvent as two cycles (design review S3)."""
  ```

### Module 7: Engine binding & opt-in external ingestion
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (modifies)
- **Responsibility**: Build and bind the attribution at the execution boundary; gate external ingestion.
- **Depends on**: Modules 1, 5
- **Interface Skeleton**:
  ```python
  # parrot/flows/dev_loop/sdd_coder/engine.py  (modifies engine.py:623)
      async def begin_execution(                      # verified: engine.py:623
          self, feature: str, worktree: str, execution_id: str,
      ) -> "ExecutionPoolView":
          """Additionally constructs UsageAttribution and binds it for the
          execution. feat_id/task_id/attempt_uid/execution_id are already owned
          here (engine.py:482-508); nothing is inferred from cwd."""
  ```
  Interactive Claude Code / Codex OTLP ingestion is **opt-in, config-gated, and
  a reconciliation source only** (design review S8). It is not on the correctness
  path for any acceptance criterion until spike S1 passes with replay fixtures.

### Module 8: Reader — per-spec report, CLI and MCP
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py` (modifies)
- **Depends on**: Modules 5, 9
- **Interface Skeleton**:
  ```python
  # parrot/flows/dev_loop/usage_report.py  (modifies usage_report.py:125)
  def build_spec_usage_report(
      rows: Iterable[UsageRecord], feat_id: str, *, by: str = "task",
  ) -> UsageReport:
      """Per-feature sibling of build_usage_report (verified: usage_report.py:125),
      grouping by task/model/seat instead of run seat. Reuses CycleUsage/AgentUsage
      and the existing markdown + HTML renderers so the three views cannot disagree."""

  # parrot/knowledge/wiki/cli.py  (modifies cli.py:3229 — sibling of @wiki.group(name="ledger"))
  @wiki.group(name="usage")
  def usage() -> None:
      """Per-spec token and cost reporting."""
  ```

### Module 9: Pricing policy
- **Path**: `packages/ai-parrot/src/parrot/observability/cost/policy.py` (new)
- **Depends on**: Module 3
- **Interface Skeleton**:
  ```python
  # parrot/observability/cost/policy.py  (new)
  PolicyKind = Literal["billed", "subscription", "estimate"]

  class PricingPolicy(BaseModel):
      """Per-seat cost policy, DERIVED not configured (U4): codex reports auth_mode
      and plan_type; the Claude Agent SDK reports a plan seat."""
      kind: PolicyKind
      def apply(self, priced: "PricedCost") -> tuple[Optional[float], Optional[float]]:
          """Return (usd, equivalent_usd). A subscription seat reports usd=0.0 with
          list price as equivalent_usd, so a plan-based run never inflates a spec
          with money that was never spent."""
  ```

---

## 4. Test Specification

### Unit Tests
- `UsageAttribution` is frozen and rejects extras; partial attribution is legal.
- Event carries the attribution snapshot taken at construction, not at dispatch.
- `CompletionUsage.__add__` sums the three new counters field-wise.
- `cost_usd` with `cache_creation_tokens` and a `valid_from` window; unpriced pair still returns `None`.
- `PricingPolicy.apply` returns `(0.0, list_price)` for a subscription seat.
- `CodexUsageCodec` over terminal / nested / missing / repeated usage events.
- `SpecUsageRecorder` refuses a root inside the worktree base; never raises on write failure.
- `by_seat()` counts one attempt with a usage event **and** a failure event as one cycle.

### Integration Tests
- An sdd-coder execution end-to-end produces durable rows readable by a second process.
- `wikitoolkit usage report --feat FEAT-NNN` renders against those rows.
- Cost is still computed exactly once per call with the new counters in play.

### Validation Contract

tests:
- packages/ai-parrot/tests/observability/test_usage_attribution.py
- packages/ai-parrot/tests/observability/test_usage_record_attribution.py
- packages/ai-parrot/tests/observability/test_run_ledger_recorder.py
- packages/ai-parrot/tests/unit/observability/test_cost_calculator.py
- packages/ai-parrot/tests/unit/observability/test_cost_computed_once.py
- packages/ai-parrot/tests/unit/observability/test_shared_cost_calculator.py
- packages/ai-parrot/tests/unit/observability/test_usage_models.py
- packages/ai-parrot/tests/unit/observability/test_usage_subscriber.py
- packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py
- packages/ai-parrot/tests/unit/events/lifecycle/test_usage_event_fields.py
- packages/ai-parrot/tests/test_completion_usage.py
- packages/ai-parrot/tests/unit/models/test_completion_usage_add.py
- packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py
- packages/ai-parrot/tests/flows/dev_loop/test_cli_dispatcher_usage_events.py
- packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py
markers: none

### Test Data / Fixtures
Captured `codex exec --json` event streams (terminal, nested, missing, repeated
usage) under `packages/ai-parrot/tests/fixtures/codex_usage/`; a frozen
two-revision price-table pair for the `valid_from` tests.

---

## 5. Acceptance Criteria

- [ ] AC-1. `UsageRecord` carries `feat_id`, `task_id`, `attempt_uid`, `execution_id`, `dispatch_kind`, `roster_seat`, and the existing `run_id`/`seat` are unchanged.
- [ ] AC-2. Attribution is read from the event when present and from the ContextVar only as a fallback; a test proves a forwarded event keeps its original attribution.
- [ ] AC-3. `CompletionUsage` and `AfterClientCallEvent` carry `cache_read`, `cache_creation` and `reasoning_output` counters; `dispatchers/claude.py` no longer drops the cache/cost it extracts at claude.py:965-967.
- [ ] AC-4. `test_cost_computed_once.py` still passes — cost is computed exactly once per LLM call (FEAT-710 G5) with the new counters present.
- [ ] AC-5. `source_cost_usd` is stored and never reported as the spec's cost.
- [ ] AC-6. Every price file has a `cache_creation_per_1m` tier, and a documented ≥90% of attempt rows in `artifacts/logs/sdd-coder-usage/` resolve to a priced `(provider, model)` pair. **Blocking** (U3).
- [ ] AC-7. Every computed cost records the price revision and the `valid_from` window used; re-pricing a historical row against a different revision is explicit, not silent.
- [ ] AC-8. The codex seat reports non-zero provider tokens for a real attempt.
- [ ] AC-9. `attempt_uid` and `execution_id` appear in **no** metric label; a cardinality regression test asserts the whitelist.
- [ ] AC-10. `SpecUsageRecorder` rows survive process exit and `git worktree remove`, and are readable by a separate process.
- [ ] AC-11. One attempt that emits a usage event and a failure event counts as **one** cycle.
- [ ] AC-12. `wikitoolkit usage report --feat FEAT-NNN` renders tokens and cost grouped by task, model and seat, with a paired MCP tool.
- [ ] AC-13. A subscription seat reports `usd = 0.0` with list price as `equivalent_usd`.
- [ ] AC-14. No `usage.*` event kind exists in `LedgerEventKind` and no file under `knowledge/wiki/ledger/` is modified.

---

## 6. Codebase Contract

Verified against base commit `c2077ec43e` (2026-10-31). Every entry below was
re-checked at spec time; the proposal's own 45 citation probes are at
`sdd/state/FEAT-783/`.

### Verified Imports
```python
from parrot.observability.context import current_run_id, current_seat   # context.py:156,158
from parrot.observability.context import usage_attribution              # context.py:162
from parrot.observability.recorders.base import AbstractLogger          # base.py:16
from parrot.observability.recorders.models import UsageRecord           # models.py:22
from parrot.observability.recorders.run_ledger import RunLedgerRecorder # run_ledger.py:65
from parrot.observability.cost.calculator import CostCalculator         # calculator.py:135
from parrot.models.basic import CompletionUsage                         # basic.py:48
from parrot.flows.dev_loop.usage_report import build_usage_report       # usage_report.py:125
```

### Existing Class Signatures
| Symbol | Signature | Location |
|---|---|---|
| `CostCalculator.cost_usd` | `(self, *, provider: str, model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> Optional[float]` | calculator.py:190 |
| `AbstractLogger.record` | `async (self, record: UsageRecord) -> None` | base.py:30 |
| `AbstractLogger.aclose` | `async (self) -> None` (default no-op) | base.py:46 |
| `RunLedgerRecorder.by_seat` | `(self) -> list[SeatUsage]` | run_ledger.py:134 |
| `SddCoderEngine.begin_execution` | `async (self, feature: str, worktree: str, execution_id: str) -> "ExecutionPoolView"` | engine.py:623 |
| `SddCoderToolkit.coder_end_execution` | `async (self, execution_id: str) -> CoderResult` | toolkit.py:438 |
| `build_usage_report` | `(ledger: RunLedgerRecorder, run_id: str) -> UsageReport` | usage_report.py:125 |
| `resolve_durable_root` | `(configured: Optional[str], *, worktree_base_path: str) -> Path` | telemetry.py:107 |
| `build_attempt_row` | `(...) -> AttemptUsageRow` | telemetry.py:160 |
| `_compute_call_cost` | `(self, client_name, model, input_tokens, output_tokens) -> Optional[float]` | base.py:792 |
| `usage_attribution` | `(run_id: Optional[str], seat: Optional[str] = None) -> Iterator[None]` | context.py:162 |
| `build_recorders_from_config` | `(config: "ObservabilityConfig") -> "list[AbstractLogger]"` | factory.py:22 |

### Integration Points
- `UsageBackend = Literal["none", "logging", "prometheus", "otel", "traceloop"]` — config.py:17; a new backend value extends this Literal.
- `ObservabilityConfig.pricing_override_path` / `PARROT_PRICING_PATH` — config.py:215, 282.
- `@wiki.group(name="ledger")` — cli.py:3229 (click, **not** argparse).
- `DEV_LOOP_CODER_TELEMETRY` gates the existing `CoderTelemetrySink`.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.observability.recorders.SpecUsageRecorder`~~ — does not exist (this spec creates it)
- ~~`parrot.observability.context.current_feat_id`~~ — does not exist
- ~~`UsageRecord.feat_id`~~ / ~~`UsageRecord.cache_read_tokens`~~ — no such fields today
- ~~`CompletionUsage.cache_creation`~~ — not a field; cache data survives only in `extra_usage`
- ~~`CostCalculator` honouring `valid_from`~~ — the string appears nowhere in calculator.py
- ~~`usage_report.feat_id`~~ — the report is keyed by `run_id`/seat only
- ~~any `usage` symbol under `knowledge/wiki/ledger/`~~ — none; and none is to be added (AC-14)
- ~~`dispatchers/codex.py` usage extraction~~ — no `input_tokens` anywhere in the file
- ~~`LedgerService.register_plane()`~~ — no generic plane seam exists
- ~~`sdd/state/<FEAT-ID>/state.json` `current_task` / `attempt_uid`~~ — not in the schema

### Edit Sites (Blueprint Anchors)

Verified against: `c2077ec43e`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/observability/attribution.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/observability/recorders/spec_usage.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/observability/cost/policy.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex_usage.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/observability/context.py` | MODIFY | `current_seat: ContextVar[Optional[str]] = ContextVar("parrot_current_seat", default=None)` | `context.py:158` | 1 |
| `packages/ai-parrot/src/parrot/observability/context.py` | MODIFY | `def usage_attribution(` | `context.py:162` | 1 |
| `packages/ai-parrot/src/parrot/observability/recorders/models.py` | MODIFY | `    # ── FEAT-479: honesty + failure. ──` | `models.py:82` | 1 |
| `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | MODIFY | `from parrot.observability.context import current_run_id, current_seat` | `subscriber.py:23` | 1 |
| `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | MODIFY | 2 sites — disambiguate by the preceding line: `trace_id = event.trace_context.trace_id if event.trace_context else None` / `run_id = current_run_id.get()` / `        seat = current_seat.get()` | `subscriber.py:114` and `:147` | 2 |
| `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` | MODIFY | 4 sites — disambiguate by the enclosing dict: token/cost `base = {` block at `:217` uses `"gen_ai.response.model": event.model,` before `"parrot.agent.name": event.agent_name or "unknown",  # FEAT-228` | `metrics.py:207,221,272,303` | 4 |
| `packages/ai-parrot/src/parrot/models/basic.py` | MODIFY | `class CompletionUsage(BaseModel):` | `basic.py:48` | 1 |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | MODIFY | `class AfterClientCallEvent(LifecycleEvent):` | `client.py:45` | 1 |
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | `    def _compute_call_cost(` | `base.py:792` | 1 |
| `packages/ai-parrot/src/parrot/observability/cost/calculator.py` | MODIFY | `    def cost_usd(` | `calculator.py:190` | 1 |
| `packages/ai-parrot/src/parrot/observability/cost/calculator.py` | MODIFY | `        cached_per_1m: float = price.get("cached_input_per_1m", input_per_1m)` | `calculator.py:229` | 1 |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/anthropic.json` | MODIFY | `      "cached_input_per_1m": 0.30,` (19 occurrences — per-model; edit all) | `anthropic.json:11` | 19 |
| `packages/ai-parrot/src/parrot/observability/recorders/factory.py` | MODIFY | `    if backend == "logging":` | `factory.py:40` | 1 |
| `packages/ai-parrot/src/parrot/observability/config.py` | MODIFY | `UsageBackend = Literal["none", "logging", "prometheus", "otel", "traceloop"]` | `config.py:17` | 1 |
| `packages/ai-parrot/src/parrot/observability/recorders/run_ledger.py` | MODIFY | `    def by_seat(self) -> list[SeatUsage]:` | `run_ledger.py:134` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | `    async def _emit_usage_event(` | `claude.py:977` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` | MODIFY | `cmd += ["--json", "--output-schema", schema_path, "-o", output_path]` | `codex.py:544` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `    async def begin_execution(` | `engine.py:623` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py` | MODIFY | `def build_attempt_row(` | `telemetry.py:160` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py` | MODIFY | `def build_usage_report(ledger: RunLedgerRecorder, run_id: str) -> UsageReport:` | `usage_report.py:125` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `@wiki.group(name="ledger")` | `cli.py:3229` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **FEAT-228** — widen the attribution dimension of existing metrics; shipped complete (6/6 tasks, 2026-06-08).
- **FEAT-479 `run_ledger.py:1-14`** — a SINK, not an `EventProvider`; the existing subscriber owns the subscription.
- **FEAT-554 `telemetry.py:107-148, 308-311`** — durable root via git-common-dir, refused inside a worktree; fail-open writes that never change a dispatch outcome.
- **`events/client.py:58-65`** — snapshot ContextVars onto the event at construction.
- **TASK-4020** — ship the CLI subcommand and its MCP tool in one task.

### Known Risks / Gotchas
- `cumulative_cost_usd` is **process-cumulative**; an sdd-worker outliving several tasks yields a rising number that must never be summed per task.
- `execution_id` is empty on 332 of 1090 historical rows (retrofitted by FEAT-559) — treat as optional.
- `coder_end_execution` has an open defect (`issue:cc372f700a47`) making it unreliable as a settlement signal; do not emit per-execution totals there.
- `engine.py` is the package's hottest file with open encapsulation defects (`issue:700660c7f663`) at `begin_execution`.
- Codex sdd-coder seats can never commit (`issue:c4d0e7a028ca`), so codex attempts are routinely abandoned — their cost is real and must not be dropped.
- `openai_base.py:1533` fabricates `CompletionUsage(0,0,0)` when a provider reports nothing; `usage_reported=False` is what distinguishes that from a real zero.
- A hook in the **user** setting source never fires for a sandboxed `sdd-worker` (HOTFIX-6756c929a450) — relevant only to the opt-in interactive path.
- `wikitoolkit` warm start is p50 ~415-425 ms (`issue:f0a40d0853f2`); nothing on the hot path may shell out to it.

### External Dependencies
None new. Claude Code 2.1.314 and codex-cli 0.164.0 are the pinned versions the research was verified against.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-783; the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (both modify `core/events/lifecycle/events/client.py`)
  - M3 → M2 (prices the counters M2 introduces)
  - M4 → M2 (emits the four counters)
  - M5 → M1 (persists the widened `UsageRecord`)
  - M6 → M5 · M7 → M1, M5 · M9 → M3 · M8 → M5, M9
  - M1, M2 and M3 form the critical path; M4 can run concurrently with M5.
- **Shared files** (their tasks serialize): `recorders/models.py` (M1, M3, M9), `core/events/lifecycle/events/client.py` (M1, M2), `cost/calculator.py` (M3, M9).
- **Exclusive resources**: none — no extension rebuild, no lockfile change, no migration.
- **Cross-feature dependencies**: none blocking. `TASK-4381` (HelixLedgerStore) touches the ledger, which this spec does not.

---

## 8. Open Questions

- [x] Ride FEAT-710's stream or open a separate priced path? — *Resolved in proposal*: ride FEAT-710; widen `UsageRecord` + ContextVars + one `AbstractLogger` sink, reading the origin's `cost_usd`.
- [x] Which seats are in v1? — *Resolved in proposal*: all three. Narrowed by design review S8 — the **dispatched** Claude coder seat is already wired via the Agent SDK, so S1 gates only the interactive session.
- [x] Who owns the price table? — *Resolved in proposal*: extend `observability/cost/pricing/*.json`; coverage is a **blocking** prerequisite (AC-6).
- [x] How does a subscription seat appear? — *Resolved in proposal*: `usd = 0.0` with list price as `equivalent_usd`, derived from `auth_mode` / `plan_type`.
- [x] Reporting or enforcement? — *Resolved in proposal*: reporting only in v1, designed enforcement-ready.
- [x] Which usage dataset survives? — *Resolved at spec time*: `UsageRecord` is the per-call source of truth; `AttemptUsageRow` becomes a derived roll-up (M6).
- [x] Which "seat" vocabulary wins? — *Resolved at spec time*: none. `dispatch_kind`, `roster_seat` and `accounting_seat` are separate fields; the word is never overloaded.
- [ ] **S1 (gate, interactive seat only)** — does a sub-agent's `claude_code.api_request` carry the parent `session.id`, an `agent_id` matching `SubagentStop`, and `agent.name`? The docs state neither this nor its declared `prompt.id` fallback. Needs one captured run under an OTLP file exporter. Blocks only M7's opt-in path.
- [ ] **S3 remainder** — one captured `codex exec --json` run to confirm the stdout event's token field names, to seed M4's fixtures.
- [ ] **S4 reconciliation** — the three-seat run against provider dashboards, to fix the drift tolerance.
- [ ] Target price-coverage threshold: AC-6 proposes ≥90% of recorded attempt rows. Confirm before implementation.

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · codex-cli 0.164.0 · Status: completed
> Transcript: `sdd/state/FEAT-783/design_research/`
> All 22 cited paths passed containment + existence checks; every claim was
> spot-checked against the source before disposition.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Carry one explicit attribution object through dispatch and lifecycle events (architecture) | CONFIRM | Attribution really is split across `DispatchLabels`, `usage_attribution()`, `AttemptUsageRow` and engine-local ids | §2 Overview, §3 M1 |
| S2 | Put attribution on the event, not only in the subscriber ContextVar (api) | CONFIRM | Verified: the event already snapshots `agent_name`/`user_id`/`session_id` from ContextVars at construction (client.py:58-65) — this follows the file's own pattern | §3 M1, §6 |
| S3 | Aggregate failure markers by `attempt_uid` instead of treating them as cycles (risk) | CONFIRM | Verified: `by_seat()` sets `rounds=len(cycles)` (run_ledger.py:134-165) and claude.py:1051-1060 emits a usage event *then* a failure event — one attempt becomes two cycles | §3 M6, §5 AC-11 |
| S4 | Make the authoritative store durable or narrow the CLI guarantee (architecture) | CONFIRM (scope noted) | Verified in-memory with a no-op `aclose()`. Scope note: the reviewer's "extend `CoderTelemetrySink` as canonical" option is excluded by a user decision — `UsageRecord` stays the source of truth | §3 M5, §5 AC-10 |
| S5 | Normalize cache counters and provider cost before fan-out (api) | CONFIRM | Verified: claude.py:965-967 already extracts cache counters and `total_cost_usd`, then drops them for lack of event slots | §3 M2, §5 AC-3 |
| S6 | Keep attempt and execution IDs out of metric labels (risk) | CONFIRM | `attempt_uid`/`execution_id` are unbounded; metrics.py:8-10 already forbids unbounded labels by contract | §3 M1, §5 AC-9 |
| S7 | Use a dedicated Codex usage codec, not the generic shared dispatcher module (alternative) | CONFIRM (overrides the proposal) | `_shared.py` is imported by twelve siblings, and reaching into `ai-parrot-client-openai` from `dev_loop` inverts the dependency direction | §3 M4 |
| S8 | Treat Claude Code OTLP ingestion as an opt-in reconciliation source (risk) | CONFIRM (corrects the proposal) | Verified and material: `dispatchers/claude.py` drives the Agent SDK and FEAT-479 M6 already harvests usage into the event. The proposal's "both CLI seats are outside AbstractClient" is wrong for the dispatched coder seat | §2 Overview, §3 M7, §8 |
| S9 | Version the price source on every computed cost (risk) | CONFIRM | Verified: `valid_from` appears nowhere in calculator.py, so a refresh silently changes historical answers — and U3 mandates a refresh | §3 M3, §5 AC-7 |

Summary: **9** confirmed · **0** rejected · **0** escalated.

Two confirmations (S7, S8) contradict the accepted proposal and were adopted over
it, which is the evidence that this was a review and not a ratification: the brief
carried only the accepted exploration document and verified code anchors.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-31 | Jesus Lara | Initial spec from the FEAT-783 research proposal; 9 design-research suggestions folded in |
