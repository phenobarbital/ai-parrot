"""build_dev_loop_flow — wire the seven dev-loop nodes into an AgentsFlow.

Implements **Module 10**. Topology (FEAT-132):

.. code-block:: text

    IntentClassifier ──(kind=="bug")──► BugIntake → Research → Development → QA → DeploymentHandoff
                     └─(kind!="bug")──────────────► Research      │
                                                                   └─(passed=False)→ FailureHandler
                                                                   ↑(any node hard-error)

Built on the FEAT-163 ``AgentsFlow`` executor using explicit conditional
edges (``add_edge``): the engine's OR-join + skip-propagation semantics
make the branch merge at ``research`` and the on_error fan-in at
``failure_handler`` first-class — no adapters, no legacy API.

When a ``redis_url`` is provided, the flow publishes node lifecycle
events (``flow.node_started`` / ``node_completed`` / ``node_failed`` /
``node_skipped``) to the per-run stream ``flow:{run_id}:flow`` via the
engine's ``on_node_event`` hook (spec G4 — the multiplexer's "flow" view).

The factory is a pure function — no globals, no env reads.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from parrot.bots.flows import AgentsFlow
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import WorkBrief
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
# Edge predicates
# ---------------------------------------------------------------------------


def _is_bug(result: Any) -> bool:
    """Return True only if result is a WorkBrief with kind == 'bug'."""
    if isinstance(result, WorkBrief):
        return result.kind == "bug"
    return False


def _is_not_bug(result: Any) -> bool:
    """Return True only if result is a WorkBrief with kind != 'bug'."""
    if isinstance(result, WorkBrief):
        return result.kind != "bug"
    return False


def _qa_passed(result: Any) -> bool:
    """True when the QAReport's ``passed`` flag is exactly True."""
    return getattr(result, "passed", False) is True


def _qa_failed(result: Any) -> bool:
    """True when the QAReport's ``passed`` flag is exactly False."""
    return getattr(result, "passed", True) is False


# ---------------------------------------------------------------------------
# Flow-level event publisher (spec G4)
# ---------------------------------------------------------------------------


class FlowEventPublisher:
    """Publishes AgentsFlow node-lifecycle events to ``flow:{run_id}:flow``.

    Bound to ``AgentsFlow(on_node_event=...)``. The run_id is read from
    the event's ``info["context"].shared_data["run_id"]`` (the engine
    passes the run's FlowContext on every event, so concurrent runs on
    the same flow instance publish to their own streams); a mutable
    holder dict serves as fallback for callers that drive ``run_flow``
    directly with an unseeded context.

    The Redis connection is lazy and every failure is swallowed — event
    publishing must never break a run.

    Args:
        redis_url: Redis URL for the XADD calls.
        run_id_holder: Mutable mapping carrying the fallback ``"run_id"``.
    """

    def __init__(self, redis_url: str, run_id_holder: Dict[str, str]) -> None:
        self._redis_url = redis_url
        self._holder = run_id_holder
        self._redis: Any = None

    async def __call__(self, event: str, node_id: str, info: Dict[str, Any]) -> None:
        """XADD one ``flow.<event>`` envelope to the current run's stream."""
        run_id = ""
        run_ctx = info.get("context")
        if run_ctx is not None:
            run_id = getattr(run_ctx, "shared_data", {}).get("run_id", "")
        if not run_id:
            run_id = self._holder.get("run_id", "")
        if not run_id:
            return
        envelope = {
            "kind": f"flow.{event}",
            "ts": time.time(),
            "run_id": run_id,
            "node_id": node_id,
            "payload": {
                k: v for k, v in info.items() if k not in ("flow", "context")
            },
        }
        try:
            redis_client = await self._ensure_redis()
            await redis_client.xadd(
                f"flow:{run_id}:flow",
                {"event": json.dumps(envelope)},
                maxlen=10_000,
                approximate=True,
            )
        except Exception:  # noqa: BLE001 - telemetry must never break the run
            pass

    async def _ensure_redis(self) -> Any:
        """Return a cached async Redis client, creating it on first call."""
        if self._redis is None:
            import redis.asyncio as aioredis  # noqa: PLC0415 - lazy

            self._redis = aioredis.from_url(
                self._redis_url, decode_responses=True
            )
        return self._redis

    async def close(self) -> None:
        """Release the Redis connection pool."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None


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
    publish_flow_events: bool = True,
    lifecycle_events: bool = True,
) -> AgentsFlow:
    """Build the seven-node dev-loop ``AgentsFlow`` (FEAT-132).

    Topology:

    - ``IntentClassifierNode`` routes:
      - ``kind == "bug"`` → ``BugIntakeNode`` → ``ResearchNode``
      - ``kind != "bug"`` → ``ResearchNode`` directly
    - ``ResearchNode`` → ``DevelopmentNode`` → ``QANode``
    - ``QANode`` → ``DeploymentHandoffNode`` (passed) or ``FailureHandlerNode``
    - Any hard error from any middle node → ``FailureHandlerNode``
      (``on_error`` edges; untaken paths are skip-propagated by the engine)

    Args:
        dispatcher: A pre-built :class:`ClaudeCodeDispatcher` (shared by
            Research, Development, and QA nodes).
        jira_toolkit: Service-account ``JiraToolkit`` instance.
        log_toolkits: Mapping of source kind → toolkit. Recognised keys:
            ``"cloudwatch"``, ``"elasticsearch"``.
        redis_url: Redis URL for ``IntentClassifierNode`` /
            ``BugIntakeNode`` intake events and the flow-level
            node-lifecycle events.
        name: Flow name (default ``"dev-loop"``).
        publish_flow_events: When True (default), attach a
            :class:`FlowEventPublisher` to the engine's ``on_node_event``
            hook. The publisher reads the run_id from
            ``flow._run_id_holder`` (seeded by ``DevLoopRunner``).
        lifecycle_events: When True (default), also attach a
            :class:`parrot.bots.flows.flow.telemetry.FlowLifecycleAdapter`
            so typed FEAT-176 events (FlowStarted/NodeCompleted/…) reach
            the global lifecycle registry — and through it the OTel /
            logging / usage subscribers.

    Returns:
        A wired :class:`AgentsFlow` instance ready to ``run_flow()``.
    """
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

    run_id_holder: Dict[str, str] = {}
    publisher: Optional[FlowEventPublisher] = None
    if publish_flow_events:
        publisher = FlowEventPublisher(redis_url, run_id_holder)

    flow = AgentsFlow(name=name, on_node_event=publisher)
    # Exposed for DevLoopRunner / callers to bind the current run_id.
    flow._run_id_holder = run_id_holder  # type: ignore[attr-defined]
    flow._event_publisher = publisher  # type: ignore[attr-defined]

    lifecycle_adapter = None
    if lifecycle_events:
        from parrot.bots.flows.flow.telemetry import (  # noqa: PLC0415
            FlowLifecycleAdapter,
        )
        lifecycle_adapter = FlowLifecycleAdapter()
        flow.add_node_event_listener(lifecycle_adapter)
    flow._lifecycle_adapter = lifecycle_adapter  # type: ignore[attr-defined]

    for node in (
        intent_classifier,
        bug_intake,
        research,
        development,
        qa,
        handoff,
        failure,
    ):
        flow.add_node(node)

    # FEAT-132: IntentClassifier branches by kind. Register "bug" first so
    # it wins in case of evaluation-order sensitivity (spec §7 R7).
    flow.add_edge(intent_classifier.name, bug_intake.name, predicate=_is_bug)
    flow.add_edge(intent_classifier.name, research.name, predicate=_is_not_bug)

    # Bug path keeps the linear edge to Research (the engine's OR-join
    # merges it with the direct non-bug edge).
    flow.add_edge(bug_intake.name, research.name)

    # Remaining linear chain: Research → Development → QA.
    flow.add_edge(research.name, development.name)
    flow.add_edge(development.name, qa.name)

    # QA branch: passed=True → handoff, passed=False → failure handler.
    flow.add_edge(qa.name, handoff.name, predicate=_qa_passed)
    flow.add_edge(qa.name, failure.name, predicate=_qa_failed)

    # Global error route — any hard error from intent_classifier or middle
    # nodes routes to the failure handler (OR-join fan-in).
    for source in (intent_classifier, bug_intake, research, development, qa, handoff):
        flow.add_edge(source.name, failure.name, condition="on_error")

    return flow


__all__ = ["FlowEventPublisher", "build_dev_loop_flow"]
