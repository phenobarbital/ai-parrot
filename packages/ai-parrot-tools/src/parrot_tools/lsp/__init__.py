"""Optional Python semantic evidence (LSP) research pilot — FEAT-580.

This package ships the data models, snapshot/session plumbing, and
``LSPToolkit`` for the SDD LSP research pilot. ``LSPToolkit`` itself is
deliberately NOT re-exported here even though ``toolkit.py`` exists: the
packaged MCP template (``_toolkit_templates/lsp.yaml``) resolves it via
the explicit dotted path ``parrot_tools.lsp.toolkit.LSPToolkit``, so
only the wire-safe contracts below are exported at the package level.
Importing this package never starts a process or spawns Pyright.
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
