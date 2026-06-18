"""LiveKit Agents worker entrypoint for LiveAvatar Phase C (FEAT-243, Module 1).

The worker joins the **same** LiveKit Cloud room as the avatar participant
(shared BYO transport with FEAT-242 — no new transport layer).

**Process model (Q-deploy, validated on livekit-agents 1.6.1).** Jobs run in
**separate processes** (``job_executor_type=PROCESS``, ``forkserver``; a warm
pool is the prod default via ``num_idle_processes``). Two design consequences,
both handled here:

1. Per-job/per-process resources are built **inside** the job, never bound onto
   the entrypoint from the parent (which would not survive pickling across the
   process boundary). The aiohttp ``LiveAvatarClient`` is created in
   :func:`entrypoint`; the VAD is loaded once per process in :func:`prewarm` and
   read from ``ctx.proc.userdata``.
2. The worker is a different process from the AgentChat WS server, so the
   :class:`OutputBridge` sink is a :class:`RedisBroadcastForwarder` (cross-process
   pub/sub) rather than a direct ``UserSocketManager``. The server runs
   :func:`run_output_subscriber` to re-broadcast.

The deployment supplies the one non-env dependency — the ai-parrot
``bot_resolver`` — by calling :func:`configure` **at import time** in its worker
entry module (so ``forkserver`` children re-run it on import), then calling
:func:`run`.

The discrete helpers (``parse_job_metadata``, ``build_livekit_config``,
``open_avatar_session``, ``register_stop_session_shutdown``, ``prewarm``) are
pure / fake-able and unit-tested. The full ``entrypoint`` / ``run`` path needs a
live room and the ``liveavatar-voice`` extra; it is exercised by the Phase C
integration tests.
"""

import logging
import os
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
from parrot.integrations.liveavatar.output_transport import RedisBroadcastForwarder
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager

__all__ = [
    "WorkerConfig",
    "configure",
    "parse_job_metadata",
    "build_livekit_config",
    "open_avatar_session",
    "register_stop_session_shutdown",
    "prewarm",
    "entrypoint",
    "run",
]

logger = logging.getLogger(__name__)

#: Async callable resolving an agent name to an ai-parrot bot exposing
#: ``ask_stream``. Supplied by the deployment via :func:`configure`.
BotResolver = Callable[[str], Awaitable[Any]]


@dataclass
class WorkerConfig:
    """Import-time configuration shared by every job in the worker process.

    Built once via :func:`configure`; per-job resources (the aiohttp client) are
    created separately inside :func:`entrypoint`.

    Attributes:
        bot_resolver: Async ``agent_name -> bot`` resolver (prod: BotManager).
        cfg: LiveAvatar API configuration (defaults from env).
        output_sink: ``UserSocketManager``-compatible sink for the output bridge
            (defaults to a :class:`RedisBroadcastForwarder` for cross-process
            delivery).
        room_manager: LiveKit room/token manager (defaults to env-driven).
        agent_name: Optional worker ``agent_name`` for ``lk agent deploy``.
    """

    bot_resolver: BotResolver
    cfg: LiveAvatarConfig
    output_sink: Any
    room_manager: LiveKitRoomManager
    agent_name: str = ""


_CONFIG: Optional[WorkerConfig] = None


def _config_from_env() -> LiveAvatarConfig:
    """Build a :class:`LiveAvatarConfig` from environment variables."""
    return LiveAvatarConfig(
        api_key=os.environ["LIVEAVATAR_API_KEY"],
        avatar_id=os.environ["LIVEAVATAR_AVATAR_ID"],
        is_sandbox=os.environ.get("LIVEAVATAR_SANDBOX", "true").lower()
        in ("1", "true", "yes"),
    )


def configure(
    *,
    bot_resolver: BotResolver,
    cfg: Optional[LiveAvatarConfig] = None,
    output_sink: Optional[Any] = None,
    room_manager: Optional[LiveKitRoomManager] = None,
    agent_name: str = "",
) -> WorkerConfig:
    """Register the worker configuration. **Call at import time** in the worker
    entry module so ``forkserver`` children re-run it when re-importing.

    Defaults pull from the environment: ``cfg`` from ``LIVEAVATAR_*``,
    ``output_sink`` from ``REDIS_URL`` (a :class:`RedisBroadcastForwarder`),
    ``room_manager`` from ``LIVEKIT_*``.

    Args:
        bot_resolver: The only required, non-env dependency — resolves an
            ai-parrot bot by name in-process.
    """
    global _CONFIG
    if output_sink is None:
        from parrot.conf import REDIS_URL

        output_sink = RedisBroadcastForwarder.from_url(REDIS_URL)
    _CONFIG = WorkerConfig(
        bot_resolver=bot_resolver,
        cfg=cfg or _config_from_env(),
        output_sink=output_sink,
        room_manager=room_manager or LiveKitRoomManager(),
        agent_name=agent_name,
    )
    return _CONFIG


def _require_config() -> WorkerConfig:
    if _CONFIG is None:
        raise RuntimeError(
            "LiveAvatar worker not configured. Call "
            "parrot.integrations.liveavatar.livekit_agent.worker.configure(...) "
            "at import time in your worker entry module before run()."
        )
    return _CONFIG


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

    A standalone helper for callers that manage the aiohttp session themselves.
    :func:`entrypoint` instead relies on the client's own async-context teardown
    (``__aexit__`` stops the session and closes the aiohttp session). Returns the
    registered coroutine function (useful for tests).
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


def _vad_from_proc(ctx: Any) -> Any:
    """Read the prewarmed VAD from ``ctx.proc.userdata`` (or ``None``)."""
    proc = getattr(ctx, "proc", None)
    userdata = getattr(proc, "userdata", None) or {}
    return userdata.get("vad")


def prewarm(proc: Any) -> None:  # pragma: no cover - requires the extra
    """Load the Silero VAD once per worker process into ``proc.userdata``.

    Registered as ``WorkerOptions.prewarm_fnc`` so each job reuses one VAD.
    """
    from livekit.plugins import silero

    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: Any) -> None:
    """LiveKit Agents job entrypoint — builds all per-job deps in-process.

    Module-level (no bound deps) so it survives the ``forkserver`` boundary.

    .. note:: Requires :func:`configure` to have been called at import time, the
       ``liveavatar-voice`` extra, and a live room. Covered by the Phase C
       integration tests, not the unit tests.
    """
    config = _require_config()
    meta = parse_job_metadata(ctx)

    # Per-job aiohttp client, created in this process/loop and torn down on
    # shutdown via its own async-context exit (stop_session + session close).
    client = LiveAvatarClient(config.cfg)
    await client.__aenter__()

    async def _close_client() -> None:
        await client.__aexit__(None, None, None)

    ctx.add_shutdown_callback(_close_client)

    await open_avatar_session(client, config.cfg, config.room_manager, meta)

    bridge = OutputBridge(config.output_sink)
    agent = LiveAvatarAgent(
        agent_name=meta.agent_name,
        session_id=meta.session_id,
        bot_resolver=config.bot_resolver,
        output_bridge=bridge,
        tenant_id=meta.tenant_id,
    )
    session = build_session(_vad_from_proc(ctx))

    await ctx.connect()
    await session.start(agent=agent, room=ctx.room)


def run() -> None:  # pragma: no cover - requires the extra
    """Run the LiveKit Agents worker CLI (long-lived stateful worker).

    Call :func:`configure` at import time first. ``lk agent deploy`` applies
    (the room is ours). Spawn-per-session vs warm pool is tuned via
    ``WorkerOptions.num_idle_processes`` (Q-deploy).
    """
    from livekit.agents import WorkerOptions, cli

    config = _require_config()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name=config.agent_name,
        )
    )
