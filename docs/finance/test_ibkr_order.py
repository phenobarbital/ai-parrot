"""Standalone IBKR paper-trading order test.

Demonstrates that IBKRWriteToolkit can place a real order via TWS/IB Gateway
without going through the full agent pipeline.

Usage::

    # With IB Gateway paper trading on port 4004 (default):
    source .venv/bin/activate
    python docs/finance/test_ibkr_order.py

    # Override port / client ID:
    IBKR_PORT=7497 IBKR_CLIENT_ID=99 python docs/finance/test_ibkr_order.py

    # DRY_RUN mode (no TWS needed — uses VirtualPortfolio):
    python docs/finance/test_ibkr_order.py --dry-run

Environment variables (all optional):
    IBKR_HOST       TWS/Gateway host (default: 127.0.0.1)
    IBKR_PORT       Port (default: 4004 for PAPER, 7496 for LIVE)
    IBKR_CLIENT_ID  Client ID (default: 99)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so this script can be run directly
# from the repo without installing the package.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Logging — configure before any imports that use loggers
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-35s | %(levelname)-7s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("test_ibkr_order")


# ---------------------------------------------------------------------------
# Test parameters — edit these to match your paper trading account / symbols
# ---------------------------------------------------------------------------
TEST_SYMBOL = "AAPL"
TEST_QUANTITY = 1          # 1 share
# Price well below market so the order stays open (won't accidentally fill)
TEST_LIMIT_PRICE = 1.00    # $1.00 limit buy — safe for paper account

# IB Gateway paper trading default; override via IBKR_PORT env var
DEFAULT_PAPER_PORT = 4004
DEFAULT_CLIENT_ID = 99


def _pretty(data: dict) -> str:
    return json.dumps(data, indent=2, default=str)


async def run_test(dry_run: bool = False) -> int:
    """Execute the IBKR order test.

    Returns:
        0 on success, 1 on failure.
    """
    from parrot.finance.tools.ibkr_write import IBKRWriteToolkit, IBKRWriteError
    from parrot.finance.paper_trading import ExecutionMode

    # ------------------------------------------------------------------
    # Override defaults so the script works without any .env file.
    # Values set here are only applied when the env var is not already set.
    # ------------------------------------------------------------------
    os.environ.setdefault("IBKR_PORT", str(DEFAULT_PAPER_PORT))
    os.environ.setdefault("IBKR_CLIENT_ID", str(DEFAULT_CLIENT_ID))

    mode = ExecutionMode.DRY_RUN if dry_run else ExecutionMode.PAPER

    logger.info("=" * 60)
    logger.info("IBKR Order Test  —  mode=%s", mode.value)
    if not dry_run:
        host = os.environ.get("IBKR_HOST", "127.0.0.1")
        port = int(os.environ.get("IBKR_PORT", DEFAULT_PAPER_PORT))
        cid = int(os.environ.get("IBKR_CLIENT_ID", DEFAULT_CLIENT_ID))
        logger.info("Target: %s:%d  clientId=%d", host, port, cid)
    logger.info("=" * 60)

    toolkit = IBKRWriteToolkit(mode=mode)
    success = False

    try:
        # ── Step 1: Account summary (verifies connectivity) ──────────────
        logger.info("[1/3] Requesting account summary...")
        try:
            account = await toolkit.get_account_summary()
            logger.info("Account summary received:")
            print(_pretty(account))
        except IBKRWriteError as exc:
            logger.error("Account summary failed: %s", exc)
            return 1

        # ── Step 2: Place a limit BUY order ──────────────────────────────
        logger.info(
            "[2/3] Placing limit BUY order: %d x %s @ $%.2f",
            TEST_QUANTITY, TEST_SYMBOL, TEST_LIMIT_PRICE,
        )
        try:
            result = await toolkit.place_limit_order(
                symbol=TEST_SYMBOL,
                sec_type="STK",
                exchange="SMART",
                currency="USD",
                action="BUY",
                quantity=TEST_QUANTITY,
                limit_price=TEST_LIMIT_PRICE,
                tif="DAY",
            )
            logger.info("Order result:")
            print(_pretty(result))

            order_id = result.get("order_id")
            status = result.get("status", "unknown")
            logger.info("Order ID: %s  |  Status: %s", order_id, status)

            # Success if we got a usable order ID back
            if order_id is not None:
                success = True
            else:
                logger.warning("No order_id in result — order may not have been submitted.")

        except IBKRWriteError as exc:
            logger.error("Order placement failed: %s", exc)
            return 1

        # ── Step 3: Cancel the order (clean up paper account) ────────────
        if success and order_id is not None and not dry_run:
            logger.info("[3/3] Cancelling order %s to keep paper account clean...", order_id)
            try:
                cancel_result = await toolkit.cancel_order(order_id=order_id)
                logger.info("Cancel result: %s", cancel_result)
            except IBKRWriteError as exc:
                # Non-fatal — order may have already expired
                logger.warning("Cancel failed (non-fatal): %s", exc)
        elif dry_run:
            logger.info("[3/3] DRY_RUN — skipping cancel (VirtualPortfolio).")

    finally:
        toolkit.disconnect()

    if success:
        logger.info("=" * 60)
        logger.info("TEST PASSED — order submitted successfully via IBKRWriteToolkit")
        logger.info("=" * 60)
        return 0
    else:
        logger.error("=" * 60)
        logger.error("TEST FAILED — see errors above")
        logger.error("=" * 60)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Standalone IBKR paper trading order test.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use DRY_RUN mode (VirtualPortfolio, no TWS connection needed).",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(run_test(dry_run=args.dry_run))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
