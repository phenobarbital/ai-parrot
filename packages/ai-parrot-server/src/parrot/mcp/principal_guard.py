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

**PBAC filtering, re-verification and audit (FEAT-477 TASK-2605, spec OQ6,
goal G6).** ``PBACGuard`` filters ``tools/list`` per principal and
re-verifies every ``tools/call`` against the *same* canonical resource,
``mcp:agent:{name}:tool:{tool}`` — the list is never trusted as an
authorization record. Deny-by-default throughout, consistent with
``setup_pbac()``'s ``PolicyEffect.DENY``: navigator-auth's upstream access
gate is keyed ``(user_id, client_uid)`` and cannot express a per-agent
grant, so this is the **only** place per-agent/per-tool authorization can
happen (OQ6 — load-bearing, not defense-in-depth).

Every ``tools/call`` is recorded via an injectable ``audit_sink`` callback
carrying exactly the fields the spec requires — principal, agent, tool,
argument hash (never raw arguments), decision, duration. **Deliberately not
a direct call to** ``parrot.security.audit_ledger.AuditLedger.append()``:
that ledger's schema (``user_id, channel, tool, provider,
key_fingerprint``, derived from real ``credential_material``) exists for
*credentialed tool invocations* (a resolved secret's fingerprint) and has
no field for a PBAC decision, a duration, or an argument hash — forcing
those into ``provider``/``credential_material`` would either misrepresent
the entry as a credential event or silently discard the very fields this
task must record. ``audit_ledger_sink()`` below provides an explicit,
documented bridge for callers that still want every PBAC decision
mirrored into a shared ``AuditLedger`` for correlation. (See this task's
Completion Note for the full rationale.) ``parrot.auth.audit`` — the
**deprecated** module — is never imported here.
"""

import contextlib
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from aiohttp import web
from parrot.auth.context import _pctx_var
from parrot.auth.permission import PermissionContext, build_principal_context
from parrot.mcp.result_policy import (
    MCPToolError,
    apply_size_policy,
    resolve_cap,
    run_with_deadline,
)

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
        await _run_audit_hook(audit_hook, {"decision": "principal_unresolved", "reason": "no mcp_user"})
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
    return build_principal_context(principal, channel=MCP_CHANNEL, tenant_id=tenant_id, roles=roles)


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


# ---------------------------------------------------------------------------
# TASK-2605: PBAC filtering, re-verification and audit
# ---------------------------------------------------------------------------


#: Canonical PBAC resource for one agent/tool pair. Both the per-agent and
#: aggregate `{agent}__{tool}` name forms resolve to the same string — the
#: aggregate is naming sugar, never its own authorization path. Mirrors
#: `AgentMCPMount.canonical_resource` (TASK-2602) by algorithm, not by
#: import — a per-request guard module has no business depending upward on
#: the mount object that constructs it.
def resource_for(agent_name: str, tool_name: str) -> str:
    """Build the canonical PBAC resource string for `agent_name`/`tool_name`.

    Args:
        agent_name: Configured agent name.
        tool_name: Tool name as registered (per-agent form).

    Returns:
        `mcp:agent:{agent_name}:tool:{tool_name}`.
    """
    return f"mcp:agent:{agent_name}:tool:{tool_name}"


def resource_from_aggregate(aggregate_name: str) -> str:
    """Resolve an aggregate `{agent}__{tool}` name to its canonical resource.

    Args:
        aggregate_name: A name published on the aggregate endpoint.

    Returns:
        The same canonical resource string `resource_for` would produce
        for the equivalent per-agent name.

    Raises:
        ValueError: If `aggregate_name` does not contain the `__` separator.
    """
    agent_name, sep, tool_name = aggregate_name.partition("__")
    if not sep:
        raise ValueError(f"{aggregate_name!r} is not an aggregate name " "('{agent}__{tool}' expected)")
    return resource_for(agent_name, tool_name)


def _hash_arguments(arguments: dict[str, Any] | None) -> str:
    """Hash call arguments for the audit trail — never log raw values.

    Args:
        arguments: The `tools/call` `arguments` payload, if any.

    Returns:
        A SHA-256 hex digest of the canonicalized (sorted-key) JSON
        representation of `arguments`.
    """
    canonical = json.dumps(arguments or {}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _mcp_error(message: str) -> dict[str, Any]:
    """Build a clean MCP tool-result error — never a stack trace.

    Args:
        message: Human-readable, non-sensitive error description.

    Returns:
        An `{"isError": True, ...}` payload matching `MCPToolAdapter`'s
        own error shape.
    """
    return {"content": [{"type": "text", "text": message}], "isError": True}


#: `(agent_name, tool_name) -> bool` (sync or async) — PBAC resolver hook.
#: Mirrors `parrot.auth.resolver.PBACPermissionResolver.can_execute`'s
#: shape (`can_execute(context, tool_name, required_permissions) -> bool`);
#: pass a bound `resolver.can_execute` (with `required_permissions=set()`)
#: or an equivalent async callable.
PBACResolver = Callable[[PermissionContext, str, "set[str]"], "bool | Awaitable[bool]"]

#: Sink for one audited `tools/call` decision. Called with
#: `{"principal", "tenant_id", "agent", "tool", "argument_hash",
#: "decision", "duration"}`. Sync or async. `None` (default) only logs.
AuditSink = Callable[[dict[str, Any]], "None | Awaitable[None]"]


def audit_ledger_sink(ledger: Any) -> AuditSink:
    """Bridge PBAC audit entries into a shared `AuditLedger` (best effort).

    `AuditLedger.append()` (`security/audit_ledger.py:338`) is shaped for
    *credentialed tool invocations* — `user_id`, `channel`, `tool`,
    `provider`, and a `key_fingerprint` derived from real credential
    material. It has no field for a PBAC decision, a duration, or an
    argument hash, so this bridge folds the decision into `provider`
    (a free-text field) and the duration/argument hash into
    `credential_material` purely as fingerprint input — `credential_material`
    is **not** a real credential here, only opaque correlation input, and
    the ledger entry itself does not literally carry the duration/hash
    back out. Callers that need those fields queryable in plain text
    should read the entries handed to their own `audit_sink` instead;
    this bridge is for teams that specifically want every PBAC decision
    to *also* show up in the shared ledger for cross-referencing.

    Args:
        ledger: An `AuditLedger` instance.

    Returns:
        An `AuditSink` callable suitable for `PBACGuard(audit_sink=...)`.
    """

    async def _sink(entry: dict[str, Any]) -> None:
        await ledger.append(
            user_id=str(entry["principal"]),
            channel=f"mcp:{entry['agent']}",
            tool=str(entry["tool"]),
            provider=f"pbac:{entry['decision']}",
            credential_material=(f"{entry['argument_hash']}:{entry['duration']:.6f}"),
        )

    return _sink


async def _call_hook(hook: Callable[..., Any] | None, *args: Any) -> Any:
    """Call `hook(*args)`, awaiting the result if it is awaitable.

    Args:
        hook: The callable to invoke, or `None` (no-op, returns `None`).
        *args: Positional arguments to pass to `hook`.

    Returns:
        `hook`'s (possibly awaited) return value, or `None` if `hook` is `None`.
    """
    if hook is None:
        return None
    result = hook(*args)
    if result is not None and hasattr(result, "__await__"):
        return await result
    return result


def _apply_result_size_policy(mcp_result: dict[str, Any], cap: int) -> dict[str, Any]:
    """Apply `result_policy.apply_size_policy` to an MCP `tools/call` response.

    `MCPToolAdapter.execute()` (`mcp/adapter.py:59`) already converted the
    tool's raw result into the MCP `{"content": [...], "isError": ...}`
    envelope by the time this guard sees it. The structured payload
    (dict/list) a tool returned lives, JSON-serialized, in the first
    content block's `text` — this unwraps it, applies the size policy, and
    re-serializes the (possibly truncated) payload back in place. A plain
    string result is size-policed as a string via the same function.

    Args:
        mcp_result: The MCP `tools/call` response (never an error result —
            callers only invoke this on success).
        cap: Approximate token budget (see `result_policy.resolve_cap`).

    Returns:
        `mcp_result` unchanged if it does not need policing, or with its
        first content block's `text` replaced by the size-policed,
        JSON-serialized payload.
    """
    content = mcp_result.get("content")
    if not content or not isinstance(content, list) or not isinstance(content[0], dict):
        return mcp_result
    text = content[0].get("text")
    if text is None:
        return mcp_result
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        payload = text
    policed = apply_size_policy(payload, cap)
    if not policed["truncated"]:
        return mcp_result
    new_content = [
        {**content[0], "text": json.dumps(policed, sort_keys=True, default=str)},
        *content[1:],
    ]
    return {**mcp_result, "content": new_content}


class PBACGuard:
    """Per-agent PBAC enforcement wrapping one mounted server's tools.

    Filters `tools/list` per principal and re-verifies every `tools/call`
    against the same canonical resource the list was filtered against —
    the list is never trusted as an authorization record (spec OQ6).
    Deny-by-default: no resolver configured, a resolver error, or an
    unknown tool name all deny.

    Args:
        agent_name: Configured agent name (used to build canonical
            resources and audit entries).
        server: The per-agent server whose `.tools` (`dict[str,
            MCPToolAdapter]`) this guard filters/re-verifies against.
        resolver: Optional `(pctx, resource, required_permissions) ->
            bool` PBAC resolver — the `PBACPermissionResolver.can_execute`
            shape. `None` (default) denies every call (deny-by-default
            when PBAC is not wired in yet).
        audit_sink: Optional callback invoked with every `tools/call`
            decision (see `AuditSink`). `None` (default) only logs.
        mount_config: Optional `AgentMCPMountConfig` (TASK-2601), read for
            its `max_result_tokens` mount-default cap and
            `call_deadline_seconds` (spec §3 Module 3, goals G7/G8 —
            TASK-2606). `None` falls back to `result_policy`'s own
            defaults (`DEFAULT_MAX_RESULT_TOKENS`, 240s).
        resource_resolver: Optional `(tool_name) -> str` overriding how a
            tool name is turned into a canonical PBAC resource. Defaults
            to `resource_for(agent_name, tool_name)` — the single-agent
            shape. Pass `resource_from_aggregate` (or an equivalent) for a
            guard wrapping an *aggregate* server, whose tool names already
            carry the owning agent as a `{agent}__{tool}` prefix; without
            this override an aggregate guard would double-prefix its own
            `agent_name` and never resolve to the real per-agent resource.
    """

    #: Fallback deadline when `mount_config` carries none — matches
    #: `AgentMCPMountConfig.call_deadline_seconds`'s own default.
    _DEFAULT_DEADLINE_SECONDS: float = 240.0

    def __init__(
        self,
        agent_name: str,
        server: Any,
        resolver: PBACResolver | None = None,
        audit_sink: AuditSink | None = None,
        mount_config: Any = None,
        resource_resolver: "Callable[[str], str] | None" = None,
    ) -> None:
        self._agent_name = agent_name
        self._server = server
        self._resolver = resolver
        self._audit_sink = audit_sink
        self._mount_config = mount_config
        self._resource_resolver = resource_resolver

    def resource_for(self, tool_name: str) -> str:
        """Build the canonical PBAC resource for `tool_name`.

        Uses `resource_resolver` when this guard was built with one
        (e.g. an aggregate guard's `resource_from_aggregate`); otherwise
        the module-level `resource_for`, bound to this guard's agent.
        """
        if self._resource_resolver is not None:
            return self._resource_resolver(tool_name)
        return resource_for(self._agent_name, tool_name)

    def resource_from_aggregate(self, aggregate_name: str) -> str:
        """See module-level `resource_from_aggregate` (agent-agnostic)."""
        return resource_from_aggregate(aggregate_name)

    async def _permitted(self, pctx: PermissionContext, tool_name: str) -> bool:
        """Evaluate whether `pctx` may call `tool_name` (deny-by-default).

        Args:
            pctx: The caller's resolved `PermissionContext`.
            tool_name: Candidate tool name.

        Returns:
            Whether the call is permitted.
        """
        if self._resolver is None:
            return False
        resource = self.resource_for(tool_name)
        try:
            return bool(await _call_hook(self._resolver, pctx, resource, set()))
        except Exception:
            logger.exception(
                "PBAC resolver error for agent=%s tool=%s — denying (fail closed)",
                self._agent_name,
                tool_name,
            )
            return False

    async def _audit(
        self,
        pctx: PermissionContext,
        tool_name: str,
        arguments: dict[str, Any] | None,
        decision: str,
        duration: float,
    ) -> None:
        """Record one `tools/call` decision.

        Args:
            pctx: The caller's resolved `PermissionContext`.
            tool_name: The tool that was (attempted to be) called.
            arguments: The raw call arguments — hashed, never logged raw.
            decision: `"allow"` or `"deny"`.
            duration: Wall-clock seconds the decision + call took.
        """
        entry = {
            "principal": pctx.user_id,
            "tenant_id": pctx.tenant_id,
            "agent": self._agent_name,
            "tool": tool_name,
            "argument_hash": _hash_arguments(arguments),
            "decision": decision,
            "duration": duration,
        }
        logger.info(
            "MCP tools/call audit: agent=%s tool=%s principal=%s decision=%s " "duration=%.4fs",
            self._agent_name,
            tool_name,
            pctx.user_id,
            decision,
            duration,
        )
        await _call_hook(self._audit_sink, entry)

    async def tools_list(self, params: dict[str, Any], pctx: PermissionContext) -> dict[str, Any]:
        """Policy-filtered `tools/list` — omits tools `pctx` may not call.

        Args:
            params: The `tools/list` request params (unused; kept for
                interface symmetry with `MCPServerBase.handle_tools_list`).
            pctx: The caller's resolved `PermissionContext`.

        Returns:
            `{"tools": [...]}`, restricted to permitted tools.
        """
        visible = []
        for tool_name, adapter in self._server.tools.items():
            if await self._permitted(pctx, tool_name):
                visible.append(adapter.to_mcp_tool_definition())
        return {"tools": visible}

    async def tools_call(self, params: dict[str, Any], pctx: PermissionContext) -> dict[str, Any]:
        """Re-verified, audited, size/deadline-policed `tools/call`.

        Never trusts `tools/list` as an authorization record — re-evaluates
        policy against the same canonical resource independently. Deny-by
        -default for an unknown tool name. Wraps adapter execution with
        `call_deadline_seconds` (TASK-2606, G7) and applies the per-tool
        (else mount-default) result-size policy to a successful response
        (TASK-2606, G8).

        Args:
            params: The `tools/call` request params (`name`, `arguments`).
            pctx: The caller's resolved `PermissionContext`.

        Returns:
            The (possibly size-policed) tool result on success, or a clean
            `{"isError": True}` payload (never a stack trace) on denial or
            timeout.
        """
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        start = time.monotonic()

        known = tool_name in self._server.tools
        allowed = known and await self._permitted(pctx, tool_name)
        decision = "allow" if allowed else "deny"

        if not allowed:
            duration = time.monotonic() - start
            await self._audit(pctx, tool_name, arguments, decision, duration)
            return _mcp_error(f"Not permitted to call tool {tool_name!r}")

        deadline = getattr(self._mount_config, "call_deadline_seconds", None) or self._DEFAULT_DEADLINE_SECONDS
        try:
            result = await run_with_deadline(lambda: self._server.handle_tools_call(params), deadline, tool_name)
        except MCPToolError as exc:
            result = _mcp_error(str(exc))
        finally:
            duration = time.monotonic() - start
            await self._audit(pctx, tool_name, arguments, decision, duration)

        if not result.get("isError"):
            declaration = getattr(self._server.tools[tool_name], "_declaration", None)
            cap = resolve_cap(declaration, self._mount_config)
            result = _apply_result_size_policy(result, cap)
        return result


__all__ = [
    "MCP_CHANNEL",
    "AuditHook",
    "AuditSink",
    "PBACGuard",
    "PBACResolver",
    "audit_ledger_sink",
    "published_principal",
    "resolve_principal",
    "resolve_tenant",
    "resource_for",
    "resource_from_aggregate",
    "runtime_key",
]
