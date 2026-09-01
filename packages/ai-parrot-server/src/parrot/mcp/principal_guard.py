"""Principal resolution + tenant binding + `_pctx_var` publication.

FEAT-477, Module 3 (identity half — spec §2 Overview #4, §3 Module 3, §8).

Converts whichever auth path fired (`AuthMethod.OAUTH2_EXTERNAL` via
introspection, or `AuthMethod.API_KEY`) into a single `PermissionContext`
and publishes it on the **existing** `_pctx_var` contextvar
(`parrot/auth/context.py:33`) — the same one `DatasetManager` and
`DatabaseQueryTool` already read, so every downstream guard inherits the
MCP caller's identity with no signature changes anywhere.

**Tenant precedence (spec §8, with its correction applied):**
``token_info["tenant_id"]`` -> ``token_info["org_id"]`` ->
``AgentMCPMountConfig.default_tenant_id`` -> **fail closed** (401). Neither
claim is populated by navigator-auth today — the mount default is the only
live path — but the claim lookups are written forward-compatibly. The wire
``client_id`` is the ``client_uid`` and is **never** used as a tenant.

PBAC decisions, audit-ledger persistence, and re-verification are TASK-2605's
job; this module only exposes an ``audit_hook`` callback so a resolution
failure can be recorded by whatever TASK-2605 wires in without this module
importing (and thus coupling to) ``security/audit_ledger.py`` directly.
"""
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from aiohttp import web
from parrot.auth.context import _pctx_var
from parrot.auth.permission import PermissionContext, build_principal_context

logger = logging.getLogger("Parrot.MCP.PrincipalGuard")

#: Originating channel recorded on every `PermissionContext` built here.
MCP_CHANNEL = "mcp"

#: Audit hook: called with a decision payload (at minimum `{"decision": ...}`)
#: on a resolution failure. Sync or async. `None` (default) means "don't
#: audit yet" — TASK-2605 wires in the real `AuditLedger`-backed hook.
AuditHook = Callable[[dict[str, Any]], "None | Awaitable[None]"]


def resolve_tenant(token_info: dict[str, Any], mount_config: Any) -> str | None:
    """Resolve the tenant id for a call, per the spec §8 precedence.

    Args:
        token_info: The `token_info` dict from `request["mcp_user"]`
            (present for `AuthMethod.OAUTH2_EXTERNAL`; empty for
            `AuthMethod.API_KEY`, which carries no token introspection).
        mount_config: The `AgentMCPMountConfig` for this mount, read for
            its `default_tenant_id` fallback.

    Returns:
        The resolved tenant id, or `None` if every path is exhausted
        (caller must fail closed — never default to `"default"`/`""`).
    """
    # client_id is NEVER a tenant — it is the wire client_uid.
    return (
        token_info.get("tenant_id")  # forward-compat: navigator-auth doesn't emit this yet
        or token_info.get("org_id")  # forward-compat: navigator-auth doesn't emit this yet
        or getattr(mount_config, "default_tenant_id", None)  # the only live path today
    )


async def _run_audit_hook(audit_hook: AuditHook | None, payload: dict[str, Any]) -> None:
    """Invoke `audit_hook` with `payload`, awaiting it if it returns one.

    Args:
        audit_hook: The hook to call, or `None` (no-op).
        payload: The decision payload to record.
    """
    if audit_hook is None:
        return
    result = audit_hook(payload)
    if result is not None and hasattr(result, "__await__"):
        await result


def _unauthorized(message: str) -> web.Response:
    """Build a 401 response matching `RemoteMCPServerBase._unauthorized_response`'s shape.

    Args:
        message: Human-readable error description.

    Returns:
        A 401 `web.Response` with the same JSON envelope the transport's
        own auth failures use.
    """
    return web.json_response(
        {"error": "unauthorized", "error_description": message},
        status=401,
        headers={"WWW-Authenticate": 'Bearer realm="mcp"'},
    )


async def resolve_principal(
    request: Any,
    mount_config: Any,
    *,
    audit_hook: AuditHook | None = None,
) -> "PermissionContext | web.Response":
    """Resolve `request["mcp_user"]` into a `PermissionContext`.

    Both auth paths (`AuthMethod.OAUTH2_EXTERNAL`'s introspection and
    `AuthMethod.API_KEY`) yield an equivalent `PermissionContext` — same
    shape, same `channel`.

    Args:
        request: The inbound request. Only `request.get("mcp_user")` is
            read — any object exposing that (a real `aiohttp.web.Request`
            populated by `_authenticate_request`, or a plain dict in tests)
            works.
        mount_config: The `AgentMCPMountConfig` for this mount.
        audit_hook: Optional callback invoked with a decision payload on
            failure (e.g. `{"decision": "principal_unresolved", ...}`).
            `None` (default) skips auditing — TASK-2605 wires the real
            `AuditLedger`-backed hook in.

    Returns:
        A `PermissionContext` on success, or a 401 `web.Response` when the
        principal or tenant cannot be resolved (fail closed).
    """
    mcp_user = request.get("mcp_user")
    if not isinstance(mcp_user, dict) or not mcp_user.get("user_id"):
        await _run_audit_hook(
            audit_hook, {"decision": "principal_unresolved", "reason": "no mcp_user"}
        )
        return _unauthorized("No authenticated principal for this request")

    principal = mcp_user["user_id"]
    token_info = mcp_user.get("token_info") or {}
    tenant_id = resolve_tenant(token_info, mount_config)
    if not tenant_id:
        await _run_audit_hook(
            audit_hook,
            {
                "decision": "principal_unresolved",
                "reason": "tenant could not be resolved",
                "principal": principal,
            },
        )
        return _unauthorized("Tenant could not be resolved for this request")

    roles = frozenset(mcp_user.get("scopes") or [])
    return build_principal_context(
        principal, channel=MCP_CHANNEL, tenant_id=tenant_id, roles=roles
    )


def runtime_key(pctx: PermissionContext) -> tuple[str, str]:
    """Build the per-call runtime binding key `(tenant_id, principal)`.

    Args:
        pctx: The resolved `PermissionContext`.

    Returns:
        `(tenant_id, principal)`, for scoping downstream per-call state
        (rate limiting, job handles, audit correlation, ...).
    """
    return (pctx.tenant_id, pctx.user_id)


@contextlib.asynccontextmanager
async def published_principal(pctx: PermissionContext) -> AsyncIterator[PermissionContext]:
    """Publish `pctx` on `_pctx_var` for the duration of the `async with` block.

    Always resets the contextvar in a `finally` — a leaked principal
    across requests is a security bug.

    Args:
        pctx: The `PermissionContext` to publish.

    Yields:
        The same `pctx`, for convenience.
    """
    token = _pctx_var.set(pctx)
    try:
        yield pctx
    finally:
        _pctx_var.reset(token)


__all__ = [
    "MCP_CHANNEL",
    "AuditHook",
    "published_principal",
    "resolve_principal",
    "resolve_tenant",
    "runtime_key",
]
