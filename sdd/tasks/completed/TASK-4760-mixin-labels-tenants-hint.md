# TASK-4760: IntentRouterMixin: label validation, per-tenant routers, hint resolution

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4757, TASK-4758, TASK-4759
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 — where the three router-thread pieces meet. Four changes to
`intent_router.py`, all inside the FEAT-224 block:

1. **CONFIGURE validation** (`:197`): today `OutputMode(mode_value)` inside
   `try/except ValueError` + warn. It gains `parse_route_label` in front, plus an
   `is_inline_component` check for composites only.
2. **Per-tenant routers**: one `EmbeddingIntentRouter` per
   `config.tenant_output_mode_routes` entry, all sharing the global router's encoder
   (that is why TASK-4758 added the `encoder=` kwarg — loading the model per tenant
   would be unacceptable).
3. **REQUEST resolution** (`:209`): a composite win returns
   `set_output_shape(ctx, OutputShape(A2UI, component))`; a plain win and the abstain
   path are unchanged.
4. **Tie-breaker over labels** (`:252`): candidates and return become route *labels*.
   The prompt's JSON key stays `output_mode` — plain labels equal `OutputMode` values,
   so existing stubs returning `{"output_mode": "structured_table"}` keep working.

The method's public signature is unchanged: `_resolve_output_mode` still returns
`Optional[OutputMode]` (G5). The component rides on `ctx`, not the return value.

---

## Scope

- Add `_tenant_output_routers` state and initialize it in `__init__`.
- Extend `configure_output_router`: label validation, composite catalog gate, per-tenant routers sharing one encoder.
- Add `_select_output_router(ctx)` with the fixed tenant pick order.
- Rework `_resolve_output_mode` to route over labels and set the hint for composites.
- Rework `_llm_disambiguate_output_mode` to take and return labels.
- Create `test_intent_router_component_routes.py`.

**NOT in scope**: `PandasAgent` wiring (TASK-4766/4767), `RequestContext.a2ui_component` (TASK-4761), and the emitter (TASK-4765). This task must not touch `bots/data.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | MODIFY | Label validation, tenant routers, hint resolution, label tie-breaker |
| `packages/ai-parrot/tests/bots/test_intent_router_component_routes.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
from parrot.registry.routing.embedding_router import EmbeddingIntentRouter, RouteScore  # verified: embedding_router.py:37,57
from parrot.registry.routing.route_labels import (  # verified: TASK-4757
    OutputShape, is_inline_component, parse_route_label, set_output_shape,
)
from parrot.skills.tenancy import current_skill_tenant  # verified: skills/tenancy.py (FEAT-707 ContextVar)
```

### Existing Signatures to Use
```python
# parrot/bots/mixins/intent_router.py:123
class IntentRouterMixin:
    _router_active: bool = False
    _router_config: Optional[IntentRouterConfig] = None
    def __init__(self, **kwargs: Any) -> None:            # :141
        self._output_router: Optional[EmbeddingIntentRouter] = None   # :151
    def configure_output_router(self, config: IntentRouterConfig) -> None:  # :175
        # :188-198 — builds the router, then:
        #     for mode_value, utterances in config.output_mode_routes.items():
        #         try: router.add_route(OutputMode(mode_value), utterances)   # :197
        #         except ValueError: logger.warning("Unknown OutputMode in output_mode_routes: %s", mode_value)
    async def _resolve_output_mode(self, query: str, ctx: Any) -> "Optional[OutputMode]":  # :209
        # rs = await asyncio.to_thread(router.route, query); rs.mode is None -> super()
        # ambiguous -> route_scores + _llm_disambiguate_output_mode; sets ctx.intent_score
    async def _llm_disambiguate_output_mode(self, query, candidates) -> "Optional[OutputMode]":  # :252
        # prompt uses 'Candidate output modes: ...' and parses {"output_mode": "..."}

# parrot/registry/routing/embedding_router.py (AFTER TASK-4758)
class RouteScore(NamedTuple):
    mode: Optional[OutputMode]; score: float; runner_up: float; ambiguous: bool
    label: Optional[str] = None; component: Optional[str] = None
    def route_label_scores(self, query: str) -> list[tuple[str, float]]: ...
```

### Does NOT Exist
- ~~`IntentRouterMixin._tenant_output_routers`~~ — this task ADDS it.
- ~~`IntentRouterMixin._select_output_router`~~ — this task ADDS it.
- ~~a `tenant` parameter on `_resolve_output_mode`~~ — the tenant comes from the ContextVar or `ctx.kwargs`, never a new parameter (the signature is frozen by G5).
- ~~`_resolve_output_mode` returning a tuple or `OutputShape`~~ — it still returns `Optional[OutputMode]`; the component travels on `ctx.a2ui_component`.
- ~~`EmbeddingIntentRouter.encoder` as a public attribute~~ — verify the private attribute name in `embedding_router.py` before reaching for it; pass the encoder through the constructor kwarg TASK-4758 added.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/mixins/intent_router.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_intent_router_component_routes.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/mixins/intent_router.py#IntentRouterMixin",
    "sym:packages/ai-parrot/src/parrot/bots/mixins/intent_router.py#IntentRouterMixin.configure_output_router",
    "sym:packages/ai-parrot/src/parrot/bots/mixins/intent_router.py#IntentRouterMixin._resolve_output_mode",
    "sym:packages/ai-parrot/src/parrot/bots/mixins/intent_router.py#IntentRouterMixin._llm_disambiguate_output_mode",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_labels.py#parse_route_label",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_labels.py#is_inline_component",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_labels.py#set_output_shape",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#current_skill_tenant"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Signature freeze (G5)**: `_resolve_output_mode(self, query, ctx) -> Optional[OutputMode]`. Do not widen it.
- **Validation order at CONFIGURE**: `parse_route_label(key)` first (catches malformed/unknown mode), then — for composites only — `is_inline_component(component)`. Either failure logs a warning and **skips that entry**; the router is still built from the remaining routes. This mirrors today's `except ValueError` branch at `:195-201`, which must not become fatal.
- **One encoder.** Build the global router first, force its encoder to load once, then pass that instance to every tenant router via `encoder=`. A per-tenant model load is an explicit acceptance-criteria failure.
- **Tenant pick order is fixed**: `current_skill_tenant()` → `ctx.kwargs.get("tenant")` → global. An unknown tenant falls back to the global router; warn **once per tenant**, not per request (mirror `skills/mixin.py`'s warn-once pattern).
- **Tie-breaker compatibility**: the prompt's JSON key stays `output_mode`. Candidates are labels; a plain label is identical to its `OutputMode` value, so existing test stubs keep working. Accept only a value present in the candidate list; otherwise abstain to the embedding winner (today's policy, unchanged).
- `route()` stays off the event loop via `asyncio.to_thread` (unchanged).
- The router never raises into `ask()`: any unexpected error resolves to abstain.

### References in Codebase
- `parrot/bots/mixins/intent_router.py:188-201` — the CONFIGURE loop and its warn-and-skip branch.
- `parrot/bots/mixins/intent_router.py:209-250` — `_resolve_output_mode`'s threshold/margin policy and `super()` chaining.
- `parrot/bots/mixins/intent_router.py:252-305` — the bounded tie-breaker and its JSON parse.
- `parrot/skills/mixin.py` — the warn-once-per-tenant pattern to copy.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Initialize `_tenant_output_routers` in `__init__` beside `_output_router` — *why*: the mixin is cooperative and must not rely on `configure_*` having run.
2. Insert label validation into the CONFIGURE loop — *why*: this is the only place with both the agent's logger and the catalog, so it is where a bad label gets a useful warning.
3. Build tenant routers passing the global encoder — *why*: N tenants must not mean N model loads.
4. Add `_select_output_router` — *why*: request-time tenant selection is a separate concern from resolution and is unit-testable alone.
5. Rework `_resolve_output_mode` over labels, calling `set_output_shape` for composites — *why*: the return type is frozen, so the component must ride on ctx.
6. Rework the tie-breaker to labels — *why*: without it, ambiguity between `structured_chart` and `a2ui:KPICard` could never be resolved.
7. Write `test_intent_router_component_routes.py` — *why*: AC-1..AC-7.

### `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` (MODIFY — state)
```python
# occurrences: 1 (verified: grep -c '        self._output_router: Optional\[EmbeddingIntentRouter\] = None' packages/ai-parrot/src/parrot/bots/mixins/intent_router.py)
# AFTER — insert below `self._output_router: Optional[EmbeddingIntentRouter] = None` (verified: intent_router.py:151)
        # FEAT-755: one router per tenant, all sharing the global router's encoder.
        self._tenant_output_routers: dict[str, EmbeddingIntentRouter] = {}
```
**Why**: initialized in `__init__` (not lazily) so `_select_output_router` can read it unconditionally on every request.

### `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` (MODIFY — CONFIGURE validation + tenant routers)
```python
# occurrences: 1 (verified: grep -c '                router.add_route(OutputMode(mode_value), utterances)' packages/ai-parrot/src/parrot/bots/mixins/intent_router.py)
# REPLACE the try/except body around `router.add_route(OutputMode(mode_value), utterances)`
# (verified: intent_router.py:197) with label-aware validation:
        for label, utterances in config.output_mode_routes.items():
            try:
                shape = parse_route_label(label)
            except ValueError:
                logger.warning("Invalid route label in output_mode_routes: %s", label)
                continue
            if shape.component is not None and not is_inline_component(shape.component):
                logger.warning(
                    "Route label %s names a component that is not registered or is "
                    "action-bearing; skipping.", label,
                )
                continue
            router.add_route(label, utterances)

# AFTER the global router is assigned, build the per-tenant routers:
        # FILL IN: for tenant, bank in config.tenant_output_mode_routes.items():
        #          build EmbeddingIntentRouter(..., encoder=<global router's loaded encoder>)
        #          applying the SAME validation loop above; store in self._tenant_output_routers
        #          — bounded by AC-2/AC-3 (one encoder, invalid entries skipped not fatal)
```
**Why**: validation lives here because this is the only point with the catalog, the agent's logger, and the whole bank in hand. Skipping (never raising) preserves today's behaviour where one bad key cannot stop an agent from starting.

### `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` (MODIFY — tenant selection)
```python
# occurrences: 1 (verified: grep -c '    async def _resolve_output_mode(' packages/ai-parrot/src/parrot/bots/mixins/intent_router.py)
# AFTER — insert this helper directly ABOVE `async def _resolve_output_mode(` (verified: intent_router.py:209)
    def _select_output_router(self, ctx: Any) -> Optional["EmbeddingIntentRouter"]:
        """Pick the router for this request.

        Order: ``current_skill_tenant()`` -> ``ctx.kwargs.get("tenant")`` -> the global
        router. An unknown tenant falls back to the global router and warns once.
        """
        # FILL IN: the three-step lookup + warn-once-per-tenant set — bounded by AC-4
```
**Why**: separating selection from resolution keeps `_resolve_output_mode`'s threshold/margin policy untouched and makes the tenant order testable on its own.

### `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` (MODIFY — resolution over labels)
```python
# occurrences: 1 (verified: grep -c '    async def _resolve_output_mode(' packages/ai-parrot/src/parrot/bots/mixins/intent_router.py)
# MODIFY the body of `_resolve_output_mode` (verified: intent_router.py:209). The signature
# and the abstain/super() chaining are UNCHANGED. Three edits inside:
#   1. router = self._select_output_router(ctx)          # was: getattr(self, "_output_router", None)
#   2. on a clear or tie-broken win:
#        if rs.component is not None:
#            return set_output_shape(ctx, OutputShape(OutputMode.A2UI, rs.component))
#        return chosen
#   3. ambiguity path: use router.route_label_scores(query) and pass LABELS to the
#      tie-breaker; map the chosen label back with parse_route_label.
# FILL IN: thread the label through the ambiguous branch and keep ctx.intent_score
#          mirroring exactly as today — bounded by AC-1/AC-5
```
**Why**: the return type is frozen by G5, so a composite win communicates the component by writing `ctx.a2ui_component` through `set_output_shape` — the same public helper FEAT-756 will use.

### `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` (MODIFY — label tie-breaker)
```python
# occurrences: 1 (verified: grep -c '    async def _llm_disambiguate_output_mode(' packages/ai-parrot/src/parrot/bots/mixins/intent_router.py)
# MODIFY `_llm_disambiguate_output_mode` (verified: intent_router.py:252):
#   - candidates: list[str] (labels); return: Optional[str] (a label)
#   - the prompt's JSON key stays "output_mode" and the wording stays close to today's
#   - accept ONLY a returned value present in `candidates`; otherwise return None
# FILL IN: replace the `OutputMode(parsed.get("output_mode"))` coercion with a
#          membership check against candidates — bounded by AC-6
```
**Why**: keeping the JSON key means existing stubs returning `{"output_mode": "structured_table"}` still pass, while composite labels become expressible for the first time.

### `packages/ai-parrot/tests/bots/test_intent_router_component_routes.py` (CREATE)
```python
"""Composite-route wiring in IntentRouterMixin (FEAT-755 TASK-4760)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.models.outputs import OutputMode
from parrot.registry.capabilities.models import IntentRouterConfig


class TestConfigureValidation:
    # FILL IN: unknown mode, malformed composite, and an action-bearing component are each
    #          skipped with a caplog warning while the router is still built — bounded by AC-2
    ...


class TestTenantRouters:
    # FILL IN: one router per tenant bank; all share ONE encoder (assert the loader runs once)
    #          — bounded by AC-3
    ...


class TestResolution:
    # FILL IN: composite win -> OutputMode.A2UI returned AND ctx.a2ui_component == "KPICard";
    #          plain win unchanged; abstain still chains super() (use the _SuperSentinel
    #          pattern from tests/bots/test_intent_router_output_mode.py) — bounded by AC-1/AC-5
    ...


class TestTieBreaker:
    # FILL IN: candidates are labels; an off-list answer abstains to the embedding winner;
    #          a stub returning {"output_mode": "structured_table"} still works — bounded by AC-6
    ...
```
**Why**: a new module rather than edits to `test_intent_router_output_mode.py`, so the FEAT-224 regression suite stays untouched and keeps proving G5.

### FILL IN checklist
- [ ] `intent_router.py::configure_output_router` — per-tenant router construction sharing the encoder; bounded by AC-2/AC-3
- [ ] `intent_router.py::_select_output_router` — three-step tenant order + warn-once; bounded by AC-4
- [ ] `intent_router.py::_resolve_output_mode` — label threading through the ambiguous branch; bounded by AC-1/AC-5
- [ ] `intent_router.py::_llm_disambiguate_output_mode` — candidate membership check; bounded by AC-6
- [ ] `test_intent_router_component_routes.py` — the four test classes; bounded by AC-1..AC-7

---

## Acceptance Criteria

- [ ] **AC-1**: a composite route win returns `OutputMode.A2UI` from `_resolve_output_mode` AND sets `ctx.a2ui_component` to the component name.
- [ ] **AC-2**: an unknown OutputMode, a malformed composite, and a composite naming an unregistered or action-bearing component are each skipped with a `logger.warning`; the router is still built from the remaining routes.
- [ ] **AC-3**: per-tenant routers share one encoder — the model loader runs exactly once regardless of tenant count.
- [ ] **AC-4**: tenant pick order is `current_skill_tenant()` → `ctx.kwargs["tenant"]` → global; an unknown tenant falls back to global and warns once, not per request.
- [ ] **AC-5**: no behaviour change for plain routes — `tests/bots/test_intent_router_output_mode.py` and `test_resolve_output_mode_noop.py` pass unmodified, including `super()` chaining on abstain.
- [ ] **AC-6**: the tie-breaker takes and returns labels, keeps the `output_mode` JSON key, and abstains on an off-list answer.
- [ ] **AC-7**: `_resolve_output_mode` still returns `Optional[OutputMode]` — signature unchanged (G5).
- [ ] `ruff check` clean on both files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_intent_router_component_routes.py -q`
- `pytest packages/ai-parrot/tests/bots/test_intent_router_output_mode.py -q`
- `pytest packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py -q`
- `pytest packages/ai-parrot/tests/bots/test_intent_router_output_mode_integration.py -q`

---

## Test Specification

Create `packages/ai-parrot/tests/bots/test_intent_router_component_routes.py` per the blueprint.

Reuse the `_SuperSentinel` pattern already in
`packages/ai-parrot/tests/bots/test_intent_router_output_mode.py` to prove `super()` is still reached on
abstain — that is the FEAT-224 cooperative contract and AC-5 depends on it.

Stub the encoder so no model is downloaded, and assert the loader call count directly
for AC-3.

The three existing FEAT-224 test modules listed in Validation Commands must pass
**unmodified** — if one needs editing, the change has broken G5 and is out of scope.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug inline-a2ui-component-routing --feature-id FEAT-755`)
2. **Read the spec** at `sdd/specs/inline-a2ui-component-routing.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/inline-a2ui-component-routing.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/inline-a2ui-component-routing.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <ID> inline-a2ui-component-routing verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by codex/gpt-5.6-terra (attempt 1, 163s)
**Date**: 2026-10-27
**Notes**: Intent router changes (label validation, tenant routers, hint resolution, label tie-breaker) in intent_router.py plus tests. Merge-tier validation (chunk 2) green: 337 passed. Reviewed for file fidelity only (no line-level diff review). Closed via close_task.sh (no durable review EvidenceRef available for finalize_task).

**Deviations from spec**: none
