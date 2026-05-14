"""Form renderers for the forms abstraction layer.

Renderers convert FormSchema + StyleSchema into platform-specific output:
- AdaptiveCardRenderer: Adaptive Card JSON for MS Teams
- HTML5Renderer: HTML5 form fragment for web
- JsonSchemaRenderer: JSON Schema output for custom frontends
- TelegramRenderer: Telegram inline keyboards / WebApp for Telegram bots
"""
# Lazy re-exports (PEP 562). TelegramRenderer pulls aiogram (~1.5s); we
# defer it until the symbol is actually accessed.
import importlib
from typing import TYPE_CHECKING

from .adaptive_card import AdaptiveCardRenderer
from .base import AbstractFormRenderer
from .html5 import HTML5Renderer
from .jsonschema import JsonSchemaRenderer

_LAZY_EXPORTS = {
    "TelegramRenderer": ".telegram",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, package=__name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from .telegram import TelegramRenderer


__all__ = [
    "AbstractFormRenderer",
    "AdaptiveCardRenderer",
    "HTML5Renderer",
    "JsonSchemaRenderer",
    "TelegramRenderer",
]
