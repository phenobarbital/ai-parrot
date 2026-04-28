"""build_dev_loop_flow — wire the five primary nodes into an AgentsFlow.

Implements **Module 10**. Topology:

.. code-block:: text

    BugIntake → Research → Development → QA → DeploymentHandoff
                                          │
                                          └─(passed=False)→ FailureHandler
                                          ↑(any node hard-error)

The factory adapts each ``parrot.bots.flow.node.Node`` subclass into the
``BasicAgent``-shaped interface that :class:`AgentsFlow.add_agent`
expects (specifically: ``name`` attribute, ``is_configured=True`` so
:meth:`AgentsFlow._ensure_agent_ready` short-circuits, and
``async ask(question, **kwargs)`` that delegates to the node's
``execute(prompt, ctx)``).

The factory is a pure function — no globals, no env reads.
"""

from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable

from parrot.bots.flow import AgentsFlow
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
from parrot.flows.dev_loop.nodes.deployment_handoff import (
    DeploymentHandoffNode,
)
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.nodes.research import ResearchNode


# ---------------------------------------------------------------------------
# Adapter — Node → BasicAgent shape
# ---------------------------------------------------------------------------


@runtime_checkable
class _ExecutableNode(Protocol):
    """Structural type the adapter accepts — every dev-loop node matches.

    Mirrors :class:`parrot.bots.flow.node.Node`'s public surface plus the
    ``execute(prompt, ctx)`` contract used by ``FlowNode.execute``
    (``parrot/bots/flow/fsm.py:266``).
    """

    name: str

    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> Any: ...


class _NodeAgentAdapter:
    """Adapt a Node subclass into the BasicAgent-shape AgentsFlow expects.

    AgentsFlow only requires the ``name`` attribute plus an ``async ask``
    method. We also expose ``is_configured = True`` so the
    ``_ensure_agent_ready`` hook short-circuits without needing a real
    ``configure()`` implementation.
    """

    def __init__(self, node: _ExecutableNode) -> None:
        self._node = node
        self.name: str = node.name
        self.is_configured: bool = True
        # Minimal tool_manager so add_agent's tool-sharing branch is
        # safe when a shared_tool_manager is passed (we don't pass one,
        # but be defensive).
        self.tool_manager = _NoopToolManager()

    async def configure(self) -> None:  # pragma: no cover - never called
        return None

    async def ask(self, question: str = "", **kwargs: Any) -> Any:
        ctx = dict(kwargs)
        return await self._node.execute(question, ctx)


class _NoopToolManager:
    """Bare-minimum stand-in for ``parrot.tools.tool_manager.ToolManager``."""

    def list_tools(self):
        return []

    def get_tool(self, name: str):  # noqa: ARG002
        return None

    def add_tool(self, *args, **kwargs):  # noqa: ARG002
        return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_dev_loop_flow(
    *,
    dispatcher: ClaudeCodeDispatcher,
    jira_toolkit: Any,
    log_toolkits: Dict[str, Any],
    redis_url: str,
    name: str = "dev-loop",
) -> AgentsFlow:
    """Build the five-node dev-loop ``AgentsFlow``.

    Args:
        dispatcher: A pre-built :class:`ClaudeCodeDispatcher` (shared by
            Research, Development, and QA nodes).
        jira_toolkit: Service-account ``JiraToolkit`` instance.
        log_toolkits: Mapping of source kind → toolkit. Recognised keys:
            ``"cloudwatch"``, ``"elasticsearch"``.
        redis_url: Redis URL for ``BugIntakeNode``'s flow-event publish.
        name: Crew/flow name (default ``"dev-loop"``).

    Returns:
        A wired :class:`AgentsFlow` instance ready to run.
    """
    bug_intake = BugIntakeNode(redis_url=redis_url)
    research = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        log_toolkits=log_toolkits,
    )
    development = DevelopmentNode(dispatcher=dispatcher)
    qa = QANode(dispatcher=dispatcher)
    handoff = DeploymentHandoffNode(jira_toolkit=jira_toolkit)
    failure = FailureHandlerNode(jira_toolkit=jira_toolkit)

    nodes_in_order = [
        bug_intake,
        research,
        development,
        qa,
        handoff,
        failure,
    ]

    # Disable execution memory so we don't trigger the registry-tool
    # branch on adapters that lack `register_tool`.
    flow = AgentsFlow(name=name, enable_execution_memory=False)
    adapters = {
        node.name: _NodeAgentAdapter(node) for node in nodes_in_order
    }
    for adapter in adapters.values():
        flow.add_agent(adapter)

    # Linear chain BugIntake → Research → Development → QA
    flow.task_flow(bug_intake.name, research.name)
    flow.task_flow(research.name, development.name)
    flow.task_flow(development.name, qa.name)

    # QA branch: passed=True → handoff, passed=False → failure handler.
    def _qa_passed(result: Any) -> bool:
        return getattr(result, "passed", False) is True

    def _qa_failed(result: Any) -> bool:
        return getattr(result, "passed", True) is False

    flow.on_condition(qa.name, handoff.name, predicate=_qa_passed)
    flow.on_condition(qa.name, failure.name, predicate=_qa_failed)

    # Global error route — any hard error from research/development/qa
    # routes to the failure handler.
    for source in (research, development, qa, handoff):
        flow.on_error(source.name, failure.name)

    # Mark terminals.
    flow.task_flow(handoff.name, None)
    flow.task_flow(failure.name, None)
    return flow


__all__ = ["build_dev_loop_flow"]
