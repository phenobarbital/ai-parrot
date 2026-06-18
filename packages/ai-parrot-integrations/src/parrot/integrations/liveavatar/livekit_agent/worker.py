"""LiveKit Agents worker entrypoint for LiveAvatar Phase C (FEAT-243, Module 1).

The worker joins the **same** LiveKit Cloud room as the avatar participant
(shared BYO transport with FEAT-242 — no new transport layer). It:

1. parses ``ctx.job.metadata`` (JSON) into :class:`AvatarJobMetadata`
   (injecting ``tenant_id`` / ``agent_name`` / ``session_id``);
2. mints room tokens via the FEAT-242 :class:`LiveKitRoomManager` and opens a
   LiveAvatar session via :class:`LiveAvatarClient` with ``livekit_config`` so
   the avatar joins our room;
3. builds the :class:`OutputBridge` + :class:`LiveAvatarAgent` (the ai-parrot
   LLM node) and the voice :func:`build_session`;
4. registers ``stop_session`` as a shutdown callback so the LiveAvatar session
   is torn down on worker teardown.

The discrete helpers (``parse_job_metadata``, ``build_livekit_config``,
``open_avatar_session``, ``register_stop_session_shutdown``) are pure / fake-able
and unit-tested. The full ``entrypoint`` / ``run`` path needs the
``liveavatar-voice`` extra and a live room; it is validated by the Phase C
integration tests (``test_phase_c_*``, out of this task's scope) and **P5 /
Q-deploy** before production.
"""

import functools
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from parrot.integrations.liveavatar.client import LiveAvatarClient
from parrot.integrations.liveavatar.livekit_agent.agent import LiveAvatarAgent
from parrot.integrations.liveavatar.livekit_agent.models import AvatarJobMetadata
from parrot.integrations.liveavatar.livekit_agent.pipeline import build_session
from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,
    LiveAvatarConfig,
    LiveKitRoomTokens,
)
from parrot.integrations.liveavatar.output_bridge import OutputBridge
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager

__all__ = [
    "LiveAvatarWorkerDeps",
    "parse_job_metadata",
    "build_livekit_config",
    "open_avatar_session",
    "register_stop_session_shutdown",
    "entrypoint",
    "run",
]

logger = logging.getLogger(__name__)


@dataclass
class LiveAvatarWorkerDeps:
    """Dependencies bound into the worker ``entrypoint``.

    Attributes:
        cfg: LiveAvatar API configuration.
        client: FEAT-242 LiveAvatar session client.
        room_manager: FEAT-242 LiveKit room/token manager.
        socket_manager: ``UserSocketManager``-like object for the output bridge.
        bot_resolver: Async ``agent_name -> bot`` resolver (prod: BotManager).
        vad: Prewarmed VAD plugin instance (e.g. Silero).
        session_factory: Optional ``AgentSession`` factory (defaults to the real
            one inside :func:`build_session`); injectable for tests.
    """

    cfg: LiveAvatarConfig
    client: LiveAvatarClient
    room_manager: LiveKitRoomManager
    socket_manager: Any
    bot_resolver: Callable[[str], Awaitable[Any]]
    vad: Any
    session_factory: Optional[Callable[..., Any]] = None


def parse_job_metadata(ctx: Any) -> AvatarJobMetadata:
    """Parse ``ctx.job.metadata`` (a JSON string) into :class:`AvatarJobMetadata`."""
    return AvatarJobMetadata.model_validate_json(ctx.job.metadata)


def build_livekit_config(tokens: LiveKitRoomTokens) -> Dict[str, Any]:
    """Compose the ``livekit_config`` payload for ``create_session_token``.

    Mirrors the FEAT-242 orchestrator wiring so the avatar joins our room.
    """
    return {
        "url": tokens.livekit_url,
        "room": tokens.room,
        "agentToken": tokens.agent_token,
    }


async def open_avatar_session(
    client: LiveAvatarClient,
    cfg: LiveAvatarConfig,
    room_manager: LiveKitRoomManager,
    meta: AvatarJobMetadata,
) -> AvatarSessionHandle:
    """Mint room tokens, create and start the LiveAvatar session for our room.

    Returns:
        The started :class:`AvatarSessionHandle` (carrying ``session_id`` /
        ``tenant_id`` / ``agent_name`` for downstream bookkeeping).
    """
    tokens = room_manager.mint_room_tokens(
        room=meta.session_id, identity=meta.agent_name
    )
    livekit_config = build_livekit_config(tokens)

    created = await client.create_session_token(cfg, livekit_config=livekit_config)
    handle = AvatarSessionHandle(
        session_id=meta.session_id,
        liveavatar_session_id=created.liveavatar_session_id,
        session_token=created.session_token,
        ws_url=created.ws_url,
        tenant_id=meta.tenant_id,
        agent_name=meta.agent_name,
    )
    await client.start_session(handle)
    logger.info(
        "Opened LiveAvatar session %s for agent=%s session=%s tenant=%s",
        handle.liveavatar_session_id,
        meta.agent_name,
        meta.session_id,
        meta.tenant_id,
    )
    return handle


def register_stop_session_shutdown(
    ctx: Any,
    client: LiveAvatarClient,
    handle: AvatarSessionHandle,
) -> Callable[[], Awaitable[None]]:
    """Register ``client.stop_session(handle)`` as a worker shutdown callback.

    Returns the registered coroutine function (useful for tests).
    """

    async def _on_shutdown() -> None:
        try:
            await client.stop_session(handle)
        except Exception:  # noqa: BLE001 - teardown must never raise
            logger.exception(
                "stop_session failed for %s", handle.liveavatar_session_id
            )

    ctx.add_shutdown_callback(_on_shutdown)
    return _on_shutdown


async def entrypoint(ctx: Any, *, deps: LiveAvatarWorkerDeps) -> None:
    """LiveKit Agents job entrypoint (bind ``deps`` via ``functools.partial``).

    .. note:: Requires the ``liveavatar-voice`` extra and a live room; covered by
       the Phase C integration tests, not the unit tests for this task.
    """
    meta = parse_job_metadata(ctx)
    handle = await open_avatar_session(deps.client, deps.cfg, deps.room_manager, meta)
    register_stop_session_shutdown(ctx, deps.client, handle)

    bridge = OutputBridge(deps.socket_manager)
    agent = LiveAvatarAgent(
        agent_name=meta.agent_name,
        session_id=meta.session_id,
        bot_resolver=deps.bot_resolver,
        output_bridge=bridge,
        tenant_id=meta.tenant_id,
    )
    session = build_session(deps.vad, session_factory=deps.session_factory)

    await ctx.connect()
    await session.start(agent=agent, room=ctx.room)


def run(deps: LiveAvatarWorkerDeps) -> None:  # pragma: no cover - requires the extra
    """Run the LiveKit Agents worker CLI (long-lived stateful worker).

    .. note:: ``lk agent deploy`` applies (the room is ours). P5 RESOLVED:
       ``WorkerOptions(entrypoint_fnc=...)`` + ``cli.run_app`` validated against
       livekit-agents 1.6.1.

    .. warning:: **Q-deploy (UNRESOLVED) — process boundary.** livekit-agents
       runs jobs in separate processes (``job_executor_type=PROCESS``,
       ``multiprocessing_context='forkserver'``; a warm pool is the prod default
       via ``num_idle_processes``). Binding non-picklable resources (the aiohttp
       ``LiveAvatarClient``, ``socket_manager``, ``bot_resolver``) onto the
       entrypoint via ``functools.partial(entrypoint, deps=deps)`` will NOT
       survive that boundary — per-process resources must be constructed INSIDE
       the job (``prewarm_fnc`` → ``proc.userdata`` and/or a module-level deps
       factory called within ``entrypoint``). Additionally, the worker is a
       separate process from the AgentChat WS server, so ``OutputBridge`` cannot
       call the server's ``UserSocketManager`` directly — it must publish via a
       cross-process channel (e.g. Redis pub/sub) that the server re-broadcasts.
       This ``run`` helper is a scaffold; finalise the deps/transport model
       before deploying.
    """
    try:
        from livekit.agents import WorkerOptions, cli
    except ImportError as exc:
        raise ImportError(
            "livekit-agents is required to run the worker. "
            "Install the 'liveavatar-voice' extra."
        ) from exc

    cli.run_app(
        WorkerOptions(entrypoint_fnc=functools.partial(entrypoint, deps=deps))
    )
