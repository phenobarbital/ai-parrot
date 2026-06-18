"""Server-side wiring for the LiveAvatar Phase C structured-output bridge (FEAT-243).

The LiveKit worker runs in a separate process and publishes structured outputs
(charts/data/canvas/tool_calls) to a Redis pub/sub channel via
``RedisBroadcastForwarder``. This module runs the **consumer** side inside the
ai-parrot-server: a background task that re-broadcasts each envelope through the
app's ``UserSocketManager`` so it reaches the browser AgentChat UI on the channel
keyed by ``session_id``.

Opt-in (mirrors ``configure_job_manager``): call
:func:`configure_liveavatar_output_subscriber` during app assembly for
deployments running LiveAvatar Phase C. The Redis URL and channel **must match**
the worker's ``RedisBroadcastForwarder`` (both default to ``parrot.conf.REDIS_URL``
and ``liveavatar:structured-outputs``).
"""

import asyncio
import logging
from typing import Optional

from aiohttp import web

from parrot.conf import REDIS_URL

__all__ = ["configure_liveavatar_output_subscriber"]

logger = logging.getLogger(__name__)

_REDIS_KEY = "liveavatar_output_redis"
_TASK_KEY = "liveavatar_output_task"


def configure_liveavatar_output_subscriber(
    app: web.Application,
    *,
    redis_url: Optional[str] = None,
    channel: Optional[str] = None,
) -> web.Application:
    """Register the LiveAvatar output subscriber on the aiohttp application.

    On startup it builds a Redis client, looks up ``app['user_socket_manager']``
    and launches a long-lived background task running
    ``run_output_subscriber``. On cleanup the task is cancelled and the Redis
    client closed.

    Args:
        app: The aiohttp Application.
        redis_url: Redis URL to subscribe on. Must match the worker's forwarder.
            Defaults to ``parrot.conf.REDIS_URL``.
        channel: Redis pub/sub channel. Defaults to the transport's
            ``DEFAULT_OUTPUT_CHANNEL``.

    Returns:
        The same ``app`` (for chaining).
    """
    resolved_redis_url = redis_url or REDIS_URL

    async def _start(application: web.Application) -> None:
        # Lazy imports: redis + ai-parrot-integrations are only needed when the
        # subscriber is enabled, and integrations is not a hard server dep.
        try:
            import redis.asyncio as aioredis
            from parrot.integrations.liveavatar.output_transport import (
                DEFAULT_OUTPUT_CHANNEL,
                run_output_subscriber,
            )
        except ImportError:
            logger.warning(
                "LiveAvatar output subscriber disabled: ai-parrot-integrations "
                "(or redis) is not installed."
            )
            return

        socket_manager = application.get("user_socket_manager")
        if socket_manager is None:
            logger.warning(
                "configure_liveavatar_output_subscriber: app['user_socket_manager'] "
                "is not set; structured outputs will not reach the UI."
            )
            return

        sub_channel = channel or DEFAULT_OUTPUT_CHANNEL
        redis = aioredis.from_url(resolved_redis_url, decode_responses=True)
        application[_REDIS_KEY] = redis
        application[_TASK_KEY] = asyncio.create_task(
            run_output_subscriber(redis, socket_manager, channel=sub_channel),
            name="liveavatar-output-subscriber",
        )
        logger.info(
            "LiveAvatar output subscriber started on redis channel %s", sub_channel
        )

    async def _stop(application: web.Application) -> None:
        task = application.pop(_TASK_KEY, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - teardown must never raise
                logger.exception("LiveAvatar output subscriber task errored on stop")

        redis = application.pop(_REDIS_KEY, None)
        if redis is not None:
            close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

    app.on_startup.append(_start)
    app.on_cleanup.append(_stop)
    return app
