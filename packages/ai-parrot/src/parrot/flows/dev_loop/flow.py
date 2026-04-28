"""build_dev_loop_flow — wire the six primary nodes into an AgentsFlow.

Implements **Module 10**. Topology (FEAT-132):

.. code-block:: text

    IntentClassifier ──(kind=="bug")──► BugIntake → Research → Development → QA → DeploymentHandoff
                     └─(kind!="bug")──────────────► Research      │
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
from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode
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

    Every adapter built by :func:`build_dev_loop_flow` shares the same
    ``shared_ctx`` dict so writes performed by one node (e.g.
    ``ResearchNode`` setting ``ctx["research_output"]``) survive into
    the next node's call. Without this, AgentsFlow's per-call
    ``**kwargs`` would copy-fork the dict and mutations would be lost.
    """

    def __init__(
        self,
        node: _ExecutableNode,
        *,
        shared_ctx: Dict[str, Any],
    ) -> None:
        self._node = node
        self._shared_ctx = shared_ctx
        self.name: str = node.name
        self.is_configured: bool = True
        # Minimal tool_manager so add_agent's tool-sharing branch is
        # safe when a shared_tool_manager is passed (we don't pass one,
        # but be defensive).
        self.tool_manager = _NoopToolManager()

    async def configure(self) -> None:  # pragma: no cover - never called
        return None

    async def ask(self, question: str = "", **kwargs: Any) -> Any:
        # Merge per-call kwargs into the shared context (last write
        # wins) so callers can still inject ad-hoc keys per agent —
        # but persistent state (bug_brief, research_output, qa_report)
        # is the same dict object across nodes.
        for key, value in kwargs.items():
            self._shared_ctx[key] = value
        return await self._node.execute(question, self._shared_ctx)


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
    """Build the six-node dev-loop ``AgentsFlow`` (FEAT-132).

    Topology:

    - ``IntentClassifierNode`` routes:
      - ``kind == "bug"`` → ``BugIntakeNode`` → ``ResearchNode``
      - ``kind != "bug"`` → ``ResearchNode`` directly
    - ``ResearchNode`` → ``DevelopmentNode`` → ``QANode``
    - ``QANode`` → ``DeploymentHandoffNode`` (passed) or ``FailureHandlerNode``
    - Any hard error from any middle node → ``FailureHandlerNode``

    Args:
        dispatcher: A pre-built :class:`ClaudeCodeDispatcher` (shared by
            Research, Development, and QA nodes).
        jira_toolkit: Service-account ``JiraToolkit`` instance.
        log_toolkits: Mapping of source kind → toolkit. Recognised keys:
            ``"cloudwatch"``, ``"elasticsearch"``.
        redis_url: Redis URL for ``IntentClassifierNode`` and
            ``BugIntakeNode``'s flow-event publish.
        name: Crew/flow name (default ``"dev-loop"``).

    Returns:
        A wired :class:`AgentsFlow` instance ready to run.
    """
    # FEAT-132: IntentClassifierNode is now the entry point.
    intent_classifier = IntentClassifierNode(redis_url=redis_url)
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
        intent_classifier,
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
    # Single shared dict — ResearchNode writes ctx["research_output"]
    # which DevelopmentNode and QANode then read.
    shared_ctx: Dict[str, Any] = {}
    adapters = {
        node.name: _NodeAgentAdapter(node, shared_ctx=shared_ctx)
        for node in nodes_in_order
    }
    for adapter in adapters.values():
        flow.add_agent(adapter)

    # FEAT-132: IntentClassifier branches by kind.
    # Register "bug" first so it wins in case of evaluation-order sensitivity
    # (spec §7 R7).
    def _is_bug(result: Any) -> bool:
        return getattr(result, "kind", "bug") == "bug"

    def _is_not_bug(result: Any) -> bool:
        kind = getattr(result, "kind", "bug")
        return kind != "bug"

    flow.on_condition(intent_classifier.name, bug_intake.name, predicate=_is_bug)
    flow.on_condition(intent_classifier.name, research.name, predicate=_is_not_bug)

    # Bug path keeps the linear edge to Research:
    flow.task_flow(bug_intake.name, research.name)

    # Remaining linear chain: Research → Development → QA
    flow.task_flow(research.name, development.name)
    flow.task_flow(development.name, qa.name)

    # QA branch: passed=True → handoff, passed=False → failure handler.
    def _qa_passed(result: Any) -> bool:
        return getattr(result, "passed", False) is True

    def _qa_failed(result: Any) -> bool:
        return getattr(result, "passed", True) is False

    flow.on_condition(qa.name, handoff.name, predicate=_qa_passed)
    flow.on_condition(qa.name, failure.name, predicate=_qa_failed)

    # Global error route — any hard error from intent_classifier or middle
    # nodes routes to the failure handler.
    for source in (intent_classifier, research, development, qa, handoff):
        flow.on_error(source.name, failure.name)

    # Mark terminals.
    flow.task_flow(handoff.name, None)
    flow.task_flow(failure.name, None)
    return flow


__all__ = ["build_dev_loop_flow"]
