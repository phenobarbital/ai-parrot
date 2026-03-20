# TASK-144: Get Options Chain with Greeks

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (3h)
**Depends-on**: TASK-142
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Fetch options chain from Alpaca with Greeks (delta, gamma, theta, vega).
> This data is required for strike selection and risk analysis.

---

## Scope

- Implement `get_options_chain()` tool method in `AlpacaOptionsToolkit`
- Fetch contracts within expiration range (min_dte to max_dte)
- Fetch contracts within strike range (% of underlying price)
- Get snapshots with Greeks for each contract
- Return structured DataFrame or dict with all data

**NOT in scope**: Strike selection logic, order placement.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/alpaca_options.py` | MODIFY | Add get_options_chain method |

---

## Implementation Notes

### Key Constraints
- Use `GetOptionContractsRequest` for contract discovery
- Use `OptionSnapshotRequest` for Greeks (batch if possible)
- Run blocking Alpaca calls in executor (`loop.run_in_executor`)
- Filter by open interest threshold (default: 50)
- Include bid/ask spread for liquidity analysis

### Alpaca API Usage
```python
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.data.requests import OptionSnapshotRequest

# Get contracts
contracts = client.get_option_contracts(GetOptionContractsRequest(
    underlying_symbols=[underlying],
    expiration_date_gte=min_date,
    expiration_date_lte=max_date,
))

# Get snapshots with Greeks
snapshots = data_client.get_option_snapshot(OptionSnapshotRequest(
    symbol_or_symbols=[c.symbol for c in contracts]
))
```

---

## Acceptance Criteria

- [x] Returns calls and puts separately
- [x] Each contract includes: symbol, strike, expiration, bid, ask, bid_size, ask_size
- [x] Greeks included: delta, gamma, theta, vega, rho, IV
- [x] Respects min_dte/max_dte filters
- [x] Respects strike_range_pct filter
- [x] Async implementation with asyncio.to_thread for blocking calls

---

## Completion Note

Implemented `get_options_chain()` in `AlpacaOptionsToolkit`:

1. **GetOptionsChainInput** Pydantic schema with:
   - underlying, min_dte, max_dte, strike_range_pct

2. **get_options_chain()** method:
   - Fetches underlying price using StockHistoricalDataClient
   - Uses OptionChainRequest with date/strike filters
   - Returns calls and puts separately with full Greeks
   - Parses OCC symbol format for contract details

3. **Helper methods**:
   - `_get_underlying_price()` - Get current stock price
   - `_parse_option_symbol()` - Parse OCC format symbols

Note: Open Interest is not available in real-time OptionsSnapshot;
using bid_size/ask_size for liquidity analysis instead.

---
**Verification (2026-03-05)**:
- Verified implementation in `parrot/finance/tools/alpaca_options.py`.
- Verified existence of `get_options_chain`, `_get_underlying_price`, and `_parse_option_symbol`.
- Verified tool decoration with `@tool_schema(GetOptionsChainInput)`.
- Ran unit tests in `tests/test_alpaca_options_toolkit.py` and confirmed they pass.

