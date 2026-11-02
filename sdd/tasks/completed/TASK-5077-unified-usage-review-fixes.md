# TASK-5077: FEAT-783 review fixes — strict price_call, per-model revision, ASYNC221

**Feature**: FEAT-783 — unified-usage
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:d95710046fd7`

## Context
Post-implementation review of FEAT-783 (ledger `issue:d95710046fd7`) found typing, revision-labelling
and lint debt in the cost calculator and its tests.

## Scope
1. `CostCalculator.price_call` takes explicit keyword-only params (misspelled kwargs raise `TypeError`).
2. Document the `PricingPolicy.apply(usd)` deviation from the spec's `apply(priced: PricedCost)`.
3. Price revision is tracked per `(provider, model)`: a bundled model absent from an override keeps
   the bundled file's revision instead of the override's hash.
4. Fix ruff ASYNC221 (blocking `subprocess.run` in async tests) via `asyncio.to_thread`.

### NOT in scope (split to a follow-up ledger issue)
- `clients/base.py` `hasattr(self, "_price_revision_fields")` dead code and missing
  cache_read/cache_creation tokens on API-client events — `clients/base.py` requires discussion first.
- `CodexUsageCodec._find_value` nested-match risk — AC-8 needs spike S1 on real codex streams.

## Files to Modify
- `packages/ai-parrot/src/parrot/observability/cost/calculator.py`
- `packages/ai-parrot/src/parrot/observability/cost/policy.py`
- `packages/ai-parrot/tests/unit/observability/test_cost_revisioning.py`
- `packages/ai-parrot/tests/unit/observability/test_spec_usage_recorder.py`
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_usage_attribution.py`

## Acceptance Criteria
- [x] `price_call(..., cached_tokens=5)` raises `TypeError`.
- [x] Under an override, a bundled-only model's revision differs from an overridden model's revision.
- [x] `ruff check` clean on the touched test files (no ASYNC221).

## Validation Commands
```bash
PYTHONPATH=packages/ai-parrot/src pytest -q packages/ai-parrot/tests/unit/observability/test_cost_revisioning.py \
  packages/ai-parrot/tests/unit/observability/test_spec_usage_recorder.py \
  packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_usage_attribution.py
```

## Completion Note
Implemented in 332046b71b. Two regression tests added to `test_cost_revisioning.py`; 96 cost/usage/pricing/policy
tests pass. Items 3 and 5 of the issue split to a follow-up ledger issue.
