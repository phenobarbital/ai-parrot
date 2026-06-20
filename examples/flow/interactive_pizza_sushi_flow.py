"""
Ejemplo: routing interactivo Pizza vs Sushi con AgentsFlow.

Variante interactiva de ``pizza_sushi_flow.py``: en lugar de un nodo de
decisión basado en LLM (CIO), usa un ``InteractiveDecisionNode`` que muestra
un menú en la terminal (questionary) y enruta según la elección del usuario.

Grafo::

    food_decision (menú CLI) ─(=='pizza')─▶ pizza_agent
                             ─(=='sushi')─▶ sushi_agent

────────────────────────────────────────────────────────────────────────────
MIGRACIÓN (FEAT-196): este ejemplo vivía en ``examples/crew/`` e importaba
desde ``parrot.bots.flow`` (singular), un paquete ELIMINADO. Reescrito contra
la API nueva ``parrot.bots.flows`` (DAG event-driven, FEAT-163):

  Antiguo  →  Nuevo
  ----------------------------------------------------------------------
  from parrot.bots.flow import AgentsFlow, TransitionCondition
  from parrot.bots.flow.interactive_node import InteractiveDecisionNode
        ↓
  from parrot.bots.flows import AgentsFlow
  from parrot.bots.flows.core import AgentNode, FlowContext
  from parrot.bots.flows.flow.nodes import InteractiveDecisionNode

  InteractiveDecisionNode(name="food_decision", ...)   → node_id="food_decision"
  crew.add_agent(a)                    flow.add_node(AgentNode(node_id=..., agent=a))
  crew.add_start_node(targets=n)       (implícito: nodos sin aristas de entrada)
  crew.add_end_node("end_pizza"/...)   (innecesario: OR-join + skip-propagation)
  crew.task_flow(src, tgt,             flow.add_edge("src", "tgt", predicate=fn)
      condition=ON_CONDITION,
      predicate=fn, instruction=s)     (instruction → BranchAgentNode)
  predicate=lambda r: r.final_decision (el motor nuevo pasa el NodeResult del
      == "pizza"                        nodo; se extrae .result.final_decision)
  crew.run_flow("Initial trigger")     flow.run_flow("Initial trigger")  # str
  result.success / result.completed    result.status / result.nodes
────────────────────────────────────────────────────────────────────────────

Uso:
    source .venv/bin/activate
    python examples/flow/interactive_pizza_sushi_flow.py

Requiere ``questionary`` (pip install questionary) y una terminal interactiva,
además de la API key del proveedor por defecto de BasicAgent.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional, Set

from dotenv import load_dotenv

from parrot.bots.agent import BasicAgent
from parrot.bots.flows import AgentsFlow
from parrot.bots.flows.core import AgentNode, FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.types import AgentLike, DependencyResults
from parrot.bots.flows.flow.nodes import InteractiveDecisionNode

# Ensure environment variables (like API keys) are loaded.
load_dotenv()

# Subclassing the frozen Pydantic AgentNode here forces Pydantic to re-resolve
# the inherited field annotations against THIS module's namespace.
__all_field_types__ = (Optional, Set, AgentTaskMachine, AgentLike)


# ---------------------------------------------------------------------------
# Branch node: a fixed-instruction AgentNode
# ---------------------------------------------------------------------------
class BranchAgentNode(AgentNode):
    """AgentNode whose prompt is a fixed instruction.

    Replaces the old ``task_flow(..., instruction=...)`` parameter.
    """

    instruction: str = ""

    def _build_prompt(self, ctx: FlowContext, deps: DependencyResults) -> str:
        return self.instruction


BranchAgentNode.model_rebuild()


# ---------------------------------------------------------------------------
# Predicate helper
# ---------------------------------------------------------------------------
def decided(food: str):
    """Predicate that fires when the interactive node selected ``food``.

    The predicate receives the source node's result — for an
    InteractiveDecisionNode that is a ``NodeResult`` whose ``.result`` is a
    ``DecisionResult`` whose ``final_decision`` is the lowercased selection.
    """

    def _predicate(source_result: Any) -> bool:
        decision_result = getattr(source_result, "result", source_result)
        choice = getattr(decision_result, "final_decision", source_result)
        return str(choice).lower() == food

    return _predicate


# ---------------------------------------------------------------------------
# Lifecycle listener (optional)
# ---------------------------------------------------------------------------
def lifecycle_listener(event: str, node_id: str, info: dict) -> None:
    if node_id:
        print(f"  · [{event:<15}] {node_id}")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
async def main() -> None:
    print("=== Interactive Pizza vs Sushi AgentsFlow ===")

    flow = AgentsFlow(name="InteractiveFoodFlow", on_node_event=lifecycle_listener)

    # 1. Branch agents (leaves)
    pizza_agent = BasicAgent(
        name="PizzaAgent",
        system_prompt=(
            "You are an expert Italian chef. When asked about pizza, provide "
            "a quick, delicious recipe."
        ),
    )
    sushi_agent = BasicAgent(
        name="SushiAgent",
        system_prompt=(
            "You are a master sushi chef. When asked about sushi, share a "
            "fascinating curiosity or fact about it."
        ),
    )
    flow.add_node(
        BranchAgentNode(
            node_id="pizza",
            agent=pizza_agent,
            instruction="Provide a pizza recipe.",
        )
    )
    flow.add_node(
        BranchAgentNode(
            node_id="sushi",
            agent=sushi_agent,
            instruction="Tell me a sushi curiosity.",
        )
    )

    # 2. Interactive decision node (CLI menu) — the entry node.
    #    Replaces the LLM-based Coordinator: prompts the user directly.
    decision_node = InteractiveDecisionNode(
        node_id="food_decision",
        question="What are you in the mood for?",
        options=["Pizza", "Sushi"],
    )
    flow.add_node(decision_node)

    # 3. Conditional routing — only the matching branch fires; the other is
    #    skipped (OR-join + skip-propagation, no end nodes needed).
    flow.add_edge("food_decision", "pizza", predicate=decided("pizza"))
    flow.add_edge("food_decision", "sushi", predicate=decided("sushi"))

    # 4. Configure branch agents (the interactive node needs no LLM).
    await asyncio.gather(pizza_agent.configure(), sushi_agent.configure())

    # 5. Execute — the initial task string is ignored by the interactive node,
    #    which prompts the user via questionary instead.
    result = await flow.run_flow("Initial trigger")

    completed = [n.node_id for n in result.nodes if n.status == "completed"]
    skipped = [nid for nid in ("pizza", "sushi") if nid not in completed]

    print("\n--- Flow Execution Result ---")
    print(f"Status   : {result.status.value}")
    print(f"Completed: {completed}")
    print(f"Skipped  : {skipped}")
    if result.errors:
        print(f"Errors   : {result.errors}")

    output = result.output
    if isinstance(output, dict):
        output = output.get("output", output)
    print(f"\nFinal Output:\n{output}")


if __name__ == "__main__":
    asyncio.run(main())
