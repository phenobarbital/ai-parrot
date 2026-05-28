import mimetypes
from typing import Any, Tuple

from jinja2 import Environment

from ...models.outputs import OutputMode
from . import register_renderer
from .base import BaseRenderer


@register_renderer(OutputMode.JINJA2)
class Jinja2Renderer(BaseRenderer):
    """
    Renders the output using a Jinja2 template.
    """

    async def render(self, data: Any, **kwargs: Any) -> Tuple[str, str]:
        """
        Renders data using a Jinja2 template asynchronously.

        Args:
            data: The data to render.
            **kwargs: Must contain 'env' (a Jinja2 Environment) and 'template' (the template name).

        Returns:
            A tuple containing the rendered content and the guessed MIME type.
        """
        env: Environment = kwargs.get("env")
        if not env:
            raise ValueError("Jinja2 environment not provided in kwargs.")

        template_name: str = kwargs.get("template")
        if not template_name:
            raise ValueError("Jinja2 template name not provided in kwargs.")

        try:
            template = env.get_template(template_name)
        except Exception as e:
            raise ValueError(
                f"Failed to load Jinja2 template '{template_name}': {e}"
            ) from e

        content_type = mimetypes.guess_type(template_name)[0] or "text/plain"

        rendered_content = await template.render_async(**data)
        return rendered_content, content_type
