"""End-to-end finance demo — full cycle with mode selection.

Runs the complete pipeline in either DRY_RUN (local simulation) or
PAPER (real API calls to Alpaca paper-api / IBKR simulated port):

    1. Research     → FinanceResearchService runs all 5 crews
    2. Deliberation → CommitteeDeliberation (analysts → CIO → Secretary → memo)
    3. Dispatch     → memo_to_orders → ExecutionOrchestrator.process_orders
    4. Monitoring   → Portfolio check → final summary

Usage::

    # DRY_RUN (default — no API keys needed)
    python -m parrot.finance.demo_full_cycle --print

    # PAPER (real Alpaca paper API calls)
    python -m parrot.finance.demo_full_cycle --mode paper --print
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from navconfig import config


logger = logging.getLogger("parrot.finance.demo_full_cycle")


# ─────────────────────────────────────────────────────────────────────
# Result container
# ─────────────────────────────────────────────────────────────────────

@dataclass
class DemoResult:
    """Container for the full-cycle demo output."""

    memo: Any  # InvestmentMemoOutput
    orders: list[Any]  # list[TradingOrder]
    execution_reports: list[Any]  # list[ExecutionReportOutput]
    elapsed_seconds: float
    mode: str = "dry_run"


# ─────────────────────────────────────────────────────────────────────
# Investment Policy Statement — demo helper
# ─────────────────────────────────────────────────────────────────────

def _build_demo_ips(yaml_path: str | None = None) -> Any:
    """Build the demo Investment Policy Statement.

    Uses inline construction by default.  Pass ``yaml_path`` to load from
    a YAML file instead (e.g. ``examples/ips_sample.yaml``).

    Returns:
        ``InvestmentPolicyStatement`` instance, or ``None`` on failure.

    Example — inline construction (default)::

        ips = _build_demo_ips()

    Example — YAML loading::

        ips = _build_demo_ips("examples/ips_sample.yaml")

        # Or equivalently:
        # from parrot.finance.schemas import InvestmentPolicyStatement
        # ips = InvestmentPolicyStatement.from_yaml("examples/ips_sample.yaml")
    """
    from parrot.finance.schemas import InvestmentPolicyStatement  # noqa: C0415

    if yaml_path:
        try:
            return InvestmentPolicyStatement.from_yaml(yaml_path)
        except Exception as exc:
            logger.warning("Could not load IPS from %s: %s — using inline IPS", yaml_path, exc)

    # Inline construction — edit to reflect your actual investment policy
    return InvestmentPolicyStatement(
        # Watchlist — not the full universe; analysts should explore broadly beyond these
        preferred_tickers=[
            "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",   # mega-cap tech
            "JPM", "GS", "BAC",                           # financials
            "XLV", "JNJ", "UNH",                          # healthcare
            "SPY", "QQQ", "IWM",                          # broad ETFs
            "GLD", "TLT",                                  # macro hedges
            "BTC/USD", "ETH/USD", "SOL/USD",              # crypto
        ],
        blocked_tickers=["DOGE", "SHIB", "GME", "MEME"],
        preferred_sectors=["technology", "healthcare", "financials", "consumer_discretionary"],
        avoided_sectors=["tobacco"],
        max_single_stock_pct=5.0,
        prefer_etf_over_single=False,   # allow single stocks for more diversity
        default_time_horizon="swing",
        max_portfolio_beta=1.5,
        esg_filter=False,               # ESG was blocking all crypto; turned off
        recommendation_targets={
            "default": [5, 8],
            "macro_analyst": [5, 8],
            "equity_analyst": [6, 10],
            "crypto_analyst": [3, 6],
            "sentiment_analyst": [5, 8],
            "risk_analyst": [4, 7],
        },
        custom_directives=(
            "Prefer momentum plays over value.\n"
            "Avoid biotech pre-FDA approval events.\n"
            "Each analyst MUST reach their minimum recommendation target — "
            "include moderate-confidence picks rather than generating too few.\n"
            "Ensure SECTOR DIVERSITY: do not concentrate all equity recommendations "
            "in 2-3 tickers. Spread across tech, healthcare, financials, and "
            "other sectors.\n"
            "Crypto analyst MUST include at least 3 crypto recommendations (BTC, ETH, "
            "and at least one alt-coin or DeFi asset).\n"
            "Do not initiate new positions during earnings week without MAJORITY "
            "consensus (not UNANIMOUS — that was too restrictive).\n"
            "Preferred tickers are a WATCHLIST, not limits — explore the full market."
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# Portfolio defaults (same as research_runner)
# ─────────────────────────────────────────────────────────────────────

def _build_portfolio_inputs() -> tuple[Any, Any]:
    """Build default portfolio snapshot and constraints for the demo."""
    from parrot.finance.schemas import (
        ConsensusLevel,
        ExecutorConstraints,
        PortfolioSnapshot,
    )

    portfolio = PortfolioSnapshot(
        total_value_usd=10_000.0,
        cash_available_usd=10_000.0,
        exposure={"cash": 100.0},
        open_positions=[],
    )
    constraints = ExecutorConstraints(
        max_order_pct=5.0,
        max_order_value_usd=1000.0,
        allowed_order_types=["limit"],
        max_daily_trades=10,
        max_daily_volume_usd=2000.0,
        max_positions=10,
        max_exposure_pct=70.0,
        max_asset_class_exposure_pct=40.0,
        min_consensus=ConsensusLevel.MAJORITY,
        max_daily_loss_pct=5.0,
        max_drawdown_pct=15.0,
    )
    return portfolio, constraints


# ─────────────────────────────────────────────────────────────────────
# Toolkit builders for PAPER mode
# ─────────────────────────────────────────────────────────────────────

def _build_paper_stock_tools() -> list:
    """Create AlpacaWriteToolkit in PAPER mode for real paper API calls."""
    from parrot.finance.paper_trading.models import ExecutionMode
    from parrot.finance.tools.alpaca_write import AlpacaWriteToolkit

    toolkit = AlpacaWriteToolkit(mode=ExecutionMode.PAPER)
    logger.info(
        "AlpacaWriteToolkit created in PAPER mode "
        "(paper=%s, base_url=%s)",
        toolkit.paper, toolkit.base_url or "default",
    )
    return toolkit.get_tools()


def _build_paper_ibkr_tools() -> tuple | None:
    """Try to create IBKRWriteToolkit in PAPER mode.

    Returns a ``(toolkit, tools)`` tuple on success, or ``None`` if ibapi is
    not installed, the TWS/Gateway port is not open, or the ibapi handshake
    fails (nextValidId not received within 5 s).

    The caller is responsible for calling ``toolkit.disconnect()`` when done.
    """
    try:
        from ibapi.client import EClient  # noqa: F401
    except ImportError:
        logger.warning("ibapi not installed — skipping IBKR executor in PAPER mode")
        return None

    from parrot.finance.paper_trading.models import ExecutionMode
    from parrot.finance.tools.ibkr_write import IBKRWriteToolkit, IBKRWriteError

    toolkit = IBKRWriteToolkit(mode=ExecutionMode.PAPER)

    # Step 1: raw TCP reachability (fast fail before spending 5 s on ibapi)
    import socket as _socket
    try:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((toolkit.host, toolkit.port))
        sock.close()
        if result != 0:
            logger.warning(
                "IBKR TWS/Gateway not reachable at %s:%d (connect_ex=%d) — "
                "skipping IBKR executor. Start TWS in paper mode to enable.",
                toolkit.host, toolkit.port, result,
            )
            return None
    except Exception as exc:
        logger.warning("IBKR TCP connectivity check failed: %s", exc)
        return None

    # Step 2: ibapi handshake — verify nextValidId is received
    # This catches cases where the port is open but the ibapi session fails
    # (wrong client ID already in use, API not enabled in TWS settings, etc.)
    try:
        toolkit._ensure_connected()
        logger.info(
            "IBKRWriteToolkit PAPER mode connected — nextValidId=%d (host=%s, port=%d)",
            toolkit._bridge._next_order_id if toolkit._bridge else -1,
            toolkit.host, toolkit.port,
        )
    except IBKRWriteError as exc:
        logger.warning(
            "IBKR ibapi handshake failed at %s:%d — skipping IBKR executor. "
            "Error: %s. Check that API connections are enabled in TWS settings "
            "and client_id=%d is not already in use.",
            toolkit.host, toolkit.port, exc, toolkit.client_id,
        )
        return None

    return toolkit, toolkit.get_tools()


# ─────────────────────────────────────────────────────────────────────
# Summary formatter
# ─────────────────────────────────────────────────────────────────────

def format_execution_summary(result: DemoResult) -> str:
    """Format a human-readable summary of the demo run."""
    lines: list[str] = []
    memo = result.memo
    mode_label = result.mode.upper()

    lines.append("=" * 70)
    lines.append(f"🏦  FINANCE FULL-CYCLE DEMO — SUMMARY [{mode_label}]")
    lines.append("=" * 70)

    # ── Memo ──
    lines.append("")
    lines.append(f"📋 Memo ID: {memo.id}")
    lines.append(f"   Created: {memo.created_at}")
    lines.append(f"   Valid until: {memo.valid_until}")
    lines.append(f"   Consensus: {memo.final_consensus}")
    lines.append(f"   Deliberation rounds: {memo.deliberation_rounds}")

    # ── Recommendations ──
    lines.append("")
    lines.append(f"📊 Recommendations ({len(memo.recommendations)}):")
    for i, rec in enumerate(memo.recommendations, 1):
        signal_emoji = {
            "BUY": "🟢", "SELL": "🔴", "HOLD": "🟡",
            "SHORT": "🔻", "COVER": "🔺",
        }.get(rec.signal.upper() if hasattr(rec.signal, "upper") else str(rec.signal), "⚪")
        lines.append(
            f"   {i}. {signal_emoji} {rec.asset} ({rec.asset_class}) "
            f"— {rec.signal} {rec.action} | "
            f"Size: {rec.sizing_pct:.1f}% | "
            f"Consensus: {rec.consensus_level}"
        )

    # ── Orders ──
    lines.append("")
    lines.append(f"📦 Orders generated: {len(result.orders)}")
    for order in result.orders:
        lines.append(
            f"   • {order.action} {order.asset} "
            f"qty={order.quantity or '?'} "
            f"limit={order.limit_price or '?'} "
            f"status={order.status.value if hasattr(order.status, 'value') else order.status}"
        )

    # ── Execution Reports ──
    lines.append("")
    lines.append(f"⚡ Execution Reports ({len(result.execution_reports)}):")
    for report in result.execution_reports:
        details = report.execution_details
        mode_tag = f"[{report.execution_mode}]" if report.execution_mode else ""
        sim_tag = " (simulated)" if report.is_simulated else " (LIVE API)"
        lines.append(
            f"   • {details.symbol}: {report.action_taken} "
            f"{details.side} {details.quantity}x @ "
            f"{details.fill_price or details.limit_price or '?'} "
            f"→ {details.status} on {report.platform} "
            f"{mode_tag}{sim_tag}"
        )
        if report.portfolio_after:
            pa = report.portfolio_after
            lines.append(
                f"     Portfolio after: cash=${pa.cash_remaining_usd:,.2f}"
            )

    # ── Risk warnings ──
    if memo.risk_warnings:
        lines.append("")
        lines.append("⚠️  Risk Warnings:")
        for w in memo.risk_warnings:
            lines.append(f"   • {w}")

    # ── Footer ──
    lines.append("")
    lines.append("─" * 70)
    lines.append(f"⏱  Total elapsed: {result.elapsed_seconds:.1f}s")
    lines.append(f"🔧 Mode: {mode_label}")
    lines.append("=" * 70)

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Main demo
# ─────────────────────────────────────────────────────────────────────

async def run_demo(
    *,
    mode: str = "dry_run",
    redis_url: str | None = None,
    ips: Any | None = None,
    ips_yaml: str | None = None,
) -> DemoResult:
    """Execute the full finance pipeline.

    Args:
        mode: Execution mode — ``"dry_run"`` for local simulation (no
            API keys needed), or ``"paper"`` for real Alpaca paper-API
            calls and optionally IBKR simulated port (7497).
        redis_url: Redis connection string. Falls back to
            ``REDIS_URL`` env var then ``redis://localhost:6379``.
        ips: Pre-built ``InvestmentPolicyStatement`` to inject into
            every analyst and CIO prompt.  When ``None`` (default),
            ``_build_demo_ips(ips_yaml)`` is called automatically so
            the demo always runs with an illustrative policy.
        ips_yaml: Optional path to a YAML file to load the IPS from.
            Ignored when ``ips`` is provided directly.

    Returns:
        DemoResult with the full pipeline output.
    """
    from parrot.bots import Agent
    from parrot.finance.agents import create_all_research_crews
    from parrot.finance.execution import ExecutionOrchestrator
    from parrot.finance.paper_trading.models import (
        ExecutionMode,
        PaperTradingConfig,
    )
    from parrot.finance.research import FinanceResearchService
    from parrot.finance.research.briefing_store import ResearchBriefingStore
    from parrot.finance.schemas import MessageBus
    from parrot.finance.swarm import CommitteeDeliberation, memo_to_orders
    from parrot.manager import BotManager

    # Resolve mode
    exec_mode = (
        ExecutionMode.PAPER if mode == "paper"
        else ExecutionMode.DRY_RUN
    )

    # Resolve IPS — always use an illustrative policy so the demo shows the feature
    _ips = ips if ips is not None else _build_demo_ips(ips_yaml)
    if _ips is not None:
        logger.info("Investment Policy Statement loaded (%d custom_directives chars)",
                    len(_ips.custom_directives))

    t0 = time.monotonic()
    _redis_url = redis_url or config.get(
        "REDIS_URL", fallback="redis://localhost:6379",
    )

    logger.info("=" * 60)
    logger.info("DEMO FULL CYCLE — mode=%s", exec_mode.value)
    logger.info("=" * 60)

    # ── 1. Register research agents ──────────────────────────────
    bot_manager = BotManager()
    agent_groups: list[dict[str, Any]] = [
        create_all_research_crews(),
    ]
    count = 0
    for group in agent_groups:
        for agent in group.values():
            bot_manager.add_bot(agent)
            if hasattr(agent, "agent_id") and agent.agent_id:
                bot_manager._bots[agent.agent_id] = agent
            count += 1

    logger.info(
        "Registered %d research agents for demo", count,
    )

    # ── 2. Start research service and run crews ──────────────────
    service = FinanceResearchService(
        bot_manager=bot_manager,
        redis_url=_redis_url,
        heartbeats=[],
    )
    await service.start()
    service_running = True
    logger.info("FinanceResearchService started")

    try:
        store = service.briefing_store
        crew_ids = ResearchBriefingStore.ALL_CREW_IDS
        logger.info(
            "Running %d research crews sequentially: %s",
            len(crew_ids), crew_ids,
        )

        for idx, crew_id in enumerate(crew_ids, 1):
            logger.info(
                "── Crew %d/%d: %s ──────────────────────────",
                idx, len(crew_ids), crew_id,
            )
            task_id = await service.trigger_crew(crew_id)
            logger.info("  Submitted task %s", task_id)

            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                briefing = await store.get_latest_briefing(crew_id)
                if briefing is not None:
                    logger.info(
                        "  ✓ Briefing received for %s (%d items)",
                        crew_id,
                        len(briefing.research_items),
                    )
                    break
                await asyncio.sleep(5)
            else:
                logger.warning(
                    "  ⚠ Timed out waiting for %s — skipping", crew_id,
                )

        latest_by_domain = await store.get_latest_briefings()
        await service.stop()
        service_running = False
        logger.info("Research phase complete, service stopped")

        # ── 3. Run deliberation ──────────────────────────────────
        domain_to_analyst = {
            "macro": "macro_analyst",
            "equity": "equity_analyst",
            "crypto": "crypto_analyst",
            "sentiment": "sentiment_analyst",
            "risk": "risk_analyst",
        }
        briefings = {
            analyst_id: latest_by_domain[domain]
            for domain, analyst_id in domain_to_analyst.items()
            if latest_by_domain.get(domain) is not None
        }

        portfolio, constraints = await asyncio.to_thread(
            _build_portfolio_inputs,
        )

        logger.info("Starting committee deliberation…")
        bus = MessageBus()
        committee = CommitteeDeliberation(
            message_bus=bus, agent_class=Agent, ips=_ips,
        )
        await committee.configure()
        memo = await committee.run_deliberation(
            briefings=briefings,
            portfolio=portfolio,
            constraints=constraints,
        )

        logger.info("=" * 60)
        logger.info("DELIBERATION COMPLETE — Memo: %s", memo.id)
        logger.info("Recommendations: %d", len(memo.recommendations))
        logger.info("=" * 60)

        # ── 4. Convert memo → orders ─────────────────────────────
        orders = memo_to_orders(memo)
        logger.info("Generated %d orders from memo", len(orders))

        if not orders:
            logger.info(
                "No actionable orders — pipeline complete "
                "(all recs may be HOLD or below consensus threshold)."
            )
            return DemoResult(
                memo=memo,
                orders=[],
                execution_reports=[],
                elapsed_seconds=time.monotonic() - t0,
                mode=exec_mode.value,
            )

        # ── 5. Configure execution mode ──────────────────────────
        paper_config = PaperTradingConfig(mode=exec_mode)

        # Build toolkit kwargs based on mode
        toolkit_kwargs: dict[str, Any] = {}
        _ibkr_toolkit = None  # kept for cleanup in finally

        if exec_mode == ExecutionMode.PAPER:
            # PAPER mode: real API calls via toolkits
            paper_config = PaperTradingConfig(
                mode=ExecutionMode.PAPER,
                # No slippage simulation — real fills from Alpaca
                simulate_slippage_bps=0,
                simulate_fill_delay_ms=0,
            )

            logger.info("Building PAPER-mode toolkits…")

            # Alpaca stock tools (real paper API)
            stock_tools = _build_paper_stock_tools()
            toolkit_kwargs["stock_tools"] = stock_tools
            logger.info(
                "  ✓ Alpaca stock tools: %d tools registered",
                len(stock_tools),
            )

            # IBKR tools (optional — requires TWS running)
            ibkr_result = _build_paper_ibkr_tools()
            if ibkr_result is not None:
                _ibkr_toolkit, ibkr_tools = ibkr_result
                toolkit_kwargs["ibkr_tools"] = ibkr_tools
                logger.info(
                    "  ✓ IBKR tools: %d tools registered",
                    len(ibkr_tools),
                )
            else:
                logger.info(
                    "  ⚠ IBKR skipped — no gateway running"
                )

        else:
            # DRY_RUN mode: local VirtualPortfolio simulation
            paper_config = PaperTradingConfig(
                mode=ExecutionMode.DRY_RUN,
                simulate_slippage_bps=5,
                simulate_fill_delay_ms=100,
            )

        # ── 6. Execute orders ────────────────────────────────────
        exec_bus = MessageBus()
        orchestrator = ExecutionOrchestrator(
            message_bus=exec_bus,
            agent_class=Agent,
            paper_config=paper_config,
            **toolkit_kwargs,
        )
        await orchestrator.configure()

        logger.info(
            "ExecutionOrchestrator configured in %s mode",
            paper_config.mode.value,
        )

        reports = await orchestrator.process_orders(orders, portfolio)

        logger.info("=" * 60)
        logger.info("EXECUTION COMPLETE — %d reports", len(reports))
        logger.info("=" * 60)

        # ── 7. Persist memo if store is available ────────────────
        if orchestrator.memo_store:
            from parrot.finance.schemas import InvestmentMemo
            try:
                full_memo = InvestmentMemo(
                    id=memo.id,
                    executive_summary=memo.executive_summary,
                    recommendations=[],
                    final_consensus=memo.final_consensus,
                )
                await orchestrator._persist_memo(full_memo)
                logger.info("Memo persisted to store")
            except Exception as e:
                logger.warning("Could not persist memo: %s", e)

        result = DemoResult(
            memo=memo,
            orders=orders,
            execution_reports=reports,
            elapsed_seconds=time.monotonic() - t0,
            mode=exec_mode.value,
        )
        return result

    finally:
        if "service_running" in locals() and service_running:
            await service.stop()
            logger.info("FinanceResearchService stopped (cleanup)")
        # Disconnect IBKR so the reader thread exits cleanly before process shutdown.
        # Without this, the daemon thread keeps spinning on socket timeouts and can
        # hang interpreter teardown (logging lock contention during daemon shutdown).
        if "_ibkr_toolkit" in locals() and _ibkr_toolkit is not None:
            try:
                _ibkr_toolkit.disconnect()
                logger.info("IBKR toolkit disconnected (cleanup)")
            except Exception as exc:
                logger.debug("IBKR disconnect error (ignored): %s", exc)


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entrypoint for the full-cycle demo."""
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Run the complete finance pipeline: "
            "research → deliberation → execution → summary."
        ),
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["dry_run", "paper"],
        default="dry_run",
        help=(
            "Execution mode. 'dry_run' (default) uses local simulation. "
            "'paper' sends real orders to Alpaca paper-API / IBKR sim port."
        ),
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default=None,
        help="Redis connection URL (default: REDIS_URL env or localhost).",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_summary",
        help="Print the execution summary to stdout.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write summary to a file (e.g., demo_output.md).",
    )
    parser.add_argument(
        "--ips-file",
        type=str,
        default=None,
        dest="ips_file",
        help=(
            "Path to a YAML file defining the Investment Policy Statement. "
            "Defaults to the built-in illustrative IPS when omitted. "
            "Example: examples/ips_sample.yaml"
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(name)-42s │ %(levelname)-7s │ %(message)s",
    )

    result = asyncio.run(
        run_demo(mode=args.mode, redis_url=args.redis_url, ips_yaml=args.ips_file),
    )

    summary = format_execution_summary(result)

    # Always print summary when --print is set or when running as CLI
    if args.print_summary or not args.output:
        print("\n" + summary)

    if args.output:
        with open(args.output, "w") as f:
            f.write(summary)
        logger.info("Summary written to %s", args.output)


if __name__ == "__main__":
    main()
