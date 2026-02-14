"""Main entrypoint — boot the autonomous trading research system.

Orchestrates startup of:
    1. BotManager with all finance agents
    2. FinanceResearchService (heartbeat-driven research crews)
    3. ResearchBriefingStore (Redis persistence + pub/sub)
    4. DeliberationTrigger (monitors briefings → fires pipeline)

The execution layer is **mocked with logging** — no real trades are
placed.  Replace ``_mock_pipeline_factory`` with
``_default_pipeline_factory`` from ``trigger.py`` for production use.

Usage::

    python -m parrot.finance.main
"""
from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from navconfig import config

logger = logging.getLogger("parrot.finance.main")


# ─────────────────────────────────────────────────────────────────────
# Mocked execution layer
# ─────────────────────────────────────────────────────────────────────

async def _mock_pipeline_factory(
    briefings: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Log what would happen instead of executing real trades.

    Drop-in replacement for ``_default_pipeline_factory`` during
    development and testing.
    """
    crew_ids = list(briefings.keys())
    logger.info(
        "🧪 [MOCK] Pipeline triggered with %d briefings: %s",
        len(crew_ids),
        crew_ids,
    )
    for crew_id, briefing in briefings.items():
        summary = (
            briefing.summary[:120] if hasattr(briefing, "summary") else str(briefing)[:120]
        )
        logger.info("  📋 %s → %s…", crew_id, summary)

    logger.info(
        "🧪 [MOCK] Pipeline complete — no orders placed (mock mode)."
    )
    return {
        "memo": None,
        "orders": [],
        "reports": [],
        "pipeline_status": "mock_completed",
    }


# ─────────────────────────────────────────────────────────────────────
# Boot function
# ─────────────────────────────────────────────────────────────────────

async def boot_trading_system(
    redis_url: str | None = None,
    mode: str = "quorum",
) -> None:
    """Initialise and run the full autonomous research + trading loop.

    Args:
        redis_url: Redis connection string (falls back to ``REDIS_URL``
            env var or ``redis://localhost:6379``).
        mode: Deliberation trigger mode — one of ``quorum``,
            ``all_fresh``, ``scheduled``, ``manual``.
    """
    from parrot.manager import BotManager  # noqa: C0415
    from parrot.finance.agents import create_all_agents  # noqa: C0415
    from parrot.finance.research import (  # noqa: C0415
        FinanceResearchService,
        ResearchBriefingStore,
        DeliberationTrigger,
    )

    _redis_url = redis_url or config.get(
        "REDIS_URL", fallback="redis://localhost:6379",
    )

    # ── 1. Create agents ─────────────────────────────────────────
    bot_manager = BotManager()
    layers = create_all_agents()
    count = 0
    for _layer_name, agents in layers.items():
        for _key, agent in agents.items():
            bot_manager.add_bot(agent)
            # Also register by agent_id so heartbeats can find them
            if hasattr(agent, "agent_id") and agent.agent_id:
                bot_manager._bots[agent.agent_id] = agent
            count += 1
    logger.info(
        "Registered %d agents in BotManager", count,
    )

    # ── 2. Start research service ────────────────────────────────
    service = FinanceResearchService(
        bot_manager=bot_manager,
        redis_url=_redis_url,
    )
    await service.start()
    logger.info("FinanceResearchService started")

    # ── 3. Briefing store (shares Redis from service) ────────────
    briefing_store = service.briefing_store
    if briefing_store is None:
        import redis.asyncio as aioredis  # noqa: C0415
        _redis = aioredis.from_url(_redis_url)
        briefing_store = ResearchBriefingStore(redis=_redis)
        logger.warning(
            "Service briefing_store was None — created standalone instance",
        )

    # ── 4. Deliberation trigger (mocked pipeline) ────────────────
    trigger = DeliberationTrigger(
        briefing_store=briefing_store,
        pipeline_factory=_mock_pipeline_factory,
        mode=mode,
        redis=_redis if briefing_store is None else None,  # Only create if not shared
    )
    logger.info(
        "DeliberationTrigger ready (mode=%s, pipeline=MOCK)", mode,
    )

    # ── 5. Subscribe trigger to briefing updates ─────────────────
    if hasattr(briefing_store, "subscribe"):
        await briefing_store.subscribe(
            "briefings:updated", trigger.on_briefing_updated,
        )
        logger.info("Subscribed trigger to briefings:updated")

    # ── 6. Run until shutdown signal ─────────────────────────────
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received — stopping…")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    logger.info("🚀 Autonomous trading system running (Ctrl-C to stop)")
    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down…")
        await service.stop()
        logger.info("✅ Shutdown complete")


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(name)-35s │ %(levelname)-7s │ %(message)s",
    )
    asyncio.run(boot_trading_system())
