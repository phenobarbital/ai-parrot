---
type: Wiki Overview
title: 'TASK-1232: CostCalculator + bundled pricing JSON'
id: doc:sdd-tasks-completed-task-1232-cost-calculator-pricing-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 5 and brainstorm §4.6. Stateless cost calculator with per-provider
  bundled JSON pricing tables. Pricing loaded once at module import — never re-read
  in the hot path. Unknown `(provider, model)` returns `None` and logs once.
relates_to:
- concept: mod:parrot.observability
  rel: mentions
- concept: mod:parrot.observability.cost
  rel: mentions
- concept: mod:parrot.observability.cost.calculator
  rel: mentions
---

# TASK-1232: CostCalculator + bundled pricing JSON

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1228
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 and brainstorm §4.6. Stateless cost calculator with per-provider bundled JSON pricing tables. Pricing loaded once at module import — never re-read in the hot path. Unknown `(provider, model)` returns `None` and logs once.

Resolved decisions (spec §8):
- D5: bundled JSON updated each minor release with `pricing.last_updated` field; WARN at boot if any file > 90 days old.
- Override path: `ObservabilityConfig.pricing_override_path` (defaults to env var `PARROT_PRICING_PATH` read via navconfig) — deep-merge.

---

## Scope

- Create `parrot/observability/cost/calculator.py` with `CostCalculator` class.
- Create bundled `pricing/{openai,anthropic,google,groq,nvidia}.json` files.
- Implement `cost_usd(*, provider, model, input_tokens, output_tokens, cached_input_tokens=0) -> Optional[float]`.
- Load bundled pricing at first-instance construction (module-level cache); apply `pricing_override_path` overrides via deep-merge.
- Log a one-time WARN per unknown `(provider, model)` pair.
- Log a boot WARN if any bundled file's `pricing.last_updated` is > 90 days old (relative to today, 2026-05-18).
- Unit tests for known/unknown models, override, stale warning, deep-merge.

**NOT in scope**: writing back to `CompletionUsage.estimated_cost` (subscribers do this); the override env-var resolver lives in `setup_telemetry` (TASK-1235) — this task accepts an explicit `override_path` constructor argument.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/cost/calculator.py` | CREATE | `CostCalculator` + loader. |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/openai.json` | CREATE | OpenAI model pricing. |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/anthropic.json` | CREATE | Anthropic model pricing. |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/google.json` | CREATE | Google/Gemini model pricing. |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/groq.json` | CREATE | Groq model pricing. |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/nvidia.json` | CREATE | NVIDIA NIM pricing (best-effort; may be empty `{}` with last_updated set). |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/README.md` | CREATE | Format documentation. |
| `packages/ai-parrot/tests/unit/observability/test_cost_calculator.py` | CREATE | Tests per acceptance criteria. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import json
import logging
from pathlib import Path
from datetime import date
from typing import Optional
```

### Pricing JSON format (per brainstorm §4.6)

```json
{
  "pricing": {
    "last_updated": "2026-05-18",
    "source": "https://openai.com/api/pricing/",
    "currency": "USD"
  },
  "models": {
    "gpt-4o-2024-08-06": {
      "input_per_1m":  2.50,
      "output_per_1m": 10.00,
      "cached_input_per_1m": 1.25,
      "valid_from": "2024-08-06"
    },
    "gpt-4o-mini-2024-07-18": {
      "input_per_1m": 0.15,
      "output_per_1m": 0.60,
      "valid_from": "2024-07-18"
    }
  }
}
```

Required fields per model: `input_per_1m`, `output_per_1m`. Optional: `cached_input_per_1m`, `valid_from`.

### `CostCalculator` signature (spec §2)

```python
class CostCalculator:
    def __init__(
        self,
        *,
        override_path: Optional[str] = None,
        stale_warn_days: int = 90,
        today: Optional[date] = None,   # for tests
    ) -> None: ...

    def cost_usd(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> Optional[float]: ...
```

### Provider key

The `provider` argument is the `gen_ai.system` resolved value (`openai`, `anthropic`, `gemini`, `groq`, `xai`, `nvidia`, `huggingface`). The bundled JSON files are keyed by **filename** matching `{provider}.json` for the standard providers; `xai` and `huggingface` are not bundled in Phase 1 and return `None` (deferred until pricing is published).

`google.json` covers `gemini` (the resolved value for `client_name="google"`).

### Does NOT Exist

- ~~A remote pricing-fetch endpoint~~ — D5 chose option (a), bundled JSON only.
- ~~`CompletionUsage.estimated_cost` mutation in this module~~ — populated by the subscriber, not the calculator.

---

## Implementation Notes

### Pricing math

```python
input_cost = (input_tokens - cached_input_tokens) * price["input_per_1m"] / 1_000_000
output_cost = output_tokens * price["output_per_1m"] / 1_000_000
cached_cost = cached_input_tokens * price.get("cached_input_per_1m",
                                              price["input_per_1m"]) / 1_000_000
total = input_cost + output_cost + cached_cost
```

Return rounded to 6 decimals for stability.

### Unknown-model warning (once per pair)

```python
self._warned_unknown: set[tuple[str, str]] = set()

if (provider, model) not in self._warned_unknown:
    self._warned_unknown.add((provider, model))
    self.logger.warning(
        "CostCalculator: no pricing for provider=%r model=%r — returning None.",
        provider, model,
    )
return None
```

### Stale-pricing boot warning

At construction, iterate over loaded files; for each one whose `pricing.last_updated` is > `stale_warn_days` days before `today`, emit ONE warning naming the provider and the cached date.

### Override deep-merge

If `override_path` is set and resolves to a directory, for each `<provider>.json` in that directory: deep-merge `models.*` over the bundled `models.*` (override wins per-model). Override file's `pricing.last_updated` overrides the bundled one.

### Module-level cache

Pricing dict loaded into a module-level `_LOADED: dict[str, dict] | None = None` and populated lazily on first `CostCalculator()` construction. Reset only via a private `_reset_pricing_cache_for_tests()` helper.

### Key Constraints

- All filesystem I/O at construction time, never in `cost_usd`.
- Logger: `logging.getLogger("parrot.observability.cost")`.
- All amounts in USD (D-future: currency is parametrized; not in Phase 1).

---

## Acceptance Criteria

- [ ] `from parrot.observability import CostCalculator` resolves.
- [ ] `CostCalculator().cost_usd(provider="openai", model="gpt-4o-2024-08-06", input_tokens=1000, output_tokens=500) == 0.0075`.
- [ ] `cost_usd(provider="openai", model="ghost-model", ...)` returns `None` and logs WARN exactly once across 100 calls.
- [ ] `CostCalculator(override_path=tmp_path).cost_usd(...)` reflects override values for any model present in `tmp_path/openai.json`.
- [ ] Override is deep-merge — models in the bundled file but absent in the override remain priced from bundled values.
- [ ] Boot WARN emitted (and only once per file) when a bundled `pricing.last_updated` is > 90 days before `today`.
- [ ] Construction performs filesystem I/O exactly once across multiple instantiations (module-level cache).

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_cost_calculator.py
import json
from datetime import date
from pathlib import Path
import pytest

from parrot.observability.cost.calculator import (
    CostCalculator, _reset_pricing_cache_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    _reset_pricing_cache_for_tests()
    yield
    _reset_pricing_cache_for_tests()


def test_known_model():
    cc = CostCalculator(today=date(2026, 5, 18))
    cost = cc.cost_usd(
        provider="openai", model="gpt-4o-2024-08-06",
        input_tokens=1000, output_tokens=500,
    )
    assert cost == pytest.approx(0.0075, rel=1e-4)


def test_unknown_model_returns_none_and_warns_once(caplog):
    cc = CostCalculator(today=date(2026, 5, 18))
    for _ in range(100):
        assert cc.cost_usd(
            provider="openai", model="ghost", input_tokens=1, output_tokens=1
        ) is None
    warns = [r for r in caplog.records if "no pricing" in r.message.lower()]
    assert len(warns) == 1


def test_override_deep_merge(tmp_path):
    override = tmp_path / "openai.json"
    override.write_text(json.dumps({
        "pricing": {"last_updated": "2026-05-18", "source": "test", "currency": "USD"},
        "models": {"gpt-4o-2024-08-06": {"input_per_1m": 1.0, "output_per_1m": 4.0}},
    }))
    cc = CostCalculator(override_path=str(tmp_path), today=date(2026, 5, 18))
    cost = cc.cost_usd(
        provider="openai", model="gpt-4o-2024-08-06",
        input_tokens=1000, output_tokens=500,
    )
    # 1000*1/1e6 + 500*4/1e6 = 0.001 + 0.002 = 0.003
    assert cost == pytest.approx(0.003, rel=1e-4)


def test_stale_pricing_warns_at_boot(tmp_path, caplog):
    override = tmp_path / "openai.json"
    override.write_text(json.dumps({
        "pricing": {"last_updated": "2025-01-01", "source": "old", "currency": "USD"},
        "models": {"gpt-4o-2024-08-06": {"input_per_1m": 2.5, "output_per_1m": 10.0}},
    }))
    CostCalculator(override_path=str(tmp_path), today=date(2026, 5, 18))
    stale = [r for r in caplog.records if "stale" in r.message.lower()
                                       or "older" in r.message.lower()]
    assert stale


def test_filesystem_io_once(tmp_path, monkeypatch):
    reads = []
    real_read = Path.read_text
    def counted_read(self, *a, **kw):
        reads.append(str(self))
        return real_read(self, *a, **kw)
    monkeypatch.setattr(Path, "read_text", counted_read)
    CostCalculator(today=date(2026, 5, 18))
    after_first = len(reads)
    CostCalculator(today=date(2026, 5, 18))
    assert len(reads) == after_first  # cache hit
```

---

## Agent Instructions

1. Confirm TASK-1228 complete.
2. Bundled pricing JSON values: source from each provider's pricing page on the day of implementation. Use the `valid_from` field to mark the model's pricing-effective date. Set `pricing.last_updated` to today's ISO date.
3. Implement `calculator.py` + JSON files + tests.
4. Run `pytest packages/ai-parrot/tests/unit/observability/test_cost_calculator.py -v`.

---

## Completion Note

*(Agent fills this in when done)*
