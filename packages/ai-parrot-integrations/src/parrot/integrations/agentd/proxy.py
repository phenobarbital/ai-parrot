"""DaemonAgentProxy + daemon slash commands for AgentREPL.

Implements Module 7 of ``sdd/specs/agent-cli-daemon.spec.md``. The Rich
console is the EXISTING ``parrot.cli.repl.AgentREPL`` — this module
supplies a third loader strategy (daemon over UDS), mirroring
``parrot.cli.loaders.ServerAgentProxy``/``_ServerBotProxy`` EXACTLY so
``AgentREPL`` sees an interchangeable loader, plus daemon-only slash
commands (``/status``, ``/schedules``, ``/invoke``) and a queued
job-event display drained between conversation turns.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from .client import AgentDaemonClient, RpcRemoteError, resolve_socket
from .protocol import (
    METHOD_EVENT_JOB_ERROR,
    METHOD_EVENT_JOB_EXECUTED,
    METHOD_EVENT_SHUTDOWN,
)

if TYPE_CHECKING:
    from parrot.cli.repl import AgentREPL

__all__ = [
    "DaemonAgentProxy",
    "register_daemon_commands",
]

#: Bounded queue length for job-event lines awaiting `drain_events()`.
_EVENT_QUEUE_MAXLEN = 512


class _DaemonResponse:
    """Lightweight wrapper for `chat.send` (non-stream) RPC results.

    Mirrors `parrot.cli.loaders._ServerResponse`'s shape.

    Attributes:
        output: The response text output.
        response: Alias for `output` (mirrors `_ServerResponse`).
        tool_calls: Empty list (not surfaced by agentd v1).
        usage: `None` (not surfaced by agentd v1).
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self.output: str = data.get("output") or ""
        self.response: str | None = data.get("output")
        self.tool_calls: list[Any] = []
        self.usage: Any = None
        self._data = data

    def __repr__(self) -> str:
        return f"_DaemonResponse(output={self.output!r})"


class _DaemonBotProxy:
    """Thin UDS proxy satisfying the same duck type as `_ServerBotProxy`.

    Only implements the subset `AgentREPL` uses: `ask()`, `ask_stream()`,
    `get_available_tools()`, `get_tools_count()`, `has_tools()`,
    `configure()` — signatures mirror `_ServerBotProxy` exactly so the two
    loader strategies are interchangeable.

    Attributes:
        name: Agent name.
        _client: The shared `AgentDaemonClient`.
        _tools: Cached list of tool names (populated once via
            `_ensure_tools()`).
    """

    def __init__(self, name: str, client: AgentDaemonClient) -> None:
        self.name = name
        self._client = client
        self._tools: list[str] = []
        self._tools_fetched = False
        self.logger = logging.getLogger(__name__)

    async def configure(self, app: Any = None) -> None:
        """No-op -- the daemon's agent is already configured server-side."""

    async def ask(
        self,
        question: str,
        session_id: str | None = None,
        user_id: str | None = None,
        output_mode: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Proxy a one-shot `ask()` call to the daemon via `chat.send`.

        Args:
            question: The user's question.
            session_id: Unused -- the daemon assigns one session per
                connection (spec §2); kept for signature parity.
            user_id: Unused; kept for signature parity.
            output_mode: Unused; kept for signature parity.
            **kwargs: Passed through as `chat.send` metadata.

        Returns:
            A `_DaemonResponse` with an `.output` attribute.
        """
        result = await self._client.call(
            "chat.send", prompt=question, stream=False, metadata=kwargs
        )
        return _DaemonResponse(result)

    async def ask_stream(
        self,
        question: str,
        session_id: str | None = None,
        user_id: str | None = None,
        output_mode: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Proxy a streaming `ask_stream()` call via `chat.send(stream=true)`.

        Args:
            question: The user's question.
            session_id: Unused; kept for signature parity.
            user_id: Unused; kept for signature parity.
            output_mode: Unused; kept for signature parity.
            **kwargs: Passed through as `chat.send` metadata.

        Yields:
            Text chunks (`chat.delta` payloads). Terminates on
            `chat.complete` or `chat.error` (an error is logged, not
            raised, to match `_ServerBotProxy.ask_stream`'s never-raises
            contract).
        """
        async for event in self._client.stream(question, **kwargs):
            if event.kind == "delta":
                yield event.text or ""
            elif event.kind == "error":
                self.logger.warning("agentd stream error: %s", event.error)
                return
            # "complete" -> nothing to yield; the loop ends naturally.

    async def _ensure_tools(self) -> None:
        """Fetch and cache the tool list once, via `tools.list`."""
        if self._tools_fetched:
            return
        result = await self._client.call("tools.list")
        self._tools = list(result.get("tools", []))
        self._tools_fetched = True

    def get_available_tools(self) -> list[str]:
        """Return the cached list of tool names."""
        return self._tools

    def get_tools_count(self) -> int:
        """Return the cached tool count."""
        return len(self._tools)

    def has_tools(self) -> bool:
        """Return whether any tools are cached."""
        return bool(self._tools)


def _format_event(method: str, params: dict[str, Any]) -> str:
    """Format one `event.*` notification into a human-readable console line."""
    job_id = params.get("job_id", "?")
    if method == METHOD_EVENT_JOB_EXECUTED:
        return f"⏱ job {job_id} ejecutado ✓"
    if method == METHOD_EVENT_JOB_ERROR:
        error = params.get("error", "")
        return f"⏱ job {job_id} error ✗ ({error})"
    if method == METHOD_EVENT_SHUTDOWN:
        return "⏹ daemon shutting down"
    return f"⏱ event {method}: {params}"


class DaemonAgentProxy:
    """Loader strategy: proxy agent interactions to a running agentd daemon.

    Mirrors `ServerAgentProxy`'s shape (`load`/`list_agents`/`close`) but
    talks JSON-RPC over a Unix domain socket instead of HTTP.

    Attributes:
        name_or_socket: Service name or explicit socket path (resolved via
            `resolve_socket()`).
    """

    def __init__(self, name_or_socket: str) -> None:
        self.name_or_socket = name_or_socket
        self._client: AgentDaemonClient | None = None
        self._events: deque[str] = deque(maxlen=_EVENT_QUEUE_MAXLEN)
        self.logger = logging.getLogger(__name__)

    async def load(self, name: str) -> _DaemonBotProxy:
        """Connect to the daemon and return a proxy bot for `name`.

        Args:
            name: Agent name (used only for display -- the daemon serves
                exactly one agent, per spec §1 "1 daemon = 1 agent").

        Returns:
            A `_DaemonBotProxy`, with its tool list already cached.
        """
        socket_path = resolve_socket(self.name_or_socket)
        self._client = await AgentDaemonClient.connect(socket_path)
        await self._client.subscribe_events(self._on_event)

        proxy = _DaemonBotProxy(name, self._client)
        await proxy._ensure_tools()
        return proxy

    async def list_agents(self) -> list[dict[str, Any]]:
        """Return the single agent this daemon serves, via `agent.info`.

        Returns:
            A one-element list with the daemon's `agent.info` payload.

        Raises:
            RuntimeError: If called before `load()`.
        """
        if self._client is None:
            raise RuntimeError("DaemonAgentProxy.load() must be called first")
        info = await self._client.call("agent.info")
        return [info]

    async def close(self) -> None:
        """Close the underlying daemon connection."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _on_event(self, method: str, params: dict[str, Any]) -> None:
        """Format and enqueue one `event.*` notification for later drain."""
        self._events.append(_format_event(method, params))

    def drain_events(self) -> list[str]:
        """Return and clear all queued, formatted job-event lines.

        Meant to be called between conversation turns only (never
        mid-stream) -- the drain point is orchestrated by the `attach`
        command wiring (TASK-2216).

        Returns:
            The queued lines, in arrival order. The queue is empty
            afterwards.
        """
        lines = list(self._events)
        self._events.clear()
        return lines


# --------------------------------------------------------------------------
# Daemon-only slash commands
# --------------------------------------------------------------------------


async def _cmd_status(repl: AgentREPL, proxy: DaemonAgentProxy) -> None:
    """Handle `/status` -- pretty-print `daemon.status`."""
    if proxy._client is None:
        repl.renderer.print("[red]Not connected to a daemon.[/red]")
        return
    try:
        status = await proxy._client.call("daemon.status")
    except RpcRemoteError as exc:
        repl.renderer.render_error(exc)
        return

    scheduler = status.get("scheduler", {})
    repl.renderer.render_info(
        [
            ("PID", str(status.get("pid"))),
            ("Uptime (s)", f"{status.get('uptime_s', 0):.1f}"),
            ("Version", str(status.get("version"))),
            ("Scheduler available", str(scheduler.get("available"))),
            ("Scheduler running", str(scheduler.get("running"))),
            ("Scheduled jobs", str(scheduler.get("jobs"))),
            ("Active connections", str(status.get("active_connections"))),
        ]
    )


async def _cmd_schedules(repl: AgentREPL, proxy: DaemonAgentProxy, args: str) -> None:
    """Handle `/schedules [list|add|pause|resume|remove ...]`."""
    if proxy._client is None:
        repl.renderer.print("[red]Not connected to a daemon.[/red]")
        return

    parts = args.split(maxsplit=1)
    sub = parts[0].lower() if parts else "list"
    rest = parts[1] if len(parts) > 1 else ""

    try:
        if sub == "list":
            jobs = await proxy._client.call("schedules.list")
            if not jobs:
                repl.renderer.print("[dim]No schedules registered.[/dim]")
                return
            rows = [
                [
                    str(job.get("schedule_id", "")),
                    str(job.get("agent_name", "")),
                    str(job.get("source", "")),
                    str(job.get("job", {}).get("next_run", "")),
                ]
                for job in jobs
            ]
            repl.renderer.render_table(
                headers=["ID", "Agent", "Source", "Next Run"],
                rows=rows,
                title="Schedules",
            )
        elif sub == "pause":
            result = await proxy._client.call("schedules.pause", schedule_id=rest.strip())
            repl.renderer.print(f"[green]Paused:[/green] {result}")
        elif sub == "resume":
            result = await proxy._client.call("schedules.resume", schedule_id=rest.strip())
            repl.renderer.print(f"[green]Resumed:[/green] {result}")
        elif sub == "remove":
            result = await proxy._client.call("schedules.remove", schedule_id=rest.strip())
            repl.renderer.print(f"[green]Removed:[/green] {result}")
        elif sub == "add":
            try:
                payload = json.loads(rest) if rest.strip() else {}
            except json.JSONDecodeError as exc:
                repl.renderer.print(f"[red]Invalid JSON for /schedules add: {exc}[/red]")
                return
            result = await proxy._client.call("schedules.add", **payload)
            repl.renderer.print(f"[green]Added:[/green] {result}")
        else:
            repl.renderer.print(
                f"[yellow]Unknown /schedules subcommand: {sub}[/yellow] "
                "(use list|add|pause|resume|remove)"
            )
    except RpcRemoteError as exc:
        repl.renderer.render_error(exc)


async def _cmd_invoke(repl: AgentREPL, proxy: DaemonAgentProxy, args: str) -> None:
    """Handle `/invoke <method> [json-kwargs]`."""
    if proxy._client is None:
        repl.renderer.print("[red]Not connected to a daemon.[/red]")
        return

    parts = args.split(maxsplit=1)
    if not parts:
        repl.renderer.print("[yellow]Usage: /invoke <method> [json-kwargs][/yellow]")
        return

    method = parts[0]
    raw_kwargs = parts[1] if len(parts) > 1 else ""
    kwargs: dict[str, Any] = {}
    if raw_kwargs.strip():
        try:
            kwargs = json.loads(raw_kwargs)
        except json.JSONDecodeError as exc:
            repl.renderer.print(f"[red]Invalid JSON kwargs for /invoke: {exc}[/red]")
            return
        if not isinstance(kwargs, dict):
            repl.renderer.print("[red]/invoke kwargs must be a JSON object.[/red]")
            return

    try:
        result = await proxy._client.call(
            "agent.invoke", params={"method": method, "kwargs": kwargs}
        )
    except RpcRemoteError as exc:
        repl.renderer.render_error(exc)
        return

    repl.renderer.print(f"[cyan]{method}[/cyan] -> {result}")


def register_daemon_commands(repl: AgentREPL, proxy: DaemonAgentProxy) -> None:
    """Register `/status`, `/schedules`, `/invoke` onto an `AgentREPL`.

    Args:
        repl: The REPL instance to register commands on.
        proxy: The `DaemonAgentProxy` backing this REPL session -- its
            `AgentDaemonClient` is what the handlers call.
    """
    from parrot.cli.commands import SlashCommand

    async def _status(repl: AgentREPL, args: str) -> None:
        await _cmd_status(repl, proxy)

    async def _schedules(repl: AgentREPL, args: str) -> None:
        await _cmd_schedules(repl, proxy, args)

    async def _invoke(repl: AgentREPL, args: str) -> None:
        await _cmd_invoke(repl, proxy, args)

    repl.register_command(SlashCommand("status", "Show daemon status.", _status))
    repl.register_command(
        SlashCommand(
            "schedules",
            "Manage schedules: /schedules [list|add|pause|resume|remove ...]",
            _schedules,
        )
    )
    repl.register_command(
        SlashCommand(
            "invoke",
            "Invoke an agent method: /invoke <method> [json-kwargs]",
            _invoke,
        )
    )
