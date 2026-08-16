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
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

__all__ = [
    "AgentServiceConfig",
    "AgentTargetConfig",
    "AgentTargetError",
    "SchedulerConfig",
    "default_socket_path",
    "resolve_agent",
]

#: Default NDJSON line-size limit (bytes) for the UDS server (spec §2).
_DEFAULT_MAX_LINE_BYTES = 10 * 1024 * 1024  # 10 MB

#: Characters not allowed in a service `name` (it becomes a filename).
_NAME_INVALID_CHARS = frozenset("/\\")


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
        exposed_methods: Allowlist of agent method names exposed via the
            `agent.invoke` RPC method; when non-empty it is also a hard
            requirement for the MCP `invoke_method` tool to be registered
            at all. Empty means all public async methods are exposed over
            RPC (still subject to the underscore-prefix rejection).
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

        Args:
            path: Path to the YAML config file.

        Returns:
            The parsed and validated config.
        """
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

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
