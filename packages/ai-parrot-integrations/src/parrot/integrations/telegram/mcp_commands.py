"""Telegram commands for per-user HTTP MCP server management.

Lets an end user attach their own HTTP-based MCP server (for example
Fireflies.ai) to the agent *for their session only*. Credentials are
split into a **non-secret public config** (persisted in DocumentDB via
:class:`~parrot.integrations.telegram.mcp_persistence.TelegramMCPPersistenceService`)
and a **secret part** (stored in the Navigator Vault via
:func:`~parrot.handlers.vault_utils.store_vault_credential`).  Secrets are
never written to Redis, logs, or any unencrypted store.

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

``name`` is used as the DocumentDB compound key and as the MCP client id,
so callers can later remove or re-add the server by that name.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ...mcp.client import AuthCredential, AuthScheme, MCPClientConfig
from .mcp_persistence import (
    TelegramMCPPersistenceService,
    TelegramMCPPublicParams,
    UserTelegramMCPConfig,  # noqa: F401 — re-exported for callers
)
from parrot.handlers.vault_utils import (
    delete_vault_credential,
    retrieve_vault_credential,
    store_vault_credential,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ...tools.manager import ToolManager


logger = logging.getLogger(__name__)


_TELEGRAM_CHANNEL = "telegram"

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


def _build_config(payload: Dict[str, Any]) -> MCPClientConfig:
    """Turn a validated JSON payload into an ``MCPClientConfig``.

    Delegates validation to :func:`_split_secret_and_public` and assembly to
    :func:`_build_config_from_parts`.  Raises ``ValueError`` with a
    user-readable message on any problem so handlers can echo it back verbatim.
    """
    public_params, secret_params = _split_secret_and_public(payload)
    return _build_config_from_parts(public_params, secret_params)


def _build_config_from_parts(
    public_params: "TelegramMCPPublicParams",
    secret_params: Dict[str, Any],
) -> MCPClientConfig:
    """Assemble an ``MCPClientConfig`` from already-validated split parts.

    This is the low-level builder used by both :func:`_build_config` (which
    validates first via :func:`_split_secret_and_public`) and
    :func:`add_mcp_handler` (which keeps the split result for persistence).

    Args:
        public_params: Non-secret parameters from :func:`_split_secret_and_public`.
        secret_params: Secret dict from :func:`_split_secret_and_public`.

    Returns:
        A fully populated :class:`MCPClientConfig`.
    """
    scheme = _ALLOWED_SCHEMES[public_params.auth_scheme]

    credential: Optional[AuthCredential] = None
    if scheme == AuthScheme.BEARER:
        credential = AuthCredential(scheme=scheme, token=secret_params["token"])
    elif scheme == AuthScheme.API_KEY:
        credential = AuthCredential(
            scheme=scheme,
            api_key=secret_params["api_key"],
            api_key_header=public_params.api_key_header or "X-API-Key",
            use_bearer_prefix=bool(public_params.use_bearer_prefix),
        )
    elif scheme == AuthScheme.BASIC:
        credential = AuthCredential(
            scheme=scheme,
            username=secret_params["username"],
            password=secret_params["password"],
        )

    return MCPClientConfig(
        name=public_params.name,
        url=public_params.url,
        transport=public_params.transport,
        description=public_params.description,
        auth_credential=credential,
        auth_type=scheme if scheme != AuthScheme.NONE else None,
        headers=dict(public_params.headers),
        allowed_tools=list(public_params.allowed_tools) if public_params.allowed_tools else None,
        blocked_tools=list(public_params.blocked_tools) if public_params.blocked_tools else None,
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
    scheme_name = "api_key" if scheme_name == "apikey" else scheme_name
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


async def rehydrate_user_mcp_servers(
    tool_manager: Optional["ToolManager"],
    user_id: str,
) -> int:
    """Re-attach every persisted MCP server to ``tool_manager``.

    Called by the wrapper from ``_initialize_user_context`` so a process
    restart or a fresh session does not make the user re-issue
    ``/add_mcp``. Loads public config from DocumentDB and secrets from the
    Vault, then rebuilds each ``MCPClientConfig``.

    Failures are logged per-server and do not abort the rehydration of the
    remaining servers.

    Args:
        tool_manager: The user's isolated :class:`~parrot.tools.manager.ToolManager`.
        user_id: Telegram user identifier (``tg:<telegram_id>``).

    Returns:
        Number of MCP servers successfully registered.
    """
    if tool_manager is None:
        return 0

    persistence = TelegramMCPPersistenceService()
    configs = await persistence.list(user_id)
    if not configs:
        return 0

    count = 0
    for config in configs:
        try:
            secret_params: Dict[str, Any] = {}
            if config.vault_credential_name:
                try:
                    secret_params = await retrieve_vault_credential(
                        user_id, config.vault_credential_name
                    )
                except KeyError:
                    logger.warning(
                        "rehydrate: Vault entry missing for MCP server %r / %s — skipping",
                        config.name,
                        user_id,
                    )
                    continue

            payload = {**config.params.model_dump(), **secret_params}
            mcp_config = _build_config(payload)
            await tool_manager.add_mcp_server(mcp_config)
            count += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "rehydrate: failed to restore MCP server %r for %s",
                config.name,
                user_id,
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
) -> None:
    """Handle ``/add_mcp <json>``.

    Operation order (with rollback):
    1. Persist public config in DocumentDB.
    2. Store secrets in the Vault (if any).
    3. Register live tools with ToolManager.

    On failure at step 2, step 1 is rolled back.
    On failure at step 3, steps 1 and 2 are rolled back.
    """
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
        public_params, secret_params = _split_secret_and_public(payload)
        config = _build_config_from_parts(public_params, secret_params)
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

    user_id = f"tg:{message.from_user.id}"
    name = config.name
    vault_name: Optional[str] = f"tg_mcp_{name}" if secret_params else None
    persistence = TelegramMCPPersistenceService()

    # Step 1: persist public config
    try:
        await persistence.save(user_id, name, public_params, vault_name)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "add_mcp: failed to save config for %r / %s", name, user_id
        )
        await message.reply(
            f"Could not save MCP server config: {exc}", parse_mode=None
        )
        return

    # Step 2: store secrets in Vault (if any)
    if secret_params:
        try:
            await store_vault_credential(user_id, vault_name, secret_params)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "add_mcp: Vault store failed for %r / %s", name, user_id
            )
            await persistence.remove(user_id, name)  # rollback step 1
            await message.reply(
                f"Could not store credentials for {name!r}: {exc}",
                parse_mode=None,
            )
            return

    # Step 3: register live tools
    try:
        registered: List[str] = await tool_manager.add_mcp_server(config)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "add_mcp: ToolManager register failed for %r / %s", name, user_id
        )
        # Rollback steps 1 & 2
        await persistence.remove(user_id, name)
        if secret_params and vault_name:
            try:
                await delete_vault_credential(user_id, vault_name)
            except Exception:  # noqa: BLE001
                pass
        await message.reply(
            f"Could not connect to MCP server {name!r}: {exc}",
            parse_mode=None,
        )
        return

    await message.reply(
        f"Connected {name!r} with {len(registered)} tool(s).",
        parse_mode=None,
    )
    await _maybe_delete(message)


async def list_mcp_handler(message: Message) -> None:
    """Handle ``/list_mcp`` — show the user's saved servers (no secrets)."""
    if message.from_user is None:
        return
    if await _reject_non_private(message):
        return

    user_id = f"tg:{message.from_user.id}"
    persistence = TelegramMCPPersistenceService()
    configs = await persistence.list(user_id)

    if not configs:
        await message.reply(
            "No MCP servers registered yet. Use /add_mcp to add one.",
            parse_mode=None,
        )
        return

    lines = ["Your MCP servers:"]
    for c in sorted(configs, key=lambda c: c.name):
        lines.append(f"• {c.name} — {c.params.url} ({c.params.auth_scheme})")
    await message.reply("\n".join(lines), parse_mode=None)


async def remove_mcp_handler(
    message: Message,
    tool_manager_resolver: ToolManagerResolver,
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

    user_id = f"tg:{message.from_user.id}"
    persistence = TelegramMCPPersistenceService()

    tool_manager = await tool_manager_resolver(message)
    removed_live = False
    if tool_manager is not None:
        try:
            removed_live = await tool_manager.remove_mcp_server(name)
        except Exception:  # noqa: BLE001
            logger.exception(
                "remove_mcp: failed to disconnect %r for %s", name, user_id
            )

    removed, vault_cred_name = await persistence.remove(user_id, name)

    # Delete Vault entry (best-effort — missing entry is not an error)
    if vault_cred_name:
        try:
            await delete_vault_credential(user_id, vault_cred_name)
        except KeyError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception(
                "remove_mcp: failed to delete Vault entry for %r / %s",
                name,
                user_id,
            )

    if removed or removed_live:
        await message.reply(f"Removed MCP server {name!r}.", parse_mode=None)
    else:
        await message.reply(
            f"No MCP server named {name!r} was found. "
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
) -> None:
    """Wire the three MCP commands on *router*.

    Args:
        router: aiogram ``Router`` owned by the Telegram wrapper.
        tool_manager_resolver: async callable returning the per-user
            ``ToolManager`` for a given ``Message`` (or ``None`` when
            the user's session has not been initialized yet). Provided
            by the wrapper so the handlers stay decoupled from the
            singleton/per-user-agent mode detail.
    """

    async def _add(message: Message) -> None:
        await add_mcp_handler(message, tool_manager_resolver)

    async def _list(message: Message) -> None:
        await list_mcp_handler(message)

    async def _remove(message: Message) -> None:
        await remove_mcp_handler(message, tool_manager_resolver)

    router.message.register(_add, Command("add_mcp"))
    router.message.register(_list, Command("list_mcp"))
    router.message.register(_remove, Command("remove_mcp"))
