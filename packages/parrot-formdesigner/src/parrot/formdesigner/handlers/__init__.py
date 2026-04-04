"""HTTP handlers for parrot-formdesigner.

Provides aiohttp handlers for serving HTML form pages and a JSON REST API,
plus a one-liner route registration helper.
"""

from .api import FormAPIHandler
from .forms import FormPageHandler
from .routes import setup_form_routes
from .telegram import TelegramWebAppHandler

__all__ = [
    "FormAPIHandler",
    "FormPageHandler",
    "TelegramWebAppHandler",
    "setup_form_routes",
]
