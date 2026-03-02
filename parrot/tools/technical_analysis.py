"""
Technical Analysis Tool
"""
from dataclasses import dataclass
from typing import Dict, Any, List, Literal, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

# Local Imports
from navconfig.logging import logging
from .toolkit import AbstractToolkit
from .alpaca import AlpacaMarketsToolkit
from .coingecko import CoingeckoToolkit
from .cryptoquant import CryptoQuantToolkit


# =============================================================================
# Data Models for Technical Analysis Improvements (FEAT-016)
# =============================================================================


@dataclass
class TechnicalSignal:
    """
    Structured technical signal with confidence scoring.

    Used by the signal generation engine to produce actionable signals
    with direction, strength, and confidence assessments.
    """
    indicator: str
    """Indicator that generated the signal: RSI, MACD, SMA, ADX, BB, Volume"""

    signal_type: str
    """Type of signal: overbought, golden_cross, bullish_crossover, etc."""

    direction: Literal["bullish", "bearish", "neutral"]
    """Direction of the signal"""

    strength: Literal["strong", "moderate", "weak"]
    """Strength classification of the signal"""

    confidence: float
    """Confidence score from 0.0 to 1.0"""

    value: Optional[float]
    """The indicator value that triggered the signal"""

    description: str
    """Human-readable explanation of the signal"""


class ADXOutput(BaseModel):
    """
    ADX (Average Directional Index) indicator output.

    ADX measures trend strength regardless of direction.
    - ADX < 20: absent (no trend)
    - ADX 20-25: weak trend
    - ADX 25-50: strong trend
    - ADX > 50: extreme trend

    +DI > -DI indicates bullish direction; -DI > +DI indicates bearish.
    """
    value: float = Field(..., description="ADX value (0-100 scale)")
    plus_di: float = Field(..., description="Positive directional indicator (+DI)")
    minus_di: float = Field(..., description="Negative directional indicator (-DI)")
    trend_strength: Literal["absent", "weak", "strong", "extreme"] = Field(
        ...,
        description="Trend strength classification: absent(<20), weak(20-25), strong(25-50), extreme(>50)"
    )
    trend_direction: Literal["bullish", "bearish", "undefined"] = Field(
        ...,
        description="Trend direction: bullish (+DI > -DI), bearish (-DI > +DI), undefined (ADX < 20)"
    )


class ATROutput(BaseModel):
    """
    ATR (Average True Range) indicator output with stop-loss levels.

    ATR measures volatility in price terms. Used for:
    - Volatility-adjusted stop-loss placement
    - Position sizing
    - Risk management

    Stop-loss levels are provided for both long and short positions.
    """
    value: float = Field(..., description="Absolute ATR value in price units")
    percent: float = Field(..., description="ATR as percentage of current price")
    period: int = Field(default=14, description="ATR calculation period")
    stop_loss_long: Dict[str, float] = Field(
        ...,
        description="Stop-loss levels for long positions (below price): tight_1x, standard_2x, wide_3x"
    )
    stop_loss_short: Dict[str, float] = Field(
        ...,
        description="Stop-loss levels for short positions (above price): tight_1x, standard_2x, wide_3x"
    )


class CompositeScore(BaseModel):
    """
    Composite technical score for asset ranking.

    Provides a 0-10 bullish/bearish score combining multiple indicators:
    - SMA Position (0-2 pts)
    - RSI Zone (0-1 pt)
    - MACD (0-1.5 pts)
    - ADX Trend (0-1.5 pts)
    - Momentum (0-2 pts)
    - Volume (0-1 pt)
    - EMA Alignment (0-1 pt)
    """
    symbol: str = Field(..., description="Asset symbol")
    score: float = Field(..., ge=0, le=10, description="Composite score (0-10)")
    max_score: float = Field(default=10.0, description="Maximum possible score")
    label: Literal[
        "strong_bullish",
        "moderate_bullish",
        "neutral",
        "moderate_bearish",
        "strong_bearish"
    ] = Field(..., description="Score classification label")
    components: Dict[str, Any] = Field(
        ...,
        description="Breakdown of score components with individual scores and max values"
    )
    signals: List[Any] = Field(
        default_factory=list,
        description="List of TechnicalSignal objects that contributed to the score"
    )
    recommendation_hint: str = Field(
        ...,
        description="Action hint: trending_entry, pullback_buy, wait, avoid, etc."
    )


# =============================================================================
# Tool Input Schema
# =============================================================================


class TechnicalAnalysisInput(BaseModel):
    symbol: str = Field(..., description="Symbol to analyze (e.g., 'AAPL', 'bitcoin').")
    asset_type: str = Field(..., description="Type of asset: 'stock' or 'crypto'.")
    source: str = Field('alpaca', description="Source for data: 'alpaca', 'coingecko', 'cryptoquant'.")
    interval: str = Field('1d', description="Time interval: '1d', '1h'. Default '1d'.")
    lookback_days: int = Field(365, description="Days of historical data to fetch for calculation. Default 365.")


class TechnicalAnalysisTool(AbstractToolkit):
    """
    Tool for performing Technical Analysis on stocks and crypto.
    Calculates SMA, RSI, MACD, Bollinger Bands from OHLCV data fetched via other toolkits.
    """
    name = "technical_analysis"
    description = "Calculates technical indicators (SMA, RSI, MACD, BBands) for stocks and crypto."
    args_schema = TechnicalAnalysisInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        # Initialize sub-toolkits
        # Note: We initialize them with default config credentials
        self.alpaca = AlpacaMarketsToolkit()
        self.coingecko = CoingeckoToolkit()
        self.cryptoquant = CryptoQuantToolkit()

    def _calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _calculate_macd(self, series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        exp1 = series.ewm(span=fast, adjust=False).mean()
        exp2 = series.ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        return macd, signal_line

    def _calculate_bollinger_bands(self, series: pd.Series, window: int = 20, num_std: int = 2):
        sma = series.rolling(window=window).mean()
        std = series.rolling(window=window).std()
        upper = sma + (std * num_std)
        lower = sma - (std * num_std)
        return upper, lower, sma

    def _calculate_ema(self, series: pd.Series, span: int) -> pd.Series:
        """
        Calculate Exponential Moving Average.

        EMA reacts faster to recent price changes than SMA, making it
        the industry standard for trend-following strategies.

        Uses the standard recursive EMA formula:
        EMA_t = alpha * price_t + (1 - alpha) * EMA_{t-1}
        where alpha = 2 / (span + 1)

        Args:
            series: Price series (typically close prices)
            span: EMA period (e.g., 12, 26)

        Returns:
            EMA series with same length as input
        """
        return series.ewm(span=span, adjust=False).mean()

    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> ADXOutput | None:
        """
        Calculate ADX (Average Directional Index) with +DI and -DI.

        ADX measures trend strength regardless of direction:
        - ADX < 20: absent (no trend)
        - ADX 20-25: weak trend
        - ADX 25-50: strong trend
        - ADX > 50: extreme trend

        +DI > -DI indicates bullish direction; -DI > +DI indicates bearish.

        Args:
            df: DataFrame with 'high', 'low', 'close' columns
            period: Smoothing period (default 14)

        Returns:
            ADXOutput model or None if insufficient data
        """
        # Check required columns
        if not all(col in df.columns for col in ['high', 'low', 'close']):
            self.logger.warning("ADX requires high, low, close columns")
            return None

        # Ensure we have enough data
        if len(df) < period * 2:
            self.logger.warning(f"ADX requires at least {period * 2} data points, got {len(df)}")
            return None

        # Calculate True Range
        high = df['high']
        low = df['low']
        close = df['close']

        tr = np.maximum(
            high - low,
            np.maximum(
                np.abs(high - close.shift(1)),
                np.abs(low - close.shift(1))
            )
        )

        # Calculate Directional Movement
        delta_high = high.diff()
        delta_low = -low.diff()

        plus_dm = np.where((delta_high > delta_low) & (delta_high > 0), delta_high, 0)
        minus_dm = np.where((delta_low > delta_high) & (delta_low > 0), delta_low, 0)

        # Wilder's smoothing (EMA with alpha=1/period)
        alpha = 1 / period
        atr = pd.Series(tr).ewm(alpha=alpha, min_periods=period, adjust=False).mean()

        plus_di = 100 * pd.Series(plus_dm).ewm(alpha=alpha, min_periods=period, adjust=False).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).ewm(alpha=alpha, min_periods=period, adjust=False).mean() / atr

        # Calculate DX and ADX
        di_sum = plus_di + minus_di
        # Avoid division by zero
        di_sum = di_sum.replace(0, np.nan)
        dx = 100 * np.abs(plus_di - minus_di) / di_sum
        adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

        # Get latest values
        adx_value = float(adx.iloc[-1])
        plus_di_value = float(plus_di.iloc[-1])
        minus_di_value = float(minus_di.iloc[-1])

        # Handle NaN values
        if np.isnan(adx_value) or np.isnan(plus_di_value) or np.isnan(minus_di_value):
            self.logger.warning("ADX calculation resulted in NaN values")
            return None

        # Classify trend strength
        if adx_value < 20:
            trend_strength = "absent"
        elif adx_value < 25:
            trend_strength = "weak"
        elif adx_value < 50:
            trend_strength = "strong"
        else:
            trend_strength = "extreme"

        # Classify trend direction
        if adx_value < 20:
            trend_direction = "undefined"
        elif plus_di_value > minus_di_value:
            trend_direction = "bullish"
        else:
            trend_direction = "bearish"

        return ADXOutput(
            value=round(adx_value, 2),
            plus_di=round(plus_di_value, 2),
            minus_di=round(minus_di_value, 2),
            trend_strength=trend_strength,
            trend_direction=trend_direction
        )

    def _calculate_atr(
        self,
        df: pd.DataFrame,
        period: int = 14,
        current_price: float | None = None
    ) -> ATROutput | None:
        """
        Calculate ATR (Average True Range) with stop-loss levels.

        ATR measures volatility in price terms. It's used for:
        - Volatility-adjusted stop-loss placement
        - Position sizing based on risk
        - Understanding normal price movement range

        Args:
            df: DataFrame with 'high', 'low', 'close' columns
            period: Smoothing period (default 14)
            current_price: Price for stop-loss calculation (defaults to last close)

        Returns:
            ATROutput model or None if insufficient data
        """
        # Check required columns
        if not all(col in df.columns for col in ['high', 'low', 'close']):
            self.logger.warning("ATR requires high, low, close columns")
            return None

        # Ensure we have enough data
        if len(df) < period:
            self.logger.warning(f"ATR requires at least {period} data points, got {len(df)}")
            return None

        # Calculate True Range
        high = df['high']
        low = df['low']
        close = df['close']

        tr = np.maximum(
            high - low,
            np.maximum(
                np.abs(high - close.shift(1)),
                np.abs(low - close.shift(1))
            )
        )

        # Wilder's smoothing (EMA with alpha=1/period)
        alpha = 1 / period
        atr_series = pd.Series(tr).ewm(alpha=alpha, min_periods=period, adjust=False).mean()

        atr_value = float(atr_series.iloc[-1])

        # Handle NaN values
        if np.isnan(atr_value):
            self.logger.warning("ATR calculation resulted in NaN value")
            return None

        # Use provided price or last close
        if current_price is None:
            current_price = float(close.iloc[-1])

        # Handle edge case of zero price
        if current_price <= 0:
            self.logger.warning("ATR: current_price must be positive")
            return None

        # Calculate ATR as percentage of price
        atr_percent = (atr_value / current_price) * 100

        # Calculate stop-loss levels for LONG positions (below current price)
        stop_loss_long = {
            "tight_1x": round(current_price - atr_value, 2),
            "standard_2x": round(current_price - 2 * atr_value, 2),
            "wide_3x": round(current_price - 3 * atr_value, 2),
        }

        # Calculate stop-loss levels for SHORT positions (above current price)
        stop_loss_short = {
            "tight_1x": round(current_price + atr_value, 2),
            "standard_2x": round(current_price + 2 * atr_value, 2),
            "wide_3x": round(current_price + 3 * atr_value, 2),
        }

        return ATROutput(
            value=round(atr_value, 4),
            percent=round(atr_percent, 2),
            period=period,
            stop_loss_long=stop_loss_long,
            stop_loss_short=stop_loss_short
        )

    def _generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        adx_output: ADXOutput | None = None
    ) -> List[TechnicalSignal]:
        """
        Generate structured signals from indicator values.

        Analyzes computed indicators and generates TechnicalSignal objects
        with direction, strength, and confidence assessments.

        Args:
            df: DataFrame with price and indicator columns
            indicators: Dict of computed indicator values
            adx_output: ADXOutput if ADX was computed

        Returns:
            List of TechnicalSignal objects
        """
        signals: List[TechnicalSignal] = []

        # Get current and previous prices for crossover detection
        if len(df) < 2:
            return signals

        price = float(df['close'].iloc[-1])
        prev_price = float(df['close'].iloc[-2])

        # ===== TREND SIGNALS (SMA) =====
        sma_200 = indicators.get('SMA_200')
        sma_50 = indicators.get('SMA_50')

        if sma_200 is not None:
            if price > sma_200:
                signals.append(TechnicalSignal(
                    indicator="SMA",
                    signal_type="above_long_trend",
                    direction="bullish",
                    strength="moderate",
                    confidence=0.5,
                    value=sma_200,
                    description=f"Price ${price:.2f} above SMA200 ${sma_200:.2f}"
                ))
            else:
                signals.append(TechnicalSignal(
                    indicator="SMA",
                    signal_type="below_long_trend",
                    direction="bearish",
                    strength="moderate",
                    confidence=0.5,
                    value=sma_200,
                    description=f"Price ${price:.2f} below SMA200 ${sma_200:.2f}"
                ))

        # Golden/Death Cross (SMA20 crosses SMA50)
        sma_20 = indicators.get('SMA_20')
        sma_20_prev = indicators.get('SMA_20_prev')
        sma_50_prev = indicators.get('SMA_50_prev')

        if all(v is not None for v in [sma_20, sma_50, sma_20_prev, sma_50_prev]):
            # Golden cross: SMA20 crosses above SMA50
            if sma_20_prev <= sma_50_prev and sma_20 > sma_50:
                signals.append(TechnicalSignal(
                    indicator="SMA",
                    signal_type="golden_cross",
                    direction="bullish",
                    strength="strong",
                    confidence=0.7,
                    value=sma_20,
                    description="Golden cross: SMA20 crossed above SMA50"
                ))
            # Death cross: SMA20 crosses below SMA50
            elif sma_20_prev >= sma_50_prev and sma_20 < sma_50:
                signals.append(TechnicalSignal(
                    indicator="SMA",
                    signal_type="death_cross",
                    direction="bearish",
                    strength="strong",
                    confidence=0.7,
                    value=sma_20,
                    description="Death cross: SMA20 crossed below SMA50"
                ))

        # ===== EMA ALIGNMENT =====
        ema_12 = indicators.get('EMA_12')
        ema_26 = indicators.get('EMA_26')

        if ema_12 is not None and ema_26 is not None:
            if ema_12 > ema_26:
                signals.append(TechnicalSignal(
                    indicator="EMA",
                    signal_type="ema_bullish_alignment",
                    direction="bullish",
                    strength="moderate",
                    confidence=0.5,
                    value=ema_12,
                    description=f"EMA12 ${ema_12:.2f} above EMA26 ${ema_26:.2f}"
                ))
            else:
                signals.append(TechnicalSignal(
                    indicator="EMA",
                    signal_type="ema_bearish_alignment",
                    direction="bearish",
                    strength="moderate",
                    confidence=0.5,
                    value=ema_12,
                    description=f"EMA12 ${ema_12:.2f} below EMA26 ${ema_26:.2f}"
                ))

        # ===== ADX TREND STRENGTH =====
        if adx_output:
            if adx_output.value >= 25:
                if adx_output.trend_direction == "bullish":
                    signals.append(TechnicalSignal(
                        indicator="ADX",
                        signal_type="strong_bullish_trend",
                        direction="bullish",
                        strength="strong",
                        confidence=0.7,
                        value=adx_output.value,
                        description=f"ADX {adx_output.value:.1f} with +DI > -DI confirms strong bullish trend"
                    ))
                elif adx_output.trend_direction == "bearish":
                    signals.append(TechnicalSignal(
                        indicator="ADX",
                        signal_type="strong_bearish_trend",
                        direction="bearish",
                        strength="strong",
                        confidence=0.7,
                        value=adx_output.value,
                        description=f"ADX {adx_output.value:.1f} with -DI > +DI confirms strong bearish trend"
                    ))
            elif adx_output.value < 20:
                signals.append(TechnicalSignal(
                    indicator="ADX",
                    signal_type="trendless_market",
                    direction="neutral",
                    strength="weak",
                    confidence=0.3,
                    value=adx_output.value,
                    description=f"ADX {adx_output.value:.1f} indicates trendless/ranging market"
                ))

        # ===== RSI SIGNALS =====
        rsi = indicators.get('RSI_14')
        if rsi is not None:
            if rsi > 70:
                signals.append(TechnicalSignal(
                    indicator="RSI",
                    signal_type="overbought",
                    direction="bearish",
                    strength="moderate",
                    confidence=0.5,
                    value=rsi,
                    description=f"RSI {rsi:.1f} indicates overbought conditions"
                ))
            elif rsi < 30:
                signals.append(TechnicalSignal(
                    indicator="RSI",
                    signal_type="oversold",
                    direction="bullish",
                    strength="moderate",
                    confidence=0.5,
                    value=rsi,
                    description=f"RSI {rsi:.1f} indicates oversold conditions"
                ))
            elif 50 <= rsi <= 70:
                signals.append(TechnicalSignal(
                    indicator="RSI",
                    signal_type="bullish_momentum",
                    direction="bullish",
                    strength="weak",
                    confidence=0.3,
                    value=rsi,
                    description=f"RSI {rsi:.1f} shows bullish momentum"
                ))
            elif 30 <= rsi < 50:
                signals.append(TechnicalSignal(
                    indicator="RSI",
                    signal_type="bearish_momentum",
                    direction="bearish",
                    strength="weak",
                    confidence=0.3,
                    value=rsi,
                    description=f"RSI {rsi:.1f} shows bearish momentum"
                ))

        # ===== MACD SIGNALS =====
        macd_data = indicators.get('MACD')
        if isinstance(macd_data, dict):
            hist = macd_data.get('hist')
            hist_prev = macd_data.get('hist_prev')

            if hist is not None and hist_prev is not None:
                # MACD histogram crosses above 0
                if hist_prev <= 0 < hist:
                    signals.append(TechnicalSignal(
                        indicator="MACD",
                        signal_type="macd_bullish_crossover",
                        direction="bullish",
                        strength="strong",
                        confidence=0.7,
                        value=hist,
                        description="MACD histogram crossed above zero"
                    ))
                # MACD histogram crosses below 0
                elif hist_prev >= 0 > hist:
                    signals.append(TechnicalSignal(
                        indicator="MACD",
                        signal_type="macd_bearish_crossover",
                        direction="bearish",
                        strength="strong",
                        confidence=0.7,
                        value=hist,
                        description="MACD histogram crossed below zero"
                    ))

        # ===== BOLLINGER BANDS =====
        bb_upper = indicators.get('BB_Upper')
        bb_lower = indicators.get('BB_Lower')

        if bb_lower is not None and price < bb_lower:
            signals.append(TechnicalSignal(
                indicator="BB",
                signal_type="bb_oversold",
                direction="bullish",
                strength="moderate",
                confidence=0.5,
                value=bb_lower,
                description=f"Price ${price:.2f} below lower Bollinger Band ${bb_lower:.2f}"
            ))
        elif bb_upper is not None and price > bb_upper:
            signals.append(TechnicalSignal(
                indicator="BB",
                signal_type="bb_overbought",
                direction="bearish",
                strength="moderate",
                confidence=0.5,
                value=bb_upper,
                description=f"Price ${price:.2f} above upper Bollinger Band ${bb_upper:.2f}"
            ))

        # ===== VOLUME SIGNALS =====
        volume = indicators.get('volume')
        avg_volume = indicators.get('Avg_Volume_20d')

        if volume is not None and avg_volume is not None and avg_volume > 0:
            volume_ratio = volume / avg_volume

            if volume_ratio > 2.0:
                # High volume with direction
                price_change = price - prev_price
                if price_change > 0:
                    signals.append(TechnicalSignal(
                        indicator="Volume",
                        signal_type="volume_breakout_bullish",
                        direction="bullish",
                        strength="strong",
                        confidence=0.7,
                        value=volume_ratio,
                        description=f"Volume breakout: {volume_ratio:.1f}x average with price up"
                    ))
                else:
                    signals.append(TechnicalSignal(
                        indicator="Volume",
                        signal_type="volume_breakdown_bearish",
                        direction="bearish",
                        strength="strong",
                        confidence=0.7,
                        value=volume_ratio,
                        description=f"Volume breakdown: {volume_ratio:.1f}x average with price down"
                    ))
            elif volume_ratio > 1.5:
                signals.append(TechnicalSignal(
                    indicator="Volume",
                    signal_type="high_volume",
                    direction="neutral",
                    strength="moderate",
                    confidence=0.5,
                    value=volume_ratio,
                    description=f"High volume: {volume_ratio:.1f}x average"
                ))

        # Adjust confidence based on cross-signal confirmation
        signals = self._adjust_signal_confidence(signals)

        return signals

    def _calculate_signal_confidence(
        self,
        signal: TechnicalSignal,
        all_signals: List[TechnicalSignal]
    ) -> float:
        """
        Calculate adjusted confidence based on confirming/conflicting signals.

        Base confidence: strong=0.7, moderate=0.5, weak=0.3

        Modifiers:
        - Each confirming signal in same direction: +0.05 (max +0.20)
        - Each conflicting signal: -0.10 (min -0.20)
        - ADX > 25 in same direction: +0.10 (trend confirmation)
        - Volume confirmation: +0.10

        Final confidence clamped to [0.1, 0.95]
        """
        # Base confidence from strength
        base_confidence = {"strong": 0.7, "moderate": 0.5, "weak": 0.3}
        base = base_confidence.get(signal.strength, 0.5)

        confirming = 0
        conflicting = 0

        for other in all_signals:
            if other is signal:
                continue
            # Count confirming signals (same direction, neither neutral)
            if other.direction == signal.direction and other.direction != "neutral":
                confirming += 1
            # Count conflicting signals (opposite direction, neither neutral)
            elif other.direction != "neutral" and signal.direction != "neutral":
                if other.direction != signal.direction:
                    conflicting += 1

        # Apply base modifiers
        adjustment = min(confirming * 0.05, 0.20) - min(conflicting * 0.10, 0.20)

        # ADX confirmation bonus
        adx_signals = [s for s in all_signals if s.indicator == "ADX" and "strong" in s.signal_type]
        if adx_signals and adx_signals[0].direction == signal.direction:
            adjustment += 0.10

        # Volume confirmation bonus
        vol_signals = [s for s in all_signals if s.indicator == "Volume" and "breakout" in s.signal_type.lower()]
        if vol_signals and vol_signals[0].direction == signal.direction:
            adjustment += 0.10

        # Clamp to valid range
        return max(0.1, min(0.95, base + adjustment))

    def _adjust_signal_confidence(
        self,
        signals: List[TechnicalSignal]
    ) -> List[TechnicalSignal]:
        """
        Adjust confidence of all signals based on cross-signal confirmation.

        Returns new list with updated confidence values.
        """
        adjusted_signals = []
        for signal in signals:
            new_confidence = self._calculate_signal_confidence(signal, signals)
            adjusted_signals.append(TechnicalSignal(
                indicator=signal.indicator,
                signal_type=signal.signal_type,
                direction=signal.direction,
                strength=signal.strength,
                confidence=round(new_confidence, 2),
                value=signal.value,
                description=signal.description
            ))
        return adjusted_signals

    async def _execute(
        self,
        symbol: str,
        asset_type: str,
        source: str = 'alpaca',
        interval: str = '1d',
        lookback_days: int = 365,
        legacy_format: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute the technical analysis.

        Args:
            symbol: Asset symbol (e.g., 'AAPL', 'bitcoin')
            asset_type: 'stock' or 'crypto'
            source: Data source ('alpaca', 'coingecko', 'cryptoquant')
            interval: Time interval ('1d', '1h', '15m')
            lookback_days: Historical data period
            legacy_format: If True, return old flat structure for backward compatibility

        Returns:
            Dict with technical analysis results in either new nested or legacy format
        """
        df = pd.DataFrame()

        try:
            # 1. Fetch Data
            if asset_type == 'stock':
                if source != 'alpaca':
                    # Fallback or error? For stocks, only Alpaca is supported currently.
                    source = 'alpaca'
                
                end_dt = datetime.now()
                start_dt = end_dt - timedelta(days=lookback_days)
                
                # Check Alpaca timeframes
                tf = "1Day"
                if interval in ['1h', '1Hour']:
                    tf = "1Hour"
                elif interval in ['15m', '15Min']:
                    tf = "15Min"
                
                data = await self.alpaca.get_stock_bars(
                    symbol=symbol, 
                    timeframe=tf, 
                    start=start_dt.strftime('%Y-%m-%d'),
                    end=end_dt.strftime('%Y-%m-%d'),
                    limit=1000
                )
                
                if 'bars' in data and data['bars']:
                    # Alpaca returns list of dicts: [{'t': '...', 'o': ..., 'c': ...}] unless it was normalized by wrapper
                    # The wrapper I checked returns: "bars": data (list of records)
                    # Keys: timestamp, open, high, low, close, volume, trade_count, vwap
                    df = pd.DataFrame(data['bars'])
                    # Rename columns if needed, but wrapper seems to use lower case full names
                    # Make sure 'close' exists
                    if 'close' not in df.columns and 'c' in df.columns:
                        df.rename(columns={'c': 'close', 'o': 'open', 'h': 'high', 'l': 'low', 'v': 'volume', 't': 'timestamp'}, inplace=True)

            elif asset_type == 'crypto':
                if source == 'coingecko':
                    # Coingecko doesn't support 'interval' freely. 
                    # days=1/7/14/30 etc determines granularity.
                    # 1 day = 5 min interval, 7-14 days = hourly, >30 days = daily.
                    # We want 'daily' usually for SMA50/200.
                    days_param = str(lookback_days)
                    if lookback_days > 30:
                        # Ensures daily resolution
                        pass 
                    else:
                        # If user wants hourly, we might get 5-min data if days=1.
                        # Simple rule: if lookback > 30, it is daily.
                        pass

                    ohlc = await self.coingecko.cg_coins_ohlc(
                        coin_id=symbol, # User must pass coin_id (e.g. bitcoin) not ticker (BTC)
                        vs_currency='usd',
                        days=days_param
                    )
                    # result is list of [time, o, h, l, c]
                    df = pd.DataFrame(ohlc, columns=['timestamp', 'open', 'high', 'low', 'close'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

                elif source == 'cryptoquant':
                    # cq_price_ohlcv returns Dict.
                    # Example assumption: { "result": { "data": [...] } }
                    data = await self.cryptoquant.cq_price_ohlcv(
                        token=symbol,
                        window='day', # Fixed to day for now or map interval
                        limit=lookback_days
                    )
                    # TODO: Parse data structure based on actual API response
                    # For now, return error if not mocked/known
                    # Assuming data is in data['result']['data'] or similar
                    if 'result' in data and 'data' in data['result']:
                         df = pd.DataFrame(data['result']['data'])
                    else:
                         return {"error": f"Unknown CryptoQuant response format: {data.keys()}"}

            if df.empty:
                return {"error": f"No data found for {symbol} from {source}"}

            # 2. Prepare DataFrame
            # Ensure 'close' is numeric
            for col in ['open', 'high', 'low', 'close']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            if 'volume' in df.columns:
                df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

            # Sort by date
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.sort_values('timestamp', inplace=True)

            # 3. Calculate Indicators
            # SMA (20, 50, 200)
            df['SMA_20'] = df['close'].rolling(window=20).mean()
            df['SMA_50'] = df['close'].rolling(window=50).mean()
            df['SMA_200'] = df['close'].rolling(window=200).mean()

            # EMA (12, 26)
            df['EMA_12'] = self._calculate_ema(df['close'], 12)
            df['EMA_26'] = self._calculate_ema(df['close'], 26)

            # RSI (Wilder's Smoothing)
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
            rs = avg_gain / avg_loss
            df['RSI_14'] = 100 - (100 / (1 + rs))

            # MACD (12, 26, 9)
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = exp1 - exp2
            df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
            df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

            # Bollinger Bands (20, 2)
            sma20 = df['close'].rolling(window=20).mean()
            std20 = df['close'].rolling(window=20).std()
            df['BB_Upper'] = sma20 + (std20 * 2)
            df['BB_Lower'] = sma20 - (std20 * 2)
            df['BB_Mid'] = sma20

            # Volume average
            if 'volume' in df.columns:
                df['Vol_Avg_20'] = df['volume'].rolling(window=20).mean()

            # ADX (new indicator)
            adx_output = None
            if 'high' in df.columns and 'low' in df.columns and len(df) >= 28:
                adx_output = self._calculate_adx(df)

            # ATR (new indicator)
            atr_output = None
            if 'high' in df.columns and 'low' in df.columns and len(df) >= 15:
                atr_output = self._calculate_atr(df)

            # 4. Build indicators dict for signal generation
            last = df.iloc[-1]
            indicators_dict = {
                "SMA_20": self._safe_float(last.get('SMA_20')),
                "SMA_50": self._safe_float(last.get('SMA_50')),
                "SMA_200": self._safe_float(last.get('SMA_200')),
                "EMA_12": self._safe_float(last.get('EMA_12')),
                "EMA_26": self._safe_float(last.get('EMA_26')),
                "RSI_14": self._safe_float(last.get('RSI_14')),
                "MACD": {
                    "value": self._safe_float(last.get('MACD')),
                    "signal": self._safe_float(last.get('MACD_Signal')),
                    "hist": self._safe_float(last.get('MACD_Hist')),
                },
                "BBands": {
                    "upper": self._safe_float(last.get('BB_Upper')),
                    "lower": self._safe_float(last.get('BB_Lower')),
                    "mid": self._safe_float(last.get('BB_Mid')),
                },
                "Avg_Volume_20d": self._safe_float(last.get('Vol_Avg_20')),
            }

            # Generate signals using the signal engine
            signals = self._generate_signals(df, indicators_dict, adx_output)

            # Route to appropriate output format
            if legacy_format:
                return self._build_legacy_output(
                    symbol=symbol,
                    df=df,
                    indicators=indicators_dict,
                    signals=signals,
                )

            return self._build_structured_output(
                symbol=symbol,
                asset_type=asset_type,
                df=df,
                adx_output=adx_output,
                atr_output=atr_output,
                signals=signals,
            )

        except Exception as e:
            self.logger.error(f"Error in TechnicalAnalysisTool: {e}")
            raise e

    # =========================================================================
    # Output Formatting Methods
    # =========================================================================

    def _safe_float(self, value, decimals: int = 2) -> float | None:
        """
        Safely convert value to float, handling NaN.

        Args:
            value: Value to convert
            decimals: Number of decimal places to round to

        Returns:
            Float value or None if NaN/invalid
        """
        if value is None:
            return None
        if pd.isna(value):
            return None
        try:
            return round(float(value), decimals)
        except (TypeError, ValueError):
            return None

    def _get_rsi_zone(self, rsi: float | None) -> str | None:
        """
        Determine RSI zone classification.

        Args:
            rsi: RSI value

        Returns:
            Zone string: 'overbought', 'bullish', 'neutral', 'bearish', 'oversold', or None
        """
        if rsi is None or pd.isna(rsi):
            return None
        if rsi >= 70:
            return "overbought"
        elif rsi >= 50:
            return "bullish"
        elif rsi >= 30:
            return "bearish"
        else:
            return "oversold"

    def _calculate_bb_bandwidth(self, row: pd.Series) -> float | None:
        """
        Calculate Bollinger Bands bandwidth percentage.

        Bandwidth = (Upper - Lower) / Middle * 100

        Args:
            row: DataFrame row with BB_Upper, BB_Lower, BB_Mid

        Returns:
            Bandwidth percentage or None
        """
        upper = row.get('BB_Upper')
        lower = row.get('BB_Lower')
        mid = row.get('BB_Mid')

        if any(pd.isna(v) for v in [upper, lower, mid]) or mid == 0:
            return None

        return round((float(upper) - float(lower)) / float(mid) * 100, 2)

    def _get_bb_position(self, row: pd.Series) -> str | None:
        """
        Determine price position within Bollinger Bands.

        Args:
            row: DataFrame row with close, BB_Upper, BB_Lower, BB_Mid

        Returns:
            Position string: 'above_upper', 'upper_half', 'mid', 'lower_half', 'below_lower', or None
        """
        close = row.get('close')
        upper = row.get('BB_Upper')
        lower = row.get('BB_Lower')
        mid = row.get('BB_Mid')

        if any(pd.isna(v) for v in [close, upper, lower, mid]):
            return None

        close, upper, lower, mid = float(close), float(upper), float(lower), float(mid)

        if close > upper:
            return "above_upper"
        elif close > mid:
            return "upper_half"
        elif close > lower:
            return "lower_half"
        else:
            return "below_lower"

    def _calculate_annualized_vol(self, df: pd.DataFrame, period: int = 20) -> float | None:
        """
        Calculate annualized volatility from daily returns.

        Args:
            df: DataFrame with 'close' column
            period: Lookback period for volatility calculation

        Returns:
            Annualized volatility percentage or None
        """
        if len(df) < period + 1:
            return None

        returns = df['close'].pct_change().dropna()
        if len(returns) < period:
            return None

        daily_vol = returns.tail(period).std()
        if pd.isna(daily_vol):
            return None

        # Annualize: daily_vol * sqrt(252 trading days)
        annualized = daily_vol * np.sqrt(252) * 100
        return round(annualized, 2)

    def _build_structured_output(
        self,
        symbol: str,
        asset_type: str,
        df: pd.DataFrame,
        adx_output: "ADXOutput | None",
        atr_output: "ATROutput | None",
        signals: List[TechnicalSignal],
    ) -> Dict[str, Any]:
        """
        Build the new nested output structure.

        Args:
            symbol: Asset symbol
            asset_type: Asset type ('stock' or 'crypto')
            df: DataFrame with calculated indicators
            adx_output: ADX calculation result
            atr_output: ATR calculation result
            signals: List of TechnicalSignal objects

        Returns:
            Nested output dict with grouped indicators
        """
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        current_price = self._safe_float(last.get('close'))
        if current_price is None:
            current_price = 0.0

        prev_close = self._safe_float(prev.get('close'))
        if prev_close and prev_close != 0:
            price_change = current_price - prev_close
            price_change_pct = (price_change / prev_close) * 100
        else:
            price_change = 0.0
            price_change_pct = 0.0

        # Build trend indicators
        trend_indicators = {
            "sma_20": self._safe_float(last.get('SMA_20')),
            "sma_50": self._safe_float(last.get('SMA_50')),
            "sma_200": self._safe_float(last.get('SMA_200')),
            "ema_12": self._safe_float(last.get('EMA_12')),
            "ema_26": self._safe_float(last.get('EMA_26')),
            "adx": adx_output.model_dump() if adx_output else None,
        }

        # Build momentum indicators
        rsi_val = self._safe_float(last.get('RSI_14'))
        prev_hist = self._safe_float(prev.get('MACD_Hist'))
        curr_hist = self._safe_float(last.get('MACD_Hist'))

        momentum_indicators = {
            "rsi_14": {
                "value": rsi_val,
                "zone": self._get_rsi_zone(last.get('RSI_14')),
            },
            "macd": {
                "line": self._safe_float(last.get('MACD')),
                "signal": self._safe_float(last.get('MACD_Signal')),
                "histogram": curr_hist,
                "prev_histogram": prev_hist,
                "histogram_rising": (
                    curr_hist > prev_hist
                    if curr_hist is not None and prev_hist is not None
                    else None
                ),
            },
        }

        # Build volatility indicators
        volatility_indicators = {
            "bollinger": {
                "upper": self._safe_float(last.get('BB_Upper')),
                "middle": self._safe_float(last.get('BB_Mid')),
                "lower": self._safe_float(last.get('BB_Lower')),
                "bandwidth_pct": self._calculate_bb_bandwidth(last),
                "price_position": self._get_bb_position(last),
            },
            "atr": {
                "value": atr_output.value if atr_output else None,
                "percent": atr_output.percent if atr_output else None,
                "stop_loss_long_2x": atr_output.stop_loss_long.get("standard_2x") if atr_output else None,
                "stop_loss_short_2x": atr_output.stop_loss_short.get("standard_2x") if atr_output else None,
            } if atr_output else None,
        }

        # Build volume indicators
        current_vol = self._safe_float(last.get('volume'), decimals=0)
        avg_vol = self._safe_float(last.get('Vol_Avg_20'), decimals=0)

        volume_indicators = {
            "current": current_vol,
            "avg_20d": avg_vol,
            "ratio": (
                round(current_vol / avg_vol, 2)
                if current_vol is not None and avg_vol is not None and avg_vol > 0
                else None
            ),
            "is_high": (
                current_vol > avg_vol * 1.5
                if current_vol is not None and avg_vol is not None
                else False
            ),
        }

        # Build risk context
        risk_context = {
            "atr_stop_long_2x": atr_output.stop_loss_long.get("standard_2x") if atr_output else None,
            "atr_stop_short_2x": atr_output.stop_loss_short.get("standard_2x") if atr_output else None,
            "volatility_annualized_pct": self._calculate_annualized_vol(df),
        }

        # Serialize signals
        serialized_signals = []
        for s in signals:
            serialized_signals.append({
                "indicator": s.indicator,
                "signal_type": s.signal_type,
                "direction": s.direction,
                "strength": s.strength,
                "confidence": s.confidence,
                "value": s.value,
                "description": s.description,
            })

        return {
            "symbol": symbol,
            "asset_type": asset_type,
            "timestamp": str(last.get('timestamp', '')),
            "price": {
                "current": round(current_price, 2),
                "change_1d": round(price_change, 2),
                "change_1d_pct": round(price_change_pct, 2),
            },
            "indicators": {
                "trend": trend_indicators,
                "momentum": momentum_indicators,
                "volatility": volatility_indicators,
                "volume": volume_indicators,
            },
            "signals": serialized_signals,
            "risk_context": risk_context,
        }

    def _build_legacy_output(
        self,
        symbol: str,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        signals: List[TechnicalSignal],
    ) -> Dict[str, Any]:
        """
        Build the old flat output structure for backward compatibility.

        Args:
            symbol: Asset symbol
            df: DataFrame with calculated indicators
            indicators: Dict of indicator values
            signals: List of TechnicalSignal objects

        Returns:
            Legacy flat output dict
        """
        last = df.iloc[-1]

        # Convert TechnicalSignal objects to flat strings (old format)
        flat_signals = [s.description for s in signals]

        vol = None
        if 'volume' in df.columns and not pd.isna(last.get('volume')):
            vol = float(last['volume'])

        return {
            "symbol": symbol,
            "timestamp": str(last.get('timestamp', '')),
            "price": float(last['close']) if not pd.isna(last.get('close')) else 0,
            "indicators": {
                "SMA_50": indicators.get("SMA_50"),
                "SMA_200": indicators.get("SMA_200"),
                "RSI_14": indicators.get("RSI_14"),
                "MACD": indicators.get("MACD"),
                "BBands": indicators.get("BBands"),
                "Avg_Volume_20d": indicators.get("Avg_Volume_20d"),
            },
            "signals": flat_signals,
            "volume": vol,
        }

    # =========================================================================
    # Multi-Timeframe Analysis
    # =========================================================================

    async def multi_timeframe_analysis(
        self,
        symbol: str,
        ohlcv_daily: pd.DataFrame,
        ohlcv_weekly: pd.DataFrame | None = None,
        ohlcv_hourly: pd.DataFrame | None = None,
    ) -> Dict[str, Any]:
        """
        Compute indicators and scores on each available timeframe,
        then produce a consensus verdict.

        A signal is much stronger when confirmed across multiple timeframes.
        This method computes indicators on hourly, daily, and weekly data
        independently, then produces a consensus verdict with confidence
        adjustment.

        Args:
            symbol: Asset symbol
            ohlcv_daily: Daily OHLCV data (required)
            ohlcv_weekly: Weekly OHLCV data (optional)
            ohlcv_hourly: Hourly OHLCV data (optional)

        Returns:
            Dict with structure:
            {
                "symbol": str,
                "timeframes": {
                    "hourly": {"score": float, "bias": str, "signals": list},
                    "daily": {"score": float, "bias": str, "signals": list},
                    "weekly": {"score": float, "bias": str, "signals": list},
                },
                "consensus": {
                    "bias": str,
                    "confidence": float,
                    "alignment": str,
                    "recommendation": str,
                    "weighted_score": float,
                }
            }
        """
        if ohlcv_daily is None or ohlcv_daily.empty:
            return {
                "symbol": symbol,
                "error": "Daily OHLCV data is required",
                "timeframes": {},
                "consensus": {
                    "bias": "neutral",
                    "confidence": 0.1,
                    "alignment": "insufficient_data",
                    "recommendation": "wait_for_data",
                    "weighted_score": 5.0,
                }
            }

        results: Dict[str, Any] = {
            "symbol": symbol,
            "timeframes": {},
            "consensus": {}
        }

        # Analyze each available timeframe
        timeframes_data = [
            ("daily", ohlcv_daily),
            ("weekly", ohlcv_weekly),
            ("hourly", ohlcv_hourly),
        ]

        for tf_name, df in timeframes_data:
            if df is None or df.empty:
                continue

            # Compute indicators for this timeframe
            tf_result = self._analyze_single_timeframe(df.copy(), tf_name)
            results["timeframes"][tf_name] = tf_result

        # Compute consensus
        results["consensus"] = self._compute_consensus(results["timeframes"])

        return results

    def _analyze_single_timeframe(
        self,
        df: pd.DataFrame,
        timeframe: str
    ) -> Dict[str, Any]:
        """
        Analyze a single timeframe and return score + bias.

        Args:
            df: OHLCV DataFrame for this timeframe
            timeframe: Timeframe name ("hourly", "daily", "weekly")

        Returns:
            Dict with score, bias, signals, and indicators
        """
        # Ensure numeric columns
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        if 'volume' in df.columns:
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

        indicators: Dict[str, Any] = {}

        # Get current price
        price = float(df['close'].iloc[-1]) if len(df) > 0 else 0

        # SMA calculations
        if len(df) >= 50:
            df['SMA_50'] = df['close'].rolling(window=50).mean()
            indicators['SMA_50'] = float(df['SMA_50'].iloc[-1]) if not pd.isna(df['SMA_50'].iloc[-1]) else None
        else:
            indicators['SMA_50'] = None

        if len(df) >= 200:
            df['SMA_200'] = df['close'].rolling(window=200).mean()
            indicators['SMA_200'] = float(df['SMA_200'].iloc[-1]) if not pd.isna(df['SMA_200'].iloc[-1]) else None
        else:
            indicators['SMA_200'] = None

        # EMA calculations
        if len(df) >= 12:
            df['EMA_12'] = self._calculate_ema(df['close'], 12)
            indicators['EMA_12'] = float(df['EMA_12'].iloc[-1]) if not pd.isna(df['EMA_12'].iloc[-1]) else None
        else:
            indicators['EMA_12'] = None

        if len(df) >= 26:
            df['EMA_26'] = self._calculate_ema(df['close'], 26)
            indicators['EMA_26'] = float(df['EMA_26'].iloc[-1]) if not pd.isna(df['EMA_26'].iloc[-1]) else None
        else:
            indicators['EMA_26'] = None

        # RSI calculation
        if len(df) >= 15:
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)

            avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

            rs = avg_gain / avg_loss.replace(0, np.inf)
            df['RSI_14'] = 100 - (100 / (1 + rs))
            rsi_val = df['RSI_14'].iloc[-1]
            indicators['RSI_14'] = float(rsi_val) if not pd.isna(rsi_val) else None
        else:
            indicators['RSI_14'] = None

        # MACD calculation
        if len(df) >= 35:
            ema_12 = df['close'].ewm(span=12, adjust=False).mean()
            ema_26 = df['close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = ema_12 - ema_26
            df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
            df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

            indicators['MACD'] = {
                'value': float(df['MACD'].iloc[-1]) if not pd.isna(df['MACD'].iloc[-1]) else None,
                'signal': float(df['MACD_Signal'].iloc[-1]) if not pd.isna(df['MACD_Signal'].iloc[-1]) else None,
                'hist': float(df['MACD_Hist'].iloc[-1]) if not pd.isna(df['MACD_Hist'].iloc[-1]) else None,
            }
        else:
            indicators['MACD'] = {'value': None, 'signal': None, 'hist': None}

        # ADX calculation
        adx_output = None
        if 'high' in df.columns and 'low' in df.columns and len(df) >= 28:
            adx_output = self._calculate_adx(df)

        # ATR calculation
        atr_output = None
        if 'high' in df.columns and 'low' in df.columns and len(df) >= 15:
            atr_output = self._calculate_atr(df)
            if atr_output:
                indicators['ATR'] = atr_output.value

        # Volume average
        if 'volume' in df.columns and len(df) >= 20:
            df['Vol_Avg_20'] = df['volume'].rolling(window=20).mean()
            vol_avg = df['Vol_Avg_20'].iloc[-1]
            indicators['Avg_Volume_20d'] = float(vol_avg) if not pd.isna(vol_avg) else None
        else:
            indicators['Avg_Volume_20d'] = None

        # Generate signals using the signal engine
        signals = self._generate_signals(df, indicators, adx_output)

        # Determine bias from signals
        bullish_count = sum(1 for s in signals if s.direction == "bullish")
        bearish_count = sum(1 for s in signals if s.direction == "bearish")
        neutral_count = sum(1 for s in signals if s.direction == "neutral")

        if bullish_count > bearish_count + 2:
            bias = "bullish"
        elif bearish_count > bullish_count + 2:
            bias = "bearish"
        else:
            bias = "neutral"

        # Calculate simple score based on bullish signal ratio
        total_directional = bullish_count + bearish_count
        if total_directional > 0:
            score = (bullish_count / total_directional) * 10
        else:
            score = 5.0

        # Serialize signals for output
        serialized_signals = []
        for s in signals:
            serialized_signals.append({
                "indicator": s.indicator,
                "signal_type": s.signal_type,
                "direction": s.direction,
                "strength": s.strength,
                "confidence": s.confidence,
                "description": s.description,
            })

        return {
            "timeframe": timeframe,
            "price": price,
            "score": round(score, 1),
            "bias": bias,
            "signals": serialized_signals,
            "signal_counts": {
                "bullish": bullish_count,
                "bearish": bearish_count,
                "neutral": neutral_count,
            },
            "indicators": indicators,
        }

    def _compute_consensus(self, timeframes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compute consensus from multiple timeframe analyses.

        Confidence adjustment rules:
        - All timeframes agree → +0.15
        - Daily + weekly agree, hourly differs → -0.05
        - Daily + weekly differ → -0.15
        - All differ → -0.25

        Timeframe weights for consensus:
        - Daily: 0.5
        - Weekly: 0.35
        - Hourly: 0.15

        Args:
            timeframes: Dict of timeframe analysis results

        Returns:
            Consensus dict with bias, confidence, alignment, recommendation
        """
        if not timeframes:
            return {
                "bias": "neutral",
                "confidence": 0.1,
                "alignment": "insufficient_data",
                "recommendation": "wait_for_data",
                "weighted_score": 5.0,
            }

        biases = {tf: data["bias"] for tf, data in timeframes.items()}
        scores = {tf: data["score"] for tf, data in timeframes.items()}

        # Base confidence
        base_confidence = 0.5

        # Determine alignment and confidence adjustment
        # Check for single timeframe FIRST before checking unique biases
        if len(timeframes) == 1:
            # Only one timeframe available - needs confirmation from others
            alignment = "single_timeframe"
            confidence_adj = 0.0
        elif len(set(biases.values())) == 1:
            # All timeframes agree (2 or more)
            alignment = "full"
            confidence_adj = 0.15
        elif "daily" in biases and "weekly" in biases:
            if biases["daily"] == biases["weekly"]:
                # Daily and weekly agree, hourly may differ
                alignment = "partial"
                confidence_adj = -0.05
            else:
                # Daily and weekly disagree
                alignment = "conflicting"
                confidence_adj = -0.15
        else:
            # All differ or edge case
            alignment = "conflicting"
            confidence_adj = -0.25

        final_confidence = max(0.1, min(0.95, base_confidence + confidence_adj))

        # Consensus bias: weighted by timeframe importance
        weights = {"daily": 0.5, "weekly": 0.35, "hourly": 0.15}

        available_weight = sum(w for tf, w in weights.items() if tf in timeframes)
        if available_weight > 0:
            weighted_score = sum(
                scores.get(tf, 5.0) * w
                for tf, w in weights.items()
                if tf in timeframes
            ) / available_weight
        else:
            weighted_score = 5.0

        if weighted_score >= 6.5:
            consensus_bias = "bullish"
        elif weighted_score <= 3.5:
            consensus_bias = "bearish"
        else:
            consensus_bias = "neutral"

        # Generate recommendation based on alignment and bias
        if alignment == "full":
            if consensus_bias == "bullish":
                recommendation = "strong_buy"
            elif consensus_bias == "bearish":
                recommendation = "strong_sell"
            else:
                recommendation = "hold"
        elif alignment == "partial":
            if consensus_bias == "bullish":
                recommendation = "bullish_with_caution"
            elif consensus_bias == "bearish":
                recommendation = "bearish_with_caution"
            else:
                recommendation = "wait_for_clarity"
        elif alignment == "single_timeframe":
            if consensus_bias == "bullish":
                recommendation = "bullish_needs_confirmation"
            elif consensus_bias == "bearish":
                recommendation = "bearish_needs_confirmation"
            else:
                recommendation = "neutral_needs_confirmation"
        else:
            recommendation = "wait_for_clarity"

        return {
            "bias": consensus_bias,
            "confidence": round(final_confidence, 2),
            "alignment": alignment,
            "recommendation": recommendation,
            "weighted_score": round(weighted_score, 1),
        }
