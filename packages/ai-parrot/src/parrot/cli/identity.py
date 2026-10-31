"""CLI identity constants (FEAT-774 hard cut of the FEAT-266 O365_PRINCIPAL bootstrap).

The CLI principal now comes from `parrot login` (see :mod:`parrot.cli.principal`).
"""
from __future__ import annotations

from parrot.cli.principal import build_cli_permission_context

#: Surface channel used for every CLI-originated permission context.
CLI_CHANNEL: str = "cli"

__all__ = ["CLI_CHANNEL", "build_cli_permission_context"]
