import contextlib
from typing import Protocol, Dict, Type, Any, Optional
from importlib import import_module
from ...models.outputs import OutputMode

class Renderer(Protocol):
    """Protocol for output renderers."""
    @staticmethod
    def render(data: Any, **kwargs) -> Any:
        ...


RENDERERS: Dict[OutputMode, Type[Renderer]] = {}
_PROMPTS: Dict[OutputMode, str] = {}


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
    if mode not in RENDERERS:
        # Lazy load the module to register the renderer
        with contextlib.suppress(ImportError):
            if mode == OutputMode.TERMINAL:
                import_module('.terminal', 'parrot.outputs.formats')
            elif mode == OutputMode.HTML:
                import_module('.html', 'parrot.outputs.formats')
            elif mode == OutputMode.JSON:
                import_module('.json', 'parrot.outputs.formats')
            elif mode == OutputMode.MARKDOWN:
                import_module('.markdown', 'parrot.outputs.formats')
            elif mode == OutputMode.YAML:
                import_module('.yaml', 'parrot.outputs.formats')
            elif mode == OutputMode.CHART:
                import_module('.charts', 'parrot.outputs.formats')
            elif mode == OutputMode.MAP:
                import_module('.map', 'parrot.outputs.formats')
            elif mode == OutputMode.ALTAIR:
                import_module('.altair', 'parrot.outputs.formats')
            elif mode == OutputMode.JINJA2:
                import_module('.jinja2', 'parrot.outputs.formats')
            elif mode == OutputMode.TEMPLATE_REPORT:
                import_module('.template_report', 'parrot.outputs.formats')
            elif mode == OutputMode.BOKEH:
                import_module('.bokeh', 'parrot.outputs.formats')
            elif mode == OutputMode.PLOTLY:
                import_module('.plotly', 'parrot.outputs.formats')
            elif mode == OutputMode.MATPLOTLIB:
                import_module('.matplotlib', 'parrot.outputs.formats')
            elif mode == OutputMode.D3:
                import_module('.d3', 'parrot.outputs.formats')
            elif mode == OutputMode.ECHARTS:
                import_module('.echarts', 'parrot.outputs.formats')
            elif mode == OutputMode.SEABORN:
                import_module('.seaborn', 'parrot.outputs.formats')
            elif mode == OutputMode.TABLE:
                import_module('.table', 'parrot.outputs.formats')
    try:
        return RENDERERS[mode]
    except KeyError as exc:
        raise ValueError(
            f"No renderer registered for mode: {mode}"
        ) from exc


def get_output_prompt(mode: OutputMode) -> Optional[str]:
    """Get system prompt for mode."""
    return _PROMPTS.get(mode)

def has_system_prompt(mode: OutputMode) -> bool:
    """Check if mode has a registered system prompt."""
    return mode in _PROMPTS


__all__ = (
    'RENDERERS',
    'register_renderer',
    'get_renderer',
    'Renderer',
    'get_output_prompt',
    'has_system_prompt',
)
