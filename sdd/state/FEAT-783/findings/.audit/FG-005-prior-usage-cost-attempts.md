---
id: FG-005
query_id: Q039
type: git_log
intent: "Any prior attempt at usage/cost accounting in this repo, merged or abandoned."
executed_at: 2026-10-30T22:42:00Z
duration_ms: 1400
parent_id: null
depth: 0
---

# FG-005 — A priced usage pipeline already shipped (FEAT-710, merged), and an earlier in-process bridge was rejected by review as the wrong shape

## Summary

There is not one prior attempt but **three**, and the history is a decided
architectural argument the proposal must answer rather than restate.

1. **FEAT-550 token-budget-bedrock** (2026-09-11/12, merged) built
   `parrot.clients.budget` — a "QuestionBudget Atomic Ledger", `BudgetScope`,
   `BudgetRegistry`, an AbstractClient budget gate and settled-estimate
   reporting.
2. **FEAT-775 "Parrot telemetry bridge"** (2026-10-20, draft spec, **PR #1747
   CLOSED**) proposed an in-process `TelemetryBridge` writing a priced
   `TelemetryEvent` to BigQuery. It was rejected, and the FEAT-710 spec records
   why in its own problem statement: it "would have added a fourth in-process
   subscriber to every LLM call, **recomputed cost a fourth time**, run BigQuery
   I/O in the agent process, **collided with the existing
   `parrot.observability.setup_telemetry`**, and introduced a TROC-specific
   `program_slug` concept into the framework."
3. **FEAT-710 parrot-telemetry-event-fanout** (merged, PR #1772, 2026-10-22)
   is what replaced it. Its G5 is decisive for FEAT-783: **"Cost is computed
   exactly once per LLM call"** — at the origin in `clients/base.py`, with a
   process-shared `CostCalculator` — because *three* subscribers were each
   computing it independently (`UsageRecordingSubscriber`,
   `MetricsSubscriber`, trace subscriber).

Consequences for the brainstorm's "Does NOT exist" list: a cost/price facility
(`observability/cost/calculator.py:135` `CostCalculator`, `:190`
`cost_usd(provider, model, input_tokens, output_tokens, cached_input_tokens)`)
**does** exist and is process-shared; a PII-free `UsageRecord`
(`observability/recorders/models.py:22`) with tokens and cost **does** exist;
`CompletionUsage` on `AIMessage.usage` (`models/basic.py:48`) **does** exist
with `estimated_cost`. OTel is also live in-process — `3b20dd97f9`
(2026-10-29, PR #1875) fixes flushing OpenTelemetry before a hard exit.

The one genuinely unmerged branch is `origin/sdd/FEAT-774-775-telemetry`, and
it is **stale, not in flight**: it carries only the two draft specs, and the
FEAT-775 half is explicitly superseded ("replaces the FEAT-775 draft of the
closed PR #1747"). FEAT-774 (the `TelemetryEvent` contract + BigQuery sink)
lands **upstream in navigator-eventbus**, not in this repo.

## Citations

- path: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
  lines: 1-12
  symbol: `FEAT-710`
  excerpt: |
    # Feature Specification: Parrot telemetry event fan-out (lifecycle events -> EventBus)
    **Feature ID**: FEAT-710
    **Jira**: NVP-506 (epic NVP-502) — replaces the FEAT-775 draft of the closed PR #1747

- path: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
  symbol: `G5 — cost computed exactly once`
  excerpt: |
    G5. **Cost is computed exactly once per LLM call.** Today each subscriber computes it
    independently from the same `AfterClientCallEvent`: `UsageRecordingSubscriber`
    (`recorders/subscriber.py:103-104`), `MetricsSubscriber` (`subscribers/metrics.py:243-244`)
    and the trace subscriber (`subscribers/trace.py:276-277`).
    After this feature, the origin computes it (`clients/base.py`) and all three
    subscribers read `event.cost_usd`.

- path: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
  symbol: `why the in-process bridge was rejected`
  excerpt: |
    The closed PR #1747 proposed doing this with a `TelemetryBridge` *inside* ai-parrot.
    That design would have added a fourth in-process subscriber to every LLM call,
    recomputed cost a fourth time, run BigQuery I/O in the agent process, collided with
    the existing `parrot.observability.setup_telemetry`, and introduced a TROC-specific
    `program_slug` concept into the framework.

- path: `packages/ai-parrot/src/parrot/observability/cost/calculator.py`
  lines: 135-190
  symbol: `CostCalculator.cost_usd`
  excerpt: |
    # cited by sdd/specs/parrot-telemetry-bridge.spec.md "Integration Points" table:
    | Cost | packages/ai-parrot/src/parrot/observability/cost/calculator.py:135 CostCalculator,
             :190 cost_usd(*, provider, model, input_tokens, output_tokens, cached_input_tokens=0) |

- path: `packages/ai-parrot/src/parrot/observability/recorders/models.py`
  lines: 22
  symbol: `UsageRecord`
  excerpt: |
    # cited by sdd/specs/telemetry-event-contract-bq-sink.spec.md:
    - **Parrot usage** (`UsageRecord`) deliberately carries no user, session or tenant.
    # and by parrot-telemetry-bridge.spec.md:
    `UsageRecord` (`observability/recorders/models.py:22`) has tokens and cost but,
    **by PII contract**, no user, session or agent (docstring :1-11).

- path: `packages/ai-parrot/src/parrot/models/basic.py`
  lines: 48
  symbol: `CompletionUsage`
  excerpt: |
    # cited by parrot-telemetry-bridge.spec.md "Integration Points":
    | Usage model | packages/ai-parrot/src/parrot/models/responses.py:143 AIMessage.usage: CompletionUsage;
      models/basic.py:48 CompletionUsage (prompt_tokens, completion_tokens, total_tokens,
      total_time, estimated_cost, extra_usage) |

- path: `sdd/specs/telemetry-event-contract-bq-sink.spec.md`
  symbol: `FEAT-774 — unmerged, lands upstream`
  excerpt: |
    **Feature ID**: FEAT-774 (cross-repo ID, reserved in `fieldsync/sdd/FEAT_ID_LEDGER.md`)
    **Target package**: `navigator-eventbus` ... The code lands upstream; this spec lives
    in ai-parrot because the bus was extracted from parrot (FEAT-313/317)

- path: `.`
  symbol: `git branch -r --no-merged origin/dev | grep telemetry`
  excerpt: |
    origin/sdd/FEAT-774-775-telemetry
    $ git diff --name-only origin/dev...origin/sdd/FEAT-774-775-telemetry
    sdd/specs/parrot-telemetry-bridge.spec.md
    sdd/specs/telemetry-event-contract-bq-sink.spec.md      # specs only, no code

- path: `packages/ai-parrot/src/parrot/observability/`
  symbol: `OTel is live in-process`
  excerpt: |
    b0497c2b48|2026-10-30|Merge pull request #1875 from phenobarbital/fix/otel-shutdown-flush
    3b20dd97f9|2026-10-29|fix(run): flush OpenTelemetry before the hard exit bypasses atexit
    971de4b690|2026-10-19|sdd: complete TASK-4484 — setup_telemetry metric fan-out

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  symbol: `an opt-in usage sink already exists in sdd_coder`
  excerpt: |
    77e1582f76|2026-09-21|fix(sdd-coder): always bind the durable evidence store, keep only the
                           usage sink opt-in
    375e966b39|2026-10-21|test(dev_loop): pin DEV_LOOP_CODER_TELEMETRY in test_disabled_binds_no_scope

## Notes

The FEAT-774/775 ids are **cross-repo ids reserved in
`fieldsync/sdd/FEAT_ID_LEDGER.md`**, not in this repo's `.id_ledger.json` —
they collide with ai-parrot's own FEAT-774 (delegated-auth / parrot login) and
FEAT-778 (domain-experts). Anyone reading those two spec files must not assume
they belong to this repo's numbering.

Jira context worth carrying into the proposal: epic **NVP-502** (Telemetría y
KPIs del ecosistema Navigator), with NVP-505 (contract + BQ sink) and NVP-506
(parrot bridge, delivered as FEAT-710). FEAT-783 is a *second* consumer of the
same priced usage stream, for a different axis (per-spec/per-task rather than
per-tenant/per-user) — the proposal should say whether it rides that stream or
opens a parallel one, because review has already rejected a parallel one once.

[cross-lane: type=read, intent=read observability/cost/calculator.py and recorders/models.py — the existing price table and UsageRecord the brainstorm assumes do not exist]
[cross-lane: type=read, intent=read observability/recorders/subscriber.py UsageRecordingSubscriber:47 — the merged precedent for a usage sink subscribing to AfterClientCallEvent]
[cross-lane: type=grep, intent=confirm the four token counters (cache_read/cache_creation) survive into CompletionUsage, since the brainstorm's cost model depends on all four]
