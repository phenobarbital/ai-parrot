"""Agent Service configuration — YAML config + agent target resolution.

Implements the daemon-side configuration surface described in
``sdd/specs/agent-cli-daemon.spec.md`` §2 ("Data Models") and Module 2:
Pydantic v2 models for ``AgentServiceConfig`` (loadable from YAML or built
directly from a Python-path target for CLI use), the default Unix-domain-
socket path computation, and ``resolve_agent()`` — turning a
``module:attr`` target into a live, configured agent instance.
"""

from __future__ import annotations

import importlib
import inspect
import os
import re
from pathlib import Path
from typing import Any

import yaml
from parrot.auth.permission import PermissionContext, build_principal_context
from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "AgentServiceConfig",
    "AgentTargetConfig",
    "AgentTargetError",
    "SchedulerConfig",
    "ServiceIdentityConfig",
    "default_socket_path",
    "expand_env_vars",
    "resolve_agent",
]

#: Environment variables provisioning the fallback service identity
#: (FEAT-434 — used when a UDS peer's credentials cannot be resolved).
_ENV_SERVICE_IDENTITY_DISPLAY_NAME = "AGENTD_SERVICE_IDENTITY_DISPLAY_NAME"
_ENV_SERVICE_IDENTITY_USER_ID = "AGENTD_SERVICE_IDENTITY_USER_ID"
_ENV_SERVICE_IDENTITY_TENANT_ID = "AGENTD_SERVICE_IDENTITY_TENANT_ID"
_ENV_SERVICE_IDENTITY_ROLES = "AGENTD_SERVICE_IDENTITY_ROLES"

#: Default NDJSON line-size limit (bytes) for the UDS server (spec §2).
_DEFAULT_MAX_LINE_BYTES = 10 * 1024 * 1024  # 10 MB

#: Characters not allowed in a service `name` (it becomes a filename).
_NAME_INVALID_CHARS = frozenset("/\\")

#: Regex for ``${VAR}`` and ``${VAR:-default}`` interpolation.
_ENV_VAR_PATTERN = re.compile(
    r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::[-](?P<default>[^}]*))?\}"
)

#: Bare env-var name: uppercase letters, digits, underscores, 2+ chars.
_BARE_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,}$")


def _expand_env_string(value: str) -> str:
    """Expand environment variables inside a single string value.

    Supports two syntaxes (applied in order):

    1. **Interpolation** — ``${VAR}`` or ``${VAR:-default}``.  Works for
       full-value *and* partial substitution
       (``"https://${HOST}:${PORT}/api"``).  When no default is given and
       the variable is unset, the ``${VAR}`` token is left as-is so
       Pydantic validation surfaces a readable error.
    2. **Bare-name fallback** — when the *entire* string (after step 1)
       matches ``^[A-Z][A-Z0-9_]+$`` and that name exists in
       ``os.environ``, the value is replaced wholesale.  This lets users
       write ``vault_path: OBSIDIAN_VAULT_PATH`` as a shorthand.
    """
    def _replacer(match: re.Match) -> str:
        name = match.group("name")
        default = match.group("default")
        env_val = os.environ.get(name)
        if env_val is not None:
            return env_val
        if default is not None:
            return default
        # Leave the token as-is so the caller gets a clear error.
        return match.group(0)

    expanded = _ENV_VAR_PATTERN.sub(_replacer, value)

    # Bare-name fallback: only when the whole string is an env-var name.
    if _BARE_ENV_NAME.match(expanded):
        env_val = os.environ.get(expanded)
        if env_val is not None:
            return env_val

    return expanded


def expand_env_vars(obj: Any) -> Any:
    """Recursively expand environment variables in a parsed YAML tree.

    Walks dicts, lists, and string leaves.  Non-string scalars (int, float,
    bool, None) are returned unchanged.

    Args:
        obj: The parsed YAML data (typically a ``dict``).

    Returns:
        A new structure with environment variables expanded.
    """
    if isinstance(obj, dict):
        return {k: expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env_vars(item) for item in obj]
    if isinstance(obj, str):
        return _expand_env_string(obj)
    return obj


class SchedulerConfig(BaseModel):
    """Headless scheduler bootstrap options for the daemon.

    Attributes:
        enabled: Whether to boot `AgentSchedulerManager` at all.
        dsn: Postgres DSN for schedule persistence. `None` means no
            Postgres pool is created (decorator-registered schedules only).
        redis: Whether to attach a Redis-backed jobstore.
    """

    enabled: bool = True
    dsn: str | None = None
    redis: bool = False


class ServiceIdentityConfig(BaseModel):
    """Fallback caller identity for UDS connections whose peer credentials
    cannot be resolved (FEAT-434 — Claude Agent Tool Bridge, spec §3 Module 4).

    Provisioning (environment variables):
        ``AGENTD_SERVICE_IDENTITY_DISPLAY_NAME`` — human-readable label
            (default ``"parrot agent server"``).
        ``AGENTD_SERVICE_IDENTITY_USER_ID``      — principal id used for
            confirmation-window keying and PBAC (default ``"1001"``).
        ``AGENTD_SERVICE_IDENTITY_TENANT_ID``    — tenant/org id (default
            ``"default"``).
        ``AGENTD_SERVICE_IDENTITY_ROLES``        — optional comma-separated
            role claims (default: none).

    Attributes:
        display_name: Human-readable label for logs/audit trails.
        user_id: Principal identifier for the resolved `PermissionContext`.
        tenant_id: Tenant/org identifier.
        roles: Role claims for policy evaluation.

    Note:
        ``window_seconds`` is intentionally NOT a field here — it is a fixed
        `0` (see the `window_seconds` property below) and is never
        configurable via environment, YAML, or constructor kwargs. This
        identity's `owner_id` is shared by construction (every unresolvable
        peer collapses onto it), so a non-zero confirmation window would let
        one human's approval clear a later destructive call made for
        somebody else.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str = "parrot agent server"
    user_id: str = "1001"
    tenant_id: str = "default"
    roles: frozenset[str] = Field(default_factory=frozenset)

    @property
    def window_seconds(self) -> int:
        """Always `0` — this identity never holds a confirmation window.

        Decoupled from `ConfirmationConfig.window_seconds` on purpose: a
        deployment may raise the guard's *default* window for regular
        callers, but that must never apply to the shared service identity.
        """
        return 0

    @classmethod
    def from_env(cls) -> ServiceIdentityConfig:
        """Build the service identity from environment config, with defaults.

        Returns:
            A :class:`ServiceIdentityConfig`. Always succeeds — every field
            has a default, so a deployment need not provision anything to
            get a usable (if generic) fallback identity.
        """
        roles_raw = os.environ.get(_ENV_SERVICE_IDENTITY_ROLES, "")
        roles = frozenset(r.strip() for r in roles_raw.split(",") if r.strip())
        kwargs: dict[str, Any] = {"roles": roles}
        if (value := os.environ.get(_ENV_SERVICE_IDENTITY_DISPLAY_NAME)):
            kwargs["display_name"] = value
        if (value := os.environ.get(_ENV_SERVICE_IDENTITY_USER_ID)):
            kwargs["user_id"] = value
        if (value := os.environ.get(_ENV_SERVICE_IDENTITY_TENANT_ID)):
            kwargs["tenant_id"] = value
        return cls(**kwargs)

    def to_permission_context(self, channel: str = "agentd") -> PermissionContext:
        """Resolve this identity into a `PermissionContext`.

        The returned context's `extra["window_seconds"]` is always `0`,
        regardless of any deployment-configured `ConfirmationConfig`
        default — the anchor downstream HITL wiring (bridged confirming
        tools) must consult to pin this identity's confirmation window.

        Args:
            channel: Originating channel propagated to the context.

        Returns:
            A `PermissionContext` wrapping a `UserSession` for this identity.
        """
        ctx = build_principal_context(
            self.user_id,
            channel=channel,
            tenant_id=self.tenant_id,
            roles=self.roles or None,
        )
        ctx.extra["window_seconds"] = self.window_seconds
        ctx.extra["display_name"] = self.display_name
        return ctx


class AgentTargetConfig(BaseModel):
    """Identifies the agent to load via a Python path.

    Attributes:
        target: `"module.path:attr"` — a class, an already-constructed
            instance, or a sync/async factory callable.
        kwargs: Keyword arguments passed when `target` resolves to a class
            or a factory callable.
    """

    target: str
    kwargs: dict[str, Any] = Field(default_factory=dict)


class AgentServiceConfig(BaseModel):
    """Full configuration for one `AgentDaemon` instance.

    Attributes:
        name: Service name — becomes the socket filename, unit name, and
            log identity. Must be non-empty and contain no path separators.
        agent: The agent target to load.
        socket: Explicit UDS path. `None` means `default_socket_path(name)`
            is used at daemon start time.
        scheduler: Headless scheduler bootstrap options.
        expose_as_tools: Which allowlisted methods also become LLM tools, so
            the agent can call them mid-conversation instead of only
            answering RPC. `None` (the default) derives a tool for every
            name in `exposed_methods`; an explicit list narrows it (use it
            to keep slow or destructive methods RPC-only); `[]` disables
            derivation entirely. A tool the agent already registers itself
            always wins over a derived one. Composes with FEAT-434: the
            derived tools land in the agent's `ToolManager`, so a
            `claude-agent` LLM reaches them through the bridge as
            `mcp__parrot__<method>` like any other registered tool.
        exposed_methods: Allowlist of agent method names exposed via the
            `agent.invoke` RPC method; when non-empty it is also a hard
            requirement for the MCP `invoke_method` tool to be registered
            at all. Empty means every public method (sync or async; the
            handler awaits the result when it is awaitable) is exposed
            over RPC, still subject to the underscore-prefix rejection.
        log_level: Logging level name (e.g. `"INFO"`, `"DEBUG"`).
        max_line_bytes: NDJSON line-size limit for the UDS server.
        shutdown_grace: Seconds to wait for graceful shutdown before the
            daemon forces an exit.
    """

    name: str
    agent: AgentTargetConfig
    socket: Path | None = None
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    exposed_methods: list[str] = Field(default_factory=list)
    expose_as_tools: list[str] | None = None
    log_level: str = "INFO"
    max_line_bytes: int = _DEFAULT_MAX_LINE_BYTES
    shutdown_grace: float = 30.0

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        """Reject empty names or names containing path separators."""
        if not value or any(ch in _NAME_INVALID_CHARS for ch in value):
            raise ValueError(
                f"Invalid service name {value!r}: must be non-empty and "
                "contain no path separators (it becomes a filename)."
            )
        return value

    @classmethod
    def from_yaml(cls, path: str | Path) -> AgentServiceConfig:
        """Load an `AgentServiceConfig` from a YAML file.

        String values support environment-variable expansion:

        - ``${VAR}`` — replaced by ``os.environ["VAR"]``; left as-is
          when unset (Pydantic validation will surface the error).
        - ``${VAR:-default}`` — replaced by the env value, falling back
          to *default* when unset.
        - Partial interpolation: ``"https://${HOST}:${PORT}/api"``
        - Bare-name shorthand: a value like ``OBSIDIAN_VAULT_PATH``
          (all-caps, no ``${}``) is replaced when a matching env var
          exists.

        Args:
            path: Path to the YAML config file.

        Returns:
            The parsed and validated config.
        """
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        expanded = expand_env_vars(raw)
        return cls.model_validate(expanded)

    @classmethod
    def from_target(
        cls, target: str, name: str, **overrides: Any
    ) -> AgentServiceConfig:
        """Build a config directly from a `module:attr` target (no YAML).

        Args:
            target: `"module.path:attr"` agent target.
            name: Service name.
            **overrides: Any other `AgentServiceConfig` fields to override
                (e.g. `socket=...`, `log_level=...`).

        Returns:
            The constructed config.
        """
        return cls(name=name, agent=AgentTargetConfig(target=target), **overrides)


def default_socket_path(name: str) -> Path:
    """Compute the default Unix-domain-socket path for a service name.

    Uses `$XDG_RUNTIME_DIR/parrot/<name>.sock`, falling back to
    `/tmp/parrot-<uid>/<name>.sock` when `XDG_RUNTIME_DIR` is unset.

    Args:
        name: Service name.

    Returns:
        The socket path. The parent directory is NOT created by this
        function — callers are responsible for `mkdir(mode=0o700)`.
    """
    xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime_dir:
        base = Path(xdg_runtime_dir) / "parrot"
    else:
        base = Path(f"/tmp/parrot-{os.getuid()}")
    return base / f"{name}.sock"


class AgentTargetError(Exception):
    """Raised when an `AgentTargetConfig.target` cannot be resolved."""


def _split_target(target: str) -> tuple[str, str]:
    """Split a `"module.path:attr"` target into its two components.

    Raises:
        AgentTargetError: If `target` is not of the form `"module:attr"`.
    """
    if ":" not in target:
        raise AgentTargetError(
            f"Invalid agent target {target!r}: expected 'module.path:attr'"
        )
    module_path, _, attr_path = target.partition(":")
    if not module_path or not attr_path:
        raise AgentTargetError(
            f"Invalid agent target {target!r}: expected 'module.path:attr'"
        )
    return module_path, attr_path


async def resolve_agent(cfg: AgentTargetConfig) -> Any:
    """Resolve an `AgentTargetConfig` into a live, configured agent instance.

    `cfg.target` is imported as `module.path:attr`:

    - A class → instantiated with `cfg.kwargs`.
    - A callable (factory) → called with `cfg.kwargs`; the result is
      awaited when it is a coroutine (async factory support).
    - Anything else (an already-constructed instance) → used as-is.

    If the resolved object exposes an async `configure()` method, it is
    awaited before returning (mirrors `AbstractBot.configure()`).

    Args:
        cfg: The target configuration to resolve.

    Returns:
        The resolved (and configured, if applicable) agent instance.

    Raises:
        AgentTargetError: If the module/attribute cannot be found, or
            resolution otherwise fails.
    """
    module_path, attr_path = _split_target(cfg.target)

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise AgentTargetError(
            f"Cannot import module {module_path!r} from target "
            f"{cfg.target!r}: {exc}"
        ) from exc

    attr: Any = module
    for part in attr_path.split("."):
        try:
            attr = getattr(attr, part)
        except AttributeError as exc:
            raise AgentTargetError(
                f"Attribute {attr_path!r} not found on module "
                f"{module_path!r} (target {cfg.target!r}): {exc}"
            ) from exc

    try:
        if inspect.isclass(attr):
            instance = attr(**cfg.kwargs)
        elif callable(attr):
            result = attr(**cfg.kwargs)
            instance = await result if inspect.isawaitable(result) else result
        else:
            instance = attr
    except AgentTargetError:
        raise
    except Exception as exc:
        raise AgentTargetError(
            f"Failed to resolve agent target {cfg.target!r}: {exc}"
        ) from exc

    configure = getattr(instance, "configure", None)
    if configure is not None and inspect.iscoroutinefunction(configure):
        await configure()

    return instance
