"""Telegram commands for per-user HTTP MCP server management.

Lets an end user attach their own HTTP-based MCP server (for example
Fireflies.ai) to the agent *for their session only*. Credentials are
stored in Redis under a per-user namespace and the server is registered
on the user's isolated ``ToolManager`` clone (see
``TelegramAgentWrapper._initialize_user_context``), so one user's MCP
token never becomes visible to another user's tool calls.

Commands exposed on the wrapper router:

* ``/add_mcp <json>`` — add an HTTP MCP server.
* ``/list_mcp`` — list this user's registered servers (no secrets).
* ``/remove_mcp <name>`` — disconnect and forget a server.

The JSON payload mirrors ``MCPClientConfig`` but only accepts the
fields that make sense for remote HTTP MCP servers driven by a token.
A minimal example::

    /add_mcp {
      "name": "fireflies",
      "url": "https://api.fireflies.ai/mcp",
      "auth_scheme": "bearer",
      "token": "sk-..."
    }

``name`` is used as the Redis hash field and as the MCP client id, so
callers can later remove or re-add the server by that name.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ...mcp.client import AuthCredential, AuthScheme, MCPClientConfig
from .mcp_persistence import TelegramMCPPublicParams

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ...tools.manager import ToolManager


logger = logging.getLogger(__name__)


_TELEGRAM_CHANNEL = "telegram"
_REDIS_KEY_TEMPLATE = "mcp:{channel}:{user_id}:servers"

# Resolver closure used by the handlers to reach the caller's per-user
# ``ToolManager``. Returns ``None`` when no ToolManager exists yet (for
# example, the user tried ``/add_mcp`` before authenticating).
ToolManagerResolver = Callable[[Message], Awaitable[Optional["ToolManager"]]]


# ── Public schema used by the JSON payload ─────────────────────────────────
# Only the fields we are willing to persist are honoured. Extra keys are
# ignored — never surface them to the user as "accepted".

_ALLOWED_SCHEMES = {
    "none": AuthScheme.NONE,
    "bearer": AuthScheme.BEARER,
    "api_key": AuthScheme.API_KEY,
    "apikey": AuthScheme.API_KEY,
    "basic": AuthScheme.BASIC,
}

_USAGE = (
    "Usage: /add_mcp <json>\n"
    "\n"
    "Minimum payload:\n"
    "{\n"
    '  "name": "fireflies",\n'
    '  "url": "https://api.fireflies.ai/mcp",\n'
    '  "auth_scheme": "bearer",\n'
    '  "token": "sk-..."\n'
    "}\n"
    "\n"
    "Supported auth_scheme values: none, bearer, api_key, basic."
)


def _redis_key(user_id: str) -> str:
    return _REDIS_KEY_TEMPLATE.format(channel=_TELEGRAM_CHANNEL, user_id=user_id)


def _build_config(payload: Dict[str, Any]) -> MCPClientConfig:
    """Turn a validated JSON payload into an ``MCPClientConfig``.

    Raises ``ValueError`` with a user-readable message on any problem so
    handlers can echo it back verbatim.
    """
    name = payload.get("name")
    url = payload.get("url")
    if not name or not isinstance(name, str):
        raise ValueError("'name' is required and must be a string.")
    if not url or not isinstance(url, str):
        raise ValueError("'url' is required and must be a string.")
    if not url.startswith(("http://", "https://")):
        raise ValueError("'url' must be an http:// or https:// URL.")

    scheme_name = str(payload.get("auth_scheme", "none")).lower()
    scheme = _ALLOWED_SCHEMES.get(scheme_name)
    if scheme is None:
        raise ValueError(
            f"Unsupported auth_scheme {scheme_name!r}. "
            f"Allowed: {sorted(_ALLOWED_SCHEMES)}."
        )

    credential: Optional[AuthCredential] = None
    if scheme == AuthScheme.BEARER:
        token = payload.get("token")
        if not token:
            raise ValueError("bearer auth requires a 'token' field.")
        credential = AuthCredential(scheme=scheme, token=token)
    elif scheme == AuthScheme.API_KEY:
        api_key = payload.get("api_key") or payload.get("token")
        if not api_key:
            raise ValueError("api_key auth requires an 'api_key' field.")
        credential = AuthCredential(
            scheme=scheme,
            api_key=api_key,
            api_key_header=payload.get("api_key_header", "X-API-Key"),
            use_bearer_prefix=bool(payload.get("use_bearer_prefix", False)),
        )
    elif scheme == AuthScheme.BASIC:
        username = payload.get("username")
        password = payload.get("password")
        if not username or not password:
            raise ValueError(
                "basic auth requires 'username' and 'password'."
            )
        credential = AuthCredential(
            scheme=scheme, username=username, password=password
        )

    headers = payload.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError("'headers' must be a JSON object if provided.")

    allowed = payload.get("allowed_tools")
    if allowed is not None and not isinstance(allowed, list):
        raise ValueError("'allowed_tools' must be a list if provided.")
    blocked = payload.get("blocked_tools")
    if blocked is not None and not isinstance(blocked, list):
        raise ValueError("'blocked_tools' must be a list if provided.")

    return MCPClientConfig(
        name=name,
        url=url,
        transport=str(payload.get("transport", "http")),
        description=payload.get("description"),
        auth_credential=credential,
        auth_type=scheme if scheme != AuthScheme.NONE else None,
        headers={str(k): str(v) for k, v in headers.items()},
        allowed_tools=list(allowed) if allowed else None,
        blocked_tools=list(blocked) if blocked else None,
    )


def _split_secret_and_public(
    payload: Dict[str, Any],
) -> tuple[TelegramMCPPublicParams, Dict[str, Any]]:
    """Split an /add_mcp payload into public config and secret params.

    Validates the same conditions as :func:`_build_config` so handlers can
    forward ``ValueError`` messages verbatim.

    Args:
        payload: Raw JSON dict from the Telegram command.

    Returns:
        Tuple of ``(TelegramMCPPublicParams, secret_params)``.
        ``secret_params`` is empty when ``auth_scheme`` is ``"none"``.

    Raises:
        ValueError: Same validation errors as ``_build_config``.
    """
    name = payload.get("name")
    url = payload.get("url")
    if not name or not isinstance(name, str):
        raise ValueError("'name' is required and must be a string.")
    if not url or not isinstance(url, str):
        raise ValueError("'url' is required and must be a string.")
    if not url.startswith(("http://", "https://")):
        raise ValueError("'url' must be an http:// or https:// URL.")

    scheme_name = str(payload.get("auth_scheme", "none")).lower()
    if scheme_name not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Unsupported auth_scheme {scheme_name!r}. "
            f"Allowed: {sorted(_ALLOWED_SCHEMES)}."
        )

    secret_params: Dict[str, Any] = {}
    if scheme_name == "bearer":
        token = payload.get("token")
        if not token:
            raise ValueError("bearer auth requires a 'token' field.")
        secret_params = {"token": token}
    elif scheme_name in ("api_key", "apikey"):
        api_key = payload.get("api_key") or payload.get("token")
        if not api_key:
            raise ValueError("api_key auth requires an 'api_key' field.")
        secret_params = {"api_key": api_key}
    elif scheme_name == "basic":
        username = payload.get("username")
        password = payload.get("password")
        if not username or not password:
            raise ValueError("basic auth requires 'username' and 'password'.")
        secret_params = {"username": username, "password": password}

    headers = payload.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError("'headers' must be a JSON object if provided.")
    allowed = payload.get("allowed_tools")
    if allowed is not None and not isinstance(allowed, list):
        raise ValueError("'allowed_tools' must be a list if provided.")
    blocked = payload.get("blocked_tools")
    if blocked is not None and not isinstance(blocked, list):
        raise ValueError("'blocked_tools' must be a list if provided.")

    public_params = TelegramMCPPublicParams(
        name=name,
        url=url,
        transport=str(payload.get("transport", "http")),
        description=payload.get("description"),
        auth_scheme=scheme_name,
        api_key_header=payload.get("api_key_header"),
        use_bearer_prefix=payload.get("use_bearer_prefix"),
        headers={str(k): str(v) for k, v in headers.items()},
        allowed_tools=list(allowed) if allowed else None,
        blocked_tools=list(blocked) if blocked else None,
    )
    return public_params, secret_params


async def _persist_config(
    redis_client: Any, user_id: str, name: str, payload: Dict[str, Any]
) -> None:
    """Store the raw JSON payload under the user's MCP hash.

    Uses the raw payload (not the built ``MCPClientConfig``) because the
    config carries non-serialisable objects like ``AuthCredential``. The
    payload has already been validated by ``_build_config``.
    """
    try:
        await redis_client.hset(
            _redis_key(user_id), name, json.dumps(payload)
        )
    except Exception:  # noqa: BLE001 — Redis errors must not leak tokens
        logger.exception(
            "Failed to persist MCP server %r for tg:%s", name, user_id
        )
        raise


async def _load_all_configs(
    redis_client: Any, user_id: str
) -> Dict[str, Dict[str, Any]]:
    """Return ``{name: payload}`` for every server the user has saved."""
    raw = await redis_client.hgetall(_redis_key(user_id))
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in (raw or {}).items():
        key_str = key.decode() if isinstance(key, (bytes, bytearray)) else key
        value_str = (
            value.decode() if isinstance(value, (bytes, bytearray)) else value
        )
        try:
            out[key_str] = json.loads(value_str)
        except json.JSONDecodeError:
            logger.warning(
                "Dropping malformed MCP payload for tg:%s / %s", user_id, key_str
            )
    return out


async def _forget_config(redis_client: Any, user_id: str, name: str) -> None:
    try:
        await redis_client.hdel(_redis_key(user_id), name)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to forget MCP server %r for tg:%s", name, user_id
        )


async def rehydrate_user_mcp_servers(
    redis_client: Any,
    tool_manager: "ToolManager",
    user_id: str,
) -> int:
    """Re-attach every persisted MCP server to ``tool_manager``.

    Called by the wrapper from ``_initialize_user_context`` so a process
    restart or a fresh session does not make the user re-issue
    ``/add_mcp``. Failures are logged per-server and do not abort the
    rehydration of the remaining servers.

    Returns:
        Number of MCP servers successfully registered.
    """
    if redis_client is None or tool_manager is None:
        return 0
    payloads = await _load_all_configs(redis_client, user_id)
    if not payloads:
        return 0
    count = 0
    for name, payload in payloads.items():
        try:
            config = _build_config(payload)
            await tool_manager.add_mcp_server(config)
            count += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to rehydrate MCP server %r for tg:%s", name, user_id
            )
    return count


# ── Handlers ──────────────────────────────────────────────────────────────


async def _reject_non_private(message: Message) -> bool:
    """Return True and reply if the command was issued outside a DM.

    MCP tokens must not be exposed in group / channel chats where the
    command text is visible to other members.
    """
    chat_type = getattr(message.chat, "type", None)
    if chat_type != "private":
        await message.reply(
            "For security, /add_mcp, /list_mcp and /remove_mcp only work "
            "in a direct message with the bot.",
            parse_mode=None,
        )
        return True
    return False


async def add_mcp_handler(
    message: Message,
    tool_manager_resolver: ToolManagerResolver,
    redis_client: Any,
) -> None:
    """Handle ``/add_mcp <json>``."""
    if message.from_user is None:
        await message.reply(
            "I can only register MCP servers for a real Telegram user.",
            parse_mode=None,
        )
        return
    if await _reject_non_private(message):
        return

    text = message.text or ""
    _, _, raw = text.partition(" ")
    raw = raw.strip()
    if not raw:
        await message.reply(_USAGE, parse_mode=None)
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        await message.reply(
            f"Could not parse JSON payload: {exc.msg}.\n\n{_USAGE}",
            parse_mode=None,
        )
        return

    if not isinstance(payload, dict):
        await message.reply(
            "JSON payload must be an object.\n\n" + _USAGE, parse_mode=None
        )
        return

    try:
        config = _build_config(payload)
    except ValueError as exc:
        await message.reply(str(exc) + "\n\n" + _USAGE, parse_mode=None)
        return

    tool_manager = await tool_manager_resolver(message)
    if tool_manager is None:
        await message.reply(
            "I need to set up your session first. Try /login (if required) "
            "and send the command again.",
            parse_mode=None,
        )
        return

    try:
        registered = await tool_manager.add_mcp_server(config)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "add_mcp: failed to connect to %r for tg:%s",
            config.name,
            message.from_user.id,
        )
        await message.reply(
            f"Could not connect to MCP server {config.name!r}: {exc}",
            parse_mode=None,
        )
        return

    if redis_client is not None:
        try:
            await _persist_config(
                redis_client, str(message.from_user.id), config.name, payload
            )
        except Exception:  # noqa: BLE001
            # Tools are live for this session; we just couldn't persist.
            await message.reply(
                f"Connected to {config.name!r} for this session, but I "
                "could not save it for next time (Redis error).",
                parse_mode=None,
            )
            await _maybe_delete(message)
            return

    await message.reply(
        f"Connected {config.name!r} with {len(registered)} tool(s).",
        parse_mode=None,
    )
    await _maybe_delete(message)


async def list_mcp_handler(
    message: Message, redis_client: Any
) -> None:
    """Handle ``/list_mcp`` — show the user's saved servers (no secrets)."""
    if message.from_user is None:
        return
    if await _reject_non_private(message):
        return
    if redis_client is None:
        await message.reply(
            "MCP server listing is unavailable (no Redis configured).",
            parse_mode=None,
        )
        return

    payloads = await _load_all_configs(
        redis_client, str(message.from_user.id)
    )
    if not payloads:
        await message.reply(
            "No MCP servers registered yet. Use /add_mcp to add one.",
            parse_mode=None,
        )
        return

    lines = ["Your MCP servers:"]
    for name, payload in sorted(payloads.items()):
        url = payload.get("url", "?")
        scheme = payload.get("auth_scheme", "none")
        lines.append(f"• {name} — {url} ({scheme})")
    await message.reply("\n".join(lines), parse_mode=None)


async def remove_mcp_handler(
    message: Message,
    tool_manager_resolver: ToolManagerResolver,
    redis_client: Any,
) -> None:
    """Handle ``/remove_mcp <name>``."""
    if message.from_user is None:
        return
    if await _reject_non_private(message):
        return

    text = message.text or ""
    _, _, name = text.partition(" ")
    name = name.strip()
    if not name:
        await message.reply(
            "Usage: /remove_mcp <server_name>", parse_mode=None
        )
        return

    user_id = str(message.from_user.id)
    tool_manager = await tool_manager_resolver(message)
    removed_live = False
    if tool_manager is not None:
        try:
            removed_live = await tool_manager.remove_mcp_server(name)
        except Exception:  # noqa: BLE001
            logger.exception(
                "remove_mcp: failed to disconnect %r for tg:%s", name, user_id
            )

    if redis_client is not None:
        await _forget_config(redis_client, user_id, name)

    if removed_live:
        await message.reply(f"Removed MCP server {name!r}.", parse_mode=None)
    else:
        await message.reply(
            f"No MCP server named {name!r} was active. "
            "Any stored entry has been cleared.",
            parse_mode=None,
        )


async def _maybe_delete(message: Message) -> None:
    """Best-effort delete the user's command message to drop any token."""
    try:
        await message.delete()
    except Exception:  # noqa: BLE001 - deletion is best-effort
        logger.debug("Could not delete /add_mcp command message", exc_info=True)


def register_mcp_commands(
    router: Router,
    tool_manager_resolver: ToolManagerResolver,
    redis_client: Any,
) -> None:
    """Wire the three MCP commands on *router*.

    Args:
        router: aiogram ``Router`` owned by the Telegram wrapper.
        tool_manager_resolver: async callable returning the per-user
            ``ToolManager`` for a given ``Message`` (or ``None`` when
            the user's session has not been initialized yet). Provided
            by the wrapper so the handlers stay decoupled from the
            singleton/per-user-agent mode detail.
        redis_client: Redis client fetched from ``app['redis']``. May be
            ``None`` in environments without Redis — the commands still
            work in-session but will not persist across restarts.
    """

    async def _add(message: Message) -> None:
        await add_mcp_handler(message, tool_manager_resolver, redis_client)

    async def _list(message: Message) -> None:
        await list_mcp_handler(message, redis_client)

    async def _remove(message: Message) -> None:
        await remove_mcp_handler(message, tool_manager_resolver, redis_client)

    router.message.register(_add, Command("add_mcp"))
    router.message.register(_list, Command("list_mcp"))
    router.message.register(_remove, Command("remove_mcp"))
