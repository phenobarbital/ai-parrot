"""
Finance Research Service
=========================

AgentService subclass specialised for autonomous financial research.

Responsibilities:
    1. Register all 5 research crews as heartbeat-driven tasks
    2. Attach domain-specific tools to each crew agent
    3. Intercept crew output → parse → store in collective memory (FileResearchMemory)
    4. Publish ``briefings:updated`` events for downstream consumers

Heartbeat schedules are now driven by ``DEFAULT_RESEARCH_SCHEDULES`` from the
memory module, which defines per-crew schedule configurations with period
granularities:
    - macro:      daily     (3×/day at 06:00, 12:00, 18:00 UTC)
    - equity:     daily     (2×/day weekdays at 07:00, 13:00 UTC)
    - crypto:     4h        (every 4 hours, 24/7)
    - sentiment:  6h        (every 6 hours, 24/7)
    - risk:       daily     (3×/day at 08:00, 14:00, 20:00 UTC)

Integration::

    from parrot.finance.research import FinanceResearchService

    service = FinanceResearchService(bot_manager=bot_manager)
    await service.start()    # starts heartbeats + tool setup + memory
    # ... runs until stop()
    await service.stop()

The service overrides ``_process_task`` to intercept research crew
results and route them through the ``ResearchOutputParser`` →
``FileResearchMemory`` pipeline before standard delivery.
"""
from __future__ import annotations
import inspect
import uuid
from typing import Any, Optional, TYPE_CHECKING
import time
from datetime import datetime, timezone
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
from .briefing_store import ResearchOutputParser
from .memory import (
    FileResearchMemory,
    ResearchDocument,
    set_research_memory,
    generate_period_key,
    DEFAULT_RESEARCH_SCHEDULES,
    ALL_CREW_IDS,
)

if TYPE_CHECKING:
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

        # Finance crews must rely on assigned data tools only.
        # Remove generic default tools that can bypass rate-limit controls.
        for tool_name in ("python_repl", "to_json"):
            if agent.tool_manager.get_tool(tool_name):
                agent.tool_manager.remove_tool(tool_name)
                logger.debug(
                    "Removed default tool %s from %s", tool_name, crew_id
                )

        count = 0
        for factory, description in tool_factories:
            try:
                tools = factory()
                # Handle async factory functions (toolkit.get_tools() is async)
                if inspect.iscoroutine(tools):
                    tools = await tools
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

async def _make_alpaca_read_tools():
    from parrot.tools.alpaca import AlpacaMarketsToolkit
    return await AlpacaMarketsToolkit().get_tools()


async def _make_technical_analysis():
    from parrot.tools.technical_analysis import TechnicalAnalysisTool
    return await TechnicalAnalysisTool().get_tools()


async def _make_finnhub_tools():
    from parrot.tools.finnhub import FinnhubToolkit
    return await FinnhubToolkit().get_tools()




# ── Crypto: Data ─────────────────────────────────────────────────────

async def _make_coingecko_tools():
    from parrot.tools.coingecko import CoingeckoToolkit
    return await CoingeckoToolkit().get_tools()


async def _make_binance_read_tools():
    from parrot.tools.binance import BinanceToolkit
    return await BinanceToolkit().get_tools()


async def _make_defillama_tools():
    from parrot.tools.defillama import DefiLlamaToolkit
    return await DefiLlamaToolkit().get_tools()


async def _make_cryptoquant_tools():
    from parrot.tools.cryptoquant import CryptoQuantToolkit
    return await CryptoQuantToolkit().get_tools()


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


async def _make_marketaux_tools():
    from parrot.tools.marketaux import MarketauxToolkit
    return await MarketauxToolkit().get_tools()


# ── Prediction Markets ───────────────────────────────────────────────

async def _make_prediction_market_tools():
    from parrot.tools.prediction_market import PredictionMarketToolkit
    return await PredictionMarketToolkit().get_tools()


# ── News: Traditional Markets ────────────────────────────────────────

def _make_market_news_tool():
    from parrot.tools.marketnews import MarketNewsTool
    return MarketNewsTool()


# =============================================================================
# BRIEFING STORE ADAPTER
# =============================================================================


class BriefingStoreAdapter:
    """Adapter that wraps FileResearchMemory with briefing-focused methods.

    Provides compatibility with research_runner.py and main.py which
    expect a briefing_store interface with methods like:
    - get_latest_briefing(crew_id) -> ResearchBriefing | None
    - get_latest_briefings() -> dict[domain, ResearchBriefing]

    This adapter translates between the document-based FileResearchMemory
    and the briefing-focused interface expected by consumers.
    """

    # Crew ID → domain mapping (same as ResearchBriefingStore)
    CREW_DOMAINS: dict[str, str] = {
        "research_crew_macro": "macro",
        "research_crew_equity": "equity",
        "research_crew_crypto": "crypto",
        "research_crew_sentiment": "sentiment",
        "research_crew_risk": "risk",
    }
    ALL_CREW_IDS = list(CREW_DOMAINS.keys())

    def __init__(self, memory: "FileResearchMemory"):
        self._memory = memory

    async def get_latest_briefing(self, crew_id: str):
        """Get the latest briefing for a single crew.

        Args:
            crew_id: Research crew identifier (e.g. "research_crew_macro")

        Returns:
            ResearchBriefing or None if no briefing is cached.
        """
        domain = self.CREW_DOMAINS.get(crew_id, crew_id.replace("research_crew_", ""))
        doc = await self._memory.get_latest(domain)
        if doc is None:
            return None
        return doc.briefing

    async def get_latest_briefings(self):
        """Get latest briefings from all crews.

        Returns:
            Dict mapping domain name → ResearchBriefing.
            Only includes domains that have data.
        """
        result = {}
        for crew_id in self.ALL_CREW_IDS:
            domain = self.CREW_DOMAINS[crew_id]
            doc = await self._memory.get_latest(domain)
            if doc is not None:
                result[domain] = doc.briefing
        return result


# =============================================================================
# FINANCE RESEARCH SERVICE
# =============================================================================

class FinanceResearchService(AgentService):
    """AgentService subclass for autonomous financial research.

    Extends the base ``AgentService`` with:
        - Pre-configured heartbeats for all 5 research crews
        - Automatic tool registration on crew agents at startup
        - Output interception: crew results are parsed into
          ``ResearchBriefing`` and stored via ``FileResearchMemory``
        - A ``memory`` attribute for external access to collective memory

    Usage::

        service = FinanceResearchService(bot_manager=bot_manager)
        await service.start()

        # Access the collective memory from outside
        latest = await service.memory.get_latest("macro")

    Args:
        bot_manager: BotManager with registered crew agents.
        redis_url: Redis connection URL. Defaults to env ``REDIS_URL``.
            Still used for distributed locking and pub/sub events.
        memory_base_path: Path for FileResearchMemory storage.
            Defaults to ``./research_memory``.
        max_workers: Concurrent crew executions. Default 5 (one per crew).
        heartbeats: Override default heartbeat configs. If not provided,
            builds from ``DEFAULT_RESEARCH_SCHEDULES``.
    """

    def __init__(
        self,
        bot_manager: "BotManager",
        redis_url: str | None = None,
        memory_base_path: str = "./research_memory",
        max_workers: int = 5,
        heartbeats: list[HeartbeatConfig] | None = None,
        **kwargs: Any,
    ):
        _redis_url = redis_url or config.get(
            "REDIS_URL", fallback="redis://localhost:6379"
        )

        # Build heartbeats from DEFAULT_RESEARCH_SCHEDULES if not provided
        if heartbeats is None:
            heartbeats = self._build_heartbeats_from_schedules()

        svc_config = AgentServiceConfig(
            redis_url=_redis_url,
            max_workers=max_workers,
            heartbeats=heartbeats,
            recover_tasks_on_start=False,
            cleanup_bots_on_stop=True,
            task_timeout_seconds=600,  # 10 min — LLM + API calls can be slow
            task_stream="parrot:finance:research_tasks",
            result_stream="parrot:finance:research_results",
            consumer_group="finance_research",
        )
        super().__init__(svc_config, bot_manager, **kwargs)

        self.logger = logging.getLogger("parrot.finance.research.service")
        self._parser = ResearchOutputParser(strict=False)
        self._memory_base_path = memory_base_path

        # Initialised in start()
        self._memory: Optional[FileResearchMemory] = None

    @property
    def memory(self) -> FileResearchMemory:
        """Access the underlying collective memory store."""
        if self._memory is None:
            raise RuntimeError(
                "FinanceResearchService not started. Call start() first."
            )
        return self._memory

    @property
    def briefing_store(self) -> "BriefingStoreAdapter":
        """Access briefings via an adapter over the memory store.

        Provides a compatible interface for research_runner.py and main.py
        that wraps FileResearchMemory with briefing-focused methods.
        """
        if self._memory is None:
            raise RuntimeError(
                "FinanceResearchService not started. Call start() first."
            )
        return BriefingStoreAdapter(self._memory)

    def _build_heartbeats_from_schedules(self) -> list[HeartbeatConfig]:
        """Build HeartbeatConfig list from DEFAULT_RESEARCH_SCHEDULES."""
        heartbeats = []
        for crew_id, schedule_config in DEFAULT_RESEARCH_SCHEDULES.items():
            domain = crew_id.replace("research_crew_", "")
            prompt = CREW_PROMPTS.get(crew_id, "Execute your research cycle.")
            heartbeats.append(HeartbeatConfig(
                agent_name=crew_id,
                cron_expression=schedule_config.cron_expression,
                prompt_template=prompt,
                delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
                metadata={
                    "domain": domain,
                    "type": "research_crew",
                    "period_granularity": schedule_config.period_granularity,
                },
            ))
        return heartbeats

    # ─────────────────────────────────────────────────────────────────
    # LIFECYCLE OVERRIDES
    # ─────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the service, configure tools, init collective memory."""
        # Initialize collective memory BEFORE starting service
        self._memory = FileResearchMemory(
            base_path=self._memory_base_path,
            cache_max_size=100,
            warmup_on_init=True,
        )
        await self._memory.start()

        # Set global memory for tools (check_research_exists, store_research, etc.)
        set_research_memory(self._memory)

        # Start base AgentService (Redis, queues, heartbeats, listener)
        await super().start()

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
            "(crews=%d, memory=%s)",
            len(self.config.heartbeats),
            self._memory.__class__.__name__,
        )

    async def stop(self) -> None:
        """Stop the service and cleanup memory."""
        await super().stop()
        if self._memory:
            await self._memory.stop()
            self.logger.info("FileResearchMemory stopped")

    # ─────────────────────────────────────────────────────────────────
    # TASK PROCESSING OVERRIDE
    # ─────────────────────────────────────────────────────────────────

    async def _process_task(self, task: AgentTask) -> TaskResult:
        """Override: intercept research crew results for memory storage.

        Flow:
            1. Execute the agent normally (parent logic)
            2. If the task came from a research crew heartbeat:
               a. Parse LLM output → ResearchBriefing
               b. Store in FileResearchMemory as ResearchDocument
               c. Enrich TaskResult metadata with document info
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
            document_id = None
            is_research = task.metadata.get("type") == "research_crew"
            domain = task.metadata.get("domain", "")
            period_granularity = task.metadata.get("period_granularity", "daily")

            if is_research and output_text and self._memory:
                try:
                    briefing = self._parser.parse(
                        crew_id=task.agent_name,
                        domain=domain,
                        raw_output=output_text,
                    )

                    # Generate period key based on crew's granularity
                    period_key = generate_period_key(period_granularity)

                    # Create ResearchDocument
                    document = ResearchDocument(
                        id=uuid.uuid4().hex,
                        crew_id=task.agent_name,
                        domain=domain,
                        period_key=period_key,
                        generated_at=datetime.now(timezone.utc),
                        briefing=briefing,
                        metadata={
                            "source": "heartbeat",
                            "task_id": task.task_id,
                            "item_count": len(briefing.research_items),
                        },
                    )

                    document_id = await self._memory.store(document)
                    self.logger.info(
                        "Stored document %s from %s (%d items, period=%s)",
                        document_id, task.agent_name,
                        len(briefing.research_items), period_key,
                    )
                except Exception as parse_exc:
                    self.logger.warning(
                        "Failed to parse/store document from %s: %s",
                        task.agent_name, parse_exc,
                    )

            # 3. Build result
            meta = {**task.metadata}
            if document_id:
                meta["document_id"] = document_id
                meta["document_stored"] = True

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
        finally:
            # Keep parity with AgentService._process_task contract.
            self._active_agents.pop(task.agent_name, None)

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
        domain = crew_id.replace("research_crew_", "")

        # Get period granularity from schedule config
        schedule_config = DEFAULT_RESEARCH_SCHEDULES.get(crew_id)
        period_granularity = schedule_config.period_granularity if schedule_config else "daily"

        task = AgentTask(
            agent_name=crew_id,
            prompt=prompt,
            priority=TaskPriority.HIGH,
            delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
            metadata={
                "domain": domain,
                "type": "research_crew",
                "source": "manual",
                "period_granularity": period_granularity,
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
        for crew_id in ALL_CREW_IDS:
            tid = await self.trigger_crew(crew_id)
            task_ids.append(tid)
        return task_ids

    def get_status(self) -> dict:
        """Extended status with collective memory info."""
        base = super().get_status()
        base["memory"] = self._memory is not None
        base["memory_base_path"] = self._memory_base_path
        return base
