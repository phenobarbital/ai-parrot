"""AgentsFlow — DAG execution engine (FEAT-163).

The new executor replaces ``parrot/bots/flow/fsm.py:AgentsFlow`` with an
event-driven scheduler consuming ``parrot.bots.flows.core`` primitives.

Key components:
    NODE_REGISTRY: Module-level registry mapping node type name → Node subclass.
    @register_node: Decorator factory to register Node subclasses.
    CompletionEvent: Dataclass pushed to the scheduler's completion queue when
        a node finishes (node_id, result, error).
    AgentsFlow: The new DAG executor class. Inherits PersistenceMixin for
        result persistence. Does NOT inherit SynthesisMixin (spec §1 + §5).
        Scheduler in TASK-1067; from_definition in TASK-1068.

See sdd/specs/agentsflow-refactor-spec3.spec.md for the full design.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple, Type, Union

from pydantic import Field as PydanticField
from navconfig.logging import logging

# ─── flows.core primitives (import, do not redefine) ────────────────────────

from ..core.node import AgentNode, EndNode, Node, StartNode
from ..core.context import FlowContext
from ..core.fsm import AgentTaskMachine
from ..core.result import (
    FlowResult,
    build_node_metadata,
    determine_run_status,
)
from ..core.storage import PersistenceMixin
from ..core.storage.synthesis import synthesize_results
from ..core.types import DependencyResults

# Declarative layer (intra-subpackage)
from .definition import FlowDefinition

# Decision-node canonical implementations (TASK-1311)
from .nodes import (
    DecisionFlowNode,
    DecisionNodeConfig,
    DecisionResult,
)

# AgentRegistry (type annotation only)
from parrot.registry.registry import AgentRegistry  # type: ignore[import-untyped]


logger = logging.getLogger(__name__)


# ─── CompletionEvent ─────────────────────────────────────────────────────────


@dataclass
class CompletionEvent:
    """Event pushed to the scheduler's completion queue when a node finishes.

    Attributes:
        node_id: Identifier of the node that finished.
        result: The result value returned by the node (``None`` on error).
        error: The exception raised by the node (``None`` on success).
    """

    node_id: str
    result: Any = None
    error: Optional[BaseException] = None


# ─── FlowEdge (programmatic conditional edges) ───────────────────────────────

#: Edge conditions accepted by :meth:`AgentsFlow.add_edge`.
EDGE_CONDITIONS = ("always", "on_success", "on_error", "on_timeout", "on_condition")


@dataclass
class FlowEdge:
    """Programmatic transition edge between two nodes.

    Counterpart of the declarative ``EdgeDefinition`` for flows built with
    ``add_node()`` / ``add_edge()`` instead of a ``FlowDefinition``.

    Attributes:
        from_: Source node_id.
        to: Target node_id.
        condition: One of ``EDGE_CONDITIONS``. ``"on_condition"`` requires a
            ``predicate``.
        predicate: Either a CEL expression string or a Python callable
            ``(source_result) -> bool`` evaluated against the source node's
            result when ``condition == "on_condition"``.
    """

    from_: str
    to: str
    condition: str = "always"
    predicate: Optional[Union[str, Callable[[Any], bool]]] = None


# ─── NODE_REGISTRY + @register_node ──────────────────────────────────────────

NODE_REGISTRY: dict[str, Type[Node]] = {}
"""Module-level mapping of node type name → Node subclass.

Populated at module load time by ``register_node()`` calls at the bottom of
this file (core types: ``"agent"``, ``"start"``, ``"end"``) and by
``TASK-1066`` for ``"decision"``, ``"interactive_decision"``, ``"synthesis"``.
"""


def register_node(name: str) -> Callable[[Type[Node]], Type[Node]]:
    """Register a Node subclass under ``name`` in ``NODE_REGISTRY``.

    This is a decorator factory; apply it to a Node subclass:

    Example::

        @register_node("my-type")
        class MyNode(AgentNode):
            ...

    Args:
        name: The type key under which to register the class. Must be unique
            across the registry.

    Returns:
        A decorator that registers the class and returns it unchanged.

    Raises:
        ValueError: If ``name`` is already registered.
        TypeError: If the decorated class is not a ``Node`` subclass.
    """

    def decorator(cls: Type[Node]) -> Type[Node]:
        if not (isinstance(cls, type) and issubclass(cls, Node)):
            raise TypeError(
                f"@register_node({name!r}) target must be a Node subclass, got {cls!r}"
            )
        if name in NODE_REGISTRY:
            raise ValueError(
                f"Node type {name!r} already registered to "
                f"{NODE_REGISTRY[name].__name__}"
            )
        NODE_REGISTRY[name] = cls
        return cls

    return decorator


# ─── AgentsFlow class skeleton ────────────────────────────────────────────────


class AgentsFlow(PersistenceMixin):
    """DAG executor consuming ``parrot.bots.flows.core`` primitives.

    This is the new-style flow executor that replaces the legacy
    ``parrot.bots.flow.fsm.AgentsFlow``. It operates on a graph of ``Node``
    instances materialized from a ``FlowDefinition`` (see ``from_definition``)
    or built programmatically via ``add_node``.

    Inherits ``PersistenceMixin`` for async result persistence.
    Does **not** inherit ``SynthesisMixin`` — use the ``synthesize_results``
    util as an ``on_complete`` hook instead (spec §1 Goals + §5 AC).

    Args:
        name: Human-readable name for this flow instance (used in logs).
        definition: Optional ``FlowDefinition`` captured for reference.
        agent_registry: Optional ``AgentRegistry`` bound to the flow's
            execution context. Used by ``from_definition`` (TASK-1068) for
            eager agent resolution.
        on_node_event: Optional callback ``(event, node_id, info) -> None``
            (sync or async) — or a sequence of them — invoked by the
            scheduler on lifecycle transitions. ``event`` is one of
            ``"flow_started"``, ``"node_started"``, ``"node_completed"``,
            ``"node_failed"``, ``"node_skipped"``, ``"flow_completed"``
            (flow-level events carry ``node_id=""``). ``info`` carries
            ``"flow"`` (name) and ``"context"`` (the run's FlowContext),
            plus per-event extras: ``"duration_ms"`` on completions and
            failures, ``"error"``/``"error_type"`` on failures,
            ``"node_count"`` on flow_started, and ``"status"`` +
            outcome counts on flow_completed. Exceptions raised by a
            callback are logged, never propagated. More listeners can be
            attached later via :meth:`add_node_event_listener`.
        **kwargs: Forwarded to ``PersistenceMixin`` (and ultimately
            ``object.__init__``).
    """

    def __init__(
        self,
        name: str,
        *,
        definition: Optional[FlowDefinition] = None,
        agent_registry: Optional[AgentRegistry] = None,
        on_node_event: Optional[
            Union[
                Callable[[str, str, Dict[str, Any]], Any],
                Sequence[Callable[[str, str, Dict[str, Any]], Any]],
            ]
        ] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self._definition = definition
        self._agent_registry = agent_registry
        self._nodes: dict[str, Node] = {}
        self._edges: list[FlowEdge] = []
        self._node_event_listeners: list[
            Callable[[str, str, Dict[str, Any]], Any]
        ] = []
        if on_node_event is not None:
            if callable(on_node_event):
                self._node_event_listeners.append(on_node_event)
            else:
                self._node_event_listeners.extend(on_node_event)
        self.logger = logging.getLogger(f"parrot.flow.{name}")

    # ── Graph construction ────────────────────────────────────────────────

    def add_node(self, node: Node) -> None:
        """Add a ``Node`` instance to the internal graph.

        Args:
            node: The ``Node`` to add. Its ``node_id`` must be unique within
                this flow.

        Raises:
            ValueError: If a node with the same ``node_id`` is already present.
        """
        if node.node_id in self._nodes:
            raise ValueError(
                f"Node {node.node_id!r} already added to flow {self.name!r}"
            )
        self._nodes[node.node_id] = node
        self.logger.debug("Added node %r to flow %r", node.node_id, self.name)

    def add_edge(
        self,
        from_: str,
        to: str,
        *,
        condition: str = "always",
        predicate: Optional[Union[str, Callable[[Any], bool]]] = None,
    ) -> FlowEdge:
        """Declare a transition edge between two programmatically-added nodes.

        When at least one edge is declared, the scheduler switches to
        explicit-edge mode: dependencies are derived from the edge list
        (``Node.dependencies`` / ``Node.successors`` are no longer required)
        and join semantics become OR-join with skip-propagation — a node is
        dispatched once **all** incoming edges are resolved (source completed,
        failed, or skipped) and **at least one** of them fired; if none fired,
        the node is marked skipped and the skip propagates downstream.

        Args:
            from_: Source node_id.
            to: Target node_id.
            condition: One of ``EDGE_CONDITIONS``. Defaults to ``"always"``
                (fires when the source completes without error). When a
                ``predicate`` is supplied the condition is promoted to
                ``"on_condition"`` automatically.
            predicate: CEL expression string or Python callable
                ``(source_result) -> bool``.

        Returns:
            The created :class:`FlowEdge`.

        Raises:
            ValueError: On unknown ``condition``, or ``"on_condition"``
                without a ``predicate``.
        """
        if predicate is not None and condition == "always":
            condition = "on_condition"
        if condition not in EDGE_CONDITIONS:
            raise ValueError(
                f"Unknown edge condition {condition!r}. "
                f"Expected one of {EDGE_CONDITIONS}"
            )
        if condition == "on_condition" and predicate is None:
            raise ValueError(
                "Edge condition 'on_condition' requires a predicate "
                "(CEL string or callable)"
            )
        edge = FlowEdge(from_=from_, to=to, condition=condition, predicate=predicate)
        self._edges.append(edge)
        self.logger.debug(
            "Added edge %r → %r (%s) to flow %r", from_, to, condition, self.name
        )
        return edge

    # ── Node-event notification ───────────────────────────────────────────

    def add_node_event_listener(
        self, callback: Callable[[str, str, Dict[str, Any]], Any]
    ) -> None:
        """Attach an additional node-event listener.

        Listeners are invoked in registration order with the same
        ``(event, node_id, info)`` contract as the constructor's
        ``on_node_event`` parameter. Use this to compose several consumers
        (e.g. a Redis publisher plus a lifecycle-telemetry adapter).

        Args:
            callback: Sync or async callable ``(event, node_id, info)``.
        """
        self._node_event_listeners.append(callback)

    def _notify_node_event(
        self, event: str, node_id: str, info: Dict[str, Any]
    ) -> None:
        """Invoke every node-event listener, shielding the scheduler.

        Sync callbacks run inline; coroutines are scheduled as fire-and-forget
        tasks. Errors are logged and swallowed — telemetry must never break
        the run.

        Args:
            event: Lifecycle event name (``flow_started`` | ``node_started``
                | ``node_completed`` | ``node_failed`` | ``node_skipped``
                | ``flow_completed``).
            node_id: The node the event refers to (empty for flow-level
                events).
            info: Extra payload (e.g. ``{"error": "..."}`` for failures).
        """
        for callback in self._node_event_listeners:
            try:
                outcome = callback(event, node_id, info)
                if asyncio.iscoroutine(outcome):
                    task = asyncio.ensure_future(outcome)
                    task.add_done_callback(self._log_event_task_error)
            except Exception as exc:  # noqa: BLE001 - telemetry must not break runs
                self.logger.warning(
                    "node-event listener raised for %s/%s: %s",
                    event, node_id, exc,
                )

    def _log_event_task_error(self, task: "asyncio.Task[Any]") -> None:
        """Done-callback that logs (instead of raising) async event errors."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self.logger.warning("async on_node_event callback raised: %s", exc)

    # ── Class-method factory (placeholder — TASK-1068) ────────────────────

    @classmethod
    def from_definition(
        cls,
        definition: FlowDefinition,
        *,
        agent_registry: Optional[AgentRegistry] = None,
    ) -> "AgentsFlow":
        """Materialize an executable ``AgentsFlow`` from a ``FlowDefinition``.

        Eagerly resolves every ``NodeDefinition.agent_ref`` against
        ``agent_registry`` at construction time so mis-configured refs fail
        fast (spec §8 OQ-5). The returned flow stores the definition and a
        pre-resolved ``{node_id: AgentLike}`` map; actual ``Node`` instances
        are re-created fresh inside each ``run_flow()`` call for concurrent
        safety (B-lite contract — TASK-1067 ``_materialize_nodes``).

        Args:
            definition: A validated ``FlowDefinition``. Cycle detection and
                referential integrity are enforced by ``FlowDefinition``'s
                own model-validators (TASK-1064); they are not re-checked here.
            agent_registry: ``AgentRegistry`` used to resolve ``agent_ref``
                strings. If ``None``, ``from_definition`` raises ``ValueError``
                (no global singleton is assumed).

        Returns:
            Configured ``AgentsFlow`` instance ready to ``run_flow()``.

        Raises:
            ValueError: If ``agent_registry`` is ``None`` or if any
                ``NodeDefinition.type`` is not in ``NODE_REGISTRY``.
            AgentNotFoundError: If any ``NodeDefinition.agent_ref`` cannot be
                resolved in ``agent_registry``.
        """
        from ..core.context import AgentNotFoundError  # noqa: PLC0415

        if agent_registry is None:
            raise ValueError(
                "AgentsFlow.from_definition() requires an agent_registry. "
                "Pass an AgentRegistry instance explicitly."
            )

        # Eagerly resolve every agent-type node's agent_ref.
        resolved_agents: dict[str, Any] = {}
        for node_def in definition.nodes:
            # Only "agent" nodes carry an agent_ref.
            if node_def.type != "agent":
                continue

            node_type = node_def.type
            if node_type not in NODE_REGISTRY:
                raise ValueError(
                    f"NodeDefinition {node_def.id!r}: node_type {node_type!r} "
                    f"not in NODE_REGISTRY. Registered types: {sorted(NODE_REGISTRY)}"
                )

            agent_ref = node_def.agent_ref or ""
            # AgentRegistry.get_bot_instance is the sync getter (matches TASK-1061 pattern).
            agent = agent_registry.get_bot_instance(agent_ref)
            if agent is None:
                raise AgentNotFoundError(
                    f"Cannot resolve agent_ref {agent_ref!r} for node {node_def.id!r}"
                )
            # Keyed by node_id so _materialize_nodes can look up by node_def.id.
            resolved_agents[node_def.id] = agent

        # Also validate non-agent node types are registered.
        for node_def in definition.nodes:
            if node_def.type == "agent":
                continue  # already checked above
            if node_def.type not in NODE_REGISTRY:
                raise ValueError(
                    f"NodeDefinition {node_def.id!r}: node_type {node_def.type!r} "
                    f"not in NODE_REGISTRY. Registered types: {sorted(NODE_REGISTRY)}"
                )

        # Construct the flow with the definition bound.
        # FlowDefinition uses .flow for the name.
        flow_name = getattr(definition, "flow", None) or getattr(definition, "name", "unnamed")
        flow = cls(
            name=flow_name,
            definition=definition,
            agent_registry=agent_registry,
        )
        # Attach pre-resolved agent map (keyed by node_id).
        flow._resolved_agents = resolved_agents
        return flow

    # ── Scheduler (TASK-1067) ─────────────────────────────────────────────

    def _materialize_nodes(self) -> dict[str, Node]:
        """Return a fresh dict of Node instances for this run.

        If a ``FlowDefinition`` is bound, new Node instances are built from it
        (so concurrent ``run_flow()`` calls do NOT share FSM state — B-lite
        contract). If no definition is bound, the nodes added via ``add_node()``
        are copied with fresh FSM instances so that concurrent invocations of
        ``run_flow()`` on the same ``AgentsFlow`` do NOT share FSM state.

        Returns:
            Mapping of node_id → fresh Node instance.
        """
        if self._definition is None:
            # Programmatic mode: create fresh copies with new FSM instances so
            # concurrent run_flow() calls do not share FSM state (B-lite contract).
            fresh: dict[str, Node] = {}
            for nid, node in self._nodes.items():
                new_fsm = AgentTaskMachine(
                    agent_name=getattr(node, "node_id", nid)
                )
                try:
                    fresh[nid] = node.model_copy(update={"fsm": new_fsm})
                except Exception:
                    # Fallback: if model_copy fails (e.g., type mismatch), use
                    # the original node. This should not happen for well-formed nodes.
                    fresh[nid] = node
            return fresh

        # Definition-driven mode: materialize fresh nodes from the definition.
        # Resolved agents are stored on self._resolved_agents (set by from_definition).
        resolved_agents: dict[str, Any] = getattr(self, "_resolved_agents", {})
        fresh: dict[str, Node] = {}

        for node_def in self._definition.nodes:
            node_type = node_def.type  # "agent", "start", "end", ...
            cls = NODE_REGISTRY.get(node_type)
            if cls is None:
                raise ValueError(
                    f"Unknown node type {node_type!r} in flow {self.name!r}. "
                    f"Available: {sorted(NODE_REGISTRY)}"
                )

            # Build dependencies and successors from edges.
            nid = node_def.id
            deps: set[str] = set()
            succs: set[str] = set()
            for edge in self._definition.edges:
                targets = [edge.to] if isinstance(edge.to, str) else list(edge.to)
                if edge.from_ == nid:
                    succs.update(targets)
                if nid in targets:
                    deps.add(edge.from_)

            # Construct node based on type requirements.
            if node_type == "agent":
                # _resolved_agents is keyed by node_id (set by from_definition).
                agent = resolved_agents.get(nid)
                if agent is None:
                    raise ValueError(
                        f"Agent ref {node_def.agent_ref!r} not resolved for "
                        f"node {nid!r}. Ensure from_definition was called with "
                        "agent_registry."
                    )
                fresh[nid] = cls(
                    agent=agent,
                    node_id=nid,
                    dependencies=deps,
                    successors=succs,
                )
            elif node_type in ("start", "end"):
                fresh[nid] = cls(
                    node_id=nid,
                    dependencies=deps,
                    successors=succs,
                )
            else:
                # For other node types, try a generic construction; subclasses
                # may need additional fields from node_def.config.
                fresh[nid] = cls(
                    node_id=nid,
                    dependencies=deps,
                    successors=succs,
                )

        return fresh

    async def _run_node(
        self,
        node: Node,
        ctx: FlowContext,
        deps: DependencyResults,
        queue: "asyncio.Queue[CompletionEvent]",
    ) -> None:
        """Task wrapper: execute a single node, manage FSM, push CompletionEvent.

        This coroutine is launched via ``asyncio.create_task``. Exceptions are
        caught here so they never escape to the scheduler's main loop
        unguarded — instead they are wrapped in a ``CompletionEvent``.

        Args:
            node: The Node to execute.
            ctx: The current flow execution context.
            deps: Dependency results to pass to ``node.execute()``.
            queue: Queue to push the CompletionEvent to on completion.
        """
        try:
            # FSM: idle → ready → running
            node.fsm.schedule()    # idle → ready
            node.fsm.start()       # ready → running
            result = await node.execute(ctx, deps)
            node.fsm.succeed()     # running → completed
            await queue.put(CompletionEvent(node_id=node.node_id, result=result))
        except BaseException as exc:
            try:
                node.fsm.fail()    # any → failed
            except Exception:
                pass               # ignore double-transition errors
            await queue.put(CompletionEvent(node_id=node.node_id, error=exc))

    def _aggregate_result(
        self,
        nodes: dict[str, Node],
        results: dict[str, Any],
        errors: dict[str, BaseException],
        completed: set[str],
        failed: set[str],
        edges: Optional[list[Any]] = None,
        durations: Optional[dict[str, float]] = None,
    ) -> FlowResult:
        """Build a FlowResult from scheduler state after the main loop exits.

        Args:
            nodes: All materialized nodes for this run.
            results: Mapping of node_id → execute() return value.
            errors: Mapping of node_id → exception.
            completed: Set of successfully completed node_ids.
            failed: Set of failed node_ids.
            edges: Explicit-mode edge list used for leaf detection. ``None``
                in definition/legacy modes (which use the definition's edges
                or ``node.successors`` respectively).
            durations: Optional node_id → wall-clock seconds of the last
                execution attempt, used for ``NodeExecutionInfo.execution_time``.

        Returns:
            Populated FlowResult.
        """
        node_infos = []
        for nid in completed | failed:
            node = nodes[nid]
            resp = results.get(nid)
            err = errors.get(nid)
            status_str = "completed" if nid in completed else "failed"
            info = build_node_metadata(
                node_id=nid,
                agent=getattr(node, "agent", None),
                response=resp,
                output=resp,
                execution_time=(durations or {}).get(nid, 0.0),
                status=status_str,
                error=str(err) if err else None,
            )
            node_infos.append(info)

        # Identify leaf nodes: nodes with no outgoing edges to known nodes.
        # Explicit/definition modes use their edge lists; legacy programmatic
        # mode uses node.successors.
        if edges is not None or self._definition is not None:
            edge_list = edges if edges is not None else self._definition.edges
            has_successor: set[str] = set()
            for edge in edge_list:
                if edge.from_ in nodes:
                    has_successor.add(edge.from_)
            leaves = [nid for nid in nodes if nid not in has_successor]
            if edges is not None and not any(nid in results for nid in leaves):
                # Explicit mode is skip-aware: when every static leaf was
                # skipped (e.g. an error-handler fan-in on the happy path),
                # fall back to the terminal nodes of the path actually
                # taken — executed nodes with no executed successor.
                outgoing: dict[str, set[str]] = {}
                for edge in edge_list:
                    targets = (
                        [edge.to] if isinstance(edge.to, str) else list(edge.to)
                    )
                    outgoing.setdefault(edge.from_, set()).update(targets)
                leaves = [
                    nid for nid in results
                    if not any(t in results for t in outgoing.get(nid, ()))
                ]
        else:
            # Leaf = node with empty successors set.
            leaves = [nid for nid, node in nodes.items() if not node.successors]

        if len(leaves) == 1 and leaves[0] in results:
            leaf_result = results[leaves[0]]
            # AgentNode.execute() returns a dict with an "output" key holding
            # the actual scalar content. Unwrap it so FlowResult.output is the
            # agent's answer rather than the execution-metadata dict.
            if isinstance(leaf_result, dict) and "output" in leaf_result:
                output: Any = leaf_result["output"]
            else:
                output = leaf_result
        else:
            # Multi-leaf fan-out: collect each leaf's scalar output.
            output_map: dict[str, Any] = {}
            for nid in leaves:
                if nid in results:
                    lr = results[nid]
                    output_map[nid] = lr["output"] if isinstance(lr, dict) and "output" in lr else lr
            output = output_map

        from ..core.types import FlowStatus

        status_str = determine_run_status(len(completed), len(failed))
        flow_status = FlowStatus(status_str)

        return FlowResult(
            output=output,
            nodes=node_infos,
            responses=dict(results),
            errors={k: str(v) for k, v in errors.items()},
            status=flow_status,
        )

    async def run_flow(
        self,
        ctx: Optional[Union[FlowContext, str]] = None,
        *,
        on_complete: Tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...] = (),
    ) -> FlowResult:
        """Run the flow DAG with event-driven scheduling.

        Each node runs as a separate ``asyncio.create_task``; a single
        ``asyncio.Queue`` collects completion events. The scheduler dispatches
        downstream nodes incrementally — fast nodes do not wait for slow siblings.
        FSM transitions are managed here, outside of ``Node.execute()``.

        Fresh Node instances are materialized at the start of each call via
        ``_materialize_nodes()`` so concurrent invocations on the same
        ``AgentsFlow`` instance do NOT share FSM state (B-lite contract).

        Args:
            ctx: Optional pre-built ``FlowContext`` or a string prompt.
                If a string is provided, a FlowContext is created with
                ``initial_task`` set to that string.
                If ``None``, a new FlowContext is created with an empty task.
            on_complete: Tuple of async callables invoked after the main loop.
                Each receives ``(ctx, result)``; exceptions are caught and logged
                but do NOT affect ``FlowResult.status``.

        Returns:
            Aggregated ``FlowResult`` describing the run.
        """
        from .cel_evaluator import CELPredicateEvaluator  # noqa: PLC0415

        # Accept a plain string as the initial task prompt.
        if isinstance(ctx, str):
            ctx = FlowContext(
                initial_task=ctx,
                agent_registry=self._agent_registry,
                synthesis_client=getattr(self, "_synthesis_client", None),
            )

        ctx = ctx or FlowContext(
            initial_task="",
            agent_registry=self._agent_registry,
            synthesis_client=getattr(self, "_synthesis_client", None),
        )

        # Fresh nodes per call (concurrent safety).
        nodes: dict[str, Node] = self._materialize_nodes()

        # Edge resolution (three modes):
        #   1. Definition-driven: use the definition's declared edges.
        #   2. Explicit programmatic: edges added via add_edge() — enables
        #      conditional routing, OR-join, and skip-propagation.
        #   3. Legacy programmatic: synthesize "always" edges from
        #      node.successors (backward compatible).
        explicit_mode = self._definition is None and bool(self._edges)
        if self._definition is not None:
            edges = self._definition.edges
        elif explicit_mode:
            edges = list(self._edges)
            for edge in edges:
                if edge.from_ not in nodes or edge.to not in nodes:
                    raise ValueError(
                        f"Edge {edge.from_!r} → {edge.to!r} references a "
                        f"node not added to flow {self.name!r}"
                    )
        else:
            # Build a synthetic edge list from node.successors / node.dependencies.
            synthetic_edges: list[Any] = []
            for nid, node in nodes.items():
                for succ in node.successors:
                    synthetic_edges.append(FlowEdge(from_=nid, to=succ))
            edges = synthetic_edges

        completion_queue: asyncio.Queue[CompletionEvent] = asyncio.Queue()
        attempts: dict[str, int] = {nid: 0 for nid in nodes}
        tasks: dict[str, asyncio.Task] = {}   # type: ignore[type-arg]
        completed: set[str] = set()
        failed: set[str] = set()
        skipped: set[str] = set()
        results: dict[str, Any] = {}
        errors: dict[str, BaseException] = {}
        active_count = 0
        loop = asyncio.get_running_loop()
        run_started_at = loop.time()
        started_at: dict[str, float] = {}
        durations: dict[str, float] = {}      # node_id → seconds (last attempt)

        # Incoming-edge index (explicit mode joins + derived dependencies).
        incoming: dict[str, list[Any]] = {nid: [] for nid in nodes}
        for edge in edges:
            targets = [edge.to] if isinstance(edge.to, str) else list(edge.to)
            for tgt in targets:
                if tgt in incoming:
                    incoming[tgt].append(edge)

        if explicit_mode:
            # Structural validation (Kahn): every node must be reachable
            # through an acyclic path. A cycle would otherwise leave its
            # nodes unexecuted and end the run with a misleading
            # "completed" status (FlowDefinition validates this itself;
            # programmatic graphs are validated here).
            unique_sources = {
                nid: {e.from_ for e in in_edges}
                for nid, in_edges in incoming.items()
            }
            in_degree = {nid: len(srcs) for nid, srcs in unique_sources.items()}
            succ_sets: dict[str, set[str]] = {}
            for tgt, srcs in unique_sources.items():
                for src in srcs:
                    succ_sets.setdefault(src, set()).add(tgt)
            frontier = [nid for nid, deg in in_degree.items() if deg == 0]
            visited = 0
            while frontier:
                current = frontier.pop()
                visited += 1
                for tgt in succ_sets.get(current, ()):
                    in_degree[tgt] -= 1
                    if in_degree[tgt] == 0:
                        frontier.append(tgt)
            if visited < len(nodes):
                cyclic = sorted(
                    nid for nid, deg in in_degree.items() if deg > 0
                )
                raise ValueError(
                    f"Flow {self.name!r} contains a cycle: nodes {cyclic} "
                    "are never reachable from an entry node. Break the "
                    "cycle or use conditional edges with a terminal path."
                )

        def _deps_for(node_id: str) -> DependencyResults:
            """Build dependency result dict for a node."""
            if explicit_mode:
                dep_ids: Set[str] = {e.from_ for e in incoming[node_id]}
                dep_ids |= set(nodes[node_id].dependencies)
            else:
                dep_ids = set(nodes[node_id].dependencies)
            return {
                dep: str(results[dep])
                for dep in dep_ids
                if dep in results
            }

        def _spawn(node_id: str) -> None:
            nonlocal active_count
            node = nodes[node_id]
            deps = _deps_for(node_id)
            started_at[node_id] = loop.time()
            tasks[node_id] = asyncio.create_task(
                self._run_node(node, ctx, deps, completion_queue)
            )
            active_count += 1
            self.logger.info("Dispatched node %r", node_id)
            self._notify_node_event(
                "node_started", node_id,
                {"flow": self.name, "context": ctx},
            )

        def _edge_passes(edge: Any, source_result: Any, source_error: Optional[BaseException]) -> bool:
            """Evaluate whether a transition edge allows dispatch of its target.

            Returns True if the edge condition is satisfied. Handles the four
            built-in edge conditions plus predicate evaluation (CEL string or
            Python callable).
            """
            condition = getattr(edge, "condition", "always")
            predicate = getattr(edge, "predicate", None)

            if condition == "always":
                # A failed source must not fire its normal-path edges; only
                # on_error / on_timeout edges route failures.
                return source_error is None
            if condition == "on_success":
                return source_error is None
            if condition == "on_error":
                return source_error is not None
            if condition == "on_timeout":
                # Timeout detection is not implemented in this scheduler version;
                # treat as error for routing purposes.
                return isinstance(source_error, asyncio.TimeoutError)
            if condition == "on_condition" and predicate:
                if source_error is not None:
                    return False
                if callable(predicate):
                    try:
                        return bool(predicate(source_result))
                    except Exception as exc:  # noqa: BLE001 - predicate guard
                        self.logger.warning(
                            "Predicate callable failed for edge %r → %r: %s",
                            edge.from_, edge.to, exc,
                        )
                        return False
                try:
                    evaluator = CELPredicateEvaluator(predicate)
                    return evaluator(source_result, error=source_error)
                except Exception as exc:
                    self.logger.warning(
                        "CEL predicate failed for edge %r → %r: %s",
                        edge.from_,
                        edge.to,
                        exc,
                    )
                    return False

            return True  # unknown condition: allow transition

        # ── Explicit-mode join helpers (OR-join + skip-propagation) ──────

        def _edge_resolved(edge: Any) -> bool:
            """An edge is resolved once its source reached a terminal state."""
            src = edge.from_
            return src in completed or src in failed or src in skipped

        def _edge_fired(edge: Any) -> bool:
            """A resolved edge fired if its source ran and the condition holds."""
            src = edge.from_
            if src in skipped:
                return False
            if src in completed or src in failed:
                return _edge_passes(edge, results.get(src), errors.get(src))
            return False

        def _resolve_ready_targets() -> None:
            """Dispatch / skip every node whose incoming edges are all resolved.

            Runs to a fixpoint so a skip cascades through its descendants in
            the same pass (e.g. a failed node skips its whole success path,
            which in turn resolves a downstream error-handler's fan-in).
            """
            progress = True
            while progress:
                progress = False
                for tgt, in_edges in incoming.items():
                    if not in_edges:
                        continue  # entry node — dispatched at start
                    if (
                        tgt in completed or tgt in failed
                        or tgt in skipped or tgt in tasks
                    ):
                        continue
                    if not all(_edge_resolved(e) for e in in_edges):
                        continue
                    if any(_edge_fired(e) for e in in_edges):
                        _spawn(tgt)
                    else:
                        skipped.add(tgt)
                        try:
                            # idle → blocked: the FSM's terminal marker for
                            # "never ran" — post-run inspection can tell a
                            # skipped node (blocked) from a pending one (idle).
                            nodes[tgt].fsm.block()
                        except Exception:  # noqa: BLE001 - telemetry only
                            pass
                        self.logger.info(
                            "Node %r skipped (no incoming edge fired)", tgt
                        )
                        self._notify_node_event(
                            "node_skipped", tgt,
                            {"flow": self.name, "context": ctx},
                        )
                    progress = True

        # Run-level bracket: flow_started precedes every node_started.
        self._notify_node_event(
            "flow_started", "",
            {"flow": self.name, "context": ctx, "node_count": len(nodes)},
        )

        # Initial dispatch — entry nodes.
        if explicit_mode:
            for nid in nodes:
                if not incoming[nid]:
                    _spawn(nid)
        else:
            for nid, node in nodes.items():
                if not node.dependencies:
                    _spawn(nid)

        # Main event loop — drain completion events.
        while active_count > 0 or not completion_queue.empty():
            event: CompletionEvent = await completion_queue.get()
            active_count -= 1
            nid = event.node_id
            durations[nid] = loop.time() - started_at.get(nid, run_started_at)
            self.logger.debug("Received completion event for node %r", nid)

            if event.error is not None:
                # Retry if max_retries > 0 and attempts not exhausted.
                max_r = getattr(nodes[nid], "max_retries", 0)
                if attempts[nid] < max_r:
                    attempts[nid] += 1
                    self.logger.info(
                        "Retrying node %r (attempt %d/%d)",
                        nid, attempts[nid], max_r,
                    )
                    # Replace the node with a fresh copy (new FSM in idle state)
                    # so that _run_node can call fsm.schedule() without hitting
                    # "Can't schedule when in failed" on the previous FSM instance.
                    old_node = nodes[nid]
                    new_fsm = AgentTaskMachine(agent_name=nid)
                    try:
                        nodes[nid] = old_node.model_copy(update={"fsm": new_fsm})
                    except Exception:
                        pass  # fallback: keep old node (FSM error will surface)
                    _spawn(nid)
                    continue
                errors[nid] = event.error
                failed.add(nid)
                if isinstance(event.error, Exception):
                    ctx.mark_failed(nid, event.error)
                self.logger.warning("Node %r failed: %s", nid, event.error)
                self._notify_node_event(
                    "node_failed", nid,
                    {
                        "flow": self.name,
                        "context": ctx,
                        "error": str(event.error),
                        "error_type": type(event.error).__name__,
                        "duration_ms": durations[nid] * 1000.0,
                    },
                )
            else:
                results[nid] = event.result
                completed.add(nid)
                ctx.mark_completed(nid, result=event.result)
                self.logger.info("Node %r completed", nid)
                self._notify_node_event(
                    "node_completed", nid,
                    {
                        "flow": self.name,
                        "context": ctx,
                        "duration_ms": durations[nid] * 1000.0,
                    },
                )

            if explicit_mode:
                # OR-join + skip-propagation over the whole graph.
                _resolve_ready_targets()
                continue

            # Legacy AND-join: evaluate outgoing edges of the finished node.
            source_error = errors.get(nid)
            for edge in edges:
                # Only edges from the just-completed node.
                if edge.from_ != nid:
                    continue

                # Handle both str and list targets (fan-out).
                targets = [edge.to] if isinstance(edge.to, str) else list(edge.to)
                for tgt in targets:
                    if tgt not in nodes:
                        continue
                    if tgt in completed or tgt in failed or tgt in tasks:
                        continue
                    if not _edge_passes(edge, results.get(nid), source_error):
                        continue
                    if all(d in completed for d in nodes[tgt].dependencies):
                        _spawn(tgt)

        aggregated = self._aggregate_result(
            nodes, results, errors, completed, failed,
            edges=edges if explicit_mode else None,
            durations=durations,
        )
        self._notify_node_event(
            "flow_completed", "",
            {
                "flow": self.name,
                "context": ctx,
                "status": aggregated.status.value,
                "duration_ms": (loop.time() - run_started_at) * 1000.0,
                "completed_count": len(completed),
                "failed_count": len(failed),
                "skipped_count": len(skipped),
            },
        )

        # Fire on_complete hooks sequentially; errors are logged, not re-raised.
        for hook in on_complete:
            try:
                await hook(ctx, aggregated)
            except Exception as exc:
                self.logger.warning("on_complete hook raised: %s", exc)

        return aggregated


# ─── New Node subclasses (TASK-1066) ─────────────────────────────────────────


@register_node("decision")
class DecisionNode(Node):
    """Wraps the legacy DecisionFlowNode as a frozen Pydantic Node.

    Holds a ``DecisionNodeConfig`` and a dict of participating agents;
    constructs a fresh ``DecisionFlowNode`` on each ``execute()`` call so
    per-run state is isolated (B-lite contract).

    Args:
        node_id: Unique identifier within the graph.
        decision_config: Configuration for the decision node (mode, etc.).
        agents: Mapping of agent_name → agent instance participating in the
            decision. These are forwarded to the legacy DecisionFlowNode.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if None.
    """

    node_id: str
    decision_config: DecisionNodeConfig
    agents: Dict[str, Any] = PydanticField(default_factory=dict)
    """Participating agents forwarded to DecisionFlowNode.  Typed as Dict[str, Any]
    because arbitrary agent types (BasicAgent, AbstractBot, etc.) are allowed."""
    dependencies: Set[str] = PydanticField(default_factory=set)
    successors: Set[str] = PydanticField(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook."""
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier."""
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> DecisionResult:
        """Execute the decision node.

        Constructs a fresh legacy DecisionFlowNode from the stored config and
        agents, calls its .ask() method with a prompt derived from the context,
        and returns the DecisionResult.

        Args:
            ctx: The current flow execution context.
            deps: Results from completed dependencies.
            **kwargs: Extra execution context (session_id, user_id, timeout, …).

        Returns:
            DecisionResult with final_decision and voting details.
        """
        await self.run_pre_actions(prompt="", **kwargs)

        # Build a fresh canonical DecisionFlowNode per execute() — no shared per-run state.
        legacy = DecisionFlowNode(
            node_id=self.node_id,
            agents=self.agents,
            config=self.decision_config,
        )

        # Build a simple prompt from the flow's initial task.
        prompt = getattr(ctx, "initial_task", "") or ""

        result: DecisionResult = await legacy.ask(question=prompt, **kwargs)
        await self.run_post_actions(result=result, **kwargs)
        return result


@register_node("interactive_decision")
class InteractiveDecisionFlowNode(Node):
    """DAG-executor wrapper for the CLI-blocking interactive decision node.

    Registered in NODE_REGISTRY under ``"interactive_decision"``.  The
    canonical implementation (with the interactive prompt logic) lives in
    :class:`parrot.bots.flows.flow.nodes.InteractiveDecisionNode`.

    This wrapper delegates ``execute()`` to a fresh canonical node per
    invocation so per-run state is isolated.

    Args:
        node_id: Unique identifier within the graph.
        question: The prompt text shown to the user.
        options: A list of string options to choose from.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if None.
    """

    node_id: str
    question: str
    options: List[str] = PydanticField(default_factory=list)
    dependencies: Set[str] = PydanticField(default_factory=set)
    successors: Set[str] = PydanticField(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook."""
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier."""
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> DecisionResult:
        """Present a CLI menu and return the user's selection as a DecisionResult.

        Uses the canonical nodes.InteractiveDecisionNode implementation via
        delegation — constructs a fresh node per execute() call so per-run
        state is isolated.

        Args:
            ctx: The current flow execution context.
            deps: Results from completed dependencies.
            **kwargs: Extra execution context forwarded to the node.

        Returns:
            DecisionResult with the user's selection in final_decision.
        """
        from .nodes import (  # noqa: PLC0415
            InteractiveDecisionNode as _InteractiveDecisionNode,
        )

        await self.run_pre_actions(prompt=self.question, **kwargs)

        canonical = _InteractiveDecisionNode(
            node_id=self.node_id,
            question=self.question,
            options=self.options,
        )
        result: DecisionResult = await canonical.ask(question=self.question, **kwargs)
        await self.run_post_actions(result=result, **kwargs)
        return result


# Backward-compatible alias: existing imports and NODE_REGISTRY checks use this name.
InteractiveDecisionNode = InteractiveDecisionFlowNode


@register_node("synthesis")
class SynthesisNode(Node):
    """In-graph result synthesis using the ``synthesize_results`` util.

    Acts as a leaf or near-leaf node that aggregates upstream agent results
    and passes them to the shared ``synthesize_results`` function (TASK-1063).
    The result is a string summary.

    The ``ctx.synthesis_client`` attribute must be set before the scheduler
    runs this node (or a RuntimeError is raised).

    NOTE: FEAT-196 deferred — once the scheduler exposes a partial FlowResult
    on the context, pass it directly to ``synthesize_results`` instead of
    constructing a minimal view from ``deps``. Tracked as tech debt post-migration.

    Args:
        node_id: Unique identifier within the graph.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if None.
    """

    node_id: str
    dependencies: Set[str] = PydanticField(default_factory=set)
    successors: Set[str] = PydanticField(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook."""
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier."""
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> str:
        """Run LLM synthesis over the accumulated dependency results.

        Builds a minimal ``FlowResult``-like view from ``deps`` and delegates
        to ``synthesize_results(ctx, partial_result)``.

        Args:
            ctx: The current flow execution context. Must have ``synthesis_client``
                set (see ``FlowContext.synthesis_client``).
            deps: Mapping of completed dependency node_id → result string.
            **kwargs: Forwarded to ``synthesize_results`` (max_tokens, temperature,
                user_id, session_id).

        Returns:
            Synthesis summary string.
        """
        await self.run_pre_actions(prompt="synthesis", **kwargs)

        # Build a minimal FlowResult-like object from the dependency results.
        # FEAT-196 deferred: once the scheduler exposes ctx.partial_result, use it directly.
        class _PartialResult:
            """Minimal FlowResult duck-type for synthesize_results."""

            def __init__(self, responses: Dict[str, Any]) -> None:
                self.responses = responses
                self.summary = ""

        partial = _PartialResult(responses=dict(deps))

        summary = await synthesize_results(ctx, partial)  # type: ignore[arg-type]
        await self.run_post_actions(result=summary, **kwargs)
        return summary


# ─── Register built-in core Node types ───────────────────────────────────────
# Must come AFTER the class definitions so the Node subclasses are in scope.

register_node("agent")(AgentNode)
register_node("start")(StartNode)
register_node("end")(EndNode)


# ─── Public API ───────────────────────────────────────────────────────────────

__all__ = [
    "AgentsFlow",
    "CompletionEvent",
    "EDGE_CONDITIONS",
    "FlowEdge",
    "NODE_REGISTRY",
    "register_node",
    # Node subclasses (TASK-1066)
    "DecisionNode",
    "InteractiveDecisionFlowNode",
    "InteractiveDecisionNode",  # backward-compatible alias for InteractiveDecisionFlowNode
    "SynthesisNode",
]
