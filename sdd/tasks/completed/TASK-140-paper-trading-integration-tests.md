# TASK-140: Integration Tests

**Feature**: Finance Paper Trading Executors (FEAT-022)
**Spec**: `sdd/specs/finance-paper-trading.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-6h)
**Depends-on**: TASK-139
**Assigned-to**: claude-session

---

## Context

> Integration tests that verify paper-trading works end-to-end with real
> testnet/paper environments (when available) or comprehensive mocks.
> Implements Spec Section 4 (Integration Tests).

---

## Scope

From spec's integration test specification:
- `test_alpaca_paper_order_e2e` — place/fill/cancel on Alpaca paper account
- `test_binance_testnet_order_e2e` — place/fill/cancel on Binance testnet
- `test_ibkr_paper_order_e2e` — place/fill/cancel on IBKR paper (requires TWS)
- `test_kraken_validate_order_e2e` — place validate-only order on Kraken
- `test_dry_run_full_pipeline` — run complete pipeline in DRY_RUN mode
- `test_orchestrator_mixed_modes` — different toolkits with different modes

Mark tests that require external services with `@pytest.mark.integration`.

**NOT in scope**: Live/production API testing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/test_paper_trading_e2e.py` | CREATE | E2E integration tests |

---

## Implementation Notes

### Key Constraints
- Tests requiring external services should be skippable
- Use `@pytest.mark.skipif` for missing credentials
- IBKR test requires TWS running (skip if not available)
- Binance testnet may have rate limits
- All tests should clean up after themselves (cancel orders)

### References in Codebase
- `tests/integration/test_enrichment_pipeline.py` — integration test patterns
- Environment variable patterns for credentials

---

## Acceptance Criteria

- [x] All 6 integration tests from spec implemented
- [x] Tests marked with `@pytest.mark.integration`
- [x] Tests skip gracefully when credentials missing
- [x] `test_dry_run_full_pipeline` passes without any API calls
- [x] Tests clean up (cancel) any orders placed
- [x] Documentation on how to run integration tests

---

## Completion Note

Implemented `tests/integration/test_paper_trading_e2e.py` with 16 tests:

**Credential-Required Tests (4, skip gracefully):**
- TestAlpacaPaperOrderE2E - skips without ALPACA_API_KEY/SECRET
- TestBinanceTestnetOrderE2E - skips without BINANCE_API_KEY/SECRET
- TestIBKRPaperOrderE2E - skips without TWS running on port 7497
- TestKrakenValidateOrderE2E - skips without KRAKEN_API_KEY/SECRET

**DRY_RUN Pipeline Tests (5, no external deps):**
- test_dry_run_full_pipeline - orchestrator setup
- test_dry_run_order_execution_no_api_calls - simulated order placement
- test_dry_run_position_tracking - position tracking via VirtualPortfolio
- test_dry_run_account_balance - simulated balance reporting
- test_dry_run_order_cancellation - order lifecycle management

**Orchestrator Mixed Modes Tests (4):**
- test_orchestrator_with_dry_run_config - VirtualPortfolio created
- test_orchestrator_with_paper_config - no VirtualPortfolio in PAPER mode
- test_multiple_toolkits_dry_run_share_portfolio - shared portfolio state
- test_isolated_portfolios_per_toolkit - independent portfolio isolation

**Safety Tests (3):**
- test_live_mode_blocked_in_dev_environment - RuntimeError in dev
- test_live_mode_allowed_in_production - LIVE allowed in production
- test_dry_run_never_calls_external_api - HTTP mocked, never called

**Test Results:** 12 passed, 4 skipped
