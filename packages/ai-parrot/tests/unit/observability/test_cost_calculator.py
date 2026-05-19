"""Unit tests for CostCalculator.

FEAT-177 TASK-1232.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import pytest

from parrot.observability.cost.calculator import (
    CostCalculator,
    _reset_pricing_cache_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset module-level pricing cache before and after each test."""
    _reset_pricing_cache_for_tests()
    yield
    _reset_pricing_cache_for_tests()


def test_known_model() -> None:
    """Known model returns the correct USD cost.

    gpt-4o-2024-08-06: input=2.50/1M, output=10.00/1M
    1000 input + 500 output:
      input_cost  = 1000 * 2.50 / 1e6 = 0.00250
      output_cost = 500  * 10.0 / 1e6 = 0.00500
      total = 0.00750
    """
    cc = CostCalculator(today=date(2026, 5, 18))
    cost = cc.cost_usd(
        provider="openai",
        model="gpt-4o-2024-08-06",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost is not None
    assert cost == pytest.approx(0.0075, rel=1e-4)


def test_unknown_model_returns_none_and_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown model returns None and logs exactly one WARN across 100 calls."""
    cc = CostCalculator(today=date(2026, 5, 18))
    with caplog.at_level(logging.WARNING):
        for _ in range(100):
            result = cc.cost_usd(
                provider="openai",
                model="ghost-model",
                input_tokens=1,
                output_tokens=1,
            )
            assert result is None

    warns = [r for r in caplog.records if "no pricing" in r.message.lower()]
    assert len(warns) == 1, f"Expected exactly 1 warn, got {len(warns)}"


def test_override_deep_merge(tmp_path: Path) -> None:
    """Override file replaces prices for listed models; bundled others remain."""
    override = tmp_path / "openai.json"
    override.write_text(json.dumps({
        "pricing": {
            "last_updated": "2026-05-18",
            "source": "test",
            "currency": "USD",
        },
        "models": {
            "gpt-4o-2024-08-06": {
                "input_per_1m": 1.0,
                "output_per_1m": 4.0,
            }
        },
    }))
    cc = CostCalculator(override_path=str(tmp_path), today=date(2026, 5, 18))
    # Override pricing: 1000*1/1e6 + 500*4/1e6 = 0.001 + 0.002 = 0.003
    cost = cc.cost_usd(
        provider="openai",
        model="gpt-4o-2024-08-06",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost == pytest.approx(0.003, rel=1e-4)

    # Bundled model absent from override remains accessible
    mini_cost = cc.cost_usd(
        provider="openai",
        model="gpt-4o-mini-2024-07-18",
        input_tokens=1000,
        output_tokens=1000,
    )
    assert mini_cost is not None, "Bundled model should still be priced"


def test_stale_pricing_warns_at_boot(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Pricing file with last_updated > 90 days ago triggers a WARN at construction."""
    override = tmp_path / "openai.json"
    override.write_text(json.dumps({
        "pricing": {
            "last_updated": "2025-01-01",
            "source": "old-data",
            "currency": "USD",
        },
        "models": {
            "gpt-4o-2024-08-06": {
                "input_per_1m": 2.50,
                "output_per_1m": 10.00,
            }
        },
    }))
    with caplog.at_level(logging.WARNING):
        CostCalculator(override_path=str(tmp_path), today=date(2026, 5, 18))

    stale_warns = [
        r for r in caplog.records
        if "stale" in r.message.lower() or "older" in r.message.lower()
    ]
    assert stale_warns, "Expected at least one staleness WARN"


def test_filesystem_io_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pricing is loaded from disk exactly once; subsequent constructors reuse cache."""
    reads: list[str] = []
    real_read = Path.read_text

    def counted_read(self: Path, *args, **kwargs):
        reads.append(str(self))
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read)

    CostCalculator(today=date(2026, 5, 18))
    after_first = len(reads)
    assert after_first > 0, "First construction must read files"

    CostCalculator(today=date(2026, 5, 18))
    assert len(reads) == after_first, "Second construction must not read additional files"


def test_cached_input_tokens_reduce_cost() -> None:
    """Cached input tokens are billed at the lower cached_input_per_1m rate."""
    cc = CostCalculator(today=date(2026, 5, 18))
    # gpt-4o-2024-08-06: input=2.50, cached=1.25, output=10.00
    # 1000 total input, 500 cached: non_cached=500, cached=500, output=200
    # input_cost  = 500 * 2.50 / 1e6 = 0.00125
    # cached_cost = 500 * 1.25 / 1e6 = 0.000625
    # output_cost = 200 * 10.0 / 1e6 = 0.002
    # total = 0.003875
    cost = cc.cost_usd(
        provider="openai",
        model="gpt-4o-2024-08-06",
        input_tokens=1000,
        output_tokens=200,
        cached_input_tokens=500,
    )
    assert cost == pytest.approx(0.003875, rel=1e-4)


def test_anthropic_pricing() -> None:
    """Anthropic models are priced via bundled anthropic.json."""
    cc = CostCalculator(today=date(2026, 5, 18))
    cost = cc.cost_usd(
        provider="anthropic",
        model="claude-3-5-sonnet",
        input_tokens=1000,
        output_tokens=500,
    )
    # claude-3-5-sonnet: input=3.00/1M, output=15.00/1M
    # 1000*3/1e6 + 500*15/1e6 = 0.003 + 0.0075 = 0.0105
    assert cost == pytest.approx(0.0105, rel=1e-4)


def test_gemini_provider_resolved_via_google_file() -> None:
    """Provider 'gemini' (from gen_ai.system) maps to google.json file."""
    cc = CostCalculator(today=date(2026, 5, 18))
    cost = cc.cost_usd(
        provider="gemini",
        model="gemini-1.5-pro",
        input_tokens=1000,
        output_tokens=500,
    )
    # gemini-1.5-pro: input=1.25/1M, output=5.00/1M
    # 1000*1.25/1e6 + 500*5/1e6 = 0.00125 + 0.0025 = 0.00375
    assert cost == pytest.approx(0.00375, rel=1e-4)
