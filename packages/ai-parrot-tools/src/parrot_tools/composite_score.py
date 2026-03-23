"""
Composite Score Tool for Technical Analysis.

Provides 0-10 bullish/bearish scores for ranking multiple assets by technical strength.
"""
from typing import Literal, Dict, Any

from pydantic import BaseModel, Field
from navconfig.logging import logging

from .toolkit import AbstractToolkit
from .technical_analysis import (
    TechnicalAnalysisTool,
    CompositeScore,
)


class CompositeScoreInput(BaseModel):
    """Input schema for CompositeScoreTool."""
    symbol: str = Field(..., description="Symbol to score (e.g., 'AAPL', 'BTC')")
    asset_type: Literal["stock", "crypto"] = Field(
        "stock",
        description="Asset type for appropriate indicator weighting"
    )
    score_type: Literal["bullish", "bearish"] = Field(
        "bullish",
        description="Score type: bullish scores favor uptrend indicators, bearish favors downtrend"
    )
    source: str = Field("alpaca", description="Data source: 'alpaca', 'coingecko', 'cryptoquant'")
    lookback_days: int = Field(365, description="Days of historical data for calculation")


class CompositeScoreTool(AbstractToolkit):
    """
    Tool for computing composite technical scores for asset ranking.

    Enables queries like "which of these 10 stocks has the strongest bullish setup?"
    and powers the equity research crew's scanning capabilities.

    Score Components (max 10 points):
    - SMA Position: 0-2 pts (price relative to SMA50/SMA200)
    - RSI Zone: 0-1 pt (momentum zone scoring)
    - MACD: 0-1.5 pts (trend confirmation)
    - ADX Trend: 0-1.5 pts (trend strength)
    - Momentum: 0-2 pts (price momentum)
    - Volume: 0-1 pt (volume confirmation)
    - EMA Alignment: 0-1 pt (EMA stack alignment)
    """
    name = "composite_score"
    description = (
        "Computes composite bullish/bearish scores (0-10) for ranking assets "
        "by technical strength. Use for screening and relative comparison."
    )
    args_schema = CompositeScoreInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._tech_tool = None

    @property
    def tech_tool(self) -> TechnicalAnalysisTool:
        """Lazy initialization of TechnicalAnalysisTool."""
        if self._tech_tool is None:
            self._tech_tool = TechnicalAnalysisTool()
        return self._tech_tool

    async def _execute(
        self,
        symbol: str,
        asset_type: Literal["stock", "crypto"] = "stock",
        score_type: Literal["bullish", "bearish"] = "bullish",
        source: str = "alpaca",
        lookback_days: int = 365,
    ) -> CompositeScore:
        """
        Compute composite technical score for an asset.

        Args:
            symbol: Asset symbol to analyze
            asset_type: 'stock' or 'crypto' for appropriate weighting
            score_type: 'bullish' for uptrend scoring, 'bearish' for downtrend
            source: Data source for fetching prices
            lookback_days: Historical data period

        Returns:
            CompositeScore with total score, components breakdown, and recommendation
        """
        # Fetch data and compute indicators using TechnicalAnalysisTool
        analysis = await self.tech_tool._execute(
            symbol=symbol,
            asset_type=asset_type,
            source=source,
            lookback_days=lookback_days,
        )

        if "error" in analysis:
            return CompositeScore(
                symbol=symbol,
                score=0.0,
                max_score=10.0,
                label="neutral",
                components={},
                signals=[],
                recommendation_hint="data_unavailable"
            )

        # Calculate score components
        components = self._calculate_components(analysis, score_type, asset_type)

        # Sum total score
        total = sum(c["score"] for c in components.values())

        # Determine label based on score and type
        label = self._determine_label(total, score_type)

        # Generate recommendation hint
        hint = self._get_recommendation_hint(label)

        return CompositeScore(
            symbol=symbol,
            score=round(total, 2),
            max_score=10.0,
            label=label,
            components=components,
            signals=analysis.get("signals", []),
            recommendation_hint=hint
        )

    def _calculate_components(
        self,
        analysis: Dict[str, Any],
        score_type: str,
        asset_type: str
    ) -> Dict[str, Dict[str, float]]:
        """
        Calculate individual score components.

        Args:
            analysis: Output from TechnicalAnalysisTool
            score_type: 'bullish' or 'bearish'
            asset_type: 'stock' or 'crypto'

        Returns:
            Dict mapping component names to {score, max} dicts
        """
        components = {}
        indicators = analysis.get("indicators", {})
        price = analysis.get("price", 0)

        # Bullish vs bearish scoring inverts some conditions
        is_bullish = score_type == "bullish"

        # 1. SMA Position (0-2 pts)
        # Price above SMA50: +1 pt, Price above SMA200: +1 pt
        sma_score = 0.0
        sma_50 = indicators.get("SMA_50")
        sma_200 = indicators.get("SMA_200")

        if sma_50 is not None and price:
            if is_bullish:
                if price > sma_50:
                    sma_score += 1.0
            else:
                if price < sma_50:
                    sma_score += 1.0

        if sma_200 is not None and price:
            if is_bullish:
                if price > sma_200:
                    sma_score += 1.0
            else:
                if price < sma_200:
                    sma_score += 1.0

        components["sma_position"] = {"score": sma_score, "max": 2.0}

        # 2. RSI Zone (0-1 pt)
        # Bullish: 50-70 zone = 1.0, 30-50 = 0.5, <30 (oversold) = 0.25
        # Bearish: 30-50 zone = 1.0, 50-70 = 0.5, >70 (overbought) = 0.25
        rsi = indicators.get("RSI_14")
        rsi_score = 0.0

        if rsi is not None:
            if is_bullish:
                if 50 <= rsi <= 70:
                    rsi_score = 1.0
                elif 30 <= rsi < 50:
                    rsi_score = 0.5
                elif rsi < 30:
                    # Oversold can be bullish reversal opportunity
                    rsi_score = 0.25
            else:
                if 30 <= rsi <= 50:
                    rsi_score = 1.0
                elif 50 < rsi <= 70:
                    rsi_score = 0.5
                elif rsi > 70:
                    # Overbought can be bearish reversal opportunity
                    rsi_score = 0.25

        components["rsi_zone"] = {"score": rsi_score, "max": 1.0}

        # 3. MACD (0-1.5 pts)
        # MACD > Signal: +1.0, Histogram > 0: +0.5
        macd = indicators.get("MACD", {})
        macd_score = 0.0

        if isinstance(macd, dict):
            macd_val = macd.get("value")
            macd_signal = macd.get("signal")
            macd_hist = macd.get("hist")

            if macd_val is not None and macd_signal is not None:
                if is_bullish:
                    if macd_val > macd_signal:
                        macd_score += 1.0
                else:
                    if macd_val < macd_signal:
                        macd_score += 1.0

            if macd_hist is not None:
                if is_bullish:
                    if macd_hist > 0:
                        macd_score += 0.5
                else:
                    if macd_hist < 0:
                        macd_score += 0.5

        components["macd"] = {"score": min(macd_score, 1.5), "max": 1.5}

        # 4. ADX Trend (0-1.5 pts)
        # ADX > 25 with correct DI alignment: 1.5 pts
        # ADX 20-25: 0.5 pts
        # ADX < 20: 0 pts (no trend)
        # Note: ADX not yet in TechnicalAnalysisTool output, placeholder
        adx_score = 0.0
        # When ADX is available from analysis, calculate:
        # adx = analysis.get("adx")
        # if adx:
        #     if adx.value > 25:
        #         if (is_bullish and adx.trend_direction == "bullish") or \
        #            (not is_bullish and adx.trend_direction == "bearish"):
        #             adx_score = 1.5
        #     elif adx.value >= 20:
        #         adx_score = 0.5
        components["adx_trend"] = {"score": adx_score, "max": 1.5}

        # 5. Momentum (0-2 pts)
        # Based on price change relative to SMA, scaled
        # For now: if price > SMA50 by more than 5%, add momentum points
        momentum_score = 0.0

        if sma_50 is not None and price and sma_50 > 0:
            pct_from_sma = ((price - sma_50) / sma_50) * 100
            if is_bullish:
                # Bullish: reward price above SMA
                if pct_from_sma > 10:
                    momentum_score = 2.0
                elif pct_from_sma > 5:
                    momentum_score = 1.5
                elif pct_from_sma > 0:
                    momentum_score = 1.0
                elif pct_from_sma > -5:
                    momentum_score = 0.5
            else:
                # Bearish: reward price below SMA
                if pct_from_sma < -10:
                    momentum_score = 2.0
                elif pct_from_sma < -5:
                    momentum_score = 1.5
                elif pct_from_sma < 0:
                    momentum_score = 1.0
                elif pct_from_sma < 5:
                    momentum_score = 0.5

        components["momentum"] = {"score": momentum_score, "max": 2.0}

        # 6. Volume (0-1 pt)
        # Volume > 1.5x avg: 1.0, Volume > avg: 0.5
        volume_score = 0.0
        avg_vol = indicators.get("Avg_Volume_20d", 0)
        current_vol = analysis.get("volume", 0)

        if avg_vol and avg_vol > 0 and current_vol:
            vol_ratio = current_vol / avg_vol
            if vol_ratio > 1.5:
                volume_score = 1.0
            elif vol_ratio > 1.0:
                volume_score = 0.5

        components["volume"] = {"score": volume_score, "max": 1.0}

        # 7. EMA Alignment (0-1 pt)
        # EMA12 > EMA26 > SMA50 = bullish stack (1.0)
        # Note: EMA not yet in TechnicalAnalysisTool output, placeholder
        ema_score = 0.0
        # When EMA is available:
        # ema_12 = indicators.get("EMA_12")
        # ema_26 = indicators.get("EMA_26")
        # if ema_12 and ema_26 and sma_50:
        #     if is_bullish:
        #         if ema_12 > ema_26 > sma_50:
        #             ema_score = 1.0
        #         elif ema_12 > ema_26:
        #             ema_score = 0.5
        #     else:
        #         if ema_12 < ema_26 < sma_50:
        #             ema_score = 1.0
        #         elif ema_12 < ema_26:
        #             ema_score = 0.5
        components["ema_alignment"] = {"score": ema_score, "max": 1.0}

        # Apply asset-type adjustments
        if asset_type == "crypto":
            # Crypto: weight momentum higher (more volatile)
            components["momentum"]["max"] = 2.5
            # Crypto: reduce SMA weight (less reliable for crypto)
            components["sma_position"]["max"] = 1.5
            # Scale down SMA score proportionally
            if components["sma_position"]["score"] > 1.5:
                components["sma_position"]["score"] = 1.5

        return components

    def _determine_label(
        self,
        total_score: float,
        score_type: str
    ) -> str:
        """
        Determine the classification label based on total score.

        Thresholds:
        - >= 7.5: strong
        - >= 5.5: moderate
        - >= 3.5: neutral
        - >= 2.0: moderate (opposite)
        - < 2.0: strong (opposite)

        Args:
            total_score: Total composite score
            score_type: 'bullish' or 'bearish'

        Returns:
            Label string
        """
        if total_score >= 7.5:
            return "strong_bullish" if score_type == "bullish" else "strong_bearish"
        elif total_score >= 5.5:
            return "moderate_bullish" if score_type == "bullish" else "moderate_bearish"
        elif total_score >= 3.5:
            return "neutral"
        elif total_score >= 2.0:
            return "moderate_bearish" if score_type == "bullish" else "moderate_bullish"
        else:
            return "strong_bearish" if score_type == "bullish" else "strong_bullish"

    def _get_recommendation_hint(self, label: str) -> str:
        """
        Generate recommendation hint based on label.

        Args:
            label: Classification label

        Returns:
            Action hint string
        """
        hints = {
            "strong_bullish": "trending_entry",
            "moderate_bullish": "pullback_buy",
            "neutral": "wait",
            "moderate_bearish": "caution",
            "strong_bearish": "avoid",
        }
        return hints.get(label, "wait")

    async def compute_score(
        self,
        symbol: str,
        asset_type: Literal["stock", "crypto"] = "stock",
        score_type: Literal["bullish", "bearish"] = "bullish",
        source: str = "alpaca",
        lookback_days: int = 365,
    ) -> CompositeScore:
        """
        Public async method for computing composite score.

        This is the method exposed as a tool via AbstractToolkit.

        Args:
            symbol: Asset symbol to analyze
            asset_type: 'stock' or 'crypto'
            score_type: 'bullish' or 'bearish'
            source: Data source
            lookback_days: Historical period

        Returns:
            CompositeScore result
        """
        return await self._execute(
            symbol=symbol,
            asset_type=asset_type,
            score_type=score_type,
            source=source,
            lookback_days=lookback_days,
        )
