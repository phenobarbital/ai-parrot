"""Unit tests for memo_to_orders conversion in parrot/finance/swarm.py."""

import pytest
from parrot.finance.schemas import (
    AssetClass,
    ConsensusLevel,
    OrderStatus,
    Platform,
)
from parrot.finance.swarm import (
    InvestmentMemoOutput,
    MemoRecommendationOutput,
    PortfolioImpactOutput,
    memo_to_orders,
)


def _make_rec(**overrides) -> MemoRecommendationOutput:
    """Helper: build a MemoRecommendationOutput with sensible defaults."""
    defaults = {
        "id": "rec-001",
        "asset": "AAPL",
        "asset_class": "stock",
        "preferred_platform": "alpaca",
        "signal": "buy",
        "action": "BUY",
        "sizing_pct": 2.0,
        "entry_price_limit": 150.0,
        "stop_loss": 145.0,
        "take_profit": 160.0,
        "trailing_stop_pct": None,
        "consensus_level": "majority",
        "bull_case": "Strong earnings",
        "bear_case": "Overvalued",
        "time_horizon": "swing",
        "analyst_votes": {
            "macro_analyst": "buy",
            "equity_analyst": "buy",
            "crypto_analyst": "hold",
            "sentiment_analyst": "buy",
            "risk_analyst": "hold",
        },
    }
    defaults.update(overrides)
    return MemoRecommendationOutput(**defaults)


def _make_memo(recs: list[MemoRecommendationOutput]) -> InvestmentMemoOutput:
    """Helper: wrap recommendations in an InvestmentMemoOutput."""
    return InvestmentMemoOutput(
        id="memo-001",
        created_at="2026-02-08T23:00:00Z",
        valid_until="2026-02-09T23:00:00Z",
        executive_summary="Test memo",
        market_conditions="Neutral",
        recommendations=recs,
        deliberation_rounds=1,
        final_consensus="majority",
        source_report_ids=["r1"],
        deliberation_round_ids=["d1"],
    )


class TestMemoToOrders:
    """Tests for memo_to_orders()."""

    def test_sizing_pct_transferred(self):
        """C1: sizing_pct from recommendation must appear on TradingOrder."""
        memo = _make_memo([_make_rec(sizing_pct=2.5)])
        orders = memo_to_orders(memo)
        assert len(orders) == 1
        assert orders[0].sizing_pct == 2.5

    def test_platform_assigned_alpaca(self):
        """C3: preferred_platform 'alpaca' maps to Platform.ALPACA."""
        memo = _make_memo([_make_rec(preferred_platform="alpaca")])
        orders = memo_to_orders(memo)
        assert orders[0].assigned_platform == Platform.ALPACA

    def test_platform_assigned_binance(self):
        """C3: preferred_platform 'binance' maps to Platform.BINANCE."""
        memo = _make_memo([
            _make_rec(
                asset="BTC/USDT",
                asset_class="crypto",
                preferred_platform="binance",
            )
        ])
        orders = memo_to_orders(memo)
        assert orders[0].assigned_platform == Platform.BINANCE
        assert orders[0].asset_class == AssetClass.CRYPTO

    def test_platform_assigned_kraken(self):
        """C3: preferred_platform 'kraken' maps to Platform.KRAKEN."""
        memo = _make_memo([
            _make_rec(
                asset="ETH/USDT",
                asset_class="crypto",
                preferred_platform="kraken",
            )
        ])
        orders = memo_to_orders(memo)
        assert orders[0].assigned_platform == Platform.KRAKEN

    def test_platform_none_when_not_specified(self):
        """C3: None preferred_platform results in None assigned_platform."""
        memo = _make_memo([_make_rec(preferred_platform=None)])
        orders = memo_to_orders(memo)
        assert orders[0].assigned_platform is None

    def test_hold_signal_skipped(self):
        """Hold signals should be skipped."""
        memo = _make_memo([_make_rec(signal="hold")])
        orders = memo_to_orders(memo)
        assert len(orders) == 0

    def test_divided_consensus_skipped(self):
        """Divided consensus should be skipped."""
        memo = _make_memo([_make_rec(consensus_level="divided")])
        orders = memo_to_orders(memo)
        assert len(orders) == 0

    def test_consensus_level_mapped(self):
        """Consensus level string maps to ConsensusLevel enum."""
        memo = _make_memo([_make_rec(consensus_level="unanimous")])
        orders = memo_to_orders(memo)
        assert orders[0].consensus_level == ConsensusLevel.UNANIMOUS

    def test_order_status_pending(self):
        """New orders should start as PENDING."""
        memo = _make_memo([_make_rec()])
        orders = memo_to_orders(memo)
        assert orders[0].status == OrderStatus.PENDING

    def test_ttl_from_time_horizon(self):
        """TTL should be set based on time_horizon."""
        memo = _make_memo([_make_rec(time_horizon="intraday")])
        orders = memo_to_orders(memo)
        assert orders[0].ttl_seconds == 14400  # 4 hours
