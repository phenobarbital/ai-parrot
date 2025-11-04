from __future__ import annotations
import sys
from typing import Any, Optional

from .formats import get_renderer
from ..models.outputs import OutputMode
from ..template.engine import TemplateEngine


class OutputFormatter:
    """
    Formatter for AI responses supporting multiple output modes.
    """

    def __init__(self, template_engine: Optional[TemplateEngine] = None):
        """
        Initialize the OutputFormatter.

        Args:
            template_engine: Optional TemplateEngine instance for template-based rendering.
                           If not provided, a new one will be created when needed.
        """
        self._is_ipython = self._detect_ipython()
        self._is_notebook = self._detect_notebook()
        self._environment = self._detect_environment()
        self._renderers = {}
        self._template_engine = template_engine

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
            # Special handling for TEMPLATE_REPORT renderer to pass TemplateEngine
            if mode == OutputMode.TEMPLATE_REPORT:
                # Lazy initialize TemplateEngine if not provided
                if self._template_engine is None:
                    self._template_engine = TemplateEngine()
                self._renderers[mode] = renderer_cls(template_engine=self._template_engine)
            else:
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

    def add_template(self, name: str, content: str) -> None:
        """
        Add an in-memory template for use with TEMPLATE_REPORT mode.

        Args:
            name: Template name (e.g., 'report.html', 'summary.md')
            content: Jinja2 template content

        Example:
            formatter = OutputFormatter()
            formatter.add_template('report.html', '<h1>{{ title }}</h1>')
            result = await formatter.format_async(
                OutputMode.TEMPLATE_REPORT,
                {"title": "My Report"},
                template="report.html"
            )
        """
        # Ensure TemplateEngine is initialized
        if self._template_engine is None:
            self._template_engine = TemplateEngine()

        # Get or create the TEMPLATE_REPORT renderer to add the template
        renderer = self._get_renderer(OutputMode.TEMPLATE_REPORT)
        if hasattr(renderer, 'add_template'):
            renderer.add_template(name, content)
