"""
Ejemplo: routing condicional Pizza vs Sushi con AgentsFlow + DecisionFlowNode.

Un nodo de decisión (CIO: un único coordinador) interpreta la petición del
usuario y decide 'pizza' o 'sushi'. Aristas con ``predicate`` enrutan a la rama
correspondiente; la rama no elegida se marca *skipped* y el skip se propaga.

Grafo::

    food_decision ─(decision=='pizza')─▶ pizza_agent
                  ─(decision=='sushi')─▶ sushi_agent

``food_decision`` es el nodo de inicio (sin aristas de entrada). ``pizza_agent``
y ``sushi_agent`` son hojas: solo corre la elegida, y su salida es
``FlowResult.output``.

────────────────────────────────────────────────────────────────────────────
MIGRACIÓN (FEAT-196): este ejemplo vivía en ``examples/crew/`` e importaba
desde ``parrot.bots.flow`` (singular), un paquete ELIMINADO. Reescrito contra
la API nueva ``parrot.bots.flows`` (DAG event-driven, FEAT-163):

  Antiguo  →  Nuevo
  ----------------------------------------------------------------------
  from parrot.bots.flow import ...     from parrot.bots.flows import AgentsFlow
                                       from parrot.bots.flows.flow.nodes import ...
                                       from parrot.bots.flows.core import AgentNode, FlowContext
  crew.add_agent(a)                    flow.add_node(AgentNode(node_id=..., agent=a))
  crew.add_start_node(targets=n)       (implícito: nodos sin aristas de entrada)
  crew.add_end_node("end_pizza")       (innecesario: el motor nuevo hace OR-join
  crew.add_end_node("end_sushi")        + skip-propagation; las hojas bastan)
  crew.task_flow(src, tgt,             flow.add_edge("src", "tgt",
      condition=ON_CONDITION,              predicate=fn)   # promueve a on_condition
      predicate=fn, instruction=s)     (instruction → subclase BranchAgentNode
                                        que fija el prompt de la rama)
  crew.run_flow(user_input)            flow.run_flow(user_input)  # acepta str
  result.success / result.completed    result.status / [n.node_id for n in
                                        result.nodes if n.status=='completed']
────────────────────────────────────────────────────────────────────────────

Uso:
    source .venv/bin/activate
    python examples/flow/pizza_sushi_flow.py

Requiere una API key del proveedor por defecto de BasicAgent (según tu .env).
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional, Set

from pydantic import BaseModel, Field

from parrot.bots.agent import BasicAgent
from parrot.bots.flows import AgentsFlow
from parrot.bots.flows.core import AgentNode, FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.types import AgentLike, DependencyResults
from parrot.bots.flows.flow.nodes import (
    DecisionFlowNode,
    DecisionMode,
    DecisionNodeConfig,
    DecisionType,
)

# Subclassing the frozen Pydantic AgentNode here forces Pydantic to re-resolve
# the inherited field annotations against THIS module's namespace, so they must
# be importable here even though they are not referenced directly.
__all_field_types__ = (Optional, Set, AgentTaskMachine, AgentLike)


# ---------------------------------------------------------------------------
# Structured output for the decision node
# ---------------------------------------------------------------------------
class FoodChoice(BaseModel):
    decision: str = Field(
        description="The chosen food: either 'pizza', 'sushi', or 'unknown'"
    )
    reasoning: str = Field(
        description="Explanation for the decision based on user input"
    )


# ---------------------------------------------------------------------------
# Branch node: a fixed-instruction AgentNode
# ---------------------------------------------------------------------------
class BranchAgentNode(AgentNode):
    """AgentNode whose prompt is a fixed instruction.

    Replaces the old ``task_flow(..., instruction=...)`` parameter: the branch
    agent always receives ``instruction`` as its prompt instead of the raw
    user input routed from upstream.
    """

    instruction: str = ""

    def _build_prompt(self, ctx: FlowContext, deps: DependencyResults) -> str:
        return self.instruction


BranchAgentNode.model_rebuild()


# ---------------------------------------------------------------------------
# Predicate helper
# ---------------------------------------------------------------------------
def decided(food: str):
    """Return a predicate that fires when the decision node chose ``food``.

    The predicate receives the source node's result — for a DecisionFlowNode
    that is a ``NodeResult`` whose ``.result`` is a ``DecisionResult`` whose
    ``final_decision`` (CIO mode) is the ``FoodChoice.decision`` string.
    """

    def _predicate(source_result: Any) -> bool:
        decision_result = getattr(source_result, "result", source_result)
        choice = getattr(decision_result, "final_decision", source_result)
        text = str(choice).lower()
        return food in text

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
    print("Initializing Pizza vs Sushi AgentsFlow...")

    flow = AgentsFlow(name="PizzaSushiFlow", on_node_event=lifecycle_listener)

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

    # 2. Decision node (CIO: single coordinator) — the entry node
    coordinator = BasicAgent(
        name="Coordinator",
        system_prompt=(
            "You analyze user input to determine if they want 'pizza' or "
            "'sushi'. Ignore everything else."
        ),
    )
    decision_node = DecisionFlowNode(
        node_id="food_decision",
        agents={"coordinator": coordinator},
        config=DecisionNodeConfig(
            mode=DecisionMode.CIO,
            decision_type=DecisionType.CUSTOM,
            decision_schema=FoodChoice,
        ),
    )
    flow.add_node(decision_node)

    # 3. Conditional routing — only the matching branch fires; the other is
    #    skipped, and the OR-join/skip-propagation keeps the flow from deadlock.
    flow.add_edge("food_decision", "pizza", predicate=decided("pizza"))
    flow.add_edge("food_decision", "sushi", predicate=decided("sushi"))

    # 4. Configure agents (AgentNode.execute calls agent.ask without configuring;
    #    the coordinator is configured lazily by DecisionFlowNode).
    await asyncio.gather(pizza_agent.configure(), sushi_agent.configure())

    # 5. Execute — run_flow accepts a plain string as the initial task.
    user_input = "I feel like having some pizza today!"
    print(f"\nUser Input: '{user_input}'\n")
    print("Running Flow...")

    result = await flow.run_flow(user_input)

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
    print(f"\nOutput:\n{output}")


if __name__ == "__main__":
    asyncio.run(main())
