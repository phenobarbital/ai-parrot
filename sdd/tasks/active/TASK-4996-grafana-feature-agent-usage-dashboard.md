# TASK-4996: Sample Grafana dashboard — usage & cost by feature and by agent

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4985, TASK-4989
**Assigned-to**: unassigned

---

## Context

Spec AC-15 (added after decomposition at the user's request). The per-spec report
(TASK-4994/4995) is a CLI/MCP view. Operators also want a Grafana view of token usage and
cost **by feature** and **by agent**. The by-agent view already works, through the
FEAT-228 `parrot.agent.name` label. No metric carries a feature id today.

**Decision (user, 2026-10-31)**: add a bounded `parrot.feat_id` metric label. There is one
series per feature, which grows slowly. `task_id`, `attempt_uid` and `execution_id`
**stay forbidden** as labels (AC-9; unbounded cardinality).

---

## Scope

- In `MetricsSubscriber._on_client_after` and `_on_client_fail`, add `"parrot.feat_id": <attribution.feat_id or "none">` to the base attribute dicts. The value is always a string, because OTel label sets must be stable per series (same rule as FEAT-228's `"unknown"`).
- Apply `PricingPolicy` to the cost counter, so that subscription seats add `0.0` and the dashboard does not show money that was never spent. This matches the subscriber (TASK-4989, AC-13).
- Add `"parrot.feat_id"` to `METRIC_LABELS` in `test_dashboard_contract.py`.
- Create `parrot-sdd-feature-usage.json`. Byte-identical copies go in `docker/grafana/provisioning/dashboards-parrot/` and in `observability/examples/grafana-dashboards/`, matching how `parrot-usage-cost.json` is shipped. It has:
  - template variables `feat_id` and `agent` (multi-select, `label_values(...)`);
  - stat panels for total tokens and total cost in the time range;
  - timeseries panels for tokens by feature, cost by feature, tokens by agent, and cost by agent;
  - a table of feature × agent × model for tokens and cost;
  - a failures-by-feature panel.
- Tests for the new label and the policy-applied cost.

**NOT in scope**: per-task or per-attempt panels (those ids are not labels; use `wikitoolkit usage report`); a JSON or Infinity datasource; changes to `parrot-usage-cost.json`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` | MODIFY | `parrot.feat_id` label + policy on cost |
| `packages/ai-parrot/tests/unit/observability/test_dashboard_contract.py` | MODIFY | Allow `parrot.feat_id` |
| `docker/grafana/provisioning/dashboards-parrot/parrot-sdd-feature-usage.json` | CREATE | Provisioned dashboard |
| `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-sdd-feature-usage.json` | CREATE | Shipped example (identical copy) |
| `packages/ai-parrot/tests/unit/observability/test_metrics_feat_id_label.py` | CREATE | Label + policy tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.subscribers.metrics import MetricsSubscriber   # metrics.py
from parrot.observability.cost import resolve_event_cost                 # lazy import at metrics.py:243
from parrot.observability.cost.policy import PricingPolicy               # created by TASK-4989
```

### Existing Signatures to Use
```python
# subscribers/metrics.py
    async def _on_client_after(self, event: AfterClientCallEvent) -> None:   # :211
        base = {"gen_ai.system": ..., "gen_ai.provider.name": ..., "gen_ai.response.model": event.model,
                "parrot.agent.name": event.agent_name or "unknown",  # FEAT-228      (:221)
        }
        cost = resolve_event_cost(event, self._cost)                          # :245
        if cost is not None: self._client_cost_total.add(cost, attributes=base)   # :246-247
    async def _on_client_fail(self, event: ClientCallFailedEvent) -> None:    # :291 — base dict line :303
# `"parrot.agent.name": event.agent_name or "unknown",  # FEAT-228` occurs 4x (:207 before, :221 after, :272 round, :303 fail)
# tests/unit/observability/test_dashboard_contract.py
METRIC_LABELS: frozenset[str] = frozenset({...})   # :81 — label allowlist
FORBIDDEN_LABELS: frozenset[str] = frozenset({"user_id", "session_id"})
# Existing dashboard to copy structure/datasource from: docker/grafana/provisioning/dashboards-parrot/parrot-usage-cost.json
#   datasource {"type": "prometheus", "uid": "claudestats-prometheus"}; title "AI-Parrot — LLM Usage & Cost"
# event.attribution (TASK-4983), event.pricing_policy (TASK-4989)
```

### Does NOT Exist
- ~~a `parrot.feat_id` metric label~~ — this task creates it
- ~~`parrot.task_id` / `parrot.attempt_uid` / `parrot.execution_id` labels~~ — must never exist (AC-9)
- ~~`parrot-sdd-feature-usage.json`~~ — this task creates it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/observability/subscribers/metrics.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/observability/test_dashboard_contract.py", "action": "MODIFY"},
    {"path": "docker/grafana/provisioning/dashboards-parrot/parrot-sdd-feature-usage.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-sdd-feature-usage.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/observability/test_metrics_feat_id_label.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/subscribers/metrics.py#MetricsSubscriber",
    "sym:packages/ai-parrot/src/parrot/observability/cost/__init__.py#resolve_event_cost"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Do **not** add `parrot.feat_id` to the before-call or round metrics. It goes only where the dashboard needs it (after-call token/cost/duration, and failure). Fewer label sets mean less cardinality.
- PromQL label names: OTel→Prometheus export turns `parrot.feat_id` into `parrot_feat_id`. Check how the existing dashboard writes `parrot.agent.name` (as `parrot_agent_name`) and do the same; the contract test's normalization decides what passes.
- The dashboard queries only metrics listed in the contract test's metric set (`gen_ai.client.token.usage`, the cost counter, `gen_ai.client.operation.duration`, the error count). Never invent a metric name.
- Cost on the dashboard is post-policy: subscription seats show $0 (AC-13).

---

## Implementation Blueprint

### Steps (in order)
1. Add the feature label to the after-call and failure base dicts. A stable `"none"` value is needed because OTel label sets must not vary per series.
2. Apply the policy to the cost counter, so the dashboard and the per-spec report agree on cost.
3. Allow the label in the contract test.
4. Build the dashboard by copying `parrot-usage-cost.json`'s skeleton (datasource uid, refresh, time settings), then write the identical example copy.
5. Tests.

### `metrics.py` (MODIFY)
```python
# FILL IN: disambiguate — the anchor `"parrot.agent.name": event.agent_name or "unknown",  # FEAT-228` occurs 4x.
# Edit ONLY:
#   (a) the `base = {` dict inside _on_client_after (anchor line :221, preceded by `"gen_ai.response.model": event.model,`)
#   (b) the attributes dict inside _on_client_fail (anchor line :303)
# In both, add directly below the anchor:
            "parrot.feat_id": _feat_label(event),  # FEAT-783: bounded, one series per feature
```
```python
# NEW module-level helper (after imports):
def _feat_label(event: object) -> str:
    """FEAT-783: the event's SDD feature id as a stable metric label ("none" when unattributed)."""
    attribution = getattr(event, "attribution", None)
    return (attribution.feat_id if attribution is not None else None) or "none"
```
```python
# REPLACE the cost block at metrics.py:245-247:
        from parrot.observability.cost.policy import PricingPolicy  # noqa: PLC0415

        cost = resolve_event_cost(event, self._cost)
        cost, _equivalent = PricingPolicy.from_label(getattr(event, "pricing_policy", None)).apply(cost)
        if cost is not None:
            self._client_cost_total.add(cost, attributes=base)
```

### `test_dashboard_contract.py` (MODIFY)
```python
# In METRIC_LABELS (occurrences: 1 — `METRIC_LABELS: frozenset[str] = frozenset({`), add "parrot.feat_id",
# with a comment: "# FEAT-783: bounded per-feature label (task/attempt/execution ids stay forbidden)"
```

### `parrot-sdd-feature-usage.json` (CREATE ×2, identical)
```json
{
  "title": "AI-Parrot — SDD Usage by Feature & Agent",
  "uid": "parrot-sdd-feature-usage",
  "tags": ["ai-parrot", "sdd", "usage", "cost"],
  "templating": {"list": [
    {"name": "feat_id", "type": "query", "multi": true, "includeAll": true,
     "datasource": {"type": "prometheus", "uid": "claudestats-prometheus"},
     "query": "FILL IN: label_values(<token usage metric>, parrot_feat_id)"},
    {"name": "agent", "type": "query", "multi": true, "includeAll": true,
     "datasource": {"type": "prometheus", "uid": "claudestats-prometheus"},
     "query": "FILL IN: label_values(<token usage metric>, parrot_agent_name)"}
  ]},
  "panels": "FILL IN: stats (tokens, cost), timeseries by feature (tokens, cost), by agent (tokens, cost), table feature×agent×model, failures by feature — every expr uses only metric names/labels the contract test allows; bounded by AC-15"
}
```
**Why**: copy the remaining top-level keys (`schemaVersion`, `time`, `refresh`, `annotations`) from `parrot-usage-cost.json` so provisioning behaves identically.

### `test_metrics_feat_id_label.py` (CREATE)
```python
"""FEAT-783 AC-15 — parrot.feat_id label + policy-applied cost on metrics."""
import pytest


@pytest.mark.asyncio
async def test_after_call_metrics_carry_feat_id() -> None:
    # FILL IN: mocked instruments (style of test_metrics_subscriber.py); attributed event -> every token/cost/duration
    # attributes dict has parrot.feat_id == "FEAT-1"; unattributed -> "none"
    ...


@pytest.mark.asyncio
async def test_no_task_or_attempt_labels() -> None:
    # FILL IN: no attributes key in {task_id, attempt_uid, execution_id, parrot.task_id, ...} (AC-9)
    ...


@pytest.mark.asyncio
async def test_subscription_cost_counter_adds_zero() -> None:
    # FILL IN: priced event with pricing_policy="subscription" -> cost counter .add called with 0.0
    ...
```

### FILL IN checklist
- [ ] The two anchor sites in metrics.py
- [ ] Dashboard panels/exprs, valid against the contract test
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] AC-15: a provisioned and shipped Grafana dashboard shows tokens and cost by feature and by agent, filterable by both.
- [ ] `test_dashboard_contract.py` passes for both copies of the new dashboard and for the existing ones.
- [ ] AC-9 still holds: only `parrot.feat_id` is added; task, attempt and execution ids are not labels.
- [ ] Subscription-seat cost adds 0.0 to the cost counter (AC-13 consistency).

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/observability/test_metrics_feat_id_label.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_dashboard_contract.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Five files only. `PYTHONPATH=packages/ai-parrot/src`. Optionally smoke-load it in the docker Grafana stack and note the result in the Completion Note.

## Completion Note
_(filled at close)_
