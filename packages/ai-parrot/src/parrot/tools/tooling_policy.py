"""Host-owned tenant tooling policy (FEAT-622 M7, review R1). Pure and synchronous: no I/O."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Collection, Iterable, Mapping, MutableMapping
from typing import Any, ClassVar, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from parrot.tools.resolver import get_toolkit_resolver
from parrot.tools.spec import (
    SECRET_MASK,
    AgentMCPServerSpec,
    NormalizedTooling,
    mcp_vault_name,
    toolkit_vault_name,
)

logger = logging.getLogger(__name__)

TenantMCPTransport = Literal["http", "sse", "streamable-http"]
ToolingRefusal = Literal[
    "local_execution",
    "transport_not_permitted",
    "endpoint_not_allowed",
    "mcp_server_unknown",
    "field_not_permitted",
    "secret_ref_not_permitted",
    "builtin_not_permitted",
    "toolkit_unavailable",
    "tool_params_not_permitted",
]
_POLICY_KEY = "parrot.tenant_tooling_policy"
_TENANT_MCP_FIELDS = frozenset(
    {
        "name",
        "url",
        "transport",
        "description",
        "allowed_tools",
        "blocked_tools",
        "auth_type",
        "headers",
        "auth_config",
        "timeout",
    }
)
_LOCAL_FIELDS = ("command", "args", "env", "socket_path")
_SECRET_BLOCKED_PHASES = frozenset({"write", "activate", "attach"})


class TenantToolingRefused(Exception):
    """Raised when tenant tooling is not permitted (HTTP 422 on writes/assign, 403 on execute)."""

    code: ClassVar[str] = "tooling_not_permitted"

    def __init__(self, reason: ToolingRefusal, *, item: str) -> None:
        self.reason: ToolingRefusal = reason
        self.item = item
        super().__init__(f"{self.code}: {reason} ({item})")


class ToolParamRefused(TenantToolingRefused):
    """A host toolkit-parameter hook refuses constructor parameters (PA-9): 422 ``tooling_not_permitted``, reason
    ``tool_params_not_permitted`` and ``details.params``; a stored agent that carries them fails its build closed."""

    def __init__(self, params: Iterable[str] = (), *, item: str = "") -> None:
        super().__init__("tool_params_not_permitted", item=item)
        self.params: list[str] = sorted({str(name) for name in params})


class HostMCPServer(BaseModel, frozen=True):
    """An MCP server registered by the host; tenants may reference it by name only."""

    name: str
    config: dict[str, Any]
    tenant_fields: frozenset[str] = frozenset({"allowed_tools", "blocked_tools", "description"})


class ToolingSubject(BaseModel, frozen=True):
    """Who/what/when a tooling check applies to."""

    tenant: str | None
    agent_id: UUID | None
    actor: str | None
    phase: Literal["write", "activate", "build", "attach", "execute"]
    held: frozenset[str] = frozenset()
    """Lower-cased slugs the write leaves untouched: exempt from the per-tenant allow-lists only (delta check)."""


def _split_https(url: str) -> tuple[str, int, str] | None:
    """Return ``(host, port, path)`` for an acceptable https URL, else ``None``."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port or 443
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return None
    segments = parts.path.split("/")
    if any(seg == ".." or seg.lower() in {"%2e", "%2e%2e", ".%2e", "%2e."} for seg in segments):
        return None
    return parts.hostname.lower(), port, parts.path or "/"


def _normalise_prefix(raw: str) -> str:
    split = _split_https(raw)
    if split is None:
        raise ValueError(f"mcp_endpoints entry must be an absolute https URL without userinfo: {raw!r}")
    host, port, path = split
    return f"https://{host}:{port}{path if path.endswith('/') else path + '/'}"


def detect_transport(config: Mapping[str, Any]) -> str | None:
    """Mirror ``MCPClient._detect_transport`` as a pure function (``None`` = undetectable)."""
    transport = config.get("transport", "auto")
    if transport != "auto":
        return str(transport)
    if config.get("socket_path"):
        return "unix"
    url = config.get("url")
    if url:
        return "sse" if ("events" in url or "sse" in url) else "http"
    if config.get("command"):
        return "stdio"
    return None


class TenantToolingPolicy(BaseModel, frozen=True):
    """Frozen host policy; the default is :meth:`deny_all`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    mcp_servers: Mapping[str, HostMCPServer] = {}
    mcp_endpoints: tuple[str, ...] = ()
    mcp_transports: frozenset[TenantMCPTransport] = frozenset({"http", "sse", "streamable-http"})
    builtin_tools: frozenset[str] = frozenset()
    host_toolkits: bool = True
    apply_to_global: bool = False
    tenant_toolkits: Callable[[str], Collection[str] | None] | None = None
    """Host callback: enabled host-toolkit slugs for a tenant, ``None`` = unrestricted. Sync, no I/O."""
    tenant_builtin_tools: Callable[[str], Collection[str] | None] | None = None
    """PA-5: like ``tenant_toolkits`` but for BUILT-IN slugs (those also in ``builtin_tools``): the per-tenant
    allow-list narrows the global ``builtin_tools`` set. ``None`` = no per-tenant narrowing. Same semantics:
    fail closed when it errors, ``held`` stored tooling still builds (refused at call time), phase ``build``
    and the tenant-less global partition are never refused."""

    @field_validator("mcp_endpoints")
    @classmethod
    def _normalise_endpoints(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_normalise_prefix(item) for item in value)

    @classmethod
    def deny_all(cls) -> "TenantToolingPolicy":
        """Host toolkits only, no MCP, no built-ins."""
        return cls()

    def check_tool(self, slug: str, *, subject: ToolingSubject) -> None:
        """Refuse a slug that is unknown, or a non-host tool outside ``builtin_tools``."""
        entry = get_toolkit_resolver().entry(slug)
        if entry is None:
            raise TenantToolingRefused("toolkit_unavailable", item=slug)
        if entry.is_host:
            if not self.host_toolkits:
                raise TenantToolingRefused("toolkit_unavailable", item=slug)
            self._check_tenant_toolkit(slug, subject)
            return
        if slug.lower() not in {name.lower() for name in self.builtin_tools}:
            raise TenantToolingRefused("builtin_not_permitted", item=slug)
        self._check_tenant_builtin(slug, subject)

    def _check_tenant_toolkit(self, slug: str, subject: ToolingSubject) -> None:
        """Per-tenant host-toolkit allow-list; never applied to phase ``build`` (a stored agent must still build)."""
        # no tenant (global partition) is unrestricted by design; ``build`` is never refused (see above)
        if self.tenant_toolkits is None or not subject.tenant or subject.phase == "build":
            return
        if slug.lower() in subject.held:  # stored, unchanged tooling: a disabled toolkit is refused at call time instead
            return
        enabled = self.enabled_toolkits(subject.tenant)
        if enabled is not None and slug.lower() not in enabled:
            raise TenantToolingRefused("toolkit_unavailable", item=slug)

    def _check_tenant_builtin(self, slug: str, subject: ToolingSubject) -> None:
        """Per-tenant built-in allow-list (PA-5); same rules as :meth:`_check_tenant_toolkit`."""
        if self.tenant_builtin_tools is None or not subject.tenant or subject.phase == "build":
            return
        if slug.lower() in subject.held:  # stored, unchanged tooling: a disabled built-in is refused at call time
            return
        enabled = self.enabled_builtin_tools(subject.tenant)
        if enabled is not None and slug.lower() not in enabled:
            raise TenantToolingRefused("toolkit_unavailable", item=slug)

    def pinned_for(self, subject: ToolingSubject) -> "TenantToolingPolicy":
        """This policy with the tenant's allow-lists (host toolkits AND built-ins) resolved ONCE: each callback runs
        (and logs a failure) once per request, however many slugs are then checked. Returns ``self`` when no
        allow-list applies."""
        if not subject.tenant or subject.phase == "build":
            return self
        update: dict[str, Any] = {}
        if self.tenant_toolkits is not None:
            enabled = self.enabled_toolkits(subject.tenant)
            update["tenant_toolkits"] = lambda _tenant: enabled
        if self.tenant_builtin_tools is not None:
            enabled_builtin = self.enabled_builtin_tools(subject.tenant)
            update["tenant_builtin_tools"] = lambda _tenant: enabled_builtin
        return self.model_copy(update=update) if update else self

    def enabled_toolkits(self, tenant: str) -> frozenset[str] | None:
        """Lower-cased enabled host-toolkit slugs for ``tenant``; ``None`` = unrestricted.

        Anything the callback returns that is not ``None``, a ``str`` (one slug, never a substring pool) or an
        iterable of names — a coroutine, a bool, an int — and any exception it raises, fails CLOSED (empty set).
        """
        return self._resolve_allow_list(self.tenant_toolkits, tenant, "tenant_toolkits")

    def enabled_builtin_tools(self, tenant: str) -> frozenset[str] | None:
        """Lower-cased built-in slugs ``tenant`` may use (PA-5); ``None`` = no per-tenant narrowing. Fails closed."""
        return self._resolve_allow_list(self.tenant_builtin_tools, tenant, "tenant_builtin_tools")

    @staticmethod
    def _resolve_allow_list(
        callback: Callable[[str], Collection[str] | None] | None, tenant: str, name: str
    ) -> frozenset[str] | None:
        """Run an allow-list ``callback`` for ``tenant``; the shared fail-closed rules of both allow-lists."""
        if callback is None:
            return None
        try:
            result = callback(tenant)
            if result is None:
                return None
            if isinstance(result, str):
                return frozenset({result.lower()})
            if inspect.isawaitable(result):
                getattr(result, "close", lambda: None)()  # an async callback is never awaited: no "never awaited" noise
                raise TypeError(f"{name} must be synchronous")
            if not isinstance(result, Iterable):
                raise TypeError(f"{name} returned {type(result).__name__}, expected a collection of slugs")
            return frozenset(str(item).lower() for item in result)
        except Exception:  # pylint: disable=broad-except
            logger.exception("%s callback failed for tenant %r; refusing (fail closed)", name, tenant)
            return frozenset()

    def resolve_mcp(self, config: Mapping[str, Any], *, subject: ToolingSubject) -> dict[str, Any]:
        """Spec §2 checks 1–4 on the FINAL kwargs; returns MCPServerConfig kwargs."""
        name = str(config.get("name", ""))
        if name in self.mcp_servers:
            return self._check_named_host(self.mcp_servers[name], config)
        self._check_local_execution(config)
        self._check_fields(config)
        self._check_endpoint(config)
        return dict(config)

    def check_tooling(self, tooling: NormalizedTooling, *, subject: ToolingSubject, owner: str | None = None) -> None:
        """Check every tool, toolkit and MCP spec of ``tooling`` (and secret references by phase)."""
        policy = self.pinned_for(subject)  # one allow-list resolution for the whole tooling
        for tool in tooling.tools:
            slug = tool if isinstance(tool, str) else getattr(tool, "name", None)
            if not isinstance(slug, str):
                raise TenantToolingRefused("toolkit_unavailable", item=repr(tool)[:80])
            policy.check_tool(slug, subject=subject)
        for toolkit in tooling.toolkits:
            policy.precheck_toolkit(toolkit, subject=subject, owner=owner)
        for server in tooling.mcp_servers:
            policy.precheck_mcp(server, subject=subject, owner=owner)

    def precheck_toolkit(self, spec: Any, *, subject: ToolingSubject, owner: str | None = None) -> None:
        """Slug check plus phase-dependent secret-reference check of one toolkit spec (no vault access)."""
        self.check_tool(spec.slug, subject=subject)
        self._check_secrets(spec.secret_refs, spec.vault_owner, spec.slug, subject, owner, toolkit_vault_name)

    def precheck_mcp(self, spec: AgentMCPServerSpec, *, subject: ToolingSubject, owner: str | None = None) -> None:
        """Effective-config check plus secret-reference check of one MCP spec (no vault access)."""
        self.resolve_mcp(effective_mcp_config(spec), subject=subject)
        self._check_secrets(spec.secret_refs, spec.vault_owner, spec.name, subject, owner, mcp_vault_name)

    @staticmethod
    def _check_secrets(
        secret_refs: Mapping[str, str],
        vault_owner: str | None,
        item: str,
        subject: ToolingSubject,
        owner: str | None,
        namer: Any,
    ) -> None:
        if not secret_refs and not vault_owner:
            return
        if subject.phase in _SECRET_BLOCKED_PHASES:
            raise TenantToolingRefused("secret_ref_not_permitted", item=item)
        if subject.phase != "build":
            return
        expected = namer(item, f"studio-agent:{subject.agent_id}")
        if any(vault != expected for vault in secret_refs.values()) or vault_owner != owner:
            raise TenantToolingRefused("secret_ref_not_permitted", item=item)

    @staticmethod
    def _check_named_host(host: HostMCPServer, config: Mapping[str, Any]) -> dict[str, Any]:
        defaults = {
            key: field.get_default(call_default_factory=True)
            for key, field in AgentMCPServerSpec.model_fields.items()
            if not field.is_required()
        }
        supplied: dict[str, Any] = {}
        for key, value in config.items():
            if key == "name":
                continue
            if key in host.tenant_fields:
                supplied[key] = value
            elif key not in defaults or defaults[key] != value:
                raise TenantToolingRefused("field_not_permitted", item=f"{host.name}.{key}")
        return {**host.config, **supplied, "name": host.name}

    def _check_local_execution(self, config: Mapping[str, Any]) -> None:
        name = str(config.get("name", ""))
        if any(config.get(key) for key in _LOCAL_FIELDS):
            raise TenantToolingRefused("local_execution", item=name)
        transport = detect_transport(config)
        if transport in {"stdio", "unix"}:
            raise TenantToolingRefused("local_execution", item=name)
        if transport is not None and transport not in self.mcp_transports:
            raise TenantToolingRefused("transport_not_permitted", item=name)

    @staticmethod
    def _check_fields(config: Mapping[str, Any]) -> None:
        for key in config:
            if key not in _TENANT_MCP_FIELDS and key not in _LOCAL_FIELDS:  # local fields: empty (checked above)
                raise TenantToolingRefused("field_not_permitted", item=f"{config.get('name', '')}.{key}")

    def _check_endpoint(self, config: Mapping[str, Any]) -> None:
        name = str(config.get("name", ""))
        url = config.get("url")
        split = _split_https(url) if isinstance(url, str) else None
        if split is None:
            raise TenantToolingRefused("endpoint_not_allowed", item=name)
        host, port, path = split
        candidate = f"https://{host}:{port}{path if path.endswith('/') else path + '/'}"
        if not any(candidate.startswith(prefix) for prefix in self.mcp_endpoints):
            raise TenantToolingRefused("endpoint_not_allowed", item=name)


def unchanged_slugs(before: NormalizedTooling, after: NormalizedTooling) -> frozenset[str]:
    """Lower-cased slugs of ``after`` that a write leaves exactly as in ``before`` (tools and toolkit specs)."""

    def _slug(tool: Any) -> str | None:
        slug = tool if isinstance(tool, str) else getattr(tool, "name", None)
        return slug.lower() if isinstance(slug, str) else None

    kept = {_slug(t) for t in after.tools if any(t == old for old in before.tools)}
    kept |= {item.slug.lower() for item in after.toolkits if any(item == old for old in before.toolkits)}
    changed = {_slug(t) for t in after.tools if not any(t == old for old in before.tools)}
    changed |= {item.slug.lower() for item in after.toolkits if not any(item == old for old in before.toolkits)}
    return frozenset(slug for slug in kept - changed if slug)


def effective_mcp_config(spec: AgentMCPServerSpec) -> dict[str, Any]:
    """Exactly what hydrate_mcp returns, minus the vault read (secret fields → SECRET_MASK)."""
    base = spec.model_dump(exclude={"params", "secret_refs", "vault_owner"}, exclude_none=True)
    base.update(spec.params)
    for field in spec.secret_refs:
        base[field] = SECRET_MASK
    return base


def set_tenant_tooling_policy(app: MutableMapping[str, Any], policy: TenantToolingPolicy) -> None:
    """Register the host policy once, before startup completes."""
    if _POLICY_KEY in app:
        raise RuntimeError("tenant tooling policy already registered")
    app[_POLICY_KEY] = policy


def get_tenant_tooling_policy(app: Mapping[str, Any]) -> TenantToolingPolicy:
    """Registered policy, or ``deny_all()`` when the host registered nothing."""
    policy = app.get(_POLICY_KEY)
    return policy if isinstance(policy, TenantToolingPolicy) else TenantToolingPolicy.deny_all()


def enforce_tenant_tooling(app: Mapping[str, Any], tooling: NormalizedTooling, *, subject: ToolingSubject) -> None:
    """THE write/activation hook: raises TenantToolingRefused; pure, no I/O."""
    policy = get_tenant_tooling_policy(app)
    if not (subject.tenant is None and not policy.apply_to_global):
        policy.check_tooling(tooling, subject=subject)
    from parrot.tools.host_hooks import check_toolkit_params  # lazy: host_hooks imports this module

    check_toolkit_params(app, tooling, subject=subject)  # PA-9: the host parameter hook, every partition
