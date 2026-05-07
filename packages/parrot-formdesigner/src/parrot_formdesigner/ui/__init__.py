"""parrot_formdesigner.ui — HTML pages + Telegram WebApp surface.

Public API:

    from parrot_formdesigner.ui import setup_form_ui

Importing this package does NOT trigger ``parrot_formdesigner.api`` —
the two are independently mountable. Hard-imports navigator-auth (same
policy as api/).
"""

from .routes import setup_form_ui

__all__ = ["setup_form_ui"]
