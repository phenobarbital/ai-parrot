"""Tests for the scheduler target registry and service resolver."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps

import pytest

pytest.importorskip("asyncdb")

from parrot.scheduler.base import (
    RegistryResolver,
    TargetRegistry,
    apply_prompt_signature,
    inject_fire_context,
)
from parrot.scheduler.models import FireContext, JobDefinition


def _definition(**overrides: object) -> JobDefinition:
    """Build a valid service definition for resolver tests."""
    values: dict[str, object] = {
        "schedule_id": "schedule-1",
        "backend": "db",
        "target_kind": "service",
        "target_name": "service",
        "method_name": "run",
        "schedule_type": "interval",
        "schedule_config": {"minutes": 5},
    }
    values.update(overrides)
    return JobDefinition(**values)


def _fire() -> FireContext:
    """Build a deterministic context for call construction."""
    return FireContext("fire-1", datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc))


def test_registry_register_get_unregister() -> None:
    """Registrations remain isolated by kind and can be removed."""
    registry = TargetRegistry()
    target = object()

    registry.register("service", target, methods=["run"])

    assert registry.get("service") is target
    assert registry.allowed_methods("service") == frozenset({"run"})
    assert registry.get("service", kind="agent") is None
    registry.unregister("service")
    assert registry.get("service") is None
    assert registry.allowed_methods("service") is None


def test_registry_rejects_private_methods() -> None:
    """Allowlist entries must be public Python identifiers."""
    with pytest.raises(ValueError):
        TargetRegistry().register("service", object(), methods=["_private"])
    with pytest.raises(ValueError):
        TargetRegistry().register("service", object(), methods=["not-valid"])


@pytest.mark.asyncio
async def test_registry_resolver_resolves_service() -> None:
    """The service resolver reads the manager-scoped registry."""
    registry = TargetRegistry()
    target = object()
    registry.register("service", target)

    resolver = RegistryResolver(registry)

    assert await resolver.resolve("service") is target
    assert await resolver.resolve("missing") is None
    assert resolver.derive_target_id(target) is None


def test_build_call_requires_method_name() -> None:
    """Services require an explicit method name."""
    resolver = RegistryResolver(TargetRegistry())

    with pytest.raises(ValueError, match="method_name"):
        resolver.build_call(object(), _definition(method_name=None), _fire())


def test_build_call_enforces_allowlist() -> None:
    """A service call is constrained to its registered methods."""

    class Service:
        def run(self) -> None:
            """Run the service."""

    registry = TargetRegistry()
    service = Service()
    registry.register("service", service, methods=["other"])

    with pytest.raises(ValueError, match="not allowed"):
        RegistryResolver(registry).build_call(service, _definition(), _fire())


def test_private_method_rejected() -> None:
    """Resolvers never schedule private service methods."""
    resolver = RegistryResolver(TargetRegistry())

    with pytest.raises(ValueError, match="public identifier"):
        resolver.build_call(object(), _definition(method_name="_private"), _fire())


def test_fire_context_injected_by_signature() -> None:
    """Fire fields follow declared signatures, kwargs, and wrapped functions."""

    def declared(prompt: str, *, fire_id: str | None = None) -> None:
        """Accept a declared fire ID."""

    def kwargs(**values: object) -> None:
        """Accept arbitrary call arguments."""

    def neither(prompt: str) -> None:
        """Accept no fire fields."""

    @wraps(declared)
    def wrapped(*args: object, **values: object) -> None:
        """Delegate through a wraps-preserving decorator."""
        declared(*args, **values)

    fire = _fire()
    assert inject_fire_context(declared, {}, fire) == {"fire_id": "fire-1"}
    assert inject_fire_context(kwargs, {}, fire) == {"fire_id": "fire-1", "scheduled_at": fire.scheduled_at}
    assert inject_fire_context(neither, {}, fire) == {}
    assert inject_fire_context(wrapped, {"fire_id": "provided"}, fire) == {"fire_id": "provided"}


def test_apply_prompt_signature_matches_legacy() -> None:
    """Prompt injection preserves the legacy positional, args, and kwargs rules."""

    def positional(prompt: str) -> None:
        """Accept one positional prompt."""

    def variadic(*args: object) -> None:
        """Accept positional arguments."""

    def keywords(**values: object) -> None:
        """Accept keyword arguments."""

    assert apply_prompt_signature(positional, [], {}, "value") == ([], {"prompt": "value"})
    assert apply_prompt_signature(variadic, [], {}, "value") == (["value"], {})
    assert apply_prompt_signature(keywords, [], {}, "value") == ([], {"prompt": "value"})
