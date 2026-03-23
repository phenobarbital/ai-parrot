"""
A2A Proxy Router - Routes requests to remote A2A agents without LLM processing.

This module provides a gateway/proxy for routing requests to multiple A2A agents
based on configurable rules. Unlike LLM-based orchestration, routing decisions
are made using deterministic rules (skill matching, tag matching, regex patterns)
resulting in minimal latency and zero LLM costs.

Key Features:
    - Rule-based routing (skill, tag, regex, round-robin)
    - Load balancing across equivalent agents
    - Request/response transformation hooks
    - Aggregated AgentCard exposing all downstream skills
    - Full A2A protocol compliance (can be consumed as an A2A agent itself)

Example:
    # Create router with mesh discovery
    mesh = A2AMeshDiscovery()
    await mesh.register("http://sales-bot:8080")
    await mesh.register("http://support-bot:8080")
    await mesh.start()

    router = A2AProxyRouter(mesh, name="APIGateway")

    # Configure routing rules
    router.route_by_skill("sales_query", "SalesBot")
    router.route_by_skill("support_ticket", "SupportBot")
    router.route_by_regex(r"precio|price|costo", "SalesBot")
    router.set_default("SupportBot")

    # Use programmatically
    task = await router.route_message("What's the price of product X?")

    # Or expose as HTTP service
    app = web.Application()
    router.setup(app)
    # Now accessible at /.well-known/agent.json as a unified gateway
"""
from __future__ import annotations
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)
import contextlib
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from aiohttp import web
from navconfig.logging import logging
from .client import A2AClient
from .mesh import A2AMeshDiscovery, RegisteredAgent
from .models import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    Task,
    TaskState,
)


# Type aliases
TransformFunc = Callable[[str, Dict[str, Any]], Coroutine[Any, Any, str]]
ResponseTransformFunc = Callable[[Task, Dict[str, Any]], Coroutine[Any, Any, Task]]


class RoutingStrategy(str, Enum):
    """Strategy for selecting target agent."""

    SKILL_MATCH = "skill"        # Match by skill ID
    SKILL_NAME = "skill_name"    # Match by skill name (partial)
    TAG_MATCH = "tag"            # Match by agent/skill tag
    REGEX = "regex"              # Match by regex pattern in message
    ROUND_ROBIN = "round_robin"  # Distribute across agents
    RANDOM = "random"            # Random selection
    PRIORITY = "priority"        # Highest priority agent
    FIRST_AVAILABLE = "first"    # First healthy agent
    WEIGHTED = "weighted"        # Weighted random selection
    CUSTOM = "custom"            # Custom routing function


class LoadBalanceStrategy(str, Enum):
    """Strategy for load balancing across multiple target agents."""

    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_RECENT = "least_recent"  # Agent used least recently
    PRIORITY = "priority"           # Highest priority first
    FIRST_HEALTHY = "first_healthy"


@dataclass
class RoutingRule:
    """
    Defines a routing rule for matching requests to agents.

    Attributes:
        pattern: Pattern to match (skill_id, tag, regex, or "*" for default)
        strategy: How to match the pattern against requests
        target_agents: List of agent names that can handle matching requests
        priority: Rule priority (higher = evaluated first)
        load_balance: Strategy for selecting among multiple targets
        weights: Optional weights for weighted load balancing
        transform_request: Optional async function to transform request before sending
        transform_response: Optional async function to transform response before returning
        enabled: Whether this rule is active
        metadata: Additional metadata for the rule
    """
    pattern: str
    strategy: RoutingStrategy
    target_agents: List[str] = field(default_factory=list)
    priority: int = 0
    load_balance: LoadBalanceStrategy = LoadBalanceStrategy.FIRST_HEALTHY
    weights: Optional[Dict[str, float]] = None
    transform_request: Optional[TransformFunc] = None
    transform_response: Optional[ResponseTransformFunc] = None
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Runtime state
    _compiled_regex: Optional[re.Pattern] = field(default=None, repr=False)
    _round_robin_counter: int = field(default=0, repr=False)
    _last_used: Dict[str, datetime] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        """Compile regex pattern if strategy is REGEX."""
        if self.strategy == RoutingStrategy.REGEX:
            try:
                self._compiled_regex = re.compile(self.pattern, re.IGNORECASE)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex pattern '{self.pattern}': {e}"
                ) from e


@dataclass
class RoutingResult:
    """Result of a routing decision."""
    matched: bool
    rule: Optional[RoutingRule] = None
    target_agent: Optional[RegisteredAgent] = None
    match_details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProxyStats:
    """Statistics for the proxy router."""
    requests_total: int = 0
    requests_routed: int = 0
    requests_failed: int = 0
    requests_no_match: int = 0
    total_latency_ms: float = 0.0
    agents_used: Dict[str, int] = field(default_factory=dict)
    rules_matched: Dict[str, int] = field(default_factory=dict)
    last_request_time: Optional[datetime] = None

    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds."""
        if self.requests_routed == 0:
            return 0.0
        return self.total_latency_ms / self.requests_routed

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "requests_total": self.requests_total,
            "requests_routed": self.requests_routed,
            "requests_failed": self.requests_failed,
            "requests_no_match": self.requests_no_match,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "agents_used": dict(self.agents_used),
            "rules_matched": dict(self.rules_matched),
            "last_request_time": self.last_request_time.isoformat() if self.last_request_time else None,  # noqa
        }


class A2AProxyRouter:
    """
    Proxy/Gateway for routing requests to A2A agents without LLM processing.

    This router receives requests and forwards them to appropriate downstream
    agents based on configurable routing rules. No LLM is involved in the
    routing decision - it's pure rule-based matching.

    The router can also expose itself as an A2A-compliant server, presenting
    an aggregated view of all downstream agents' capabilities.

    Use Cases:
        - API Gateway: Single entry point for multiple specialized agents
        - Load Balancer: Distribute requests across equivalent agents
        - Router: Direct requests based on content/intent
        - Facade: Hide internal agent topology from clients

    Example:
        # Setup
        mesh = A2AMeshDiscovery()
        await mesh.register("http://agent1:8080")
        await mesh.register("http://agent2:8080")

        router = A2AProxyRouter(mesh, name="Gateway")

        # Add routing rules
        router.route_by_skill("data_analysis", "DataAnalyst")
        router.route_by_tag("customer", "SupportBot")
        router.route_by_regex(r"urgent|emergency", "PriorityHandler")
        router.set_default("GeneralAssistant")

        # Route a message (no LLM involved!)
        task = await router.route_message("Analyze this data...")
        print(task.artifacts[0].parts[0].text)

        # Expose as A2A server
        app = web.Application()
        router.setup(app)
    """

    def __init__(
        self,
        mesh: A2AMeshDiscovery,
        *,
        name: str = "A2ARouter",
        description: str = "A2A Proxy Router",
        version: str = "1.0.0",
        aggregate_skills: bool = True,
        skill_prefix_with_agent: bool = True,
        default_timeout: float = 60.0,
        base_path: str = "/a2a",
        tags: Optional[List[str]] = None,
        capabilities: Optional[AgentCapabilities] = None,
    ):
        """
        Initialize the A2A Proxy Router.

        Args:
            mesh: A2AMeshDiscovery instance for agent lookup
            name: Name for this router (used in AgentCard)
            description: Description for this router
            version: Version string
            aggregate_skills: If True, aggregate skills from all downstream agents
            skill_prefix_with_agent: If True, prefix aggregated skills with agent name
            default_timeout: Default timeout for proxied requests
            base_path: URL prefix for A2A endpoints when exposed as server
            tags: Tags for the router's AgentCard
            capabilities: Capabilities to advertise
        """
        self.mesh = mesh
        self.name = name
        self.description = description
        self.version = version
        self.aggregate_skills = aggregate_skills
        self.skill_prefix_with_agent = skill_prefix_with_agent
        self.default_timeout = default_timeout
        self.base_path = base_path.rstrip("/")
        self.tags = tags or ["gateway", "router", "proxy"]
        self.capabilities = capabilities or AgentCapabilities(streaming=True)

        # Routing rules
        self._rules: List[RoutingRule] = []
        self._default_agent: Optional[str] = None

        # Runtime state
        self._stats = ProxyStats()
        self._app: Optional[web.Application] = None
        self._agent_card_cache: Optional[AgentCard] = None
        self._agent_card_cache_time: Optional[datetime] = None
        self._cache_ttl_seconds: float = 60.0  # Refresh aggregated card every 60s

        # Active client connections (reused for performance)
        self._client_cache: Dict[str, A2AClient] = {}

        self.logger = logging.getLogger(f"A2A.Router.{name}")

    # ─────────────────────────────────────────────────────────────────────────
    # Rule Configuration
    # ─────────────────────────────────────────────────────────────────────────

    def add_route(
        self,
        pattern: str,
        target: Union[str, List[str]],
        *,
        strategy: RoutingStrategy = RoutingStrategy.SKILL_MATCH,
        priority: int = 0,
        load_balance: LoadBalanceStrategy = LoadBalanceStrategy.FIRST_HEALTHY,
        weights: Optional[Dict[str, float]] = None,
        transform_request: Optional[TransformFunc] = None,
        transform_response: Optional[ResponseTransformFunc] = None,
        enabled: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "A2AProxyRouter":
        """
        Add a routing rule.

        Args:
            pattern: Pattern to match (interpretation depends on strategy)
            target: Agent name or list of agent names
            strategy: How to match the pattern
            priority: Rule priority (higher = evaluated first)
            load_balance: How to select among multiple targets
            weights: Weights for weighted load balancing
            transform_request: Async function to transform request
            transform_response: Async function to transform response
            enabled: Whether rule is active
            metadata: Additional metadata

        Returns:
            Self for method chaining

        Example:
            router.add_route(
                "data_analysis",
                ["Analyst1", "Analyst2"],
                strategy=RoutingStrategy.SKILL_MATCH,
                load_balance=LoadBalanceStrategy.ROUND_ROBIN,
                priority=10
            )
        """
        targets = [target] if isinstance(target, str) else list(target)

        rule = RoutingRule(
            pattern=pattern,
            strategy=strategy,
            target_agents=targets,
            priority=priority,
            load_balance=load_balance,
            weights=weights,
            transform_request=transform_request,
            transform_response=transform_response,
            enabled=enabled,
            metadata=metadata or {},
        )

        self._rules.append(rule)
        self._sort_rules()

        self.logger.debug(
            f"Added route: {strategy.value}:{pattern} -> {targets}"
        )

        return self

    def route_by_skill(
        self,
        skill_id: str,
        target: Union[str, List[str]],
        **kwargs
    ) -> "A2AProxyRouter":
        """
        Add routing rule that matches by skill ID.

        Args:
            skill_id: Skill ID to match
            target: Target agent(s)
            **kwargs: Additional RoutingRule parameters

        Returns:
            Self for method chaining
        """
        return self.add_route(
            skill_id,
            target,
            strategy=RoutingStrategy.SKILL_MATCH,
            **kwargs
        )

    def route_by_skill_name(
        self,
        skill_name: str,
        target: Union[str, List[str]],
        **kwargs
    ) -> "A2AProxyRouter":
        """
        Add routing rule that matches by skill name (partial match).

        Args:
            skill_name: Skill name pattern to match
            target: Target agent(s)
            **kwargs: Additional RoutingRule parameters

        Returns:
            Self for method chaining
        """
        return self.add_route(
            skill_name,
            target,
            strategy=RoutingStrategy.SKILL_NAME,
            **kwargs
        )

    def route_by_tag(
        self,
        tag: str,
        target: Union[str, List[str]],
        **kwargs
    ) -> "A2AProxyRouter":
        """
        Add routing rule that matches by tag.

        Args:
            tag: Tag to match
            target: Target agent(s)
            **kwargs: Additional RoutingRule parameters

        Returns:
            Self for method chaining
        """
        return self.add_route(
            tag,
            target,
            strategy=RoutingStrategy.TAG_MATCH,
            **kwargs
        )

    def route_by_regex(
        self,
        pattern: str,
        target: Union[str, List[str]],
        **kwargs
    ) -> "A2AProxyRouter":
        """
        Add routing rule that matches by regex pattern in the message.

        Args:
            pattern: Regex pattern to match against message content
            target: Target agent(s)
            **kwargs: Additional RoutingRule parameters

        Returns:
            Self for method chaining

        Example:
            router.route_by_regex(
                r"urgent|emergency|critical",
                "PriorityHandler",
                priority=100  # High priority
            )
        """
        return self.add_route(
            pattern,
            target,
            strategy=RoutingStrategy.REGEX,
            **kwargs
        )

    def route_round_robin(
        self,
        agents: List[str],
        **kwargs
    ) -> "A2AProxyRouter":
        """
        Add round-robin routing across multiple agents.

        All requests matching this rule will be distributed evenly
        across the specified agents.

        Args:
            agents: List of agent names to rotate through
            **kwargs: Additional RoutingRule parameters

        Returns:
            Self for method chaining
        """
        return self.add_route(
            "*",  # Match all
            agents,
            strategy=RoutingStrategy.ROUND_ROBIN,
            load_balance=LoadBalanceStrategy.ROUND_ROBIN,
            **kwargs
        )

    def set_default(self, agent_name: str) -> "A2AProxyRouter":
        """
        Set the default agent for requests that don't match any rule.

        Args:
            agent_name: Name of the default agent

        Returns:
            Self for method chaining
        """
        self._default_agent = agent_name
        self.logger.debug(f"Set default agent: {agent_name}")
        return self

    def remove_route(self, pattern: str, strategy: Optional[RoutingStrategy] = None) -> bool:
        """
        Remove a routing rule.

        Args:
            pattern: Pattern of the rule to remove
            strategy: If provided, only remove rule with matching strategy

        Returns:
            True if rule was removed, False if not found
        """
        for i, rule in enumerate(self._rules):
            if rule.pattern == pattern:
                if strategy is None or rule.strategy == strategy:
                    del self._rules[i]
                    self.logger.debug(f"Removed route: {pattern}")
                    return True
        return False

    def clear_routes(self) -> "A2AProxyRouter":
        """
        Clear all routing rules.

        Returns:
            Self for method chaining
        """
        self._rules.clear()
        self._default_agent = None
        self.logger.debug("Cleared all routes")
        return self

    def list_routes(self) -> List[Dict[str, Any]]:
        """
        List all configured routing rules.

        Returns:
            List of rule configurations
        """
        return [
            {
                "pattern": rule.pattern,
                "strategy": rule.strategy.value,
                "targets": rule.target_agents,
                "priority": rule.priority,
                "load_balance": rule.load_balance.value,
                "enabled": rule.enabled,
            }
            for rule in self._rules
        ]

    def _sort_rules(self) -> None:
        """Sort rules by priority (highest first)."""
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Routing Logic
    # ─────────────────────────────────────────────────────────────────────────

    def _match_rule(
        self,
        rule: RoutingRule,
        message: str,
        skill_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """
        Check if a rule matches the given request.

        Args:
            rule: Rule to evaluate
            message: Message content
            skill_id: Optional skill ID from request
            tags: Optional tags from request

        Returns:
            True if rule matches
        """
        if not rule.enabled:
            return False

        strategy = rule.strategy
        pattern_lower = rule.pattern.lower()

        if strategy == RoutingStrategy.SKILL_MATCH:
            # Exact skill ID match
            return skill_id is not None and skill_id.lower() == pattern_lower

        elif strategy == RoutingStrategy.SKILL_NAME:
            # Partial skill name match
            if skill_id and pattern_lower in skill_id.lower():
                return True
            # Also check message content for skill-like requests
            return pattern_lower in message.lower()

        elif strategy == RoutingStrategy.TAG_MATCH:
            # Match against provided tags
            if tags:
                return any(t.lower() == pattern_lower for t in tags)
            return False

        elif strategy == RoutingStrategy.REGEX:
            # Regex match against message
            if rule._compiled_regex:
                return bool(rule._compiled_regex.search(message))
            return False

        elif strategy in (
            RoutingStrategy.ROUND_ROBIN, RoutingStrategy.RANDOM, RoutingStrategy.FIRST_AVAILABLE
        ):
            # These always match (used for catch-all or default routing)
            return rule.pattern == "*"

        return False

    def _select_target(
        self,
        rule: RoutingRule,
    ) -> Optional[RegisteredAgent]:
        """
        Select a target agent from a rule's target list.

        Applies load balancing strategy to select among multiple targets.

        Args:
            rule: Routing rule with target agents

        Returns:
            Selected RegisteredAgent or None if no healthy target
        """
        if not rule.target_agents:
            return None

        # Get healthy agents from mesh
        healthy_targets: List[Tuple[str, RegisteredAgent]] = []
        for name in rule.target_agents:
            if agent := self.mesh.get(name):
                if agent.healthy:
                    healthy_targets.append((name, agent))

        if not healthy_targets:
            self.logger.warning(
                f"No healthy targets for rule {rule.pattern}: {rule.target_agents}"
            )
            return None

        # Apply load balancing strategy
        strategy = rule.load_balance

        if strategy == LoadBalanceStrategy.FIRST_HEALTHY:
            return healthy_targets[0][1]

        elif strategy == LoadBalanceStrategy.ROUND_ROBIN:
            idx = rule._round_robin_counter % len(healthy_targets)
            rule._round_robin_counter += 1
            return healthy_targets[idx][1]

        elif strategy == LoadBalanceStrategy.RANDOM:
            import random
            return random.choice(healthy_targets)[1]

        elif strategy == LoadBalanceStrategy.LEAST_RECENT:
            # Select agent used least recently
            def last_used_time(item: Tuple[str, RegisteredAgent]) -> datetime:
                return rule._last_used.get(
                    item[0],
                    datetime.min.replace(tzinfo=timezone.utc)
                )
            sorted_targets = sorted(healthy_targets, key=last_used_time)
            selected = sorted_targets[0]
            rule._last_used[selected[0]] = datetime.now(timezone.utc)
            return selected[1]

        elif strategy == LoadBalanceStrategy.PRIORITY:
            # Select highest priority agent
            def get_priority(item: Tuple[str, RegisteredAgent]) -> int:
                endpoint = self.mesh.get_endpoint(item[1].url)
                return endpoint.priority if endpoint else 0
            sorted_targets = sorted(healthy_targets, key=get_priority, reverse=True)
            return sorted_targets[0][1]

        # Default: first healthy
        return healthy_targets[0][1]

    def find_target(
        self,
        message: str,
        *,
        skill_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> RoutingResult:
        """
        Find the target agent for a request.

        Evaluates all rules in priority order and returns the first match.

        Args:
            message: Message content
            skill_id: Optional skill ID
            tags: Optional tags

        Returns:
            RoutingResult with matched rule and target agent
        """
        # Try each rule in priority order
        for rule in self._rules:
            if self._match_rule(rule, message, skill_id, tags):
                if target := self._select_target(rule):
                    return RoutingResult(
                        matched=True,
                        rule=rule,
                        target_agent=target,
                        match_details={
                            "pattern": rule.pattern,
                            "strategy": rule.strategy.value,
                        }
                    )

        # Try default agent
        if self._default_agent:
            if agent := self.mesh.get(self._default_agent):
                if agent.healthy:
                    return RoutingResult(
                        matched=True,
                        rule=None,
                        target_agent=agent,
                        match_details={"default": True}
                    )

        # No match found
        return RoutingResult(matched=False)

    # ─────────────────────────────────────────────────────────────────────────
    # Proxy Execution (No LLM!)
    # ─────────────────────────────────────────────────────────────────────────

    async def route_message(
        self,
        message: str,
        *,
        skill_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Task:
        """
        Route a message to the appropriate agent and return the response.

        This is a PASSTHROUGH operation - no LLM is involved.
        The message is forwarded as-is to the matched agent.

        Args:
            message: Message content to route
            skill_id: Optional skill ID to help with routing
            tags: Optional tags to help with routing
            context_id: Optional context ID for conversations
            metadata: Optional metadata
            timeout: Optional timeout override

        Returns:
            Task with the response from the downstream agent

        Raises:
            ValueError: If no target agent found
            ConnectionError: If target agent is unreachable
        """
        start_time = time.monotonic()
        self._stats.requests_total += 1
        self._stats.last_request_time = datetime.now(timezone.utc)

        # Find target
        result = self.find_target(message, skill_id=skill_id, tags=tags)

        if not result.matched or not result.target_agent:
            self._stats.requests_no_match += 1
            raise ValueError("No target agent found for request")

        agent = result.target_agent
        rule = result.rule

        self.logger.debug(
            f"Routing to {agent.card.name}: {result.match_details}"
        )

        try:
            # Apply request transformation if configured
            transformed_message = message
            if rule and rule.transform_request:
                transformed_message = await rule.transform_request(
                    message,
                    {"skill_id": skill_id, "tags": tags, "metadata": metadata}
                )

            # Get or create client
            client = await self._get_client(agent)

            # Send message (PASSTHROUGH - no LLM!)
            task = await client.send_message(
                transformed_message,
                context_id=context_id,
                metadata=metadata,
            )

            # Apply response transformation if configured
            if rule and rule.transform_response:
                task = await rule.transform_response(
                    task,
                    {"agent": agent.card.name, "rule": rule.pattern}
                )

            # Update stats
            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._stats.requests_routed += 1
            self._stats.total_latency_ms += elapsed_ms
            self._stats.agents_used[agent.card.name] = \
                self._stats.agents_used.get(agent.card.name, 0) + 1

            if rule:
                self._stats.rules_matched[rule.pattern] = \
                    self._stats.rules_matched.get(rule.pattern, 0) + 1

            return task

        except Exception as e:
            self._stats.requests_failed += 1
            self.logger.error(f"Routing failed to {agent.card.name}: {e}")
            raise

    async def route_message_stream(
        self,
        message: str,
        *,
        skill_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """
        Route a message and stream the response.

        Args:
            message: Message to route
            skill_id: Optional skill ID
            tags: Optional tags
            context_id: Optional context ID
            metadata: Optional metadata

        Yields:
            Text chunks as they arrive from the downstream agent
        """
        result = self.find_target(message, skill_id=skill_id, tags=tags)

        if not result.matched or not result.target_agent:
            raise ValueError("No target agent found for request")

        agent = result.target_agent
        rule = result.rule

        # Apply request transformation
        transformed_message = message
        if rule and rule.transform_request:
            transformed_message = await rule.transform_request(
                message,
                {"skill_id": skill_id, "tags": tags}
            )

        # Get client and stream
        client = await self._get_client(agent)

        async for chunk in client.stream_message(
            transformed_message,
            context_id=context_id,
            metadata=metadata,
        ):
            yield chunk

    async def invoke_skill(
        self,
        skill_id: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        agent_name: Optional[str] = None,
        context_id: Optional[str] = None,
    ) -> Any:
        """
        Invoke a specific skill on a remote agent.

        If agent_name is not provided, finds an agent with the skill.

        Args:
            skill_id: ID of the skill to invoke
            params: Parameters for the skill
            agent_name: Optional specific agent to use
            context_id: Optional context ID

        Returns:
            Skill result from the downstream agent

        Raises:
            ValueError: If no agent found with the skill
        """
        self._stats.requests_total += 1

        # Find agent with skill
        if agent_name:
            agent = self.mesh.get(agent_name)
            if not agent or not agent.healthy:
                raise ValueError(f"Agent {agent_name} not available")
        else:
            # Search for agent with this skill
            agents = self.mesh.get_by_skill(skill_id)
            if not agents:
                raise ValueError(f"No agent found with skill: {skill_id}")
            agent = agents[0]

        try:
            client = await self._get_client(agent)
            result = await client.invoke_skill(skill_id, params, context_id=context_id)

            self._stats.requests_routed += 1
            self._stats.agents_used[agent.card.name] = \
                self._stats.agents_used.get(agent.card.name, 0) + 1

            return result

        except Exception as e:
            self._stats.requests_failed += 1
            raise

    async def _get_client(self, agent: RegisteredAgent) -> A2AClient:
        """
        Get or create a client for an agent.

        Clients are cached and reused for performance.

        Args:
            agent: Target agent

        Returns:
            Connected A2AClient
        """
        if agent.url in self._client_cache:
            client = self._client_cache[agent.url]
            if client.is_connected:
                return client

        # Get endpoint config for auth details
        endpoint = self.mesh.get_endpoint(agent.url)

        client = A2AClient(
            agent.url,
            auth_token=endpoint.auth_token if endpoint else None,
            api_key=endpoint.api_key if endpoint else None,
            headers=endpoint.headers if endpoint else None,
            timeout=endpoint.timeout if endpoint else self.default_timeout,
        )

        await client.connect()
        self._client_cache[agent.url] = client

        return client

    async def close_clients(self) -> None:
        """Close all cached client connections."""
        for client in self._client_cache.values():
            with contextlib.suppress(Exception):
                await client.disconnect()
        self._client_cache.clear()

    # ─────────────────────────────────────────────────────────────────────────
    # Convenience Methods
    # ─────────────────────────────────────────────────────────────────────────

    async def ask(
        self,
        message: str,
        *,
        agent: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Shortcut: send message and get response as string.

        Args:
            message: Message to send
            agent: Optional specific agent to use
            **kwargs: Additional arguments for route_message

        Returns:
            Response text
        """
        if agent:
            # Direct to specific agent
            target = self.mesh.get(agent)
            if not target:
                raise ValueError(f"Agent {agent} not found")

            client = await self._get_client(target)
            task = await client.send_message(message, **kwargs)
        else:
            # Route based on rules
            task = await self.route_message(message, **kwargs)

        if task.status.state == TaskState.FAILED:
            error = task.status.message.get_text() if task.status.message else "Unknown error"
            raise RuntimeError(f"Agent error: {error}")

        if task.artifacts and task.artifacts[0].parts:
            return task.artifacts[0].parts[0].text or ""

        return ""

    async def fan_out(
        self,
        message: str,
        agents: List[str],
        *,
        timeout: float = 60.0,
        **kwargs
    ) -> Dict[str, Union[str, Exception]]:
        """
        Send message to multiple agents in parallel.

        Args:
            message: Message to send
            agents: List of agent names
            timeout: Timeout for each request
            **kwargs: Additional arguments

        Returns:
            Dict mapping agent name to response or exception
        """
        async def call_agent(name: str) -> Tuple[str, Union[str, Exception]]:
            try:
                result = await self.ask(message, agent=name, timeout=timeout, **kwargs)
                return name, result
            except Exception as e:
                return name, e

        results = await asyncio.gather(
            *[call_agent(name) for name in agents],
            return_exceptions=False
        )

        return dict(results)

    async def pipeline(
        self,
        message: str,
        agents: List[str],
        **kwargs
    ) -> str:
        """
        Execute a sequential pipeline of agents.

        Each agent's output becomes the next agent's input.

        Args:
            message: Initial message
            agents: Ordered list of agent names
            **kwargs: Additional arguments

        Returns:
            Final output from the last agent
        """
        current_input = message

        for name in agents:
            current_input = await self.ask(current_input, agent=name, **kwargs)

        return current_input

    # ─────────────────────────────────────────────────────────────────────────
    # A2A Server Exposure
    # ─────────────────────────────────────────────────────────────────────────

    def get_agent_card(self, force_refresh: bool = False) -> AgentCard:
        """
        Get the AgentCard for this router.

        When aggregate_skills is True, the card includes skills from all
        downstream agents, making this router appear as a single agent
        with all capabilities.

        Args:
            force_refresh: Force refresh of cached card

        Returns:
            AgentCard representing this router
        """
        now = datetime.now(timezone.utc)

        # Check cache
        if (not force_refresh and self._agent_card_cache and self._agent_card_cache_time and (now - self._agent_card_cache_time).total_seconds() < self._cache_ttl_seconds):  # noqa
            return self._agent_card_cache

        # Build skills list
        skills: List[AgentSkill] = []
        all_tags: Set[str] = set(self.tags)

        if self.aggregate_skills:
            for agent in self.mesh.list_healthy():
                for skill in agent.card.skills:
                    # Create aggregated skill
                    if self.skill_prefix_with_agent:
                        skill_id = f"{agent.card.name.lower().replace(' ', '_')}:{skill.id}"
                        skill_name = f"[{agent.card.name}] {skill.name}"
                    else:
                        skill_id = skill.id
                        skill_name = skill.name

                    aggregated = AgentSkill(
                        id=skill_id,
                        name=skill_name,
                        description=skill.description,
                        tags=skill.tags + [agent.card.name.lower()],
                        input_schema=skill.input_schema,
                        examples=skill.examples,
                    )
                    skills.append(aggregated)
                    all_tags.update(skill.tags)

        # Add a generic "route" skill
        skills.append(AgentSkill(
            id="route",
            name="Route Message",
            description="Route a message to the appropriate downstream agent",
            tags=["routing", "gateway"],
        ))

        card = AgentCard(
            name=self.name,
            description=self.description,
            version=self.version,
            url=None,  # Set when mounted
            skills=skills,
            capabilities=self.capabilities,
            tags=list(all_tags),
        )

        # Cache
        self._agent_card_cache = card
        self._agent_card_cache_time = now

        return card

    def setup(
        self,
        app: web.Application,
        base_path: Optional[str] = None,
    ) -> None:
        """
        Mount the router as an A2A server on an aiohttp application.

        This allows external services to discover and use this router
        as if it were a regular A2A agent.

        Args:
            app: aiohttp Application
            base_path: Optional path prefix override
        """
        path = base_path or self.base_path

        # Discovery endpoint
        app.router.add_get(
            "/.well-known/agent.json",
            self._handle_discovery
        )

        # A2A message endpoints
        app.router.add_post(
            f"{path}/message/send",
            self._handle_message
        )
        app.router.add_post(
            f"{path}/message/stream",
            self._handle_stream
        )

        # Stats endpoint
        app.router.add_get(
            f"{path}/stats",
            self._handle_stats
        )

        # Routes endpoint
        app.router.add_get(
            f"{path}/routes",
            self._handle_routes
        )

        # Cleanup on shutdown
        app.on_cleanup.append(self._cleanup)

        self._app = app
        self.logger.info(f"A2A Router mounted at {path}")

    async def _cleanup(self, app: web.Application) -> None:
        """Cleanup handler for aiohttp app shutdown."""
        await self.close_clients()

    async def _handle_discovery(self, request: web.Request) -> web.Response:
        """Handler for /.well-known/agent.json"""
        card = self.get_agent_card()

        # Set URL from request
        host = request.host
        scheme = request.scheme
        card.url = f"{scheme}://{host}"

        return web.json_response(card.to_dict())

    async def _handle_message(self, request: web.Request) -> web.Response:
        """Handler for POST /a2a/message/send"""
        try:
            data = await request.json()

            # Extract message
            message_data = data.get("message", {})
            if isinstance(message_data, dict):
                parts = message_data.get("parts", [])
                content = " ".join(
                    p.get("text", "") for p in parts if p.get("type") == "text"
                )
            else:
                content = str(message_data)

            skill_id = data.get("skillId")
            context_id = message_data.get("contextId") if isinstance(message_data, dict) else None

            # Route and proxy
            task = await self.route_message(
                content,
                skill_id=skill_id,
                context_id=context_id,
            )

            return web.json_response(task.to_dict())

        except json.JSONDecodeError:
            return web.json_response(
                {"error": {"code": "InvalidJSON", "message": "Invalid JSON body"}},
                status=400
            )
        except ValueError as e:
            return web.json_response(
                {"error": {"code": "NoRoute", "message": str(e)}},
                status=404
            )
        except Exception as e:
            self.logger.error(f"Error handling message: {e}", exc_info=True)
            return web.json_response(
                {"error": {"code": "InternalError", "message": str(e)}},
                status=500
            )

    async def _handle_stream(self, request: web.Request) -> web.StreamResponse:
        """Handler for POST /a2a/message/stream"""
        try:
            data = await request.json()

            message_data = data.get("message", {})
            if isinstance(message_data, dict):
                parts = message_data.get("parts", [])
                content = " ".join(
                    p.get("text", "") for p in parts if p.get("type") == "text"
                )
            else:
                content = str(message_data)

            # Prepare streaming response
            response = web.StreamResponse()
            response.headers["Content-Type"] = "text/event-stream"
            response.headers["Cache-Control"] = "no-cache"
            response.headers["Connection"] = "keep-alive"
            await response.prepare(request)

            try:
                async for chunk in self.route_message_stream(
                    content,
                    skill_id=data.get("skillId"),
                ):
                    event_data = {
                        "artifactUpdate": {
                            "artifact": {
                                "parts": [{"type": "text", "text": chunk}]
                            }
                        }
                    }
                    await response.write(
                        f"data: {json.dumps(event_data)}\n\n".encode()
                    )

                # Send completion
                completion = {
                    "statusUpdate": {
                        "final": True,
                        "status": {"state": "completed"}
                    }
                }
                await response.write(
                    f"data: {json.dumps(completion)}\n\n".encode()
                )

            except Exception as e:
                error_event = {
                    "statusUpdate": {
                        "final": True,
                        "status": {
                            "state": "failed",
                            "message": {"parts": [{"type": "text", "text": str(e)}]}
                        }
                    }
                }
                await response.write(
                    f"data: {json.dumps(error_event)}\n\n".encode()
                )

            return response

        except Exception as e:
            self.logger.error(f"Error in stream handler: {e}")
            return web.json_response(
                {"error": {"code": "InternalError", "message": str(e)}},
                status=500
            )

    async def _handle_stats(self, request: web.Request) -> web.Response:
        """Handler for GET /a2a/stats"""
        return web.json_response(self._stats.to_dict())

    async def _handle_routes(self, request: web.Request) -> web.Response:
        """Handler for GET /a2a/routes"""
        return web.json_response({
            "routes": self.list_routes(),
            "default_agent": self._default_agent,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Properties and Info
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> ProxyStats:
        """Get current statistics."""
        return self._stats

    def get_info(self) -> Dict[str, Any]:
        """Get detailed information about the router state."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "rules_count": len(self._rules),
            "default_agent": self._default_agent,
            "mesh_agents": len(self.mesh),
            "mesh_healthy": len(self.mesh.list_healthy()),
            "cached_clients": len(self._client_cache),
            "stats": self._stats.to_dict(),
        }

    def __repr__(self) -> str:
        return (
            f"A2AProxyRouter("
            f"name={self.name!r}, "
            f"rules={len(self._rules)}, "
            f"mesh_agents={len(self.mesh)})"
        )
