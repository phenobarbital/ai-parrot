# parrot/a2a/mixin.py
"""
A2A Client Mixin - Add A2A client capabilities to AI-Parrot agents.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from navconfig.logging import logging
from .models import TaskState
from .client import (
    A2AClient,
    A2AAgentConnection,
    A2ARemoteAgentTool,
    A2ARemoteSkillTool
)


if TYPE_CHECKING:
    from ..bots.abstract import AbstractBot


class A2AClientMixin:
    """
    Mixin to add A2A client capabilities to any AbstractBot.

    This allows an agent to communicate with remote A2A agents,
    either directly or by registering them as tools.

    Example:
        class MyAgent(A2AClientMixin, BasicAgent):
            pass

        agent = MyAgent(name="Orchestrator", llm="openai:gpt-4")
        await agent.configure()

        # Connect to remote agents
        await agent.add_a2a_agent("https://data-agent:8080")
        await agent.add_a2a_agent("https://search-agent:8081")

        # Now the agent can use remote agents as tools
        response = await agent.ask("Search for X and analyze the data")

        # Or call remote agents directly
        result = await agent.ask_remote_agent("data-agent", "What's the total revenue?")
    """

    _a2a_clients: Dict[str, A2AAgentConnection]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._a2a_clients: Dict[str, A2AAgentConnection] = {}
        self._a2a_logger = logging.getLogger(f"A2AClient.{getattr(self, 'name', 'Agent')}")

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
            self._a2a_logger.info(f"Registered remote agent '{agent_name}' as tool: {tool.name}")

        if register_skills_as_tools:
            for skill in card.skills:
                skill_tool = A2ARemoteSkillTool(client, skill)
                self._register_a2a_tool(skill_tool)
                self._a2a_logger.info(f"Registered remote skill as tool: {skill_tool.name}")

        self._a2a_logger.info(
            f"Connected to A2A agent '{card.name}' at {url} with {len(card.skills)} skills"
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
        """Disconnect from a remote A2A agent."""
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

    # ─────────────────────────────────────────────────────────────
    # Direct Communication Methods
    # ─────────────────────────────────────────────────────────────

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
        """
        conn = self._a2a_clients.get(agent_name)
        if not conn:
            raise ValueError(f"A2A agent '{agent_name}' not connected")

        if stream:
            chunks = []
            async for chunk in conn.client.stream_message(question, context_id=context_id):
                chunks.append(chunk)
            return "".join(chunks)
        else:
            task = await conn.client.send_message(question, context_id=context_id)

            if task.status.state == TaskState.FAILED:
                error = task.status.message.get_text() if task.status.message else "Unknown"
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
        """
        if conn := self._a2a_clients.get(agent_name):
            return await conn.client.invoke_skill(skill_id, params, context_id=context_id)

        raise ValueError(f"A2A agent '{agent_name}' not connected")

    # ─────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────

    async def shutdown_a2a(self) -> None:
        """Disconnect all A2A agents."""
        for name in list(self._a2a_clients.keys()):
            await self.remove_a2a_agent(name)

    async def shutdown(self, **kwargs) -> None:
        """Override shutdown to cleanup A2A connections."""
        await self.shutdown_a2a()

        if hasattr(super(), 'shutdown'):
            await super().shutdown(**kwargs)
