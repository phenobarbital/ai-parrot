# TASK-157: Options Toolkit Documentation

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (2h)
**Depends-on**: TASK-154
**Assigned-to**: claude-session

---

## Context

> Documentation and usage examples for the options toolkit.
> Covers strategy selection, API usage, and integration patterns.

---

## Scope

- Create `docs/finance/options-strategies.md` documentation
- Include strategy explanations with P&L diagrams
- Provide code examples for toolkit usage
- Document environment setup (Alpaca credentials)
- Add troubleshooting section

**NOT in scope**: API reference (auto-generated from docstrings).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/finance/options-strategies.md` | CREATE | Main documentation |

---

## Implementation Notes

### Documentation Structure

1. **Overview**
   - What strategies are supported
   - When to use each strategy

2. **Setup**
   - Environment variables required
   - Paper trading configuration

3. **Strategy Guide**
   - Iron Butterfly: definition, P&L profile, use cases
   - Iron Condor: definition, P&L profile, use cases
   - Decision framework table

4. **Usage Examples**
   ```python
   from parrot.finance.tools.alpaca_options import AlpacaOptionsToolkit

   toolkit = AlpacaOptionsToolkit(paper=True)

   # Place Iron Butterfly
   result = await toolkit.place_iron_butterfly(
       underlying="SPY",
       expiration_days=30,
       wing_width=5.0,
   )
   ```

5. **Integration**
   - How CIO uses options tools
   - How Risk Analyst monitors positions

6. **Troubleshooting**
   - Common errors and solutions
   - Liquidity issues
   - Risk limit rejections

---

## Acceptance Criteria

- [x] Documentation created at `docs/finance/options-strategies.md`
- [x] Both strategies explained with diagrams
- [x] Code examples for all toolkit methods
- [x] Environment setup documented
- [x] Troubleshooting section included
- [x] Links to Alpaca documentation included

---

## Completion Note

**Completed**: 2026-03-04
**Implemented by**: claude-session

### Summary

Created comprehensive documentation at `docs/finance/options-strategies.md` (468 lines) covering:

1. **Overview** - Strategy comparison table, theta-positive characteristics
2. **Setup** - Environment variables, installation, paper trading config
3. **Strategy Guide**:
   - Iron Butterfly: ASCII P&L diagram, structure table, use cases, example
   - Iron Condor: ASCII P&L diagram, structure table, use cases, example
4. **Decision Framework** - When to use each strategy based on IV/market
5. **Toolkit Methods Reference**:
   - `get_options_chain()` with Greeks
   - `place_iron_butterfly()`
   - `place_iron_condor()`
   - `get_options_positions()`
   - `close_options_position()`
6. **Integration** - CIO agent and Risk Analyst usage patterns
7. **Risk Management** - Position limits, best practices
8. **Troubleshooting** - Common errors with solutions
9. **External Resources** - Links to Alpaca documentation
10. **Testing** - How to run integration/unit tests

### Files Created

- `docs/finance/options-strategies.md` (468 lines)
