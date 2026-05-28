"""FlowLoader — Load, save, and materialize FlowDefinition instances.

Handles persistence (file I/O, Redis) and materialization (JSON → runnable
AgentsFlow). Combines FlowDefinition, CELPredicateEvaluator, ACTION_REGISTRY,
and AgentsFlow into a cohesive API.

Example::

    >>> definition = FlowLoader.load_from_file("my_flow.json")
    >>> flow = FlowLoader.to_agents_flow(definition, extra_agents={"worker": my_agent})
    >>> result = await flow.run_flow("Hello")
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from navconfig.logging import logging

from .actions import create_action
from .cel_evaluator import CELPredicateEvaluator
from .definition import EdgeDefinition, FlowDefinition, NodeDefinition
# FEAT-163 TASK-1069: retargeted from legacy .fsm (deleted) to new package locations.
# NOTE: AgentsFlow is imported lazily inside to_agents_flow() to avoid circular import:
#   parrot.bots.flows.flow → parrot.bots.flow.definition → parrot.bots.flow (init)
#   → parrot.bots.flow.loader → parrot.bots.flows.flow  (circular)
from parrot.bots.flows.core.fsm import TransitionCondition


REDIS_KEY_PREFIX = "parrot:flow:"

logger = logging.getLogger("parrot.flow.loader")


class FlowLoader:
    """Load, save, and materialize FlowDefinition instances."""

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FlowDefinition:
        """Parse a dict into a validated FlowDefinition."""
        return FlowDefinition.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> FlowDefinition:
        """Parse a JSON string into a validated FlowDefinition."""
        return cls.from_dict(json.loads(json_str))

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    @classmethod
    def load_from_file(cls, path: Union[str, Path]) -> FlowDefinition:
        """Load from file path or AGENTS_DIR/flows/{name}.json."""
        path = Path(path)

        if not path.is_absolute() and not path.exists():
            from parrot.conf import AGENTS_DIR
            path = AGENTS_DIR / "flows" / path
            if not path.suffix:
                path = path.with_suffix(".json")

        if not path.exists():
            raise FileNotFoundError(f"Flow file not found: {path}")

        return cls.from_json(path.read_text(encoding="utf-8"))

    @classmethod
    def save_to_file(
        cls,
        definition: FlowDefinition,
        path: Union[str, Path],
        *,
        indent: int = 2,
        update_timestamp: bool = True,
    ) -> None:
        """Persist FlowDefinition as JSON with optional timestamp update."""
        if update_timestamp:
            definition.updated_at = datetime.now(timezone.utc)

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        json_str = definition.model_dump_json(by_alias=True, indent=indent)
        path.write_text(json_str, encoding="utf-8")
        logger.info("Saved flow '%s' to %s", definition.flow, path)

    # ------------------------------------------------------------------
    # Redis I/O
    # ------------------------------------------------------------------

    @classmethod
    async def load_from_redis(
        cls,
        redis: Any,
        flow_name: str,
    ) -> FlowDefinition:
        """Load a FlowDefinition from Redis.

        Args:
            redis: An async Redis client (redis.asyncio.Redis).
            flow_name: Name of the flow (used as key suffix).

        Raises:
            KeyError: If flow not found in Redis.
        """
        key = f"{REDIS_KEY_PREFIX}{flow_name}"
        data = await redis.get(key)
        if data is None:
            raise KeyError(f"Flow '{flow_name}' not found in Redis (key: {key})")
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return cls.from_json(data)

    @classmethod
    async def save_to_redis(
        cls,
        redis: Any,
        definition: FlowDefinition,
        *,
        ttl: Optional[int] = None,
        update_timestamp: bool = True,
    ) -> None:
        """Save a FlowDefinition to Redis.

        Args:
            redis: An async Redis client (redis.asyncio.Redis).
            definition: The flow definition to persist.
            ttl: Optional time-to-live in seconds.
            update_timestamp: Whether to set updated_at to now.
        """
        if update_timestamp:
            definition.updated_at = datetime.now(timezone.utc)

        key = f"{REDIS_KEY_PREFIX}{definition.flow}"
        json_str = definition.model_dump_json(by_alias=True)

        if ttl is not None:
            await redis.setex(key, ttl, json_str)
        else:
            await redis.set(key, json_str)
        logger.info("Saved flow '%s' to Redis (key: %s)", definition.flow, key)

    @classmethod
    async def list_flows_in_redis(cls, redis: Any) -> List[str]:
        """List all flow names stored in Redis.

        Scans for keys matching the ``parrot:flow:*`` pattern and returns
        the flow names (key suffix after the prefix).
        """
        prefix = REDIS_KEY_PREFIX
        flow_names: List[str] = []
        async for key in redis.scan_iter(match=f"{prefix}*"):
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            flow_names.append(key[len(prefix):])
        return sorted(flow_names)

    @classmethod
    async def delete_from_redis(cls, redis: Any, flow_name: str) -> None:
        """Delete a flow from Redis."""
        key = f"{REDIS_KEY_PREFIX}{flow_name}"
        await redis.delete(key)
        logger.info("Deleted flow '%s' from Redis (key: %s)", flow_name, key)

    # ------------------------------------------------------------------
    # Materialization: FlowDefinition → AgentsFlow
    # ------------------------------------------------------------------

    @classmethod
    def to_agents_flow(
        cls,
        definition: FlowDefinition,
        agent_registry: Optional[Any] = None,
        extra_agents: Optional[Dict[str, Any]] = None,
    ) -> "AgentsFlow":
        """Materialize a FlowDefinition into a runnable AgentsFlow.

        Migrated from legacy API (FEAT-196 TASK-1314) to use the new
        ``AgentsFlow.add_node()`` API and ``parrot.bots.flows.core`` node
        primitives (``StartNode``, ``EndNode``, ``AgentNode``).

        Args:
            definition: Parsed flow definition.
            agent_registry: Optional registry mapping names → agent instances.
                Supports dict-like access (``registry[name]`` or
                ``registry.get(name)``).
            extra_agents: Dict of name → agent instance overrides.
                Takes priority over agent_registry.

        Returns:
            A fully wired AgentsFlow ready for ``run_flow()``.

        Raises:
            LookupError: If an agent_ref cannot be resolved.
            ValueError: If an invalid CEL predicate is provided.
        """
        # Lazy import to avoid circular:
        #   loader → flows.flow → loader
        from parrot.bots.flows.flow.flow import AgentsFlow  # noqa: PLC0415
        from parrot.bots.flows.core.node import AgentNode, StartNode, EndNode  # noqa: PLC0415

        extra_agents = extra_agents or {}

        # Phase 1: Pre-compute dependencies and successors for each node_id
        # from the declared edges, so nodes can be constructed with correct wiring.
        deps_map: Dict[str, set] = {nd.id: set() for nd in definition.nodes}
        succs_map: Dict[str, set] = {nd.id: set() for nd in definition.nodes}
        for edge_def in definition.edges:
            targets = (
                list(edge_def.to)
                if isinstance(edge_def.to, list)
                else [edge_def.to]
            )
            src = edge_def.from_
            for tgt in targets:
                succs_map[src].add(tgt)
                if tgt in deps_map:
                    deps_map[tgt].add(src)

        # Validate all CEL predicates before building nodes (fail-fast).
        for edge_def in definition.edges:
            if (
                edge_def.condition == "on_condition"
                and edge_def.predicate
            ):
                # CELPredicateEvaluator raises ValueError on bad expressions.
                CELPredicateEvaluator(edge_def.predicate)

        # Phase 2: Build and add each node in programmatic mode.
        # NOTE: flow is created without definition= so _materialize_nodes uses
        # the programmatic fresh-copy path (preserving pre/post actions).
        # Routing is based on node.successors (set from edges above), which
        # works for simple always/on_success/on_error edges.  CEL predicate
        # evaluation in programmatic mode is not supported; predicates are
        # validated at construction time (above) but not enforced at routing.
        flow = AgentsFlow(name=definition.flow)

        for node_def in definition.nodes:
            node_type = node_def.type
            nid = node_def.id
            deps = deps_map.get(nid, set())
            succs = succs_map.get(nid, set())

            if node_type == "start":
                flow_node: Any = StartNode(
                    node_id=nid,
                    dependencies=deps,
                    successors=succs,
                    metadata=node_def.metadata or {},
                )
            elif node_type == "end":
                flow_node = EndNode(
                    node_id=nid,
                    dependencies=deps,
                    successors=succs,
                    metadata=node_def.metadata or {},
                )
            elif node_type in ("agent", "human", "decision"):
                agent = cls._resolve_agent(
                    node_def.agent_ref, extra_agents, agent_registry
                )
                flow_node = AgentNode(
                    agent=agent,
                    node_id=nid,
                    dependencies=deps,
                    successors=succs,
                )
            elif node_type == "interactive_decision":
                from .flow import InteractiveDecisionNode  # noqa: PLC0415

                config = node_def.config or {}
                question = config.get("question", node_def.label or nid)
                options = config.get("options", [])
                flow_node = InteractiveDecisionNode(
                    node_id=nid,
                    question=question,
                    options=options,
                    dependencies=deps,
                    successors=succs,
                )
            else:
                raise ValueError(f"Unknown node type: {node_type!r}")

            # Attach pre/post actions to the node before adding to flow.
            for action_def in node_def.pre_actions:
                action = create_action(action_def)
                flow_node.add_pre_action(action)
            for action_def in node_def.post_actions:
                action = create_action(action_def)
                flow_node.add_post_action(action)

            flow.add_node(flow_node)

        return flow

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_agent(
        agent_ref: Optional[str],
        extra_agents: Dict[str, Any],
        agent_registry: Optional[Any],
    ) -> Any:
        """Resolve an agent_ref to an agent instance.

        Resolution order: extra_agents → agent_registry.

        Raises:
            LookupError: If the agent cannot be found.
        """
        if not agent_ref:
            raise LookupError("Node requires 'agent_ref' but none was provided.")

        # 1. extra_agents takes priority
        if agent_ref in extra_agents:
            return extra_agents[agent_ref]

        # 2. Try agent_registry (dict-like or object with .get())
        if agent_registry is not None:
            if isinstance(agent_registry, dict):
                agent = agent_registry.get(agent_ref)
            elif hasattr(agent_registry, "get"):
                agent = agent_registry.get(agent_ref)
            else:
                agent = None
            if agent is not None:
                return agent

        raise LookupError(
            f"Agent '{agent_ref}' not found in extra_agents or agent_registry."
        )
