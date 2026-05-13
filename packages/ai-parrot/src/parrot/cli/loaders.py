"""Agent loading strategies for the AI-Parrot CLI REPL.

Provides two loading strategies:

- ``StandaloneAgentLoader`` — loads agents from the in-process
  ``AgentRegistry`` without requiring a running server.
- ``ServerAgentProxy`` — proxies agent interactions to a running
  AI-Parrot server via HTTP.
"""
import asyncio
import difflib
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import aiohttp
import questionary

from parrot.bots.abstract import AbstractBot
from parrot.registry import agent_registry
from parrot.registry.registry import BotMetadata


class AgentLoadError(Exception):
    """Raised when an agent cannot be loaded.

    Attributes:
        agent_name: The name that was requested.
        suggestions: Fuzzy-matched agent names from the registry.
    """

    def __init__(
        self,
        agent_name: str,
        suggestions: Optional[List[str]] = None,
        message: Optional[str] = None,
    ) -> None:
        """Initialise AgentLoadError.

        Args:
            agent_name: The requested agent name.
            suggestions: Optional list of close-match suggestions.
            message: Optional custom error message.
        """
        self.agent_name = agent_name
        self.suggestions = suggestions or []
        if message:
            detail = message
        elif self.suggestions:
            detail = f"Agent '{agent_name}' not found. Did you mean: {', '.join(self.suggestions)}?"
        else:
            detail = f"Agent '{agent_name}' not found. No similar agents registered."
        super().__init__(detail)


class StandaloneAgentLoader:
    """Load agents from the in-process AgentRegistry.

    Uses ``AgentRegistry.get_instance()`` with fuzzy name matching fallback
    and an interactive ``questionary.select()`` picker when no name is given.

    Attributes:
        logger: Module-level logger.
    """

    def __init__(self) -> None:
        """Initialise the standalone loader."""
        self.logger = logging.getLogger(__name__)

    async def load(self, name: str) -> AbstractBot:
        """Load a registered agent by name.

        Calls ``AgentRegistry.get_instance()`` to retrieve the agent,
        including implicit ``configure()`` via ``BotMetadata.get_instance()``.

        Args:
            name: The registered agent name.

        Returns:
            Configured ``AbstractBot`` instance.

        Raises:
            AgentLoadError: If the agent is not found, with fuzzy suggestions.
        """
        self.logger.debug("Loading agent '%s' from registry", name)
        bot = await agent_registry.get_instance(name)
        if bot is None:
            available = list(agent_registry._registered_agents.keys())
            close = difflib.get_close_matches(name, available, n=3, cutoff=0.5)
            raise AgentLoadError(name, suggestions=close)
        self.logger.info("Loaded agent '%s'", name)
        return bot

    async def list_agents(self) -> List[BotMetadata]:
        """Return all registered agent metadata.

        Returns:
            List of ``BotMetadata`` instances from the registry.
        """
        return list(agent_registry._registered_agents.values())

    async def select_agent(self) -> str:
        """Present an interactive agent picker using questionary.

        Displays a ``questionary.select()`` prompt listing all registered
        agent names. Uses ``ask_async()`` for asyncio compatibility.

        Returns:
            The selected agent name.

        Raises:
            AgentLoadError: If no agents are registered.
        """
        agents = list(agent_registry._registered_agents.keys())
        if not agents:
            raise AgentLoadError(
                "",
                message="No agents are registered. Check your agents directory.",
            )
        selected = await questionary.select(
            "Select an agent to start:",
            choices=agents,
        ).ask_async()
        if selected is None:
            raise AgentLoadError("", message="No agent selected.")
        return selected


class _ServerBotProxy:
    """Thin HTTP proxy that satisfies the AbstractBot interface subset.

    Not a full AbstractBot subclass — only implements the methods used
    by the REPL (``ask()``, ``ask_stream()``, ``get_available_tools()``,
    ``get_tools_count()``, ``has_tools()``, ``configure()``).

    Attributes:
        name: Agent name as reported by the server.
        _server_url: Base URL of the running AI-Parrot server.
        _session: Shared ``aiohttp.ClientSession``.
        _tools: Cached list of tool names.
    """

    def __init__(
        self,
        name: str,
        server_url: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialise the server bot proxy.

        Args:
            name: Agent name.
            server_url: Base URL of the server.
            session: Shared aiohttp session.
        """
        self.name = name
        self._server_url = server_url.rstrip("/")
        self._session = session
        self._tools: List[str] = []
        self.logger = logging.getLogger(__name__)

    async def configure(self, app: Any = None) -> None:  # noqa: ARG002
        """No-op configure for server proxy.

        Args:
            app: Unused application context.
        """

    async def ask(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        output_mode: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Proxy an ask() call to the server.

        Args:
            question: The user's question.
            session_id: Optional session ID for conversation continuity.
            user_id: Optional user ID.
            output_mode: Output mode (passed as string to server).
            **kwargs: Additional keyword arguments.

        Returns:
            A dict-like object with an ``output`` attribute populated from
            the server response JSON.

        Raises:
            AgentLoadError: On HTTP errors or connection failure.
        """
        url = f"{self._server_url}/api/agent/{quote(self.name, safe='')}/ask"
        payload: Dict[str, Any] = {
            "question": question,
            "session_id": session_id or "",
            "user_id": user_id or "cli-user",
        }
        try:
            async with self._session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                # Return a simple namespace so callers can do response.output
                return _ServerResponse(data)
        except aiohttp.ClientError as exc:
            raise AgentLoadError(
                self.name,
                message=f"Server request failed: {exc}",
            ) from exc

    async def ask_stream(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        output_mode: Any = None,
        **kwargs: Any,
    ):
        """Proxy a streaming ask_stream() call to the server.

        Falls back to a single-chunk async generator from the server response
        when the server does not support SSE streaming.

        Args:
            question: The user's question.
            session_id: Optional session ID.
            user_id: Optional user ID.
            output_mode: Output mode.
            **kwargs: Additional keyword arguments.

        Yields:
            Text chunks from the server response.
        """
        response = await self.ask(
            question,
            session_id=session_id,
            user_id=user_id,
            output_mode=output_mode,
        )
        output = response.output or ""
        if isinstance(output, str):
            # Simulate chunked streaming for server responses
            chunk_size = 50
            for i in range(0, len(output), chunk_size):
                yield output[i : i + chunk_size]
                await asyncio.sleep(0)
        else:
            yield str(output)

    def get_available_tools(self) -> List[str]:
        """Return cached list of tool names.

        Returns:
            List of tool name strings.
        """
        return self._tools

    def get_tools_count(self) -> int:
        """Return the number of available tools.

        Returns:
            Count of tools.
        """
        return len(self._tools)

    def has_tools(self) -> bool:
        """Return True if any tools are available.

        Returns:
            Whether tools are registered.
        """
        return bool(self._tools)


class _ServerResponse:
    """Lightweight wrapper for server JSON responses.

    Attributes:
        output: The response text output.
        tool_calls: Empty list (server responses don't include tool calls in v1).
        usage: None usage stats.
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        """Initialise from parsed JSON data.

        Args:
            data: Parsed response dictionary from the server.
        """
        self.output: str = data.get("output") or data.get("response") or ""
        self.response: Optional[str] = data.get("response")
        self.tool_calls: List[Any] = []
        self.usage: Any = None
        self._data = data

    def __repr__(self) -> str:
        """Return string representation."""
        return f"_ServerResponse(output={self.output!r})"


class ServerAgentProxy:
    """Proxy agent interactions to a running AI-Parrot server via HTTP.

    Lists available agents from the server registry and proxies ``ask()``
    calls through the server REST API.

    Attributes:
        server_url: Base URL of the running server.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        server_url: str,
        timeout: int = 30,
    ) -> None:
        """Initialise the server proxy.

        Args:
            server_url: Base URL of the running AI-Parrot server
                        (e.g. ``http://localhost:8080``).
            timeout: Request timeout in seconds.
        """
        self.server_url = server_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)

    def _get_session(self) -> aiohttp.ClientSession:
        """Return (or create) the shared aiohttp session.

        Returns:
            The shared ``aiohttp.ClientSession``.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def load(self, name: str) -> _ServerBotProxy:
        """Create a proxy bot for the named agent on the server.

        Verifies the agent exists by hitting the server's agent info endpoint.

        Args:
            name: Agent name as registered on the server.

        Returns:
            A ``_ServerBotProxy`` that proxies calls to the server.

        Raises:
            AgentLoadError: If the server is unreachable or agent not found.
        """
        session = self._get_session()
        url = f"{self.server_url}/api/agent/{name}"
        try:
            async with session.get(url) as resp:
                if resp.status == 404:
                    raise AgentLoadError(name, message=f"Agent '{name}' not found on server.")
                resp.raise_for_status()
        except aiohttp.ClientConnectorError as exc:
            raise AgentLoadError(
                name,
                message=(
                    f"Cannot connect to server at {self.server_url}. "
                    f"Is it running? ({exc})"
                ),
            ) from exc
        except aiohttp.ClientError as exc:
            raise AgentLoadError(
                name, message=f"Server error: {exc}"
            ) from exc
        return _ServerBotProxy(name, self.server_url, session)

    async def list_agents(self) -> List[Dict[str, Any]]:
        """Fetch the list of agents from the server registry.

        Returns:
            List of agent metadata dicts from the server.

        Raises:
            AgentLoadError: If the server is unreachable.
        """
        session = self._get_session()
        url = f"{self.server_url}/api/agents"
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientConnectorError as exc:
            raise AgentLoadError(
                "",
                message=(
                    f"Cannot connect to server at {self.server_url}. "
                    f"Is it running? ({exc})"
                ),
            ) from exc
        except aiohttp.ClientError as exc:
            raise AgentLoadError("", message=f"Server error: {exc}") from exc

    async def select_agent(self) -> str:
        """Present an interactive agent picker from the server's agent list.

        Returns:
            The selected agent name.

        Raises:
            AgentLoadError: If the server is unreachable or no agents found.
        """
        agents = await self.list_agents()
        if not agents:
            raise AgentLoadError("", message="No agents found on server.")
        names = [a.get("name", str(a)) for a in agents]
        selected = await questionary.select(
            "Select an agent to start:",
            choices=names,
        ).ask_async()
        if selected is None:
            raise AgentLoadError("", message="No agent selected.")
        return selected

    async def close(self) -> None:
        """Close the underlying HTTP session.

        Should be called when the proxy is no longer needed.
        """
        if self._session and not self._session.closed:
            await self._session.close()
            self.logger.debug("HTTP session closed")
