"""Procedure plane — what to do next, as a wikitoolkit overlay plane (FEAT-891)."""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    **dict.fromkeys(
        (
            "ProbeCheck",
            "ScopeArg",
            "GuardSpec",
            "ExecutorRef",
            "ProcedureSpec",
            "ProcedureManifest",
            "ProbeResult",
            "ResolvedProcedure",
            "Resolution",
            "INDEX_SCHEMA_VERSION",
            "PLANE_DIR",
            "INDEX_FILE",
            "EDGE_FIELDS",
        ),
        "models",
    ),
    **dict.fromkeys(("MANIFEST_DIR", "load_manifest", "manifest_specs", "skill_spec", "skill_specs"), "producers"),
    **dict.fromkeys(("GraphFinding", "validate_graph"), "validate"),
    **dict.fromkeys(("compile_index", "publish_index", "read_index", "is_stale"), "index"),
    "ProcedurePlane": "plane",
    **dict.fromkeys(("ProbeRunner", "resolve"), "resolver"),
    **dict.fromkeys(("ProcedureNextInput", "op_procedure_next", "procedure_plane_available"), "operations"),
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve a public name from its submodule on first access."""
    try:
        module = importlib.import_module(f"{__name__}.{_EXPORTS[name]}")
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(module, name)
