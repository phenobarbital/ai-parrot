"""
Ejemplo: Consenso de síntesis con AgentsFlow + DecisionFlowNode.

Tres agentes (Claude Opus, Gemini Pro y Grok) leen el mismo documento,
cada uno produce su propia síntesis en Markdown. Luego, un DecisionFlowNode
en modo BALLOT pone a tres jueces a votar cuál es la versión "más correcta"
del documento (multi-choice). La síntesis ganadora se pasa al agente final,
que la formatea como respuesta y la guarda en disco como archivo Markdown
usando FileManagerTool.

Grafo::

    claude_synth ─┐
    gemini_synth ─┼──▶ consensus (BALLOT) ──▶ writer
    grok_synth   ─┘

Los tres sintetizadores no tienen aristas de entrada → son nodos de inicio y
corren en paralelo. ``writer`` no tiene aristas de salida → es el nodo
terminal y su salida es ``FlowResult.output``.

────────────────────────────────────────────────────────────────────────────
MIGRACIÓN (FEAT-196): este ejemplo vivía en ``examples/crew/`` e importaba
desde ``parrot.bots.flow`` (singular), un paquete ELIMINADO. Se reescribió
contra la API nueva ``parrot.bots.flows`` (DAG event-driven, FEAT-163):

  Antiguo  →  Nuevo
  ----------------------------------------------------------------------
  from parrot.bots.flow import ...      from parrot.bots.flows import AgentsFlow
                                        from parrot.bots.flows.flow.nodes import ...
                                        from parrot.bots.flows.core import AgentNode, FlowContext
  crew.add_agent(a)                     flow.add_node(AgentNode(node_id=..., agent=a))
  crew.add_start_node(targets=[...])    (implícito: nodos sin aristas de entrada)
  crew.add_end_node(name="end")         (implícito: nodos sin aristas de salida)
  crew.task_flow(src, tgt,              flow.add_edge("src", "tgt",
      condition=ON_SUCCESS,                 condition="on_success")
      prompt_builder=fn)                (la API nueva NO tiene prompt_builder por
                                         arista → se sustituye por subclases de
                                         nodo que leen ctx.results: ver
                                         ConsensusDecisionNode y WriterNode abajo)
  crew.run_flow(initial_task=s,         flow.run_flow(FlowContext(initial_task=s))
      max_iterations=50)                (DAG: corre hasta completar, sin tope)
  result.status == "failed"             result.status is FlowStatus.FAILED
  result.completed                      [n.node_id for n in result.nodes ...]
────────────────────────────────────────────────────────────────────────────

Uso:
    source .venv/bin/activate
    python examples/flow/consensus_synthesis_flow.py \
        --input documents/diarization_usage.md \
        --output outputs/consensus_synthesis.md

Requiere las variables de entorno (en .env o exportadas):
    ANTHROPIC_API_KEY  -> Claude Opus / Sonnet
    GOOGLE_API_KEY     -> Gemini 2.5 Pro
    XAI_API_KEY        -> Grok
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from parrot.bots.agent import BasicAgent
from parrot.bots.flows import AgentsFlow
from parrot.bots.flows.core import AgentNode, FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.result import NodeResult, build_node_metadata
from parrot.bots.flows.core.types import AgentLike, DependencyResults
from parrot.bots.flows.flow.nodes import (
    DecisionFlowNode,
    DecisionMode,
    DecisionNodeConfig,
    DecisionType,
)

# Names below are not referenced directly, but subclassing the frozen Pydantic
# Node models in THIS module makes Pydantic re-resolve the inherited field
# annotations (``Set``, ``Optional``, ``AgentTaskMachine``, ``AgentLike``)
# against this module's namespace — so they must be importable here.
__all_field_types__ = (Optional, Set, AgentTaskMachine, AgentLike)
from parrot.tools.filemanager import FileManagerTool
from parrot_tools.file_reader import FileReaderTool


# ---------------------------------------------------------------------------
# Esquema de votación
# ---------------------------------------------------------------------------
class SynthesisVote(BaseModel):
    """Voto de un juez sobre la mejor síntesis.

    `decision` debe ser exactamente uno de: 'claude' | 'gemini' | 'grok'.
    """

    decision: str = Field(
        pattern="^(claude|gemini|grok)$",
        description="Clave del autor de la síntesis ganadora: 'claude', 'gemini' o 'grok'",
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Nivel de confianza en el voto (0.0-1.0)"
    )
    reasoning: str = Field(description="Por qué esa síntesis es la más correcta")


# ---------------------------------------------------------------------------
# Nodos personalizados
# ---------------------------------------------------------------------------
# La API nueva de AgentsFlow no admite ``prompt_builder`` por arista. Para
# inyectar las síntesis upstream en el prompt de un nodo, se subclasa el nodo
# y se lee ``ctx.results`` directamente (mapping node_id -> resultado de
# ``execute()``). Para un AgentNode ese resultado es el dict
# ``{'output', 'response', 'execution_time', 'prompt'}``; para un
# DecisionFlowNode es un ``NodeResult`` cuyo ``.result`` es un ``DecisionResult``.


class ConsensusDecisionNode(DecisionFlowNode):
    """DecisionFlowNode (BALLOT) que vota sobre las síntesis de los upstream.

    Sustituye al antiguo ``prompt_builder=build_decision_prompt``: en lugar de
    usar ``ctx.initial_task`` (que aquí es la ruta del documento), compone la
    papeleta con el texto Markdown producido por cada sintetizador, leído de
    ``ctx.results``.

    Attributes:
        synth_node_ids: node_ids de los sintetizadores upstream, en el orden
            en que se presentan a los jueces.
    """

    synth_node_ids: List[str] = Field(default_factory=list)

    def _compose_ballot_question(self, ctx: FlowContext) -> str:
        """Construye la papeleta con las tres síntesis como contexto."""
        parts = [
            "Tienes que elegir cuál de las siguientes tres síntesis del MISMO "
            "documento es la versión MÁS CORRECTA.\n",
        ]
        for sid in self.synth_node_ids:
            res = ctx.results.get(sid)
            text = (
                res.get("output", "(sin resultado)")
                if isinstance(res, dict)
                else str(res) if res is not None else "(sin resultado)"
            )
            author = sid.replace("_synth", "")
            parts.append(f"\n===== Síntesis de {author} =====\n{text}\n")
        parts.append(
            "\nResponde con un JSON estructurado: "
            "decision ∈ {claude, gemini, grok}, confidence (0-1) y reasoning."
        )
        return "\n".join(parts)

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> NodeResult:
        """Igual que DecisionFlowNode.execute pero con la papeleta compuesta."""
        start = time.time()
        question = self._compose_ballot_question(ctx)
        decision_result = await self.ask(question=question, **kwargs)
        elapsed = time.time() - start
        return NodeResult(
            node_id=self.node_id,
            node_name=self.name,
            task=question,
            result=decision_result,
            metadata=build_node_metadata(
                node_id=self.node_id,
                agent=None,
                response=decision_result,
                output=decision_result.final_decision,
                execution_time=elapsed,
                status="completed",
            ).to_dict(),
            execution_time=elapsed,
        )


class WriterNode(AgentNode):
    """AgentNode final que recibe la síntesis ganadora ya seleccionada.

    Sustituye al antiguo ``prompt_builder=build_writer_prompt``: lee la
    ``DecisionResult`` del nodo de consenso y el Markdown ganador de
    ``ctx.results``, y compone el prompt del writer.

    Attributes:
        decision_node_id: node_id del nodo de consenso (su resultado es un
            NodeResult cuyo ``.result`` es la DecisionResult).
        synth_map: mapping clave-de-voto -> node_id del sintetizador, p.ej.
            ``{"claude": "claude_synth", ...}``.
    """

    decision_node_id: str
    synth_map: Dict[str, str] = Field(default_factory=dict)

    def _build_prompt(self, ctx: FlowContext, deps: DependencyResults) -> str:
        decision_nr = ctx.results.get(self.decision_node_id)
        decision_result = getattr(decision_nr, "result", decision_nr)
        winner = getattr(decision_result, "final_decision", None) or str(decision_result)
        winner_key = str(winner).lower().strip()

        winner_sid = self.synth_map.get(winner_key, "")
        synth_res = ctx.results.get(winner_sid)
        winning_md = (
            synth_res.get("output", "")
            if isinstance(synth_res, dict)
            else str(synth_res) if synth_res is not None else ""
        )

        return (
            f"Autor ganador del consenso: **{winner_key}**\n\n"
            "Síntesis ganadora (Markdown a preservar íntegro):\n"
            "------ INICIO SÍNTESIS GANADORA ------\n"
            f"{winning_md}\n"
            "------ FIN SÍNTESIS GANADORA ------\n\n"
            "Sigue las instrucciones del system prompt: añade encabezado con el "
            "autor, breve preámbulo, conserva el Markdown ganador y guárdalo en "
            "disco con FileManagerTool (operation='create')."
        )


# Resolve deferred annotations now that all field types are importable here.
ConsensusDecisionNode.model_rebuild()
WriterNode.model_rebuild()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def build_synthesizer(
    name: str,
    use_llm: str,
    model: str,
    source_path: Path,
) -> BasicAgent:
    """Crea un agente sintetizador con LLM específico y herramientas de archivo."""
    system_prompt = (
        "Eres un experto en análisis y síntesis de documentos. "
        "Recibirás la ruta de un documento; debes leerlo con FileReaderTool "
        "y producir una síntesis fiel del mismo en formato Markdown. "
        "La síntesis debe:\n"
        "  - Conservar las ideas y datos principales del original.\n"
        "  - Estar bien estructurada (títulos, viñetas, tablas si procede).\n"
        "  - Tener entre 300 y 600 palabras.\n"
        "  - Estar en el mismo idioma que el documento original.\n\n"
        "Devuelve EXCLUSIVAMENTE el Markdown de la síntesis, sin texto adicional."
    )
    return BasicAgent(
        name=name,
        use_llm=use_llm,
        llm=f"{use_llm}:{model}",
        system_prompt=system_prompt,
        tools=[FileReaderTool()],
        instructions=(
            f"Lee el archivo en '{source_path}' usando FileReaderTool y "
            "genera tu síntesis en Markdown."
        ),
    )


def build_judge(name: str, use_llm: str, model: str) -> BasicAgent:
    """Crea un agente juez que vota cuál síntesis es la mejor."""
    system_prompt = (
        "Eres un juez imparcial. Recibirás tres síntesis del MISMO documento, "
        "etiquetadas como 'claude', 'gemini' y 'grok'. Tu tarea es elegir la "
        "que mejor refleje el contenido y las ideas del documento original "
        "(fidelidad, completitud, claridad, estructura).\n\n"
        "Debes devolver una decisión estructurada con: decision (claude|gemini|grok), "
        "confidence (0-1) y reasoning (justificación corta)."
    )
    return BasicAgent(
        name=name,
        use_llm=use_llm,
        llm=f"{use_llm}:{model}",
        system_prompt=system_prompt,
        use_tools=False,  # los jueces no necesitan tools
    )


def build_writer(output_path: Path) -> BasicAgent:
    """Agente final: recibe la síntesis ganadora y la escribe a disco."""
    base_dir = output_path.parent.resolve()
    file_manager = FileManagerTool(
        manager_type="fs",
        default_output_dir=str(base_dir),
        base_path=str(base_dir),
        sandboxed=False,  # permitimos rutas absolutas dentro de base_dir
    )

    system_prompt = (
        "Eres un agente de redacción final. Recibirás:\n"
        "  1) El nombre del autor ganador del consenso (claude/gemini/grok).\n"
        "  2) El texto Markdown de la síntesis ganadora.\n\n"
        "Tu trabajo es:\n"
        "  - Añadir un encabezado con el autor ganador y un breve preámbulo "
        "    (1-2 frases) que confirme el consenso.\n"
        "  - Conservar íntegro el contenido Markdown ganador debajo.\n"
        f"  - Guardar el resultado completo en '{output_path}' usando "
        "    FileManagerTool con operation='create' (path absoluto y content=Markdown final).\n\n"
        "Cuando termines, responde con un breve resumen confirmando "
        "qué archivo escribiste y cuántos bytes ocupa."
    )
    return BasicAgent(
        name="writer",
        use_llm="anthropic",
        llm="anthropic:claude-sonnet-4-5",
        system_prompt=system_prompt,
        tools=[file_manager],
    )


# ---------------------------------------------------------------------------
# Lifecycle listener (opcional)
# ---------------------------------------------------------------------------
def lifecycle_listener(event: str, node_id: str, info: Dict[str, Any]) -> None:
    """Traza una línea por evento del scheduler (sin tocar el motor)."""
    if node_id:
        suffix = f" ({info['duration_ms']:.0f} ms)" if "duration_ms" in info else ""
        print(f"  · [{event:<15}] {node_id}{suffix}")
    else:
        print(f"  · [{event:<15}] flow={info.get('flow')} {info.get('status', '')}")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
async def run(source_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    flow = AgentsFlow(name="ConsensusSynthesisFlow", on_node_event=lifecycle_listener)

    # 1. Tres sintetizadores con LLMs distintos (nodos de inicio: sin entrada)
    synth_specs = [
        ("claude_synth", "anthropic", "claude-opus-4-5", "claude"),
        ("gemini_synth", "google", "gemini-2.5-pro", "gemini"),
        ("grok_synth", "grok", "grok-4.3", "grok"),
    ]
    synth_agents = {
        node_id: build_synthesizer(node_id, use_llm, model, source_path)
        for node_id, use_llm, model, _vote in synth_specs
    }
    for node_id, agent in synth_agents.items():
        flow.add_node(AgentNode(node_id=node_id, agent=agent))

    synth_node_ids = [node_id for node_id, *_ in synth_specs]
    synth_map = {vote_key: node_id for node_id, _llm, _model, vote_key in synth_specs}

    # 2. DecisionFlowNode (BALLOT) con tres jueces y quórum de 2
    judges = {
        "claude_judge": build_judge("claude_judge", "anthropic", "claude-opus-4-5"),
        "gemini_judge": build_judge("gemini_judge", "google", "gemini-2.5-pro"),
        "grok_judge": build_judge("grok_judge", "grok", "grok-4.3"),
    }
    consensus_node = ConsensusDecisionNode(
        node_id="consensus",
        agents=judges,
        synth_node_ids=synth_node_ids,
        config=DecisionNodeConfig(
            mode=DecisionMode.BALLOT,
            decision_type=DecisionType.MULTI_CHOICE,
            decision_schema=SynthesisVote,
            options=[
                {"key": "claude", "label": "Síntesis de Claude Opus"},
                {"key": "gemini", "label": "Síntesis de Gemini Pro"},
                {"key": "grok", "label": "Síntesis de Grok"},
            ],
            minimum_votes=2,  # quórum: al menos 2 de 3 jueces
        ),
    )
    flow.add_node(consensus_node)

    # 3. Agente final que escribe el resultado a disco
    writer = WriterNode(
        node_id="writer",
        agent=build_writer(output_path),
        decision_node_id="consensus",
        synth_map=synth_map,
    )
    flow.add_node(writer)

    # 4. Cableado del DAG: 3 síntesis → consenso → writer
    for sid in synth_node_ids:
        flow.add_edge(sid, "consensus", condition="on_success")
    flow.add_edge("consensus", "writer", condition="on_success")

    # 5. Configurar agentes (AgentNode.execute llama a agent.ask sin configurar;
    #    los jueces los configura el DecisionFlowNode de forma perezosa).
    await asyncio.gather(
        *(agent.configure() for agent in synth_agents.values()),
        writer.agent.configure(),
    )

    # 6. Ejecutar el flujo
    print(f"\n📄 Documento origen : {source_path}")
    print(f"💾 Salida esperada  : {output_path}\n")
    print("⏳ Ejecutando AgentsFlow...\n")

    result = await flow.run_flow(FlowContext(initial_task=str(source_path)))

    completed = [n.node_id for n in result.nodes if n.status == "completed"]
    print("\n--- Resultado del flujo ---")
    print(f"Status     : {result.status.value}")
    print(f"Completados: {completed}")
    print(f"Tiempo     : {result.total_time:.2f}s")
    if result.errors:
        print(f"Errores    : {result.errors}")
    print("\nSalida final (writer):")
    writer_out = result.responses.get("writer", {})
    print(writer_out.get("output") if isinstance(writer_out, dict) else writer_out)

    if output_path.exists():
        print(f"\n✅ Markdown escrito en: {output_path} ({output_path.stat().st_size} bytes)")
    else:
        print(f"\n⚠️  El archivo {output_path} no se generó.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Ruta del documento origen (txt, md, pdf, docx, pptx, csv, xlsx)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/consensus_synthesis.md"),
        help="Ruta del Markdown de salida con la síntesis consensuada",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true", help="Logging en nivel DEBUG"
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    if not args.input.exists():
        raise SystemExit(f"❌ El documento de entrada no existe: {args.input}")
    asyncio.run(run(args.input.resolve(), args.output.resolve()))


if __name__ == "__main__":
    main()
