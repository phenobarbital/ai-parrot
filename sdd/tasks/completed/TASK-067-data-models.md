# TASK-067: Technical Analysis Data Models

**Feature**: TechnicalAnalysisTool Improvements
**Spec**: `sdd/specs/technical-analysis-improvements.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-opus-session

---

## Context

This task creates the foundational Pydantic models and dataclasses for the TechnicalAnalysisTool improvements. These models define the structured output format for ADX, ATR, signals, and composite scores. All subsequent tasks depend on these models being available.

Reference: Spec Section 2 (Data Models)

---

## Scope

- Implement `TechnicalSignal` dataclass for structured signal output
- Implement `ADXOutput` Pydantic model for ADX indicator results
- Implement `ATROutput` Pydantic model for ATR indicator with stop-loss levels (long AND short positions)
- Implement `CompositeScore` Pydantic model for asset ranking scores
- Add all models to the technical_analysis.py file

**NOT in scope**:
- Indicator calculation logic (TASK-068, TASK-069, TASK-070)
- Signal generation logic (TASK-071)
- CompositeScoreTool implementation (TASK-072)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/technical_analysis.py` | MODIFY | Add new data models after existing imports |

---

## Implementation Notes

### Pattern to Follow

```python
from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel, Field

@dataclass
class TechnicalSignal:
    """Structured technical signal with confidence scoring."""
    indicator: str          # "RSI", "MACD", "SMA", "ADX", "BB", "Volume"
    signal_type: str        # "overbought", "golden_cross", etc.
    direction: Literal["bullish", "bearish", "neutral"]
    strength: Literal["strong", "moderate", "weak"]
    confidence: float       # 0.0-1.0
    value: float | None     # The indicator value that triggered
    description: str        # Human-readable explanation


class ADXOutput(BaseModel):
    """ADX indicator output."""
    value: float = Field(..., description="ADX value (0-100 scale)")
    plus_di: float = Field(..., description="Positive directional indicator")
    minus_di: float = Field(..., description="Negative directional indicator")
    trend_strength: Literal["absent", "weak", "strong", "extreme"]
    trend_direction: Literal["bullish", "bearish", "undefined"]


class ATROutput(BaseModel):
    """ATR indicator output with stop-loss levels."""
    value: float = Field(..., description="Absolute ATR value")
    percent: float = Field(..., description="ATR as percentage of price")
    period: int = Field(default=14)
    stop_loss_long: dict = Field(
        ...,
        description="Stop-loss levels for long positions (below price)"
    )
    stop_loss_short: dict = Field(
        ...,
        description="Stop-loss levels for short positions (above price)"
    )


class CompositeScore(BaseModel):
    """Composite technical score for asset ranking."""
    symbol: str
    score: float = Field(..., ge=0, le=10)
    max_score: float = Field(default=10.0)
    label: Literal["strong_bullish", "moderate_bullish", "neutral", "moderate_bearish", "strong_bearish"]
    components: dict
    signals: list
    recommendation_hint: str
```

### Key Constraints

- ATR stop-loss must include both long and short position levels (per open question decision)
- `trend_strength` thresholds: "absent" (<20), "weak" (20-25), "strong" (25-50), "extreme" (>50)
- `trend_direction` based on +DI vs -DI comparison
- All models must use strict type hints

### References in Codebase

- `parrot/tools/technical_analysis.py` — existing `TechnicalAnalysisInput` Pydantic model
- Spec section 2.4 "Data Models" — detailed field specifications

---

## Acceptance Criteria

- [x] `TechnicalSignal` dataclass defined with all 7 fields
- [x] `ADXOutput` model with trend_strength and trend_direction enums
- [x] `ATROutput` model with `stop_loss_long` and `stop_loss_short` dicts
- [x] `CompositeScore` model with 0-10 score bounds
- [x] All models importable: `from parrot.tools.technical_analysis import TechnicalSignal, ADXOutput, ATROutput, CompositeScore`
- [x] No linting errors: `ruff check parrot/tools/technical_analysis.py`

---

## Test Specification

```python
# tests/test_technical_analysis_models.py
import pytest
from parrot.tools.technical_analysis import (
    TechnicalSignal,
    ADXOutput,
    ATROutput,
    CompositeScore,
)


class TestTechnicalSignal:
    def test_creation(self):
        """TechnicalSignal dataclass creates correctly."""
        signal = TechnicalSignal(
            indicator="RSI",
            signal_type="overbought",
            direction="bearish",
            strength="moderate",
            confidence=0.7,
            value=72.5,
            description="RSI above 70 indicates overbought conditions"
        )
        assert signal.indicator == "RSI"
        assert signal.direction == "bearish"
        assert signal.confidence == 0.7


class TestADXOutput:
    def test_valid_adx(self):
        """ADXOutput validates correctly."""
        adx = ADXOutput(
            value=32.5,
            plus_di=28.3,
            minus_di=15.7,
            trend_strength="strong",
            trend_direction="bullish"
        )
        assert adx.value == 32.5
        assert adx.trend_strength == "strong"

    def test_invalid_trend_strength(self):
        """ADXOutput rejects invalid trend_strength."""
        with pytest.raises(ValueError):
            ADXOutput(
                value=32.5,
                plus_di=28.3,
                minus_di=15.7,
                trend_strength="invalid",
                trend_direction="bullish"
            )


class TestATROutput:
    def test_stop_loss_levels(self):
        """ATROutput includes both long and short stop-loss levels."""
        atr = ATROutput(
            value=3.42,
            percent=1.85,
            period=14,
            stop_loss_long={"tight_1x": 181.58, "standard_2x": 178.16, "wide_3x": 174.74},
            stop_loss_short={"tight_1x": 188.42, "standard_2x": 191.84, "wide_3x": 195.26}
        )
        assert "tight_1x" in atr.stop_loss_long
        assert "tight_1x" in atr.stop_loss_short


class TestCompositeScore:
    def test_score_bounds(self):
        """CompositeScore validates 0-10 bounds."""
        score = CompositeScore(
            symbol="AAPL",
            score=7.2,
            label="moderate_bullish",
            components={"sma": {"score": 2.0, "max": 2.0}},
            signals=[],
            recommendation_hint="trending_entry"
        )
        assert 0 <= score.score <= 10

    def test_score_out_of_bounds(self):
        """CompositeScore rejects scores outside 0-10."""
        with pytest.raises(ValueError):
            CompositeScore(
                symbol="AAPL",
                score=15.0,  # Invalid
                label="strong_bullish",
                components={},
                signals=[],
                recommendation_hint="buy"
            )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/technical-analysis-improvements.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-067-data-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:

Implemented 4 data models in `parrot/tools/technical_analysis.py`:

1. **TechnicalSignal** (dataclass) - 7 fields for structured signal output with direction, strength, and confidence
2. **ADXOutput** (Pydantic) - ADX indicator with trend_strength enum (absent/weak/strong/extreme) and trend_direction enum (bullish/bearish/undefined)
3. **ATROutput** (Pydantic) - ATR indicator with separate `stop_loss_long` and `stop_loss_short` dicts for position-specific stop levels
4. **CompositeScore** (Pydantic) - 0-10 bounded score with label enum and component breakdown

Created comprehensive test suite at `tests/test_technical_analysis_models.py` with 23 test cases covering:
- All field validations
- Enum constraint enforcement
- Score bounds validation
- Serialization (model_dump)

**Deviations from spec**: none
