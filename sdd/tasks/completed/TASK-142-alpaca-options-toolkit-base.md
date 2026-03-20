# TASK-142: AlpacaOptionsToolkit Base Class

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (2h)
**Depends-on**: TASK-141
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Foundation class for options toolkit. Sets up Alpaca Trading and Data clients,
> configures paper trading mode, and establishes the toolkit pattern.

---

## Scope

- Create `AlpacaOptionsToolkit` extending `AbstractToolkit`
- Initialize `TradingClient` with paper trading support
- Initialize `OptionHistoricalDataClient` for Greeks/snapshots
- Implement `get_tools()` method returning tool list
- Add proper logging setup

**NOT in scope**: Individual tool implementations (separate tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/alpaca_options.py` | CREATE | Toolkit base class |
| `parrot/finance/tools/__init__.py` | MODIFY | Export new toolkit |

---

## Implementation Notes

### Key Constraints
- Paper trading must be default (`paper=True`)
- Use `navconfig` for API key retrieval
- Follow pattern from `AlpacaWriteToolkit`
- All methods must be async

### References in Codebase
- `parrot/finance/tools/alpaca_write.py` — Pattern reference
- `parrot/tools/toolkit.py` — AbstractToolkit base class

---

## Acceptance Criteria

- [x] Class extends `AbstractToolkit`
- [x] `TradingClient` initialized with paper mode by default
- [x] `OptionHistoricalDataClient` initialized
- [x] `get_tools()` returns tool list (includes get_account helper)
- [x] Proper logging configured
- [x] Environment variables documented in docstring

---

## Completion Note

Created `parrot/finance/tools/alpaca_options.py` with:

1. **AlpacaOptionsToolkit** class extending `AbstractToolkit`
2. **Lazy-initialized clients**:
   - `trading_client` property → `TradingClient` with paper=True default
   - `data_client` property → `OptionHistoricalDataClient`
3. **AlpacaOptionsError** exception class
4. **get_account()** helper method for account info
- **cleanup()** method for client teardown

Exported from `parrot/finance/tools/__init__.py` as `AlpacaOptionsToolkit` and `AlpacaOptionsError`.

---
**Verification (2026-03-05)**:
- Verified implementation in `parrot/finance/tools/alpaca_options.py`.
- Verified exports in `parrot/finance/tools/__init__.py`.
- Ran unit tests in `tests/test_alpaca_options_toolkit.py` (TestAlpacaOptionsToolkit class) and confirmed all 13 tests pass.

