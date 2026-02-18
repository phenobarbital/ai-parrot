"""
Finance Research Service
=========================

AgentService subclass specialised for autonomous financial research.

Responsibilities:
    1. Register all 5 research crews as heartbeat-driven tasks
    2. Attach domain-specific tools to each crew agent
    3. Intercept crew output → parse → store as ResearchBriefing
    4. Publish ``briefings:updated`` events for downstream consumers

Heartbeat schedules (cron expressions, UTC):
    - macro_crew:      ``0 6,12,18 * * *``    → 3×/day (06:00, 12:00, 18:00)
    - equity_crew:     ``0 7,13 * * 1-5``     → 2×/day weekdays (07:00, 13:00)
    - crypto_crew:     ``0 */4 * * *``         → every 4 hours, 24/7
    - sentiment_crew:  ``0 */6 * * *``         → every 6 hours, 24/7
    - risk_crew:       ``0 8,14,20 * * *``     → 3×/day (08:00, 14:00, 20:00)

Integration::

    from parrot.finance.research import FinanceResearchService

    service = FinanceResearchService(bot_manager=bot_manager)
    await service.start()    # starts heartbeats + tool setup
    # ... runs until stop()
    await service.stop()

The service overrides ``_process_task`` to intercept research crew
results and route them through the ``ResearchOutputParser`` →
``ResearchBriefingStore`` pipeline before standard delivery.
"""
from __future__ import annotations
from typing import Any, Optional, TYPE_CHECKING
import time
from navconfig import config
from navconfig.logging import logging
from parrot.services import (
    AgentService,
    AgentServiceConfig,
    AgentTask,
    DeliveryChannel,
    DeliveryConfig,
    HeartbeatConfig,
    TaskPriority,
    TaskResult,
    TaskStatus,
)
from .briefing_store import ResearchBriefingStore, ResearchOutputParser

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from parrot.manager import BotManager


logger = logging.getLogger("parrot.finance.research.service")


# =============================================================================
# PROMPTS — What each crew is asked to do on each heartbeat
# =============================================================================
# These complement the system_prompt already set on the crew agents.
# They are passed as the ``prompt`` parameter to agent.ask().

MACRO_HEARTBEAT_PROMPT = """\
Execute your scheduled macroeconomic data collection cycle.

1. Query FRED for the latest values of your assigned series
   (Fed Funds, 10Y/2Y Treasury, CPI, PCE, unemployment, VIX, DXY, M2).
2. Check for any upcoming economic events in the next 7 days.
3. Summarise your findings as a JSON array per your output format.

Focus on changes since your last collection. Flag any significant
moves (>1σ from recent average) or upcoming high-importance releases.
"""

EQUITY_HEARTBEAT_PROMPT = """\
Execute your scheduled equity and ETF data collection cycle.

1. Fetch current quotes and daily performance for the focus universe:
   SPY, QQQ, IWM, XLF, XLK, XLE, TLT, GLD.
2. Check earnings calendar for the next 7 days.
3. Scan for significant price movements (>3% daily) in S&P 500 components.
4. Check sector performance and rotation signals.
5. Summarise your findings as a JSON array per your output format.
"""

CRYPTO_HEARTBEAT_PROMPT = """\
Execute your scheduled cryptocurrency data collection cycle.

1. Fetch current prices, 24h volume, and market cap for:
   BTC, ETH, SOL, AVAX, LINK, DOT, MATIC.
2. Check BTC dominance and total crypto market cap trend.
3. Fetch funding rates for BTC and ETH perpetuals.
4. Check DeFi TVL changes and stablecoin supply.
5. Monitor exchange inflows/outflows if available.
6. Summarise your findings as a JSON array per your output format.
"""

SENTIMENT_HEARTBEAT_PROMPT = """\
Execute your scheduled sentiment data collection cycle.

1. Fetch the current Crypto Fear & Greed Index.
2. Scan financial news for the top stories affecting markets.
3. Check for any extreme sentiment readings across indicators.
4. Note any significant shift in narrative or trending topics.
5. Summarise your findings as a JSON array per your output format.
"""

RISK_HEARTBEAT_PROMPT = """\
Execute your scheduled risk metrics collection cycle.

1. Fetch current VIX level and Financial Stress Index from FRED.
2. Check yield curve status (10Y-2Y spread).
3. Assess current portfolio exposure levels and concentration.
4. Calculate cross-asset correlations for recent period.
5. Flag any threshold breaches per risk framework.
6. Summarise your findings as a JSON array per your output format.
"""

CREW_PROMPTS: dict[str, str] = {
    "research_crew_macro": MACRO_HEARTBEAT_PROMPT,
    "research_crew_equity": EQUITY_HEARTBEAT_PROMPT,
    "research_crew_crypto": CRYPTO_HEARTBEAT_PROMPT,
    "research_crew_sentiment": SENTIMENT_HEARTBEAT_PROMPT,
    "research_crew_risk": RISK_HEARTBEAT_PROMPT,
}

# =============================================================================
# CREW SCHEDULE CONFIGURATION
# =============================================================================

DEFAULT_HEARTBEATS: list[HeartbeatConfig] = [
    HeartbeatConfig(
        agent_name="research_crew_macro",
        cron_expression="0 6,12,18 * * *",
        prompt_template=MACRO_HEARTBEAT_PROMPT,
        delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
        metadata={"domain": "macro", "type": "research_crew"},
    ),
    HeartbeatConfig(
        agent_name="research_crew_equity",
        cron_expression="0 7,13 * * 1-5",
        prompt_template=EQUITY_HEARTBEAT_PROMPT,
        delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
        metadata={"domain": "equity", "type": "research_crew"},
    ),
    HeartbeatConfig(
        agent_name="research_crew_crypto",
        cron_expression="0 */4 * * *",
        prompt_template=CRYPTO_HEARTBEAT_PROMPT,
        delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
        metadata={"domain": "crypto", "type": "research_crew"},
    ),
    HeartbeatConfig(
        agent_name="research_crew_sentiment",
        cron_expression="0 */6 * * *",
        prompt_template=SENTIMENT_HEARTBEAT_PROMPT,
        delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
        metadata={"domain": "sentiment", "type": "research_crew"},
    ),
    HeartbeatConfig(
        agent_name="research_crew_risk",
        cron_expression="0 8,14,20 * * *",
        prompt_template=RISK_HEARTBEAT_PROMPT,
        delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
        metadata={"domain": "risk", "type": "research_crew"},
    ),
]


# =============================================================================
# TOOL REGISTRATION
# =============================================================================

async def configure_research_tools(bot_manager: "BotManager") -> dict[str, int]:
    """Attach domain-specific tools to each research crew agent.

    Resolves each crew agent via ``BotManager.get_bot()`` and registers
    the appropriate toolkits. Tools are imported lazily to avoid circular
    imports and to skip unavailable optional dependencies gracefully.

    Args:
        bot_manager: The BotManager instance with registered crew agents.

    Returns:
        Dict mapping crew_id → number of tools registered.
    """
    tool_counts: dict[str, int] = {}

    # ─────────────────────────────────────────────────────────────
    # TOOL MAPPING — each crew gets exactly what it needs.
    #
    # IMPORTANT: All crews run CONCURRENTLY.  Assigning the same
    # API tool to multiple crews causes parallel hits to the same
    # endpoint, exhausting rate limits.  Each external API is
    # assigned to ONE primary crew; analysts receive cross-crew
    # data via cross-pollination during deliberation.
    #
    # External API ownership:
    #   fred_api   → macro  (economic indicators, VIX, yield curve)
    #   finnhub    → equity (company fundamentals, earnings, recs)
    #   alpaca     → equity + risk (stock quotes; risk needs prices)
    #   binance    → crypto + risk (crypto prices; risk needs prices)
    #   market_news→ macro + sentiment (headlines, flow narrative)
    # ─────────────────────────────────────────────────────────────
    tool_map: dict[str, list[tuple[callable, str]]] = {
        "research_crew_macro": [
            (_make_fred_tool, "FRED API (rates, CPI, employment, VIX)"),
            (_make_market_news_tool, "MarketWatch RSS (macro headlines)"),
            (_make_prediction_market_tools, "Prediction Markets (event probabilities)"),
        ],
        "research_crew_equity": [
            (_make_alpaca_read_tools, "Alpaca Markets (quotes, bars)"),
            (_make_technical_analysis, "Technical Analysis (RSI, MACD, BB)"),
            (_make_finnhub_tools, "Finnhub (financials, earnings, analyst recs)"),
        ],
        "research_crew_crypto": [
            (_make_coingecko_tools, "CoinGecko (prices, market cap, volumes)"),
            (_make_binance_read_tools, "Binance (orderbook, funding rates)"),
            (_make_defillama_tools, "DeFiLlama (TVL, protocol data)"),
            (_make_cryptoquant_tools, "CryptoQuant (on-chain metrics)"),
            (_make_cointelegraph_tool, "CoinTelegraph (crypto news + summaries)"),
            (_make_coindesk_tool, "Coindesk (crypto news)"),
            (_make_rsscrypto_tool, "RSSCrypto (aggregated crypto news)"),
        ],
        "research_crew_sentiment": [
            (_make_cnn_fear_greed_tool, "CNN Fear & Greed (traditional markets)"),
            (_make_fear_greed_tool, "Crypto Fear & Greed (alternative.me)"),
            (_make_cmc_fear_greed_tool, "CMC Fear & Greed (CoinMarketCap)"),
            (_make_marketaux_tools, "Marketaux (news sentiment scores)"),
            (_make_market_news_tool, "MarketWatch RSS (flow narrative)"),
            (_make_prediction_market_tools, "Prediction Markets (crowd wisdom)"),
        ],
        "research_crew_risk": [
            # Risk needs cross-asset PRICES for correlation/VaR.
            # VIX, yield curve etc. come via macro briefing at
            # analyst cross-pollination time.
            (_make_alpaca_read_tools, "Alpaca Markets (equity prices)"),
            (_make_binance_read_tools, "Binance (crypto prices)"),
        ],
    }

    for crew_id, tool_factories in tool_map.items():
        agent = await bot_manager.get_bot(crew_id)
        if agent is None:
            logger.warning(
                "Agent '%s' not found in BotManager — skipping tool setup",
                crew_id,
            )
            tool_counts[crew_id] = 0
            continue

        count = 0
        for factory, description in tool_factories:
            try:
                tools = factory()
                if not isinstance(tools, list):
                    tools = [tools]
                for tool in tools:
                    if tool is None:
                        logger.warning(
                            "Skipping None tool from %s on %s",
                            description, crew_id,
                        )
                        continue
                    agent.tool_manager.register_tool(tool)
                    count += 1
                logger.debug(
                    "Registered %s on %s (%d tools)", description, crew_id, len(tools),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to register %s on %s: %s", description, crew_id, exc,
                )

        tool_counts[crew_id] = count
        logger.info(
            "Configured %s with %d tools", crew_id, count,
        )

    # ─────────────────────────────────────────────────────────────
    # MCP SERVERS — async registration of remote MCP tool servers.
    #
    # Unlike the sync factories above, MCP servers require an async
    # round-trip to connect and discover tools.
    # ─────────────────────────────────────────────────────────────
    mcp_map: dict[str, list[tuple[callable, str]]] = {
        # AlphaVantage → macro only (forex, commodities, indicators).
        # equity has finnhub; risk gets cross-asset data from alpaca/binance.
        "research_crew_macro": [
            (_alphavantage_mcp_config, "AlphaVantage MCP (economic indicators, forex, commodities)"),
        ],
    }

    for crew_id, mcp_factories in mcp_map.items():
        agent = await bot_manager.get_bot(crew_id)
        if agent is None:
            continue
        for config_factory, description in mcp_factories:
            try:
                mcp_config = config_factory()
                tools = await agent.add_mcp_server(mcp_config)
                added = len(tools) if tools else 0
                tool_counts[crew_id] = tool_counts.get(crew_id, 0) + added
                logger.info(
                    "Added MCP server %s on %s (%d tools)",
                    description, crew_id, added,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to add MCP %s on %s: %s",
                    description, crew_id, exc,
                )

    return tool_counts


# ── Lazy tool factories ──────────────────────────────────────────────
# Imported lazily to:
#   1. Avoid circular imports (tools may import from parrot.finance)
#   2. Skip gracefully if an optional dependency is missing
#   3. Defer API key resolution to runtime (navconfig.config)
# ─────────────────────────────────────────────────────────────────────

# ── Economic / Macro ─────────────────────────────────────────────────

def _make_fred_tool():
    from parrot.tools.fred_api import FredAPITool
    return FredAPITool()


# ── MCP Server config factories ─────────────────────────────────────

def _alphavantage_mcp_config():
    """Return MCPServerConfig for AlphaVantage (reads ALPHAVANTAGE_API_KEY)."""
    from parrot.mcp.integration import create_alphavantage_mcp_server
    return create_alphavantage_mcp_server()


# ── Equity / ETF ─────────────────────────────────────────────────────

def _make_alpaca_read_tools():
    from parrot.tools.alpaca import AlpacaMarketsToolkit
    return AlpacaMarketsToolkit().get_tools()


def _make_technical_analysis():
    from parrot.tools.technical_analysis import TechnicalAnalysisTool
    return TechnicalAnalysisTool()


def _make_finnhub_tools():
    from parrot.tools.finnhub import FinnhubToolkit
    return FinnhubToolkit().get_tools()




# ── Crypto: Data ─────────────────────────────────────────────────────

def _make_coingecko_tools():
    from parrot.tools.coingecko import CoingeckoToolkit
    return CoingeckoToolkit().get_tools()


def _make_binance_read_tools():
    from parrot.tools.binance import BinanceToolkit
    return BinanceToolkit().get_tools()


def _make_defillama_tools():
    from parrot.tools.defillama import DefiLlamaToolkit
    return DefiLlamaToolkit().get_tools()


def _make_cryptoquant_tools():
    from parrot.tools.cryptoquant import CryptoQuantToolkit
    return CryptoQuantToolkit().get_tools()


# ── Crypto: News ─────────────────────────────────────────────────────

def _make_cointelegraph_tool():
    from parrot.tools.cointelegraph import CoinTelegraphTool
    return CoinTelegraphTool()


def _make_coindesk_tool():
    from parrot.tools.coindesk import CoindeskTool
    return CoindeskTool()


def _make_rsscrypto_tool():
    from parrot.tools.rsscrypto import RSSCryptoTool
    return RSSCryptoTool()


# ── Sentiment ────────────────────────────────────────────────────────

def _make_cnn_fear_greed_tool():
    from parrot.tools.cnn_fear_greed import CNNFearGreedTool
    return CNNFearGreedTool()


def _make_fear_greed_tool():
    from parrot.tools.fear_greed import FearGreedTool
    return FearGreedTool()


def _make_cmc_fear_greed_tool():
    from parrot.tools.cmc_fear_greed import CMCFearGreedTool
    return CMCFearGreedTool()


def _make_marketaux_tools():
    from parrot.tools.marketaux import MarketauxToolkit
    return MarketauxToolkit().get_tools()


# ── Prediction Markets ───────────────────────────────────────────────

def _make_prediction_market_tools():
    from parrot.tools.prediction_market import PredictionMarketToolkit
    return PredictionMarketToolkit().get_tools()


# ── News: Traditional Markets ────────────────────────────────────────

def _make_market_news_tool():
    from parrot.tools.marketnews import MarketNewsTool
    return MarketNewsTool()


# =============================================================================
# FINANCE RESEARCH SERVICE
# =============================================================================

class FinanceResearchService(AgentService):
    """AgentService subclass for autonomous financial research.

    Extends the base ``AgentService`` with:
        - Pre-configured heartbeats for all 5 research crews
        - Automatic tool registration on crew agents at startup
        - Output interception: crew results are parsed into
          ``ResearchBriefing`` and stored via ``ResearchBriefingStore``
        - A ``briefing_store`` attribute for external access

    Usage::

        service = FinanceResearchService(bot_manager=bot_manager)
        await service.start()

        # Access the briefing store from outside
        latest = await service.briefing_store.get_latest_briefings()

    Args:
        bot_manager: BotManager with registered crew agents.
        redis_url: Redis connection URL. Defaults to env ``REDIS_URL``.
        max_workers: Concurrent crew executions. Default 5 (one per crew).
        heartbeats: Override default heartbeat configs.
        briefing_ttl_overrides: Override default TTLs per domain.
    """

    def __init__(
        self,
        bot_manager: "BotManager",
        redis_url: str | None = None,
        max_workers: int = 5,
        heartbeats: list[HeartbeatConfig] | None = None,
        briefing_ttl_overrides: dict[str, int] | None = None,
        **kwargs: Any,
    ):
        _redis_url = redis_url or config.get(
            "REDIS_URL", fallback="redis://localhost:6379"
        )

        svc_config = AgentServiceConfig(
            redis_url=_redis_url,
            max_workers=max_workers,
            heartbeats=heartbeats if heartbeats is not None else DEFAULT_HEARTBEATS,
            task_timeout_seconds=600,  # 10 min — LLM + API calls can be slow
            task_stream="parrot:finance:research_tasks",
            result_stream="parrot:finance:research_results",
            consumer_group="finance_research",
        )
        super().__init__(svc_config, bot_manager, **kwargs)

        self.logger = logging.getLogger("parrot.finance.research.service")
        self._parser = ResearchOutputParser(strict=False)
        self._briefing_ttl_overrides = briefing_ttl_overrides

        # Initialised in start()
        self._briefing_store: Optional[ResearchBriefingStore] = None

    @property
    def briefing_store(self) -> ResearchBriefingStore:
        """Access the underlying briefing store."""
        if self._briefing_store is None:
            raise RuntimeError(
                "FinanceResearchService not started. Call start() first."
            )
        return self._briefing_store

    # ─────────────────────────────────────────────────────────────────
    # LIFECYCLE OVERRIDES
    # ─────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the service, configure tools, init briefing store."""
        # Start base AgentService (Redis, queues, heartbeats, listener)
        await super().start()

        # Initialise briefing store with the same Redis connection
        self._briefing_store = ResearchBriefingStore(
            redis=self._redis,
            ttl_overrides=self._briefing_ttl_overrides,
        )

        # Configure tools on crew agents
        try:
            tool_counts = await configure_research_tools(self.bot_manager)
            total = sum(tool_counts.values())
            self.logger.info(
                "Tool registration complete: %d tools across %d crews",
                total, len(tool_counts),
            )
        except Exception as exc:
            self.logger.error(
                "Tool registration failed (service will continue): %s", exc,
                exc_info=True,
            )

        self.logger.info(
            "✅ FinanceResearchService started "
            "(crews=%d, store=%s)",
            len(self.config.heartbeats),
            self._briefing_store.__class__.__name__,
        )

    # ─────────────────────────────────────────────────────────────────
    # TASK PROCESSING OVERRIDE
    # ─────────────────────────────────────────────────────────────────

    async def _process_task(self, task: AgentTask) -> TaskResult:
        """Override: intercept research crew results for briefing storage.

        Flow:
            1. Execute the agent normally (parent logic)
            2. If the task came from a research crew heartbeat:
               a. Parse LLM output → ResearchBriefing
               b. Store in ResearchBriefingStore
               c. Enrich TaskResult metadata with briefing info
            3. Deliver result via standard delivery pipeline
        """
        start = time.monotonic()
        task.status = TaskStatus.RUNNING
        self.logger.info(
            "Processing research task %s → '%s'",
            task.task_id, task.agent_name,
        )

        try:
            # 1. Resolve and execute agent
            agent = await self._resolve_agent(task.agent_name)
            if not agent:
                raise ValueError(
                    f"Agent '{task.agent_name}' not found in BotManager"
                )
            response = await self._execute_agent(agent, task)
            elapsed = (time.monotonic() - start) * 1000
            output_text = self._extract_output(response)

            # 2. Intercept research crew output
            briefing_id = None
            is_research = task.metadata.get("type") == "research_crew"
            domain = task.metadata.get("domain", "")

            if is_research and output_text and self._briefing_store:
                try:
                    briefing = self._parser.parse(
                        crew_id=task.agent_name,
                        domain=domain,
                        raw_output=output_text,
                    )
                    briefing_id = await self._briefing_store.store_briefing(
                        crew_id=task.agent_name,
                        briefing=briefing,
                    )
                    self.logger.info(
                        "Stored briefing %s from %s (%d items)",
                        briefing_id, task.agent_name,
                        len(briefing.research_items),
                    )
                except Exception as parse_exc:
                    self.logger.warning(
                        "Failed to parse/store briefing from %s: %s",
                        task.agent_name, parse_exc,
                    )

            # 3. Build result
            meta = {**task.metadata}
            if briefing_id:
                meta["briefing_id"] = briefing_id
                meta["briefing_stored"] = True

            result = TaskResult(
                task_id=task.task_id,
                agent_name=task.agent_name,
                success=True,
                output=output_text,
                execution_time_ms=elapsed,
                metadata=meta,
            )

        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            self.logger.error(
                "Research task %s failed: %s", task.task_id, exc,
                exc_info=True,
            )
            result = TaskResult(
                task_id=task.task_id,
                agent_name=task.agent_name,
                success=False,
                error=str(exc),
                execution_time_ms=elapsed,
            )

        # 4. Update status, deliver, clean up
        task.status = (
            TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
        )
        await self._deliver_result(task, result)
        if self._task_queue:
            await self._task_queue._remove_persisted(task)

        return result

    # ─────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────

    async def trigger_crew(self, crew_id: str) -> str:
        """Manually trigger a single research crew run.

        Useful for testing or on-demand research updates.

        Args:
            crew_id: e.g. ``research_crew_macro``.

        Returns:
            Task ID.
        """
        prompt = CREW_PROMPTS.get(crew_id, "Execute your research cycle.")
        domain = ResearchBriefingStore.CREW_DOMAINS.get(crew_id, "unknown")

        task = AgentTask(
            agent_name=crew_id,
            prompt=prompt,
            priority=TaskPriority.HIGH,
            delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
            metadata={
                "domain": domain,
                "type": "research_crew",
                "source": "manual",
                "max_iterations": 3,  # Extractive work — 2-3 rounds
            },
        )
        return await self.submit_task(task)

    async def trigger_all_crews(self) -> list[str]:
        """Trigger all research crews.

        Note: this submits all crews without delays.  For sequential
        execution with per-crew briefing waits, use trigger_crew()
        in a loop (see research_runner.py).

        Returns:
            List of task IDs, one per crew.
        """
        task_ids = []
        for crew_id in ResearchBriefingStore.ALL_CREW_IDS:
            tid = await self.trigger_crew(crew_id)
            task_ids.append(tid)
        return task_ids

    def get_status(self) -> dict:
        """Extended status with briefing store info."""
        base = super().get_status()
        base["briefing_store"] = (
            self._briefing_store is not None
        )
        return base