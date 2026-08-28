"""Embedded Admin UI subpackage.

Exposes :func:`setup_admin_ui`, called from ``BotManager.setup()`` to
mount the compiled Svelte 5 + Vite Admin UI (when present) plus its
supporting JSON endpoints, and the status endpoint's Pydantic models /
handler (also the source for the TS codegen pipeline).
"""
from .serving import setup_admin_ui
from .status import AdminStatus, AdminStatusHandler, AgentCounts, DependencyHealth

__all__ = [
    "AdminStatus",
    "AdminStatusHandler",
    "AgentCounts",
    "DependencyHealth",
    "setup_admin_ui",
]
