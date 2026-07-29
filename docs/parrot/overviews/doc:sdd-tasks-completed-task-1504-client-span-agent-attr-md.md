---
type: Wiki Overview
title: 'TASK-1504: Add parrot.agent.name to the client span'
id: doc:sdd-tasks-completed-task-1504-client-span-agent-attr-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 Overview step 4, §3 Module 6. Traces already carry `parrot.agent.name`
relates_to:
- concept: mod:parrot
  rel: mentions
---

# TASK-1504: Add parrot.agent.name to the client span

**Feature**: FEAT-228 — Per-Agent Cost & Usage Metrics
**Spec**: `sdd/specs/per-agent-cost-usage-metrics.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1500
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 4, §3 Module 6. Traces already carry `parrot.agent.name`
on the agent ROOT span (`trace.py:349`) but NOT on the client child span. Adding
it to the client span gives a flat, per-client-call agent dimension for symmetry
with the metrics work (TASK-1503) and convenient filtering in the OpenLIT UI.

---

## Scope

- In `attributes.py`, add `"parrot.agent.name"` to the dicts returned by
  `build_before_client_attrs` (line 126), `build_after_client_attrs` (line 150),
  and `build_client_failed_attrs` (line 181) — but ONLY when `event.agent_name`
  is not None (follow the existing convention of never emitting None attrs).
- No change needed in `trace.py` if it simply spreads the builder dicts onto the
  span (verify `_on_client_start`/`_on_client_end` at lines 268/274 use the
  builders and `span.set_attribute(k, v)` loops).

**NOT in scope**: the event field (TASK-1500), metric labels (TASK-1503), the
invoke-span attribute (already exists at `trace.py:349`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/attributes.py` | MODIFY | Add `parrot.agent.name` to the 3 client attr builders (omit when None) |
| `packages/ai-parrot/src/parrot/observability/subscribers/trace.py` | VERIFY/MODIFY | Confirm builder output reaches the span; adjust only if needed |
| `packages/ai-parrot/tests/integration/observability/test_poc.py` | MODIFY | Assert client span carries `parrot.agent.name` |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/attributes.py
def build_before_client_attrs(event) -> dict[str, Any]:          # line 126
    # currently: gen_ai.system, gen_ai.request.model, gen_ai.request.has_tools,
    #            (+ temperature, system_prompt_hash when set)
def build_after_client_attrs(event, *, cost_usd=None) -> dict:   # line 150
    # currently: gen_ai.system, gen_ai.response.model, parrot.client.duration_ms,
    #            (+ tokens, finish_reason, parrot.cost.usd when set)
def build_client_failed_attrs(event) -> dict[str, Any]:          # line 181

# packages/ai-parrot/src/parrot/observability/subscribers/trace.py
async def _on_client_start(self, event):   # line 268
    attrs = build_before_client_attrs(event)   # line 271
async def _on_client_end(self, event):     # line 274
    extra = build_after_client_attrs(event, cost_usd=cost)   # line 283
# span attribute write loop: span.set_attribute(k, v)   # lines 176/204/229
# invoke span already has it: "parrot.agent.name": event.agent_name   # line 349

# event.agent_name — Optional[str] from TASK-1500
```

### Does NOT Exist
- ~~`parrot.agent.name` on client spans today~~ — only on the invoke span (349).
- ~~writing None attributes~~ — the builders deliberately omit None values; keep
  that convention for `parrot.agent.name`.

---

## Implementation Notes

### Pattern to Follow
```python
def build_after_client_attrs(event, *, cost_usd=None):
    attrs = {
        "gen_ai.system": resolve_gen_ai_system(event.client_name),
        "gen_ai.response.model": event.model,
        "parrot.client.duration_ms": event.duration_ms,
    }
    if event.agent_name:                       # NEW — omit when None/empty
        attrs["parrot.agent.name"] = event.agent_name
    ...
    return attrs
```

### Key Constraints
- Mirror the existing `if event.<field>:` guards already used for optional attrs.
- Keep the attribute key identical to the invoke span's (`parrot.agent.name`) so
  both layers are queryable by one key.

---

## Acceptance Criteria

- [ ] Client start/end/failed spans carry `parrot.agent.name` when the event has it.
- [ ] When `event.agent_name` is None, the attribute is OMITTED (not set to None/"").
- [ ] Attribute key matches the invoke span's (`parrot.agent.name`).
- [ ] `pytest packages/ai-parrot/tests/integration/observability/test_poc.py -v` passes.
- [ ] `ruff check` passes.

---

## Test Specification

```python
async def test_client_span_has_agent_name(span_exporter, subscriber):
    # drive a mocked client call with AfterClientCallEvent(agent_name="porygon")
    spans = span_exporter.get_finished_spans()
    client_span = next(s for s in spans if s.attributes.get("gen_ai.response.model"))
    assert client_span.attributes.get("parrot.agent.name") == "porygon"

async def test_client_span_omits_agent_when_none(span_exporter, subscriber):
    # agent_name=None
    assert "parrot.agent.name" not in client_span.attributes
```

---

## Agent Instructions

Standard SDD flow. First VERIFY trace.py spreads the builder dict onto the span
(it does at the set_attribute loops) — likely no trace.py change is needed.
Move to `completed/`, update the index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-08
**Notes**: Added `if event.agent_name: attrs["parrot.agent.name"] = event.agent_name` to
all three client attribute builders in `attributes.py` — `build_before_client_attrs`,
`build_after_client_attrs`, and `build_client_failed_attrs`. No change to `trace.py` was
required: `_on_client_start`/`_on_client_end`/`_on_client_fail` already spread the builder
dicts through `if v is not None` loops in `_start_span` and `_end_span_ok`/`_end_span_error`.
9 integration tests pass (7 existing + 2 new: test_scenario_8 and test_scenario_9). ruff
check passes.
**Deviations from spec**: none — builders sufficed, trace.py untouched as spec anticipated.
