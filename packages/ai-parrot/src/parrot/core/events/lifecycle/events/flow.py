"""Flow / node orchestration lifecycle events.

FEAT-176 Phase 1.5 — flow-layer events deferred by the Phase 1 spec
("Crew / multi-agent events").

Covers the ``AgentsFlow`` scheduler lifecycle: a run-level bracket
(``FlowStartedEvent`` / ``FlowCompletedEvent``) plus one event per node
dispatch outcome (started / completed / failed / skipped — the skipped
outcome exists only in the explicit-edge OR-join mode).

Emission site: :class:`parrot.bots.flows.flow.telemetry.FlowLifecycleAdapter`
attached to ``AgentsFlow``'s node-event listener channel. Events carry the
run's :class:`TraceContext` (root span for flow events, one child span per
node) so flow spans stitch with the client/tool spans emitted inside nodes.
"""
from dataclasses import dataclass

from navigator_eventbus.lifecycle.base import LifecycleEvent


@dataclass(frozen=True)
class FlowStartedEvent(LifecycleEvent):
    """Emitted when ``AgentsFlow.run_flow()`` begins dispatching.

    Attributes:
        flow_name: Name of the ``AgentsFlow`` instance.
        run_id: Caller-supplied run identifier (empty when the flow is run
            outside a runner that mints one).
        node_count: Number of nodes materialized for this run.
    """

    flow_name: str = ""
    run_id: str = ""
    node_count: int = 0


@dataclass(frozen=True)
class FlowCompletedEvent(LifecycleEvent):
    """Emitted after the scheduler loop ends and the result is aggregated.

    Emitted for every terminal status (``completed`` / ``partial`` /
    ``failed``) — inspect :attr:`status` to discriminate.

    Attributes:
        flow_name: Name of the ``AgentsFlow`` instance.
        run_id: Caller-supplied run identifier.
        status: Aggregated run status (``FlowStatus`` value).
        duration_ms: Wall-clock time of the whole run in milliseconds.
        completed_count: Nodes that finished successfully.
        failed_count: Nodes that raised (after exhausting retries).
        skipped_count: Nodes skipped by OR-join skip-propagation.
    """

    flow_name: str = ""
    run_id: str = ""
    status: str = ""
    duration_ms: float = 0.0
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0


@dataclass(frozen=True)
class NodeStartedEvent(LifecycleEvent):
    """Emitted when the scheduler dispatches a node.

    Attributes:
        flow_name: Name of the owning ``AgentsFlow``.
        node_id: Graph-unique node identifier.
        run_id: Caller-supplied run identifier.
    """

    flow_name: str = ""
    node_id: str = ""
    run_id: str = ""


@dataclass(frozen=True)
class NodeCompletedEvent(LifecycleEvent):
    """Emitted when a node's ``execute()`` returns successfully.

    NOT emitted when the node raises (``NodeFailedEvent`` is used instead).

    Attributes:
        flow_name: Name of the owning ``AgentsFlow``.
        node_id: Graph-unique node identifier.
        run_id: Caller-supplied run identifier.
        duration_ms: Wall-clock time of the (last) execution attempt in
            milliseconds.
    """

    flow_name: str = ""
    node_id: str = ""
    run_id: str = ""
    duration_ms: float = 0.0


@dataclass(frozen=True)
class NodeFailedEvent(LifecycleEvent):
    """Emitted when a node fails after exhausting its retry budget.

    Attributes:
        flow_name: Name of the owning ``AgentsFlow``.
        node_id: Graph-unique node identifier.
        run_id: Caller-supplied run identifier.
        duration_ms: Wall-clock time of the failing attempt in milliseconds.
        error_type: ``type(exc).__name__`` of the exception.
        error_message: String representation of the exception.
    """

    flow_name: str = ""
    node_id: str = ""
    run_id: str = ""
    duration_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class NodeSkippedEvent(LifecycleEvent):
    """Emitted when OR-join skip-propagation marks a node as never-run.

    Only produced by the explicit-edge scheduler mode: the node's incoming
    edges all resolved but none fired (untaken branch, or upstream failure
    routed elsewhere).

    Attributes:
        flow_name: Name of the owning ``AgentsFlow``.
        node_id: Graph-unique node identifier.
        run_id: Caller-supplied run identifier.
    """

    flow_name: str = ""
    node_id: str = ""
    run_id: str = ""
