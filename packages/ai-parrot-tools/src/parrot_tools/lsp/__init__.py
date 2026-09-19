"""Optional Python semantic evidence (LSP) research pilot — FEAT-580.

This package ships the data models, snapshot/session plumbing, and
``LSPToolkit`` for the SDD LSP research pilot. Only the wire-safe
contracts land in M1 (:mod:`parrot_tools.lsp.models`); no toolkit is
exported here until ``toolkit.py`` exists, so importing this package
never starts a process or spawns Pyright.
"""

from .models import (
    EvidenceMeta,
    LSP_ERROR_CODES,
    LSPConfig,
    LSPDiagnostic,
    LSPFailure,
    LSPLocation,
    LSPResult,
    OPERATOR_UNCONFIGURED_ENVIRONMENT_ID,
    SourcePosition,
    SourceRange,
    SourceState,
)

__all__ = [
    "EvidenceMeta",
    "LSP_ERROR_CODES",
    "LSPConfig",
    "LSPDiagnostic",
    "LSPFailure",
    "LSPLocation",
    "LSPResult",
    "OPERATOR_UNCONFIGURED_ENVIRONMENT_ID",
    "SourcePosition",
    "SourceRange",
    "SourceState",
]
