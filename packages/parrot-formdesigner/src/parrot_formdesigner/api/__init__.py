"""parrot_formdesigner.api — JSON REST surface.

Public API:

    from parrot_formdesigner.api import setup_form_api

Importing this package triggers two side effects:

1. ``parrot_formdesigner.controls.builtin`` is imported, seeding the
   form-control registry with one entry per ``FieldType``.
2. ``navigator_auth.decorators`` is imported (HARD dependency).

If ``navigator-auth`` is not installed, ``import parrot_formdesigner.api``
raises ``ImportError``.
"""

# Side-effect import: seed the form-controls registry before any consumer
# calls ``setup_form_api(app, registry)``. Note: do NOT do ``from .. import
# controls`` here — it would shadow ``api/controls.py`` inside relative
# imports from ``api/routes.py``.
from ..controls import builtin  # noqa: F401
from .routes import setup_form_api

__all__ = ["setup_form_api"]
