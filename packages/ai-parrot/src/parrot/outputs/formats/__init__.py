from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

import contextlib
import warnings
from typing import Protocol, Dict, Type, Any, Optional
from importlib import import_module
from ...models.outputs import OutputMode

# FEAT-273 (Module 12 / G7): legacy OutputModes superseded by the A2UI pipeline.
# Each entry names the A2UI replacement path (single source of truth for the message).
# Kept modes (JSON/YAML/MARKDOWN/SLACK/WHATSAPP/TERMINAL, infographic-JSON) are ABSENT.
_A2UI_REPLACEMENTS: Dict[OutputMode, str] = {
    OutputMode.ALTAIR: "OutputMode.A2UI with the Chart catalog component",
    OutputMode.PLOTLY: "OutputMode.A2UI with the Chart catalog component",
    OutputMode.MATPLOTLIB: "OutputMode.A2UI with the Chart catalog component",
    OutputMode.SEABORN: "OutputMode.A2UI with the Chart catalog component",
    OutputMode.ECHARTS: "OutputMode.A2UI with the Chart catalog component",
    OutputMode.STRUCTURED_CHART: "OutputMode.A2UI with the Chart catalog component",
    OutputMode.MAP: "OutputMode.A2UI with the Map catalog component",
    OutputMode.STRUCTURED_MAP: "OutputMode.A2UI with the Map catalog component",
    OutputMode.TABLE: "OutputMode.A2UI with the DataTable catalog component",
    OutputMode.STRUCTURED_TABLE: "OutputMode.A2UI with the DataTable catalog component",
    OutputMode.CARD: "OutputMode.A2UI with the Card/KPICard catalog components",
    OutputMode.TEMPLATE_REPORT: "OutputMode.A2UI with the Report catalog component",
    OutputMode.JINJA2: "OutputMode.A2UI with the Report catalog component",
    OutputMode.HTML: "OutputMode.A2UI with the SSR-HTML renderer",
    OutputMode.APPLICATION: "OutputMode.A2UI with the SSR-HTML renderer",
}


def _warn_if_deprecated(mode: OutputMode) -> None:
    """Emit a `DeprecationWarning` for an A2UI-superseded legacy mode (FEAT-273)."""
    replacement = _A2UI_REPLACEMENTS.get(mode)
    if replacement is not None:
        warnings.warn(
            f"OutputMode.{mode.name} is deprecated (FEAT-273): use {replacement}.",
            DeprecationWarning,
            stacklevel=3,
        )

class Renderer(Protocol):
    """Protocol for output renderers."""
    @staticmethod
    def render(data: Any, **kwargs) -> Any:
        ...


RENDERERS: Dict[OutputMode, Type[Renderer]] = {}
_PROMPTS: Dict[OutputMode, str] = {}

# Module-level dispatch table — maps OutputMode → module name(s) to import
_MODULE_MAP: dict = {
    OutputMode.TEXT:            ('.text',),
    OutputMode.TERMINAL:        ('.terminal',),          # no renderer; TerminalGenerator is in generators/
    OutputMode.HTML:            ('.html',),
    OutputMode.JSON:            ('.json',),
    OutputMode.MARKDOWN:        ('.markdown',),
    OutputMode.YAML:            ('.yaml',),
    OutputMode.CHART:           ('.chart',),             # base class only; no renderer registered
    OutputMode.MAP:             ('.map',),
    OutputMode.ALTAIR:          ('.altair',),
    OutputMode.STRUCTURED_CHART: ('.structured_chart',),
    OutputMode.STRUCTURED_TABLE: ('.structured_table',),
    OutputMode.STRUCTURED_MAP:   ('.structured_map',),
    OutputMode.JINJA2:          ('.jinja2',),
    OutputMode.TEMPLATE_REPORT: ('.template_report',),
    OutputMode.PLOTLY:          ('.plotly',),
    OutputMode.MATPLOTLIB:      ('.matplotlib',),
    OutputMode.ECHARTS:         ('.echarts',),
    OutputMode.SEABORN:         ('.seaborn',),
    OutputMode.TABLE:           ('.table',),
    OutputMode.APPLICATION:     ('.application',),
    OutputMode.CARD:            ('.card',),
    OutputMode.WHATSAPP:        ('.whatsapp',),
    OutputMode.SLACK:           ('.slack',),
    OutputMode.INFOGRAPHIC:     ('.infographic', '.infographic_html'),
}


def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None):
    """
    Decorator to register a renderer class and optionally its system prompt.

    Args:
        mode: OutputMode enum value
        system_prompt: Optional system prompt to inject when using this mode
    """
    def decorator(cls):
        RENDERERS[mode] = cls
        if system_prompt:
            _PROMPTS[mode] = system_prompt
        return cls
    return decorator

def get_renderer(mode: OutputMode) -> Type[Renderer]:
    """Get the renderer class for the given output mode."""
    _warn_if_deprecated(mode)
    if mode not in RENDERERS:
        modules = _MODULE_MAP.get(mode, ())
        with contextlib.suppress(ImportError):
            for mod in modules:
                import_module(mod, 'parrot.outputs.formats')
    try:
        return RENDERERS[mode]
    except KeyError as exc:
        raise ValueError(
            f"No renderer registered for mode: {mode}"
        ) from exc

def get_output_prompt(mode: OutputMode) -> Optional[str]:
    """Get system prompt for mode."""
    # Trigger lazy loading to ensure decorator has run
    if mode not in _PROMPTS:
        with contextlib.suppress(ValueError):
            get_renderer(mode)
    return _PROMPTS.get(mode)

def has_system_prompt(mode: OutputMode) -> bool:
    """Check if mode has a registered system prompt."""
    if mode not in _PROMPTS:
        with contextlib.suppress(ValueError):
            get_renderer(mode)
    return mode in _PROMPTS


def get_infographic_html_renderer():
    """Return ``InfographicHTMLRenderer`` with its concrete type preserved.

    Use this instead of ``get_renderer(OutputMode.INFOGRAPHIC)`` when you
    need to call ``render_to_html()``, which is not part of the base
    ``Renderer`` Protocol.

    Returns:
        Type[InfographicHTMLRenderer]: The concrete renderer class.
    """
    # FEAT-273 (G7): the infographic-HTML path is superseded; the JSON path is kept.
    warnings.warn(
        "The infographic-HTML renderer path is deprecated (FEAT-273): use "
        "OutputMode.A2UI with the Infographic catalog component and the SSR-HTML "
        "renderer. The infographic-JSON path is unaffected.",
        DeprecationWarning,
        stacklevel=2,
    )
    from .infographic_html import InfographicHTMLRenderer  # noqa: F401 — ensure registered
    get_renderer(OutputMode.INFOGRAPHIC)  # trigger lazy-load + registration
    from .infographic_html import InfographicHTMLRenderer as _Cls
    return _Cls


from .base import RenderResult, RenderError

__all__ = (
    'RENDERERS',
    'register_renderer',
    'get_renderer',
    'Renderer',
    'get_output_prompt',
    'has_system_prompt',
    'get_infographic_html_renderer',
    'RenderResult',
    'RenderError',
)
