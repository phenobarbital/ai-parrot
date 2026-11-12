# HOTFIX-otel-attribution-1: Map the tenant onto OTel spans and LLM metrics

**Feature**: otel-attribution — tag every agent LLM call's OTel telemetry with agent and tenant
**Spec**: `sdd/briefs/otel-attribution.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-710 put a server-resolved `tenant` on `AfterClientCallEvent`, `ClientCallFailedEvent`,
`AfterInvokeEvent` and `InvokeFailedEvent`, but no OTel signal carries it: the span attribute
builders (`observability/attributes.py`) and `MetricsSubscriber` (`observability/subscribers/metrics.py`)
never read it. The request-count metric is recorded from `BeforeClientCallEvent` and the round metrics
from `ClientRoundEvent`; neither event has a `tenant` field. Events are dispatched fire-and-forget
(`emit_nowait`), so identity must be captured on the event when it is built — the subscriber cannot read
a ContextVar later (see the FEAT-228 comment at `clients/base.py:682-684`).

## Scope

1. Add `tenant: Optional[str] = None` to `BeforeClientCallEvent` and `ClientRoundEvent`
   (frozen dataclasses in `core/events/lifecycle/events/client.py`), after their `session_id` field, with a
   docstring `Args` entry matching the existing `AfterClientCallEvent` one.
2. In `AbstractClient._emit_before_call` and `AbstractClient._emit_round_event` (`clients/base.py`), pass
   `tenant=current_tenant.get()` next to `agent_name=current_agent_name.get()` — the same capture-at-construction
   pattern `_emit_after_call` already uses at `clients/base.py:832`.
3. In `observability/attributes.py` add, near the top-level constants:
   - `TENANT_ATTR = "parrot.tenant"`
   - `UNKNOWN_TENANT = "unknown"`
   - `def tenant_label(tenant: Optional[str]) -> str` returning `tenant or UNKNOWN_TENANT` (Google-style docstring).
   Then set `attrs[TENANT_ATTR] = tenant_label(event.tenant)` in `build_before_client_attrs`,
   `build_after_client_attrs`, `build_client_failed_attrs`, `build_after_invoke_attrs` and
   `build_invoke_failed_attrs` (unconditionally — the sentinel makes missing coverage visible).
   `build_before_invoke_attrs` is unchanged (`BeforeInvokeEvent` has no tenant; the invoke span gets it at end).
4. In `observability/subscribers/metrics.py`, import `TENANT_ATTR` and `tenant_label` with the existing
   `resolve_gen_ai_system` import (`metrics.py:31`) and add `TENANT_ATTR: tenant_label(event.tenant)` to the
   attribute dict of `_on_client_before`, `_on_client_after` (the shared `base` dict), `_on_client_round`
   (the shared `base` dict), `_on_client_fail`, `_on_invoke_after` and `_on_invoke_fail`.
5. Tests in a new `tests/unit/observability/test_tenant_attribution.py`.

**NOT in scope**: tool-call metrics/spans (`parrot.tool.*`), the Prometheus usage recorder
(`observability/recorders/prometheus_recorder.py`), the OpenLIT recorder, `BeforeInvokeEvent`, EventBus
fan-out (`observability/fanout.py`), dashboards, docs. Do not change any existing attribute key or value.

## Files to Create / Modify

| File | Action | What |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | MODIFY | `tenant` field on `BeforeClientCallEvent`, `ClientRoundEvent` |
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | capture `tenant=current_tenant.get()` in `_emit_before_call`, `_emit_round_event` |
| `packages/ai-parrot/src/parrot/observability/attributes.py` | MODIFY | `TENANT_ATTR`, `UNKNOWN_TENANT`, `tenant_label`; tenant on 5 builders |
| `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` | MODIFY | tenant label on 6 LLM/invoke metric handlers |
| `packages/ai-parrot/tests/unit/observability/test_tenant_attribution.py` | CREATE | unit tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.observability.context import current_tenant          # observability/context.py:85
from parrot.observability.context import current_agent_name      # already imported in clients/base.py:84
from parrot.observability.attributes import resolve_gen_ai_system  # metrics.py:31 (extend this import)
from parrot.core.events.lifecycle.events import (
    BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent, ClientRoundEvent,
    AfterInvokeEvent, InvokeFailedEvent,
)
from parrot.core.events.lifecycle import TraceContext            # used by existing event tests
```

`current_tenant` is already imported in `clients/base.py` (used at `:832` and `:933`).

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True)
class BeforeClientCallEvent(LifecycleEvent):   # :28 — fields end with agent_name (:49), user_id, session_id (:51)
class AfterClientCallEvent(LifecycleEvent):    # :55 — tenant: Optional[str] = None  # FEAT-710  (:95)
class ClientCallFailedEvent(LifecycleEvent):   # :112 — tenant field at :141
class ClientRoundEvent(LifecycleEvent):        # :225 — fields end with agent_name (:269), user_id, session_id (:271)

# packages/ai-parrot/src/parrot/clients/base.py  (class AbstractClient, :297)
def _emit_before_call(self, *, client_name: str, model: str, temperature=None, system_prompt=None,
                      has_tools: bool = False, parent_trace=None) -> "TraceContext":          # :638
    # builds BeforeClientCallEvent( ... agent_name=current_agent_name.get(), user_id=..., session_id=...) :673-687
def _emit_round_event(self, tc, *, client_name, model, round_number, usage, raw_usage, tool_calls,
                      duration_ms) -> None:                                                   # :697
    # builds ClientRoundEvent( ... agent_name=current_agent_name.get(), user_id=..., session_id=...) :748-766

# packages/ai-parrot/src/parrot/observability/attributes.py
def build_before_client_attrs(event: BeforeClientCallEvent) -> dict[str, Any]     # :172
def build_after_client_attrs(event: AfterClientCallEvent, cost_usd=None) -> dict  # :215
def build_client_failed_attrs(event: ClientCallFailedEvent) -> dict[str, Any]     # :256
def build_after_invoke_attrs(event: AfterInvokeEvent) -> dict[str, Any]           # :151
def build_invoke_failed_attrs(event: InvokeFailedEvent) -> dict[str, Any]         # :333

# packages/ai-parrot/src/parrot/observability/subscribers/metrics.py  (class MetricsSubscriber)
async def _on_client_before(self, event: BeforeClientCallEvent) -> None   # :201
async def _on_client_after(self, event: AfterClientCallEvent) -> None     # :217 (base dict :223-229)
async def _on_client_round(self, event: ClientRoundEvent) -> None         # :258 (base dict :277-283)
async def _on_client_fail(self, event: ClientCallFailedEvent) -> None     # :300
async def _on_invoke_after(self, event: AfterInvokeEvent) -> None         # :334
async def _on_invoke_fail(self, event: InvokeFailedEvent) -> None         # :344
```

### Does NOT Exist

- ~~`BeforeClientCallEvent.tenant`~~, ~~`ClientRoundEvent.tenant`~~ — added by this task.
- ~~`BeforeInvokeEvent.tenant`~~ — not added (out of scope).
- ~~`parrot.tenant`~~, ~~`tenant.id`~~ — no tenant attribute key exists anywhere in `parrot/observability/` today.
- ~~`TENANT_ATTR`~~, ~~`UNKNOWN_TENANT`~~, ~~`tenant_label`~~ — created by this task.
- Subscribers must not call `current_tenant.get()` — the value is gone by dispatch time.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/clients/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/attributes.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/subscribers/metrics.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/observability/test_tenant_attribution.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py#BeforeClientCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py#AfterClientCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py#ClientCallFailedEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py#ClientRoundEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py#AfterInvokeEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py#InvokeFailedEvent",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_before_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_round_event",
    "sym:packages/ai-parrot/src/parrot/observability/attributes.py#build_before_client_attrs",
    "sym:packages/ai-parrot/src/parrot/observability/attributes.py#build_after_client_attrs",
    "sym:packages/ai-parrot/src/parrot/observability/attributes.py#build_client_failed_attrs",
    "sym:packages/ai-parrot/src/parrot/observability/attributes.py#build_after_invoke_attrs",
    "sym:packages/ai-parrot/src/parrot/observability/attributes.py#build_invoke_failed_attrs",
    "sym:packages/ai-parrot/src/parrot/observability/subscribers/metrics.py#MetricsSubscriber._on_client_before",
    "sym:packages/ai-parrot/src/parrot/observability/subscribers/metrics.py#MetricsSubscriber._on_client_after",
    "sym:packages/ai-parrot/src/parrot/observability/subscribers/metrics.py#MetricsSubscriber._on_client_round",
    "sym:packages/ai-parrot/src/parrot/observability/subscribers/metrics.py#MetricsSubscriber._on_client_fail",
    "sym:packages/ai-parrot/src/parrot/observability/subscribers/metrics.py#MetricsSubscriber._on_invoke_after",
    "sym:packages/ai-parrot/src/parrot/observability/subscribers/metrics.py#MetricsSubscriber._on_invoke_fail"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

`_emit_after_call` already does exactly this for the after event (`clients/base.py:816-833`):

```python
event = AfterClientCallEvent(
    ...
    agent_name=current_agent_name.get(),
    ...
    tenant=current_tenant.get(),
)
```

`MetricsSubscriber` already uses a sentinel for the agent: `"parrot.agent.name": event.agent_name or "unknown"`
(`metrics.py:227`). Mirror it for the tenant via `tenant_label`.

### Key Constraints

- Frozen dataclasses: add the field with a default (`= None`) at the end of each class so positional
  construction elsewhere is unaffected.
- `parrot.tenant` is a bounded label (one value per tenant + `"unknown"`); never add `user_id`/`session_id`
  to metrics (they stay span-only, see the field comments in `client.py:50-51`).
- Keep `parrot.agent.name` handling exactly as is.

## Implementation Blueprint

### Steps (in order)

1. Event fields (`client.py`), then the two emit sites (`clients/base.py`).
2. `attributes.py` constants + `tenant_label` + five builders.
3. `metrics.py` import + six handlers.
4. Tests, then the validation commands.

### FILL IN checklist

- [ ] `BeforeClientCallEvent.tenant` and `ClientRoundEvent.tenant` exist, default `None`, documented.
- [ ] `_emit_before_call` / `_emit_round_event` pass `tenant=current_tenant.get()`.
- [ ] Five span builders set `parrot.tenant`; `build_before_invoke_attrs` untouched.
- [ ] Six metric handlers include `parrot.tenant`; tool handlers untouched.

## Acceptance Criteria

- [ ] With `current_tenant` bound to `"acme"`, `_emit_before_call` and `_emit_round_event` produce events whose `tenant == "acme"`; unbound → `None`.
- [ ] Each of the five builders returns `parrot.tenant == "acme"` for an event with `tenant="acme"` and `"unknown"` for `tenant=None`.
- [ ] Request count, duration, token usage, cost, rounds, round tokens, client errors, invoke duration and invoke failures are recorded with `parrot.tenant`; tool metrics are not.
- [ ] All existing observability and client-event tests still pass.
- [ ] `ruff check` clean on the four modified source files.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_tenant_attribution.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_attributes.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_attributes_semconv.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_metrics_label_whitelist.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_metrics_feat_id_label.py -q`
- `pytest packages/ai-parrot/tests/unit/clients/test_client_emits_agent_name.py -q`
- `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_client_events_agent_name.py -q`

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_tenant_attribution.py
# Cases (use the _Instrument capture stub from test_metrics_label_whitelist.py for metrics,
# and the TraceContext fixture pattern from tests/unit/clients/test_client_emits_agent_name.py):
# - test_before_and_round_events_capture_bound_tenant      (token = current_tenant.set("acme"); reset in finally)
# - test_before_and_round_events_tenant_none_when_unbound
# - test_span_builders_set_tenant_or_unknown               (parametrize over the 5 builders)
# - test_before_invoke_attrs_have_no_tenant_key
# - test_client_metrics_carry_tenant_label                 (_on_client_before/_after/_round/_fail)
# - test_invoke_metrics_carry_tenant_label                 (_on_invoke_after/_fail)
# - test_tool_metrics_have_no_tenant_label
```

## Agent Instructions

1. Work in the brief worktree (`fix-otel-attribution-otel-attribution`), never on `dev`.
2. Read `sdd/briefs/otel-attribution.brief.md` (Root cause, Assumptions).
3. Verify the Codebase Contract line anchors before editing; if one moved, update this file first.
4. Mark this task `in-progress` in `sdd/briefs/otel-attribution.index.json` and commit only that file.
5. Implement, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the files in the table above: `fix(otel-attribution): HOTFIX-otel-attribution-1 — tenant on OTel signals`.
7. Close with `parrot sdd task close HOTFIX-otel-attribution-1 otel-attribution verified`, fill in the
   Completion Note, commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) with gpt-5.6-terra (codex), 1 attempt
**Date**: 2026-11-12
**Status**: done-with-issues
**Notes**: Mapped the server-resolved tenant onto OTel spans and LLM metrics: `tenant` added to BeforeClientCallEvent/ClientRoundEvent (events/client.py), set from `current_tenant` in clients/base.py, with attributes.py and subscribers/metrics.py updated; new tests in tests/unit/observability/test_tenant_attribution.py. Commits: lint 5ee263e8e3, merge 8af3579f73.

Merge-tier validation did NOT settle green: the engine runs ended `timed_out` (second run exit -15/SIGTERM after ~1 min, no pytest summary; the first two runs ended `timed_out` with exit 0). No failure was observed in the tests that did run, and the cause of the stall is unidentified. Accepted by the operator as done-with-issues.

Three failing tests seen in the first validation log are NOT caused by this brief (static diff evidence vs origin/dev, not a baseline run): `test_agent_name_is_not_pii_field` -> issue:ea9f2f8ab334 (`user_id` already declared on AfterClientCallEvent on dev; this brief adds only `tenant`); `test_live_envelope.py::TestCanonicalRole` x2 -> issue:33b76e470d2b (stream_voice role handling untouched by this brief).

**Deviations from spec**: none in scope
