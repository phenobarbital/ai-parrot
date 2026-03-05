"""IBKR toolkit diagnostic script — toolkit layer only (no agent/executor).

Runs a structured sequence of tests against IBKRWriteToolkit directly to
isolate whether failures originate in the toolkit or in the agent executor.

Modes
-----
1. DRY_RUN (default, no TWS required)
   Tests all toolkit logic using VirtualPortfolio.

2. PAPER (requires IB Gateway or TWS running in paper mode)
   Tests real TWS connectivity + order submission.

Usage
-----
    source .venv/bin/activate

    # DRY_RUN — no TWS needed (quick sanity check)
    python docs/finance/ibkr_diag.py

    # PAPER — needs IB Gateway on port 4002 / 4004 or TWS on 7497
    python docs/finance/ibkr_diag.py --paper

    # Override port and client ID
    python docs/finance/ibkr_diag.py --paper --port 7497 --client-id 10

Environment variables (all optional, flags take precedence)
-----------------------------------------------------------
    IBKR_HOST       Default: 127.0.0.1
    IBKR_PORT       Default: 4002 (PAPER)
    IBKR_CLIENT_ID  Default: 99
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Ensure the repo root is importable when run directly
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("ibkr_diag")

# ---------------------------------------------------------------------------
# Test parameters — safe values for paper account
# ---------------------------------------------------------------------------
SYMBOL = "AAPL"
QTY = 1
LIMIT_PRICE = 1.00          # Far below market → stays open, won't fill
STOP_PRICE = 0.50           # Same idea
TAKE_PROFIT_PRICE = 1.50
STOP_LOSS_PRICE = 0.75


def _pp(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


class DiagResult:
    """Collects pass/fail for each test step."""

    def __init__(self) -> None:
        self._steps: list[tuple[str, bool, str]] = []

    def record(self, name: str, passed: bool, note: str = "") -> None:
        self._steps.append((name, passed, note))
        icon = "✓" if passed else "✗"
        level = logging.INFO if passed else logging.ERROR
        logger.log(level, "%s  %s  %s", icon, name, f"— {note}" if note else "")

    def summary(self) -> int:
        """Print summary and return exit code (0=all pass, 1=any fail)."""
        passed = [s for s in self._steps if s[1]]
        failed = [s for s in self._steps if not s[1]]
        print("\n" + "=" * 60)
        print(f"RESULTS: {len(passed)} passed, {len(failed)} failed")
        if failed:
            print("\nFailed steps:")
            for name, _, note in failed:
                print(f"  ✗ {name}: {note}")
        print("=" * 60)
        return 0 if not failed else 1


# ---------------------------------------------------------------------------
# Individual test helpers
# ---------------------------------------------------------------------------

async def _test_account_summary(toolkit, diag: DiagResult) -> Dict[str, Any]:
    from parrot.finance.tools.ibkr_write import IBKRWriteError
    try:
        result = await toolkit.get_account_summary()
        logger.info("Account summary:\n%s", _pp(result))
        diag.record("get_account_summary", True)
        return result
    except IBKRWriteError as exc:
        diag.record("get_account_summary", False, str(exc))
        return {}


async def _test_get_positions(toolkit, diag: DiagResult) -> None:
    from parrot.finance.tools.ibkr_write import IBKRWriteError
    try:
        positions = await toolkit.get_positions()
        logger.info("Positions (%d):\n%s", len(positions), _pp(positions))
        diag.record("get_positions", True, f"{len(positions)} positions")
    except IBKRWriteError as exc:
        diag.record("get_positions", False, str(exc))


async def _test_limit_order(toolkit, diag: DiagResult, cancel: bool = True) -> str | None:
    """Place a limit order and return order_id on success."""
    from parrot.finance.tools.ibkr_write import IBKRWriteError
    label = "place_limit_order"
    try:
        result = await toolkit.place_limit_order(
            symbol=SYMBOL,
            sec_type="STK",
            exchange="SMART",
            currency="USD",
            action="BUY",
            quantity=QTY,
            limit_price=LIMIT_PRICE,
            tif="DAY",
        )
        logger.info("Limit order result:\n%s", _pp(result))
        order_id = result.get("order_id")
        status = result.get("status", "unknown")
        if order_id is not None:
            diag.record(label, True, f"order_id={order_id} status={status}")
            if cancel and not _is_dry_run(toolkit):
                await _test_cancel_order(toolkit, diag, order_id, label="cancel_limit_order")
            return str(order_id)
        else:
            diag.record(label, False, "no order_id in result")
            return None
    except IBKRWriteError as exc:
        diag.record(label, False, str(exc))
        return None


async def _test_stop_order(toolkit, diag: DiagResult) -> None:
    from parrot.finance.tools.ibkr_write import IBKRWriteError
    label = "place_stop_order"
    try:
        result = await toolkit.place_stop_order(
            symbol=SYMBOL,
            sec_type="STK",
            exchange="SMART",
            currency="USD",
            action="BUY",
            quantity=QTY,
            stop_price=STOP_PRICE,
            tif="DAY",
        )
        logger.info("Stop order result:\n%s", _pp(result))
        order_id = result.get("order_id")
        if order_id is not None:
            diag.record(label, True, f"order_id={order_id}")
            if not _is_dry_run(toolkit):
                await _test_cancel_order(toolkit, diag, order_id, label="cancel_stop_order")
        else:
            diag.record(label, False, "no order_id in result")
    except IBKRWriteError as exc:
        diag.record(label, False, str(exc))


async def _test_bracket_order(toolkit, diag: DiagResult) -> None:
    from parrot.finance.tools.ibkr_write import IBKRWriteError
    label = "place_bracket_order"
    try:
        result = await toolkit.place_bracket_order(
            symbol=SYMBOL,
            sec_type="STK",
            exchange="SMART",
            currency="USD",
            action="BUY",
            quantity=QTY,
            limit_price=LIMIT_PRICE,
            take_profit_price=TAKE_PROFIT_PRICE,
            stop_loss_price=STOP_LOSS_PRICE,
        )
        logger.info("Bracket order result:\n%s", _pp(result))
        parent_id = result.get("parent_id")
        if parent_id is not None:
            diag.record(label, True, f"parent_id={parent_id}")
            if not _is_dry_run(toolkit):
                # Cancel parent; TWS will cascade to legs
                await _test_cancel_order(
                    toolkit, diag, parent_id, label="cancel_bracket_order"
                )
        else:
            diag.record(label, False, "no parent_id in result")
    except IBKRWriteError as exc:
        diag.record(label, False, str(exc))


async def _test_cancel_order(
    toolkit, diag: DiagResult, order_id: Any, label: str = "cancel_order"
) -> None:
    from parrot.finance.tools.ibkr_write import IBKRWriteError
    try:
        result = await toolkit.cancel_order(order_id=int(order_id))
        logger.info("Cancel result:\n%s", _pp(result))
        diag.record(label, result.get("cancelled", False), f"order_id={order_id}")
    except IBKRWriteError as exc:
        # Non-fatal for clean-up steps — paper orders may already be gone
        diag.record(label, False, f"(non-fatal) {exc}")


async def _test_market_data(toolkit, diag: DiagResult) -> None:
    from parrot.finance.tools.ibkr_write import IBKRWriteError
    label = "request_market_data"
    try:
        result = await toolkit.request_market_data(
            symbol=SYMBOL, sec_type="STK", exchange="SMART", currency="USD"
        )
        logger.info("Market data:\n%s", _pp(result))
        diag.record(label, True, f"bid={result.get('bid')} ask={result.get('ask')}")
    except IBKRWriteError as exc:
        diag.record(label, False, str(exc))


def _is_dry_run(toolkit) -> bool:
    from parrot.finance.paper_trading import ExecutionMode
    return toolkit._execution_mode == ExecutionMode.DRY_RUN


# ---------------------------------------------------------------------------
# Main diagnostic runner
# ---------------------------------------------------------------------------

async def run_diag(paper: bool, port: int, client_id: int) -> int:
    from parrot.finance.tools.ibkr_write import IBKRWriteToolkit
    from parrot.finance.paper_trading import ExecutionMode

    mode = ExecutionMode.PAPER if paper else ExecutionMode.DRY_RUN

    # Apply env overrides so navconfig picks them up
    os.environ["IBKR_PORT"] = str(port)
    os.environ["IBKR_CLIENT_ID"] = str(client_id)

    diag = DiagResult()

    print("=" * 60)
    print(f"IBKR Toolkit Diagnostic  —  mode={mode.value}")
    if paper:
        host = os.environ.get("IBKR_HOST", "127.0.0.1")
        print(f"Target: {host}:{port}  clientId={client_id}")
    print("=" * 60)

    toolkit = IBKRWriteToolkit(mode=mode)

    try:
        # ── 1. Connectivity / account ────────────────────────────────────
        print("\n--- [1] Account & Positions ---")
        await _test_account_summary(toolkit, diag)
        await _test_get_positions(toolkit, diag)

        # ── 2. Market data (paper only — requires market data subscription)
        if paper:
            print("\n--- [2] Market Data Snapshot ---")
            await _test_market_data(toolkit, diag)

        # ── 3. Order types ───────────────────────────────────────────────
        print("\n--- [3] Order Placement ---")
        await _test_limit_order(toolkit, diag, cancel=True)
        await _test_stop_order(toolkit, diag)
        await _test_bracket_order(toolkit, diag)

    finally:
        toolkit.disconnect()

    return diag.summary()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose IBKRWriteToolkit directly (no agent/executor).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        help="Run against real IB Gateway/TWS in PAPER mode (default: DRY_RUN).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("IBKR_PORT", 4002)),
        help="TWS/Gateway port (default: 4002 for IB Gateway paper).",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=int(os.environ.get("IBKR_CLIENT_ID", 99)),
        dest="client_id",
        help="IBKR client ID (default: 99).",
    )
    args = parser.parse_args()

    if args.paper:
        print(
            "\nNOTE: PAPER mode requires IB Gateway or TWS running and accepting "
            f"connections on port {args.port}.\n"
            "Make sure 'Enable ActiveX and Socket Clients' is checked in TWS/Gateway settings.\n"
        )

    exit_code = asyncio.run(run_diag(args.paper, args.port, args.client_id))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
