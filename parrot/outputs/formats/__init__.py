import contextlib
from typing import Protocol, Dict, Type, Any
from importlib import import_module
from ...models.outputs import OutputMode

class Renderer(Protocol):
    """Protocol for output renderers."""
    @staticmethod
    def render(data: Any, **kwargs) -> Any:
        ...


RENDERERS: Dict[OutputMode, Type[Renderer]] = {}


def register_renderer(mode: OutputMode):
    def decorator(cls):
        RENDERERS[mode] = cls
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
    try:
        return RENDERERS[mode]
    except KeyError as exc:
        raise ValueError(
            f"No renderer registered for mode: {mode}"
        ) from exc


__all__ = (
    'RENDERERS',
    'register_renderer',
    'get_renderer',
    'Renderer',
)
