"""FEAT-878 startup checks for user-store configuration and Redis durability."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from redis.exceptions import ResponseError

from .settings import (
    SWITCHES,
    close_user_store_redis,
    get_user_store_redis,
    redis_url,
    resolve_store_backend,
    validate_user_store_settings,
)

_HOOKS_KEY = "_parrot_user_store_hooks"


def _safe_url() -> str:
    """Return the configured Redis URL without credentials."""
    try:
        parts = urlsplit(redis_url())
        return f"{parts.scheme}://{parts.hostname}:{parts.port or 6379}{parts.path}"
    except Exception:  # noqa: BLE001 - malformed configuration must not break diagnostics
        return "configured endpoint"


async def run_user_store_diagnostics(logger: logging.Logger | None = None) -> list[str]:
    """Log Redis availability and durability warnings without raising.

    Args:
        logger: Optional logger to receive diagnostic messages.

    Returns:
        Warning messages emitted by the diagnostic.
    """
    log = logger or logging.getLogger("parrot.userstore")
    warnings: list[str] = []
    try:
        if not any(resolve_store_backend(switch) == "redis" for switch in SWITCHES):
            return warnings
        client = get_user_store_redis()
        await client.ping()
    except Exception:  # noqa: BLE001 - diagnostics must never stop startup
        warning = f"User-store Redis at {_safe_url()} is unreachable"
        warnings.append(warning)
        log.warning(warning)
        return warnings

    async def _config_get(name: str) -> str | None:
        try:
            values = await client.config_get(name)
            value = values.get(name)
            return str(value).strip().lower() if value is not None else None
        except ResponseError:
            log.debug("User-store Redis does not permit CONFIG GET %s", name)
        except Exception:  # noqa: BLE001 - diagnostics must never stop startup
            log.debug("User-store Redis CONFIG GET %s failed", name)
        return None

    policy = await _config_get("maxmemory-policy")
    if policy and policy.startswith("allkeys-"):
        warning = f"User-store Redis eviction policy {policy!r} can evict user data"
        warnings.append(warning)
        log.warning(warning)

    appendonly = await _config_get("appendonly")
    save = await _config_get("save")
    if appendonly == "no" and save == "":
        warning = "User-store Redis persistence is disabled (appendonly=no and save is empty)"
        warnings.append(warning)
        log.warning(warning)

    return warnings


def install_user_store_hooks(app: Any) -> None:
    """Validate user-store settings and install diagnostics and cleanup hooks once.

    Args:
        app: Mutable aiohttp-compatible application.
    """
    if app.get(_HOOKS_KEY):
        return
    validate_user_store_settings()
    app[_HOOKS_KEY] = True

    async def _diagnostics(_app: Any) -> None:
        await run_user_store_diagnostics()

    async def _close(_app: Any) -> None:
        await close_user_store_redis()

    app.on_startup.append(_diagnostics)
    app.on_cleanup.append(_close)
