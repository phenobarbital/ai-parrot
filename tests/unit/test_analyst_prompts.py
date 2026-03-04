# tests/unit/test_analyst_prompts.py
from parrot.finance.prompts import ANALYST_EQUITY, ANALYST_SENTIMENT, ANALYST_RISK


class TestAnalystPromptsMassive:
    def test_equity_has_options_source(self):
        assert "massive:options_chain" in ANALYST_EQUITY

    def test_equity_has_earnings_source(self):
        assert "massive:benzinga_earnings" in ANALYST_EQUITY

    def test_equity_has_ratings_source(self):
        assert "massive:benzinga_analyst_ratings" in ANALYST_EQUITY

    def test_sentiment_has_short_interest(self):
        assert "massive:short_interest" in ANALYST_SENTIMENT

    def test_sentiment_has_short_volume(self):
        assert "massive:short_volume" in ANALYST_SENTIMENT

    def test_sentiment_has_squeeze_analysis(self):
        assert "massive:derived_short_analysis" in ANALYST_SENTIMENT

    def test_risk_has_greeks_source(self):
        assert "massive:options_chain" in ANALYST_RISK
