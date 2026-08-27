"""Embedded Admin UI subpackage.

Exposes :func:`setup_admin_ui`, called from ``BotManager.setup()`` to
mount the compiled Svelte 5 + Vite Admin UI (when present) plus its
supporting JSON endpoints.
"""
from .serving import setup_admin_ui

__all__ = ["setup_admin_ui"]
