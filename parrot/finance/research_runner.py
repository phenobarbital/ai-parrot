"""Research-only runner for the Finance module.

Runs layers 1–4 (Research → Analysts → CIO → Secretary) and produces
an ``InvestmentMemoOutput`` **without** executing any trades.

Optionally sends the resulting memo to Telegram when
``send_telegram=True``.

Usage::

    # Programmatic
    from parrot.finance.research_runner import run_research_only
    memo = await run_research_only(send_telegram=True)

    # CLI
    python -m parrot.finance.research_runner
    python -m parrot.finance.research_runner --telegram
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from navconfig import config

logger = logging.getLogger("parrot.finance.research_runner")


async def run_research_only(
    *,
    redis_url: str | None = None,
    send_telegram: bool = False,
    telegram_chat_id: str | int | None = None,
) -> Any:
    """Execute the research + deliberation pipeline (no execution).

    Steps:
        1. Boot BotManager with research, analyst, and deliberation agents.
        2. Start ``FinanceResearchService`` to trigger all crews.
        3. Wait for briefings to populate.
        4. Run ``CommitteeDeliberation.run_deliberation()`` which executes
           cross-pollination → CIO rounds → secretary memo.
        5. Optionally send the memo to Telegram.

    Args:
        redis_url: Redis connection string.  Falls back to
            ``REDIS_URL`` env var then ``redis://localhost:6379``.
        send_telegram: If ``True``, send the memo via Telegram.
        telegram_chat_id: Override target chat. Falls back to
            ``FINANCE_TELEGRAM_DESTINATION`` env var.

    Returns:
        The ``InvestmentMemoOutput`` produced by the secretary.
    """
    # Late imports to avoid heavy startup cost when module is just imported.
    from parrot.manager import BotManager  # noqa: C0415
    from parrot.finance.agents import (  # noqa: C0415
        create_all_research_crews,
        create_all_analysts,
        create_cio,
        create_secretary,
    )
    from parrot.finance.research import (  # noqa: C0415
        FinanceResearchService,
    )
    from parrot.finance.swarm import CommitteeDeliberation  # noqa: C0415
    from parrot.finance.schemas import (  # noqa: C0415
        ConsensusLevel,
        ExecutorConstraints,
        MessageBus,
        PortfolioSnapshot,
    )
    from parrot.bots import Agent  # noqa: C0415

    _redis_url = redis_url or config.get(
        "REDIS_URL", fallback="redis://localhost:6379",
    )

    # ── 1. Register only the agents needed for research ──────────
    bot_manager = BotManager()

    # Build agent groups separately — don't merge into one dict because
    # create_all_research_crews() and create_all_analysts() share keys
    # ("macro", "equity", …) which would overwrite each other.
    agent_groups: list[dict[str, Any]] = [
        create_all_research_crews(),
        create_all_analysts(),
        {"cio": create_cio(), "secretary": create_secretary()},
    ]
    count = 0
    for group in agent_groups:
        for agent in group.values():
            bot_manager.add_bot(agent)
            # Also register by agent_id so heartbeats/service can find them
            if hasattr(agent, "agent_id") and agent.agent_id:
                bot_manager._bots[agent.agent_id] = agent
            count += 1

    logger.info(
        "Registered %d agents (research-only mode, no executors)",
        count,
    )

    # ── 2. Start research service (heartbeats + tools) ───────────
    service = FinanceResearchService(
        bot_manager=bot_manager,
        redis_url=_redis_url,
    )
    await service.start()
    logger.info("FinanceResearchService started")

    try:
        # ── 3. Run research crews SEQUENTIALLY ────────────────────
        # Running crews in parallel exhausts both Gemini's token-per-
        # minute quota and external API rate limits (FRED, finnhub,
        # Alpaca, etc.).  Sequential execution is slower but reliable.
        from parrot.finance.research.briefing_store import ResearchBriefingStore
        import time  # noqa: C0415

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

            # Wait for THIS crew's briefing (max 120s per crew)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                latest = await store.get_latest_briefings()
                if latest.get(crew_id) is not None:
                    logger.info("  ✓ Briefing received for %s", crew_id)
                    break
                await asyncio.sleep(5)
            else:
                logger.warning(
                    "  ⚠ Timed out waiting for %s briefing — skipping",
                    crew_id,
                )

        # Final snapshot of all available briefings
        latest = await store.get_latest_briefings()

        # ── 4. Run deliberation ──────────────────────────────────
        briefings = {k: v for k, v in latest.items() if v is not None}

        # Default portfolio + constraints (research mode — no real positions)
        portfolio = PortfolioSnapshot(
            total_value_usd=10_000.0,
            cash_available_usd=10_000.0,
            exposure={},
            open_positions=[],
        )
        constraints = ExecutorConstraints(
            max_order_pct=2.0,
            max_order_value_usd=500.0,
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

        logger.info("Starting committee deliberation…")
        bus = MessageBus()
        committee = CommitteeDeliberation(
            message_bus=bus, agent_class=Agent,
        )
        await committee.configure()
        memo = await committee.run_deliberation(
            briefings=briefings,
            portfolio=portfolio,
            constraints=constraints,
        )

        logger.info("=" * 60)
        logger.info("RESEARCH CYCLE COMPLETE")
        logger.info("Memo ID: %s", memo.id)
        logger.info(
            "Recommendations: %d", len(memo.recommendations),
        )
        logger.info("=" * 60)

        # ── 5. Optionally send via Telegram ──────────────────────
        if send_telegram:
            from parrot.finance.telegram_notify import (  # noqa: C0415
                send_memo_to_telegram,
            )
            sent = await send_memo_to_telegram(
                memo, chat_id=telegram_chat_id,
            )
            if sent:
                logger.info("Memo sent to Telegram ✅")
            else:
                logger.warning("Telegram send failed — see logs above")

        return memo

    finally:
        await service.stop()
        logger.info("FinanceResearchService stopped")


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entrypoint."""
    import argparse  # noqa: C0415

    parser = argparse.ArgumentParser(
        description="Run the finance research pipeline (no execution).",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Send the resulting memo to Telegram.",
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        default=None,
        help="Override Telegram chat ID (default: FINANCE_TELEGRAM_DESTINATION).",
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default=None,
        help="Redis connection URL (default: REDIS_URL env or localhost).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(name)-40s │ %(levelname)-7s │ %(message)s",
    )

    asyncio.run(
        run_research_only(
            redis_url=args.redis_url,
            send_telegram=args.telegram,
            telegram_chat_id=args.chat_id,
        )
    )


if __name__ == "__main__":
    main()
