# TASK-153: Risk Analyst Options Tools

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (3h)
**Depends-on**: TASK-148
**Assigned-to**: claude-session

---

## Context

> Add options-specific risk analysis tools for Risk Analyst agent.
> Risk Analyst needs to evaluate Greeks exposure and stress test positions.

---

## Scope

- Add `analyze_options_portfolio_risk()` tool
- Add `stress_test_options_positions()` tool
- Add `get_position_greeks()` tool
- Integrate into Risk Analyst's toolset

**NOT in scope**: CIO tools (separate task), execution tools.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/alpaca_options.py` | MODIFY | Add risk analysis tools |
| `parrot/finance/swarm.py` | MODIFY | Add tools to Risk Analyst |
| `parrot/finance/prompts.py` | MODIFY | Update Risk Analyst prompt |

---

## Implementation Notes

### Tools to Add

**analyze_options_portfolio_risk():**
- Total options premium at risk
- Net delta (directional exposure)
- Net gamma (convexity risk)
- Net theta (daily decay)
- Net vega (vol sensitivity)
- Positions by expiration bucket
- Concentration by underlying

**stress_test_options_positions():**
- Hypothetical underlying move (±5%)
- Hypothetical IV change (±20%)
- P&L impact for each scenario

**get_position_greeks():**
- Fetch current Greeks for specific position
- Aggregate across all legs

---

## Acceptance Criteria

- [x] `analyze_options_portfolio_risk()` returns aggregate metrics
- [x] `stress_test_options_positions()` returns scenario P&L
- [x] `get_position_greeks()` returns position-level Greeks
- [x] Tools added to Risk Analyst's toolset
- [x] Risk Analyst prompt updated with tool descriptions

---

## Completion Note

**Completed**: 2026-03-04

### Implementation Summary

1. **Added 3 input schemas** to `parrot/finance/tools/alpaca_options.py`:
   - `AnalyzeOptionsPortfolioRiskInput` - parameters for portfolio risk analysis
   - `StressTestOptionsPositionsInput` - parameters for stress testing (underlying_move_pct, iv_change_pct)
   - `GetPositionGreeksInput` - position_id parameter

2. **Added 3 risk analysis methods** to `AlpacaOptionsToolkit`:
   - `analyze_options_portfolio_risk()` - aggregates Greeks across all positions, groups by expiration and underlying
   - `stress_test_options_positions()` - calculates P&L impact using first-order Greeks approximation
   - `get_position_greeks()` - returns Greeks for a specific position with aggregated totals

3. **Modified `swarm.py`** to filter and provide risk-specific tools to Risk Analyst:
   - Created `risk_analysis_tool_names` set with the 4 risk tools
   - Added filtered tools to Risk Analyst's toolset

4. **Updated `ANALYST_RISK` prompt** in `prompts.py`:
   - Added `<options_risk_tools>` section documenting all risk analysis tools
   - Explains Greek metrics, stress testing scenarios, and when to use each tool

All tools verified working and accessible to Risk Analyst agent.
