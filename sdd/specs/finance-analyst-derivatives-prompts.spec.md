# Feature Specification: Analyst Derivatives Recommendations

**Feature ID**: FEAT-027
**Date**: 2026-03-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Depends on**: FEAT-026 (Multi-Executor Integration), FEAT-023 (Options Multi-Leg Strategies)

---

## 1. Motivation & Business Requirements

### Problem Statement

The investment committee system has fully integrated **options and futures execution** capabilities:
- IBKR executor handles stocks, ETFs, options (OPT), and futures (FUT)
- Alpaca executor supports long-leg options strategies
- CIO has `<options_strategies>` framework for Iron Butterflies and Iron Condors
- Risk Analyst has `<options_risk_tools>` for portfolio Greeks analysis

**However, the five analysts are NOT instructed to recommend or flag derivative opportunities:**

| Analyst | Current State | Gap |
|---------|--------------|-----|
| Macro Analyst | Mentions "index futures" as data source only | No guidance on recommending futures (ES, NQ, ZB, ZN) |
| Equity Analyst | Recommends stocks/ETFs only | No guidance on covered calls, protective puts, or when options > direct |
| Crypto Analyst | Recommends spot crypto only | No guidance on perpetual futures or options (if available) |
| Sentiment Analyst | Analyzes "options flow" as input | No guidance on translating flow signals into options recommendations |
| Risk Analyst | Has options risk tools | No guidance on recommending hedges via options/futures |

The CIO can recommend options strategies, but receives **no structured input** from analysts about when derivatives might be appropriate. This creates a gap where:
1. High-IV environments go unnoticed by analysts → CIO misses income opportunities
2. Directional conviction without options consideration → suboptimal risk/reward
3. Hedging needs identified by Risk Analyst → no clear path to options hedge

### Goals

1. Add `<derivatives_guidance>` section to each analyst prompt
2. Enable analysts to recommend `asset_class: OPTIONS` or `asset_class: FUTURES` in their output
3. Add `options_opportunity_flag` field to analyst output schema for CIO awareness
4. Provide specific criteria for when each analyst should consider derivatives
5. Add futures recommendation guidance for Macro Analyst (index futures, bond futures)
6. Add covered call / protective put guidance for Equity Analyst
7. Add hedge recommendation capability for Risk Analyst

### Non-Goals (explicitly out of scope)

- Changes to CIO prompts (already has options framework)
- New options/futures execution tools (already exist via IBKR/Alpaca)
- Options pricing or Greeks computation (covered by FEAT-023)
- Crypto derivatives (Binance perps, etc.) — separate feature due to regulatory complexity

---

## 2. Architectural Design

### Overview

This feature is **prompt-only** — no code changes required. We update the system prompts for each analyst to include derivatives awareness.

```
Current Flow:
  Analyst Report → CIO reviews → CIO decides on options (alone)

New Flow:
  Analyst Report (with options_opportunity_flag) → CIO reviews with analyst hints
    ↓
  Analyst: "High IV on SPY + range-bound view = options_opportunity_flag: true"
  CIO: Sees flag, applies <options_strategies> framework, recommends Iron Condor
```

### Integration Points

| Component | Change Type | Notes |
|-----------|-------------|-------|
| `prompts.py` — Macro Analyst | modify | Add `<derivatives_guidance>` for futures |
| `prompts.py` — Equity Analyst | modify | Add `<derivatives_guidance>` for options |
| `prompts.py` — Crypto Analyst | modify | Add note about futures awareness (limited) |
| `prompts.py` — Sentiment Analyst | modify | Add `<derivatives_guidance>` for flow → recommendation |
| `prompts.py` — Risk Analyst | modify | Add `<derivatives_guidance>` for hedging |
| `prompts.py` — All analyst output schemas | modify | Add `options_opportunity_flag` field |

### Prompt Additions

#### 2.1 Macro Analyst — Futures Guidance

```xml
<derivatives_guidance>
FUTURES RECOMMENDATIONS

You can recommend index futures and bond futures when macro conditions favor them.

AVAILABLE FUTURES (via IBKR):
- ES (E-mini S&P 500) / MES (Micro E-mini S&P 500)
- NQ (E-mini Nasdaq-100) / MNQ (Micro E-mini Nasdaq-100)
- YM (E-mini Dow) / MYM (Micro E-mini Dow)
- ZB (30-Year Treasury Bond) / ZN (10-Year Treasury Note)
- ZF (5-Year Treasury Note) / ZT (2-Year Treasury Note)

WHEN TO RECOMMEND FUTURES OVER ETFs:
1. Leverage efficiency needed (futures = 5-10% margin vs 100% for ETF)
2. Tax efficiency (60/40 treatment for Section 1256 contracts)
3. 24-hour trading needed (macro event overnight)
4. Hedging existing equity exposure (short futures vs liquidating)
5. Duration plays on rates (ZN/ZB more precise than TLT)

OUTPUT FORMAT:
When recommending a futures position, use:
{
    "asset": "ES",
    "asset_class": "futures",
    "signal": "buy",
    "rationale": "Fed pivot + positive macro momentum favors S&P continuation",
    "contract_month": "nearest_quarterly",
    "micro_alternative": "MES"
}

FLAG FOR CIO:
Set `options_opportunity_flag: true` when:
- VIX > 25 and you see range-bound consolidation ahead (CIO may prefer options income)
- Your macro view is high-conviction but timing uncertain (options limit loss)
</derivatives_guidance>
```

#### 2.2 Equity Analyst — Options Guidance

```xml
<derivatives_guidance>
OPTIONS RECOMMENDATIONS

You can recommend options strategies when they offer better risk/reward than direct positions.

STRATEGIES YOU CAN RECOMMEND:

1. COVERED CALL (income on existing positions)
   - Asset class: options
   - When: You're bullish but expect limited upside / range-bound
   - How: "Recommend selling 30-delta calls on existing XYZ position"

2. PROTECTIVE PUT (hedge existing positions)
   - Asset class: options
   - When: Bullish long-term but near-term risk elevated
   - How: "Recommend buying puts on XYZ to limit downside"

3. LONG CALL/PUT (directional with defined risk)
   - Asset class: options
   - When: High conviction + want limited capital at risk
   - How: "Recommend long calls on XYZ instead of shares"

4. COLLAR (protection + income)
   - Asset class: options
   - When: Protecting gains, willing to cap upside
   - How: "Recommend collar on XYZ: sell 25-delta call, buy 25-delta put"

WHEN TO RECOMMEND OPTIONS OVER STOCK:

| Condition | Recommendation |
|-----------|----------------|
| High conviction + limited capital | Long calls/puts |
| Own stock + range-bound view | Covered call |
| Own stock + binary event ahead | Protective put or collar |
| IV percentile > 60 + range view | Flag for CIO (iron condor/butterfly) |

OUTPUT FORMAT:
{
    "asset": "AAPL",
    "asset_class": "options",
    "signal": "buy",
    "strategy": "long_call",
    "rationale": "Earnings catalyst + limited risk profile preferred",
    "suggested_delta": 0.40,
    "suggested_dte": 45
}

FLAG FOR CIO:
Set `options_opportunity_flag: true` when:
- IV percentile > 50 on a stock you're neutral/range-bound on
- You recommend a stock but acknowledge binary event risk
- Existing portfolio position could benefit from income overlay
</derivatives_guidance>
```

#### 2.3 Sentiment Analyst — Flow to Recommendation

```xml
<derivatives_guidance>
OPTIONS FLOW TRANSLATION

You analyze options flow data. When you detect significant flow signals, you can
translate them into actionable recommendations.

FLOW SIGNALS TO RECOMMENDATIONS:

| Flow Signal | Interpretation | Recommendation |
|-------------|----------------|----------------|
| Unusual call buying (large premium, OTM) | Smart money bullish | Flag bullish, consider long calls |
| Unusual put buying (large premium, OTM) | Smart money bearish/hedging | Flag bearish or hedge |
| IV spike without news | Anticipated event | Flag options_opportunity (premium selling after event) |
| Put/call ratio extreme (> 1.5) | Fear elevated | Contrarian bullish signal |
| Call/put ratio extreme (< 0.5) | Complacency | Contrarian bearish signal |
| Gamma exposure flip | Dealer hedging shifts | Volatility regime change |

OUTPUT FORMAT:
When flow suggests options positioning:
{
    "asset": "NVDA",
    "asset_class": "options",
    "signal": "buy",
    "flow_signal": "unusual_call_sweep",
    "flow_premium": 2500000,
    "flow_interpretation": "Large institutional call buying ahead of earnings",
    "rationale": "Follow smart money flow"
}

FLAG FOR CIO:
Set `options_opportunity_flag: true` when:
- You detect elevated IV that may contract (post-catalyst setup)
- Flow suggests institutional hedging activity (CIO may want to sell premium)
- Gamma exposure indicates upcoming volatility (CIO may avoid premium selling)
</derivatives_guidance>
```

#### 2.4 Risk Analyst — Hedging Recommendations

```xml
<derivatives_guidance>
DERIVATIVES FOR HEDGING

When you identify portfolio risks, you can recommend derivatives-based hedges.

HEDGING STRATEGIES:

1. PORTFOLIO PROTECTION (tail risk)
   - Asset: SPY puts or VIX calls
   - When: Portfolio drawdown risk elevated, correlation spike expected
   - How: "Recommend 5% allocation to SPY puts (3-month, 10% OTM)"

2. SECTOR HEDGE
   - Asset: Sector ETF puts (XLF, XLE, XLK)
   - When: Overexposed to a sector with elevated risk
   - How: "Recommend XLK puts to hedge tech concentration"

3. SINGLE-STOCK HEDGE
   - Asset: Individual stock puts
   - When: Large single-stock position with event risk
   - How: "Recommend protective puts on TSLA ahead of earnings"

4. FUTURES HEDGE
   - Asset: ES/NQ short
   - When: Want to reduce beta without selling positions
   - How: "Recommend short ES to neutralize 20% of equity beta"

5. COLLAR RECOMMENDATION
   - When: Protecting gains while generating some income
   - How: "Recommend collar on XYZ"

WHEN TO RECOMMEND DERIVATIVES:

| Risk Identified | Hedge Recommendation |
|-----------------|---------------------|
| Portfolio VAR > limit | SPY puts or short ES |
| Correlation spike risk | VIX calls |
| Single stock > 15% | Protective puts or collar |
| Sector > 40% | Sector ETF puts |
| Event risk (earnings, FOMC) | Reduce delta or buy puts |

OUTPUT FORMAT:
{
    "hedge_recommendation": {
        "asset": "SPY",
        "asset_class": "options",
        "strategy": "protective_put",
        "rationale": "Portfolio VAR approaching limit, 3-month puts provide tail protection",
        "sizing_pct": 3.0,
        "suggested_strike": "10% OTM",
        "suggested_dte": 90
    }
}

FLAG FOR CIO:
Set `options_opportunity_flag: true` when:
- You identify a hedging need that could be met with options
- Portfolio has positions that could generate income via covered calls
- IV is elevated on portfolio holdings (premium selling opportunity)
</derivatives_guidance>
```

#### 2.5 Output Schema Addition (All Analysts)

Add to each analyst's output schema:

```json
{
    "analyst_id": "...",
    "...existing fields...",
    "options_opportunity_flag": "boolean — true if conditions favor options strategy (high IV, range-bound, hedge needed)",
    "options_opportunity_reason": "string — brief explanation if flag is true (e.g., 'IV percentile 75 on SPY, range-bound view')"
}
```

---

## 3. Acceptance Criteria

### Required

- [ ] Macro Analyst prompt includes `<derivatives_guidance>` for futures (ES, NQ, ZB, ZN)
- [ ] Equity Analyst prompt includes `<derivatives_guidance>` for covered calls, puts, collars
- [ ] Sentiment Analyst prompt includes `<derivatives_guidance>` for flow translation
- [ ] Risk Analyst prompt includes `<derivatives_guidance>` for hedging strategies
- [ ] All analyst output schemas include `options_opportunity_flag` and `options_opportunity_reason`
- [ ] Prompts pass lint check (`ruff check parrot/finance/prompts.py`)

### Verification

- [ ] Run deliberation CLI with research data and verify analysts can output `asset_class: options` or `asset_class: futures`
- [ ] Verify CIO receives `options_opportunity_flag` from analyst reports

---

## 4. Test Specification

### Unit Tests

None required — this is a prompt-only change.

### Integration Tests

```python
# Test that analyst prompts contain derivatives guidance
def test_macro_analyst_has_futures_guidance():
    from parrot.finance.prompts import MACRO_ANALYST_PROMPT
    assert "<derivatives_guidance>" in MACRO_ANALYST_PROMPT
    assert "ES" in MACRO_ANALYST_PROMPT
    assert "futures" in MACRO_ANALYST_PROMPT.lower()

def test_equity_analyst_has_options_guidance():
    from parrot.finance.prompts import EQUITY_ANALYST_PROMPT
    assert "<derivatives_guidance>" in EQUITY_ANALYST_PROMPT
    assert "covered_call" in EQUITY_ANALYST_PROMPT.lower() or "covered call" in EQUITY_ANALYST_PROMPT.lower()

def test_risk_analyst_has_hedge_guidance():
    from parrot.finance.prompts import RISK_ANALYST_PROMPT
    assert "<derivatives_guidance>" in RISK_ANALYST_PROMPT
    assert "hedge" in RISK_ANALYST_PROMPT.lower()

def test_analyst_output_schema_has_options_flag():
    from parrot.finance.prompts import (
        MACRO_ANALYST_PROMPT, EQUITY_ANALYST_PROMPT,
        SENTIMENT_ANALYST_PROMPT, RISK_ANALYST_PROMPT
    )
    for prompt in [MACRO_ANALYST_PROMPT, EQUITY_ANALYST_PROMPT,
                   SENTIMENT_ANALYST_PROMPT, RISK_ANALYST_PROMPT]:
        assert "options_opportunity_flag" in prompt
```

---

## 5. Rollout Plan

### Phase 1: Prompt Updates
1. Add `<derivatives_guidance>` to each analyst prompt in `prompts.py`
2. Update output schemas to include `options_opportunity_flag`
3. Run linter and tests

### Phase 2: Validation
1. Run full deliberation cycle with CLI
2. Verify analysts produce derivatives recommendations when appropriate
3. Verify CIO sees and uses `options_opportunity_flag`

---

## 6. Security & Compliance

- No new security concerns — prompts only
- Derivatives recommendations go through existing execution constraints
- Risk limits (15% max options exposure, 5% per strategy) enforced by CIO prompt

---

## 7. Open Questions

1. **Crypto derivatives**: Should Crypto Analyst recommend Binance perpetual futures? (Deferred — regulatory complexity): No
2. **Delta targets**: Should we specify exact delta recommendations or leave to CIO discretion?: CIO discretion.
3. **Futures margin**: Should Macro Analyst consider margin requirements in recommendations?: Yes.

---

## 8. References

- FEAT-026: Multi-Executor Integration (IBKR, Kraken)
- FEAT-023: Options Multi-Leg Strategies
- `parrot/finance/prompts.py`: All analyst and CIO prompts
- `parrot/finance/schemas.py`: `AssetClass.OPTIONS`, `AssetClass.FUTURES`
