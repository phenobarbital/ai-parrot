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

from parrot.human import HumanChannel

from .config import AgentServiceConfig, default_socket_path, resolve_agent
from .protocol import (
    INTERNAL_ERROR,
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

#: Plain-string RPC/notification names for the bridged-HITL wiring
#: (FEAT-434). Deliberately NOT protocol.py constants — `RpcNotification`
#: and the dispatch table both accept arbitrary strings, and this keeps
#: the wire-protocol surface (Module 2, TASK-2208) untouched by this task.
_HITL_REQUEST_NOTIFICATION = "hitl.request"
_HITL_NOTIFY_NOTIFICATION = "hitl.notify"
_HITL_CANCEL_NOTIFICATION = "hitl.cancel"
_HITL_RESPOND_METHOD = "hitl.respond"


class _AgentdHumanChannel(HumanChannel):
    """Delivers bridged confirming-tool HITL requests to the agentd console.

    FEAT-434 (spec §3 Module 5): confirming tools called by a bridged
    Claude Code sub-agent must ask a real human via the daemon's own
    channel — never the `ConfirmationConfig.default_channel="telegram"`
    default. Outbound interactions are published through the daemon's
    existing `EventBroker` fan-out (reaching every `parrot attach`
    session); the human's answer arrives via the `"hitl.respond"` RPC
    (`AgentDaemon._handle_hitl_respond`), which invokes the
    `HumanInteractionManager.receive_response` callback registered here
    at `startup()`.
    """

    channel_type = "agentd"

    def __init__(self, daemon: AgentDaemon) -> None:
        self._daemon = daemon
        self.logger = logging.getLogger(__name__)
        self._response_callback = None

    async def register_response_handler(self, callback) -> None:
        """Store the manager's `receive_response` callback."""
        self._response_callback = callback

    async def send_interaction(self, interaction: Any, recipient: str) -> bool:
        """Publish the interaction to every attached `parrot attach` console."""
        server = self._daemon.server
        if server is None:
            self.logger.warning(
                "Cannot deliver HITL interaction %s: daemon server not ready",
                interaction.interaction_id,
            )
            return False
        await server.event_broker.publish(
            _HITL_REQUEST_NOTIFICATION,
            {
                "interaction_id": interaction.interaction_id,
                "question": interaction.question,
                "interaction_type": interaction.interaction_type.value,
                "recipient": recipient,
            },
        )
        return True

    async def send_notification(self, recipient: str, message: str) -> None:
        """Publish a one-way notification (no response expected)."""
        server = self._daemon.server
        if server is not None:
            await server.event_broker.publish(
                _HITL_NOTIFY_NOTIFICATION, {"recipient": recipient, "message": message}
            )

    async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool:
        """Publish a cancellation notice for a pending interaction."""
        server = self._daemon.server
        if server is None:
            return False
        await server.event_broker.publish(
            _HITL_CANCEL_NOTIFICATION,
            {"interaction_id": interaction_id, "recipient": recipient},
        )
        return True


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

    Prefers the canonical text fields -- `.output`, falling back to
    `.response` -- mirroring `ResponseRenderer.render()`'s own extraction
    (`parrot.cli.renderer`) for a real `AIMessage`. A bare `str()` of an
    `AIMessage` would otherwise dump every Pydantic field (input, output,
    response, data, code, images, ...) into `output`, since `AIMessage`
    has no custom `__str__`. Falls back to `str(response)` only when
    neither attribute is present (e.g. a plain object with no `.output`/
    `.response`, such as a bare string response).

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

    output = getattr(response, "output", None)
    if output is None:
        output = getattr(response, "response", None)
    if output is None:
        output = str(response)
    elif not isinstance(output, str):
        output = str(output)

    return {"output": output, "metadata": metadata}


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
        # FEAT-434: bridged-HITL wiring, populated by `_configure_hitl()`.
        self._hitl_channel: _AgentdHumanChannel | None = None
        self._human_manager: Any = None
        self._confirmation_guard: Any = None

    async def run(self) -> None:
        """Run the daemon's full lifecycle (spec §2, steps 1-6).

        Returns once a graceful shutdown completes (SIGTERM/SIGINT or a
        `daemon.shutdown` RPC).
        """
        self._configure_logging()

        # Install signal handlers FIRST, before the socket is bound and
        # advertised (sd_notify) -- a SIGTERM arriving in that window would
        # otherwise hit Python's default disposition (immediate kill)
        # instead of the graceful shutdown path.
        await self._install_signal_handlers()

        self.agent = await resolve_agent(self.config.agent)
        await self._configure_hitl()

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

    async def _configure_hitl(self) -> None:
        """Wire a `ConfirmationGuard` onto the agent's `ToolManager` (FEAT-434).

        Makes bridged confirming tools (`ClaudeAgentToolBridge`, TASK-2287)
        park until a real human answers via the agentd console, instead of
        the `ConfirmationConfig.default_channel="telegram"` default or
        (with no guard at all) letting the sub-agent grant itself
        permission. Best-effort: an agent target with no `tool_manager`
        attribute, or one whose guard is already externally configured, is
        left untouched.

        The daemon's guard pins `window_seconds=0` regardless of any other
        deployment default — belt-and-braces with the service identity's
        own fixed `window_seconds=0` (`agentd/config.py`,
        `ServiceIdentityConfig`, TASK-2286): this daemon's `ToolManager`
        always re-asks, for every caller.
        """
        tool_manager = getattr(self.agent, "tool_manager", None)
        if tool_manager is None:
            self.logger.debug(
                "Agent target has no tool_manager; skipping bridged-HITL wiring."
            )
            return
        if getattr(tool_manager, "confirmation_guard", None) is not None:
            self.logger.debug(
                "ToolManager already has a ConfirmationGuard; leaving it as-is."
            )
            return

        from parrot.auth import (
            ConfirmationConfig,
            ConfirmationGuard,
            InMemoryConfirmationWindowStore,
        )
        from parrot.human import HumanInteractionManager

        self._hitl_channel = _AgentdHumanChannel(self)
        self._human_manager = HumanInteractionManager(
            channels={"agentd": self._hitl_channel}
        )
        await self._human_manager.startup()
        self._confirmation_guard = ConfirmationGuard(
            store=InMemoryConfirmationWindowStore(),
            human_manager=self._human_manager,
            config=ConfirmationConfig(window_seconds=0, default_channel="agentd"),
        )
        tool_manager.set_confirmation_guard(self._confirmation_guard)
        self.logger.info(
            "Bridged HITL wiring configured: channel=agentd window_seconds=0"
        )

    async def _handle_hitl_respond(
        self, session: Session, params: dict[str, Any]
    ) -> Any:
        """Handle `hitl.respond`: a human's answer to a bridged confirmation.

        Raises:
            RpcHandlerError: `INTERNAL_ERROR` when no HITL channel is
                configured (no confirming tools were ever wired, or
                `_configure_hitl` skipped because the agent has no
                `tool_manager`).
        """
        if self._hitl_channel is None or self._hitl_channel._response_callback is None:
            raise RpcHandlerError(
                INTERNAL_ERROR, "No bridged HITL channel is configured."
            )

        from parrot.human.models import HumanResponse, InteractionType

        respondent = params.get("respondent")
        if not respondent and session.permission_context is not None:
            respondent = session.permission_context.user_id
        response = HumanResponse(
            interaction_id=params["interaction_id"],
            respondent=respondent or "anonymous",
            response_type=InteractionType(params["response_type"]),
            value=params["value"],
        )
        await self._hitl_channel._response_callback(response)
        return {"ok": True}

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
            # FEAT-434: bridged-HITL response channel (plain string — see
            # `_HITL_RESPOND_METHOD`, deliberately not a protocol.py constant).
            _HITL_RESPOND_METHOD: self._handle_hitl_respond,
        }

    async def _handle_chat_send(self, session: Session, params: dict[str, Any]) -> Any:
        """Handle `chat.send`: one-shot response, or ack + streamed deltas.

        `stream_id` may be supplied by the caller (e.g. `AgentDaemonClient.
        stream()` generates it up front and registers its queue before
        even sending this request, to avoid a race where the daemon's
        first `chat.delta` arrives before the client is listening for
        it). Falls back to generating one server-side for callers that
        don't supply it (e.g. a raw NDJSON client).
        """
        prompt = params.get("prompt", "")
        stream = bool(params.get("stream", False))
        metadata = params.get("metadata") or {}
        # FEAT-434: forward the caller's resolved identity (SO_PEERCRED ->
        # OS user, or the service-identity fallback; TASK-2286) so bridged
        # confirming tools key their confirmation window on the real
        # caller, not "anonymous". `AbstractBot.ask()`/`ask_stream()`
        # already forward this onto the LLM client as `_permission_context`
        # when set — this is the existing mechanism, not a new one.
        metadata.setdefault("permission_context", session.permission_context)

        if not stream:
            response = await self.agent.ask(
                prompt, session_id=session.session_id, **metadata
            )
            return _agent_response_to_rpc(response)

        stream_id = params.get("stream_id") or uuid.uuid4().hex
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
        """Iterate `agent.ask_stream()`, emitting `chat.delta`/`chat.complete`.

        `AbstractBot.ask_stream()`'s real contract yields text deltas
        (`str`, or an object with `.text`/`.content`) followed by a
        trailing `AIMessage`-shaped sentinel (identified by `.output`) --
        mirrors the exact chunk-shape handling `AgentREPL.send_stream()`
        already uses (`parrot.cli.repl`). The sentinel is NOT itself a
        text delta -- treating it as one would `str()`-dump every
        Pydantic field into the stream.
        """
        accumulated: list[str] = []
        final_response: Any = None
        try:
            async for chunk in self.agent.ask_stream(
                prompt, session_id=session.session_id, **metadata
            ):
                if isinstance(chunk, str):
                    text = chunk
                elif hasattr(chunk, "text"):
                    text = chunk.text
                elif hasattr(chunk, "content"):
                    text = chunk.content
                elif hasattr(chunk, "output"):
                    # Final AIMessage-like sentinel -- not a text delta.
                    final_response = chunk
                    break
                else:
                    text = str(chunk)
                accumulated.append(text)
                await session.notify(
                    METHOD_CHAT_DELTA, {"stream_id": stream_id, "text": text}
                )

            response_text = "".join(accumulated)
            if final_response is not None:
                output = getattr(final_response, "output", None)
                if output is None:
                    output = getattr(final_response, "response", None)
                if output is not None:
                    response_text = output if isinstance(output, str) else str(output)

            await session.notify(
                METHOD_CHAT_COMPLETE,
                {
                    "stream_id": stream_id,
                    "response": response_text,
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
        """Handle `agent.info`.

        Includes `exposed_methods` (the daemon's `agent.invoke` allowlist)
        so clients that only know a socket path/name -- e.g. the MCP stdio
        proxy (TASK-2215) -- can decide whether to expose `invoke_method`
        without needing the `AgentServiceConfig` object itself.
        """
        get_tools_count = getattr(self.agent, "get_tools_count", None)
        return {
            "name": getattr(self.agent, "name", self.config.name),
            "class": type(self.agent).__name__,
            "llm": str(getattr(self.agent, "llm", None)),
            "tools_count": get_tools_count() if callable(get_tools_count) else 0,
            "uptime_s": time.monotonic() - self._start_time,
            "exposed_methods": list(self.config.exposed_methods),
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
