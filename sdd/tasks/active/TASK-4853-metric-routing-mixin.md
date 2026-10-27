# TASK-4853: MetricRoutingMixin — metric default-shape slot in `_resolve_output_mode`

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4846, TASK-4847
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (mixin half), decisions D1/D2. Precedence becomes
**explicit > router (phrasing) > metric default shape > agent default**. Q1 is RESOLVED:
FEAT-755 is merged on `dev`, so the hook returns the FEAT-755 form via
`set_output_shape(ctx, OutputShape(OutputMode.A2UI, component))` — contract in
`sdd/specs/inline-a2ui-component-routing.spec.md:317-331` ("Hook contract for FEAT-756").

---

## Scope

- Implement `MetricRoutingMixin` (`__init__` popping `metric_registry` / `metric_route_threshold`,
  MRO warning, `configure_metric_router`, `_resolve_output_mode`, `_hint_channel_available`).
- `_resolve_output_mode`: `resolved = await super()._resolve_output_mode(query, ctx)`; not `None`
  → return it. No registry → `None`. Else `registry.resolve(query, tenant=resolve_metric_tenant(None, ctx))`;
  no match (or score below `metric_route_threshold` when set) → `None`. On match: `ctx.kwargs["metric_match"] = match`,
  `bind_metric_match(match)`, `ctx.intent_score = match.score`; if `_hint_channel_available()` and
  `is_inline_component(component)` → `return set_output_shape(ctx, OutputShape(OutputMode.A2UI, component))`;
  else `None` (D2). Never raises (warn + `None`).
- Write `test_metric_routing_mixin.py` incl. integration `test_metric_turn_precedence`.

**NOT in scope**: `bots/mixins/__init__.py` export (TASK-4856); suggestions (TASK-4854);
mixing into `PandasAgent` (Q7 → no). No edit to `intent_router.py`, `abstract.py`, `base.py`, `data.py` (G9).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/mixins/metric_routing.py` | CREATE | `MetricRoutingMixin` |
| `packages/ai-parrot/tests/bots/test_metric_routing_mixin.py` | CREATE | unit + precedence integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode                                   # models/outputs.py:23 (A2UI member)
from parrot.registry.routing.route_labels import OutputShape, set_output_shape, is_inline_component   # route_labels.py:33, :97, :78
from parrot.bots.mixins.intent_router import IntentRouterMixin                 # intent_router.py:130 (used only for the MRO check)
from parrot.metrics.registry import MetricRegistry                             # TASK-4847 (new)
from parrot.metrics.context import bind_metric_match, resolve_metric_tenant    # TASK-4846 (new)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/mixins/intent_router.py
class IntentRouterMixin:                                         # L130
    def __init__(self, **kwargs: Any) -> None                    # L148
    async def _resolve_output_mode(self, query: str, ctx: Any) -> "Optional[OutputMode]"   # L279
        # no router → `return await super()._resolve_output_mode(query, ctx)` L299; abstain → super() L304;
        # route() off-loop via asyncio.to_thread L301
# packages/ai-parrot/src/parrot/bots/abstract.py
async def _resolve_output_mode(self, query, ctx) -> Optional[OutputMode]   # L4168 — terminal, returns None
# packages/ai-parrot/src/parrot/utils/helpers.py
class RequestContext:  # L7 — self.kwargs L36; output_mode L41; intent_score L42; a2ui_component: Optional[str] L46
# packages/ai-parrot/src/parrot/registry/routing/route_labels.py
class OutputShape(NamedTuple): mode: OutputMode; component: Optional[str] = None   # L33
def set_output_shape(ctx: Any, shape: OutputShape) -> OutputMode   # L97 — writes ctx.a2ui_component when ctx not None
def is_inline_component(component: str) -> bool                    # L78 — never raises
# TASK-4847 (new)
class MetricRegistry: async def resolve(self, question: str, *, tenant: str | None = None) -> MetricMatch | None
# TASK-4846 (new)
def resolve_metric_tenant(explicit: str | None = None, ctx: Any | None = None, default: str | None = None) -> str | None  # raises ValueError
def bind_metric_match(match: MetricMatch | None) -> Token
# test idiom: packages/ai-parrot/tests/bots/test_intent_router_output_mode.py
class _SuperSentinel   # L17 — terminal recording super_called; _Agent(IntentRouterMixin, _SuperSentinel) L32; _Ctx L36
```

### Does NOT Exist
- ~~A tuple return `(OutputMode, hint)` from `_resolve_output_mode`~~ — return a bare `OutputMode` via `set_output_shape`; the hint rides on `ctx.a2ui_component`.
- ~~`RequestContext.tenant`~~ — tenant is in `ctx.kwargs["tenant"]`.
- ~~`ctx.component_hint`~~ — attribute is `a2ui_component`; reader is `get_component_hint` (not needed here).
- ~~`parrot.bots.mixins.MetricRoutingMixin` export~~ — added by TASK-4856; import from `parrot.bots.mixins.metric_routing` in tests.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/mixins/metric_routing.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/bots/test_metric_routing_mixin.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/mixins/intent_router.py#IntentRouterMixin",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_labels.py#set_output_shape",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_labels.py#OutputShape",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_labels.py#is_inline_component",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._resolve_output_mode"
  ]
}
```

---

## Implementation Notes

- Required MRO: `class X(IntentRouterMixin, MetricRoutingMixin, BasicAgent)`. Warn (once, at `__init__`) when
  `IntentRouterMixin` appears AFTER `MetricRoutingMixin` in `type(self).__mro__`.
- `ctx` may be `None` or duck-typed: guard `getattr(ctx, "kwargs", None)` being a dict before writing.
- Import `parrot.registry.routing.route_labels` at module top (light, no a2ui chain — `is_inline_component` imports the catalog lazily).

---

## Implementation Blueprint

### Steps (in order)
1. Write the mixin per the block — *why*: signatures fixed by spec §3 M8 + FEAT-755 hook contract.
2. Write tests with `_SuperSentinel`-style terminal and a stub registry (`AsyncMock` / tiny class) — *why*: no encoder needed.

### `packages/ai-parrot/src/parrot/bots/mixins/metric_routing.py` (CREATE)
```python
"""Metric default-shape slot of the output-mode chain (FEAT-756 M8)."""
from __future__ import annotations

import logging
from typing import Any, Optional

from parrot.metrics.context import bind_metric_match, resolve_metric_tenant
from parrot.metrics.registry import MetricRegistry
from parrot.models.outputs import OutputMode
from parrot.registry.routing.route_labels import OutputShape, is_inline_component, set_output_shape

_LOGGER = logging.getLogger(__name__)


class MetricRoutingMixin:
    """explicit > router (phrasing) > METRIC > agent default.

    MRO contract: ``class X(IntentRouterMixin, MetricRoutingMixin, BasicAgent)``.
    """

    metric_registry: Optional[MetricRegistry] = None
    metric_route_threshold: Optional[float] = None

    def __init__(self, **kwargs: Any) -> None:
        registry = kwargs.pop("metric_registry", None)
        threshold = kwargs.pop("metric_route_threshold", None)
        super().__init__(**kwargs)
        if registry is not None:
            self.configure_metric_router(registry, threshold=threshold)
        elif threshold is not None:
            self.metric_route_threshold = threshold
        # FILL IN: MRO check — if IntentRouterMixin is in type(self).__mro__ at an index AFTER MetricRoutingMixin,
        #   _LOGGER.warning(...) explaining precedence would invert. Import IntentRouterMixin lazily inside.

    def configure_metric_router(self, registry: MetricRegistry, *, threshold: Optional[float] = None) -> None:
        """Attach (or replace) the registry after construction."""
        self.metric_registry = registry
        if threshold is not None:
            self.metric_route_threshold = threshold

    def _hint_channel_available(self) -> bool:
        """FEAT-755 channel probe (merged on dev; kept guarded so a rename degrades to abstain)."""
        try:
            from parrot.registry.routing import route_labels  # noqa: F401
        except ImportError:
            return False
        return True

    async def _resolve_output_mode(self, query: str, ctx: Any) -> Optional[OutputMode]:
        resolved = await super()._resolve_output_mode(query, ctx)  # type: ignore[misc]
        if resolved is not None or self.metric_registry is None:
            return resolved
        try:
            # FILL IN: tenant = resolve_metric_tenant(None, ctx); match = await registry.resolve(query, tenant=tenant);
            #   None or (threshold set and match.score < threshold) → return None;
            #   stash ctx.kwargs["metric_match"] (when dict), bind_metric_match(match), ctx.intent_score = match.score;
            #   component = match.metric.default_shape.component;
            #   if self._hint_channel_available() and is_inline_component(component):
            #       return set_output_shape(ctx, OutputShape(OutputMode.A2UI, component))
            return None
        except Exception as exc:  # never break a turn
            _LOGGER.warning("metric routing failed: %s", exc)
            return None
```
**Why this shape**: super() first means a phrasing win or an earlier override is never outranked (FEAT-755 contract). Returning `None` when the component is not inline keeps the turn on the agent default while the match stays visible to `query_metric` (D2).

### FILL IN checklist
- [ ] `__init__` MRO warning — bounded by D1
- [ ] `_resolve_output_mode` match handling — bounded by AC "With class X(...)" in spec §5

---

## Acceptance Criteria

- [ ] No registry → behaviour identical to `test_resolve_output_mode_noop` (returns `None`, super reached).
- [ ] Phrasing router win → result unchanged, registry not consulted.
- [ ] Router abstain + match → `ctx.kwargs["metric_match"]` and `current_metric_match()` set; returns `OutputMode.A2UI` with `ctx.a2ui_component == "KPICard"` when inline; `None` when `is_inline_component` is False (monkeypatched).
- [ ] Registry raising → `None`, warning logged.
- [ ] Wrong MRO order → warning logged.

## Validation Commands
- `pytest packages/ai-parrot/tests/bots/test_metric_routing_mixin.py -q`
- `pytest packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_metric_routing_mixin.py
from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.bots.mixins.metric_routing import MetricRoutingMixin

class _SuperSentinel:  # copy of tests/bots/test_intent_router_output_mode.py:17
    ...
class _Agent(IntentRouterMixin, MetricRoutingMixin, _SuperSentinel): ...

async def test_metric_routing_mixin_abstains_without_registry(): ...
async def test_metric_routing_mixin_after_router_abstain(worked_hours_def, monkeypatch): ...  # stashes; A2UI + hint
async def test_metric_routing_mixin_not_inline_returns_none(monkeypatch): ...
async def test_metric_routing_mixin_registry_error_is_swallowed(): ...
def test_metric_routing_mixin_mro_warning(caplog): ...
async def test_metric_turn_precedence(): ...  # bar-chart phrasing → STRUCTURED_CHART; "worked hours this month" → match stashed
```
`worked_hours_def` lives in `packages/ai-parrot/tests/unit/metrics/conftest.py`, NOT visible here — build an equivalent
definition locally in this test file.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4846 and TASK-4847 are `done`.
2. Re-verify the route_labels anchors (`grep -n 'def set_output_shape' packages/ai-parrot/src/parrot/registry/routing/route_labels.py`).
3. Implement, run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, commit listed files, close with `scripts/sdd/close_task.sh TASK-4853 metric-definition-registry verified`.

## Completion Note

