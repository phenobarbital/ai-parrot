"""AgentDaemon — lifecycle, RPC handlers, SingleAgentManager, sd_notify.

Implements Module 5 of ``sdd/specs/agent-cli-daemon.spec.md``: the daemon
itself. Binds one agent (``resolve_agent()``, TASK-2210) + an optional
headless scheduler (``AgentSchedulerManager.start_headless()``,
TASK-2209, lazily imported from ai-parrot-server) + the UDS server
(``JsonRpcUnixServer``, TASK-2211) into one foreground process
implementing the full RPC surface and the 6-step lifecycle of spec §2
"Daemon lifecycle".
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import signal
import socket
import sys
import time
import uuid
from typing import Any

from .config import AgentServiceConfig, default_socket_path, resolve_agent
from .protocol import (
    METHOD_AGENT_INFO,
    METHOD_AGENT_INVOKE,
    METHOD_CHAT_COMPLETE,
    METHOD_CHAT_DELTA,
    METHOD_CHAT_ERROR,
    METHOD_CHAT_SEND,
    METHOD_DAEMON_SHUTDOWN,
    METHOD_DAEMON_STATUS,
    METHOD_EVENT_JOB_ERROR,
    METHOD_EVENT_JOB_EXECUTED,
    METHOD_EVENT_SHUTDOWN,
    METHOD_EVENTS_SUBSCRIBE,
    METHOD_EVENTS_UNSUBSCRIBE,
    METHOD_SCHEDULES_ADD,
    METHOD_SCHEDULES_LIST,
    METHOD_SCHEDULES_PAUSE,
    METHOD_SCHEDULES_REMOVE,
    METHOD_SCHEDULES_RESUME,
    METHOD_TOOLS_LIST,
    SCHEDULE_NOT_FOUND,
    SCHEDULER_UNAVAILABLE,
    UNKNOWN_AGENT_METHOD,
)
from .server import Handler, JsonRpcUnixServer, RpcHandlerError, Session

__all__ = [
    "AgentDaemon",
    "SingleAgentManager",
    "sd_notify",
]


def sd_notify(state: str) -> None:
    """Send a systemd `sd_notify` datagram, if `NOTIFY_SOCKET` is set.

    Hand-rolled (no dependency on the `sdnotify` PyPI package, per spec
    §7). No-op when `NOTIFY_SOCKET` is unset (e.g. `Type=simple` /
    supervisord, or a plain terminal run).

    Args:
        state: The state string to send (e.g. `"READY=1"`, `"STOPPING=1"`).
    """
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return

    if address.startswith("@"):
        address = "\0" + address[1:]  # Linux abstract namespace socket.

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(address)
        sock.sendall(state.encode("utf-8"))
    except OSError:
        pass  # Best-effort notification; never fail the daemon over this.
    finally:
        sock.close()


def _serialize_for_rpc(value: Any) -> Any:
    """Best-effort JSON-serializable conversion for RPC results.

    Mirrors `AgentSchedulerManager._format_result()`'s fallback chain
    (`model_dump` -> `to_dict`/`dict` -> JSON-compatible -> `str`), but
    keeps structured data (dict/list) intact instead of stringifying it,
    since RPC results should stay structured whenever possible.

    Args:
        value: The value to convert.

    Returns:
        A JSON-serializable representation of `value`.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _serialize_for_rpc(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_for_rpc(v) for v in value]
    if hasattr(value, "model_dump"):
        with contextlib.suppress(Exception):
            return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        with contextlib.suppress(Exception):
            return value.to_dict()
    if hasattr(value, "dict"):
        with contextlib.suppress(Exception):
            return value.dict()
    try:
        import json

        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _agent_response_to_rpc(response: Any) -> dict[str, Any]:
    """Convert an agent's `ask()` response into the minimal RPC shape.

    Args:
        response: Whatever `agent.ask()` returned.

    Returns:
        `{"output": str, "metadata": dict}` -- `metadata` is the response's
        `model_dump()`/`to_dict()` when available, else empty.
    """
    metadata: dict[str, Any] = {}
    if hasattr(response, "model_dump"):
        with contextlib.suppress(Exception):
            metadata = response.model_dump(mode="json")
    elif hasattr(response, "to_dict"):
        with contextlib.suppress(Exception):
            metadata = response.to_dict()
    return {"output": str(response), "metadata": metadata}


class SingleAgentManager:
    """Minimal `bot_manager` contract for `AgentSchedulerManager`.

    Exposes exactly the surface `AgentSchedulerManager._execute_agent_job`
    touches: `_bots` (dict), `registry.get_instance(name)`, and
    `get_crew(name)` (always `None` -- agentd v1 is single-agent, no crew
    support; multi-agent/crew orchestration is covered by the aiohttp
    server, per spec §1 Non-Goals).
    """

    class _Registry:
        """Minimal stand-in for `BotManager.registry`."""

        def __init__(self, bots: dict[str, Any]) -> None:
            self._bots = bots

        async def get_instance(self, name: str) -> Any:
            """Return the single registered agent by name.

            Raises:
                ValueError: If `name` does not match the registered agent.
            """
            agent = self._bots.get(name)
            if agent is None:
                raise ValueError(f"Agent {name!r} not found")
            return agent

    def __init__(self, agent: Any, name: str) -> None:
        self._bots: dict[str, Any] = {name: agent}
        self.registry = SingleAgentManager._Registry(self._bots)

    def get_crew(self, name: str) -> None:
        """Always return `None` -- no crew support in agentd v1."""
        return


class AgentDaemon:
    """Foreground per-agent daemon (spec §2 "Daemon lifecycle").

    Loads exactly one agent, optionally boots `AgentSchedulerManager`
    headless (best-effort -- degrades with a warning if ai-parrot-server
    is not installed), and serves JSON-RPC 2.0 over a Unix domain socket
    until a shutdown signal (or `daemon.shutdown` RPC) is received.

    Attributes:
        config: The daemon's `AgentServiceConfig`.
        agent: The resolved agent instance (set once `run()` starts).
        server: The `JsonRpcUnixServer` instance (set once `run()` starts).
    """

    def __init__(self, config: AgentServiceConfig) -> None:
        self.config = config
        self.agent: Any = None
        self.server: JsonRpcUnixServer | None = None
        self._scheduler_manager: Any = None
        self._shutdown_event = asyncio.Event()
        self._start_time = time.monotonic()
        self.logger = logging.getLogger(__name__)

    async def run(self) -> None:
        """Run the daemon's full lifecycle (spec §2, steps 1-6).

        Returns once a graceful shutdown completes (SIGTERM/SIGINT or a
        `daemon.shutdown` RPC).
        """
        self._configure_logging()

        self.agent = await resolve_agent(self.config.agent)

        await self._start_scheduler()

        socket_path = self.config.socket or default_socket_path(self.config.name)
        self.server = JsonRpcUnixServer(
            socket_path, self._build_dispatch(), max_line_bytes=self.config.max_line_bytes
        )
        await self.server.start()

        self._start_time = time.monotonic()
        self.logger.info(
            "agentd ready: socket=%s agent=%s scheduler=%s",
            socket_path,
            self.config.name,
            "on" if self._scheduler_manager is not None else "off",
        )
        sd_notify("READY=1")

        await self._install_signal_handlers()
        await self._shutdown_event.wait()
        await self._shutdown()

    def _configure_logging(self) -> None:
        """Configure stdout logging (journald-friendly -- no own timestamp)."""
        logging.basicConfig(
            level=self.config.log_level,
            format="%(levelname)s %(name)s :: %(message)s",
            stream=sys.stdout,
        )

    async def _install_signal_handlers(self) -> None:
        """Register SIGTERM/SIGINT handlers that trigger graceful shutdown."""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, self._shutdown_event.set)

    async def _start_scheduler(self) -> None:
        """Best-effort headless scheduler bootstrap (spec §2, step 3).

        Skipped entirely when `config.scheduler.enabled` is False. When
        ai-parrot-server is not installed, logs a warning and continues
        without a scheduler -- `schedules.*` RPCs then return
        `SCHEDULER_UNAVAILABLE` (1003) instead of crashing the daemon.
        """
        if not self.config.scheduler.enabled:
            self.logger.info("Scheduler disabled by config; skipping.")
            return

        try:
            from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
            from parrot.scheduler.manager import AgentSchedulerManager
        except ImportError as exc:
            self.logger.warning(
                "ai-parrot-server (scheduler support) not installed; "
                "running without a scheduler (%s)",
                exc,
            )
            return

        single_agent_manager = SingleAgentManager(self.agent, self.config.name)
        manager = AgentSchedulerManager(bot_manager=single_agent_manager)
        await manager.start_headless(
            dsn=self.config.scheduler.dsn, use_redis=self.config.scheduler.redis
        )
        manager.register_bot_schedules(self.agent)
        manager.scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
        manager.scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
        self._scheduler_manager = manager

    def _on_job_executed(self, event: Any) -> None:
        """APScheduler listener (sync, per APScheduler's contract) -> fan-out."""
        if self.server is None:
            return
        asyncio.create_task(
            self.server.event_broker.publish(
                METHOD_EVENT_JOB_EXECUTED,
                {
                    "job_id": event.job_id,
                    "scheduled_run_time": str(getattr(event, "scheduled_run_time", "")),
                },
            )
        )

    def _on_job_error(self, event: Any) -> None:
        """APScheduler listener (sync, per APScheduler's contract) -> fan-out."""
        if self.server is None:
            return
        asyncio.create_task(
            self.server.event_broker.publish(
                METHOD_EVENT_JOB_ERROR,
                {
                    "job_id": event.job_id,
                    "error": str(getattr(event, "exception", "")),
                },
            )
        )

    async def _shutdown(self) -> None:
        """Graceful shutdown (spec §2, step 6), bounded by `shutdown_grace`."""
        self.logger.info("agentd shutting down...")

        if self.server is not None:
            with contextlib.suppress(Exception):
                await self.server.event_broker.publish(METHOD_EVENT_SHUTDOWN, {})

        if self._scheduler_manager is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    self._scheduler_manager.stop_headless(wait=True),
                    timeout=self.config.shutdown_grace,
                )

        cleanup = getattr(self.agent, "cleanup", None)
        if callable(cleanup):
            with contextlib.suppress(Exception):
                result = cleanup()
                if inspect.isawaitable(result):
                    await result

        if self.server is not None:
            await self.server.close()

        self.logger.info("agentd stopped.")

    # -- RPC dispatch table -------------------------------------------------

    def _build_dispatch(self) -> dict[str, Handler]:
        """Build the method -> handler mapping passed to `JsonRpcUnixServer`."""
        return {
            METHOD_CHAT_SEND: self._handle_chat_send,
            METHOD_AGENT_INFO: self._handle_agent_info,
            METHOD_TOOLS_LIST: self._handle_tools_list,
            METHOD_AGENT_INVOKE: self._handle_agent_invoke,
            METHOD_SCHEDULES_LIST: self._handle_schedules_list,
            METHOD_SCHEDULES_ADD: self._handle_schedules_add,
            METHOD_SCHEDULES_PAUSE: self._handle_schedules_pause,
            METHOD_SCHEDULES_RESUME: self._handle_schedules_resume,
            METHOD_SCHEDULES_REMOVE: self._handle_schedules_remove,
            METHOD_EVENTS_SUBSCRIBE: self._handle_events_subscribe,
            METHOD_EVENTS_UNSUBSCRIBE: self._handle_events_unsubscribe,
            METHOD_DAEMON_STATUS: self._handle_daemon_status,
            METHOD_DAEMON_SHUTDOWN: self._handle_daemon_shutdown,
        }

    async def _handle_chat_send(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `chat.send`: one-shot response, or ack + streamed deltas."""
        prompt = params.get("prompt", "")
        stream = bool(params.get("stream", False))
        metadata = params.get("metadata") or {}

        if not stream:
            response = await self.agent.ask(
                prompt, session_id=session.session_id, **metadata
            )
            return _agent_response_to_rpc(response)

        stream_id = uuid.uuid4().hex
        session.stream_ids.add(stream_id)
        task = asyncio.create_task(
            self._run_stream(session, stream_id, prompt, metadata)
        )
        session.tasks.add(task)
        task.add_done_callback(session.tasks.discard)
        return {"stream_id": stream_id}

    async def _run_stream(
        self, session: Session, stream_id: str, prompt: str, metadata: dict[str, Any]
    ) -> None:
        """Iterate `agent.ask_stream()`, emitting `chat.delta`/`chat.complete`."""
        accumulated: list[str] = []
        try:
            async for chunk in self.agent.ask_stream(
                prompt, session_id=session.session_id, **metadata
            ):
                text = str(chunk)
                accumulated.append(text)
                await session.notify(
                    METHOD_CHAT_DELTA, {"stream_id": stream_id, "text": text}
                )
            await session.notify(
                METHOD_CHAT_COMPLETE,
                {
                    "stream_id": stream_id,
                    "response": "".join(accumulated),
                    "usage": {},
                },
            )
        except Exception as exc:
            self.logger.exception(
                "Streaming chat.send failed for stream_id=%s", stream_id
            )
            with contextlib.suppress(Exception):
                await session.notify(
                    METHOD_CHAT_ERROR, {"stream_id": stream_id, "error": str(exc)}
                )
        finally:
            session.stream_ids.discard(stream_id)

    async def _handle_agent_info(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `agent.info`."""
        get_tools_count = getattr(self.agent, "get_tools_count", None)
        return {
            "name": getattr(self.agent, "name", self.config.name),
            "class": type(self.agent).__name__,
            "llm": str(getattr(self.agent, "llm", None)),
            "tools_count": get_tools_count() if callable(get_tools_count) else 0,
            "uptime_s": time.monotonic() - self._start_time,
        }

    async def _handle_tools_list(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `tools.list`."""
        get_tools = getattr(self.agent, "get_available_tools", None)
        tools = get_tools() if callable(get_tools) else []
        return {"tools": list(tools)}

    async def _handle_agent_invoke(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `agent.invoke`.

        Raises:
            RpcHandlerError: `UNKNOWN_AGENT_METHOD` for underscore-prefixed
                methods (always rejected), methods outside a non-empty
                `exposed_methods` allowlist, or methods that don't exist.
        """
        method_name = params.get("method")
        args = params.get("args") or []
        kwargs = params.get("kwargs") or {}

        if not method_name or method_name.startswith("_"):
            raise RpcHandlerError(
                UNKNOWN_AGENT_METHOD, f"Method not allowed: {method_name!r}"
            )

        if (
            self.config.exposed_methods
            and method_name not in self.config.exposed_methods
        ):
            raise RpcHandlerError(
                UNKNOWN_AGENT_METHOD, f"Method not in allowlist: {method_name!r}"
            )

        method = getattr(self.agent, method_name, None)
        if method is None or not callable(method):
            raise RpcHandlerError(
                UNKNOWN_AGENT_METHOD, f"Unknown agent method: {method_name!r}"
            )

        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result

        return _serialize_for_rpc(result)

    async def _require_scheduler(self) -> Any:
        """Return the scheduler manager, or raise `SCHEDULER_UNAVAILABLE`."""
        if self._scheduler_manager is None:
            raise RpcHandlerError(
                SCHEDULER_UNAVAILABLE,
                "Scheduler is not available (ai-parrot-server not "
                "installed, or scheduler.enabled=false in config).",
            )
        return self._scheduler_manager

    async def _handle_schedules_list(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `schedules.list`."""
        manager = await self._require_scheduler()
        return _serialize_for_rpc(await manager.list_jobs())

    async def _handle_schedules_add(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `schedules.add`."""
        manager = await self._require_scheduler()
        schedule = await manager.add_schedule(**params)
        return _serialize_for_rpc(schedule)

    async def _handle_schedules_pause(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `schedules.pause`."""
        manager = await self._require_scheduler()
        try:
            schedule = await manager.pause_schedule(params.get("schedule_id"))
        except Exception as exc:
            raise RpcHandlerError(SCHEDULE_NOT_FOUND, str(exc)) from exc
        return _serialize_for_rpc(schedule)

    async def _handle_schedules_resume(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `schedules.resume` (re-enable + reschedule the job)."""
        manager = await self._require_scheduler()
        try:
            schedule = await manager.update_schedule(
                params.get("schedule_id"), {"enabled": True}
            )
        except Exception as exc:
            raise RpcHandlerError(SCHEDULE_NOT_FOUND, str(exc)) from exc
        return _serialize_for_rpc(schedule)

    async def _handle_schedules_remove(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `schedules.remove`."""
        manager = await self._require_scheduler()
        try:
            await manager.delete_schedule(params.get("schedule_id"))
        except Exception as exc:
            raise RpcHandlerError(SCHEDULE_NOT_FOUND, str(exc)) from exc
        return {"removed": True}

    async def _handle_events_subscribe(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `events.subscribe`."""
        self.server.event_broker.subscribe(session)
        return {"subscribed": True}

    async def _handle_events_unsubscribe(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `events.unsubscribe`."""
        self.server.event_broker.unsubscribe(session)
        return {"subscribed": False}

    async def _handle_daemon_status(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `daemon.status`."""
        scheduler_info: dict[str, Any] = {
            "available": self._scheduler_manager is not None
        }
        if self._scheduler_manager is not None:
            scheduler_info["running"] = bool(self._scheduler_manager.scheduler.running)
            scheduler_info["jobs"] = len(self._scheduler_manager.scheduler.get_jobs())

        return {
            "pid": os.getpid(),
            "uptime_s": time.monotonic() - self._start_time,
            "version": _integrations_version(),
            "scheduler": scheduler_info,
            "active_connections": self.server.active_connections if self.server else 0,
        }

    async def _handle_daemon_shutdown(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `daemon.shutdown`: signal the main loop to shut down."""
        self._shutdown_event.set()
        return {"ok": True}


def _integrations_version() -> str:
    """Return the installed `ai-parrot-integrations` package version."""
    try:
        from importlib.metadata import version

        return version("ai-parrot-integrations")
    except Exception:  # noqa: BLE001 - version reporting must never crash the daemon
        return "unknown"
