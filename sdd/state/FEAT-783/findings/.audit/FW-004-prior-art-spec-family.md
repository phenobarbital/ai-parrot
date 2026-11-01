---
id: FW-004
query_id: Q001
type: wiki_query
intent: "Orient: prior art — which specs in this repo already cover usage, cost and telemetry."
executed_at: 2026-10-30T22:39:16Z
duration_ms: 0
parent_id: FW-001
depth: 2
---

# FW-004 — Fifteen committed specs already cover usage/cost/telemetry; FEAT-228 "Per-Agent Cost & Usage Metrics" is `approved` and names the exact attribution defect

## Summary

This problem space has been specced repeatedly. `sdd/specs/` holds 15 specs matching
usage/cost/telemetry/token/observability. The closest is `per-agent-cost-usage-metrics.spec.md`
(**FEAT-228, 2026-06-08, Status: approved**), whose Problem Statement is a precise statement of the
same structural defect the source is circling, one level down the stack: cost and token **metrics**
are labelled with `gen_ai.system` + `gen_ai.response.model` **only**, so you cannot slice spend by
agent — the attribution exists in traces but not in the aggregated metric layer.

Any proposal must position itself against this family rather than re-derive it: the correct framing
is "extend the existing attribution dimension from {provider, model, agent} to
{feat_id, task_id, attempt_uid, execution_id, seat}", not "build a usage plane".

## Citations

- path: `sdd/specs/per-agent-cost-usage-metrics.spec.md`
  lines: 1-20
  symbol: frontmatter + header
  excerpt: |
    type: feature
    base_branch: dev
    # Feature Specification: Per-Agent Cost & Usage Metrics
    **Feature ID**: FEAT-228
    **Date**: 2026-06-08
    **Status**: approved

- path: `sdd/specs/per-agent-cost-usage-metrics.spec.md`
  lines: 21-45
  symbol: §1 Problem Statement
  excerpt: |
    But the **metrics** for LLM client calls — cost (USD), token usage, and
    request duration — are labelled with `gen_ai.system` (provider) and
    `gen_ai.response.model` **only**. See `subscribers/metrics.py:_on_client_after`,
    where base = {"gen_ai.system": system, "gen_ai.response.model": model}
    and self._client_cost_total.add(cost, attributes=base).
    Consequence: ... you **cannot** slice "USD cost per agent" or "tokens per agent"
    from the metrics layer.

- path: `sdd/specs/`
  lines: 1-1
  symbol: related spec inventory
  excerpt: |
    per-agent-cost-usage-metrics.spec.md   otel-observability.spec.md
    tokens-observability.spec.md           unified-telemetry-bus.spec.md
    devflow-telemetry-accounting.spec.md   invoke-telemetry.spec.md
    sdd-coder-bedrock-token-telemetry.spec.md  token-budget-bedrock.spec.md
    bedrock-per-round-token.spec.md        parrot-telemetry-event-fanout.spec.md
    observability-otel-grafana.spec.md     observability-metrics-fanout-and-env-config.spec.md
    merge-tier-validation-cost.spec.md     openai-max-completion-tokens.spec.md
    services-vault-token-sync-tech-debt.spec.md

- path: `packages/ai-parrot/src/parrot/observability/subscribers/`
  lines: 1-1
  symbol: `metrics.py` / `trace.py`
  excerpt: |
    # per FEAT-228 §1: trace.py:349 writes parrot.agent.name onto the invoke span;
    # metrics.py:_on_client_after labels cost/token counters with provider+model only.

## Notes

`sdd-coder-bedrock-token-telemetry.spec.md` (the largest at ~11k tokens) and
`devflow-telemetry-accounting.spec.md` are the two that overlap the dev-loop seat specifically.
Neither was read in this lane.

[cross-lane: type=read, intent=Read sdd/specs/per-agent-cost-usage-metrics.spec.md fully and determine whether FEAT-228 was ever implemented (check sdd/tasks/index/per-agent-cost-usage-metrics.json)]
[cross-lane: type=git_log, intent=git log on observability/subscribers/metrics.py to see whether the FEAT-228 agent-attribution fix landed]
