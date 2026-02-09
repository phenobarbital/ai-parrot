"""
Trading Swarm - Committee Deliberation Orchestrator (v2)
========================================================

Orquesta el proceso deliberativo completo del comité de inversión:
    1. Polinización cruzada (cross-pollination)
    2. Enfrentamiento y deliberación (CIO-led debate)
    3. Consenso y generación del memo (Secretary)

Integración con Parrot Agent (BaseBot / BaseAgent):
    - Los agentes se crean UNA VEZ con system_prompt_template fijo
    - El contexto dinámico se pasa via el parámetro `system_prompt`
      del método ask(), que COMPLEMENTA (no reemplaza) el template
    - structured_output acepta un Pydantic BaseModel o StructuredOutputConfig
    - ask() retorna AIMessage cuyo .content contiene el modelo parseado

Dependencias:
    - trading_swarm_schemas.py (dataclasses de datos)
    - trading_swarm_prompts.py (system prompts y grafo de polinización)
"""

from __future__ import annotations
from typing import Any
import asyncio
import json
import uuid
from dataclasses import asdict
from pydantic import BaseModel, Field
from navconfig.logging import logging
from .schemas import (
    AgentMessage,
    AssetClass,
    ConsensusLevel,
    ExecutorConstraints,
    MessageBus,
    MessageType,
    Platform,
    PortfolioSnapshot,
    ResearchBriefing,
    TradingOrder,
    OrderStatus,
)
from .prompts import (
    ANALYST_MACRO,
    ANALYST_EQUITY,
    ANALYST_CRYPTO,
    ANALYST_SENTIMENT,
    ANALYST_RISK,
    CIO_ARBITER,
    SECRETARY_MEMO_WRITER,
    CROSS_POLLINATION_GRAPH,
    MODEL_RECOMMENDATIONS,
)



# =============================================================================
# PYDANTIC MODELS para structured_output
# =============================================================================
# Estos modelos se pasan a Agent.ask(structured_output=...) para que
# Parrot fuerce al LLM a devolver JSON tipado.
# =============================================================================
class RecommendationOutput(BaseModel):
    """Una recomendación individual de un analista."""
    asset: str
    asset_class: str
    signal: str
    confidence: float = Field(ge=0.0, le=1.0)
    time_horizon: str
    target_price: float | None = None
    stop_loss_price: float | None = None
    rationale: str
    data_points: list[str] = Field(default_factory=list)


class AnalystReportOutput(BaseModel):
    """Output estructurado de un analista del comité."""
    analyst_id: str
    analyst_role: str
    version: int = 1
    market_outlook: str
    recommendations: list[RecommendationOutput]
    overall_confidence: float = Field(ge=0.0, le=1.0)
    key_risks: list[str]
    key_catalysts: list[str]
    cross_pollination_received_from: list[str] = Field(default_factory=list)
    revision_notes: str = ""


class RiskPortfolioSummary(BaseModel):
    """Resumen de riesgo del portfolio (solo del risk analyst)."""
    var_1d_95_usd: float = 0.0
    max_position_weight_pct: float = 0.0
    top_correlation_pair: str = ""
    distance_to_max_drawdown_pct: float = 0.0
    distance_to_max_daily_loss_pct: float = 0.0
    risk_budget_used_pct: float = 0.0
    recommendation: str = "hold_steady"


class RiskAnalystReportOutput(AnalystReportOutput):
    """Output del risk analyst con portfolio_risk_summary adicional."""
    portfolio_risk_summary: RiskPortfolioSummary = Field(
        default_factory=RiskPortfolioSummary
    )


class ContradictionOutput(BaseModel):
    """Una contradicción identificada por el CIO."""
    between: list[str]
    topic: str
    description: str
    severity: str


class GapOutput(BaseModel):
    """Un gap identificado por el CIO."""
    description: str
    should_be_addressed_by: list[str]
    severity: str


class RevisionRequestOutput(BaseModel):
    """Una solicitud de revisión emitida por el CIO."""
    target_analyst_id: str
    target_report_id: str
    contradiction_with: str | None = None
    gap_description: str
    specific_questions: list[str]


class ConsensusAssessmentOutput(BaseModel):
    """Un resumen del consenso emitido por el CIO."""
    asset: str
    consensus_level: str
    agreed_signal: str | None = None
    dissenting_analysts: list[str] = Field(default_factory=list)
    dissent_summary: str = ""


class CIOAssessmentOutput(BaseModel):
    """Output estructurado del CIO/Árbitro."""
    round_number: int
    contradictions_found: list[ContradictionOutput]
    gaps_identified: list[GapOutput]
    revision_requests: list[RevisionRequestOutput]
    consensus_assessment: list[ConsensusAssessmentOutput]
    overall_assessment: str
    ready_for_memo: bool
    reason_not_ready: str | None = None


class PortfolioImpactOutput(BaseModel):
    """Un resumen del impacto en el portfolio emitido por el CIO."""
    new_exposure_pct: float = 0.0
    total_exposure_after_pct: float = 0.0
    constraint_adjustments_made: str | None = None


class MemoRecommendationOutput(BaseModel):
    """Una recomendación del memo final."""
    id: str
    asset: str
    asset_class: str
    preferred_platform: str | None = None
    signal: str
    action: str
    sizing_pct: float
    max_position_value: float | None = None
    entry_price_limit: float | None = None
    stop_loss: float
    take_profit: float | None = None
    trailing_stop_pct: float | None = None
    consensus_level: str
    bull_case: str
    bear_case: str
    time_horizon: str
    analyst_votes: dict[str, str]


class InvestmentMemoOutput(BaseModel):
    """Output estructurado del Secretary."""
    id: str
    created_at: str
    valid_until: str
    executive_summary: str
    market_conditions: str
    recommendations: list[MemoRecommendationOutput]
    deliberation_rounds: int
    final_consensus: str
    source_report_ids: list[str]
    deliberation_round_ids: list[str]
    risk_warnings: list[str] = Field(default_factory=list)
    portfolio_impact: PortfolioImpactOutput = Field(
        default_factory=PortfolioImpactOutput
    )


# =============================================================================
# ANALYST REGISTRY
# =============================================================================
ANALYST_CONFIG: dict[str, dict[str, Any]] = {
    "macro_analyst": {
        "name": "Macro Analyst",
        "agent_id": "macro_analyst",
        "llm": MODEL_RECOMMENDATIONS["macro_analyst"]["model"],
        "system_prompt": ANALYST_MACRO,
        "output_model": AnalystReportOutput,
    },
    "equity_analyst": {
        "name": "Equity & ETF Analyst",
        "agent_id": "equity_analyst",
        "llm": MODEL_RECOMMENDATIONS["equity_analyst"]["model"],
        "system_prompt": ANALYST_EQUITY,
        "output_model": AnalystReportOutput,
    },
    "crypto_analyst": {
        "name": "Crypto & DeFi Analyst",
        "agent_id": "crypto_analyst",
        "llm": MODEL_RECOMMENDATIONS["crypto_analyst"]["model"],
        "system_prompt": ANALYST_CRYPTO,
        "output_model": AnalystReportOutput,
    },
    "sentiment_analyst": {
        "name": "Sentiment & Flow Analyst",
        "agent_id": "sentiment_analyst",
        "llm": MODEL_RECOMMENDATIONS["sentiment_analyst"]["model"],
        "system_prompt": ANALYST_SENTIMENT,
        "output_model": AnalystReportOutput,
    },
    "risk_analyst": {
        "name": "Risk & Quantitative Analyst",
        "agent_id": "risk_analyst",
        "llm": MODEL_RECOMMENDATIONS["risk_analyst"]["model"],
        "system_prompt": ANALYST_RISK,
        "output_model": RiskAnalystReportOutput,
    },
}


# =============================================================================
# HELPERS: Construcción de contexto dinámico
# =============================================================================
# Estas funciones construyen bloques XML con datos JSON que se pasan
# via system_prompt= en ask(). Esto COMPLEMENTA el system_prompt_template
# que ya contiene el rol estático, mandato, instrucciones y formato.
#
# El system_prompt_template del agente tiene placeholders como:
#   <your_research_briefing>
#   {{research_briefing_json}}
#   </your_research_briefing>
#
# Pero en v2, esos placeholders se ignoran porque el contexto dinámico
# se pasa como system_prompt= adicional con sus propios XML tags.
# Los prompts deben actualizarse para no incluir los placeholders,
# o el orquestador simplemente los sobrescribe con datos reales.
# =============================================================================

def _to_json(data: Any) -> str:
    """Serializa a JSON compacto para inyección en prompts."""
    if data is None:
        return "null"
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


def _build_context_block(tag: str, data: Any) -> str:
    """
    Construye un bloque XML con datos JSON.

    Ejemplo:
        _build_context_block("current_portfolio", {"cash": 5000})
        →  <current_portfolio>
           {"cash": 5000}
           </current_portfolio>
    """
    content = _to_json(data)
    return f"\n<{tag}>\n{content}\n</{tag}>\n"


def _build_analyst_context(
    briefing_dict: dict,
    track_record: dict,
    portfolio_dict: dict,
    cross_pollination_reports: dict[str, Any],
    constraints_dict: dict | None = None,
) -> str:
    """
    Construye el contexto dinámico completo para un analista.
    Se pasa via system_prompt= en ask().
    """
    ctx = ""
    ctx += _build_context_block("your_research_briefing", briefing_dict)
    ctx += _build_context_block("your_track_record", track_record)
    ctx += _build_context_block("current_portfolio", portfolio_dict)
    ctx += _build_context_block("cross_pollination", cross_pollination_reports)
    if constraints_dict:
        ctx += _build_context_block("portfolio_constraints", constraints_dict)
    return ctx


def _build_cio_context(
    all_reports: dict[str, Any],
    previous_rounds: list[dict],
) -> str:
    """Construye el contexto dinámico para el CIO."""
    ctx = ""
    ctx += _build_context_block("analyst_reports", all_reports)
    ctx += _build_context_block("deliberation_history", previous_rounds)
    return ctx


def _build_secretary_context(
    final_reports: dict[str, Any],
    cio_assessment: dict,
    portfolio_dict: dict,
    constraints_dict: dict,
) -> str:
    """Construye el contexto dinámico para el Secretary."""
    ctx = ""
    ctx += _build_context_block("analyst_reports", final_reports)
    ctx += _build_context_block("cio_assessment", cio_assessment)
    ctx += _build_context_block("current_portfolio", portfolio_dict)
    ctx += _build_context_block("portfolio_constraints", constraints_dict)
    return ctx


# =============================================================================
# DELIBERATION ORCHESTRATOR
# =============================================================================

class CommitteeDeliberation:
    """
    Orquesta el proceso deliberativo completo del comité de inversión.

    Integración con Parrot Agent:
        - Los agentes se crean en configure() con system_prompt_template
          que contiene la parte ESTÁTICA (rol, mandato, instrucciones, formato)
        - En cada llamada a ask(), el contexto DINÁMICO (briefings, portfolio,
          cross-pollination, reports) se pasa via el parámetro system_prompt=
          que COMPLEMENTA el template, no lo reemplaza
        - Los agentes se reutilizan entre ciclos sin recrearlos
        - use_tools=False, use_conversation_history=False y
          use_vector_context=False se pasan explícitamente ya que estos
          agentes no necesitan tools, historial ni vector search

    Ciclo de vida:
        1. configure() → Inicializa los 7 agentes una sola vez
        2. run_deliberation(briefings, portfolio) → Ejecuta el ciclo completo
        3. Resultado: InvestmentMemoOutput listo para la cola de órdenes

    Uso:
        from parrot.bots import Agent

        committee = CommitteeDeliberation(
            message_bus=bus,
            agent_class=Agent,
        )
        await committee.configure()

        # Reutilizable N veces (ej: 3 ciclos/día via cron)
        memo = await committee.run_deliberation(
            briefings=briefings_dict,
            portfolio=portfolio_snapshot,
            constraints=executor_constraints,
        )
    """

    MAX_DELIBERATION_ROUNDS = 3

    def __init__(
        self,
        message_bus: MessageBus,
        agent_class: type | None = None,
    ):
        self.bus = message_bus
        self._agent_class = agent_class
        self._analysts: dict[str, Any] = {}   # agent_id → Agent instance
        self._cio: Any = None
        self._secretary: Any = None
        # Estado de la deliberación actual (se resetea en cada ciclo)
        self._current_reports: dict[str, AnalystReportOutput] = {}
        self._deliberation_rounds: list[CIOAssessmentOutput] = []
        self._logger = logging.getLogger("trading_swarm.deliberation")

    # -----------------------------------------------------------------
    # CONFIGURACIÓN (una sola vez)
    # -----------------------------------------------------------------

    async def configure(self) -> None:
        """
        Inicializa todos los agentes del comité.
        Llamar UNA VEZ al inicio. Los agentes se reutilizan entre ciclos.

        Cada agente recibe su system_prompt_template con la parte estática:
        rol, mandato, instrucciones y formato de output. Los datos dinámicos
        (briefings, portfolio, etc.) se inyectan en cada ask() via
        el parámetro system_prompt=.
        """
        if self._agent_class is None:
            raise RuntimeError(
                "agent_class no proporcionado. "
                "Pasa tu clase Agent de Parrot al constructor."
            )

        # Crear los 5 analistas
        for analyst_id, config in ANALYST_CONFIG.items():
            agent = self._agent_class(
                name=config["name"],
                agent_id=config["agent_id"],
                llm=config["llm"],
                system_prompt=config["system_prompt"],
                use_tools=False,
            )
            await agent.configure()
            self._analysts[analyst_id] = agent
            self._logger.info(f"Analista configurado: {analyst_id}")

        # Crear CIO
        self._cio = self._agent_class(
            name="Chief Investment Officer",
            agent_id="cio",
            llm=MODEL_RECOMMENDATIONS["cio"]["model"],
            system_prompt=CIO_ARBITER,
            use_tools=False,
        )
        await self._cio.configure()
        self._logger.info("CIO configurado")

        # Crear Secretary
        self._secretary = self._agent_class(
            name="Investment Committee Secretary",
            agent_id="secretary",
            llm=MODEL_RECOMMENDATIONS["secretary"]["model"],
            system_prompt=SECRETARY_MEMO_WRITER,
            use_tools=False,
        )
        await self._secretary.configure()
        self._logger.info("Secretary configurado")

    # -----------------------------------------------------------------
    # EJECUCIÓN PRINCIPAL
    # -----------------------------------------------------------------

    async def run_deliberation(
        self,
        briefings: dict[str, ResearchBriefing],
        portfolio: PortfolioSnapshot,
        constraints: ExecutorConstraints,
    ) -> InvestmentMemoOutput:
        """
        Ejecuta el ciclo deliberativo completo.

        Args:
            briefings: Dict de analyst_id → ResearchBriefing (de los crews)
            portfolio: Estado actual del portfolio
            constraints: Constraints del ejecutor

        Returns:
            InvestmentMemoOutput listo para convertir en TradingOrders
        """
        self._logger.info("=" * 60)
        self._logger.info("INICIO DE CICLO DELIBERATIVO")
        self._logger.info("=" * 60)

        # Reset estado para este ciclo
        self._current_reports = {}
        self._deliberation_rounds = []

        portfolio_dict = asdict(portfolio)
        constraints_dict = asdict(constraints)

        # ── FASE 1: POLINIZACIÓN CRUZADA ─────────────────────────
        self._logger.info("FASE 1: Polinización cruzada")
        await self._phase_cross_pollination(
            briefings, portfolio_dict, constraints_dict
        )

        # ── FASE 2: DELIBERACIÓN CIO-LED (hasta 3 rondas) ───────
        self._logger.info("FASE 2: Deliberación")
        await self._phase_deliberation(
            briefings, portfolio_dict, constraints_dict
        )

        # ── FASE 3: GENERACIÓN DEL MEMO (Secretary) ─────────────
        self._logger.info("FASE 3: Generación del memo")
        memo = await self._phase_memo_generation(
            portfolio_dict, constraints_dict
        )

        # Notificar al message bus
        await self.bus.send(AgentMessage(
            msg_type=MessageType.INVESTMENT_MEMO,
            sender="secretary",
            phase="execution",
            priority=1,
            payload=memo.model_dump(),
        ))

        self._logger.info("=" * 60)
        self._logger.info("CICLO DELIBERATIVO COMPLETADO")
        self._logger.info(
            f"Recomendaciones generadas: {len(memo.recommendations)}"
        )
        self._logger.info("=" * 60)

        return memo

    # -----------------------------------------------------------------
    # FASE 1: POLINIZACIÓN CRUZADA
    # -----------------------------------------------------------------

    async def _phase_cross_pollination(
        self,
        briefings: dict[str, ResearchBriefing],
        portfolio_dict: dict,
        constraints_dict: dict,
    ) -> None:
        """
        Polinización cruzada en dos sub-fases paralelas:

        Sub-fase A (paralelo): macro_analyst + sentiment_analyst
            → No dependen de nadie, producen informes primero.

        Sub-fase B (paralelo): equity_analyst + crypto_analyst + risk_analyst
            → Reciben los informes de fase A como contexto adicional.

        Grafo de dependencias (CROSS_POLLINATION_GRAPH):
            macro_analyst:     ← [independiente]
            sentiment_analyst: ← [independiente]
            equity_analyst:    ← [macro_analyst, sentiment_analyst]
            crypto_analyst:    ← [macro_analyst, sentiment_analyst]
            risk_analyst:      ← [macro_analyst]
        """

        # ── Sub-fase A: Analistas independientes ─────────────────
        phase_a_ids = [
            aid for aid, deps in CROSS_POLLINATION_GRAPH.items()
            if len(deps) == 0
        ]
        self._logger.info(f"  Sub-fase A (independientes): {phase_a_ids}")

        phase_a_results = await asyncio.gather(
            *[
                self._run_analyst(
                    analyst_id=aid,
                    briefing=briefings.get(aid),
                    portfolio_dict=portfolio_dict,
                    constraints_dict=constraints_dict,
                    cross_pollination_reports={},
                )
                for aid in phase_a_ids
            ],
            return_exceptions=True,
        )

        for aid, result in zip(phase_a_ids, phase_a_results):
            self._store_analyst_result(aid, result)

        # ── Sub-fase B: Analistas dependientes ───────────────────
        phase_b_ids = [
            aid for aid, deps in CROSS_POLLINATION_GRAPH.items()
            if len(deps) > 0
        ]
        self._logger.info(f"  Sub-fase B (dependientes): {phase_b_ids}")

        phase_b_results = await asyncio.gather(
            *[
                self._run_analyst(
                    analyst_id=aid,
                    briefing=briefings.get(aid),
                    portfolio_dict=portfolio_dict,
                    constraints_dict=constraints_dict,
                    cross_pollination_reports={
                        dep_id: self._current_reports[dep_id].model_dump()
                        for dep_id in CROSS_POLLINATION_GRAPH[aid]
                        if dep_id in self._current_reports
                    },
                )
                for aid in phase_b_ids
            ],
            return_exceptions=True,
        )

        for aid, result in zip(phase_b_ids, phase_b_results):
            self._store_analyst_result(aid, result)

        # Notificar al bus
        for aid, report in self._current_reports.items():
            await self.bus.send(AgentMessage(
                msg_type=MessageType.INDIVIDUAL_REPORT,
                sender=aid,
                phase="cross_pollination",
                payload=report.model_dump(),
            ))

    # -----------------------------------------------------------------
    # FASE 2: DELIBERACIÓN CIO-LED
    # -----------------------------------------------------------------
    async def _phase_deliberation(
        self,
        briefings: dict[str, ResearchBriefing],
        portfolio_dict: dict,
        constraints_dict: dict,
    ) -> None:
        """
        Loop de deliberación de hasta MAX_DELIBERATION_ROUNDS rondas.

        En cada ronda:
        1. CIO recibe los 5 informes + historial → detecta problemas
        2. Si ready_for_memo → break
        3. Si no → analistas afectados revisan en paralelo
        4. Repetir

        En la última ronda el CIO DEBE aprobar (desacuerdo se preserva
        como información, no como bloqueo).
        """
        for round_num in range(1, self.MAX_DELIBERATION_ROUNDS + 1):
            self._logger.info(f"  Ronda de deliberación {round_num}")

            # ── CIO evalúa ───────────────────────────────────────
            cio_assessment = await self._run_cio(round_num)
            self._deliberation_rounds.append(cio_assessment)

            self._logger.info(
                f"    Contradicciones: "
                f"{len(cio_assessment.contradictions_found)}, "
                f"Gaps: {len(cio_assessment.gaps_identified)}, "
                f"Revisiones: "
                f"{len(cio_assessment.revision_requests)}, "
                f"Listo: {cio_assessment.ready_for_memo}"
            )

            await self.bus.send(AgentMessage(
                msg_type=(
                    MessageType.DELIBERATION_COMPLETE
                    if cio_assessment.ready_for_memo
                    else MessageType.REVISION_REQUEST
                ),
                sender="cio",
                phase="deliberation",
                payload=cio_assessment.model_dump(),
            ))

            # ── ¿Listo? ─────────────────────────────────────────
            if cio_assessment.ready_for_memo:
                self._logger.info(
                    f"  ✓ Consenso alcanzado en ronda {round_num}"
                )
                break

            # ── Ejecutar revisiones (paralelo) ───────────────────
            if not cio_assessment.revision_requests:
                self._logger.info("  Sin revisiones pendientes → avanzando")
                break

            revision_ids = []
            revision_tasks = []

            for rev_req in cio_assessment.revision_requests:
                aid = rev_req.target_analyst_id
                if aid not in self._analysts:
                    self._logger.warning(
                        f"  Revisión a {aid}: agente no existe"
                    )
                    continue

                revision_ids.append(aid)

                # En revisión, el analista recibe TODOS los demás
                # informes como cross-pollination + pregunta del CIO
                all_other_reports = {
                    other_id: self._current_reports[other_id].model_dump()
                    for other_id in self._current_reports
                    if other_id != aid
                }

                revision_tasks.append(
                    self._run_analyst(
                        analyst_id=aid,
                        briefing=briefings.get(aid),
                        portfolio_dict=portfolio_dict,
                        constraints_dict=constraints_dict,
                        cross_pollination_reports=all_other_reports,
                        revision_question=self._build_revision_question(
                            rev_req, round_num
                        ),
                        version=round_num + 1,
                    )
                )

            if revision_tasks:
                revision_results = await asyncio.gather(
                    *revision_tasks,
                    return_exceptions=True
                )
                for aid, result in zip(revision_ids, revision_results):
                    if isinstance(result, Exception):
                        self._logger.error(
                            f"    Error revisión {aid}: {result}"
                        )
                    else:
                        self._current_reports[aid] = result
                        self._logger.info(
                            f"    ✓ {aid} revisó informe "
                            f"(v{result.version})"
                        )
                        await self.bus.send(AgentMessage(
                            msg_type=MessageType.REVISED_REPORT,
                            sender=aid,
                            phase="deliberation",
                            payload=result.model_dump(),
                        ))
        else:
            self._logger.warning(
                f"  Máximo de rondas "
                f"({self.MAX_DELIBERATION_ROUNDS}) alcanzado. "
                "Procediendo con consenso parcial."
            )

    # -----------------------------------------------------------------
    # FASE 3: GENERACIÓN DEL MEMO
    # -----------------------------------------------------------------

    async def _phase_memo_generation(
        self,
        portfolio_dict: dict,
        constraints_dict: dict,
    ) -> InvestmentMemoOutput:
        """
        El Secretary sintetiza todos los informes y la evaluación
        del CIO en un Investment Memo accionable.

        El contexto dinámico (informes, evaluación CIO, portfolio,
        constraints) se pasa via system_prompt= en ask().
        El system_prompt_template del Secretary ya tiene el rol,
        mandato, reglas de sizing y formato de output.
        """
        final_reports = {
            aid: report.model_dump()
            for aid, report in self._current_reports.items()
        }
        last_cio = (
            self._deliberation_rounds[-1].model_dump()
            if self._deliberation_rounds
            else {}
        )

        # Contexto dinámico complementa el system_prompt_template
        dynamic_context = _build_secretary_context(
            final_reports=final_reports,
            cio_assessment=last_cio,
            portfolio_dict=portfolio_dict,
            constraints_dict=constraints_dict,
        )

        question = (
            "Based on all the analyst reports and the CIO's final "
            "assessment provided in your context, generate the "
            "Investment Memo now. "
            "Apply all sizing rules and risk management constraints. "
            "Include ONLY recommendations with MAJORITY consensus or "
            "higher. Set appropriate validity period based on the "
            "shortest time horizon among recommendations."
        )

        self._logger.info("  Secretary generando memo...")
        response = await self._secretary.ask(
            question,
            system_prompt=dynamic_context,
            structured_output=InvestmentMemoOutput,
            use_tools=False,
            use_conversation_history=False,
            use_vector_context=False,
        )

        memo: InvestmentMemoOutput = response.content
        self._logger.info(
            f"  ✓ Memo generado: {len(memo.recommendations)} "
            f"recomendaciones accionables"
        )
        return memo

    # -----------------------------------------------------------------
    # EJECUCIÓN DE AGENTES INDIVIDUALES
    # -----------------------------------------------------------------

    async def _run_analyst(
        self,
        analyst_id: str,
        briefing: ResearchBriefing | None,
        portfolio_dict: dict,
        constraints_dict: dict,
        cross_pollination_reports: dict[str, Any],
        revision_question: str | None = None,
        version: int = 1,
    ) -> AnalystReportOutput:
        """
        Ejecuta un analista individual.

        El agente ya tiene su system_prompt_template fijo con el rol,
        mandato, instrucciones y formato de output.

        Aquí construimos el contexto dinámico (briefing, portfolio,
        cross-pollination) y lo pasamos via system_prompt= en ask(),
        que lo CONCATENA al final del system prompt generado.

        Args:
            analyst_id: ID del analista en ANALYST_CONFIG
            briefing: ResearchBriefing del crew (puede ser None)
            portfolio_dict: Estado del portfolio serializado
            constraints_dict: Constraints (solo para risk_analyst)
            cross_pollination_reports: Informes de otros analistas
            revision_question: Pregunta de revisión del CIO
            version: Versión del informe (se incrementa en revisiones)

        Returns:
            AnalystReportOutput parseado por Parrot
        """
        agent = self._analysts[analyst_id]
        config = ANALYST_CONFIG[analyst_id]

        # Datos del briefing
        briefing_dict = asdict(briefing) if briefing else {}
        track_record = (
            briefing.analyst_track_record if briefing else {}
        )

        # Contexto dinámico → system_prompt= en ask()
        dynamic_context = _build_analyst_context(
            briefing_dict=briefing_dict,
            track_record=track_record,
            portfolio_dict=portfolio_dict,
            cross_pollination_reports=cross_pollination_reports,
            constraints_dict=(
                constraints_dict if analyst_id == "risk_analyst"
                else None
            ),
        )

        # Pregunta (normal o de revisión)
        if revision_question:
            question = revision_question
        else:
            question = (
                "Analyze the research briefing and market conditions "
                "provided in your context. Generate your analyst report "
                "with specific, actionable recommendations. "
                f"This is version {version} of your report."
            )
            if cross_pollination_reports:
                sources = ", ".join(cross_pollination_reports.keys())
                question += (
                    f" You have received cross-pollination input "
                    f"from: {sources}. "
                    "Integrate their insights where relevant."
                )

        # ask() con system_prompt= que complementa el template
        response = await agent.ask(
            question,
            system_prompt=dynamic_context,
            structured_output=config["output_model"],
            use_tools=False,
            use_conversation_history=False,
            use_vector_context=False,
        )

        report: AnalystReportOutput = response.content
        report.version = version
        return report

    async def _run_cio(
        self, round_number: int
    ) -> CIOAssessmentOutput:
        """
        Ejecuta al CIO para evaluar los informes actuales.

        El system_prompt_template del CIO tiene el rol y las 4 fases
        de evaluación. Los informes y el historial se pasan como
        contexto dinámico via system_prompt=.
        """
        all_reports = {
            aid: report.model_dump()
            for aid, report in self._current_reports.items()
        }
        previous_rounds = [
            r.model_dump() for r in self._deliberation_rounds
        ]

        dynamic_context = _build_cio_context(
            all_reports=all_reports,
            previous_rounds=previous_rounds,
        )

        question = (
            f"This is deliberation round {round_number} "
            f"(maximum {self.MAX_DELIBERATION_ROUNDS}). "
            "Review all 5 analyst reports. "
            "Detect contradictions, identify gaps, "
            "and assess consensus."
        )
        if round_number > 1:
            question += (
                f" Check whether revision requests from round "
                f"{round_number - 1} were adequately addressed."
            )
        if round_number == self.MAX_DELIBERATION_ROUNDS:
            question += (
                " This is the FINAL round. You MUST set "
                "ready_for_memo to true regardless of remaining "
                "disagreements. Mark unresolved items in your "
                "assessment."
            )

        response = await self._cio.ask(
            question,
            system_prompt=dynamic_context,
            structured_output=CIOAssessmentOutput,
            use_tools=False,
            use_conversation_history=False,
            use_vector_context=False,
        )

        assessment: CIOAssessmentOutput = response.content
        assessment.round_number = round_number
        return assessment

    # -----------------------------------------------------------------
    # HELPERS INTERNOS
    # -----------------------------------------------------------------

    def _store_analyst_result(
        self,
        analyst_id: str,
        result: AnalystReportOutput | Exception,
    ) -> None:
        """Almacena resultado de un analista con fallback si falla."""
        if isinstance(result, Exception):
            self._logger.error(f"  ✗ {analyst_id}: {result}")
            self._current_reports[analyst_id] = AnalystReportOutput(
                analyst_id=analyst_id,
                analyst_role=analyst_id.replace("_analyst", ""),
                market_outlook=(
                    f"[ERROR: {analyst_id} failed: {result}]"
                ),
                recommendations=[],
                overall_confidence=0.0,
                key_risks=["Analyst failed to produce report"],
                key_catalysts=[],
            )
        else:
            self._current_reports[analyst_id] = result
            self._logger.info(
                f"  ✓ {analyst_id}: "
                f"{len(result.recommendations)} recs, "
                f"confianza {result.overall_confidence:.0%}"
            )

    def _build_revision_question(
        self,
        rev_req: RevisionRequestOutput,
        round_number: int,
    ) -> str:
        """Pregunta de revisión del CIO para un analista."""
        parts = [
            f"REVISION REQUEST (Round {round_number + 1}):",
            "The CIO has identified issues with your report.",
        ]
        if rev_req.contradiction_with:
            parts.append(
                f"Your analysis contradicts "
                f"{rev_req.contradiction_with}."
            )
        if rev_req.gap_description:
            parts.append(
                f"Gap identified: {rev_req.gap_description}"
            )
        if rev_req.specific_questions:
            parts.append(
                "You must address these specific questions:"
            )
            for i, q in enumerate(rev_req.specific_questions, 1):
                parts.append(f"  {i}. {q}")
        parts.append(
            "\nRevise your report to address these issues. "
            "Focus on the specific points raised — do NOT redo "
            "your entire analysis. Update confidence and "
            "recommendations if warranted. Add revision_notes "
            "explaining what changed."
        )
        return "\n".join(parts)


# =============================================================================
# MEMO → ORDER CONVERSION
# =============================================================================

logger = logging.getLogger("trading_swarm.memo_to_orders")

def memo_to_orders(
    memo: InvestmentMemoOutput,
) -> list[TradingOrder]:
    """
    Convierte un InvestmentMemo en TradingOrders para el OrderRouter.

    Solo convierte recomendaciones con consenso suficiente
    (MAJORITY o superior) y señal != HOLD.
    """
    orders = []
    actionable_consensus = {
        "unanimous", "strong_majority", "majority"
    }
    consensus_map = {
        "unanimous": ConsensusLevel.UNANIMOUS,
        "strong_majority": ConsensusLevel.STRONG_MAJORITY,
        "majority": ConsensusLevel.MAJORITY,
    }
    asset_class_map = {
        "stock": AssetClass.STOCK,
        "etf": AssetClass.ETF,
        "crypto": AssetClass.CRYPTO,
    }
    platform_map = {
        "alpaca": Platform.ALPACA,
        "binance": Platform.BINANCE,
        "kraken": Platform.KRAKEN,
    }
    ttl_map = {
        "scalp": 3600,
        "intraday": 14400,
        "swing": 86400,
        "position": 172800,
        "long_term": 259200,
    }

    for rec in memo.recommendations:
        if rec.consensus_level not in actionable_consensus:
            logger.info(
                f"  Skip {rec.asset}: "
                f"consenso {rec.consensus_level}"
            )
            continue
        if rec.signal == "hold":
            continue

        order = TradingOrder(
            id=str(uuid.uuid4()),
            memo_id=memo.id,
            recommendation_id=rec.id,
            asset=rec.asset,
            asset_class=asset_class_map.get(
                rec.asset_class, AssetClass.STOCK
            ),
            action=rec.action,
            order_type="limit",
            sizing_pct=rec.sizing_pct,
            limit_price=rec.entry_price_limit,
            assigned_platform=platform_map.get(
                rec.preferred_platform
            ) if rec.preferred_platform else None,
            stop_loss=rec.stop_loss,
            take_profit=rec.take_profit,
            trailing_stop_pct=rec.trailing_stop_pct,
            status=OrderStatus.PENDING,
            ttl_seconds=ttl_map.get(rec.time_horizon, 86400),
            consensus_level=consensus_map.get(
                rec.consensus_level, ConsensusLevel.DIVIDED
            ),
        )
        orders.append(order)
        logger.info(
            f"  Orden: {rec.action} {rec.asset} "
            f"({rec.consensus_level}, {rec.sizing_pct}%)"
        )

    return orders


# =============================================================================
# ENTRY POINT
# =============================================================================

async def run_full_cycle(
    agent_class: type,
    briefings: dict[str, ResearchBriefing],
    portfolio: PortfolioSnapshot,
    constraints: ExecutorConstraints,
) -> tuple[InvestmentMemoOutput, list[TradingOrder]]:
    """
    Punto de entrada principal.

    Uso:
        from parrot.bots import Agent
        from trading_swarm_deliberation import run_full_cycle

        memo, orders = await run_full_cycle(
            agent_class=Agent,
            briefings=my_briefings,
            portfolio=my_portfolio,
            constraints=my_constraints,
        )

        # Enviar órdenes al OrderRouter
        for order in orders:
            routed = router.route(order)
            await order_queue.put(routed)
    """
    bus = MessageBus()

    all_agent_ids = list(ANALYST_CONFIG.keys()) + [
        "cio", "secretary", "stock_executor", "crypto_executor",
        "portfolio_manager", "system",
    ]
    for agent_id in all_agent_ids:
        bus.register(agent_id)

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

    orders = memo_to_orders(memo)
    return memo, orders
