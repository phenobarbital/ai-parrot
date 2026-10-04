"""Lazy, fixed target adapter registry (FEAT-581, M4).

Spec §3 "M4: Target registry and fixture entry points" fixes six public
target kinds (:data:`TARGET_KINDS`, taken directly from
:class:`parrot.e2e.models.TargetConfig`'s own ``kind`` literal, never
duplicated by hand). :func:`get_target_adapter` is the single entry point
the M3 supervisor uses to resolve one kind to its concrete
:class:`parrot.e2e.targets.base.TargetAdapter`.

The registry is intentionally lazy: importing this package (or calling
:func:`get_target_adapter` for one kind) never imports the concrete module
for any *other* kind. Concrete adapter modules
(``parrot.e2e.targets.{mcp,botmanager,ui,browser}``) are later M4
deliverables and do not exist yet in this checkout — resolving any kind
today raises :class:`parrot.e2e.errors.E2EPrerequisiteError` (never a raw
``ImportError``/``ModuleNotFoundError``), exactly the "missing optional
implementation" case this registry is required to surface explicitly. The
same typed error is raised once a module exists but is missing its
required extra/binary, or does not (yet) define the expected factory
attribute.

This module has no ``parrot.e2e.supervisor`` import and does not import any
concrete target module at package-import time — only the M2 schema/error
surface, resolving the M3/M4 cycle spec §3 calls out.
"""

from __future__ import annotations

import importlib
from typing import get_args

from parrot.e2e.errors import E2EConfigError, E2EPrerequisiteError
from parrot.e2e.models import TargetConfig
from parrot.e2e.targets.base import LaunchSpec, TargetAdapter

__all__ = ["LaunchSpec", "TargetAdapter", "TARGET_KINDS", "get_target_adapter"]

# Taken from TargetConfig.kind's own Literal — never hand-duplicated, so this
# registry cannot silently drift from the persisted schema (spec §2).
TARGET_KINDS: frozenset[str] = frozenset(get_args(TargetConfig.model_fields["kind"].annotation))

# One (module, factory attribute) pair per public target kind. Each module is
# expected to define a zero-argument callable at ``factory_name`` returning a
# ``TargetAdapter``. Only ``mcp.py`` is shared by three kinds — one stdio/HTTP
# adapter module, three distinct protocol-specific factories.
_ADAPTER_REGISTRY: dict[str, tuple[str, str]] = {
    "mcp-toolkit": ("parrot.e2e.targets.mcp", "build_mcp_toolkit_adapter"),
    "mcp-stdio": ("parrot.e2e.targets.mcp", "build_mcp_stdio_adapter"),
    "mcp-agent": ("parrot.e2e.targets.mcp", "build_mcp_agent_adapter"),
    "botmanager": ("parrot.e2e.targets.botmanager", "build_botmanager_adapter"),
    "ui": ("parrot.e2e.targets.ui", "build_ui_adapter"),
    "browser": ("parrot.e2e.targets.browser", "build_browser_adapter"),
}

assert set(_ADAPTER_REGISTRY) == TARGET_KINDS, (
    f"_ADAPTER_REGISTRY kinds {sorted(_ADAPTER_REGISTRY)} must exactly match "
    f"TargetConfig.kind's six literal values {sorted(TARGET_KINDS)}"
)


def get_target_adapter(kind: str) -> TargetAdapter:
    """Lazily resolve one target kind to its concrete :class:`TargetAdapter`.

    Only the module registered for ``kind`` is imported — never all six.

    Args:
        kind: One of :data:`TARGET_KINDS` (``TargetConfig.kind``'s value).

    Returns:
        The result of calling that kind's zero-argument factory — a
        :class:`TargetAdapter`.

    Raises:
        E2EConfigError: If ``kind`` is not one of :data:`TARGET_KINDS`.
        E2EPrerequisiteError: If the registered module cannot be imported
            (missing optional implementation or dependency — e.g. an
            uninstalled extra, or the module simply does not exist yet in
            this checkout), or the module exists but does not define the
            expected factory attribute.
    """
    if kind not in _ADAPTER_REGISTRY:
        raise E2EConfigError(
            f"unknown target kind {kind!r}; expected one of {sorted(TARGET_KINDS)}",
            reason_code="unknown_target_kind",
        )
    module_name, factory_name = _ADAPTER_REGISTRY[kind]

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise E2EPrerequisiteError(
            f"target kind {kind!r} requires {module_name!r}, which is not available: {exc}",
            reason_code="target_adapter_unavailable",
        ) from exc

    try:
        factory = getattr(module, factory_name)
    except AttributeError as exc:
        raise E2EPrerequisiteError(
            f"target kind {kind!r} module {module_name!r} does not define {factory_name!r}",
            reason_code="target_adapter_unavailable",
        ) from exc

    return factory()
