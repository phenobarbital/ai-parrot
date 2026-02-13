"""
Trading Swarm - Data Structures & Schemas
==========================================

Estructuras de datos para el sistema de trading autónomo multi-agente.
Diseñado para integrarse con Parrot Agent, AgentCrew y AgentMemory.

Módulos:
    1. Message Bus - Comunicación intra-agente en memoria
    2. Research & Analysis - Schemas de investigación y análisis
    3. Investment Memo - Estructura del memo final del comité
    4. Order Queue - Cola de órdenes con separación de capacidades
    5. Agent Capabilities - Modelo de seguridad por least privilege
"""

from __future__ import annotations
from typing import Any
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from navconfig.logging import logging


# =============================================================================
# 1. ENUMS COMPARTIDOS
# =============================================================================


class AssetClass(str, Enum):
    """Clase de activo - determina routing al agente ejecutor correcto."""
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"
    OPTIONS = "options"  # futuro
    FOREX = "forex"      # futuro


class Platform(str, Enum):
    """Plataformas de trading disponibles."""
    ALPACA = "alpaca"           # Stocks, ETFs
    BINANCE = "binance"         # Crypto
    KRAKEN = "kraken"           # Crypto
    BLOCKCHAIN = "blockchain"   # Crypto
    BYBIT = "bybit"             # Crypto (Spot, Linear, Inverse)
    IBKR = "ibkr"               # Multi-asset (Stocks, Options, Futures, Forex)


class Signal(str, Enum):
    """Señal de inversión."""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class ConsensusLevel(str, Enum):
    """Nivel de consenso del comité."""
    UNANIMOUS = "unanimous"       # 5/5 → sizing completo
    STRONG_MAJORITY = "strong_majority"  # 4/5 → 75% sizing
    MAJORITY = "majority"         # 3/5 → 50% sizing
    DIVIDED = "divided"           # <3/5 → NO ejecutar
    DEADLOCK = "deadlock"         # Posiciones irreconciliables → NO ejecutar


class TimeHorizon(str, Enum):
    """Horizonte temporal de la recomendación."""
    SCALP = "scalp"          # Minutos a horas
    INTRADAY = "intraday"    # Dentro del día
    SWING = "swing"          # Días a semanas
    POSITION = "position"    # Semanas a meses
    LONG_TERM = "long_term"  # Meses+


class OrderStatus(str, Enum):
    """Estado de una orden en la cola."""
    PENDING = "pending"                # En cola, esperando ejecución
    VALIDATING = "validating"          # Ejecutor verificando constraints
    CONSTRAINT_REJECTED = "constraint_rejected"  # Violó un constraint
    EXECUTING = "executing"            # Enviada a la plataforma
    FILLED = "filled"                  # Completamente ejecutada
    PARTIALLY_FILLED = "partially_filled"
    PLATFORM_REJECTED = "platform_rejected"  # La plataforma rechazó
    EXPIRED = "expired"                # TTL expirado
    CANCELLED = "cancelled"            # Cancelada manualmente (kill switch)


class MessageType(str, Enum):
    """Tipos de mensaje en el bus interno."""
    # Research → Analyst
    RESEARCH_DELIVERY = "research_delivery"
    # Analyst → Analyst (polinización cruzada)
    CROSS_POLLINATION = "cross_pollination"
    # Analyst → Mesa
    INDIVIDUAL_REPORT = "individual_report"
    # CIO/Árbitro → Analyst
    REVISION_REQUEST = "revision_request"
    # Analyst → Mesa (post-revisión)
    REVISED_REPORT = "revised_report"
    # CIO → Secretary
    DELIBERATION_COMPLETE = "deliberation_complete"
    # Secretary → Order Queue
    INVESTMENT_MEMO = "investment_memo"
    # Order Queue → Executor
    ORDER_DISPATCH = "order_dispatch"
    # Executor → System
    EXECUTION_REPORT = "execution_report"
    # Portfolio Manager → Order Queue (stop-loss, take-profit)
    MECHANICAL_ORDER = "mechanical_order"
    # System → All (kill switch, circuit breaker)
    SYSTEM_HALT = "system_halt"
    SYSTEM_RESUME = "system_resume"


# =============================================================================
# 2. MESSAGE BUS - Comunicación en memoria entre agentes
# =============================================================================


@dataclass
class AgentMessage:
    """
    Unidad atómica de comunicación entre agentes.

    Diseñado para asyncio.Queue - sin serialización de red.
    Cada mensaje es inmutable una vez creado; las respuestas
    generan nuevos mensajes con correlation_id.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    msg_type: MessageType = MessageType.RESEARCH_DELIVERY
    sender: str = ""          # agent_id del emisor
    recipients: list[str] = field(default_factory=list)  # agent_ids destino, vacío = broadcast
    correlation_id: str | None = None  # Para encadenar request/response
    phase: str = ""           # "research", "analysis", "deliberation", "execution"
    priority: int = 5         # 1 (máxima) a 10 (mínima)
    ttl_seconds: int = 3600   # Tiempo de vida del mensaje (1h default)
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return elapsed > self.ttl_seconds

    @property
    def is_broadcast(self) -> bool:
        return len(self.recipients) == 0


class MessageBus:
    """
    Bus de mensajes en memoria usando asyncio.Queue por agente.

    En lugar de un protocolo de red, cada agente tiene su propia
    queue. El bus rutea mensajes basándose en recipients.
    Para broadcast, copia el mensaje a todas las queues.

    Uso:
        bus = MessageBus()
        bus.register("macro_analyst")
        bus.register("stock_analyst")

        # Enviar mensaje directo
        await bus.send(AgentMessage(
            sender="macro_analyst",
            recipients=["stock_analyst"],
            msg_type=MessageType.CROSS_POLLINATION,
            payload={"report": {...}}
        ))

        # Recibir (en el agente destino)
        msg = await bus.receive("stock_analyst")
    """

    def __init__(self, max_queue_size: int = 100):
        self._queues: dict[str, asyncio.Queue[AgentMessage]] = {}
        self._max_size = max_queue_size
        self._halted = False
        # Log de mensajes para auditoría (últimos N mensajes)
        self._message_log: list[AgentMessage] = []
        self._log_max = 1000
        self._logger = logging.getLogger(__name__)

    def register(self, agent_id: str) -> None:
        """Registra un agente en el bus."""
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue(maxsize=self._max_size)

    def unregister(self, agent_id: str) -> None:
        """Desregistra un agente."""
        self._queues.pop(agent_id, None)

    async def send(self, message: AgentMessage) -> None:
        """Envía un mensaje. Broadcast si recipients está vacío."""
        if self._halted and message.msg_type not in (
            MessageType.SYSTEM_HALT, MessageType.SYSTEM_RESUME
        ):
            return  # Sistema detenido, solo mensajes de sistema pasan

        # Log para auditoría
        self._message_log.append(message)
        if len(self._message_log) > self._log_max:
            self._message_log = self._message_log[-self._log_max:]

        if message.is_broadcast:
            for agent_id, queue in self._queues.items():
                if agent_id != message.sender:  # No enviarse a sí mismo
                    try:
                        queue.put_nowait(message)
                    except asyncio.QueueFull:
                        try:
                            queue.get_nowait()  # Evict oldest
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            queue.put_nowait(message)
                        except asyncio.QueueFull:
                            pass
                        self._logger.warning(
                            "MessageBus queue full for %s; evicted oldest message",
                            agent_id,
                        )
        else:
            for recipient in message.recipients:
                queue = self._queues.get(recipient)
                if queue:
                    try:
                        queue.put_nowait(message)
                    except asyncio.QueueFull:
                        pass

    async def receive(
        self, agent_id: str, timeout: float | None = None
    ) -> AgentMessage | None:
        """
        Recibe el siguiente mensaje para un agente.
        Descarta mensajes expirados automáticamente.
        """
        queue = self._queues.get(agent_id)
        if not queue:
            return None
        try:
            while True:
                msg = await asyncio.wait_for(queue.get(), timeout=timeout)
                if not msg.is_expired:
                    return msg
                # Mensaje expirado, intentar siguiente
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None

    async def halt(self, reason: str = "") -> None:
        """Kill switch - detiene todo el tráfico excepto mensajes de sistema."""
        self._halted = True
        halt_msg = AgentMessage(
            msg_type=MessageType.SYSTEM_HALT,
            sender="system",
            payload={"reason": reason},
            priority=1,
        )
        await self.send(halt_msg)

    async def resume(self) -> None:
        """Reanuda operaciones."""
        self._halted = False
        resume_msg = AgentMessage(
            msg_type=MessageType.SYSTEM_RESUME,
            sender="system",
            priority=1,
        )
        await self.send(resume_msg)

    @property
    def is_halted(self) -> bool:
        return self._halted


# =============================================================================
# 3. RESEARCH & ANALYSIS - Schemas de investigación
# =============================================================================
@dataclass
class ResearchItem:
    """
    Una pieza individual de investigación producida por un Crew.
    Puede ser una noticia, un dato de mercado, un indicador, etc.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""         # "rss:bloomberg", "api:binance", "scrape:fed.gov"
    source_url: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    domain: str = ""         # "macro", "technical", "sentiment", "crypto", "risk"
    title: str = ""
    summary: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)  # Datos estructurados
    relevance_score: float = 0.0  # 0.0-1.0, asignado por el crew
    assets_mentioned: list[str] = field(default_factory=list)  # ["AAPL", "BTC", "ETH"]


@dataclass
class ResearchBriefing:
    """
    Paquete de investigación que un Crew entrega a su Analista.
    Incluye los items de investigación + contexto histórico del analista.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    analyst_id: str = ""
    domain: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Investigación fresca del crew
    research_items: list[ResearchItem] = field(default_factory=list)
    # Contexto histórico del analista (del AgentMemory/BigQuery)
    analyst_track_record: dict[str, Any] = field(default_factory=dict)
    # Ejemplo: {"total_predictions": 47, "accuracy": 0.62,
    #           "best_domain": "tech_stocks", "recent_misses": [...]}
    # Estado actual del portfolio relevante a este dominio
    portfolio_snapshot: dict[str, Any] = field(default_factory=dict)
    # Ejemplo: {"crypto_exposure_pct": 23.5, "open_positions": [...]}


@dataclass
class AnalystReport:
    """
    Informe individual de un analista del comité.
    Producido después de revisar el ResearchBriefing.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    analyst_id: str = ""
    analyst_role: str = ""   # "macro", "technical", "sentiment", "crypto", "risk"
    version: int = 1         # Se incrementa con cada revisión
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revised_at: datetime | None = None

    # Análisis
    market_outlook: str = ""  # Narrativa libre del analista
    recommendations: list[AnalystRecommendation] = field(default_factory=list)

    # Confianza general del analista
    overall_confidence: float = 0.0  # 0.0-1.0
    key_risks: list[str] = field(default_factory=list)
    key_catalysts: list[str] = field(default_factory=list)

    # Metadata de deliberación
    cross_pollination_received_from: list[str] = field(default_factory=list)
    revision_notes: str = ""  # Qué cambió tras la revisión


@dataclass
class AnalystRecommendation:
    """Recomendación individual sobre un activo específico."""
    asset: str = ""              # Ticker o símbolo: "AAPL", "BTC/USDT"
    asset_class: AssetClass = AssetClass.STOCK
    signal: Signal = Signal.HOLD
    confidence: float = 0.0      # 0.0-1.0
    time_horizon: TimeHorizon = TimeHorizon.SWING
    target_price: float | None = None
    stop_loss_price: float | None = None
    rationale: str = ""          # Argumentación breve
    data_points: list[str] = field(default_factory=list)  # Evidencia citada


# =============================================================================
# 4. DELIBERATION - Estructuras de la mesa de debate
# =============================================================================
@dataclass
class RevisionRequest:
    """
    Solicitud del CIO/Árbitro a un analista para revisar su informe.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    target_analyst_id: str = ""
    target_report_id: str = ""
    requested_by: str = "cio"  # Siempre el CIO
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Qué se pide revisar
    contradiction_with: str | None = None  # analyst_id del informe contradictorio
    gap_description: str = ""     # Descripción del hueco argumental
    specific_questions: list[str] = field(default_factory=list)
    # Ejemplo: ["Tu análisis técnico muestra bullish en BTC pero ignoras
    #            el dato del analista macro sobre la subida de tasas. ¿Cómo reconcilias?"]


@dataclass
class DeliberationRound:
    """
    Registro de una ronda completa de deliberación.
    Se almacena para auditoría y training del sistema.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    round_number: int = 1  # Máximo 3 rondas
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Informes en esta ronda
    reports: list[AnalystReport] = field(default_factory=list)
    # Contradicciones detectadas por el CIO
    contradictions_found: list[dict[str, str]] = field(default_factory=list)
    # Ejemplo: [{"between": ["macro", "technical"], "topic": "BTC direction",
    #            "description": "..."}]
    # Revisiones solicitadas
    revision_requests: list[RevisionRequest] = field(default_factory=list)
    # ¿Hubo consenso?
    consensus_reached: bool = False
    consensus_level: ConsensusLevel = ConsensusLevel.DIVIDED


# =============================================================================
# 5. INVESTMENT MEMO - El producto final del comité
# =============================================================================
@dataclass
class MemoRecommendation:
    """
    Una recomendación de acción concreta dentro del memo.
    Diseñada para ser parseada por el agente ejecutor sin ambigüedad.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # Asset
    asset: str = ""              # "AAPL", "BTC/USDT", "ETH/USDT"
    asset_class: AssetClass = AssetClass.STOCK
    preferred_platform: Platform | None = None  # Si hay preferencia

    # Acción
    signal: Signal = Signal.HOLD
    action: str = ""             # "BUY", "SELL", "CLOSE", "REDUCE", "INCREASE"

    # Sizing (el Secretary aplica reglas de risk management aquí)
    sizing_pct: float = 0.0      # % del portfolio total (ej: 2.0 = 2%)
    max_position_value: float | None = None  # Tope absoluto en USD

    # Precios
    entry_price_limit: float | None = None   # Precio límite de entrada
    stop_loss: float | None = None           # Stop-loss obligatorio
    take_profit: float | None = None         # Take-profit sugerido
    trailing_stop_pct: float | None = None   # Trailing stop en %

    # Consenso
    consensus_level: ConsensusLevel = ConsensusLevel.DIVIDED
    bull_case: str = ""          # Resumen del caso alcista
    bear_case: str = ""          # Resumen del caso bajista
    time_horizon: TimeHorizon = TimeHorizon.SWING

    # Votos individuales (para auditoría)
    analyst_votes: dict[str, Signal] = field(default_factory=dict)
    # Ejemplo: {"macro": "sell", "technical": "buy", "sentiment": "buy", ...}


@dataclass
class InvestmentMemo:
    """
    Documento final producido por el Secretary.
    Este es el artefacto que se coloca en la cola de órdenes.

    El Secretary NO investiga - sintetiza y aplica risk management.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: datetime | None = None  # TTL del memo

    # Contexto del portfolio al momento de emisión
    portfolio_snapshot: PortfolioSnapshot | None = None

    # Resumen ejecutivo (narrativa del Secretary)
    executive_summary: str = ""
    market_conditions: str = ""  # Resumen del estado del mercado

    # Recomendaciones accionables
    recommendations: list[MemoRecommendation] = field(default_factory=list)

    # Metadata de deliberación
    deliberation_rounds: int = 1
    final_consensus: ConsensusLevel = ConsensusLevel.DIVIDED

    # Referencias a los informes fuente (para auditoría)
    source_report_ids: list[str] = field(default_factory=list)
    deliberation_round_ids: list[str] = field(default_factory=list)

    @property
    def actionable_recommendations(self) -> list[MemoRecommendation]:
        """Solo recomendaciones con suficiente consenso para ejecutar."""
        return [
            r for r in self.recommendations
            if r.consensus_level in (
                ConsensusLevel.UNANIMOUS,
                ConsensusLevel.STRONG_MAJORITY,
                ConsensusLevel.MAJORITY,
            )
            and r.signal != Signal.HOLD
        ]

    @property
    def is_expired(self) -> bool:
        if self.valid_until is None:
            return False
        return datetime.now(timezone.utc) > self.valid_until


@dataclass
class PortfolioSnapshot:
    """Estado del portfolio en un momento dado."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_value_usd: float = 0.0
    cash_available_usd: float = 0.0
    # Exposición por clase de activo
    exposure: dict[str, float] = field(default_factory=dict)
    # Ejemplo: {"stock": 45.2, "crypto": 23.5, "cash": 31.3}  (porcentajes)
    # Posiciones abiertas
    open_positions: list[Position] = field(default_factory=list)
    # Métricas de riesgo
    daily_pnl_usd: float = 0.0
    daily_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0  # Desde el máximo histórico
    # Límites consumidos hoy
    daily_trades_executed: int = 0
    daily_volume_usd: float = 0.0


@dataclass
class Position:
    """Una posición abierta en el portfolio."""
    asset: str = ""
    asset_class: AssetClass = AssetClass.STOCK
    platform: Platform = Platform.ALPACA
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl_usd: float = 0.0
    unrealized_pnl_pct: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# 6. ORDER QUEUE - Cola de órdenes con separación de capacidades
# =============================================================================
@dataclass
class TradingOrder:
    """
    Orden en la cola de ejecución.

    El flujo es:
    1. Secretary genera InvestmentMemo
    2. Cada MemoRecommendation se convierte en TradingOrder(s)
    3. El OrderRouter asigna la orden al ejecutor correcto por asset_class
    4. El ejecutor verifica constraints y ejecuta
    5. El resultado actualiza el estado de la orden

    Inspirado en el patrón de restaurante:
    - La "comanda" (MemoRecommendation) llega a la "cocina" (OrderRouter)
    - Se asigna a la "estación" correcta (ejecutor por plataforma)
    - Cada cocinero solo tiene acceso a sus propios ingredientes (APIs)
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memo_id: str = ""              # Referencia al InvestmentMemo origen
    recommendation_id: str = ""    # Referencia a la MemoRecommendation

    # Qué ejecutar
    asset: str = ""
    asset_class: AssetClass = AssetClass.STOCK
    action: str = ""               # "BUY", "SELL"
    order_type: str = "limit"      # "limit", "market", "stop_limit"
    quantity: float | None = None  # Calculada por el ejecutor basado en sizing
    sizing_pct: float = 0.0       # % del portfolio (del memo)
    limit_price: float | None = None
    stop_price: float | None = None

    # Routing
    assigned_platform: Platform | None = None   # Asignada por el OrderRouter
    assigned_executor: str | None = None        # agent_id del ejecutor

    # Protecciones post-ejecución
    stop_loss: float | None = None
    take_profit: float | None = None
    trailing_stop_pct: float | None = None

    # Lifecycle
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int = 21600       # 6 horas default
    status_history: list[OrderStatusChange] = field(default_factory=list)

    # Resultado (llenado por el ejecutor)
    fill_price: float | None = None
    fill_quantity: float | None = None
    filled_at: datetime | None = None
    platform_order_id: str | None = None  # ID de la orden en la plataforma
    execution_notes: str = ""
    error_message: str = ""

    # Metadata de consenso (heredada del memo, para auditoría del ejecutor)
    consensus_level: ConsensusLevel = ConsensusLevel.DIVIDED

    @property
    def is_expired(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.created_at).total_seconds()
        return elapsed > self.ttl_seconds and self.status == OrderStatus.PENDING

    def change_status(
        self, new_status: OrderStatus, changed_by: str, reason: str
    ) -> None:
        """Change order status with mandatory audit trail.

        This is the sole entry point for status mutations.
        Every call appends an OrderStatusChange record.
        """
        old = self.status
        self.status = new_status
        self.status_history.append(OrderStatusChange(
            from_status=old,
            to_status=new_status,
            changed_by=changed_by,
            reason=reason,
        ))


@dataclass
class OrderStatusChange:
    """Registro de cambio de estado para auditoría completa."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    from_status: OrderStatus = OrderStatus.PENDING
    to_status: OrderStatus = OrderStatus.PENDING
    changed_by: str = ""     # agent_id o "system"
    reason: str = ""


# =============================================================================
# 7. AGENT CAPABILITIES - Modelo de seguridad por least privilege
# =============================================================================
class Capability(str, Enum):
    """
    Capacidades granulares asignables a cada agente.

    Principio: cada agente solo tiene las capacidades mínimas
    necesarias para su rol. El agente de Alpaca NO puede operar
    en Binance, y viceversa.
    """
    # Lectura de mercado (sin riesgo)
    READ_MARKET_DATA = "read_market_data"         # Precios, volúmenes, order book
    READ_PORTFOLIO = "read_portfolio"             # Ver posiciones y balance
    READ_NEWS = "read_news"                       # RSS, APIs de noticias
    READ_ONCHAIN = "read_onchain"                 # Datos on-chain (etherscan, etc)

    # Operaciones de trading (riesgo controlado)
    PLACE_ORDER_STOCK = "place_order_stock"        # Ordenes en Alpaca
    PLACE_ORDER_CRYPTO = "place_order_crypto"      # Ordenes en Binance/Kraken
    CANCEL_ORDER = "cancel_order"                  # Cancelar ordenes propias
    MODIFY_ORDER = "modify_order"                  # Modificar ordenes abiertas

    # Gestión de portfolio (riesgo medio)
    SET_STOP_LOSS = "set_stop_loss"               # Poner/modificar stop-loss
    SET_TAKE_PROFIT = "set_take_profit"           # Poner/modificar take-profit
    CLOSE_POSITION = "close_position"              # Cerrar posición completa

    # PROHIBIDOS para agentes (solo humano)
    # Estos NUNCA se asignan a un agente automático:
    # - WITHDRAW_FUNDS
    # - CHANGE_API_KEYS
    # - TRANSFER_BETWEEN_ACCOUNTS
    # - MODIFY_AGENT_CAPABILITIES

    # Sistema
    SEND_MESSAGE = "send_message"                 # Enviar al message bus
    WRITE_MEMORY = "write_memory"                 # Escribir a AgentMemory/BigQuery
    READ_MEMORY = "read_memory"                   # Leer del AgentMemory


@dataclass
class ExecutorConstraints:
    """
    Hard limits para un agente ejecutor.
    Verificados ANTES de cada operación.
    Nunca modificables por el propio agente.
    """
    # Límites por operación
    max_order_pct: float = 2.0            # Máximo % del portfolio por orden
    max_order_value_usd: float = 500.0    # Tope absoluto por orden
    allowed_order_types: list[str] = field(
        default_factory=lambda: ["limit"]  # Solo órdenes limitadas al inicio
    )

    # Límites diarios
    max_daily_trades: int = 10
    max_daily_volume_usd: float = 2000.0

    # Límites de portfolio
    max_positions: int = 10               # Posiciones abiertas simultáneas
    max_exposure_pct: float = 70.0        # Máximo invertido (30% siempre en cash)
    max_asset_class_exposure_pct: float = 40.0  # Máximo en una sola clase

    # Consenso mínimo para ejecutar
    min_consensus: ConsensusLevel = ConsensusLevel.MAJORITY

    # Circuit breaker
    max_daily_loss_pct: float = 5.0       # Detener si pierde 5% en un día
    max_drawdown_pct: float = 15.0        # Detener si drawdown desde máximo >15%

    def validate_order(
        self,
        order: TradingOrder,
        portfolio: PortfolioSnapshot,
    ) -> tuple[bool, str]:
        """
        Verifica que una orden cumple todos los constraints.
        Retorna (is_valid, reason_if_invalid).
        """
        # Verificar consenso mínimo
        consensus_order = [
            ConsensusLevel.UNANIMOUS,
            ConsensusLevel.STRONG_MAJORITY,
            ConsensusLevel.MAJORITY,
            ConsensusLevel.DIVIDED,
            ConsensusLevel.DEADLOCK,
        ]
        if consensus_order.index(order.consensus_level) > consensus_order.index(
            self.min_consensus
        ):
            return False, (
                f"Consenso insuficiente: {order.consensus_level.value}, "
                f"mínimo requerido: {self.min_consensus.value}"
            )

        # Verificar tipo de orden permitido
        if order.order_type not in self.allowed_order_types:
            return False, f"Tipo de orden no permitido: {order.order_type}"

        # Verificar límite diario de trades
        if portfolio.daily_trades_executed >= self.max_daily_trades:
            return False, (
                f"Límite diario de trades alcanzado: "
                f"{portfolio.daily_trades_executed}/{self.max_daily_trades}"
            )

        # Verificar circuit breaker
        if abs(portfolio.daily_pnl_pct) >= self.max_daily_loss_pct:
            return False, (
                f"Circuit breaker: pérdida diaria {portfolio.daily_pnl_pct:.1f}% "
                f"excede límite de {self.max_daily_loss_pct}%"
            )

        if portfolio.max_drawdown_pct >= self.max_drawdown_pct:
            return False, (
                f"Circuit breaker: drawdown {portfolio.max_drawdown_pct:.1f}% "
                f"excede límite de {self.max_drawdown_pct}%"
            )

        # Verificar exposición máxima
        cash_pct = portfolio.exposure.get("cash", 0)
        if cash_pct < (100 - self.max_exposure_pct):
            return False, (
                f"Exposición máxima alcanzada: cash es {cash_pct:.1f}%, "
                f"mínimo requerido: {100 - self.max_exposure_pct:.1f}%"
            )

        return True, "OK"


@dataclass
class AgentCapabilityProfile:
    """
    Perfil de capacidades de un agente.
    Define QUÉ puede hacer y con QUÉ restricciones.

    Ejemplo de perfiles:

    Analista Macro:
        capabilities: [READ_NEWS, READ_MARKET_DATA, SEND_MESSAGE, READ_MEMORY, WRITE_MEMORY]
        platforms: []  (no opera en ninguna)
        constraints: None  (no ejecuta órdenes)

    Ejecutor de Stocks (Alpaca):
        capabilities: [READ_MARKET_DATA, READ_PORTFOLIO, PLACE_ORDER_STOCK,
                       CANCEL_ORDER, SET_STOP_LOSS, SET_TAKE_PROFIT, SEND_MESSAGE]
        platforms: [ALPACA]
        asset_classes: [STOCK, ETF]
        constraints: ExecutorConstraints(...)

    Ejecutor de Crypto (Binance):
        capabilities: [READ_MARKET_DATA, READ_PORTFOLIO, PLACE_ORDER_CRYPTO,
                       CANCEL_ORDER, SET_STOP_LOSS, SET_TAKE_PROFIT, SEND_MESSAGE]
        platforms: [BINANCE]
        asset_classes: [CRYPTO]
        constraints: ExecutorConstraints(...)
    """
    agent_id: str = ""
    role: str = ""  # "macro_analyst", "stock_executor", "cio", "secretary", etc.
    capabilities: set[Capability] = field(default_factory=set)
    # Plataformas a las que tiene acceso (vacío = ninguna)
    platforms: list[Platform] = field(default_factory=list)
    # Clases de activo que puede operar (vacío = ninguna)
    asset_classes: list[AssetClass] = field(default_factory=list)
    # Constraints de ejecución (solo para ejecutores)
    constraints: ExecutorConstraints | None = None

    def can(self, capability: Capability) -> bool:
        """¿Tiene esta capacidad?"""
        return capability in self.capabilities

    def can_operate_on(self, platform: Platform) -> bool:
        """¿Puede operar en esta plataforma?"""
        return platform in self.platforms

    def can_trade(self, asset_class: AssetClass) -> bool:
        """¿Puede operar esta clase de activo?"""
        return asset_class in self.asset_classes


# =============================================================================
# 8. ORDER ROUTER - Asignación de órdenes al ejecutor correcto
# =============================================================================
class OrderRouter:
    """
    Rutea órdenes al ejecutor correcto basándose en asset_class y platform.

    Similar al "expedidor" en un restaurante: recibe la comanda del
    Secretary y la envía a la estación (ejecutor) correcta.

    Reglas de routing:
    - STOCK/ETF → Ejecutor Alpaca
    - CRYPTO → Ejecutor Binance (primario) o Kraken (fallback)
    - Si no hay ejecutor disponible → orden rechazada
    """

    def __init__(self):
        self._executor_profiles: dict[str, AgentCapabilityProfile] = {}
        # Mapeo de asset_class → ejecutores disponibles (orden de preferencia)
        self._routing_table: dict[AssetClass, list[str]] = {}

    def register_executor(self, profile: AgentCapabilityProfile) -> None:
        """Registra un ejecutor con su perfil de capacidades."""
        self._executor_profiles[profile.agent_id] = profile
        for asset_class in profile.asset_classes:
            if asset_class not in self._routing_table:
                self._routing_table[asset_class] = []
            if profile.agent_id not in self._routing_table[asset_class]:
                self._routing_table[asset_class].append(profile.agent_id)

    def route(self, order: TradingOrder) -> TradingOrder:
        """Asigna ejecutor y plataforma a una orden. Modifica in-place."""
        executors = self._routing_table.get(order.asset_class, [])

        if not executors:
            error_msg = (
                f"No hay ejecutor disponible para {order.asset_class.value}"
            )
            order.error_message = error_msg
            order.change_status(
                OrderStatus.CONSTRAINT_REJECTED,
                changed_by="order_router",
                reason=error_msg,
            )
            return order

        # Asignar al primer ejecutor disponible (se puede sofisticar)
        executor_id = executors[0]
        profile = self._executor_profiles[executor_id]

        order.assigned_executor = executor_id
        order.assigned_platform = profile.platforms[0] if profile.platforms else None
        order.change_status(
            OrderStatus.VALIDATING,
            changed_by="order_router",
            reason=f"Assigned to {executor_id} on {order.assigned_platform}",
        )

        return order

    def get_routing_table(self) -> dict[str, list[str]]:
        """Retorna la tabla de routing para debugging."""
        return {k.value: v for k, v in self._routing_table.items()}


# =============================================================================
# 9. PREDEFINED AGENT PROFILES
# =============================================================================
def create_analyst_profile(agent_id: str, role: str) -> AgentCapabilityProfile:
    """
    Crea un perfil estándar de analista.
    Solo lectura + comunicación. CERO acceso a trading.
    """
    return AgentCapabilityProfile(
        agent_id=agent_id,
        role=role,
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_NEWS,
            Capability.READ_PORTFOLIO,   # Solo lectura, para contextualizar análisis
            Capability.READ_MEMORY,
            Capability.WRITE_MEMORY,
            Capability.SEND_MESSAGE,
        },
        platforms=[],       # No opera en ninguna plataforma
        asset_classes=[],   # No tradea nada
        constraints=None,   # No necesita constraints de ejecución
    )


def create_stock_executor_profile(
    agent_id: str = "stock_executor",
) -> AgentCapabilityProfile:
    """Ejecutor de stocks/ETFs vía Alpaca. NO puede tocar crypto."""
    return AgentCapabilityProfile(
        agent_id=agent_id,
        role="stock_executor",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.PLACE_ORDER_STOCK,
            Capability.CANCEL_ORDER,
            Capability.SET_STOP_LOSS,
            Capability.SET_TAKE_PROFIT,
            Capability.CLOSE_POSITION,
            Capability.SEND_MESSAGE,
            Capability.WRITE_MEMORY,
        },
        platforms=[Platform.ALPACA],
        asset_classes=[AssetClass.STOCK, AssetClass.ETF],
        constraints=ExecutorConstraints(
            max_order_pct=2.0,
            max_order_value_usd=500.0,
            max_daily_trades=10,
            max_daily_volume_usd=2000.0,
            max_positions=10,
            max_exposure_pct=70.0,
            max_asset_class_exposure_pct=40.0,
            min_consensus=ConsensusLevel.MAJORITY,
            max_daily_loss_pct=5.0,
            max_drawdown_pct=15.0,
        ),
    )


def create_crypto_executor_profile(
    agent_id: str = "crypto_executor",
    platform: Platform = Platform.BINANCE,
) -> AgentCapabilityProfile:
    """Ejecutor de crypto. NO puede tocar stocks."""
    return AgentCapabilityProfile(
        agent_id=agent_id,
        role="crypto_executor",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.PLACE_ORDER_CRYPTO,
            Capability.CANCEL_ORDER,
            Capability.SET_STOP_LOSS,
            Capability.SET_TAKE_PROFIT,
            Capability.CLOSE_POSITION,
            Capability.SEND_MESSAGE,
            Capability.WRITE_MEMORY,
        },
        platforms=[platform],
        asset_classes=[AssetClass.CRYPTO],
        constraints=ExecutorConstraints(
            max_order_pct=1.5,           # Más conservador en crypto
            max_order_value_usd=300.0,
            max_daily_trades=8,
            max_daily_volume_usd=1500.0,
            max_positions=8,
            max_exposure_pct=60.0,       # Más conservador
            max_asset_class_exposure_pct=35.0,
            min_consensus=ConsensusLevel.STRONG_MAJORITY,  # Necesita más consenso
            max_daily_loss_pct=4.0,      # Más conservador
            max_drawdown_pct=12.0,
        ),
    )


def create_cio_profile(agent_id: str = "cio") -> AgentCapabilityProfile:
    """Chief Investment Officer / Árbitro. Solo lectura + comunicación."""
    return AgentCapabilityProfile(
        agent_id=agent_id,
        role="cio",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.READ_MEMORY,
            Capability.WRITE_MEMORY,
            Capability.SEND_MESSAGE,
        },
        platforms=[],
        asset_classes=[],
        constraints=None,
    )


def create_secretary_profile(agent_id: str = "secretary") -> AgentCapabilityProfile:
    """Secretary / Editor del memo final. Solo lectura + comunicación."""
    return AgentCapabilityProfile(
        agent_id=agent_id,
        role="secretary",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.READ_MEMORY,
            Capability.WRITE_MEMORY,
            Capability.SEND_MESSAGE,
        },
        platforms=[],
        asset_classes=[],
        constraints=None,
    )


def create_portfolio_manager_profile(
    agent_id: str = "portfolio_manager",
) -> AgentCapabilityProfile:
    """
    Portfolio Manager - monitorea posiciones y ejecuta reglas mecánicas.
    Puede cerrar posiciones pero NO abrir nuevas.
    """
    return AgentCapabilityProfile(
        agent_id=agent_id,
        role="portfolio_manager",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.CLOSE_POSITION,     # Puede cerrar (stop-loss, take-profit)
            Capability.SET_STOP_LOSS,
            Capability.SET_TAKE_PROFIT,
            Capability.CANCEL_ORDER,
            Capability.SEND_MESSAGE,
            Capability.WRITE_MEMORY,
            Capability.READ_MEMORY,
        },
        # Acceso a TODAS las plataformas para monitorear y cerrar
        platforms=[Platform.ALPACA, Platform.BINANCE, Platform.KRAKEN],
        asset_classes=[AssetClass.STOCK, AssetClass.ETF, AssetClass.CRYPTO],
        constraints=ExecutorConstraints(
            max_order_pct=0.0,            # NO puede abrir posiciones nuevas
            max_order_value_usd=0.0,
            max_daily_trades=20,          # Más trades permitidos (stop-loss mecánicos)
            max_daily_volume_usd=50000.0, # Alto porque cierra posiciones existentes
            max_positions=0,              # No abre posiciones
            max_exposure_pct=100.0,       # No aplica (solo cierra)
            max_asset_class_exposure_pct=100.0,
            min_consensus=ConsensusLevel.DEADLOCK,  # No necesita consenso (reglas mecánicas)
            max_daily_loss_pct=100.0,     # No aplica
            max_drawdown_pct=100.0,
        ),
    )
