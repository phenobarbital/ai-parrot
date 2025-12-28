"""
A2A Mesh Discovery - Centralized service for discovering remote A2A agents.

This module provides a centralized discovery service for remote A2A agents,
similar to how MCPServerConfig lists available MCP servers. It enables:
- Registration of remote A2A agents by URL
- Health checking with configurable intervals
- Agent lookup by name, skill, or tag
- Configuration from YAML files with environment variable substitution
- Event callbacks for agent status changes

Example:
    # Standalone usage
    mesh = A2AMeshDiscovery()
    await mesh.start()
    await mesh.register("http://agent1:8080")
    await mesh.register("http://agent2:8080")

    # Query agents
    agent = mesh.get("CustomerSupport")
    analysts = mesh.get_by_skill("data_analysis")

    # From YAML config
    mesh = A2AMeshDiscovery.from_config("a2a_agents.yaml")
    await mesh.start()
"""
from __future__ import annotations
import contextlib
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Set,
    Union,
)
import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import aiohttp
import yaml
from navconfig.logging import logging
from .client import A2AClient
from .models import RegisteredAgent


# Type alias for event callbacks
AgentEventCallback = Callable[["RegisteredAgent", str], Coroutine[Any, Any, None]]


class AgentStatus(str, Enum):
    """Status of an agent in the mesh."""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNREACHABLE = "unreachable"


class HealthCheckStrategy(str, Enum):
    """Strategy for health checking agents."""
    DISCOVERY = "discovery"      # Fetch /.well-known/agent.json
    PING = "ping"                # Simple HTTP GET to base URL
    CUSTOM = "custom"            # Custom health check endpoint


@dataclass
class A2AEndpoint:
    """
    Configuration for an A2A endpoint before discovery.

    Represents a known endpoint that can be registered with the mesh.
    The actual AgentCard is fetched during discovery.

    Attributes:
        url: Base URL of the A2A agent
        name: Optional name hint (actual name comes from AgentCard)
        auth_token: Bearer token for authentication
        api_key: API key for X-API-Key header
        headers: Additional HTTP headers
        tags: Local tags for categorization (merged with agent's tags)
        timeout: Request timeout for this endpoint
        health_check_strategy: How to check health for this endpoint
        health_check_endpoint: Custom health check endpoint (if strategy is CUSTOM)
        enabled: Whether this endpoint is enabled
        priority: Priority for load balancing (higher = preferred)
        metadata: Additional metadata
    """
    url: str
    name: Optional[str] = None
    auth_token: Optional[str] = None
    api_key: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    tags: Set[str] = field(default_factory=set)
    timeout: float = 30.0
    health_check_strategy: HealthCheckStrategy = HealthCheckStrategy.DISCOVERY
    health_check_endpoint: Optional[str] = None
    enabled: bool = True
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Normalize URL and convert tags to set."""
        self.url = self.url.rstrip("/")
        if isinstance(self.tags, list):
            self.tags = set(self.tags)


@dataclass
class DiscoveryStats:
    """Statistics about mesh discovery operations."""
    total_registered: int = 0
    total_healthy: int = 0
    total_unhealthy: int = 0
    last_health_check: Optional[datetime] = None
    health_checks_performed: int = 0
    discovery_errors: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "total_registered": self.total_registered,
            "total_healthy": self.total_healthy,
            "total_unhealthy": self.total_unhealthy,
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "health_checks_performed": self.health_checks_performed,
            "discovery_errors": self.discovery_errors,
        }


class A2AMeshDiscovery:
    """
    Centralized discovery service for remote A2A agents.

    Provides a registry of remote A2A agents with automatic health checking,
    multiple lookup methods, and event notifications.

    Features:
        - Register agents by URL with automatic card discovery
        - Periodic health checks with configurable intervals
        - Lookup by name, skill ID, skill name, or tag
        - Full-text search across agent metadata
        - Event callbacks for status changes
        - YAML configuration with environment variable substitution
        - Statistics and monitoring

    Example:
        # Basic usage
        mesh = A2AMeshDiscovery(health_check_interval=60.0)
        await mesh.start()

        agent_card = await mesh.register("http://my-agent:8080")
        print(f"Registered: {agent_card.name}")

        # Query by skill
        analysts = mesh.get_by_skill("data_analysis")
        for agent in analysts:
            print(f"  - {agent.card.name} at {agent.url}")

        await mesh.stop()

        # From config file
        mesh = A2AMeshDiscovery.from_config("config/a2a_agents.yaml")
        await mesh.start()  # Discovers all configured endpoints
    """

    # Pattern for environment variable substitution: ${VAR_NAME}
    ENV_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')

    def __init__(
        self,
        health_check_interval: float = 30.0,
        health_check_timeout: float = 10.0,
        auto_discover_on_start: bool = True,
        max_concurrent_health_checks: int = 10,
        retry_unhealthy_interval: float = 60.0,
        remove_after_failures: int = 0,  # 0 = never remove
    ):
        """
        Initialize the mesh discovery service.

        Args:
            health_check_interval: Seconds between health checks for healthy agents
            health_check_timeout: Timeout for health check requests
            auto_discover_on_start: If True, discover all endpoints on start()
            max_concurrent_health_checks: Max concurrent health check requests
            retry_unhealthy_interval: Seconds between retries for unhealthy agents
            remove_after_failures: Remove agent after N consecutive failures (0 = never)
        """
        self._health_check_interval = health_check_interval
        self._health_check_timeout = health_check_timeout
        self._auto_discover_on_start = auto_discover_on_start
        self._max_concurrent_health_checks = max_concurrent_health_checks
        self._retry_unhealthy_interval = retry_unhealthy_interval
        self._remove_after_failures = remove_after_failures

        # Storage
        self._endpoints: Dict[str, A2AEndpoint] = {}      # url -> endpoint config
        self._discovered: Dict[str, RegisteredAgent] = {}  # name -> discovered agent
        self._url_to_name: Dict[str, str] = {}             # url -> agent name (reverse lookup)
        self._failure_counts: Dict[str, int] = {}          # name -> consecutive failures

        # Runtime state
        self._health_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._stats = DiscoveryStats()
        self._semaphore: Optional[asyncio.Semaphore] = None

        # Event callbacks
        self._on_agent_healthy: List[AgentEventCallback] = []
        self._on_agent_unhealthy: List[AgentEventCallback] = []
        self._on_agent_registered: List[AgentEventCallback] = []
        self._on_agent_removed: List[AgentEventCallback] = []

        self.logger = logging.getLogger("Parrot.A2AMesh")

    # ─────────────────────────────────────────────────────────────────────────
    # Factory methods
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        config_path: Union[str, Path],
        **kwargs
    ) -> "A2AMeshDiscovery":
        """
        Create mesh from YAML configuration file.

        The YAML file supports environment variable substitution using ${VAR_NAME}.

        Example YAML:
            settings:
              health_check_interval: 30
              health_check_timeout: 10
              auto_discover_on_start: true

            agents:
              - url: http://sales-agent:8080
                tags: [sales, revenue]

              - url: http://support-agent:8080
                auth_token: ${SUPPORT_AGENT_TOKEN}
                tags: [support, customer]

              - url: https://external-agent.example.com
                api_key: ${EXTERNAL_API_KEY}
                timeout: 60
                enabled: true

        Args:
            config_path: Path to YAML configuration file
            **kwargs: Override settings from config

        Returns:
            Configured A2AMeshDiscovery instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config format is invalid
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)

        if not raw_config:
            raw_config = {}

        # Process environment variables
        config = cls._substitute_env_vars(raw_config)

        # Extract settings
        settings = config.get("settings", {})
        merged_settings = {
            "health_check_interval": settings.get("health_check_interval", 30.0),
            "health_check_timeout": settings.get("health_check_timeout", 10.0),
            "auto_discover_on_start": settings.get("auto_discover_on_start", True),
            "max_concurrent_health_checks": settings.get("max_concurrent_health_checks", 10),
            "retry_unhealthy_interval": settings.get("retry_unhealthy_interval", 60.0),
            "remove_after_failures": settings.get("remove_after_failures", 0),
        }
        merged_settings |= kwargs

        # Create instance
        instance = cls(**merged_settings)

        # Add endpoints from config
        agents_config = config.get("agents", [])
        for agent_config in agents_config:
            if isinstance(agent_config, str):
                # Simple URL string
                instance.add_endpoint(agent_config)
            elif isinstance(agent_config, dict):
                # Full endpoint configuration
                if url := agent_config.pop("url", None):
                    instance.add_endpoint(url, **agent_config)

        instance.logger.info(
            f"Loaded {len(instance._endpoints)} endpoints from {path}"
        )

        return instance

    @classmethod
    def _substitute_env_vars(cls, obj: Any) -> Any:
        """
        Recursively substitute environment variables in configuration.

        Replaces ${VAR_NAME} patterns with environment variable values.
        If variable is not set, the pattern is left unchanged.

        Args:
            obj: Object to process (dict, list, str, or other)

        Returns:
            Processed object with environment variables substituted
        """
        if isinstance(obj, dict):
            return {k: cls._substitute_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [cls._substitute_env_vars(item) for item in obj]
        elif isinstance(obj, str):
            def replacer(match):
                var_name = match.group(1)
                return os.environ.get(var_name, match.group(0))
            return cls.ENV_VAR_PATTERN.sub(replacer, obj)
        return obj

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle management
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Start the mesh discovery service.

        This will:
        1. Initialize the concurrency semaphore
        2. Discover all configured endpoints (if auto_discover_on_start is True)
        3. Start the background health check loop
        """
        if self._running:
            self.logger.warning("Mesh discovery already running")
            return

        self._running = True
        self._semaphore = asyncio.Semaphore(self._max_concurrent_health_checks)

        self.logger.info(
            f"Starting A2A Mesh Discovery with {len(self._endpoints)} endpoints"
        )

        # Auto-discover configured endpoints
        if self._auto_discover_on_start and self._endpoints:
            await self._discover_all_endpoints()

        # Start health check loop
        self._health_task = asyncio.create_task(
            self._health_check_loop(),
            name="a2a_mesh_health_check"
        )

        self.logger.info(
            f"A2A Mesh Discovery started: "
            f"{self._stats.total_healthy}/{self._stats.total_registered} agents healthy"
        )

    async def stop(self) -> None:
        """
        Stop the mesh discovery service.

        Cancels the health check loop and cleans up resources.
        """
        if not self._running:
            return

        self._running = False

        if self._health_task:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
            self._health_task = None

        self.logger.info("A2A Mesh Discovery stopped")

    async def __aenter__(self) -> "A2AMeshDiscovery":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()

    # ─────────────────────────────────────────────────────────────────────────
    # Endpoint configuration (pre-discovery)
    # ─────────────────────────────────────────────────────────────────────────

    def add_endpoint(
        self,
        url: str,
        *,
        name: Optional[str] = None,
        auth_token: Optional[str] = None,
        api_key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        tags: Optional[Union[Set[str], List[str]]] = None,
        timeout: float = 30.0,
        health_check_strategy: Union[HealthCheckStrategy, str] = HealthCheckStrategy.DISCOVERY,
        health_check_endpoint: Optional[str] = None,
        enabled: bool = True,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "A2AMeshDiscovery":
        """
        Add an endpoint configuration for later discovery.

        The endpoint won't be discovered until start() is called or
        register() is called explicitly.

        Args:
            url: Base URL of the A2A agent
            name: Optional name hint
            auth_token: Bearer token for authentication
            api_key: API key for X-API-Key header
            headers: Additional HTTP headers
            tags: Tags for categorization
            timeout: Request timeout
            health_check_strategy: Strategy for health checks
            health_check_endpoint: Custom health check endpoint
            enabled: Whether endpoint is enabled
            priority: Priority for load balancing
            metadata: Additional metadata

        Returns:
            Self for method chaining
        """
        url = url.rstrip("/")

        if isinstance(health_check_strategy, str):
            health_check_strategy = HealthCheckStrategy(health_check_strategy)

        endpoint = A2AEndpoint(
            url=url,
            name=name,
            auth_token=auth_token,
            api_key=api_key,
            headers=headers,
            tags=set(tags) if tags else set(),
            timeout=timeout,
            health_check_strategy=health_check_strategy,
            health_check_endpoint=health_check_endpoint,
            enabled=enabled,
            priority=priority,
            metadata=metadata or {},
        )

        self._endpoints[url] = endpoint
        self.logger.debug(f"Added endpoint: {url}")

        return self

    def remove_endpoint(self, url: str) -> bool:
        """
        Remove an endpoint configuration.

        Also removes the discovered agent if present.

        Args:
            url: URL of the endpoint to remove

        Returns:
            True if endpoint was removed, False if not found
        """
        url = url.rstrip("/")

        if url not in self._endpoints:
            return False

        del self._endpoints[url]

        # Remove discovered agent if present
        if url in self._url_to_name:
            name = self._url_to_name[url]
            if name in self._discovered:
                agent = self._discovered.pop(name)
                del self._url_to_name[url]
                self._failure_counts.pop(name, None)
                self._update_stats()
                asyncio.create_task(self._emit_event("removed", agent))

        self.logger.debug(f"Removed endpoint: {url}")
        return True

    def get_endpoint(self, url: str) -> Optional[A2AEndpoint]:
        """Get endpoint configuration by URL."""
        return self._endpoints.get(url.rstrip("/"))

    def list_endpoints(self) -> List[A2AEndpoint]:
        """List all configured endpoints."""
        return list(self._endpoints.values())

    # ─────────────────────────────────────────────────────────────────────────
    # Registration and discovery
    # ─────────────────────────────────────────────────────────────────────────

    async def register(
        self,
        url: str,
        *,
        auth_token: Optional[str] = None,
        api_key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        tags: Optional[Union[Set[str], List[str]]] = None,
        timeout: float = 30.0,
        **kwargs
    ) -> RegisteredAgent:
        """
        Register and discover an agent immediately.

        Connects to the agent, fetches its AgentCard, and adds it to the registry.
        This method both configures the endpoint and performs discovery.

        Args:
            url: Base URL of the A2A agent
            auth_token: Bearer token for authentication
            api_key: API key for X-API-Key header
            headers: Additional HTTP headers
            tags: Additional tags to merge with agent's tags
            timeout: Request timeout
            **kwargs: Additional endpoint configuration

        Returns:
            RegisteredAgent with discovered card

        Raises:
            ConnectionError: If agent is unreachable
            ValueError: If agent card is invalid
        """
        url = url.rstrip("/")

        # Add to endpoints if not already configured
        if url not in self._endpoints:
            self.add_endpoint(
                url,
                auth_token=auth_token,
                api_key=api_key,
                headers=headers,
                tags=tags,
                timeout=timeout,
                **kwargs
            )

        endpoint = self._endpoints[url]

        # Perform discovery
        return await self._discover_endpoint(endpoint)

    async def _discover_endpoint(self, endpoint: A2AEndpoint) -> RegisteredAgent:
        """
        Discover an agent from an endpoint configuration.

        Args:
            endpoint: Endpoint configuration

        Returns:
            Discovered and registered agent

        Raises:
            ConnectionError: If discovery fails
        """
        if not endpoint.enabled:
            raise ValueError(f"Endpoint {endpoint.url} is disabled")

        try:
            async with A2AClient(
                endpoint.url,
                auth_token=endpoint.auth_token,
                api_key=endpoint.api_key,
                headers=endpoint.headers,
                timeout=endpoint.timeout,
            ) as client:
                card = await client.discover()

            # Merge local tags with agent's tags
            if endpoint.tags:
                card.tags = list(set(card.tags) | endpoint.tags)

            # Create registered agent
            agent = RegisteredAgent(
                url=endpoint.url,
                card=card,
                last_seen=datetime.now(timezone.utc),
                healthy=True,
            )

            # Store in registry
            old_agent = self._discovered.get(card.name)
            self._discovered[card.name] = agent
            self._url_to_name[endpoint.url] = card.name
            self._failure_counts[card.name] = 0

            self._update_stats()

            # Emit event
            if old_agent is None:
                await self._emit_event("registered", agent)

            self.logger.info(
                f"Discovered A2A agent: {card.name} at {endpoint.url} "
                f"with {len(card.skills)} skills"
            )

            return agent

        except Exception as e:
            self._stats.discovery_errors += 1
            self.logger.error(f"Failed to discover agent at {endpoint.url}: {e}")
            raise ConnectionError(f"Failed to discover agent: {e}") from e

    async def _discover_all_endpoints(self) -> Dict[str, Union[RegisteredAgent, Exception]]:
        """
        Discover all configured endpoints concurrently.

        Returns:
            Dict mapping URL to either RegisteredAgent or Exception
        """
        results: Dict[str, Union[RegisteredAgent, Exception]] = {}

        enabled_endpoints = [ep for ep in self._endpoints.values() if ep.enabled]

        if not enabled_endpoints:
            return results

        async def discover_one(ep: A2AEndpoint) -> tuple[str, Union[RegisteredAgent, Exception]]:
            try:
                agent = await self._discover_endpoint(ep)
                return ep.url, agent
            except Exception as e:
                return ep.url, e

        # Discover concurrently with semaphore
        tasks = [discover_one(ep) for ep in enabled_endpoints]
        completed = await asyncio.gather(*tasks, return_exceptions=False)

        for url, result in completed:
            results[url] = result
            if isinstance(result, Exception):
                self.logger.warning(f"Failed to discover {url}: {result}")

        return results

    async def unregister(self, name: str) -> bool:
        """
        Unregister an agent by name.

        Removes the agent from the registry but keeps the endpoint configuration.

        Args:
            name: Name of the agent to unregister

        Returns:
            True if agent was unregistered, False if not found
        """
        if name not in self._discovered:
            return False

        agent = self._discovered.pop(name)

        # Clean up reverse lookup
        for url, agent_name in list(self._url_to_name.items()):
            if agent_name == name:
                del self._url_to_name[url]
                break

        self._failure_counts.pop(name, None)
        self._update_stats()

        await self._emit_event("removed", agent)

        self.logger.info(f"Unregistered agent: {name}")
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Query methods
    # ─────────────────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[RegisteredAgent]:
        """
        Get a registered agent by name.

        Args:
            name: Exact name of the agent

        Returns:
            RegisteredAgent if found, None otherwise
        """
        return self._discovered.get(name)

    def get_by_url(self, url: str) -> Optional[RegisteredAgent]:
        """
        Get a registered agent by URL.

        Args:
            url: URL of the agent

        Returns:
            RegisteredAgent if found, None otherwise
        """
        url = url.rstrip("/")
        name = self._url_to_name.get(url)
        return self._discovered.get(name) if name else None

    def get_by_skill(
        self,
        skill_id: str,
        *,
        include_unhealthy: bool = False,
        match_name: bool = True,
    ) -> List[RegisteredAgent]:
        """
        Find agents that have a specific skill.

        Searches by skill ID and optionally by skill name.

        Args:
            skill_id: Skill ID or name to search for
            include_unhealthy: If True, include unhealthy agents
            match_name: If True, also match against skill name

        Returns:
            List of matching RegisteredAgent instances
        """
        results: List[RegisteredAgent] = []
        skill_lower = skill_id.lower()

        for agent in self._discovered.values():
            # Skip unhealthy unless requested
            if not include_unhealthy and not agent.healthy:
                continue

            # Check each skill
            for skill in agent.card.skills:
                matched = skill.id.lower() == skill_lower

                if not matched and match_name:
                    matched = skill_lower in skill.name.lower()

                if matched:
                    results.append(agent)
                    break  # Don't add same agent twice

        return results

    def get_by_tag(
        self,
        tag: str,
        *,
        include_unhealthy: bool = False,
        check_skill_tags: bool = True,
    ) -> List[RegisteredAgent]:
        """
        Find agents that have a specific tag.

        Searches agent-level tags and optionally skill-level tags.

        Args:
            tag: Tag to search for (case-insensitive)
            include_unhealthy: If True, include unhealthy agents
            check_skill_tags: If True, also check tags on individual skills

        Returns:
            List of matching RegisteredAgent instances
        """
        results: List[RegisteredAgent] = []
        tag_lower = tag.lower()

        for agent in self._discovered.values():
            # Skip unhealthy unless requested
            if not include_unhealthy and not agent.healthy:
                continue

            # Check agent-level tags
            if any(t.lower() == tag_lower for t in agent.card.tags):
                results.append(agent)
                continue

            # Check skill-level tags
            if check_skill_tags:
                for skill in agent.card.skills:
                    if any(t.lower() == tag_lower for t in skill.tags):
                        results.append(agent)
                        break

        return results

    def search(
        self,
        query: str,
        *,
        include_unhealthy: bool = False,
        search_fields: Optional[List[str]] = None,
    ) -> List[RegisteredAgent]:
        """
        Full-text search across agent metadata.

        Searches agent name, description, skill names, and skill descriptions.

        Args:
            query: Search query (case-insensitive)
            include_unhealthy: If True, include unhealthy agents
            search_fields: Fields to search (default: name, description, skills)

        Returns:
            List of matching RegisteredAgent instances
        """
        results: List[RegisteredAgent] = []
        query_lower = query.lower()

        if search_fields is None:
            search_fields = ["name", "description", "skills"]

        for agent in self._discovered.values():
            if not include_unhealthy and not agent.healthy:
                continue

            matched = False
            card = agent.card

            # Search name
            if "name" in search_fields and query_lower in card.name.lower():
                matched = True

            # Search description
            if not matched and "description" in search_fields:
                if query_lower in card.description.lower():
                    matched = True

            # Search skills
            if not matched and "skills" in search_fields:
                for skill in card.skills:
                    if query_lower in skill.name.lower():
                        matched = True
                        break
                    if query_lower in skill.description.lower():
                        matched = True
                        break

            # Search tags
            if not matched and "tags" in search_fields:
                if any(query_lower in t.lower() for t in card.tags):
                    matched = True

            if matched:
                results.append(agent)

        return results

    def list_healthy(self) -> List[RegisteredAgent]:
        """
        Get all healthy agents.

        Returns:
            List of healthy RegisteredAgent instances
        """
        return [a for a in self._discovered.values() if a.healthy]

    def list_unhealthy(self) -> List[RegisteredAgent]:
        """
        Get all unhealthy agents.

        Returns:
            List of unhealthy RegisteredAgent instances
        """
        return [a for a in self._discovered.values() if not a.healthy]

    def list_all(self) -> List[RegisteredAgent]:
        """
        Get all registered agents regardless of health status.

        Returns:
            List of all RegisteredAgent instances
        """
        return list(self._discovered.values())

    def list_by_priority(self, descending: bool = True) -> List[RegisteredAgent]:
        """
        Get agents sorted by priority.

        Priority comes from the endpoint configuration.

        Args:
            descending: If True, highest priority first

        Returns:
            List of RegisteredAgent instances sorted by priority
        """
        def get_priority(agent: RegisteredAgent) -> int:
            endpoint = self._endpoints.get(agent.url)
            return endpoint.priority if endpoint else 0

        return sorted(
            self._discovered.values(),
            key=get_priority,
            reverse=descending
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Health checking
    # ─────────────────────────────────────────────────────────────────────────

    async def _health_check_loop(self) -> None:
        """
        Background loop for periodic health checks.

        Runs continuously until stop() is called.
        """
        while self._running:
            try:
                await self._perform_health_checks()
                self._stats.last_health_check = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Health check error: {e}")

            await asyncio.sleep(self._health_check_interval)

    async def _perform_health_checks(self) -> None:
        """
        Perform health checks on all registered agents.

        Uses semaphore to limit concurrent checks.
        """
        if not self._discovered:
            return

        async def check_one(name: str, agent: RegisteredAgent) -> None:
            async with self._semaphore:
                await self._check_agent_health(name, agent)

        # Check all agents concurrently
        await asyncio.gather(
            *[check_one(name, agent) for name, agent in list(self._discovered.items())],
            return_exceptions=True
        )

        self._stats.health_checks_performed += 1
        self._update_stats()

    async def _check_agent_health(self, name: str, agent: RegisteredAgent) -> None:
        """
        Check health of a single agent.

        Args:
            name: Agent name
            agent: Agent to check
        """
        endpoint = self._endpoints.get(agent.url)
        if not endpoint:
            return

        was_healthy = agent.healthy

        try:
            healthy = await self._do_health_check(endpoint)

            if healthy:
                agent.healthy = True
                agent.last_seen = datetime.now(timezone.utc)
                self._failure_counts[name] = 0

                if not was_healthy:
                    self.logger.info(f"Agent {name} is now healthy")
                    await self._emit_event("healthy", agent)
            else:
                await self._handle_health_failure(name, agent, was_healthy)

        except Exception as e:
            self.logger.debug(f"Health check failed for {name}: {e}")
            await self._handle_health_failure(name, agent, was_healthy)

    async def _do_health_check(self, endpoint: A2AEndpoint) -> bool:
        """
        Perform the actual health check request.

        Args:
            endpoint: Endpoint to check

        Returns:
            True if healthy, False otherwise
        """
        strategy = endpoint.health_check_strategy

        timeout = aiohttp.ClientTimeout(total=self._health_check_timeout)
        headers = {"Content-Type": "application/json"}
        if endpoint.auth_token:
            headers["Authorization"] = f"Bearer {endpoint.auth_token}"
        if endpoint.api_key:
            headers["X-API-Key"] = endpoint.api_key
        if endpoint.headers:
            headers |= endpoint.headers

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            if strategy == HealthCheckStrategy.DISCOVERY:
                url = f"{endpoint.url}/.well-known/agent.json"
            elif strategy == HealthCheckStrategy.PING:
                url = endpoint.url
            elif strategy == HealthCheckStrategy.CUSTOM:
                url = endpoint.health_check_endpoint or endpoint.url
            else:
                url = f"{endpoint.url}/.well-known/agent.json"

            async with session.get(url) as resp:
                return resp.status == 200

    async def _handle_health_failure(
        self,
        name: str,
        agent: RegisteredAgent,
        was_healthy: bool
    ) -> None:
        """
        Handle a health check failure.

        Args:
            name: Agent name
            agent: Agent that failed health check
            was_healthy: Whether agent was healthy before this check
        """
        agent.healthy = False
        self._failure_counts[name] = self._failure_counts.get(name, 0) + 1

        if was_healthy:
            self.logger.warning(f"Agent {name} is now unhealthy")
            await self._emit_event("unhealthy", agent)

        # Remove after consecutive failures if configured
        if self._remove_after_failures > 0:
            if self._failure_counts[name] >= self._remove_after_failures:
                self.logger.warning(
                    f"Removing agent {name} after {self._failure_counts[name]} failures"
                )
                await self.unregister(name)

    async def check_health_now(self, name: Optional[str] = None) -> Dict[str, bool]:
        """
        Trigger immediate health check.

        Args:
            name: If provided, only check this agent. Otherwise check all.

        Returns:
            Dict mapping agent name to health status
        """
        results: Dict[str, bool] = {}

        if name:
            if agent := self._discovered.get(name):
                await self._check_agent_health(name, agent)
                results[name] = agent.healthy
        else:
            await self._perform_health_checks()
            for agent_name, agent in self._discovered.items():
                results[agent_name] = agent.healthy

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Events and callbacks
    # ─────────────────────────────────────────────────────────────────────────
    def on_agent_healthy(self, callback: AgentEventCallback) -> "A2AMeshDiscovery":
        """
        Register callback for when an agent becomes healthy.

        Args:
            callback: Async callback(agent, event_type)

        Returns:
            Self for method chaining
        """
        self._on_agent_healthy.append(callback)
        return self

    def on_agent_unhealthy(self, callback: AgentEventCallback) -> "A2AMeshDiscovery":
        """
        Register callback for when an agent becomes unhealthy.

        Args:
            callback: Async callback(agent, event_type)

        Returns:
            Self for method chaining
        """
        self._on_agent_unhealthy.append(callback)
        return self

    def on_agent_registered(self, callback: AgentEventCallback) -> "A2AMeshDiscovery":
        """
        Register callback for when a new agent is registered.

        Args:
            callback: Async callback(agent, event_type)

        Returns:
            Self for method chaining
        """
        self._on_agent_registered.append(callback)
        return self

    def on_agent_removed(self, callback: AgentEventCallback) -> "A2AMeshDiscovery":
        """
        Register callback for when an agent is removed.

        Args:
            callback: Async callback(agent, event_type)

        Returns:
            Self for method chaining
        """
        self._on_agent_removed.append(callback)
        return self

    async def _emit_event(self, event_type: str, agent: RegisteredAgent) -> None:
        """
        Emit an event to registered callbacks.

        Args:
            event_type: Type of event (healthy, unhealthy, registered, removed)
            agent: Agent involved in the event
        """
        callbacks: List[AgentEventCallback] = []

        if event_type == "healthy":
            callbacks = self._on_agent_healthy
        elif event_type == "unhealthy":
            callbacks = self._on_agent_unhealthy
        elif event_type == "registered":
            callbacks = self._on_agent_registered
        elif event_type == "removed":
            callbacks = self._on_agent_removed

        for callback in callbacks:
            try:
                await callback(agent, event_type)
            except Exception as e:
                self.logger.error(f"Error in event callback: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Statistics and monitoring
    # ─────────────────────────────────────────────────────────────────────────
    def _update_stats(self) -> None:
        """Update internal statistics."""
        self._stats.total_registered = len(self._discovered)
        self._stats.total_healthy = sum(bool(a.healthy) for a in self._discovered.values())
        self._stats.total_unhealthy = self._stats.total_registered - self._stats.total_healthy

    @property
    def stats(self) -> DiscoveryStats:
        """Get current discovery statistics."""
        return self._stats

    def get_info(self) -> Dict[str, Any]:
        """
        Get detailed information about the mesh state.

        Returns:
            Dictionary with mesh status information
        """
        return {
            "running": self._running,
            "endpoints_configured": len(self._endpoints),
            "agents_discovered": len(self._discovered),
            "stats": self._stats.to_dict(),
            "agents": {
                name: {
                    "url": agent.url,
                    "healthy": agent.healthy,
                    "last_seen": agent.last_seen.isoformat(),
                    "skills_count": len(agent.card.skills),
                    "tags": agent.card.tags,
                    "failure_count": self._failure_counts.get(name, 0),
                }
                for name, agent in self._discovered.items()
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Utility methods
    # ─────────────────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        """Return number of registered agents."""
        return len(self._discovered)

    def __contains__(self, name: str) -> bool:
        """Check if agent is registered."""
        return name in self._discovered

    def __iter__(self):
        """Iterate over registered agents."""
        return iter(self._discovered.values())

    def __repr__(self) -> str:
        return (
            f"A2AMeshDiscovery("
            f"endpoints={len(self._endpoints)}, "
            f"discovered={len(self._discovered)}, "
            f"healthy={self._stats.total_healthy})"
        )
