# TASK-072: CompositeScoreTool Implementation

**Feature**: TechnicalAnalysisTool Improvements
**Spec**: `sdd/specs/technical-analysis-improvements.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-067, TASK-068, TASK-069, TASK-070, TASK-071
**Assigned-to**: claude-opus-session

---

## Context

Per the open question decision, composite scoring is implemented as a **separate tool** (`CompositeScoreTool`) rather than a method on `TechnicalAnalysisTool`. This tool provides 0-10 bullish/bearish scores for ranking multiple assets by technical strength.

This enables queries like "which of these 10 stocks has the strongest bullish setup?" and powers the equity research crew's scanning capabilities.

Reference: Spec Section 3 (Module 3: Composite Scoring Engine) + Open Question decision

---

## Scope

- Create new `CompositeScoreTool` class inheriting from `AbstractToolkit`
- Implement `_execute()` to compute composite scores
- Implement 7 score components (max 10 points total):
  1. SMA Position (0-2 pts)
  2. RSI Zone (0-1 pt)
  3. MACD (0-1.5 pts)
  4. ADX Trend (0-1.5 pts)
  5. Momentum (0-2 pts)
  6. Volume (0-1 pt)
  7. EMA Alignment (0-1 pt)
- Support both `bullish` and `bearish` score types
- Support `stock` and `crypto` asset types (crypto adjustments)
- Return `CompositeScore` model

**NOT in scope**:
- Multi-timeframe analysis (TASK-073)
- Batch ranking of multiple symbols (future enhancement)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/composite_score.py` | CREATE | New CompositeScoreTool |
| `parrot/tools/__init__.py` | MODIFY | Export CompositeScoreTool |
| `tests/test_composite_score_tool.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
"""
Composite Score Tool for Technical Analysis
"""
from typing import Literal
import pandas as pd
import numpy as np
from pydantic import BaseModel, Field

from navconfig.logging import logging
from .toolkit import AbstractToolkit
from .technical_analysis import (
    TechnicalAnalysisTool,
    TechnicalSignal,
    CompositeScore,
)


class CompositeScoreInput(BaseModel):
    symbol: str = Field(..., description="Symbol to score")
    asset_type: Literal["stock", "crypto"] = Field("stock", description="Asset type")
    score_type: Literal["bullish", "bearish"] = Field("bullish", description="Score type")
    source: str = Field("alpaca", description="Data source")
    lookback_days: int = Field(365, description="Days of historical data")


class CompositeScoreTool(AbstractToolkit):
    """
    Tool for computing composite technical scores for asset ranking.

    Score Components (max 10 points):
    - SMA Position: 0-2 pts
    - RSI Zone: 0-1 pt
    - MACD: 0-1.5 pts
    - ADX Trend: 0-1.5 pts
    - Momentum: 0-2 pts
    - Volume: 0-1 pt
    - EMA Alignment: 0-1 pt
    """
    name = "composite_score"
    description = "Computes composite bullish/bearish scores (0-10) for ranking assets by technical strength."
    args_schema = CompositeScoreInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.tech_tool = TechnicalAnalysisTool()

    async def _execute(
        self,
        symbol: str,
        asset_type: Literal["stock", "crypto"] = "stock",
        score_type: Literal["bullish", "bearish"] = "bullish",
        source: str = "alpaca",
        lookback_days: int = 365,
    ) -> CompositeScore:
        """
        Compute composite technical score.
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
                label="neutral",
                components={},
                signals=[],
                recommendation_hint="data_unavailable"
            )

        # Calculate score components
        components = self._calculate_components(analysis, score_type, asset_type)

        # Sum total score
        total = sum(c["score"] for c in components.values())

        # Determine label
        if total >= 7.5:
            label = "strong_bullish" if score_type == "bullish" else "strong_bearish"
        elif total >= 5.5:
            label = "moderate_bullish" if score_type == "bullish" else "moderate_bearish"
        elif total >= 3.5:
            label = "neutral"
        elif total >= 2.0:
            label = "moderate_bearish" if score_type == "bullish" else "moderate_bullish"
        else:
            label = "strong_bearish" if score_type == "bullish" else "strong_bullish"

        # Recommendation hint
        if label.startswith("strong_bullish"):
            hint = "trending_entry"
        elif label.startswith("moderate_bullish"):
            hint = "pullback_buy"
        elif label == "neutral":
            hint = "wait"
        else:
            hint = "avoid"

        return CompositeScore(
            symbol=symbol,
            score=round(total, 2),
            label=label,
            components=components,
            signals=analysis.get("signals", []),
            recommendation_hint=hint
        )

    def _calculate_components(
        self,
        analysis: dict,
        score_type: str,
        asset_type: str
    ) -> dict:
        """Calculate individual score components."""
        components = {}
        indicators = analysis.get("indicators", {})
        price = analysis.get("price", 0)

        # 1. SMA Position (0-2 pts)
        sma_score = 0.0
        sma_20 = indicators.get("SMA_50")  # Using SMA_50 as proxy for SMA_20
        sma_50 = indicators.get("SMA_50")
        if sma_20 and price > sma_20:
            sma_score += 1.0
        if sma_50 and price > sma_50:
            sma_score += 1.0
        components["sma_position"] = {"score": sma_score, "max": 2.0}

        # 2. RSI Zone (0-1 pt)
        rsi = indicators.get("RSI_14")
        rsi_score = 0.0
        if rsi:
            if 50 <= rsi <= 70:
                rsi_score = 1.0
            elif 30 <= rsi < 50:
                rsi_score = 0.5
            elif rsi < 30:
                rsi_score = 0.25
        components["rsi_zone"] = {"score": rsi_score, "max": 1.0}

        # 3. MACD (0-1.5 pts)
        macd = indicators.get("MACD", {})
        macd_score = 0.0
        if isinstance(macd, dict):
            if macd.get("value", 0) > macd.get("signal", 0):
                macd_score += 1.0
            if macd.get("hist", 0) > 0:
                macd_score += 0.5
        components["macd"] = {"score": min(macd_score, 1.5), "max": 1.5}

        # 4. ADX Trend (0-1.5 pts)
        adx_score = 0.0
        # ADX scoring would use the ADX output
        # For now, placeholder based on available data
        components["adx_trend"] = {"score": adx_score, "max": 1.5}

        # 5. Momentum (0-2 pts)
        # period_return / 20, clamped to [-1, 2]
        momentum_score = 0.0
        # Would calculate from price history
        components["momentum"] = {"score": momentum_score, "max": 2.0}

        # 6. Volume (0-1 pt)
        volume_score = 0.0
        avg_vol = indicators.get("Avg_Volume_20d", 0)
        current_vol = analysis.get("volume", 0)
        if avg_vol and current_vol > avg_vol * 1.5:
            volume_score = 1.0
        elif avg_vol and current_vol > avg_vol:
            volume_score = 0.5
        components["volume"] = {"score": volume_score, "max": 1.0}

        # 7. EMA Alignment (0-1 pt)
        ema_score = 0.0
        # EMA12 > EMA26 > SMA50 would be 1.0
        components["ema_alignment"] = {"score": ema_score, "max": 1.0}

        # Crypto adjustments
        if asset_type == "crypto":
            # Weight momentum higher for crypto
            components["momentum"]["max"] = 2.5
            # Reduce SMA weight
            components["sma_position"]["max"] = 1.5

        return components
```

### Key Constraints

- Must use `TechnicalAnalysisTool` internally for data fetching and indicator calculation
- Score components must sum to max 10 points
- Crypto adjustments: higher momentum weight, lower SMA weight
- Label thresholds: strong(>=7.5), moderate(>=5.5), neutral(>=3.5), weak(>=2.0), very weak(<2.0)

### References in Codebase

- `parrot/tools/toolkit.py` — `AbstractToolkit` base class
- Brainstorm doc lines 56-64, 266-296 — composite score reference

---

## Acceptance Criteria

- [ ] `CompositeScoreTool` class created as separate tool
- [ ] All 7 score components implemented
- [ ] Returns `CompositeScore` model with components breakdown
- [ ] `bullish` and `bearish` score types supported
- [ ] Crypto-specific adjustments applied when `asset_type == "crypto"`
- [ ] Tool registered and exported from `parrot/tools/__init__.py`
- [ ] All tests pass: `pytest tests/test_composite_score_tool.py -v`

---

## Test Specification

```python
# tests/test_composite_score_tool.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.tools.composite_score import CompositeScoreTool


@pytest.fixture
def score_tool():
    return CompositeScoreTool()


@pytest.fixture
def bullish_analysis():
    """Mock analysis result for bullish setup."""
    return {
        "symbol": "AAPL",
        "price": 185.0,
        "indicators": {
            "SMA_50": 180.0,
            "SMA_200": 170.0,
            "RSI_14": 62.0,
            "MACD": {"value": 2.0, "signal": 1.5, "hist": 0.5},
            "Avg_Volume_20d": 35000000,
        },
        "volume": 50000000,
        "signals": [],
    }


@pytest.fixture
def bearish_analysis():
    """Mock analysis result for bearish setup."""
    return {
        "symbol": "AAPL",
        "price": 165.0,
        "indicators": {
            "SMA_50": 180.0,
            "SMA_200": 190.0,
            "RSI_14": 35.0,
            "MACD": {"value": -1.0, "signal": 0.5, "hist": -1.5},
            "Avg_Volume_20d": 35000000,
        },
        "volume": 30000000,
        "signals": [],
    }


class TestCompositeScoreTool:
    @pytest.mark.asyncio
    async def test_bullish_score(self, score_tool, bullish_analysis):
        """Bullish setup produces high score."""
        with patch.object(score_tool.tech_tool, '_execute', new_callable=AsyncMock) as mock:
            mock.return_value = bullish_analysis
            result = await score_tool._execute(symbol="AAPL", score_type="bullish")

        assert result.symbol == "AAPL"
        assert result.score > 5.0  # Should be moderate-to-strong bullish
        assert "bullish" in result.label

    @pytest.mark.asyncio
    async def test_bearish_score(self, score_tool, bearish_analysis):
        """Bearish setup produces low bullish score."""
        with patch.object(score_tool.tech_tool, '_execute', new_callable=AsyncMock) as mock:
            mock.return_value = bearish_analysis
            result = await score_tool._execute(symbol="AAPL", score_type="bullish")

        assert result.score < 4.0  # Should be neutral-to-bearish

    @pytest.mark.asyncio
    async def test_components_breakdown(self, score_tool, bullish_analysis):
        """Score includes component breakdown."""
        with patch.object(score_tool.tech_tool, '_execute', new_callable=AsyncMock) as mock:
            mock.return_value = bullish_analysis
            result = await score_tool._execute(symbol="AAPL")

        assert "sma_position" in result.components
        assert "rsi_zone" in result.components
        assert "macd" in result.components
        assert all("score" in c and "max" in c for c in result.components.values())

    @pytest.mark.asyncio
    async def test_crypto_adjustments(self, score_tool, bullish_analysis):
        """Crypto asset type applies different weights."""
        with patch.object(score_tool.tech_tool, '_execute', new_callable=AsyncMock) as mock:
            mock.return_value = bullish_analysis
            result = await score_tool._execute(symbol="BTC", asset_type="crypto")

        # Crypto should have different max values
        assert result.components["momentum"]["max"] == 2.5
        assert result.components["sma_position"]["max"] == 1.5


class TestScoreLabels:
    def test_score_label_thresholds(self, score_tool):
        """Verify label assignment thresholds."""
        # This would test the internal label assignment logic
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/technical-analysis-improvements.spec.md` for full context
2. **Check dependencies** — verify TASK-067 through TASK-071 are in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-072-composite-score-tool.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:

Created `CompositeScoreTool` as a separate tool in `parrot/tools/composite_score.py`:

1. **7 Score Components** (max 10 points):
   - `sma_position` (0-2 pts): Price relative to SMA50/SMA200
   - `rsi_zone` (0-1 pt): RSI momentum zone scoring
   - `macd` (0-1.5 pts): MACD vs signal line + histogram
   - `adx_trend` (0-1.5 pts): Placeholder for ADX (not yet in TechnicalAnalysisTool output)
   - `momentum` (0-2 pts): Price momentum relative to SMA50
   - `volume` (0-1 pt): Volume confirmation vs 20-day average
   - `ema_alignment` (0-1 pt): Placeholder for EMA stack (not yet in output)

2. **Score Types**: Both `bullish` and `bearish` scoring supported with inverted conditions

3. **Asset Types**: `stock` and `crypto` with crypto adjustments:
   - Momentum max increased to 2.5 pts
   - SMA position max reduced to 1.5 pts

4. **Label Thresholds**:
   - >= 7.5: strong_bullish/bearish
   - >= 5.5: moderate_bullish/bearish
   - >= 3.5: neutral
   - >= 2.0: moderate opposite
   - < 2.0: strong opposite

5. **Recommendation Hints**: trending_entry, pullback_buy, wait, caution, avoid

6. **Integration**: Uses TechnicalAnalysisTool internally via lazy initialization

Created 25 comprehensive tests covering all components, labels, hints, and edge cases.

**Deviations from spec**:
- ADX and EMA alignment components return 0 until TASK-074 (Output Restructuring) integrates these indicators into TechnicalAnalysisTool output. Placeholder code included for when they become available.
