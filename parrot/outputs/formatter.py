from __future__ import annotations
from typing import Any
import sys
from ..models.outputs import OutputMode
from .formats import RENDERERS, get_renderer


class OutputFormatter:
    """
    Formatter for AI responses supporting multiple output modes.
    """

    def __init__(self):
        self._is_ipython = self._detect_ipython()
        self._is_notebook = self._detect_notebook()
        self._environment = self._detect_environment()  # Once
        self._renderers = {}  # Cache renderer instances

    def _detect_environment(self) -> str:
        """Detect once: jupyter, terminal, colab, etc."""
        if self._is_ipython:
            return 'jupyter' if self._is_notebook else 'ipython'
        else:
            return 'terminal'

    def _detect_ipython(self) -> bool:
        """Detect if running in IPython/Jupyter environment."""
        try:
            if 'IPython' not in sys.modules:
                return False
            # Check if IPython is available and active
            from IPython import get_ipython  # type: ignore  # pylint: disable=import-outside-toplevel
            return get_ipython() is not None
        except (ImportError, NameError):
            return False

    def _detect_notebook(self) -> bool:
        """Detect if running specifically in Jupyter notebook (not just IPython)."""
        try:
            from IPython import get_ipython  # type: ignore  # pylint: disable=import-outside-toplevel
            ipython = get_ipython()
            # Check if it's a notebook kernel
            return False if ipython is None else 'IPKernelApp' in ipython.config
        except Exception:
            return False

    def _get_renderer(self, mode: OutputMode):
        """Lazy load and cache renderers"""
        if mode not in self._renderers:
            renderer_cls = get_renderer(mode)
            self._renderers[mode] = renderer_cls()
        else:
            renderer_cls = RENDERERS[mode]
        if not renderer_cls:
            raise ValueError(f"No renderer registered for mode: {mode}")
        return self._renderers[mode]

    def format(
        self,
        mode: OutputMode,
        data: Any,
        **kwargs
    ) -> Any:
        """Main entry point for formatting"""

        # Handle default mode - return as-is
        if mode == OutputMode.DEFAULT:
            return data

        # Get or create renderer
        renderer = self._get_renderer(mode)

        # Render
        return renderer.render(
            data,
            environment=self._environment,
            is_ipython=self._is_ipython,
            is_notebook=self._is_notebook,
            **kwargs
        )
