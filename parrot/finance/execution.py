"""
Trading Swarm - Order Execution Layer
======================================

Conecta la salida del comité deliberativo (InvestmentMemo) con la
ejecución real en plataformas de trading via agentes Parrot.

Componentes:
    1. OrderQueue - Cola async de órdenes con TTL y prioridad
    2. ExecutionOrchestrator - Coordina routing + ejecución + monitoreo
    3. Executor agents - Agentes Haiku que traducen órdenes a API calls
    4. PortfolioMonitor - Monitoreo periódico de stop-loss/take-profit

Integración con Parrot Agent:
    - Los ejecutores son agentes Parrot con Tools (AbstractTool)
    - Cada ejecutor tiene tools específicas de su plataforma
    - El Portfolio Manager tiene tools de lectura cross-platform
    - system_prompt_template = rol estático
    - system_prompt= en ask() = orden + portfolio + constraints dinámicos

Flujo:
    InvestmentMemo
        → memo_to_orders() [de deliberation.py]
        → OrderQueue
        → OrderRouter.route() [asigna ejecutor por asset_class]
        → ExecutorAgent.ask() [valida constraints + ejecuta via tools]
        → ExecutionReport
        → MessageBus (notificación) + BigQuery (log)
"""

from __future__ import annotations
from typing import Any
import asyncio
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional
from decimal import Decimal
from pydantic import BaseModel, Field
from navconfig.logging import logging
from ..tools.abstract import AbstractTool
from .paper_trading.models import (
    ExecutionMode,
    PaperTradingConfig,
    SimulationDetails,
    SimulatedOrder,
)
from .paper_trading.portfolio import VirtualPortfolio
from ..bots.abstract import AbstractBot
# -- Trading swarm imports --
from .schemas import (
    AgentCapabilityProfile,
    AgentMessage,
    AssetClass,
    ConsensusLevel,
    ExecutorConstraints,
    InvestmentMemo,
    MessageBus,
    MessageType,
    OrderRouter,
    OrderStatus,
    Platform,
    PortfolioSnapshot,
    Position,
    RoutingMode,
    TradingOrder,
    create_stock_executor_profile,
    create_crypto_executor_profile,
    create_ibkr_executor_profile,
)
from .memo_store import AbstractMemoStore, MemoEventType
from .fsm import transition_order
from .guards import (
    DeterministicGuard,
    ExecutionAuditEntry,
    create_mandate_from_order,
    wrap_tools_with_guards,
)
from .prompts import (
    EXECUTOR_STOCK,
    EXECUTOR_CRYPTO,
    EXECUTOR_IBKR,
    PORTFOLIO_MANAGER,
    MODEL_RECOMMENDATIONS,
)
from .swarm import (
    CommitteeDeliberation,
    memo_to_orders,
)
from .enrichment import EnrichmentService

# =============================================================================
# PYDANTIC MODELS - Structured output de los ejecutores
# =============================================================================
class ValidationCheck(BaseModel):
    """Validation Check."""
    check: str
    result: str  # "pass" | "fail"
    detail: str


class ValidationResult(BaseModel):
    """Validation Result."""
    passed: bool
    checks_performed: list[ValidationCheck]


class PriceCheck(BaseModel):
    """Solo para crypto executor."""
    memo_entry_price: float = 0.0
    current_market_price: float = 0.0
    deviation_pct: float = 0.0
    within_tolerance: bool = True


class ExecutionDetails(BaseModel):
    """Order Execution Details."""
    platform_order_id: str | None = None
    order_type: str = "limit"
    side: str = ""  # "buy" | "sell"
    symbol: str = ""
    quantity: float = 0.0
    limit_price: float = 0.0
    status: str = ""  # "submitted" | "filled" | "rejected" | "error"
    fill_price: float | None = None
    fill_quantity: float | None = None
    filled_at: str | None = None


class CompanionOrder(BaseModel):
    """Companion Orders."""
    type: str = ""  # "stop_loss" | "take_profit"
    platform_order_id: str = ""
    trigger_price: float = 0.0
    status: str = ""


class PortfolioAfterExecution(BaseModel):
    """How Portfolio ends after execution."""
    daily_trades_used: int = 0
    daily_volume_used_usd: float = 0.0
    total_exposure_pct: float = 0.0
    cash_remaining_usd: float = 0.0
    crypto_exposure_pct: float | None = None  # Solo crypto executor


class ExecutionReportOutput(BaseModel):
    """Output estructurado de un ejecutor tras procesar una orden."""
    order_id: str
    executor_id: str
    platform: str
    action_taken: str  # "executed" | "rejected" | "partial" | "error"
    validation_result: ValidationResult
    price_check: PriceCheck | None = None  # Solo crypto
    execution_details: ExecutionDetails
    companion_orders: list[CompanionOrder] = Field(default_factory=list)
    error_message: str | None = None
    portfolio_after: PortfolioAfterExecution
    # Paper trading fields (backward compatible defaults)
    is_simulated: bool = Field(
        default=False,
        description="True if this execution was simulated (paper/dry-run mode)",
    )
    execution_mode: str = Field(
        default="live",
        description="Execution mode: 'live', 'paper', or 'dry_run'",
    )
    simulation_details: Optional[SimulationDetails] = Field(
        default=None,
        description="Details about simulation parameters applied (only for simulated)",
    )


# -- Portfolio Manager output --
class PositionAction(BaseModel):
    """Action for Position:
    - close_stop_loss
    - close_take_profit
    """
    action_type: str  # "close_stop_loss" | "close_take_profit" | etc.
    asset: str
    platform: str
    details: dict[str, Any] = Field(default_factory=dict)
    order_generated: dict[str, Any] | None = None


class CircuitBreakerStatus(BaseModel):
    """Circuit Breaker status, can be:
    - safe
    - approaching
    - critical
    - triggered
    """
    triggered: bool = False
    daily_pnl_pct: float = 0.0
    drawdown_pct: float = 0.0
    threshold_proximity: str = "safe"  # "safe"|"approaching"|"critical"|"triggered"


class PortfolioHealthOutput(BaseModel):
    """Portfolios' Health."""
    total_value_usd: float = 0.0
    daily_pnl_usd: float = 0.0
    open_positions: int = 0
    positions_at_risk: int = 0
    stale_orders_cancelled: int = 0


class PortfolioManagerOutput(BaseModel):
    """Output del Portfolio Manager tras un check periódico."""
    check_timestamp: str
    positions_checked: int = 0
    actions: list[PositionAction] = Field(default_factory=list)
    circuit_breaker_status: CircuitBreakerStatus = Field(
        default_factory=CircuitBreakerStatus
    )
    portfolio_health: PortfolioHealthOutput = Field(
        default_factory=PortfolioHealthOutput
    )
    next_check_recommended_seconds: int = 900


# =============================================================================
# ORDER QUEUE
# =============================================================================

class OrderQueue:
    """
    Cola async de órdenes con prioridad por consenso y TTL automático.

    Las órdenes con consenso UNANIMOUS se procesan primero,
    seguidas de STRONG_MAJORITY, luego MAJORITY.

    Las órdenes expiradas se descartan automáticamente al extraerlas.
    """

    # Prioridad numérica: menor = más prioritaria
    _CONSENSUS_PRIORITY = {
        ConsensusLevel.UNANIMOUS: 1,
        ConsensusLevel.STRONG_MAJORITY: 2,
        ConsensusLevel.MAJORITY: 3,
        ConsensusLevel.DIVIDED: 99,    # Nunca debería llegar aquí
        ConsensusLevel.DEADLOCK: 99,
    }

    def __init__(self, maxsize: int = 50):
        # PriorityQueue con tupla (priority, counter, order)
        # counter es un tiebreaker monotónico para evitar comparación
        # de TradingOrder cuando priority y timestamp coinciden
        self._queue: asyncio.PriorityQueue[
            tuple[int, int, TradingOrder]
        ] = asyncio.PriorityQueue(maxsize=maxsize)
        self._counter = 0  # Monotonic tiebreaker (FIFO garantizado)
        self._total_enqueued = 0
        self._total_processed = 0
        self._total_expired = 0
        self._logger = logging.getLogger(
            'TradingSwarm.OrderQueue'
        )

    async def put(self, order: TradingOrder) -> None:
        """Encola una orden con prioridad por consenso."""
        priority = self._CONSENSUS_PRIORITY.get(
            order.consensus_level, 99
        )
        # Usar counter monotónico como tiebreaker (FIFO dentro del mismo nivel)
        self._counter += 1
        await self._queue.put((priority, self._counter, order))
        self._total_enqueued += 1
        self._logger.info(
            f"  Orden encolada: {order.action} {order.asset} "
            f"(prioridad {priority}, queue size {self._queue.qsize()})"
        )

    async def get(self) -> TradingOrder | None:
        """
        Extrae la orden de mayor prioridad.
        Descarta expiradas automáticamente.
        """
        while not self._queue.empty():
            _, _, order = await self._queue.get()
            if order.is_expired:
                order.change_status(
                    OrderStatus.EXPIRED,
                    changed_by="order_queue",
                    reason="TTL expired while in queue",
                )
                self._total_expired += 1
                self._logger.info(
                    f"  Orden expirada descartada: {order.asset}"
                )
                continue
            self._total_processed += 1
            return order
        return None

    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "enqueued": self._total_enqueued,
            "processed": self._total_processed,
            "expired": self._total_expired,
            "pending": self._queue.qsize(),
        }


# =============================================================================
# EXECUTION ORCHESTRATOR
# =============================================================================

class ExecutionOrchestrator:
    """
    Orquesta la ejecución de órdenes: routing → validación → ejecución.

    Integración con Parrot Agent:
        - Los ejecutores son agentes Parrot con system_prompt estático
          (rol, capabilities, constraints, instrucciones de validación)
        - La orden + portfolio se pasan via system_prompt= en ask()
        - Los ejecutores tienen tools (AbstractTool) para las APIs
          de cada plataforma, registradas en su ToolManager
        - use_tools=True para ejecutores (necesitan llamar a las APIs)

    Ejecutores registrados (4 total):
        1. Stock Executor (Alpaca) - stocks/ETFs via Alpaca
        2. Crypto Executor (Binance) - crypto via Binance
        3. Crypto Executor (Kraken) - crypto via Kraken
        4. IBKR Executor - multi-asset (stocks, ETFs, options, futures) via IBKR

        Portfolio Manager (cross-platform):
            - Tools de lectura y cierre de todas las plataformas

    Routing modes:
        - STOCK: MULTI (orders go to both Alpaca and IBKR)
        - CRYPTO: SINGLE (orders go to one exchange only)

    Ciclo de vida:
        1. configure() → Crea los agentes ejecutores + registra en router
        2. process_orders(orders) → Rutea y ejecuta una lista de órdenes
        3. Los agentes se reutilizan entre ciclos

    Uso:
        orchestrator = ExecutionOrchestrator(
            message_bus=bus,
            agent_class=Agent,
        )
        await orchestrator.configure()

        # Procesar órdenes del memo
        reports = await orchestrator.process_orders(orders)
    """

    def __init__(
        self,
        message_bus: MessageBus,
        agent_class: type[AbstractBot] | None = None,
        stock_tools: list[AbstractTool] | None = None,
        crypto_tools: list[AbstractTool] | None = None,
        kraken_tools: list[AbstractTool] | None = None,
        ibkr_tools: list[AbstractTool] | None = None,
        monitor_tools: list[AbstractTool] | None = None,
        paper_config: PaperTradingConfig | None = None,
        memo_store: Optional[AbstractMemoStore] = None,
    ):
        """Initialize the execution orchestrator.

        Args:
            message_bus: Internal message bus for agent communication.
            agent_class: Bot/Agent class to use for executor agents.
            stock_tools: Tools for the stock executor (Alpaca).
            crypto_tools: Tools for the crypto executor (Binance).
            kraken_tools: Tools for the Kraken crypto executor.
            ibkr_tools: Tools for the IBKR multi-asset executor.
            monitor_tools: Tools for the portfolio monitor.
            paper_config: Paper trading configuration. Defaults to DRY_RUN.
            memo_store: Optional memo store for investment memo persistence.
                If None, tries to create a FileMemoStore from the
                ``MEMO_STORE_PATH`` environment variable. If the env var is
                not set, memo persistence is disabled.
        """
        self.bus = message_bus
        self._agent_class = agent_class
        self._stock_tools = stock_tools or []
        self._crypto_tools = crypto_tools or []
        self._kraken_tools = kraken_tools or []
        self._ibkr_tools = ibkr_tools or []
        self._monitor_tools = monitor_tools or []

        # Paper trading configuration
        self._paper_config = paper_config or PaperTradingConfig()
        self._virtual_portfolio: VirtualPortfolio | None = None

        # Create VirtualPortfolio for DRY_RUN mode
        if self._paper_config.mode == ExecutionMode.DRY_RUN:
            self._virtual_portfolio = VirtualPortfolio(
                slippage_bps=self._paper_config.simulate_slippage_bps,
                fill_delay_ms=self._paper_config.simulate_fill_delay_ms,
            )

        self._router = OrderRouter()
        self._queue = OrderQueue()

        # Agentes ejecutores
        self._executors: dict[str, Any] = {}  # agent_id → Agent
        self._executor_profiles: dict[str, AgentCapabilityProfile] = {}

        # Portfolio Manager
        self._portfolio_manager: Any = None
        self._logger = logging.getLogger(
            'TradingSwarm.ExecutionOrchestrator'
        )

        # Memo store for investment memo persistence (opt-in)
        self.memo_store: Optional[AbstractMemoStore] = (
            memo_store if memo_store is not None else self._default_memo_store()
        )

    def _default_memo_store(self) -> Optional[AbstractMemoStore]:
        """Create a default FileMemoStore if MEMO_STORE_PATH is configured.

        Reads the ``MEMO_STORE_PATH`` environment variable. If set, creates a
        :class:`~parrot.finance.memo_store.FileMemoStore` at that path. If the
        variable is not set, returns ``None`` (memo persistence is disabled).

        Returns:
            A FileMemoStore instance, or None if not configured.
        """
        path = os.getenv("MEMO_STORE_PATH")
        if path:
            from .memo_store import FileMemoStore
            self._logger.info("MemoStore enabled at %s", path)
            return FileMemoStore(base_path=path)
        return None

    @property
    def execution_mode(self) -> ExecutionMode:
        """Current execution mode."""
        return self._paper_config.mode

    @property
    def is_simulated(self) -> bool:
        """True if running in paper or dry-run mode."""
        return self._paper_config.mode in (ExecutionMode.PAPER, ExecutionMode.DRY_RUN)

    # -----------------------------------------------------------------
    # MEMO PERSISTENCE HOOKS
    # -----------------------------------------------------------------

    async def _persist_memo(self, memo: InvestmentMemo) -> None:
        """Fire-and-forget memo persistence.

        Stores the investment memo in the configured memo store.
        Errors are logged but not raised to avoid blocking the pipeline.

        Args:
            memo: The investment memo to persist.
        """
        try:
            await self.memo_store.store(memo)
            self._logger.debug("Memo %s persisted successfully", memo.id)
        except Exception as exc:
            self._logger.error("Failed to persist memo %s: %s", memo.id, exc)

    async def _finalize_execution(
        self,
        memo: InvestmentMemo,
        reports: list[ExecutionReportOutput],
    ) -> None:
        """Log lifecycle event after order execution completes.

        Logs EXECUTION_COMPLETED if any orders succeeded, or
        EXECUTION_FAILED if all orders failed. Errors in logging
        do not crash the pipeline.

        Args:
            memo: The source investment memo.
            reports: List of execution reports for all processed orders.
        """
        if not self.memo_store:
            return

        successful = sum(1 for r in reports if r.action_taken == "executed")
        failed = len(reports) - successful

        event_type = (
            MemoEventType.EXECUTION_COMPLETED
            if successful > 0
            else MemoEventType.EXECUTION_FAILED
        )

        tickers = list({
            r.execution_details.symbol
            for r in reports
            if r.execution_details.symbol
        })

        try:
            await self.memo_store.log_event(
                memo.id,
                event_type,
                {
                    "total_orders": len(reports),
                    "successful": successful,
                    "failed": failed,
                    "tickers": tickers,
                },
            )
        except Exception as exc:
            self._logger.error(
                "Failed to log execution event for memo %s: %s", memo.id, exc
            )

    # -----------------------------------------------------------------
    # CONFIGURACIÓN
    # -----------------------------------------------------------------

    async def configure(self) -> None:
        """
        Crea los agentes ejecutores y los registra en el router.
        Llamar UNA VEZ al inicio.
        """
        if self._agent_class is None:
            raise RuntimeError("agent_class no proporcionado.")

        # ── Stock Executor (Alpaca) ──────────────────────────────
        stock_profile = create_stock_executor_profile()
        stock_agent = self._agent_class(
            name="Stock Executor (Alpaca)",
            agent_id="stock_executor",
            llm=MODEL_RECOMMENDATIONS["stock_executor"]["model"],
            system_prompt=EXECUTOR_STOCK,
            use_tools=True,
        )
        # Registrar tools de Alpaca
        for tool in self._stock_tools:
            stock_agent.tool_manager.register_tool(tool)
        await stock_agent.configure()

        self._executors["stock_executor"] = stock_agent
        self._executor_profiles["stock_executor"] = stock_profile
        self._router.register_executor(stock_profile)
        self._logger.info(
            f"Stock executor configurado "
            f"(platforms: {stock_profile.platforms}, "
            f"assets: {stock_profile.asset_classes})"
        )

        # ── Crypto Executor (Binance) ────────────────────────────
        crypto_profile = create_crypto_executor_profile()
        crypto_agent = self._agent_class(
            name="Crypto Executor (Binance)",
            agent_id="crypto_executor",
            llm=MODEL_RECOMMENDATIONS["crypto_executor"]["model"],
            system_prompt=EXECUTOR_CRYPTO,
            use_tools=True,
        )
        for tool in self._crypto_tools:
            crypto_agent.tool_manager.register_tool(tool)
        await crypto_agent.configure()

        self._executors["crypto_executor"] = crypto_agent
        self._executor_profiles["crypto_executor"] = crypto_profile
        self._router.register_executor(crypto_profile)
        self._logger.info(
            f"Crypto executor configurado "
            f"(platforms: {crypto_profile.platforms}, "
            f"assets: {crypto_profile.asset_classes})"
        )

        # ── Crypto Executor (Kraken) ─────────────────────────────
        kraken_profile = create_crypto_executor_profile(
            agent_id="crypto_executor_kraken",
            platform=Platform.KRAKEN,
        )
        kraken_agent = self._agent_class(
            name="Crypto Executor (Kraken)",
            agent_id="crypto_executor_kraken",
            llm=MODEL_RECOMMENDATIONS["crypto_executor"]["model"],
            system_prompt=EXECUTOR_CRYPTO,
            use_tools=True,
        )
        for tool in self._kraken_tools:
            kraken_agent.tool_manager.register_tool(tool)
        await kraken_agent.configure()

        self._executors["crypto_executor_kraken"] = kraken_agent
        self._executor_profiles["crypto_executor_kraken"] = kraken_profile
        self._router.register_executor(kraken_profile)
        self._logger.info(
            f"Kraken executor configurado "
            f"(platforms: {kraken_profile.platforms}, "
            f"assets: {kraken_profile.asset_classes})"
        )

        # ── IBKR Executor (multi-asset) ──────────────────────────
        ibkr_profile = create_ibkr_executor_profile()
        ibkr_agent = self._agent_class(
            name="IBKR Executor",
            agent_id="ibkr_executor",
            llm=MODEL_RECOMMENDATIONS["ibkr_executor"]["model"],
            system_prompt=EXECUTOR_IBKR,
            use_tools=True,
        )
        for tool in self._ibkr_tools:
            ibkr_agent.tool_manager.register_tool(tool)
        await ibkr_agent.configure()

        self._executors["ibkr_executor"] = ibkr_agent
        self._executor_profiles["ibkr_executor"] = ibkr_profile
        self._router.register_executor(ibkr_profile)
        self._logger.info(
            f"IBKR executor configurado "
            f"(platforms: {ibkr_profile.platforms}, "
            f"assets: {ibkr_profile.asset_classes})"
        )

        # ── Default routing modes ────────────────────────────────
        # STOCK: MULTI so both Alpaca and IBKR can receive stock orders
        self._router.set_routing_mode(AssetClass.STOCK, RoutingMode.MULTI)
        # CRYPTO: SINGLE — each crypto order goes to one exchange only
        self._router.set_routing_mode(AssetClass.CRYPTO, RoutingMode.SINGLE)
        self._logger.info(
            "Routing modes configured: STOCK=MULTI, CRYPTO=SINGLE"
        )

        # ── Portfolio Manager ────────────────────────────────────
        pm_agent = self._agent_class(
            name="Portfolio Manager",
            agent_id="portfolio_manager",
            llm=MODEL_RECOMMENDATIONS["portfolio_manager"]["model"],
            system_prompt=PORTFOLIO_MANAGER,
            use_tools=True,
        )
        for tool in self._monitor_tools:
            pm_agent.tool_manager.register_tool(tool)
        await pm_agent.configure()

        self._portfolio_manager = pm_agent
        self._logger.info("Portfolio Manager configurado")

        self._logger.info(
            f"Routing table: {self._router.get_routing_table()}"
        )

        # Log execution mode configuration
        self._logger.info(
            f"Execution mode: {self._paper_config.mode.value} | "
            f"is_simulated={self.is_simulated}"
        )
        if self._paper_config.mode == ExecutionMode.DRY_RUN:
            self._logger.info(
                f"DRY_RUN config: slippage={self._paper_config.simulate_slippage_bps}bps, "
                f"fill_delay={self._paper_config.simulate_fill_delay_ms}ms"
            )

    # -----------------------------------------------------------------
    # PROCESAMIENTO DE ÓRDENES
    # -----------------------------------------------------------------

    async def process_orders(
        self,
        orders: list[TradingOrder],
        portfolio: PortfolioSnapshot,
    ) -> list[ExecutionReportOutput]:
        """
        Procesa una lista de órdenes del memo.

        1. Encola todas las órdenes
        2. Las extrae por prioridad (consenso)
        3. Rutea cada una al ejecutor correcto
        4. El ejecutor valida constraints y ejecuta
        5. Retorna los reportes de ejecución

        Las órdenes se procesan SECUENCIALMENTE por diseño:
        cada ejecución modifica el estado del portfolio, y la
        siguiente orden debe ver el estado actualizado.
        """
        self._logger.info(f"Procesando {len(orders)} órdenes")

        # Encolar todas
        for order in orders:
            await self._queue.put(order)

        reports = []
        current_portfolio = portfolio

        # Procesar secuencialmente por prioridad
        while True:
            order = await self._queue.get()
            if order is None:
                break

            # Rutear al ejecutor correcto (returns list for multi-routing)
            routed_orders = self._router.route(order)

            for routed_order in routed_orders:
                if routed_order.status == OrderStatus.CONSTRAINT_REJECTED:
                    self._logger.warning(
                        f"  Orden rechazada por router: "
                        f"{routed_order.error_message}"
                    )
                    await self._notify_execution(routed_order, None)
                    continue

                # Ejecutar
                report = await self._execute_order(
                    routed_order, current_portfolio
                )
                reports.append(report)

                # Actualizar portfolio snapshot para la siguiente orden
                # (en producción esto vendría de una lectura real de la API)
                current_portfolio = self._update_portfolio_estimate(
                    current_portfolio, report
                )

        self._logger.info(
            f"Ejecución completada: {len(reports)} reportes, "
            f"Queue stats: {self._queue.stats}"
        )
        return reports

    async def _execute_order(
        self,
        order: TradingOrder,
        portfolio: PortfolioSnapshot,
    ) -> ExecutionReportOutput:
        """
        Ejecuta una orden individual via el agente ejecutor asignado.

        El agente ejecutor:
        1. Recibe la orden + portfolio + constraints como contexto
        2. Valida constraints internamente (redundancia de seguridad)
        3. Usa sus tools para interactuar con la API de la plataforma
        4. Retorna un ExecutionReportOutput estructurado

        In DRY_RUN mode, orders are routed to VirtualPortfolio instead.
        """
        executor_id = order.assigned_executor

        # ── DRY_RUN Mode: Route to VirtualPortfolio ───────────────
        if self._paper_config.mode == ExecutionMode.DRY_RUN and self._virtual_portfolio:
            self._logger.info(
                f"  [DRY_RUN] Simulating: {order.action} {order.asset} "
                f"via VirtualPortfolio"
            )
            return await self._execute_order_dry_run(order, portfolio)

        agent = self._executors.get(executor_id)
        profile = self._executor_profiles.get(executor_id)

        if not agent or not profile:
            self._logger.error(
                f"Ejecutor {executor_id} no encontrado"
            )
            return self._build_error_report(
                order, executor_id or "unknown",
                f"Executor {executor_id} not found"
            )

        # ── Pre-validación en el orquestador (primera capa) ─────
        # El ejecutor también valida (segunda capa, redundancia)
        if profile.constraints:
            is_valid, reason = profile.constraints.validate_order(
                order, portfolio
            )
            if not is_valid:
                self._logger.warning(
                    f"  Pre-validación fallida para {order.asset}: "
                    f"{reason}"
                )
                order.error_message = reason
                transition_order(
                    order, "reject",
                    changed_by="orchestrator",
                    reason=reason,
                )
                await self._notify_execution(order, None)
                return self._build_rejected_report(
                    order, executor_id, reason
                )

        # ── Transition to EXECUTING ──────────────────────────────
        transition_order(
            order, "execute",
            changed_by="orchestrator",
            reason=f"Dispatching to {executor_id}",
        )

        # ── Layer 2: Create anti-hallucination guard ─────────────
        mandate = create_mandate_from_order(
            order=order,
            portfolio=portfolio,
            constraints=profile.constraints,
            allowed_tools={
                getattr(t, 'name', '') for t in agent.tool_manager.get_all_tools()
            },
        )
        guard = DeterministicGuard(mandate=mandate)

        # ── Layer 3: Wrap tools with deterministic guard ─────────
        original_tools = list(agent.tool_manager.get_all_tools())
        safe_tools = wrap_tools_with_guards(original_tools, guard)
        agent.tool_manager.clear_tools()
        for tool in safe_tools:
            agent.tool_manager.register_tool(tool)

        # ── Construir contexto dinámico para el ejecutor ─────────
        dynamic_context = self._build_executor_context(
            order, portfolio, profile.constraints
        )

        question = (
            f"Execute this trading order. "
            f"Validate all constraints, then place the order "
            f"via the {order.assigned_platform.value} API. "
            f"Report the result."
        )

        self._logger.info(
            f"  Ejecutando: {order.action} {order.asset} "
            f"via {executor_id} en {order.assigned_platform.value}"
        )

        try:
            response = await agent.ask(
                question,
                system_prompt=dynamic_context,
                structured_output=ExecutionReportOutput,
                use_tools=True,   # Los ejecutores SÍ usan tools
                use_conversation_history=False,
                use_vector_context=False,
            )
            report: ExecutionReportOutput = response.content

            # ── Layer 4: Post-execution reconciliation ───────────
            if report.action_taken == "executed":
                recon = guard.reconcile_execution(
                    requested_symbol=order.asset,
                    requested_side=order.action,
                    requested_qty=order.quantity or 0,
                    requested_price=order.limit_price,
                    filled_symbol=report.execution_details.symbol,
                    filled_side=report.execution_details.side if hasattr(
                        report.execution_details, 'side'
                    ) else None,
                    filled_qty=report.execution_details.fill_quantity,
                    filled_price=report.execution_details.fill_price,
                )
                if not recon.allowed:
                    self._logger.critical(
                        f"  ⚠ RECONCILIATION FAILED for {order.asset}: "
                        f"{recon.summary()}"
                    )

            # Log guard violations
            if guard.violations:
                for v in guard.violations:
                    log_fn = (
                        self._logger.critical if v.is_critical
                        else self._logger.warning
                    )
                    log_fn(f"  Guard violation: {v.to_dict()}")

            # Build audit entry
            audit = ExecutionAuditEntry.from_guard(
                guard,
                blocked=False,
                reconciliation_passed=(
                    recon.allowed if report.action_taken == "executed"
                    else None
                ),
            )
            self._logger.debug(
                f"  Audit: {audit.order_id} | "
                f"violations={len(audit.violations)} | "
                f"recon={'PASS' if audit.reconciliation_passed else 'FAIL' if audit.reconciliation_passed is False else 'N/A'}"
            )

            # Actualizar estado de la orden basándose en el reporte
            self._update_order_from_report(order, report)

            # Notificar al bus
            await self._notify_execution(order, report)

            self._logger.info(
                f"  ✓ {order.asset}: {report.action_taken} "
                f"(platform_order: {report.execution_details.platform_order_id})"
            )
            return report

        except Exception as e:
            self._logger.error(
                f"  ✗ Error ejecutando {order.asset}: {e}"
            )
            order.error_message = str(e)
            transition_order(
                order, "platform_reject",
                changed_by="orchestrator",
                reason=str(e),
            )
            await self._notify_execution(order, None)
            return self._build_error_report(
                order, executor_id, str(e)
            )

        finally:
            # ── Restore original tools unconditionally ───────────
            agent.tool_manager.clear_tools()
            for tool in original_tools:
                agent.tool_manager.register_tool(tool)

    async def _execute_order_dry_run(
        self,
        order: TradingOrder,
        portfolio: PortfolioSnapshot,
    ) -> ExecutionReportOutput:
        """
        Execute an order via VirtualPortfolio in DRY_RUN mode.

        This provides local simulation without touching any real APIs.
        Market orders fill immediately; limit orders require price updates.
        """
        if not self._virtual_portfolio:
            return self._build_error_report(
                order,
                order.assigned_executor or "dry_run",
                "VirtualPortfolio not initialized for DRY_RUN mode",
            )

        # Current price for market order fill (use limit_price or estimate)
        current_price = Decimal(str(order.limit_price or 100.0))

        # Calculate quantity from sizing_pct if not explicitly provided
        if order.quantity and order.quantity > 0:
            quantity = Decimal(str(order.quantity))
        elif order.sizing_pct and order.sizing_pct > 0:
            # Calculate quantity based on portfolio value and sizing percentage
            port_val = portfolio.total_value_usd or portfolio.cash_available_usd or 100000
            portfolio_value = Decimal(str(port_val))
            sizing = Decimal(str(order.sizing_pct)) / Decimal("100")
            position_value = portfolio_value * sizing
            quantity = (position_value / current_price).quantize(Decimal("0.00001"))
            # Ensure minimum quantity of 1 for whole-share assets
            whole_share_assets = (AssetClass.STOCK, AssetClass.ETF)
            if quantity < Decimal("1") and order.asset_class in whole_share_assets:
                quantity = Decimal("1")
        else:
            return self._build_error_report(
                order,
                order.assigned_executor or "dry_run",
                "Order has no quantity or sizing_pct specified",
            )

        # Validate quantity is positive
        if quantity <= 0:
            return self._build_error_report(
                order,
                order.assigned_executor or "dry_run",
                f"Calculated quantity {quantity} must be greater than 0",
            )

        # Map TradingOrder to SimulatedOrder
        simulated_order = SimulatedOrder(
            order_id=order.id,
            symbol=order.asset,
            platform=order.assigned_platform.value if order.assigned_platform else "dry_run",
            side="buy" if order.action.lower() in ("buy", "long") else "sell",
            order_type="limit" if order.limit_price else "market",
            quantity=quantity,
            limit_price=Decimal(str(order.limit_price)) if order.limit_price else None,
            stop_price=Decimal(str(order.stop_loss)) if order.stop_loss else None,
        )

        try:
            # Place order in VirtualPortfolio
            filled_order = await self._virtual_portfolio.place_order(
                simulated_order, current_price
            )

            # Determine action taken
            if filled_order.status == "filled":
                action_taken = "executed"
                fill_price = float(filled_order.filled_price) if filled_order.filled_price else None
                fill_qty = float(filled_order.filled_quantity) if filled_order.filled_quantity else None
                status = "filled"
            elif filled_order.status == "pending":
                action_taken = "partial"  # Order pending (limit not hit)
                fill_price = None
                fill_qty = None
                status = "pending"
            else:
                action_taken = "rejected"
                fill_price = None
                fill_qty = None
                status = filled_order.status

            # Build execution report
            report = ExecutionReportOutput(
                order_id=order.id,
                executor_id="dry_run_executor",
                platform=simulated_order.platform,
                action_taken=action_taken,
                validation_result=ValidationResult(
                    passed=True,
                    checks_performed=[
                        ValidationCheck(
                            check="dry_run_validation",
                            result="pass",
                            detail="Order validated for DRY_RUN simulation",
                        )
                    ],
                ),
                execution_details=ExecutionDetails(
                    platform_order_id=filled_order.order_id,
                    order_type=simulated_order.order_type,
                    side=simulated_order.side,
                    symbol=simulated_order.symbol,
                    quantity=float(simulated_order.quantity),
                    limit_price=float(simulated_order.limit_price) if simulated_order.limit_price else 0.0,
                    status=status,
                    fill_price=fill_price,
                    fill_quantity=fill_qty,
                    filled_at=filled_order.filled_at.isoformat() if filled_order.filled_at else None,
                ),
                portfolio_after=PortfolioAfterExecution(
                    cash_remaining_usd=float(self._virtual_portfolio.get_state().cash_balance),
                ),
                is_simulated=True,
                execution_mode=ExecutionMode.DRY_RUN.value,
                simulation_details=SimulationDetails(
                    slippage_applied_bps=self._paper_config.simulate_slippage_bps,
                    fill_delay_applied_ms=self._paper_config.simulate_fill_delay_ms,
                ),
            )

            # Update order state
            if action_taken == "executed":
                transition_order(
                    order, "fill",
                    changed_by="dry_run_executor",
                    reason="Simulated fill in DRY_RUN mode",
                )
            elif action_taken == "partial":
                # Order is pending, waiting for price update
                self._logger.info(
                    f"  [DRY_RUN] Order {order.id} pending - "
                    f"limit {order.limit_price} not hit at price {current_price}"
                )

            await self._notify_execution(order, report)

            self._logger.info(
                f"  [DRY_RUN] ✓ {order.asset}: {action_taken} "
                f"(simulated order: {filled_order.order_id})"
            )
            return report

        except Exception as e:
            self._logger.error(f"  [DRY_RUN] ✗ Error simulating {order.asset}: {e}")
            return self._build_error_report(
                order,
                "dry_run_executor",
                f"DRY_RUN simulation error: {e}",
            )

    # -----------------------------------------------------------------
    # PORTFOLIO MONITOR
    # -----------------------------------------------------------------

    async def run_portfolio_check(
        self,
        positions: list[Position],
        current_prices: dict[str, float],
        portfolio: PortfolioSnapshot,
        circuit_breaker_config: dict[str, float],
    ) -> PortfolioManagerOutput:
        """
        Ejecuta un check periódico del Portfolio Manager.

        Llamar via cron cada 15-60 minutos.
        El PM revisa stop-losses, take-profits, trailing stops,
        y el circuit breaker.

        Args:
            positions: Posiciones abiertas actuales
            current_prices: Dict de asset → precio actual
            portfolio: Estado del portfolio
            circuit_breaker_config: Umbrales de circuit breaker

        Returns:
            PortfolioManagerOutput con acciones tomadas
        """
        if not self._portfolio_manager:
            raise RuntimeError("Portfolio Manager no configurado")

        # Contexto dinámico
        dynamic_context = self._build_monitor_context(
            positions, current_prices, portfolio,
            circuit_breaker_config,
        )

        question = (
            "Perform a portfolio health check. "
            "Check all positions against their stop-loss and "
            "take-profit levels. "
            "Check circuit breaker thresholds. "
            "Cancel any stale orders. "
            "Report all actions taken."
        )

        response = await self._portfolio_manager.ask(
            question,
            system_prompt=dynamic_context,
            structured_output=PortfolioManagerOutput,
            use_tools=True,   # PM usa tools para cerrar posiciones
            use_conversation_history=False,
            use_vector_context=False,
        )

        result: PortfolioManagerOutput = response.content

        # Si circuit breaker se activó, halt el bus
        if result.circuit_breaker_status.triggered:
            self._logger.critical(
                "⚠ CIRCUIT BREAKER TRIGGERED: "
                f"daily_pnl={result.circuit_breaker_status.daily_pnl_pct:.1f}%, "
                f"drawdown={result.circuit_breaker_status.drawdown_pct:.1f}%"
            )
            await self.bus.halt(
                reason=(
                    f"Circuit breaker: "
                    f"daily_pnl={result.circuit_breaker_status.daily_pnl_pct:.1f}%, "
                    f"drawdown={result.circuit_breaker_status.drawdown_pct:.1f}%"
                )
            )

        # Notificar acciones al bus
        if result.actions:
            await self.bus.send(AgentMessage(
                msg_type=MessageType.MECHANICAL_ORDER,
                sender="portfolio_manager",
                phase="monitoring",
                payload=result.model_dump(),
            ))

        self._logger.info(
            f"Portfolio check: {result.positions_checked} posiciones, "
            f"{len(result.actions)} acciones, "
            f"circuit_breaker={result.circuit_breaker_status.threshold_proximity}"
        )

        return result

    # -----------------------------------------------------------------
    # CONTEXT BUILDERS
    # -----------------------------------------------------------------

    def _build_executor_context(
        self,
        order: TradingOrder,
        portfolio: PortfolioSnapshot,
        constraints: ExecutorConstraints | None,
    ) -> str:
        """Contexto dinámico para un ejecutor."""
        ctx = ""
        ctx += _ctx_block("order_to_execute", asdict(order))
        ctx += _ctx_block("portfolio_state", asdict(portfolio))
        if constraints:
            ctx += _ctx_block("your_constraints", asdict(constraints))
        return ctx

    def _build_monitor_context(
        self,
        positions: list[Position],
        current_prices: dict[str, float],
        portfolio: PortfolioSnapshot,
        circuit_breaker_config: dict[str, float],
    ) -> str:
        """Contexto dinámico para el Portfolio Manager."""
        ctx = ""
        ctx += _ctx_block(
            "current_positions",
            [asdict(p) for p in positions],
        )
        ctx += _ctx_block("current_prices", current_prices)
        ctx += _ctx_block("portfolio_state", asdict(portfolio))
        ctx += _ctx_block(
            "circuit_breaker_thresholds", circuit_breaker_config
        )
        return ctx

    # -----------------------------------------------------------------
    # ORDER STATE MANAGEMENT
    # -----------------------------------------------------------------

    def _update_order_from_report(
        self,
        order: TradingOrder,
        report: ExecutionReportOutput,
    ) -> None:
        """Actualiza el estado de la orden basándose en el reporte."""
        # Map action_taken → FSM event name
        _ACTION_TO_FSM_EVENT = {
            "executed": "fill",
            "partial": "partial_fill",
            "rejected": "reject",
            "error": "platform_reject",
        }
        event = _ACTION_TO_FSM_EVENT.get(
            report.action_taken, "platform_reject"
        )

        # Update fill details before status transition
        order.platform_order_id = (
            report.execution_details.platform_order_id
        )
        order.fill_price = report.execution_details.fill_price
        order.fill_quantity = report.execution_details.fill_quantity
        if report.execution_details.filled_at:
            try:
                order.filled_at = datetime.fromisoformat(
                    report.execution_details.filled_at
                )
            except (ValueError, TypeError):
                order.filled_at = datetime.now(timezone.utc)
        order.error_message = report.error_message or ""

        transition_order(
            order, event,
            changed_by=report.executor_id,
            reason=report.error_message or f"Action: {report.action_taken}",
        )

    def _update_portfolio_estimate(
        self,
        portfolio: PortfolioSnapshot,
        report: ExecutionReportOutput,
    ) -> PortfolioSnapshot:
        """
        Estima el nuevo estado del portfolio tras una ejecución.

        En producción, esto debería ser una lectura real de la API.
        Aquí hacemos un estimado para que la siguiente orden en la
        cola tenga datos razonablemente actualizados.
        """
        if report.action_taken != "executed":
            return portfolio

        pa = report.portfolio_after
        # Actualizar con los datos reportados por el ejecutor
        updated = PortfolioSnapshot(
            timestamp=datetime.now(timezone.utc),
            total_value_usd=portfolio.total_value_usd,
            cash_available_usd=pa.cash_remaining_usd,
            exposure=portfolio.exposure.copy(),
            open_positions=list(portfolio.open_positions),
            daily_pnl_usd=portfolio.daily_pnl_usd,
            daily_pnl_pct=portfolio.daily_pnl_pct,
            max_drawdown_pct=portfolio.max_drawdown_pct,
            daily_trades_executed=pa.daily_trades_used,
            daily_volume_usd=pa.daily_volume_used_usd,
        )
        return updated

    # -----------------------------------------------------------------
    # NOTIFICATION & ERROR HELPERS
    # -----------------------------------------------------------------

    async def _notify_execution(
        self,
        order: TradingOrder,
        report: ExecutionReportOutput | None,
    ) -> None:
        """Notifica al bus sobre el resultado de una ejecución."""
        payload = {
            "order_id": order.id,
            "asset": order.asset,
            "action": order.action,
            "status": order.status.value,
            "error": order.error_message,
        }
        if report:
            payload["report"] = report.model_dump()

        await self.bus.send(AgentMessage(
            msg_type=MessageType.EXECUTION_REPORT,
            sender=order.assigned_executor or "orchestrator",
            phase="execution",
            priority=2,
            payload=payload,
        ))

    def _build_error_report(
        self,
        order: TradingOrder,
        executor_id: str,
        error: str,
    ) -> ExecutionReportOutput:
        return ExecutionReportOutput(
            order_id=order.id,
            executor_id=executor_id,
            platform=order.assigned_platform.value if order.assigned_platform else "unknown",
            action_taken="error",
            validation_result=ValidationResult(
                passed=False,
                checks_performed=[
                    ValidationCheck(
                        check="system",
                        result="fail",
                        detail=error,
                    )
                ],
            ),
            execution_details=ExecutionDetails(
                symbol=order.asset,
                status="error",
            ),
            error_message=error,
            portfolio_after=PortfolioAfterExecution(),
            is_simulated=self.is_simulated,
            execution_mode=self._paper_config.mode.value,
            simulation_details=SimulationDetails(
                slippage_applied_bps=self._paper_config.simulate_slippage_bps,
                fill_delay_applied_ms=self._paper_config.simulate_fill_delay_ms,
            ) if self.is_simulated else None,
        )

    def _build_rejected_report(
        self,
        order: TradingOrder,
        executor_id: str,
        reason: str,
    ) -> ExecutionReportOutput:
        return ExecutionReportOutput(
            order_id=order.id,
            executor_id=executor_id,
            platform=order.assigned_platform.value if order.assigned_platform else "unknown",
            action_taken="rejected",
            validation_result=ValidationResult(
                passed=False,
                checks_performed=[
                    ValidationCheck(
                        check="constraint_validation",
                        result="fail",
                        detail=reason,
                    )
                ],
            ),
            execution_details=ExecutionDetails(
                symbol=order.asset,
                status="rejected",
            ),
            error_message=reason,
            portfolio_after=PortfolioAfterExecution(),
            is_simulated=self.is_simulated,
            execution_mode=self._paper_config.mode.value,
            simulation_details=SimulationDetails(
                slippage_applied_bps=self._paper_config.simulate_slippage_bps,
                fill_delay_applied_ms=self._paper_config.simulate_fill_delay_ms,
            ) if self.is_simulated else None,
        )


# =============================================================================
# CONTEXT BLOCK HELPER
# =============================================================================

def _ctx_block(tag: str, data: Any) -> str:
    """Bloque XML con JSON para system_prompt=."""
    content = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    return f"\n<{tag}>\n{content}\n</{tag}>\n"


# =============================================================================
# FULL PIPELINE: Deliberation → Execution
# =============================================================================

from .fsm import PipelineStateMachine

logger = logging.getLogger('TradingSwarm.pipeline')

async def run_trading_pipeline(
    agent_class: type[AbstractBot],
    briefings: dict,
    portfolio: PortfolioSnapshot,
    constraints: ExecutorConstraints,
    stock_tools: list[AbstractTool] | None = None,
    crypto_tools: list[AbstractTool] | None = None,
    monitor_tools: list[AbstractTool] | None = None,
    massive_toolkit: Any | None = None,
    options_analytics: Any | None = None,
    quant_toolkit: Any | None = None,
    redis_client: Any | None = None,
    paper_config: PaperTradingConfig | None = None,
) -> dict[str, Any]:
    """Pipeline completo: deliberación + ejecución en una sola llamada.

    Uso desde cron:
        from parrot.bots import Agent
        from trading_swarm_execution import run_trading_pipeline

        result = await run_trading_pipeline(
            agent_class=Agent,
            briefings=research_briefings,
            portfolio=current_portfolio,
            constraints=default_constraints,
            stock_tools=[AlpacaGetQuote(), AlpacaPlaceOrder(), ...],
            crypto_tools=[BinanceGetTicker(), BinancePlaceOrder(), ...],
        )

        print(f"Memo: {result['memo'].id}")
        print(f"Orders: {len(result['orders'])}")
        print(f"Executed: {len(result['reports'])}")
    """

    pipeline_fsm = PipelineStateMachine(pipeline_id="trading")

    bus = MessageBus()
    # Register all agents
    all_ids = [
        "macro_analyst", "equity_analyst", "crypto_analyst",
        "sentiment_analyst", "risk_analyst", "cio", "secretary",
        "stock_executor", "crypto_executor", "portfolio_manager",
        "system",
    ]
    for aid in all_ids:
        bus.register(aid)

    try:
        # ── FASE A.5: Enrichment (optional) ──────────────────────
        enrichment_enabled = os.environ.get(
            "MASSIVE_ENRICHMENT_ENABLED", "false"
        ).lower() == "true"
        enrichment_timeout = int(
            os.environ.get("MASSIVE_ENRICHMENT_TIMEOUT", "300")
        )

        if massive_toolkit and enrichment_enabled:
            pipeline_fsm.start_research()
            pipeline_fsm.start_enrichment()
            logger.info("=" * 60)
            logger.info("PIPELINE: Fase de enriquecimiento (Massive)")
            logger.info("=" * 60)

            enrichment_service = EnrichmentService(
                massive_toolkit=massive_toolkit,
                redis_client=redis_client,
                options_toolkit=options_analytics,
                quant_toolkit=quant_toolkit,
            )
            try:
                briefings = await asyncio.wait_for(
                    enrichment_service.enrich_briefings(briefings),
                    timeout=enrichment_timeout,
                )
                logger.info("Enrichment completado exitosamente")
            except asyncio.TimeoutError:
                logger.warning(
                    "Enrichment timeout (%ds). Continuing with raw briefings.",
                    enrichment_timeout,
                )
            except Exception as e:
                logger.warning(
                    "Enrichment failed: %s. Continuing with raw briefings.",
                    e,
                )

        # ── FASE A: Deliberación ─────────────────────────────────
        pipeline_fsm.start_deliberation()
        logger.info("=" * 60)
        logger.info("PIPELINE: Fase de deliberación")
        logger.info("=" * 60)

        committee = CommitteeDeliberation(
            message_bus=bus,
            agent_class=agent_class,
        )
        await committee.configure()

        memo = await committee.run_deliberation(
            briefings=briefings,
            portfolio=portfolio,
            constraints=constraints,
        )

        # ── FASE B: Dispatch ─────────────────────────────────────
        pipeline_fsm.start_dispatch()
        orders = memo_to_orders(memo)

        if not orders:
            logger.info("No hay órdenes accionables. Pipeline finalizado.")
            pipeline_fsm.start_execution()
            pipeline_fsm.start_monitoring()
            pipeline_fsm.complete()
            return {
                "memo": memo,
                "orders": [],
                "reports": [],
                "pipeline_status": "no_actionable_orders",
                "pipeline_phase": pipeline_fsm.phase.value,
            }

        # ── FASE C: Ejecución ────────────────────────────────────
        pipeline_fsm.start_execution()
        logger.info("=" * 60)
        logger.info("PIPELINE: Fase de ejecución")
        logger.info("=" * 60)

        orchestrator = ExecutionOrchestrator(
            message_bus=bus,
            agent_class=agent_class,
            stock_tools=stock_tools,
            crypto_tools=crypto_tools,
            monitor_tools=monitor_tools,
            paper_config=paper_config,
        )
        await orchestrator.configure()

        # Fire-and-forget memo persistence (TASK-164)
        if orchestrator.memo_store:
            asyncio.create_task(orchestrator._persist_memo(memo))

        reports = await orchestrator.process_orders(orders, portfolio)

        # Log execution lifecycle event (TASK-165)
        await orchestrator._finalize_execution(memo, reports)

        # ── FASE D: Monitoring / Complete ────────────────────────
        pipeline_fsm.start_monitoring()

        # Resumen
        executed = sum(
            1 for r in reports if r.action_taken == "executed"
        )
        rejected = sum(
            1 for r in reports if r.action_taken in ("rejected", "error")
        )

        pipeline_fsm.complete()

        # Determine execution mode info
        effective_config = paper_config or PaperTradingConfig()
        execution_mode_str = effective_config.mode.value
        is_simulated = effective_config.mode in (ExecutionMode.PAPER, ExecutionMode.DRY_RUN)

        logger.info("=" * 60)
        logger.info(
            f"PIPELINE COMPLETADO [{execution_mode_str.upper()}]: "
            f"{executed} ejecutadas, {rejected} rechazadas"
        )
        if is_simulated:
            logger.info(
                f"  (Simulated execution: slippage={effective_config.simulate_slippage_bps}bps, "
                f"delay={effective_config.simulate_fill_delay_ms}ms)"
            )
        logger.info("=" * 60)

        return {
            "memo": memo,
            "orders": orders,
            "reports": reports,
            "pipeline_status": "completed",
            "pipeline_phase": pipeline_fsm.phase.value,
            "execution_mode": execution_mode_str,
            "is_simulated": is_simulated,
            "summary": {
                "total_recommendations": len(memo.recommendations),
                "actionable_orders": len(orders),
                "executed": executed,
                "rejected": rejected,
            },
        }

    except Exception as exc:
        pipeline_fsm.fail()
        logger.error(f"PIPELINE FAILED: {exc}")
        raise

