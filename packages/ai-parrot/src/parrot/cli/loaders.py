"""Agent loading strategies for the AI-Parrot CLI REPL.

Provides two loading strategies:

- ``StandaloneAgentLoader`` — loads agents from the in-process
  ``AgentRegistry`` without requiring a running server.
- ``ServerAgentProxy`` — proxies agent interactions to a running
  AI-Parrot server via HTTP.
"""

import difflib
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import quote

import aiohttp
import questionary

from parrot.bots.abstract import AbstractBot
from parrot.registry import agent_registry
from parrot.registry.registry import BotMetadata
from parrot.utils.tty import restore_stdin_blocking
from parrot.cli.events import BackendCapabilities, ToolFailed, ToolFinished, ToolStarted


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


async def _iter_sse(resp: aiohttp.ClientResponse) -> AsyncIterator[str]:
    """Yield the payload of each Server-Sent Event in ``resp``.

    Joins consecutive ``data:`` lines until a blank line terminates the event.
    ``error:`` lines are yielded prefixed with ``"error:"`` so the caller can
    raise. Comment lines (``:``) and unknown fields are ignored.

    Args:
        resp: An open ``aiohttp.ClientResponse`` with ``text/event-stream`` body.

    Yields:
        The concatenated ``data:`` payload of one event (without the prefix).
    """
    buffer: List[str] = []
    async for raw in resp.content:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if buffer:
                yield "\n".join(buffer)
                buffer = []
            continue
        if line.startswith("data:"):
            buffer.append(line[5:].lstrip())
        elif line.startswith("error:"):
            yield "error:" + line[6:].strip()
        # Comment lines (":") and any other SSE field ("event:", "id:", "retry:")
        # are outside the grammar this server emits (stream.py:90-106); ignore them.
    if buffer:
        yield "\n".join(buffer)


class StandaloneAgentLoader:
    """Load agents from the in-process AgentRegistry.

    Uses ``AgentRegistry.get_instance()`` with fuzzy name matching fallback
    and an interactive ``questionary.select()`` picker when no name is given.

    On first use, runs the full discovery pipeline (module imports, YAML
    config, YAML definitions) so that decorator-registered and
    config-registered agents are available even without a running server.

    Attributes:
        logger: Module-level logger.
    """

    def __init__(self) -> None:
        """Initialise the standalone loader."""
        self.logger = logging.getLogger(__name__)
        self._discovered = False

    async def _ensure_discovered(self) -> None:
        """Run the registry discovery pipeline once.

        Mirrors the three-step sequence from
        ``BotManager.load_bots()`` so that CLI-launched agents
        have the same visibility as server-launched ones:

        1. ``load_modules()`` — import ``*.py`` files from every
           discovery directory, triggering ``@register_agent`` decorators.
        2. ``discover_config_agents()`` — register agents declared in
           ``agents.yaml``.
        3. ``load_agent_definitions()`` — register agents from YAML
           definition files in ``agents/agents/``.
        """
        if self._discovered:
            return
        self._discovered = True

        # Step 1: decorator-based discovery (imports *.py)
        imported = await agent_registry.load_modules()
        self.logger.debug("Discovery: imported %d module(s)", imported)

        # Step 2: agents.yaml config entries
        config_count = agent_registry.discover_config_agents()
        self.logger.debug("Discovery: %d agent(s) from config", config_count)

        # Step 3: YAML agent definition files (agents/agents/*.yaml)
        definitions_dir = agent_registry.agents_dir / "agents"
        if definitions_dir.is_dir():
            def_count = agent_registry.load_agent_definitions(definitions_dir)
            self.logger.debug("Discovery: %d agent(s) from YAML definitions", def_count)

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
        await self._ensure_discovered()
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
        await self._ensure_discovered()
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
        await self._ensure_discovered()
        agents = list(agent_registry._registered_agents.keys())
        if not agents:
            raise AgentLoadError(
                "",
                message="No agents are registered. Check your agents directory.",
            )
        with restore_stdin_blocking():
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
        capabilities: Static backend capabilities read by ``TurnRunner``.
    """

    capabilities: BackendCapabilities = BackendCapabilities(
        streaming=True, live_tool_events=True, usage=True, resume=False
    )

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
        """Proxy an ask() call to the server's AgentTalk endpoint.

        Args:
            question: The user's question.
            session_id: Optional session ID for conversation continuity.
            user_id: Unused -- identity comes only from the bearer token (Q8);
                kept for signature parity with ``DaemonAgentProxy``.
            output_mode: Output mode (unused by the JSON ask route).
            **kwargs: Additional keyword arguments (unused).

        Returns:
            A ``_ServerResponse`` with an ``output`` attribute populated from
            the server response JSON.

        Raises:
            AgentLoadError: On HTTP errors or connection failure.
        """
        url = f"{self._server_url}/api/v1/agents/chat/{quote(self.name, safe='')}"
        payload: Dict[str, Any] = {
            "query": question,
            "session_id": session_id or "",
            "stream": False,
        }
        # Q8: identity comes from the bearer token only -- never send user_id.
        try:
            async with self._session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
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
        """Proxy a streaming ask_stream() call to the server's SSE endpoint.

        Consumes ``StreamHandler.stream_sse`` frames: plain ``content``
        deltas are yielded as ``str``, ``tool_event`` frames are mapped to
        ``ToolStarted``/``ToolFinished``/``ToolFailed``, and the terminal
        ``ai_message`` frame becomes the final ``_ServerResponse``. Tolerates
        a server without ``tool_event`` frames (older server, spec AC7).

        Args:
            question: The user's question.
            session_id: Optional session ID.
            user_id: Unused -- identity comes only from the bearer token (Q8);
                kept for signature parity with ``DaemonAgentProxy``.
            output_mode: Unused; kept for signature parity.
            **kwargs: Additional keyword arguments (unused).

        Yields:
            ``str`` text deltas, ``ToolStarted``/``ToolFinished``/``ToolFailed``
            events, and finally a ``_ServerResponse`` with ``tool_calls``/``usage``.

        Raises:
            AgentLoadError: On HTTP errors, connection failure, or an
                ``error:`` SSE line from the server.
        """
        url = f"{self._server_url}/bots/{quote(self.name, safe='')}/stream/sse"
        payload: Dict[str, Any] = {"prompt": question, "session_id": session_id or ""}
        final: Optional[_ServerResponse] = None
        try:
            async with self._session.post(url, json=payload) as resp:
                resp.raise_for_status()
                async for event in _iter_sse(resp):
                    if event.startswith("error:"):
                        raise AgentLoadError(self.name, message=f"Server stream error: {event[6:]}")
                    if event == "[DONE]":
                        break
                    frame = json.loads(event)
                    if "content" in frame and "type" not in frame:
                        yield frame["content"]
                    elif frame.get("type") == "tool_event":
                        yield _tool_event_from_frame(frame.get("data") or {})
                    elif frame.get("type") == "ai_message":
                        final = _ServerResponse(frame.get("data") or {})
                    else:
                        # Unknown/older-server frame type: log and skip (AC7).
                        self.logger.debug("Ignoring unknown SSE frame type: %r", frame.get("type"))
        except aiohttp.ClientError as exc:
            raise AgentLoadError(
                self.name,
                message=f"Server request failed: {exc}",
            ) from exc
        if final is not None:
            yield final

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


def _tool_event_from_frame(data: Dict[str, Any]) -> "ToolStarted | ToolFinished | ToolFailed":
    """Map one ``tool_event`` frame payload to its typed TurnEvent.

    Args:
        data: The ``data`` object of a ``{"type": "tool_event", ...}`` frame
            (``event`` is ``"started"`` | ``"finished"`` | ``"failed"``).

    Returns:
        ``ToolStarted``, ``ToolFinished`` or ``ToolFailed``.

    Raises:
        ValueError: On an unknown ``event`` value.
    """
    common = {
        "turn_id": data.get("turn_id", ""),
        "seq": int(data.get("seq", 0)),
        "call_id": data["call_id"],
        "tool_name": data["tool_name"],
    }
    kind = data.get("event")
    if kind == "started":
        return ToolStarted(kind="tool_started", args_summary=data.get("args_summary") or {}, **common)
    if kind == "finished":
        return ToolFinished(
            kind="tool_finished",
            duration_ms=float(data.get("duration_ms", 0.0)),
            result_status=data.get("result_status", ""),
            result_size_bytes=int(data.get("result_size_bytes", 0)),
            **common,
        )
    if kind == "failed":
        return ToolFailed(
            kind="tool_failed",
            duration_ms=float(data.get("duration_ms", 0.0)),
            error_type=data.get("error_type", ""),
            error_message=data.get("error_message", ""),
            **common,
        )
    raise ValueError(f"unknown tool_event kind: {kind!r}")


class _DictObj:
    """Attribute-access wrapper over a plain dict, tolerant of missing keys.

    Used to adapt ``ai_message`` frame dicts (``AIMessage.to_dict()`` is
    ``model_dump()``) to the attribute-style reads performed by
    ``ResponseRenderer._render_tool_calls``/``_render_usage``
    (``tc.name``, ``usage.prompt_tokens``, etc.).

    Args:
        d: The source dictionary; its items become instance attributes.
    """

    def __init__(self, d: Dict[str, Any]) -> None:
        """Copy ``d``'s items onto ``self.__dict__``."""
        self.__dict__.update(d)

    def __getattr__(self, name: str) -> Any:
        """Return ``None`` for any attribute not present in the source dict."""
        return None


class _ServerResponse:
    """Lightweight wrapper for server JSON responses.

    Attributes:
        output: The response text output.
        tool_calls: List of ``_DictObj`` tool-call wrappers (from ``ai_message``).
        usage: ``_DictObj`` usage wrapper, or ``None`` when absent.
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        """Initialise from parsed JSON data.

        Args:
            data: Parsed response dictionary from the server.
        """
        self.output: str = data.get("output") or data.get("response") or ""
        self.response: Optional[str] = data.get("response")
        self.tool_calls: List[Any] = [_DictObj(tc) for tc in (data.get("tool_calls") or [])]
        self.usage: Any = _DictObj(data["usage"]) if isinstance(data.get("usage"), dict) else None
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
        *,
        token: Optional[str] = None,
    ) -> None:
        """Initialise the server proxy.

        Args:
            server_url: Base URL of the running AI-Parrot server
                        (e.g. ``http://localhost:8080``).
            timeout: Request timeout in seconds.
            token: Optional bearer token sent as ``Authorization: Bearer <token>``
                on every request.
        """
        self.server_url = server_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._token = token
        self._session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)

    def _get_session(self) -> aiohttp.ClientSession:
        """Return (or create) the shared aiohttp session.

        Returns:
            The shared ``aiohttp.ClientSession``.
        """
        if self._session is None or self._session.closed:
            headers = {"Authorization": f"Bearer {self._token}"} if self._token else None
            self._session = aiohttp.ClientSession(timeout=self.timeout, headers=headers)
        return self._session

    async def load(self, name: str) -> _ServerBotProxy:
        """Create a proxy bot for the named agent on the server.

        Verifies the agent exists by hitting the server's chatbot info endpoint.

        Args:
            name: Agent name as registered on the server.

        Returns:
            A ``_ServerBotProxy`` that proxies calls to the server.

        Raises:
            AgentLoadError: If the server is unreachable or agent not found.
        """
        session = self._get_session()
        url = f"{self.server_url}/api/v1/chatbots/{quote(name, safe='')}"
        try:
            async with session.get(url) as resp:
                if resp.status == 404:
                    raise AgentLoadError(name, message=f"Agent '{name}' not found on server.")
                resp.raise_for_status()
        except aiohttp.ClientConnectorError as exc:
            raise AgentLoadError(
                name,
                message=(f"Cannot connect to server at {self.server_url}. " f"Is it running? ({exc})"),
            ) from exc
        except aiohttp.ClientError as exc:
            raise AgentLoadError(name, message=f"Server error: {exc}") from exc
        return _ServerBotProxy(name, self.server_url, session)

    async def list_agents(self) -> List[Dict[str, Any]]:
        """Fetch the list of agents from the server registry.

        Returns:
            List of agent metadata dicts from the server's
            ``{"agents": [...], "total": N}`` payload (Q11).

        Raises:
            AgentLoadError: If the server is unreachable.
        """
        session = self._get_session()
        url = f"{self.server_url}/api/v1/bots"
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                payload = await resp.json()
                return payload.get("agents", []) if isinstance(payload, dict) else list(payload)
        except aiohttp.ClientConnectorError as exc:
            raise AgentLoadError(
                "",
                message=(f"Cannot connect to server at {self.server_url}. " f"Is it running? ({exc})"),
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
        with restore_stdin_blocking():
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
