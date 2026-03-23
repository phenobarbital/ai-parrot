from typing import Any, Dict, Optional
from dataclasses import asdict
from ...models.outputs import OutputMode
from ...template.engine import TemplateEngine
from . import register_renderer
from .base import BaseRenderer


@register_renderer(OutputMode.TEMPLATE_REPORT)
class TemplateReportRenderer(BaseRenderer):
    """
    Renders AI output using Jinja2 templates via the TemplateEngine.

    Supports both file-based templates and in-memory templates via add_template().
    """

    def __init__(self, template_engine: Optional[TemplateEngine] = None):
        """
        Initialize the TemplateReportRenderer.

        Args:
            template_engine: Optional TemplateEngine instance. If not provided,
            one will be created on first use.
        """
        self._template_engine = template_engine

    @property
    def template_engine(self) -> TemplateEngine:
        """
        Lazy initialization of TemplateEngine if not provided.

        Returns:
            TemplateEngine instance
        """
        if self._template_engine is None:
            # Initialize with no template directories (will use in-memory only)
            self._template_engine = TemplateEngine()
        return self._template_engine

    def add_template(self, name: str, content: str) -> None:
        """
        Add an in-memory template to the engine.

        Args:
            name: Template name (e.g., 'report.html', 'summary.md')
            content: Jinja2 template content

        Example:
            renderer.add_template('report.html', '<h1>{{ title }}</h1>')
        """
        self.template_engine.add_templates({name: content})

    async def render(self, data: Any, **kwargs: Any) -> str:
        """
        Renders data using a Jinja2 template asynchronously.

        Args:
            data: The data to render. Can be:
                - dict: passed directly to template
                - Pydantic model: converted via model_dump()
                - dataclass: converted via asdict()
                - any object with attributes: accessible in template
            **kwargs: Additional arguments:
                - template: (required) Template name to use
                - template_engine: (optional) Override the default engine
                - Additional kwargs are passed to the template context

        Returns:
            Rendered template content as string

        Raises:
            ValueError: If template is not provided or not found

        Example:
            result = await renderer.render(
                {"title": "Report", "items": [1, 2, 3]},
                template="report.html"
            )
        """
        # Get template name
        template_name: str = kwargs.pop("template", None)
        if not template_name:
            raise ValueError(
                "Template name must be provided via 'template' kwarg. "
                "Example: renderer.render(data, template='report.html')"
            )

        # Allow overriding the template engine
        engine = kwargs.pop("template_engine", None) or self.template_engine

        # Prepare the template context
        context = self._prepare_template_context(data, kwargs)

        # Render the template
        try:
            return await engine.render(template_name, context)
        except FileNotFoundError as e:
            raise ValueError(
                f"Template '{template_name}' not found. "
                f"Use add_template() to add in-memory templates or "
                f"ensure the template exists in the template directories."
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Failed to render template '{template_name}': {e}"
            ) from e

    def _prepare_template_context(
        self, data: Any, extra_kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prepare the context dictionary for template rendering.

        Args:
            data: The main data to render
            extra_kwargs: Additional kwargs to include in context

        Returns:
            Dictionary to pass to template
        """
        # Start with extra kwargs
        context = dict(extra_kwargs)

        # Handle different data types
        if isinstance(data, dict):
            # Merge dict data with kwargs (data takes precedence)
            context |= data
        elif hasattr(data, 'model_dump'):
            # Pydantic model
            context |= data.model_dump()
        elif hasattr(data, '__dataclass_fields__'):
            # Dataclass
            context |= asdict(data)
        else:
            # Primitive or unknown type - wrap as 'data'
            context['data'] = data

        return context
