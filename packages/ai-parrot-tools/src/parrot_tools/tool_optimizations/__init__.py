"""Claude Code / Codex tool optimizations (FEAT-543).

Three focused ``AbstractToolkit`` subclasses, exposed as ordinary AI-Parrot
tools and installable as local stdio MCP capabilities:

* ``LocalGitToolkit`` — deterministic Git workflows, no LLM calls.
* ``BoundedSourceToolkit`` — bounded reads with hashes and continuation.
* ``TargetedWriterToolkit`` — patch generation for *already-decided* TASK work.

Importing this package is deliberately cheap: names are resolved lazily via
:pep:`562` ``__getattr__`` so that ``import parrot_tools.tool_optimizations``
pulls in neither ``pydantic`` nor any toolkit machinery. The host read-guard
runtime depends on that — it must stay stdlib-light on import.
"""

from typing import Any

__all__ = (
    # models
    "OperationError",
    "StepResult",
    "OperationResult",
    "SourceInfo",
    "SourceResult",
    "WriterLimits",
    "ReferenceSlice",
    "TargetFile",
    "DelegationPacket",
    "PatchManifest",
    # policy
    "MIN_RESULT_BYTES",
    "OptimizationPolicy",
    "PolicyError",
    "SymlinkRejectedError",
    "LockTimeoutError",
    "BudgetError",
    "WorktreeLock",
    "compact_json",
    "measure_json_bytes",
    "fit_to_budget",
    "relative_posix",
    "check_no_symlink_components",
    "resolve_operand",
    # base
    "OptimizationToolkitBase",
)

#: Public name -> defining submodule. Kept explicit so a typo surfaces as an
#: AttributeError here rather than as a confusing ImportError downstream.
_EXPORTS: dict[str, str] = {
    "OperationError": "models",
    "StepResult": "models",
    "OperationResult": "models",
    "SourceInfo": "models",
    "SourceResult": "models",
    "WriterLimits": "models",
    "ReferenceSlice": "models",
    "TargetFile": "models",
    "DelegationPacket": "models",
    "PatchManifest": "models",
    "MIN_RESULT_BYTES": "policy",
    "OptimizationPolicy": "policy",
    "PolicyError": "policy",
    "SymlinkRejectedError": "policy",
    "LockTimeoutError": "policy",
    "BudgetError": "policy",
    "WorktreeLock": "policy",
    "compact_json": "policy",
    "measure_json_bytes": "policy",
    "fit_to_budget": "policy",
    "relative_posix": "policy",
    "check_no_symlink_components": "policy",
    "resolve_operand": "policy",
    "OptimizationToolkitBase": "base",
}


def __getattr__(name: str) -> Any:
    """Lazily import a public name from its defining submodule.

    Args:
        name: The attribute being accessed on this package.

    Returns:
        The resolved object.

    Raises:
        AttributeError: ``name`` is not a public export of this package.
    """
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(f".{module_name}", __name__), name)
    globals()[name] = value  # cache: subsequent lookups skip __getattr__
    return value


def __dir__() -> list[str]:
    """Return the public export names for interactive completion."""
    return sorted(__all__)
