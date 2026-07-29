---
type: Wiki Overview
title: 'TASK-1503: Add parrot.agent.name label to client metrics'
id: doc:sdd-tasks-active-task-1503-metrics-agent-label-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §1 Problem Statement, §3 Module 5 — the core deliverable. The cost counter,
relates_to:
- concept: mod:parrot
  rel: mentions
---

# TASK-1503: Add parrot.agent.name label to client metrics

**Feature**: FEAT-228 — Per-Agent Cost & Usage Metrics
**Spec**: `sdd/specs/per-agent-cost-usage-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1500
**Assigned-to**: unassigned

---

## Context

Spec §1 Problem Statement, §3 Module 5 — the core deliverable. The cost counter,
token-usage histogram, and client operation-duration histogram are currently
labelled only by provider + model. This task adds `parrot.agent.name` (from the
event field added in TASK-1500) so per-agent cost/usage can be sliced directly
from metrics.

---

## Scope

- In `subscribers/metrics.py`, add `"parrot.agent.name": event.agent_name or
  "unknown"` to the `base` label dict in `_on_client_after` (used by the cost
  counter, token-usage histogram, and client op-duration histogram).
- Apply the same label in `_on_client_before` (line 174) and `_on_client_fail`
  (line 219) for consistency across the client metrics they record.
- DECISION POINT (spec §8 open question): decide whether to also add the label
  to tool metrics (`_on_tool_after`, line 230). Default: add it for symmetry
  using `current_agent_name.get()` (tools run in the same invoke scope). Record
  the decision in the Completion Note.

**NOT in scope**: the event field (TASK-1500), span attributes (TASK-1504).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` | MODIFY | Add agent label to client (and optionally tool) metric records |
| `packages/ai-parrot/tests/integration/observability/test_poc.py` | MODIFY | Assert metric records carry `parrot.agent.name` |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
class MetricsSubscriber:
    _client_cost_total   = meter.create_counter(...)    # line 103
    _client_op_duration  = meter.create_histogram(...)  # line 122
    _client_token_usage  = meter.create_histogram(...)  # line 127

    async def _on_client_before(self, event): ...        # line 174
    async def _on_client_after(self, event):             # line 185
        system = ...
        base = {"gen_ai.system": system, "gen_ai.response.model": event.model}  # ~line 188
        self._client_op_duration.record(..., attributes={**base, "gen_ai.operation.name": "chat"})  # ~line 191
        self._client_token_usage.record(..., attributes={**base, "gen_ai.token.type": "input"})     # ~line 198
        self._client_token_usage.record(..., attributes={**base, "gen_ai.token.type": "output"})    # ~line 203
        self._client_cost_total.add(cost, attributes=base)   # ~line 217
    async def _on_client_fail(self, event): ...          # line 219
    async def _on_tool_after(self, event): ...           # line 230 (attributes={"parrot.tool.name": ...})

# event.agent_name — added by TASK-1500 (Optional[str], default None)
```

### Does NOT Exist
- ~~`event.agent_name` before TASK-1500~~ — this task depends on that field.
- ~~`user_id` / `session_id` on any metric label~~ — PII; MUST NOT be added
  (metrics.py docstring lines 9-10).

---

## Implementation Notes

### Pattern to Follow
```python
async def _on_client_after(self, event):
    system = resolve_gen_ai_system(event.client_name)
    base = {
        "gen_ai.system": system,
        "gen_ai.response.model": event.model,
        "parrot.agent.name": event.agent_name or "unknown",   # NEW
    }
    ...  # existing records all derive from `base`
```

### Key Constraints
- Cardinality note (spec §7): provider × model × agent. Bounded and desired.
- Fallback to `"unknown"` (never emit a None attribute value).
- Do not touch `ClientStreamChunkEvent` (never subscribed — line 168).

---

## Acceptance Criteria

- [ ] Cost counter, token-usage histogram, and client op-duration histogram each carry `parrot.agent.name`.
- [ ] Missing/None agent_name records as `"unknown"`.
- [ ] No PII label added.
- [ ] Tool-metric decision made and documented (default: include).
- [ ] `pytest packages/ai-parrot/tests/integration/observability/test_poc.py -v` passes.
- [ ] `ruff check` passes.

---

## Test Specification

```python
async def test_cost_metric_carries_agent_name(metric_reader, subscriber):
    # emit AfterClientCallEvent(agent_name="porygon", ...) through the registry
    ...
    data = collect(metric_reader)  # existing helper pattern in test_poc.py
    pts = points_for(data, "parrot.llm.cost.usd")  # or the real instrument name
    assert any(p.attributes.get("parrot.agent.name") == "porygon" for p in pts)

async def test_cost_metric_unknown_when_absent(metric_reader, subscriber):
    # emit AfterClientCallEvent(agent_name=None, ...)
    assert any(p.attributes.get("parrot.agent.name") == "unknown" for p in pts)
```

---

## Agent Instructions

Standard SDD flow. Confirm the exact instrument names from lines 103/122/127
before asserting in tests. Move to `completed/`, update index.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**: (state the tool-metric decision: included or excluded, and why)
**Deviations from spec**: none
