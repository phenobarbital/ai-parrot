from __future__ import annotations
import sys
from typing import Any

from .formats import get_renderer
from ..models.outputs import OutputMode


class OutputFormatter:
    """
    Formatter for AI responses supporting multiple output modes.
    """

    def __init__(self):
        self._is_ipython = self._detect_ipython()
        self._is_notebook = self._detect_notebook()
        self._environment = self._detect_environment()
        self._renderers = {}

    def _detect_environment(self) -> str:
        if self._is_ipython:
            return "jupyter" if self._is_notebook else "ipython"
        return "terminal"

    def _detect_ipython(self) -> bool:
        try:
            if "IPython" not in sys.modules:
                return False
            from IPython import get_ipython
            return get_ipython() is not None
        except (ImportError, NameError):
            return False

    def _detect_notebook(self) -> bool:
        try:
            from IPython import get_ipython
            ipython = get_ipython()
            return ipython is not None and "IPKernelApp" in ipython.config
        except Exception:
            return False

    def _get_renderer(self, mode: OutputMode):
        if mode not in self._renderers:
            renderer_cls = get_renderer(mode)
            self._renderers[mode] = renderer_cls()
        return self._renderers[mode]

    def format(self, mode: OutputMode, data: Any, **kwargs) -> Any:
        if mode == OutputMode.DEFAULT:
            return data

        renderer = self._get_renderer(mode)
        if hasattr(renderer, "render_async"):
            raise TypeError(
                f"Renderer for mode '{mode}' requires async execution. Use 'format_async' instead."
            )

        return renderer.render(
            data,
            environment=self._environment,
            is_ipython=self._is_ipython,
            is_notebook=self._is_notebook,
            **kwargs,
        )

    async def format_async(self, mode: OutputMode, data: Any, **kwargs) -> Any:
        if mode == OutputMode.DEFAULT:
            return data

        renderer = self._get_renderer(mode)
        render_method = getattr(renderer, "render_async", renderer.render)

        return await render_method(
            data,
            environment=self._environment,
            is_ipython=self._is_ipython,
            is_notebook=self._is_notebook,
            **kwargs,
        )
