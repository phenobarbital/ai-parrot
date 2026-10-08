"""Target-agnostic scheduler base (FEAT-644): resolver contract and registry."""

from __future__ import annotations

import inspect
import logging
from enum import Enum
from typing import Any, Protocol, Sequence, runtime_checkable

from .models import FireContext, JobDefinition, utcnow

__all__ = (
    "ScheduleType",
    "TargetMissingError",
    "SchedulerUnavailableError",
    "NotEditableError",
    "SchedulerRunNowConflictError",
    "TargetResolver",
    "TargetRegistry",
    "RegistryResolver",
    "apply_prompt_signature",
    "inject_fire_context",
    "utcnow",
)

logger = logging.getLogger("Parrot.Scheduler")

_RUN_NOW_JOB_PREFIX = "run_now:"
_FIRE_CONTEXT_PARAMS = ("fire_id", "scheduled_at")


class ScheduleType(Enum):
    """Schedule execution types."""

    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    INTERVAL = "interval"
    CRON = "cron"
    CRONTAB = "crontab"


class TargetMissingError(LookupError):
    """The target is unavailable in this process."""


class SchedulerUnavailableError(RuntimeError):
    """Coordination backend or jobstore is unavailable."""


class NotEditableError(ValueError):
    """A code-declared or external job cannot be mutated."""


class SchedulerRunNowConflictError(Exception):
    """A run-now execution is already active for the schedule."""


@runtime_checkable
class TargetResolver(Protocol):
    """Strategy resolving a ``target_kind`` to a live object."""

    kind: str

    async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None: ...

    def derive_target_id(self, target: Any) -> str | None: ...

    def build_call(
        self, target: Any, definition: JobDefinition, fire: FireContext
    ) -> tuple[list[Any], dict[str, Any]]: ...


class TargetRegistry:
    """Manager-scoped explicit registrations, keyed by ``(kind, name)``."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], Any] = {}
        self._methods: dict[tuple[str, str], frozenset[str]] = {}

    def register(self, name: str, obj: Any, *, kind: str = "service", methods: Sequence[str] | None = None) -> None:
        """Register ``obj`` with an optional public-method allowlist."""
        key = (kind, name)
        if methods is None:
            self._methods.pop(key, None)
        else:
            allowed_methods = frozenset(methods)
            if any(not method.isidentifier() or method.startswith("_") for method in allowed_methods):
                raise ValueError("methods must be public Python identifiers")
            self._methods[key] = allowed_methods
        self._objects[key] = obj

    def unregister(self, name: str, *, kind: str = "service") -> None:
        """Remove a target and its allowlist if registered."""
        key = (kind, name)
        self._objects.pop(key, None)
        self._methods.pop(key, None)

    def get(self, name: str, *, kind: str = "service") -> Any | None:
        """Return a registered target, or ``None`` when absent."""
        return self._objects.get((kind, name))

    def allowed_methods(self, name: str, *, kind: str = "service") -> frozenset[str] | None:
        """Return the target method allowlist, if one was registered."""
        return self._methods.get((kind, name))


def apply_prompt_signature(
    method: Any, call_args: list[Any], call_kwargs: dict[str, Any], prompt: Any
) -> tuple[list[Any], dict[str, Any]]:
    """Inject ``prompt`` into a call according to its signature."""
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return call_args, call_kwargs

    positional_params = [
        param
        for param in signature.parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if positional_params:
        call_kwargs.setdefault(positional_params[0].name, prompt)
        return call_args, call_kwargs

    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in signature.parameters.values()):
        call_args.append(prompt)
        return call_args, call_kwargs

    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        call_kwargs.setdefault("prompt", prompt)
    return call_args, call_kwargs


def inject_fire_context(method: Any, call_kwargs: dict[str, Any], fire: FireContext) -> dict[str, Any]:
    """Add fire context when the target signature accepts it."""
    try:
        signature = inspect.signature(inspect.unwrap(method))
    except (TypeError, ValueError):
        return call_kwargs

    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    for name in _FIRE_CONTEXT_PARAMS:
        if name not in call_kwargs and (name in signature.parameters or accepts_kwargs):
            call_kwargs[name] = getattr(fire, name)
    return call_kwargs


class RegistryResolver:
    """``service`` kind: objects registered via ``register_target``."""

    kind: str = "service"

    def __init__(self, registry: TargetRegistry) -> None:
        self._registry = registry

    async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None:
        """Return the registered object or ``None`` without raising."""
        return self._registry.get(name, kind=self.kind)

    def derive_target_id(self, target: Any) -> str | None:
        """Return no ID because services carry none."""
        return None

    def build_call(self, target: Any, definition: JobDefinition, fire: FireContext) -> tuple[list[Any], dict[str, Any]]:
        """Validate the service method and build its arguments."""
        method_name = definition.method_name
        if method_name is None:
            raise ValueError("method_name is required for service schedules")
        if method_name.startswith("_"):
            raise ValueError("method_name must be a public identifier")

        allowed_methods = self._registry.allowed_methods(definition.target_name, kind=self.kind)
        if allowed_methods is not None and method_name not in allowed_methods:
            raise ValueError(f"method {method_name!r} not allowed for service {definition.target_name!r}")

        method = getattr(target, method_name)
        if not callable(method):
            raise ValueError(f"method {method_name!r} is not callable")

        call_args: list[Any] = []
        call_kwargs = dict(definition.metadata)
        if definition.prompt is not None:
            call_args, call_kwargs = apply_prompt_signature(method, call_args, call_kwargs, definition.prompt)
        return call_args, inject_fire_context(method, call_kwargs, fire)
