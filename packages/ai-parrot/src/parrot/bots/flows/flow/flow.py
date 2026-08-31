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
import os
import socket
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple, Type, Union

from pydantic import BaseModel, ValidationError
from pydantic import Field as PydanticField
from navconfig.logging import logging

# ─── flows.core primitives (import, do not redefine) ────────────────────────

from ..core.node import AgentNode, EndNode, Node, StartNode
from ..core.context import FlowContext
from ..core.fsm import AgentTaskMachine
from ..core.result import (
    FlowResult,
    _serialise_result_value,
    build_node_metadata,
    determine_run_status,
)
from ..core.checkpoint.checkpointer import FlowCheckpointer
from ..core.checkpoint.errors import (
    CheckpointFingerprintMismatchError,
    CheckpointNotFoundError,
    CheckpointPersistenceError,
    FlowNotExportableError,
)
from ..core.checkpoint.model import CheckpointInputMetadata, FlowCheckpoint, MemoryRefs
from ..core.checkpoint.serializer import FlowStateSerializer
from ..core.checkpoint.store.base import CheckpointStore
from ..core.checkpoint.recovery import get_recovery_service
from ..core.checkpoint.store.factory import get_checkpoint_store
from ..core.storage import PersistenceMixin
from ..core.storage.synthesis import synthesize_results
from ..core.types import DependencyResults
from parrot.conf import FLOW_CHECKPOINT_HISTORY, FLOW_CHECKPOINT_REDIS_TTL

# Declarative layer (intra-subpackage)
from .definition import EdgeDefinition, FlowDefinition, NodeDefinition

# Decision-node canonical implementations (TASK-1311)
from .nodes import (
    DecisionFlowNode,
    DecisionNodeConfig,
    DecisionResult,
)

# Declarative config models for the built-in node types.
from .node_configs import (
    DecisionConfigDef,
    InteractiveDecisionConfigDef,
    SynthesisConfigDef,
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

NODE_CONFIG_MODELS: dict[str, Type[BaseModel]] = {}
"""Optional mapping of node type name → Pydantic model for ``NodeDefinition.config``.

A type present here declares the shape of its ``config`` block, which makes
two things possible that a bare ``Dict[str, Any]`` cannot:

* ``_materialize_nodes`` can build the node from a definition alone, without
  the caller having to supply a ``node_factories`` entry (see the ``else``
  branch below);
* the authoring catalog can publish a real JSON Schema per node type, so a
  model emitting a ``FlowDefinition`` is constrained instead of guessing.

Registration is opt-in — a type with no entry keeps the historical
"construct with node_id/dependencies/successors only" behaviour.
"""


def register_node(
    name: str,
    *,
    config_model: Optional[Type[BaseModel]] = None,
) -> Callable[[Type[Node]], Type[Node]]:
    """Register a Node subclass under ``name`` in ``NODE_REGISTRY``.

    This is a decorator factory; apply it to a Node subclass:

    Example::

        @register_node("my-type", config_model=MyNodeConfig)
        class MyNode(AgentNode):
            ...

    Args:
        name: The type key under which to register the class. Must be unique
            across the registry.
        config_model: Optional Pydantic model describing this type's
            ``NodeDefinition.config`` block. When supplied, the model's
            validated fields are expanded into the node constructor by
            ``AgentsFlow._materialize_nodes``, so the type becomes usable
            from a pure ``FlowDefinition`` with no ``node_factories`` entry.
            Keyword-only and optional, so existing call sites are unaffected.

    Returns:
        A decorator that registers the class and returns it unchanged.

    Raises:
        ValueError: If ``name`` is already registered.
        TypeError: If the decorated class is not a ``Node`` subclass, or
            ``config_model`` is not a ``BaseModel`` subclass.
    """
    if config_model is not None and not (isinstance(config_model, type) and issubclass(config_model, BaseModel)):
        raise TypeError(
            f"register_node({name!r}, config_model=...) expects a pydantic " f"BaseModel subclass, got {config_model!r}"
        )

    def decorator(cls: Type[Node]) -> Type[Node]:
        if not (isinstance(cls, type) and issubclass(cls, Node)):
            raise TypeError(f"@register_node({name!r}) target must be a Node subclass, got {cls!r}")
        if name in NODE_REGISTRY:
            raise ValueError(f"Node type {name!r} already registered to " f"{NODE_REGISTRY[name].__name__}")
        NODE_REGISTRY[name] = cls
        if config_model is not None:
            NODE_CONFIG_MODELS[name] = config_model
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
        checkpoint: Enable AgentsFlow state checkpointing (FEAT-399).
            Default ``False`` — zero behavior change when omitted.
        checkpoint_retention: Ephemeral (Redis) checkpoint TTL in seconds.
            Defaults to ``FLOW_CHECKPOINT_REDIS_TTL``.
        checkpoint_history: Max retained checkpoints per flow. Defaults to
            ``FLOW_CHECKPOINT_HISTORY``.
        checkpoint_include_responses: Include raw per-node responses in
            checkpoints (heavy; results-only by default).
        checkpoint_definition: Optional externally-supplied ``FlowDefinition``
            embedded in every checkpoint instead of the result of
            ``self.to_definition()``. Required for any explicit-edge graph
            with callable predicates — those fail ``to_definition()``
            (line 652) since a Python callable cannot round-trip through a
            declarative definition. ``None`` (default) keeps the historical
            behavior of deriving the definition via ``to_definition()``.
        checkpoint_shared_data: Optional ``(ctx) -> dict[str, Any]``
            projector used instead of the raw ``ctx.shared_data`` mapping
            when building every checkpoint. See
            ``FlowCheckpointer.__init__``'s ``shared_data_projector`` for
            the full rationale (never persist live objects). ``None``
            (default) keeps the historical behavior.
        checkpoint_input: Optional immutable ``CheckpointInputMetadata``
            embedded on every checkpoint this flow builds. Compared against
            ``resume(expected_input=...)`` to reject reusing a ``run_id``
            whose recorded input no longer matches. ``None`` (default,
            the only value generic non-dev-workflow callers ever pass)
            leaves ``FlowCheckpoint.input_metadata`` unset.
        checkpoint_required: When True, the explicit-mode scheduler awaits
            ``FlowCheckpointer.checkpoint(ctx)`` after every successful
            node's ``mark_completed()`` (and after any retry-reset is
            applied) and BEFORE dispatching any downstream/back-edge
            target — a required persistence barrier, not best-effort
            telemetry. A ``CheckpointPersistenceError`` (including a lost
            resume lease) fails the run: already-active sibling tasks are
            cancelled and no new work is dispatched. Required mode also
            bypasses the fire-and-forget ``make_listener()`` write path
            entirely — the awaited barrier is the sole persistence
            mechanism (spec §7: "required persistence must not run through
            make_listener()"). Default ``False`` keeps the existing
            best-effort listener path byte-for-byte unchanged.
        durable: Write-through every checkpoint to the durable store too.
        checkpoint_store: Ephemeral ``CheckpointStore`` name/instance/None
            (env fallback) — resolved via ``get_checkpoint_store()``.
        durable_store: Durable ``CheckpointStore`` name/instance/None.
        flow_id: Stable identifier for this flow run, used as the
            checkpoint key. Auto-generated (UUID4) when omitted.
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
        checkpoint: bool = False,
        checkpoint_retention: Optional[int] = None,
        checkpoint_history: Optional[int] = None,
        checkpoint_include_responses: bool = False,
        checkpoint_definition: Optional[FlowDefinition] = None,
        checkpoint_shared_data: Optional[Callable[[FlowContext], Dict[str, Any]]] = None,
        checkpoint_input: Optional[CheckpointInputMetadata] = None,
        checkpoint_required: bool = False,
        durable: bool = False,
        checkpoint_store: Optional[Union[str, CheckpointStore]] = None,
        durable_store: Optional[Union[str, CheckpointStore]] = None,
        flow_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self._definition = definition
        self._agent_registry = agent_registry
        # Optional per-type factories for custom (non agent/start/end) node
        # types, injected via ``from_definition(node_factories=...)``. Each
        # factory closes over live dependencies (dispatcher, toolkits, …) and
        # is called as ``factory(node_def, deps, succs) -> Node`` afresh per
        # ``run_flow()`` so concurrent runs do not share node state.
        self._node_factories: dict[str, Callable[["NodeDefinition", set[str], set[str]], Node]] = {}
        # node_id → single resolved agent (agent nodes), and node_id →
        # {agent_name: instance} for multi-agent types (decision). Both are
        # populated by ``from_definition``; empty in programmatic mode.
        self._resolved_agents: dict[str, Any] = {}
        self._resolved_agent_groups: dict[str, dict[str, Any]] = {}
        self._nodes: dict[str, Node] = {}
        self._edges: list[FlowEdge] = []
        self._node_event_listeners: list[Callable[[str, str, Dict[str, Any]], Any]] = []
        # Fire-and-forget tasks spawned for async listeners. Tracked (not just
        # scheduled) so ``run_flow`` can drain them before it returns —
        # otherwise the last events of a run (a node failing, then the
        # terminal node) can still be in flight when the caller snapshots
        # its own state from them.
        self._pending_event_tasks: "set[asyncio.Task[Any]]" = set()
        if on_node_event is not None:
            if callable(on_node_event):
                self._node_event_listeners.append(on_node_event)
            else:
                self._node_event_listeners.extend(on_node_event)
        self.logger = logging.getLogger(f"parrot.flow.{name}")

        # ── Checkpointing (FEAT-399) ────────────────────────────────────
        self.flow_id: str = flow_id or str(uuid.uuid4())
        self._checkpoint_enabled = checkpoint
        self._checkpoint_retention = FLOW_CHECKPOINT_REDIS_TTL if checkpoint_retention is None else checkpoint_retention
        self._checkpoint_history = FLOW_CHECKPOINT_HISTORY if checkpoint_history is None else checkpoint_history
        self._checkpoint_include_responses = checkpoint_include_responses
        # External declarative definition (explicit-edge graphs with
        # callable predicates fail to_definition()) + allowlisted
        # shared-data projector, both threaded into FlowCheckpointer by
        # _ensure_checkpointer() (spec §3 Module 2).
        self._checkpoint_definition_arg = checkpoint_definition
        self._checkpoint_shared_data_arg = checkpoint_shared_data
        self._checkpoint_input_arg = checkpoint_input
        # Required checkpoint barrier (spec §3 Module 2) — the explicit-mode
        # scheduler awaits FlowCheckpointer.checkpoint() before dispatching
        # any downstream/back-edge target when True. Default False keeps
        # the historical best-effort listener path byte-for-byte unchanged.
        self._checkpoint_required = checkpoint_required
        self._checkpoint_durable = durable
        self._checkpoint_store_arg = checkpoint_store
        self._durable_store_arg = durable_store
        self._checkpointer: Optional[FlowCheckpointer] = None
        # Set by resume() so a resumed run's checkpoint numbering/parent
        # chain continues from the loaded checkpoint instead of starting
        # fresh at 1 (see FlowCheckpointer's `starting_checkpoint_id`).
        self._resume_starting_checkpoint_id: int = 0
        # Set by resume() so run_flow() seeds the scheduler from the
        # loaded checkpoint's FlowContext instead of starting empty.
        self._resume_seed_context: Optional[FlowContext] = None
        # Memory refs carried across suspend/resume (session/chatbot/user
        # ids) — never conversational memory content (spec §2).
        self._checkpoint_memory_refs: MemoryRefs = MemoryRefs()
        # The live FlowContext of the currently-executing run_flow() call, if
        # any — lets suspend() dump a mid-run snapshot from outside run_flow().
        self._active_ctx: Optional[FlowContext] = None

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
            raise ValueError(f"Node {node.node_id!r} already added to flow {self.name!r}")
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
            raise ValueError(f"Unknown edge condition {condition!r}. " f"Expected one of {EDGE_CONDITIONS}")
        if condition == "on_condition" and predicate is None:
            raise ValueError("Edge condition 'on_condition' requires a predicate " "(CEL string or callable)")
        edge = FlowEdge(from_=from_, to=to, condition=condition, predicate=predicate)
        self._edges.append(edge)
        self.logger.debug("Added edge %r → %r (%s) to flow %r", from_, to, condition, self.name)
        return edge

    # ── Node-event notification ───────────────────────────────────────────

    def add_node_event_listener(self, callback: Callable[[str, str, Dict[str, Any]], Any]) -> None:
        """Attach an additional node-event listener.

        Listeners are invoked in registration order with the same
        ``(event, node_id, info)`` contract as the constructor's
        ``on_node_event`` parameter. Use this to compose several consumers
        (e.g. a Redis publisher plus a lifecycle-telemetry adapter).

        Args:
            callback: Sync or async callable ``(event, node_id, info)``.
        """
        self._node_event_listeners.append(callback)

    def _notify_node_event(self, event: str, node_id: str, info: Dict[str, Any]) -> None:
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
                    self._pending_event_tasks.add(task)
                    task.add_done_callback(self._pending_event_tasks.discard)
                    task.add_done_callback(self._log_event_task_error)
            except Exception as exc:  # noqa: BLE001 - telemetry must not break runs
                self.logger.warning(
                    "node-event listener raised for %s/%s: %s",
                    event,
                    node_id,
                    exc,
                )

    def _log_event_task_error(self, task: "asyncio.Task[Any]") -> None:
        """Done-callback that logs (instead of raising) async event errors."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self.logger.warning("async on_node_event callback raised: %s", exc)

    async def _drain_event_tasks(self, timeout: float = 5.0) -> None:
        """Await the in-flight async node-event tasks (bounded, never raises).

        ``_notify_node_event`` schedules async listeners fire-and-forget so a
        slow listener cannot stall the scheduler. That is right *during* a
        run and wrong at the *end* of one: the events describing how a run
        finished (``node_failed`` on the node that broke, then the terminal
        node's own lifecycle) are emitted within milliseconds of
        ``run_flow`` returning, and a caller that folds those events into its
        own state — the dev-loop ``SessionHost`` — would snapshot before they
        landed. A failed node then stays "running" in the console forever.

        Args:
            timeout: Upper bound in seconds. A listener still running past it
                is left alone (its own done-callback logs any error); the run
                result is never held hostage to telemetry.
        """
        pending = [t for t in self._pending_event_tasks if not t.done()]
        if not pending:
            return
        try:
            await asyncio.wait(pending, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - telemetry must not break runs
            self.logger.warning("draining node-event tasks raised: %s", exc)

    # ── Class-method factory (placeholder — TASK-1068) ────────────────────

    @classmethod
    def from_definition(
        cls,
        definition: FlowDefinition,
        *,
        agent_registry: Optional[AgentRegistry] = None,
        node_factories: Optional[dict[str, Callable[["NodeDefinition", set[str], set[str]], Node]]] = None,
        checkpoint: Optional[bool] = None,
        checkpoint_retention: Optional[int] = None,
        checkpoint_history: Optional[int] = None,
        checkpoint_include_responses: Optional[bool] = None,
        durable: Optional[bool] = None,
        checkpoint_store: Optional[Union[str, CheckpointStore]] = None,
        durable_store: Optional[Union[str, CheckpointStore]] = None,
        flow_id: Optional[str] = None,
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
            node_factories: Optional ``{node_type: factory}`` map for custom
                (non ``agent``/``start``/``end``) node types. ``factory`` is
                called as ``factory(node_def, deps, succs) -> Node`` inside
                ``_materialize_nodes()`` (fresh per ``run_flow()``), letting the
                node close over live dependencies (dispatcher, toolkits, …)
                that cannot travel through the plain ``NodeDefinition.config``
                dict. Node types still must be registered in ``NODE_REGISTRY``.
            checkpoint: Explicit override for checkpointing (FEAT-399). When
                ``None`` (default), falls back to ``definition.metadata.checkpoint``.
                A constructor-level override always wins over the metadata block.
            checkpoint_retention: See ``AgentsFlow.__init__``; falls back to
                ``definition.metadata.checkpoint_retention`` when ``None``.
            checkpoint_history: See ``AgentsFlow.__init__``; falls back to
                ``definition.metadata.checkpoint_history`` when ``None``.
            checkpoint_include_responses: See ``AgentsFlow.__init__``; falls
                back to ``definition.metadata.checkpoint_include_responses``.
            durable: See ``AgentsFlow.__init__``; falls back to
                ``definition.metadata.durable`` when ``None``.
            checkpoint_store: See ``AgentsFlow.__init__``.
            durable_store: See ``AgentsFlow.__init__``.
            flow_id: See ``AgentsFlow.__init__``.

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
                "AgentsFlow.from_definition() requires an agent_registry. " "Pass an AgentRegistry instance explicitly."
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
                raise AgentNotFoundError(f"Cannot resolve agent_ref {agent_ref!r} for node {node_def.id!r}")
            # Keyed by node_id so _materialize_nodes can look up by node_def.id.
            resolved_agents[node_def.id] = agent

        # Also validate non-agent node types are registered, and resolve the
        # agent *groups* a decision node votes with. A decision node has no
        # agent_ref (it has several agents, not one), so its participants are
        # named declaratively in ``config.agent_refs``; without resolving them
        # here the node would be built with an empty ``agents`` mapping and
        # run a vote with no voters.
        resolved_groups: dict[str, dict[str, Any]] = {}
        for node_def in definition.nodes:
            if node_def.type == "agent":
                continue  # already checked above
            if node_def.type not in NODE_REGISTRY:
                raise ValueError(
                    f"NodeDefinition {node_def.id!r}: node_type {node_def.type!r} "
                    f"not in NODE_REGISTRY. Registered types: {sorted(NODE_REGISTRY)}"
                )
            refs = (node_def.config or {}).get("agent_refs") or []
            if not refs:
                continue
            group: dict[str, Any] = {}
            for ref in refs:
                agent = agent_registry.get_bot_instance(ref)
                if agent is None:
                    raise AgentNotFoundError(f"Cannot resolve agent_refs entry {ref!r} for node " f"{node_def.id!r}")
                group[ref] = agent
            resolved_groups[node_def.id] = group

        # Construct the flow with the definition bound.
        # FlowDefinition uses .flow for the name.
        flow_name = getattr(definition, "flow", None) or getattr(definition, "name", "unnamed")
        meta = definition.metadata
        flow = cls(
            name=flow_name,
            definition=definition,
            agent_registry=agent_registry,
            checkpoint=checkpoint if checkpoint is not None else meta.checkpoint,
            checkpoint_retention=(
                checkpoint_retention if checkpoint_retention is not None else meta.checkpoint_retention
            ),
            checkpoint_history=(checkpoint_history if checkpoint_history is not None else meta.checkpoint_history),
            checkpoint_include_responses=(
                checkpoint_include_responses
                if checkpoint_include_responses is not None
                else meta.checkpoint_include_responses
            ),
            durable=durable if durable is not None else meta.durable,
            checkpoint_store=checkpoint_store,
            durable_store=durable_store,
            flow_id=flow_id,
        )
        # Attach pre-resolved agent map (keyed by node_id).
        flow._resolved_agents = resolved_agents
        # Agent *groups* for multi-agent node types (decision), keyed by node_id.
        flow._resolved_agent_groups = resolved_groups
        # Attach custom-node factories (keyed by NodeDefinition.type).
        flow._node_factories = dict(node_factories or {})
        return flow

    # ── Graph → FlowDefinition export (FEAT-399 TASK-2052) ─────────────────

    @staticmethod
    def _registry_type_name(node: Node) -> Optional[str]:
        """Return the ``NODE_REGISTRY`` key for ``node``'s class, if any.

        Prefers an exact class match; falls back to ``isinstance`` for
        registered base classes (covers subclasses of a registered type).

        Args:
            node: The node instance to look up.

        Returns:
            The registered type name, or ``None`` if unregistered.
        """
        node_cls = type(node)
        for type_name, cls in NODE_REGISTRY.items():
            if cls is node_cls:
                return type_name
        for type_name, cls in NODE_REGISTRY.items():
            if isinstance(node, cls):
                return type_name
        return None

    def to_definition(self) -> FlowDefinition:
        """Export this flow's graph to a ``FlowDefinition`` (spec §3 Module 7).

        For a flow already built via ``from_definition()``, returns the
        bound ``FlowDefinition`` unchanged. For a programmatic flow (built
        via ``add_node``/``add_edge``), inverts the mapping performed by
        ``from_definition``/``_materialize_nodes`` to construct one: every
        node's type must be registered in ``NODE_REGISTRY``, and every
        ``agent``-type node must expose a resolvable string ``agent_ref``
        (its wrapped agent's ``.name``). This is a pure export — it never
        mutates the flow.

        Returns:
            A validated ``FlowDefinition`` equivalent to this flow's graph.

        Raises:
            FlowNotExportableError: If a node's class is not registered in
                ``NODE_REGISTRY``, an ``agent``-type node has no resolvable
                string ``agent_ref``, or an edge's ``predicate`` is a live
                Python callable (only CEL expression strings round-trip).
        """
        if self._definition is not None:
            return self._definition

        node_defs: list[NodeDefinition] = []
        for node_id, node in self._nodes.items():
            type_name = self._registry_type_name(node)
            if type_name is None:
                raise FlowNotExportableError(
                    f"Node {node_id!r} (class {type(node).__name__}) is not "
                    "registered in NODE_REGISTRY; cannot export flow "
                    f"{self.name!r} to a FlowDefinition."
                )

            agent_ref: Optional[str] = None
            if type_name == "agent":
                agent_ref = getattr(getattr(node, "agent", None), "name", None)
                if not agent_ref:
                    raise FlowNotExportableError(
                        f"Node {node_id!r} of type 'agent' has no resolvable "
                        "string agent_ref (its agent has no stable .name); "
                        f"cannot export flow {self.name!r} to a FlowDefinition."
                    )

            node_defs.append(NodeDefinition(id=node_id, type=type_name, agent_ref=agent_ref))

        edge_defs: list[EdgeDefinition] = []
        for edge in self._edges:
            if edge.predicate is not None and not isinstance(edge.predicate, str):
                raise FlowNotExportableError(
                    f"Edge {edge.from_!r} -> {edge.to!r} has a live Python "
                    "callable predicate; cannot export flow "
                    f"{self.name!r} to a FlowDefinition (only CEL expression "
                    "strings round-trip)."
                )
            edge_defs.append(
                EdgeDefinition(
                    **{
                        "from": edge.from_,
                        "to": edge.to,
                        "condition": edge.condition,
                        "predicate": edge.predicate,
                    }
                )
            )

        return FlowDefinition(flow=self.name, nodes=node_defs, edges=edge_defs)

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
                new_fsm = AgentTaskMachine(agent_name=getattr(node, "node_id", nid))
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
                    f"Unknown node type {node_type!r} in flow {self.name!r}. " f"Available: {sorted(NODE_REGISTRY)}"
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
                    max_retries=node_def.max_retries,
                )
            elif node_type in ("start", "end"):
                # StartNode/EndNode declare no `fsm` field (only AgentNode
                # does), yet `_run_node()` unconditionally calls
                # `node.fsm.schedule()/.start()/.succeed()/.fail()` for
                # EVERY dispatched node. The programmatic branch above
                # (`self._definition is None`) already papers over this via
                # `node.model_copy(update={"fsm": new_fsm})`; the
                # definition-driven branch never did, because no existing
                # FlowDefinition-based flow in this codebase used "start"/
                # "end" node types before FEAT-419's `plan/compile.py::
                # to_flow_definition()` started emitting `__start__`/
                # `__end__` sentinels unconditionally. Mirror the same
                # model_copy patch here so a defined-then-run flow with
                # start/end sentinels does not crash on its first dispatch.
                start_end_node = cls(
                    node_id=nid,
                    dependencies=deps,
                    successors=succs,
                )
                fresh[nid] = start_end_node.model_copy(update={"fsm": AgentTaskMachine(agent_name=nid)})
            else:
                # Custom node type: prefer a registered factory so the node can
                # close over live dependencies (dispatcher, toolkits, …) that a
                # plain ``NodeDefinition.config`` dict cannot carry. The factory
                # is invoked fresh on every ``run_flow()`` (B-lite contract).
                factory = self._node_factories.get(node_type)
                if factory is not None:
                    fresh[nid] = factory(node_def, deps, succs)
                else:
                    fresh[nid] = self._build_node_from_config(
                        cls,
                        node_type,
                        node_def,
                        deps,
                        succs,
                        resolved_agents=self._resolved_agent_groups.get(nid),
                    )

        return fresh

    @staticmethod
    def _build_node_from_config(
        cls: Type[Node],
        node_type: str,
        node_def: NodeDefinition,
        deps: set[str],
        succs: set[str],
        resolved_agents: Optional[Dict[str, Any]] = None,
    ) -> Node:
        """Construct a node from ``node_def.config`` alone.

        When ``node_type`` declares a ``config_model`` (see
        ``register_node(..., config_model=...)``), ``node_def.config`` is
        validated against it and the resulting fields are expanded into the
        node constructor. This is what lets a plain ``FlowDefinition``
        express a ``decision`` / ``interactive_decision`` node without the
        caller supplying a matching ``node_factories`` entry — the same
        contract ``make_tool_node_factory`` implements by hand for the
        ``"tool"`` type.

        Types with no registered config model keep the historical behaviour:
        construct with ``node_id`` / ``dependencies`` / ``successors`` only.

        Args:
            cls: The registered ``Node`` subclass for ``node_type``.
            node_type: The ``NODE_REGISTRY`` key being materialized.
            node_def: The definition entry for this node.
            deps: Node ids this node depends on.
            succs: Node ids that depend on this node.
            resolved_agents: Live instances for the agents this node's config
                named in ``agent_refs`` (a ``decision`` node's voters), keyed
                by agent name. ``from_definition`` resolves them; a config
                model that declares an ``agents`` kwarg receives them here.

        Returns:
            A freshly constructed node.

        Raises:
            ValueError: If ``node_def.config`` does not satisfy the type's
                declared config model. The message names the node and the
                offending fields so the error is actionable.
        """
        extra: Dict[str, Any] = {}
        config_model = NODE_CONFIG_MODELS.get(node_type)
        if config_model is not None:
            try:
                parsed = config_model.model_validate(node_def.config or {})
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid 'config' for node {node_def.id!r} of type "
                    f"{node_type!r} (expected {config_model.__name__}): {exc}"
                ) from exc
            to_kwargs = getattr(parsed, "to_node_kwargs", None)
            extra = to_kwargs() if callable(to_kwargs) else parsed.model_dump()

        # Merge the resolved live agents into whatever the config model
        # produced. A JSON document can only name agents, never carry them, so
        # without this a decision node is built with agents={} and its vote has
        # no voters.
        if resolved_agents and "agents" in extra:
            extra["agents"] = {**extra["agents"], **resolved_agents}

        node = cls(
            node_id=node_def.id,
            dependencies=deps,
            successors=succs,
            **extra,
        )
        # ``max_retries`` lives on the definition; mirror it onto the instance
        # so ``_run_node``'s retry budget reads the configured value instead of
        # silently falling back to 0 (the field did not exist on Node before).
        if "max_retries" in type(node).model_fields:
            node = node.model_copy(update={"max_retries": node_def.max_retries})
        return node

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
            node.fsm.schedule()  # idle → ready
            node.fsm.start()  # ready → running
            result = await node.execute(ctx, deps)
            node.fsm.succeed()  # running → completed
            await queue.put(CompletionEvent(node_id=node.node_id, result=result))
        except BaseException as exc:
            try:
                node.fsm.fail()  # any → failed
            except Exception:
                pass  # ignore double-transition errors
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
        *,
        ctx: Optional[FlowContext] = None,
        run_started_at: Optional[float] = None,
        skipped: Optional[set[str]] = None,
    ) -> FlowResult:
        """Build a FlowResult from scheduler state after the main loop exits.

        **Output shape contract (normative, FEAT-447 G4).** ``FlowResult.output``
        is polymorphic and its shape is decided here, by how many *leaf* nodes
        the run actually executed:

        * exactly one executed leaf -> that leaf's **scalar** output (unwrapped
          from its ``AgentNode.execute()`` envelope);
        * a fan-out of two or more executed leaves -> a ``dict[node_id, Any]``
          of each leaf's scalar output;
        * no executed leaf (empty graph, or every leaf failed/skipped) -> an
          empty dict ``{}`` -- that case falls into the fan-out branch with
          nothing to collect. Pre-existing behaviour, left unchanged here
          because normalising it to ``None`` would break an existing field's
          contract; use ``status`` / ``metadata["leaves"]`` to detect it.

        The node_ids that produced ``output`` are echoed in
        ``metadata["leaves"]``. This polymorphism is deliberate and pinned by
        tests -- see :attr:`FlowResult.output`.

        **Timing notes.** ``NodeExecutionInfo.execution_time`` comes from the
        scheduler's ``durations`` (which include spawn/queue overhead), *not*
        from the node's own ``envelope["execution_time"]``; the two coexist and
        measure different spans. Because ``durations[nid]`` is rewritten on
        every completion event, a retried node reports its **last** attempt.
        ``total_time`` is measured against ``run_started_at`` on the event
        loop's monotonic clock -- the same clock the scheduler uses -- so on a
        **resumed** run it is the wall clock of the resumed *segment*, not of
        the original run.

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
            ctx: Optional run context. When supplied, ``nodes`` are ordered by
                its ``completion_order`` (the true execution order) instead of
                by set-iteration order. Failed nodes are absent from
                ``completion_order`` -- ``mark_failed`` does not append -- so
                they are appended afterwards in sorted order.
            run_started_at: Optional ``loop.time()`` reading from the start of
                the run, used for ``total_time``. ``total_time`` stays ``0.0``
                when it is omitted.
            skipped: Optional set of skipped node_ids. Reported through
                ``metadata["skipped"]`` only: ``NodeExecutionInfo.status`` is a
                closed literal with no ``"skipped"`` member, so skipped nodes
                deliberately get no ``NodeExecutionInfo`` entry.

        Returns:
            Populated FlowResult. ``summary`` is intentionally left empty --
            ``AgentsFlow`` does not inherit ``SynthesisMixin``; synthesis stays
            opt-in through ``synthesize_results``.
        """
        # Deterministic node ordering (FEAT-447 G3). `completed | failed` is a
        # set union, so iterating it directly discards execution order and
        # varies with string hashing across processes. `ctx.completion_order`
        # carries the true order; `mark_failed` does NOT append to it, so the
        # residue (failures, and anything seeded by a resume) is appended in
        # sorted order for stability. Without a ctx we still sort rather than
        # iterate the union -- it costs nothing and removes the hash-order
        # nondeterminism unconditionally.
        terminal: set[str] = completed | failed
        ordered: list[str] = []
        if ctx is not None:
            seen: set[str] = set()
            for nid in ctx.completion_order:
                if nid in terminal and nid not in seen:
                    ordered.append(nid)
                    seen.add(nid)
            ordered.extend(sorted(terminal - seen))
        else:
            ordered = sorted(terminal)

        node_infos = []
        execution_log: list[dict[str, Any]] = []
        for nid in ordered:
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
            execution_log.append(
                {
                    "node_id": info.node_id,
                    "node_name": info.node_name,
                    "status": info.status,
                    "execution_time": info.execution_time,
                    "error": info.error,
                }
            )

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
                    targets = [edge.to] if isinstance(edge.to, str) else list(edge.to)
                    outgoing.setdefault(edge.from_, set()).update(targets)
                leaves = [nid for nid in results if not any(t in results for t in outgoing.get(nid, ()))]
        else:
            # Leaf = node with empty successors set.
            leaves = [nid for nid, node in nodes.items() if not node.successors]

        # node_ids that actually contributed to `output` (echoed in metadata).
        output_leaves: list[str] = []
        if len(leaves) == 1 and leaves[0] in results:
            leaf_result = results[leaves[0]]
            # AgentNode.execute() returns a dict with an "output" key holding
            # the actual scalar content. Unwrap it so FlowResult.output is the
            # agent's answer rather than the execution-metadata dict.
            if isinstance(leaf_result, dict) and "output" in leaf_result:
                output: Any = leaf_result["output"]
            else:
                output = leaf_result
            output_leaves = [leaves[0]]
        else:
            # Multi-leaf fan-out: collect each leaf's scalar output.
            output_map: dict[str, Any] = {}
            for nid in leaves:
                if nid in results:
                    lr = results[nid]
                    output_map[nid] = lr["output"] if isinstance(lr, dict) and "output" in lr else lr
            output = output_map
            output_leaves = list(output_map)

        from ..core.types import FlowStatus

        status_str = determine_run_status(len(completed), len(failed))
        flow_status = FlowStatus(status_str)

        # Run wall clock (FEAT-447 G2). The scheduler measures `run_started_at`
        # on the event loop's monotonic clock, so it must be read back from the
        # same clock -- mixing in time.time()/time.monotonic() would compare
        # unrelated epochs.
        total_time = 0.0
        if run_started_at is not None:
            try:
                total_time = max(0.0, asyncio.get_running_loop().time() - run_started_at)
            except RuntimeError:
                # Called outside a running loop (only reachable from a direct
                # synchronous call): the scheduler's epoch is unavailable, so
                # leave total_time at its default rather than invent a figure.
                self.logger.debug(
                    "No running loop while aggregating %r; total_time left at 0.0",
                    self.name,
                )

        # `mode` uses the flow's own internal vocabulary. Note this is a
        # DIFFERENT axis from AgentCrew's metadata['mode']
        # ('sequential'/'parallel'/'loop'), which describes an execution
        # strategy rather than how the graph was declared.
        if edges is not None:
            mode = "explicit"
        elif self._definition is not None:
            mode = "definition"
        else:
            mode = "legacy"

        metadata: dict[str, Any] = {
            "mode": mode,
            "node_count": len(nodes),
            "completed_count": len(completed),
            "failed_count": len(failed),
            "skipped": sorted(skipped) if skipped else [],
            "leaves": output_leaves,
        }

        return FlowResult(
            output=output,
            nodes=node_infos,
            responses=dict(results),
            errors={k: str(v) for k, v in errors.items()},
            status=flow_status,
            execution_log=execution_log,
            total_time=total_time,
            metadata=metadata,
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

        When checkpointing is enabled (``checkpoint=True``, or this instance
        was produced by ``resume()``), a ``FlowCheckpointer`` is attached for
        the duration of this call: its listener is registered, the resume
        lease is acquired (skipped if already held by ``resume()``), and
        ``checkpointer.aclose()`` always runs in a ``finally`` block —
        checkpoint write failures never fail or block this call (spec §7).

        Args:
            ctx: Optional pre-built ``FlowContext`` or a string prompt.
                If a string is provided, a FlowContext is created with
                ``initial_task`` set to that string.
                If ``None`` and this instance holds a resume-seeded context
                (from ``AgentsFlow.resume()``), that seeded context is used
                (consumed once). Otherwise a new FlowContext is created with
                an empty task.
            on_complete: Tuple of async callables invoked after the main loop.
                Each receives ``(ctx, result)``; exceptions are caught and logged
                but do NOT affect ``FlowResult.status``.

        Returns:
            Aggregated ``FlowResult`` describing the run.

        Raises:
            FlowNotExportableError: If ``checkpoint=True`` and this flow's
                graph cannot be exported (fail-fast, before any node runs).
            FlowLockedError: If checkpointing is enabled and another holder
                already holds the resume lease for this ``flow_id``.
        """
        # Accept a plain string as the initial task prompt.
        if isinstance(ctx, str):
            ctx = FlowContext(
                initial_task=ctx,
                agent_registry=self._agent_registry,
                synthesis_client=getattr(self, "_synthesis_client", None),
            )

        if ctx is None and self._resume_seed_context is not None:
            ctx = self._resume_seed_context
            self._resume_seed_context = None

        ctx = ctx or FlowContext(
            initial_task="",
            agent_registry=self._agent_registry,
            synthesis_client=getattr(self, "_synthesis_client", None),
        )

        self._active_ctx = ctx
        checkpointer, listener = await self._ensure_checkpointer(ctx)
        if checkpointer is not None:
            # Track this run so a graceful-shutdown hook (FlowRecoveryService,
            # FEAT-399 TASK-2054) can suspend it. A no-op when no service has
            # ever been requested (get_recovery_service() lazily creates the
            # process-wide default; registration itself has no side effects
            # beyond a dict entry until shutdown() is actually invoked).
            get_recovery_service().register(self)
        try:
            return await self._run_flow_scheduler(ctx, on_complete=on_complete)
        finally:
            self._active_ctx = None
            if checkpointer is not None:
                get_recovery_service().unregister(self)
                if listener is not None:
                    try:
                        self._node_event_listeners.remove(listener)
                    except ValueError:  # pragma: no cover - defensive
                        pass
                await checkpointer.aclose()
                if checkpointer is self._checkpointer:
                    self._checkpointer = None

    async def _ensure_checkpointer(
        self, ctx: "FlowContext"
    ) -> Tuple[Optional[FlowCheckpointer], Optional[Callable[[str, str, Dict[str, Any]], Any]]]:
        """Build (or reuse) this run's ``FlowCheckpointer`` and register its listener.

        If ``resume()`` already attached a checkpointer (with its lease
        already acquired there), it is reused as-is — the lease is never
        re-acquired here. Otherwise, when ``checkpoint=True``, a fresh
        checkpointer is built, the graph is validated exportable
        (``to_definition()``, fail-fast), and the resume lease is acquired.

        In required mode (``checkpoint_required=True``) the fire-and-forget
        listener is never attached — the scheduler's awaited barrier is the
        sole persistence mechanism (spec §7: "required persistence must not
        run through make_listener()"), so the returned ``listener`` is
        ``None`` in that case even though ``checkpointer`` is not.

        Args:
            ctx: The live ``FlowContext`` for this run — bound into the
                checkpointer's listener closure (skipped in required mode).

        Returns:
            ``(checkpointer, listener)``. ``listener`` is ``None`` in
            required mode or when checkpointing is disabled; ``checkpointer``
            is ``None`` only when checkpointing is disabled for this run.

        Raises:
            FlowNotExportableError: See ``to_definition()``.
            FlowLockedError: See ``FlowCheckpointer.acquire_lease()``.
        """
        if self._checkpointer is not None:
            # Already set up by resume() — lease already acquired there.
            checkpointer = self._checkpointer
            listener = None
            if not self._checkpoint_required:
                listener = checkpointer.make_listener(ctx)
                self.add_node_event_listener(listener)
            return checkpointer, listener

        if not self._checkpoint_enabled:
            return None, None

        # An externally-supplied definition (checkpoint_definition=...) takes
        # precedence and skips to_definition() entirely — explicit-edge
        # graphs built with callable predicates cannot round-trip through it
        # (spec §7 known risk). Only fall back to the fail-fast
        # to_definition() export when the caller did not supply one.
        definition = (
            self._checkpoint_definition_arg if self._checkpoint_definition_arg is not None else self.to_definition()
        )

        store = get_checkpoint_store(self._checkpoint_store_arg)
        durable_store: Optional[CheckpointStore] = None
        if self._checkpoint_durable or self._durable_store_arg is not None:
            durable_store = get_checkpoint_store(self._durable_store_arg)

        checkpointer = FlowCheckpointer(
            flow_id=self.flow_id,
            flow_name=self.name,
            definition=definition,
            store=store,
            durable_store=durable_store,
            include_responses=self._checkpoint_include_responses,
            durable=self._checkpoint_durable,
            history_limit=self._checkpoint_history,
            memory_refs=self._checkpoint_memory_refs,
            shared_data_projector=self._checkpoint_shared_data_arg,
            input_metadata=self._checkpoint_input_arg,
            starting_checkpoint_id=self._resume_starting_checkpoint_id,
        )

        holder = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        await checkpointer.acquire_lease(holder)

        self._checkpointer = checkpointer
        listener = None
        if not self._checkpoint_required:
            listener = checkpointer.make_listener(ctx)
            self.add_node_event_listener(listener)
        return checkpointer, listener

    async def suspend(self) -> FlowCheckpoint:
        """Suspend this flow: dump ephemeral history to durable storage.

        Copies the ephemeral store's retained checkpoint history to the
        durable store, then writes a final ``status="suspended"``
        checkpoint to both — usable mid-run (e.g. from a signal handler or
        the graceful-shutdown recovery service) as well as standalone.

        Returns:
            The final ``status="suspended"`` ``FlowCheckpoint``.

        Raises:
            ValueError: If this flow has no active checkpointer (checkpointing
                was never enabled for it) or no active run to snapshot.
        """
        if self._checkpointer is None:
            raise ValueError(
                f"AgentsFlow {self.name!r} has no active checkpointer; " "suspend() requires checkpoint=True."
            )
        if self._active_ctx is None:
            raise ValueError(
                f"AgentsFlow {self.name!r} has no active run to suspend "
                "(suspend() must be called while run_flow() is executing)."
            )
        return await self._checkpointer.dump(self._active_ctx)

    @classmethod
    async def resume(
        cls,
        flow_id: str,
        checkpoint_id: Optional[int] = None,
        *,
        agent_registry: AgentRegistry,
        store: Optional[Union[str, CheckpointStore]] = None,
        durable_store: Optional[Union[str, CheckpointStore]] = None,
        flow_factory: Optional[Callable[[FlowDefinition], "AgentsFlow"]] = None,
        seed_context: Optional[FlowContext] = None,
        expected_input: Optional[CheckpointInputMetadata] = None,
    ) -> "AgentsFlow":
        """Reconstruct and resume a checkpointed flow (spec §3 Module 7).

        Loads the checkpoint (durable store first, ephemeral fallback),
        acquires the resume lease fail-fast, rebuilds the flow via
        ``from_definition()`` (or ``flow_factory``, see below), and seeds a
        ``FlowContext`` from the checkpoint so completed nodes are never
        re-executed when the returned flow's ``run_flow()`` is called.

        Args:
            flow_id: The flow run's identifier (checkpoint key).
            checkpoint_id: Optional specific checkpoint to resume/re-fork
                from; defaults to the latest checkpoint for ``flow_id``.
            agent_registry: ``AgentRegistry`` used to re-resolve agent refs
                (required — same contract as ``from_definition()``).
            store: Ephemeral ``CheckpointStore`` name/instance/None (env
                fallback).
            durable_store: Durable ``CheckpointStore`` name/instance/None.
                Checked first when given; falls back to the ephemeral store.
            flow_factory: Optional ``(definition) -> AgentsFlow`` that rebuilds
                the graph instead of ``from_definition()``. **Required for any
                flow whose routing depends on more than the node topology**,
                for two reasons that compound:

                * ``from_definition()`` reconstructs a custom node type through
                  the generic fallback ``cls(node_id=…, dependencies=…,
                  successors=…)``. For a node whose fields all have defaults
                  that does not raise — it silently produces a node with every
                  live dependency (agents, repositories, clients) set to
                  ``None``. Passing ``node_factories`` would fix this half.
                * A flow rebuilt from a definition has ``self._definition`` set,
                  and ``run_flow()`` selects the explicit-edge scheduler with
                  ``self._definition is None and bool(self._edges)``. So a
                  resumed flow silently drops to AND-join semantics with no
                  back-edge detection and **no predicate evaluation at all**,
                  however the original was built. ``node_factories`` cannot fix
                  this half.

                Handing the caller its own builder back fixes both at once: it
                already has a function that produces the graph exactly as it
                was. ``None`` keeps the historical behaviour.
            seed_context: Optional caller-created live ``FlowContext`` (e.g.
                one already bound to a fresh ``SessionHost``, dispatcher, or
                trace context for this process). When given, resume seeds
                *this* context in place — via ``mark_completed()`` only, which
                never touches ``shared_data``/``agent_registry``/
                ``synthesis_client``/``trace_context`` — instead of building a
                brand-new internal ``FlowContext``. The caller's live objects
                are therefore never overwritten by checkpoint data. ``None``
                keeps the historical behaviour of seeding a fresh context.
            expected_input: Optional ``CheckpointInputMetadata`` the caller
                expects this checkpoint to carry (spec §2 step 2: "A
                checkpoint hit must match the expected fingerprint"). When
                given, resume raises ``CheckpointFingerprintMismatchError``
                if the loaded checkpoint's ``input_metadata`` is missing or
                does not equal ``expected_input`` — reusing a ``run_id``
                across an incompatible workflow, topology version, or input
                fingerprint must fail loudly instead of silently resuming
                the wrong run. Checked fail-fast, before the resume lease is
                acquired. ``None`` (default) skips this check entirely.

        Returns:
            A configured ``AgentsFlow`` instance ready for ``run_flow()``
            (with no arguments — the resume-seeded context is used
            automatically).

        Raises:
            CheckpointNotFoundError: If no matching checkpoint exists
                (missing or TTL-expired).
            FlowLockedError: If another holder already holds the resume
                lease for ``flow_id``.
            ValueError: If ``flow_factory`` returns a graph missing a node the
                checkpoint recorded as completed.
            CheckpointFingerprintMismatchError: If ``expected_input`` is given
                and does not match the loaded checkpoint's ``input_metadata``.
        """
        ephemeral_store = get_checkpoint_store(store)
        durable: Optional[CheckpointStore] = get_checkpoint_store(durable_store) if durable_store is not None else None

        checkpoint: Optional[FlowCheckpoint] = None
        if durable is not None:
            checkpoint = (
                await durable.get(flow_id, checkpoint_id)
                if checkpoint_id is not None
                else await durable.latest(flow_id)
            )
        if checkpoint is None:
            checkpoint = (
                await ephemeral_store.get(flow_id, checkpoint_id)
                if checkpoint_id is not None
                else await ephemeral_store.latest(flow_id)
            )
        if checkpoint is None:
            raise CheckpointNotFoundError(
                f"No checkpoint found for flow_id={flow_id!r}"
                + (f", checkpoint_id={checkpoint_id}" if checkpoint_id is not None else " (no latest checkpoint)")
            )

        if checkpoint.lossy:
            logger.warning(
                "AgentsFlow.resume(): checkpoint flow_id=%s checkpoint_id=%s "
                "is lossy — some dependency results may be degraded strings",
                flow_id,
                checkpoint.checkpoint_id,
            )

        # Fail fast, before acquiring the lease or rebuilding anything: a
        # run_id reused across an incompatible workflow/topology/input must
        # never silently resume the wrong run (spec §2 step 2).
        if expected_input is not None and checkpoint.input_metadata != expected_input:
            raise CheckpointFingerprintMismatchError(
                f"Cannot resume flow_id={flow_id!r}: checkpoint input_metadata "
                f"{checkpoint.input_metadata!r} does not match expected "
                f"{expected_input!r}."
            )

        serializer = FlowStateSerializer()

        # Acquire the resume lease fail-fast, before any reconstruction —
        # reused (never re-acquired) by run_flow()'s _ensure_checkpointer().
        checkpointer = FlowCheckpointer(
            flow_id=flow_id,
            flow_name=checkpoint.flow_name,
            definition=checkpoint.definition,
            store=ephemeral_store,
            durable_store=durable,
            serializer=serializer,
            memory_refs=checkpoint.memory_refs,
            starting_checkpoint_id=checkpoint.checkpoint_id,
        )
        holder = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        await checkpointer.acquire_lease(holder)

        if flow_factory is not None:
            flow = flow_factory(checkpoint.definition)
        else:
            flow = cls.from_definition(checkpoint.definition, agent_registry=agent_registry)

        # A factory is free to return any graph; if it returns one that does
        # not contain a node the checkpoint says finished, the seeding below
        # would mark a node that does not exist and the run would restart
        # from the wrong frontier — silently, and looking like a successful
        # resume. Both shapes count as "known": a programmatic flow holds its
        # nodes in ``_nodes``, while a definition-bound one materializes them
        # per run and knows them only through the definition.
        known_ids = set(flow._nodes)
        if flow._definition is not None:
            known_ids |= {node_def.id for node_def in (flow._definition.nodes or ())}
        missing = [node_id for node_id in checkpoint.context.completion_order if node_id not in known_ids]
        if missing:
            raise ValueError(
                f"Cannot resume flow_id={flow_id!r}: the rebuilt graph is "
                f"missing node(s) recorded as completed: {sorted(missing)}. "
                "The flow_factory must produce the same node ids as the "
                "checkpointed run."
            )

        flow.flow_id = flow_id
        flow._checkpoint_enabled = True
        flow._checkpointer = checkpointer
        flow._resume_starting_checkpoint_id = checkpoint.checkpoint_id
        flow._checkpoint_memory_refs = checkpoint.memory_refs

        decoded_results = {
            node_id: serializer.from_safe(value) for node_id, value in checkpoint.context.results.items()
        }
        decoded_responses = (
            {node_id: serializer.from_safe(value) for node_id, value in checkpoint.context.responses.items()}
            if checkpoint.context.responses is not None
            else {}
        )

        if seed_context is not None:
            # Seed the caller's own live context in place (spec §2 step 4):
            # mark_completed() only touches completed_tasks/completion_order/
            # active_tasks/results/responses/node_metadata — never
            # shared_data/agent_registry/synthesis_client/trace_context — so
            # whatever live objects the caller already wired onto this
            # context (a fresh SessionHost, dispatchers, toolkits, ...) are
            # never overwritten by checkpoint data.
            seed_ctx = seed_context
            for node_id in checkpoint.context.completion_order:
                seed_ctx.mark_completed(
                    node_id,
                    result=decoded_results.get(node_id),
                    response=decoded_responses.get(node_id),
                )
        else:
            # Historical behaviour: seed a fresh FlowContext from the
            # checkpoint. agent_registry/synthesis_client/trace_context are
            # re-bound here, not restored from the checkpoint (spec §7).
            seed_ctx = FlowContext(
                initial_task=checkpoint.context.initial_task,
                agent_registry=agent_registry,
            )
            seed_ctx.shared_data.update(checkpoint.context.shared_data)
            for node_id in checkpoint.context.completion_order:
                seed_ctx.mark_completed(
                    node_id,
                    result=decoded_results.get(node_id),
                    response=decoded_responses.get(node_id),
                )

        flow._resume_seed_context = seed_ctx
        return flow

    async def _run_flow_scheduler(
        self,
        ctx: FlowContext,
        *,
        on_complete: Tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...] = (),
    ) -> FlowResult:
        """Event-driven scheduler body (extracted from ``run_flow()``, FEAT-399).

        Unchanged scheduler logic — ``ctx`` is already fully resolved by
        ``run_flow()`` (string/None normalization, resume-seed consumption)
        before this is called; extracted only so ``run_flow()`` can wrap it
        in a checkpointer-lifecycle ``try/finally`` without reformatting the
        entire scheduler body.

        Args:
            ctx: The fully-resolved ``FlowContext`` for this run.
            on_complete: See ``run_flow()``.

        Returns:
            Aggregated ``FlowResult`` describing the run.
        """
        from .cel_evaluator import CELPredicateEvaluator  # noqa: PLC0415

        # Required checkpoint barrier (spec §3 Module 2). `self._checkpointer`
        # is set by `_ensure_checkpointer()` before this method runs whenever
        # checkpointing is enabled at all; `required` gates the awaited-write
        # barrier below on top of that (both must hold — checkpoint_required
        # alone, with checkpointing disabled, is a no-op).
        checkpointer = self._checkpointer
        required = bool(self._checkpoint_required and checkpointer is not None)

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
                        f"Edge {edge.from_!r} → {edge.to!r} references a " f"node not added to flow {self.name!r}"
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
        tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        # Resume (FEAT-399): seed from ctx.completed_tasks/.results when the
        # caller pre-populated a FlowContext (AgentsFlow.resume()) — a no-op
        # (identical to the prior `set()`/`{}`) for every ordinary run, where
        # these are empty. Completed nodes are never re-executed; anything
        # else (in-flight/failed/never-started) re-runs (at-least-once).
        completed: set[str] = set(ctx.completed_tasks)
        failed: set[str] = set()
        skipped: set[str] = set()
        results: dict[str, Any] = dict(ctx.results)
        errors: dict[str, BaseException] = {}
        active_count = 0
        loop = asyncio.get_running_loop()
        run_started_at = loop.time()
        started_at: dict[str, float] = {}
        durations: dict[str, float] = {}  # node_id → seconds (last attempt)

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
            #
            # ``on_condition`` edges are exempt (FEAT-377 TASK-1910), mirroring
            # FlowDefinition._validate_acyclic: a CEL/callable-gated back-edge
            # is a deliberate, bounded repair/retry loop (e.g. dev-loop's
            # ``qa -> development`` edge, gated by an attempt-count
            # predicate) that this explicit-edge executor's OR-join +
            # skip-propagation semantics support. A genuinely unconditional
            # cycle still raises — those edges have no predicate to bound
            # iteration.
            unique_sources = {
                nid: {e.from_ for e in in_edges if e.condition != "on_condition"} for nid, in_edges in incoming.items()
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
                cyclic = sorted(nid for nid, deg in in_degree.items() if deg > 0)
                raise ValueError(
                    f"Flow {self.name!r} contains a cycle: nodes {cyclic} "
                    "are never reachable from an entry node. Break the "
                    "cycle or use conditional edges with a terminal path."
                )

        # ── Cyclic back-edge support (FEAT-377 TASK-1910) ───────────────────
        #
        # A bounded repair/retry loop (e.g. dev-loop's `qa -> development`
        # edge, CEL/callable-gated on an attempt counter) is a genuine graph
        # cycle that `_validate_acyclic`-style checks above now tolerate for
        # `on_condition` edges. But tolerating the cycle structurally is not
        # enough for EXECUTION: the plain OR-join gate ("dispatch once every
        # incoming edge is resolved") would deadlock forever on a node's
        # first-ever dispatch, since the back-edge's source cannot resolve
        # until the very node it points at has already run at least once.
        #
        # Two additions close that gap:
        #   1. `_forward_in_edges[tgt]` — `incoming[tgt]` minus any edge that
        #      is part of a cycle — gates a node's FIRST dispatch. Back-edges
        #      never block a node from running the first time.
        #   2. `_resolve_retries()` — after a back-edge SOURCE completes and
        #      its predicate fires, reset every node on the cycle (target
        #      through source, inclusive) and re-dispatch the target. This is
        #      the mechanism that actually re-enters the loop.
        _back_edges: List[Tuple[Any, Set[str]]] = []
        _back_edge_ids: Set[int] = set()
        if explicit_mode:
            full_adj: Dict[str, List[str]] = defaultdict(list)
            for edge in edges:
                for tgt in ([edge.to] if isinstance(edge.to, str) else list(edge.to)):
                    full_adj[edge.from_].append(tgt)
            reverse_adj: Dict[str, List[str]] = defaultdict(list)
            for src, tgts in full_adj.items():
                for tgt in tgts:
                    reverse_adj[tgt].append(src)

            def _reachable(start: str, adj: Dict[str, List[str]]) -> Set[str]:
                seen = {start}
                stack = [start]
                while stack:
                    cur = stack.pop()
                    for nxt in adj.get(cur, ()):
                        if nxt not in seen:
                            seen.add(nxt)
                            stack.append(nxt)
                return seen

            # Which `on_condition` edges are genuine cyclic *back*-edges (as
            # opposed to a forward/tree edge that merely happens to sit on
            # the same undirected cycle as one) is a graph-theoretic
            # question, not a "does a cycle exist through here" one —
            # `edge.from_ in _reachable(tgt, full_adj)` (cycle MEMBERSHIP)
            # was the original TASK-1910 test, and it is too coarse once a
            # cycle has more than one `on_condition` edge on it (FEAT-377/A:
            # dev-loop feature-mode's `feedback_router -> development` retry
            # edge closes a cycle that ALSO contains the pre-existing
            # `qa -> feedback_router` forward-routing edge — both satisfy
            # "cycle membership", but only the former is meant to trigger a
            # retry-reset; misclassifying the latter turned every ordinary
            # QA failure into a spurious repair-loop reset, live-locking the
            # run). The correct test is the classic DFS white/gray/black
            # back-edge definition: edge u->v is a back-edge iff v is still
            # on the active DFS stack (a true ancestor of u) when the edge
            # is explored — a tree/forward/cross edge to an already-visited
            # node never re-triggers `_dfs` and is never gray at that point.
            _WHITE, _GRAY, _BLACK = 0, 1, 2
            _color: Dict[str, int] = dict.fromkeys(nodes, _WHITE)
            _dfs_back_edges: List[Any] = []
            _edges_by_source: Dict[str, List[Any]] = defaultdict(list)
            for edge in edges:
                _edges_by_source[edge.from_].append(edge)

            def _dfs(start: str) -> None:
                # Iterative DFS (explicit stack of (node, out-edge index)
                # frames) — recursion would also work for dev-loop-sized
                # graphs, but an explicit stack avoids any dependency on
                # graph size staying well under the interpreter's recursion
                # limit for arbitrary `AgentsFlow` callers.
                call_stack: List[Tuple[str, int]] = [(start, 0)]
                _color[start] = _GRAY
                while call_stack:
                    u, i = call_stack[-1]
                    out_edges = _edges_by_source.get(u, ())
                    if i >= len(out_edges):
                        _color[u] = _BLACK
                        call_stack.pop()
                        continue
                    call_stack[-1] = (u, i + 1)
                    edge = out_edges[i]
                    for v in ([edge.to] if isinstance(edge.to, str) else list(edge.to)):
                        if v not in _color:
                            continue  # defensive: edge to an unknown node id
                        if _color[v] == _WHITE:
                            _color[v] = _GRAY
                            call_stack.append((v, 0))
                        elif _color[v] == _GRAY and edge.condition == "on_condition":
                            _dfs_back_edges.append(edge)

            for nid in nodes:
                if _color[nid] == _WHITE:
                    _dfs(nid)

            for edge in _dfs_back_edges:
                for tgt in ([edge.to] if isinstance(edge.to, str) else list(edge.to)):
                    forward_from_tgt = _reachable(tgt, full_adj)
                    backward_to_src = _reachable(edge.from_, reverse_adj)
                    cycle_members = forward_from_tgt & backward_to_src
                    _back_edges.append((edge, cycle_members))
                    _back_edge_ids.add(id(edge))

        _forward_in_edges: Dict[str, List[Any]] = {
            nid: [e for e in in_edges if id(e) not in _back_edge_ids] for nid, in_edges in incoming.items()
        }

        def _deps_for(node_id: str) -> DependencyResults:
            """Build dependency result dict for a node."""
            if explicit_mode:
                dep_ids: Set[str] = {e.from_ for e in incoming[node_id]}
                dep_ids |= set(nodes[node_id].dependencies)
            else:
                dep_ids = set(nodes[node_id].dependencies)
            return {dep: str(results[dep]) for dep in dep_ids if dep in results}

        def _spawn(node_id: str) -> None:
            nonlocal active_count
            node = nodes[node_id]
            deps = _deps_for(node_id)
            started_at[node_id] = loop.time()
            tasks[node_id] = asyncio.create_task(self._run_node(node, ctx, deps, completion_queue))
            active_count += 1
            self.logger.info("Dispatched node %r", node_id)
            self._notify_node_event(
                "node_started",
                node_id,
                {"flow": self.name, "context": ctx},
            )

        async def _await_required_barrier() -> None:
            """Await the required checkpoint write; fail the job on failure.

            Called only in required mode (``required`` closed over above),
            only after a node's successful ``ctx.mark_completed()`` and any
            retry-reset has already been applied to both scheduler state and
            ``ctx`` — and always BEFORE any new node this event makes
            eligible is spawned (spec §2 Overview, §7). On
            ``CheckpointPersistenceError`` (including a lost resume lease),
            already-active sibling tasks are cancelled/awaited before the
            error propagates — no new work is dispatched once a required
            barrier fails.
            """
            assert checkpointer is not None  # `required` (closed over) implies this
            try:
                checkpointer.raise_if_lease_lost()
                await checkpointer.checkpoint(ctx)
            except CheckpointPersistenceError:
                active = [t for t in tasks.values() if not t.done()]
                for t in active:
                    t.cancel()
                if active:
                    await asyncio.gather(*active, return_exceptions=True)
                raise

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
                            edge.from_,
                            edge.to,
                            exc,
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

        def _resolve_ready_targets() -> List[str]:
            """Compute (and skip-resolve) every node whose incoming edges are
            all resolved — without dispatching the ones ready to run.

            Runs to a fixpoint so a skip cascades through its descendants in
            the same pass (e.g. a failed node skips its whole success path,
            which in turn resolves a downstream error-handler's fan-in).
            Skips are applied immediately (they need no checkpoint — spec §7:
            only a successful node is ever checkpointed as complete); nodes
            ready to dispatch are only collected and returned so the caller
            can await the required checkpoint barrier (spec §2/§7) exactly
            once per completion event, over every target this pass makes
            eligible, before spawning any of them. In non-required mode the
            caller spawns the returned list immediately with no intervening
            ``await`` — behavior is unchanged from the previous
            spawn-inline implementation (no yield point exists between the
            fixpoint computing this list and every entry being dispatched).

            Gates on ``_forward_in_edges`` (FEAT-377 TASK-1910) rather than
            the raw ``incoming`` index: a cyclic back-edge must never block a
            node's first-ever dispatch (its source cannot resolve until the
            node it points at has already run once) — re-entry after a
            back-edge fires is handled separately by ``_resolve_retries()``.

            Returns:
                node_ids ready to dispatch this pass (not yet spawned).
            """
            to_spawn: List[str] = []
            progress = True
            while progress:
                progress = False
                for tgt, in_edges in _forward_in_edges.items():
                    if not in_edges:
                        continue  # entry node — dispatched at start
                    if tgt in completed or tgt in failed or tgt in skipped or tgt in tasks or tgt in to_spawn:
                        continue
                    if not all(_edge_resolved(e) for e in in_edges):
                        continue
                    if any(_edge_fired(e) for e in in_edges):
                        to_spawn.append(tgt)
                    else:
                        skipped.add(tgt)
                        try:
                            # idle → blocked: the FSM's terminal marker for
                            # "never ran" — post-run inspection can tell a
                            # skipped node (blocked) from a pending one (idle).
                            nodes[tgt].fsm.block()
                        except Exception:  # noqa: BLE001 - telemetry only
                            pass
                        self.logger.info("Node %r skipped (no incoming edge fired)", tgt)
                        self._notify_node_event(
                            "node_skipped",
                            tgt,
                            {"flow": self.name, "context": ctx},
                        )
                    progress = True
            return to_spawn

        def _resolve_retries() -> Optional[str]:
            """Re-enter a bounded repair loop when a back-edge fires.

            When a cyclic back-edge's source has resolved and its predicate
            passes, every node on the cycle (target through source,
            inclusive) is reset to "never ran" in BOTH scheduler-local state
            AND ``ctx`` (``FlowContext.reset_completed()`` — spec §2/§7: the
            persisted frontier must request the next repair attempt instead
            of restoring stale completions) — but the target is NOT spawned
            here. Only meaningful once the target has already completed at
            least once — the loop's first pass is a normal forward dispatch,
            never a retry.

            Returns:
                The node_id to (re-)dispatch if a retry was triggered — the
                caller awaits the required checkpoint barrier (spec §2/§7)
                before spawning it and skips the normal OR-join pass for
                this event, since the reset invalidates the state it would
                otherwise act on. ``None`` if no back-edge fired.
            """
            for edge, members in _back_edges:
                src = edge.from_
                tgt = edge.to if isinstance(edge.to, str) else None
                if tgt is None or tgt not in completed:
                    continue
                if src not in completed and src not in failed:
                    continue
                if not _edge_fired(edge):
                    continue
                for member in members:
                    completed.discard(member)
                    failed.discard(member)
                    skipped.discard(member)
                    results.pop(member, None)
                    errors.pop(member, None)
                    tasks.pop(member, None)
                    old_node = nodes[member]
                    try:
                        nodes[member] = old_node.model_copy(update={"fsm": AgentTaskMachine(agent_name=member)})
                    except Exception:  # noqa: BLE001 - fallback: keep old node
                        pass
                ctx.reset_completed(members)
                self.logger.info(
                    "Repair-loop retry: edge %r -> %r fired; reset %s and " "re-dispatched %r",
                    src,
                    tgt,
                    sorted(members),
                    tgt,
                )
                return tgt
            return None

        # Run-level bracket: flow_started precedes every node_started.
        self._notify_node_event(
            "flow_started",
            "",
            {"flow": self.name, "context": ctx, "node_count": len(nodes)},
        )

        # Initial dispatch — entry nodes. Gated on `_forward_in_edges`
        # (FEAT-377 TASK-1910) so a node whose ONLY incoming edges are
        # cyclic back-edges still counts as an entry node. Entry nodes
        # already in `completed` (resume, FEAT-399) are skipped — never
        # re-executed.
        if explicit_mode:
            for nid in nodes:
                if nid in completed:
                    continue
                if not _forward_in_edges[nid]:
                    _spawn(nid)
        else:
            for nid, node in nodes.items():
                if nid in completed:
                    continue
                if not node.dependencies:
                    _spawn(nid)

        # Resume (FEAT-399): dispatch any node whose dependencies are
        # already satisfied by the pre-seeded `completed` set, reaching the
        # true execution frontier without waiting for a live completion
        # event. `_resolve_ready_targets()` already handles this correctly
        # for explicit/add_edge mode (OR-join + skip-propagation, generic
        # fixpoint); definition-driven/legacy mode has no equivalent
        # pre-loop entry point, so a small AND-join fixpoint is added here.
        # A no-op whenever `completed` is empty (every non-resume run).
        if completed:
            if explicit_mode:
                # No barrier here even in required mode: nothing "completed"
                # in THIS process yet — every id in the pre-seeded
                # `completed` set was already checkpointed by the prior
                # process before this resume (that is the whole point of
                # resuming). The barrier only guards NEW completions below.
                for tgt in _resolve_ready_targets():
                    _spawn(tgt)
            else:
                progress = True
                while progress:
                    progress = False
                    for nid, node in nodes.items():
                        if nid in completed or nid in failed or nid in skipped or nid in tasks:
                            continue
                        deps = node.dependencies
                        if deps and all(d in completed for d in deps):
                            _spawn(nid)
                            progress = True

        # Main event loop — drain completion events.
        while active_count > 0 or not completion_queue.empty():
            event: CompletionEvent = await completion_queue.get()
            active_count -= 1
            nid = event.node_id
            durations[nid] = loop.time() - started_at.get(nid, run_started_at)
            self.logger.debug("Received completion event for node %r", nid)
            # Required checkpoint barrier gates only the SUCCESS path (spec
            # §7: "Failed or cancelled nodes are never checkpointed as
            # complete") — captured before either branch runs below.
            node_succeeded = event.error is None

            if event.error is not None:
                # Retry if max_retries > 0 and attempts not exhausted.
                max_r = getattr(nodes[nid], "max_retries", 0)
                if attempts[nid] < max_r:
                    attempts[nid] += 1
                    self.logger.info(
                        "Retrying node %r (attempt %d/%d)",
                        nid,
                        attempts[nid],
                        max_r,
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
                    # FEAT-447: `metadata=` (an existing parameter) fills
                    # ctx.node_metadata, so a context inspected after the run
                    # -- including a checkpointed/resumed one -- carries the
                    # same fidelity as the FlowResult.
                    ctx.mark_failed(
                        nid,
                        event.error,
                        metadata=build_node_metadata(
                            node_id=nid,
                            agent=getattr(nodes[nid], "agent", None),
                            response=None,
                            output=None,
                            execution_time=durations[nid],
                            status="failed",
                            error=str(event.error),
                        ),
                    )
                self.logger.warning("Node %r failed: %s", nid, event.error)
                self._notify_node_event(
                    "node_failed",
                    nid,
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
                # FEAT-447: `response=` carries the raw envelope verbatim (NOT
                # pre-unwrapped -- consumers read scalars through
                # FlowResult.node_results / ctx-level readers), and `metadata=`
                # fills ctx.node_metadata. Both parameters already existed;
                # AgentsFlow simply never passed them. The NodeExecutionInfo is
                # deliberately built here as well as in _aggregate_result --
                # the two paths stay independent rather than one consuming the
                # other's state.
                ctx.mark_completed(
                    nid,
                    result=event.result,
                    response=event.result,
                    metadata=build_node_metadata(
                        node_id=nid,
                        agent=getattr(nodes[nid], "agent", None),
                        response=event.result,
                        output=event.result,
                        execution_time=durations[nid],
                        status="completed",
                        error=None,
                    ),
                )
                self.logger.info("Node %r completed", nid)
                self._notify_node_event(
                    "node_completed",
                    nid,
                    {
                        "flow": self.name,
                        "context": ctx,
                        "duration_ms": durations[nid] * 1000.0,
                        "node_result": _serialise_result_value(event.result),
                    },
                )

            if explicit_mode:
                # A cyclic back-edge firing takes precedence over the normal
                # OR-join pass for this event (FEAT-377 TASK-1910): the reset
                # it performs invalidates the very state the OR-join pass
                # would otherwise read.
                retry_target: Optional[str] = None
                if _back_edges:
                    retry_target = _resolve_retries()
                if retry_target is not None:
                    # Required barrier (spec §2/§7): the reset above has
                    # already been applied to both scheduler state and ctx
                    # (via ctx.reset_completed()) — checkpoint that
                    # post-reset frontier before re-dispatching the target,
                    # so a crash here restores the invalidated cycle instead
                    # of the stale completions it replaced.
                    if required and node_succeeded:
                        await _await_required_barrier()
                    _spawn(retry_target)
                    continue
                # OR-join + skip-propagation over the whole graph.
                to_spawn = _resolve_ready_targets()
                # Required barrier (spec §2/§7): await it once per completion
                # event — even when `to_spawn` is empty, this node's own
                # success must still be durably persisted — before spawning
                # anything this event made eligible.
                if required and node_succeeded:
                    await _await_required_barrier()
                for tgt in to_spawn:
                    _spawn(tgt)
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
            nodes,
            results,
            errors,
            completed,
            failed,
            edges=edges if explicit_mode else None,
            durations=durations,
            # FEAT-447: hand the aggregator what the scheduler already
            # measured -- true completion order, the run clock, and the
            # skipped set -- instead of discarding it.
            ctx=ctx,
            run_started_at=run_started_at,
            skipped=skipped,
        )
        self._notify_node_event(
            "flow_completed",
            "",
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

        # Let the async node-event listeners finish before handing the result
        # back — the caller's own terminal bookkeeping is built from them.
        await self._drain_event_tasks()

        return aggregated


# ─── New Node subclasses (TASK-1066) ─────────────────────────────────────────


@register_node("decision", config_model=DecisionConfigDef)
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
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

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


@register_node("interactive_decision", config_model=InteractiveDecisionConfigDef)
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
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

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


@register_node("synthesis", config_model=SynthesisConfigDef)
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
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

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
