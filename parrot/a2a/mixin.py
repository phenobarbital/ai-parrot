"""
A2A Client Mixin - Add A2A client capabilities to AI-Parrot agents.

This mixin enables agents to:
- Connect to remote A2A agents directly
- Discover agents from a centralized mesh
- Use remote agents as callable tools
- Integrate with Router and Orchestrator for complex workflows
"""
from __future__ import annotations
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Union,
)

from navconfig.logging import logging
from .client import (
    A2AClient,
    A2AAgentConnection,
    A2ARemoteAgentTool,
    A2ARemoteSkillTool,
)
from .models import TaskState
if TYPE_CHECKING:
    from .mesh import A2AMeshDiscovery
    from .router import A2AProxyRouter
    from .orchestrator import A2AOrchestrator


class A2AClientMixin:
    """
    Mixin to add A2A client capabilities to any AbstractBot.

    This allows an agent to communicate with remote A2A agents,
    either directly or by registering them as tools.

    Features:
        - Direct connection to remote A2A agents
        - Integration with A2AMeshDiscovery for centralized discovery
        - Integration with A2AProxyRouter for rule-based routing
        - Integration with A2AOrchestrator for hybrid orchestration
        - Automatic tool registration for remote agents/skills

    Example:
        class MyAgent(A2AClientMixin, BasicAgent):
            pass

        agent = MyAgent(name="Orchestrator", llm="openai:gpt-4")
        await agent.configure()

        # Option 1: Connect to remote agents directly
        await agent.add_a2a_agent("https://data-agent:8080")
        await agent.add_a2a_agent("https://search-agent:8081")

        # Now the agent can use remote agents as tools
        response = await agent.ask("Search for X and analyze the data")

        # Or call remote agents directly
        result = await agent.ask_remote_agent("data-agent", "What's the total revenue?")

        # Option 2: Use mesh discovery
        mesh = A2AMeshDiscovery.from_config("agents.yaml")
        await mesh.start()
        agent.set_mesh(mesh)
        await agent.discover_from_mesh(skill="data_analysis")

        # Option 3: Use router for rule-based routing
        router = A2AProxyRouter(mesh)
        router.route_by_skill("analysis", "AnalystBot")
        agent.set_router(router)
        result = await agent.route_to_agent("Analyze this data")

        # Option 4: Use orchestrator for hybrid routing
        orchestrator = A2AOrchestrator(mesh)
        orchestrator.set_fallback_llm(llm_client)
        agent.set_orchestrator(orchestrator)
        result = await agent.orchestrate("Complex multi-agent task")
    """

    # Type hints for instance attributes
    _a2a_clients: Dict[str, A2AAgentConnection]
    _a2a_mesh: Optional["A2AMeshDiscovery"]
    _a2a_router: Optional["A2AProxyRouter"]
    _a2a_orchestrator: Optional["A2AOrchestrator"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._a2a_clients: Dict[str, A2AAgentConnection] = {}
        self._a2a_mesh: Optional["A2AMeshDiscovery"] = None
        self._a2a_router: Optional["A2AProxyRouter"] = None
        self._a2a_orchestrator: Optional["A2AOrchestrator"] = None
        self._a2a_logger = logging.getLogger(
            f"A2AClient.{getattr(self, 'name', 'Agent')}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Mesh Integration
    # ─────────────────────────────────────────────────────────────────────────
    def set_mesh(self, mesh: "A2AMeshDiscovery") -> None:
        """
        Connect this agent to an A2A mesh discovery service.

        The mesh provides centralized discovery and health checking
        of remote A2A agents.

        Args:
            mesh: A2AMeshDiscovery instance

        Example:
            mesh = A2AMeshDiscovery.from_config("agents.yaml")
            await mesh.start()
            agent.set_mesh(mesh)
        """
        self._a2a_mesh = mesh
        self._a2a_logger.info("Connected to A2A mesh discovery")

    def get_mesh(self) -> Optional["A2AMeshDiscovery"]:
        """Get the connected mesh discovery service."""
        return self._a2a_mesh

    async def discover_from_mesh(
        self,
        skill: Optional[str] = None,
        tag: Optional[str] = None,
        register_as_tools: bool = True,
    ) -> List[A2AAgentConnection]:
        """
        Discover and connect to agents from the mesh.

        Queries the mesh for agents matching the criteria and
        establishes connections to them.

        Args:
            skill: Filter by skill ID
            tag: Filter by tag
            register_as_tools: If True, register discovered agents as tools

        Returns:
            List of new connections established

        Example:
            # Connect to all agents with data analysis skill
            await agent.discover_from_mesh(skill="data_analysis")

            # Connect to all agents tagged as "support"
            await agent.discover_from_mesh(tag="support")

            # Connect to all healthy agents
            await agent.discover_from_mesh()
        """
        if not self._a2a_mesh:
            raise ValueError("No mesh configured. Call set_mesh() first.")

        # Query mesh based on criteria
        agents = []
        if skill:
            agents = self._a2a_mesh.get_by_skill(skill)
        elif tag:
            agents = self._a2a_mesh.get_by_tag(tag)
        else:
            agents = self._a2a_mesh.list_healthy()

        # Connect to new agents
        connections = []
        for registered_agent in agents:
            agent_name = registered_agent.card.name.lower().replace(" ", "_")
            if agent_name not in self._a2a_clients:
                # Get endpoint config for auth details
                endpoint = self._a2a_mesh.get_endpoint(registered_agent.url)
                conn = await self.add_a2a_agent(
                    registered_agent.url,
                    name=agent_name,
                    auth_token=endpoint.auth_token if endpoint else None,
                    api_key=endpoint.api_key if endpoint else None,
                    headers=endpoint.headers if endpoint else None,
                    register_as_tool=register_as_tools,
                )
                connections.append(conn)

        self._a2a_logger.info(
            f"Discovered {len(connections)} new agents from mesh"
        )
        return connections

    # ─────────────────────────────────────────────────────────────────────────
    # Router Integration
    # ─────────────────────────────────────────────────────────────────────────

    def set_router(self, router: "A2AProxyRouter") -> None:
        """
        Set an A2A router for rule-based message routing.

        The router enables deterministic routing based on skills,
        tags, or regex patterns without LLM involvement.

        Args:
            router: A2AProxyRouter instance

        Example:
            router = A2AProxyRouter(mesh)
            router.route_by_skill("analysis", "AnalystBot")
            router.route_by_tag("support", "SupportBot")
            agent.set_router(router)
        """
        self._a2a_router = router
        self._a2a_logger.info("Connected to A2A router")

    def get_router(self) -> Optional["A2AProxyRouter"]:
        """Get the connected router."""
        return self._a2a_router

    async def route_to_agent(
        self,
        message: str,
        *,
        skill_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        context_id: Optional[str] = None,
    ) -> str:
        """
        Route a message to an agent using the configured router.

        Uses rule-based routing (no LLM) to select the appropriate
        agent and forward the message.

        Args:
            message: Message to route
            skill_id: Optional skill ID hint
            tags: Optional tags hint
            context_id: Optional context for multi-turn

        Returns:
            Response from the routed agent

        Raises:
            ValueError: If no router configured or no route matched
        """
        if not self._a2a_router:
            raise ValueError("No router configured. Call set_router() first.")

        return await self._a2a_router.ask(
            message,
            skill_id=skill_id,
            tags=tags,
            context_id=context_id,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Orchestrator Integration
    # ─────────────────────────────────────────────────────────────────────────

    def set_orchestrator(self, orchestrator: "A2AOrchestrator") -> None:
        """
        Set an A2A orchestrator for hybrid routing.

        The orchestrator combines rule-based routing with LLM-driven
        decision making for complex scenarios.

        Args:
            orchestrator: A2AOrchestrator instance

        Example:
            orchestrator = A2AOrchestrator(mesh)
            orchestrator.route_by_skill("simple_query", "FAQBot")
            orchestrator.set_fallback_llm(llm_client)
            agent.set_orchestrator(orchestrator)
        """
        self._a2a_orchestrator = orchestrator
        self._a2a_logger.info("Connected to A2A orchestrator")

    def get_orchestrator(self) -> Optional["A2AOrchestrator"]:
        """Get the connected orchestrator."""
        return self._a2a_orchestrator

    async def orchestrate(
        self,
        message: str,
        *,
        mode: Optional[str] = None,
        agents: Optional[List[str]] = None,
        context_id: Optional[str] = None,
    ) -> str:
        """
        Orchestrate a message across multiple agents.

        Uses the configured orchestrator which combines rules and
        LLM-based decision making.

        Args:
            message: Message to orchestrate
            mode: Orchestration mode (rules, llm, hybrid, parallel, sequential)
            agents: Optional explicit list of agents
            context_id: Optional context for multi-turn

        Returns:
            Final response from orchestration

        Raises:
            ValueError: If no orchestrator configured
            RuntimeError: If orchestration fails
        """
        if not self._a2a_orchestrator:
            raise ValueError(
                "No orchestrator configured. Call set_orchestrator() first."
            )

        # Import here to avoid circular imports
        from .orchestrator import OrchestrationMode  # pylint: disable=C0415

        orchestration_mode = None
        if mode:
            orchestration_mode = OrchestrationMode(mode)

        return await self._a2a_orchestrator.ask(
            message,
            mode=orchestration_mode,
            agents=agents,
            context_id=context_id,
        )

    async def fan_out(
        self,
        message: str,
        agents: List[str],
        **kwargs
    ) -> Dict[str, Union[str, Exception]]:
        """
        Send message to multiple agents in parallel.

        Args:
            message: Message to send
            agents: List of agent names
            **kwargs: Additional arguments

        Returns:
            Dict mapping agent name to response or exception
        """
        if not self._a2a_orchestrator:
            raise ValueError("No orchestrator configured. Call set_orchestrator() first.")

        return await self._a2a_orchestrator.fan_out(message, agents, **kwargs)

    async def pipeline(
        self,
        message: str,
        agents: List[str],
        **kwargs
    ) -> str:
        """
        Execute sequential pipeline across agents.

        Each agent's output becomes the next agent's input.

        Args:
            message: Initial message
            agents: Ordered list of agent names
            **kwargs: Additional arguments

        Returns:
            Final output from last agent
        """
        if not self._a2a_orchestrator:
            raise ValueError("No orchestrator configured. Call set_orchestrator() first.")

        return await self._a2a_orchestrator.pipeline(message, agents, **kwargs)

    # ─────────────────────────────────────────────────────────────────────────
    # Direct Agent Connection
    # ─────────────────────────────────────────────────────────────────────────

    async def add_a2a_agent(
        self,
        url: str,
        *,
        name: Optional[str] = None,
        auth_token: Optional[str] = None,
        api_key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        register_as_tool: bool = True,
        register_skills_as_tools: bool = False,
        use_streaming: bool = False,
        timeout: float = 60.0,
    ) -> A2AAgentConnection:
        """
        Connect to a remote A2A agent.

        Args:
            url: Base URL of the remote agent
            name: Optional name override (defaults to agent's name from card)
            auth_token: Bearer token for authentication
            api_key: API key for authentication
            headers: Additional headers
            register_as_tool: If True, register the agent as a callable tool
            register_skills_as_tools: If True, register each skill as a separate tool
            use_streaming: If True, use streaming for tool calls
            timeout: Request timeout

        Returns:
            A2AAgentConnection with the remote agent info
        """
        client = A2AClient(
            url,
            auth_token=auth_token,
            api_key=api_key,
            headers=headers,
            timeout=timeout,
        )

        await client.connect()

        card = client.agent_card
        agent_name = name or card.name.lower().replace(" ", "_")

        connection = A2AAgentConnection(
            url=url,
            card=card,
            client=client,
            name=agent_name,
        )

        self._a2a_clients[agent_name] = connection

        # Register as tool(s)
        if register_as_tool:
            tool = A2ARemoteAgentTool(
                client,
                tool_name=f"ask_{agent_name}",
                use_streaming=use_streaming,
            )
            self._register_a2a_tool(tool)
            self._a2a_logger.info(
                f"Registered remote agent '{agent_name}' as tool: {tool.name}"
            )

        if register_skills_as_tools:
            for skill in card.skills:
                skill_tool = A2ARemoteSkillTool(client, skill)
                self._register_a2a_tool(skill_tool)
                self._a2a_logger.info(
                    f"Registered remote skill as tool: {skill_tool.name}"
                )

        self._a2a_logger.info(
            f"Connected to A2A agent '{card.name}' at {url} "
            f"with {len(card.skills)} skills"
        )

        return connection

    def _register_a2a_tool(self, tool: Any) -> None:
        """Register a tool with the agent's tool manager."""
        if hasattr(self, 'tool_manager') and self.tool_manager:
            self.tool_manager.register_tool(tool)

            # Sync to LLM if method exists
            if hasattr(self, '_sync_tools_to_llm'):
                self._sync_tools_to_llm()

    async def remove_a2a_agent(self, name: str) -> None:
        """
        Disconnect from a remote A2A agent.

        Args:
            name: Name of the agent to disconnect
        """
        if name not in self._a2a_clients:
            self._a2a_logger.warning(f"A2A agent '{name}' not found")
            return

        connection = self._a2a_clients[name]

        # Remove tools
        if hasattr(self, 'tool_manager') and self.tool_manager:
            tool_name = f"ask_{name}"
            if self.tool_manager.get_tool(tool_name):
                self.tool_manager.unregister_tool(tool_name)

            # Remove skill tools
            for skill in connection.card.skills:
                skill_tool_name = f"remote_{skill.id}"
                if self.tool_manager.get_tool(skill_tool_name):
                    self.tool_manager.unregister_tool(skill_tool_name)

        await connection.client.disconnect()
        del self._a2a_clients[name]

        self._a2a_logger.info(f"Disconnected from A2A agent '{name}'")

    # ─────────────────────────────────────────────────────────────────────────
    # Query Methods
    # ─────────────────────────────────────────────────────────────────────────

    def list_a2a_agents(self) -> List[str]:
        """List connected A2A agent names."""
        return list(self._a2a_clients.keys())

    def get_a2a_agent(self, name: str) -> Optional[A2AAgentConnection]:
        """Get a connected A2A agent by name."""
        return self._a2a_clients.get(name)

    def get_a2a_client(self, name: str) -> Optional[A2AClient]:
        """Get the A2A client for a connected agent."""
        conn = self._a2a_clients.get(name)
        return conn.client if conn else None

    # ─────────────────────────────────────────────────────────────────────────
    # Direct Communication Methods
    # ─────────────────────────────────────────────────────────────────────────

    async def ask_remote_agent(
        self,
        agent_name: str,
        question: str,
        *,
        context_id: Optional[str] = None,
        stream: bool = False,
    ) -> str:
        """
        Ask a question directly to a remote A2A agent.

        Args:
            agent_name: Name of the connected agent
            question: The question to ask
            context_id: Optional context for multi-turn
            stream: If True, stream the response

        Returns:
            The agent's response as text

        Raises:
            ValueError: If agent not connected
            RuntimeError: If agent returns error
        """
        conn = self._a2a_clients.get(agent_name)
        if not conn:
            raise ValueError(f"A2A agent '{agent_name}' not connected")

        if stream:
            chunks = []
            async for chunk in conn.client.stream_message(
                question, context_id=context_id
            ):
                chunks.append(chunk)
            return "".join(chunks)
        else:
            task = await conn.client.send_message(question, context_id=context_id)

            if task.status.state == TaskState.FAILED:
                error = (
                    task.status.message.get_text()
                    if task.status.message
                    else "Unknown error"
                )
                raise RuntimeError(f"Remote agent error: {error}")

            if task.artifacts and task.artifacts[0].parts:
                return task.artifacts[0].parts[0].text or ""
            return ""

    async def invoke_remote_skill(
        self,
        agent_name: str,
        skill_id: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        context_id: Optional[str] = None,
    ) -> Any:
        """
        Invoke a specific skill on a remote agent.

        Args:
            agent_name: Name of the connected agent
            skill_id: ID of the skill to invoke
            params: Parameters for the skill
            context_id: Optional context

        Returns:
            The skill result

        Raises:
            ValueError: If agent not connected
        """
        conn = self._a2a_clients.get(agent_name)
        if not conn:
            raise ValueError(f"A2A agent '{agent_name}' not connected")

        return await conn.client.invoke_skill(
            skill_id, params, context_id=context_id
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def shutdown_a2a(self) -> None:
        """Disconnect all A2A connections and cleanup resources."""
        # Disconnect direct connections
        for name in list(self._a2a_clients.keys()):
            await self.remove_a2a_agent(name)

        # Close router clients if present
        if self._a2a_router:
            await self._a2a_router.close_clients()

        # Close orchestrator clients if present
        if self._a2a_orchestrator:
            await self._a2a_orchestrator.close_clients()

        self._a2a_logger.info("A2A connections shutdown complete")

    async def shutdown(self, **kwargs) -> None:
        """Override shutdown to cleanup A2A connections."""
        await self.shutdown_a2a()

        if hasattr(super(), 'shutdown'):
            await super().shutdown(**kwargs)
