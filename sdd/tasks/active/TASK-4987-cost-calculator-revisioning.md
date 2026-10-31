# TASK-4987: CostCalculator cache-creation tier, valid_from, price revision stamping

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4986
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (mechanics half), design review S9, AC-4/AC-7. `CostCalculator.cost_usd`
has no cache-creation tier and ignores `valid_from` (the string appears nowhere in
calculator.py), so a price refresh silently rewrites history. This task adds the tier,
dated entries and a per-provider content revision, and stamps the revision onto every
priced event and record. Cost is still computed **exactly once at the origin** (FEAT-710 G5).

---

## Scope

- `cost_usd(...)` gains `cache_creation_tokens: int = 0` and `at: Optional[date] = None`. Its return contract is unchanged.
- Add `PricedCost` and `CostCalculator.price_call(**kwargs) -> PricedCost`. It uses the same arithmetic plus `price_revision`/`valid_from`/`priced`.
- Add `CostCalculator.revision_for(provider, model, at=None) -> tuple[Optional[str], Optional[str]]`, a lookup with no arithmetic, so the origin can stamp the revision without pricing twice.
- Price entries accept an optional `cache_creation_per_1m` and an optional `valid_from`. A model's value may be a dict (legacy, valid forever) or a list of dated dicts; `at` selects the latest entry whose `valid_from <= at`.
- The revision is the provider file's content hash, computed once at load into `_META[provider]["revision"]`.
- Add `price_revision: Optional[str]` and `price_valid_from: Optional[str]` to `AfterClientCallEvent` and `UsageRecord`. `clients/base.py::_emit_after_call` stamps them via `revision_for`. The subscriber copies them, and resolves them itself when it priced the event (unpriced-origin path).
- `resolve_event_cost` passes the event's cache counters **only when non-zero**.
- Tests with a frozen two-revision price-table pair under `packages/ai-parrot/tests/fixtures/pricing_revisions/`.

**NOT in scope**: changing any price value or adding models (TASK-4988); pricing policy (TASK-4989).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/cost/calculator.py` | MODIFY | Tier, `at`, `PricedCost`, `price_call`, `revision_for`, revision at load |
| `packages/ai-parrot/src/parrot/observability/cost/__init__.py` | MODIFY | `resolve_event_cost` passes cache counters |
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | `_emit_after_call` stamps the revision |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | MODIFY | `price_revision`/`price_valid_from` |
| `packages/ai-parrot/src/parrot/observability/recorders/models.py` | MODIFY | Same two fields |
| `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | MODIFY | Copy/resolve them |
| `packages/ai-parrot/tests/unit/observability/test_cost_revisioning.py` | CREATE | Tests |
| `packages/ai-parrot/tests/fixtures/pricing_revisions/rev_a/anthropic.json` | CREATE | Frozen fixture |
| `packages/ai-parrot/tests/fixtures/pricing_revisions/rev_b/anthropic.json` | CREATE | Frozen fixture (different prices + dated list) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.cost.calculator import CostCalculator, _reset_pricing_cache_for_tests  # calculator.py:135, :42
from parrot.observability.cost import get_shared_cost_calculator, resolve_event_cost              # cost/__init__.py
```

### Existing Signatures to Use
```python
# observability/cost/calculator.py
_LOADED: Optional[dict[str, dict[str, dict]]] = None   # :31
_META: dict[str, dict] = {}                            # :33 — {provider: {"last_updated", "source"}}
def _load_bundled_pricing() -> dict[str, dict[str, dict]]   # :49 — reads p.read_text() per *.json
def _apply_override(...)                                   # override merge (read it before editing)
class CostCalculator:                                      # :135
    def __init__(self, *, override_path=None, stale_warn_days=90, today=None)
    def cost_usd(self, *, provider, model, input_tokens, output_tokens, cached_input_tokens=0) -> Optional[float]  # :190
        # file_key = "google" if provider == "gemini" else provider   (:212)
        # cached_per_1m: float = price.get("cached_input_per_1m", input_per_1m)   (:229) — anchor
# clients/base.py
    async def _emit_after_call(self, tc, *, client_name, model, duration_ms, input_tokens=None, output_tokens=None, finish_reason=None) -> Optional[float]  # :729
        cost_usd = self._compute_call_cost(client_name, model, input_tokens, output_tokens)   # :757
    def _compute_call_cost(self, client_name, model, input_tokens, output_tokens) -> Optional[float]  # :792 — UNCHANGED
# observability/cost/__init__.py
def resolve_event_cost(event, fallback) -> Optional[float]:   # :86; calls calc.cost_usd(... output_tokens=event.output_tokens or 0,) (:104)
```

### Does NOT Exist
- ~~`CostCalculator` honouring `valid_from`~~ — this task creates it
- ~~`PricedCost`~~, ~~`CostCalculator.price_call`~~, ~~`CostCalculator.revision_for`~~ — this task creates them
- ~~`cache_creation_per_1m` in any pricing JSON~~ — TASK-4988 adds the data; this task only reads it, defaulting to `input_per_1m`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/observability/cost/calculator.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/cost/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/clients/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/subscriber.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/observability/test_cost_revisioning.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/fixtures/pricing_revisions/rev_a/anthropic.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/fixtures/pricing_revisions/rev_b/anthropic.json", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/cost/calculator.py#CostCalculator",
    "sym:packages/ai-parrot/src/parrot/observability/cost/calculator.py#_load_bundled_pricing",
    "sym:packages/ai-parrot/src/parrot/observability/cost/__init__.py#resolve_event_cost",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_after_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._compute_call_cost"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **AC-4 trap**: `test_cost_computed_once.py:23` uses a spy whose `cost_usd(self, *, provider, model, input_tokens, output_tokens)` accepts ONLY those four kwargs. `resolve_event_cost` must add `cached_input_tokens=`/`cache_creation_tokens=` **only when the value is > 0**. Otherwise the spy raises TypeError, cost becomes None, and the test fails.
- `clients/base.py` is "discuss before modifying". The spec lists it as an edit site with the contract unchanged. Touch only `_emit_after_call`'s event construction: `_compute_call_cost` keeps its signature, and `revision_for` does no arithmetic, so cost is still computed once.
- Anthropic `input_tokens` already **excludes** cache reads/writes, while OpenAI `prompt_tokens` **includes** cached tokens. The existing formula (`non_cached = input - cached`) assumes OpenAI semantics. Do not change it for `cached_input_tokens`. Price `cache_creation_tokens` as an **additional** amount (`cache_creation_tokens * cache_creation_per_1m`), never subtracted from input. Document this in the docstring.
- The revision string is `f"{file_key}@{sha256(file_bytes).hexdigest()[:12]}"`. An override recomputes the overridden provider's revision from the override file's bytes.

---

## Implementation Blueprint

### Steps (in order)
1. Compute the revision in `_load_bundled_pricing` (and in the override path) into `_META`, so revision lookup is O(1) with no I/O on the hot path.
2. Add `_select_entry(price_value, at)`, which normalizes dict-or-list to one dict; it is the single place `valid_from` is honoured.
3. Extend `cost_usd`; add `price_call` and `revision_for`.
4. Add event/record fields, stamp them in `base.py`, and copy them in the subscriber.
5. Update `resolve_event_cost` (non-zero-only kwargs).
6. Fixtures + tests.

### `packages/ai-parrot/src/parrot/observability/cost/calculator.py` (MODIFY)
```python
# AFTER the imports (add `import hashlib` and `from pydantic import BaseModel`)
class PricedCost(BaseModel):
    """One computed cost plus the price revision that produced it (FEAT-783 S9)."""

    usd: Optional[float] = None
    price_revision: Optional[str] = None
    valid_from: Optional[str] = None
    priced: bool = False


def _select_entry(value: "dict | list[dict]", at: Optional[date]) -> Optional[dict]:
    """Return the price entry in force at *at* (None = latest). A bare dict is valid forever."""
    # FILL IN: list -> keep entries whose date.fromisoformat(valid_from) <= at (missing valid_from = date.min);
    # return the one with the max valid_from; None when no entry is in force — bounded by AC-7
    raise NotImplementedError
```
```python
# occurrences: 1 (verified: grep -c '    def cost_usd(' calculator.py) — widen the signature at calculator.py:190
    def cost_usd(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        cache_creation_tokens: int = 0,
        at: Optional[date] = None,
    ) -> Optional[float]:
        """...existing docstring + cache_creation_tokens (additive tier) and at (valid_from window)..."""
        return self.price_call(
            provider=provider, model=model, input_tokens=input_tokens, output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens, cache_creation_tokens=cache_creation_tokens, at=at,
        ).usd
```
```python
# Move the existing arithmetic (calculator.py:211-238) into price_call; at the anchor
# `        cached_per_1m: float = price.get("cached_input_per_1m", input_per_1m)` (calculator.py:229, 1 occurrence) add:
        cache_creation_per_1m: float = price.get("cache_creation_per_1m", input_per_1m)
# and add to total:  cache_creation_tokens * cache_creation_per_1m / 1_000_000

    def price_call(self, **kwargs: Any) -> PricedCost:
        """Same arithmetic as cost_usd, plus the revision and valid_from that produced it."""
        # FILL IN: resolve file_key (gemini->google), _select_entry(..., kwargs.get("at")),
        # unpriced -> PricedCost(priced=False) and _warn_unknown; else compute — bounded by AC-7 (None never a guess)
        raise NotImplementedError

    def revision_for(
        self, provider: str, model: str, at: Optional[date] = None
    ) -> tuple[Optional[str], Optional[str]]:
        """(price_revision, valid_from) for the entry in force, without computing a cost."""
        # FILL IN: lookup only — bounded by FEAT-710 G5 (no arithmetic here)
        raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/observability/cost/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            output_tokens=event.output_tokens or 0,' __init__.py) — inside resolve_event_cost (:104)
# REPLACE the calc.cost_usd(...) call with:
        extra: dict[str, int] = {}
        if getattr(event, "cache_read_tokens", None):
            extra["cached_input_tokens"] = event.cache_read_tokens
        if getattr(event, "cache_creation_tokens", None):
            extra["cache_creation_tokens"] = event.cache_creation_tokens
        return calc.cost_usd(
            provider=resolve_gen_ai_system(event.client_name),
            model=event.model,
            input_tokens=event.input_tokens or 0,
            output_tokens=event.output_tokens or 0,
            **extra,  # only when non-zero: duck-typed calculators (test_cost_computed_once.py:23) take 4 kwargs
        )
```

### `packages/ai-parrot/src/parrot/clients/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            cost_usd=cost_usd,' base.py) — inside _emit_after_call's AfterClientCallEvent(...) (base.py:775)
# AFTER — insert below `            cost_usd=cost_usd,`
            **self._price_revision_fields(client_name, model, cost_usd),
```
```python
# NEW private method directly after _compute_call_cost (ends base.py:~812)
    def _price_revision_fields(
        self, client_name: str, model: "Optional[str]", cost_usd: "Optional[float]"
    ) -> "dict[str, Optional[str]]":
        """FEAT-783: the revision that priced this call — a lookup, never a second computation."""
        if cost_usd is None:
            return {}
        calc = get_shared_cost_calculator()
        if calc is None or not hasattr(calc, "revision_for"):
            return {}
        try:
            from parrot.observability.attributes import resolve_gen_ai_system  # noqa: PLC0415

            revision, valid_from = calc.revision_for(resolve_gen_ai_system(client_name), model or "")
            return {"price_revision": revision, "price_valid_from": valid_from}
        except Exception:  # noqa: BLE001 — telemetry must never break the call path
            return {}
```

### Event / record / subscriber (MODIFY)
```python
# client.py — below the FEAT-783 counter block TASK-4986 added in AfterClientCallEvent:
    price_revision: Optional[str] = None    # FEAT-783 S9
    price_valid_from: Optional[str] = None  # FEAT-783 S9
# models.py — inside the FEAT-783 four-counter block TASK-4986 added:
    price_revision: Optional[str] = None
    price_valid_from: Optional[str] = None
# subscriber.py _on_client_after — after the counter kwargs TASK-4986 added:
#   FILL IN: price_revision/price_valid_from = event's when event.cost_usd is not None; else, when
#   resolve_event_cost priced it here, take them from (get_shared_cost_calculator() or self._cost).revision_for(...)
#   guarded by hasattr — bounded by AC-7 and FEAT-710 G5 (never compute cost twice)
```

### Fixtures + `test_cost_revisioning.py` (CREATE)
```python
"""FEAT-783 TASK-4987 — cache-creation tier, valid_from window, price revision (AC-4, AC-7)."""
from datetime import date
from pathlib import Path

import pytest

from parrot.observability.cost.calculator import CostCalculator, _reset_pricing_cache_for_tests

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "pricing_revisions"


@pytest.fixture(autouse=True)
def _fresh_cache():
    _reset_pricing_cache_for_tests()
    yield
    _reset_pricing_cache_for_tests()


def test_cache_creation_tier_is_additive() -> None:
    # FILL IN: ...
    ...


def test_valid_from_selects_window() -> None:
    # FILL IN: rev_b holds a dated list; at=before/after the boundary gives the two different prices
    ...


def test_revision_changes_with_file_content() -> None:
    # FILL IN: override rev_a vs rev_b -> different price_revision for the same model (AC-7: explicit, not silent)
    ...


def test_unpriced_pair_still_none() -> None:
    # FILL IN: price_call(...).priced is False and cost_usd(...) is None
    ...
```
Fixture JSON follows the bundled shape (`{"pricing": {"last_updated", "source", "currency"}, "models": {...}}`). `rev_b` holds one model as a two-element list with `valid_from` dates.

### FILL IN checklist
- [ ] `_select_entry`; bounded by AC-7
- [ ] `price_call` / `revision_for`; bounded by FEAT-710 G5
- [ ] Override path recomputes the revision; bounded by Key Constraints
- [ ] Subscriber revision copy/resolve; bounded by AC-7
- [ ] Test bodies + fixtures

---

## Acceptance Criteria

- [ ] AC-4: `test_cost_computed_once.py` and `test_shared_cost_calculator.py` still pass.
- [ ] AC-7: every priced event and record carries `price_revision` + `price_valid_from`. Re-pricing against a different revision yields a different `price_revision`.
- [ ] An unpriced `(provider, model)` still returns `None`.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/observability/test_cost_revisioning.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_cost_calculator.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_cost_computed_once.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_shared_cost_calculator.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_client_event_tenant_cost.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Nine files only. `PYTHONPATH=packages/ai-parrot/src`. Do not change any bundled price value.

## Completion Note
_(filled at close)_
