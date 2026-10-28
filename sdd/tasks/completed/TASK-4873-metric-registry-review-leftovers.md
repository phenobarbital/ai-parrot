# TASK-4873: Metric registry review leftovers (visibility, cache TTL, mixin filtering)

**Feature**: FEAT-756 — metric-definition-registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:a262cacba885`

## Context

Minor leftovers from the FEAT-756 code review, filed in the work ledger as
`issue:a262cacba885` and drained by `/sdd-fix`.

## Scope

1. `allowed_groups` is persisted but no `groups` visibility level exists —
   document it as reserved and reject non-empty values in the model.
2. Global `private` rows pass the DB CHECK but no list query ever returns them —
   reject them in the `MetricDefinition` validator.
3. `MetricRegistry._views` is never refreshed — add a TTL (`cache_ttl`) so
   HTTP writes reach running agents; rebuild the matcher bank only when the
   view's terms change.
4. Private-visibility filtering existed only in `MetricsToolkit` — move it into
   `MetricRegistry` (`user_id` on `list`/`describe`/`resolve`) and pass the
   caller from both `MetricsToolkit` and `MetricRoutingMixin`.
5. Amend spec D3 / `resolve_metric_tenant` docstring: the explicit kwarg is
   host-only; model-facing lanes pass `explicit=None`.
6. Document that hosts must set `RequestScope.may_author`.

**NOT in scope**: a `groups` visibility level; cross-process cache
invalidation hooks; the pre-existing unused import in `metrics/importers.py`.

## Files to Modify

- `packages/ai-parrot/src/parrot/metrics/registry.py`
- `packages/ai-parrot/src/parrot/metrics/models.py`
- `packages/ai-parrot/src/parrot/metrics/context.py`
- `packages/ai-parrot/src/parrot/bots/mixins/metric_routing.py`
- `packages/ai-parrot-tools/src/parrot_tools/metrics/toolkit.py`
- `packages/ai-parrot-server/src/parrot/handlers/scope.py`
- `sdd/specs/metric-definition-registry.spec.md`
- tests: `packages/ai-parrot/tests/unit/metrics/test_registry_view.py`,
  `packages/ai-parrot/tests/unit/metrics/test_models.py`,
  `packages/ai-parrot/tests/bots/test_metric_routing_mixin.py`,
  `packages/ai-parrot-server/tests/handlers/test_metric_definitions_store.py`

## Acceptance Criteria

- [x] A global `private` definition and a non-empty `allowed_groups` fail validation.
- [x] `MetricRegistry` hides another user's private metrics on list/describe/resolve.
- [x] `MetricRoutingMixin` resolves with the caller's `user_id`.
- [x] Definitions saved after the first read appear once `cache_ttl` elapses; `invalidate()` forces a reload.
- [x] Spec D3 and docstrings amended.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-server/src pytest -q packages/ai-parrot/tests/unit/metrics packages/ai-parrot/tests/bots/test_metric_routing_mixin.py packages/ai-parrot-tools/tests/metrics packages/ai-parrot-server/tests/handlers/test_metric_definitions_store.py packages/ai-parrot-server/tests/handlers/test_metric_definitions_handler.py
```

## Completion Note

Implemented in commit 068f7054f. 128 tests pass across the metric suites
(registry, models, mixin, toolkit, Postgres store, REST handler). Design
choices: `cache_ttl` defaults to 60 s; views are shared per tenant and only
split per caller when the tenant actually has `private` metrics, so the
matcher bank is not rebuilt per user in the common case. The store's SQL
still excludes global non-public rows as a defensive backstop.
