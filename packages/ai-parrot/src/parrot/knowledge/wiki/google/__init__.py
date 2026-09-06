"""Google Antigravity / Gemini CLI WikiToolkit and Bookstore infrastructure integration."""

from parrot.knowledge.wiki.google.installer import (
    install_google_integration,
    integration_status,
    uninstall_google_integration,
)

__all__ = [
    "install_google_integration",
    "uninstall_google_integration",
    "integration_status",
]
