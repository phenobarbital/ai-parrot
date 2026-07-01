"""CLI identity bootstrap for the O365 device-code broker seam (FEAT-266).

The O365 device-code resolver (``O365DeviceCodeCredentialResolver``) fails
closed without a canonical per-user identity (spec §1/§7). The CLI is the
only surface for device-code (Telegram explicitly excluded), so this module
reads the explicit Entra principal from the ``O365_PRINCIPAL`` environment
variable, normalizes it via :class:`~parrot.auth.identity.CanonicalIdentityMapper`,
and builds the :class:`~parrot.auth.permission.PermissionContext` that
``AbstractBot.ask(permission_context=...)`` threads through to the
``ToolManager`` → ``AbstractTool`` credential seam (see
``tools/manager.py`` around the ``_cred_channel``/``_cred_user_id``
injection and ``tools/abstract.py``'s broker gate).
"""
from __future__ import annotations

import os
from typing import Optional

from parrot.auth.identity import CanonicalIdentityMapper
from parrot.auth.permission import PermissionContext, UserSession

#: Environment variable carrying the CLI's explicit Entra principal
#: (email address or Entra Object ID) for the O365 device-code flow.
O365_PRINCIPAL_ENV_VAR: str = "O365_PRINCIPAL"

#: Surface channel used for every CLI-originated permission context.
CLI_CHANNEL: str = "cli"


def resolve_cli_o365_principal() -> str:
    """Read and normalize the CLI's canonical O365 principal from the environment.

    Returns:
        The canonical identity string (lower-cased email or Entra OID).

    Raises:
        RuntimeError: ``O365_PRINCIPAL`` is unset/blank, or does not
            normalize to a canonical identity. Fails closed — the
            device-code resolver must never operate under an anonymous
            vault key.
    """
    raw = (os.environ.get(O365_PRINCIPAL_ENV_VAR) or "").strip()
    if not raw:
        raise RuntimeError(
            f"{O365_PRINCIPAL_ENV_VAR} is not set. The O365 device-code CLI "
            "flow requires an explicit Entra principal (email or Object ID) "
            "to resolve credentials for — refusing to proceed with an "
            "anonymous identity."
        )

    canonical = CanonicalIdentityMapper.to_canonical({"oid": raw, "email": raw})
    if not canonical:
        raise RuntimeError(
            f"{O365_PRINCIPAL_ENV_VAR}={raw!r} did not normalize to a "
            "canonical identity — expected an email address or an Entra "
            "Object ID (UUID)."
        )
    return canonical


def build_cli_permission_context(user_id: Optional[str] = None) -> PermissionContext:
    """Build the CLI ``PermissionContext`` for the O365 device-code broker seam.

    Args:
        user_id: Optional pre-resolved canonical identity. When omitted,
            it is resolved via :func:`resolve_cli_o365_principal` (reads
            ``O365_PRINCIPAL`` from the environment).

    Returns:
        A :class:`~parrot.auth.permission.PermissionContext` with
        ``channel="cli"`` and the canonical ``user_id``, ready to pass to
        ``AbstractBot.ask(permission_context=...)`` /
        ``AbstractBot.ask_stream(permission_context=...)``.

    Raises:
        RuntimeError: No principal could be resolved (fail closed —
            propagated from :func:`resolve_cli_o365_principal`).
    """
    canonical = user_id or resolve_cli_o365_principal()
    session = UserSession(user_id=canonical, tenant_id=CLI_CHANNEL, roles=frozenset())
    return PermissionContext(session=session, channel=CLI_CHANNEL)


def bot_declares_o365_device_code(bot: object) -> bool:
    """Return True when ``bot`` declares an ``o365``/``device_code`` credential.

    Used by the CLI entry point (``parrot.cli.agent_repl``) to decide
    whether to bootstrap a device-code ``PermissionContext`` (and therefore
    enforce ``O365_PRINCIPAL``) for this particular agent — agents that
    don't declare the o365 device-code provider are completely unaffected.

    Args:
        bot: The loaded agent instance (an ``AbstractBot``).

    Returns:
        True if any entry in ``bot._credentials`` declares
        ``provider="o365"`` with ``auth="device_code"``.
    """
    for cfg in getattr(bot, "_credentials", None) or []:
        if getattr(cfg, "provider", None) == "o365" and getattr(cfg, "auth", None) == "device_code":
            return True
    return False
