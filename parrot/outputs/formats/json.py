from typing import Any, Tuple, Optional
import orjson
from datamodel.parsers.json import JSONContent, json_encoder, json_decoder
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


@register_renderer(OutputMode.JSON)
class JSONRenderer(BaseRenderer):
    """Renderer for JSON output using orjson (Rust) or standard json"""

    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        """
        Render response as JSON.
        """
        indent = kwargs.get('indent')
        include_metadata = kwargs.get('include_metadata', False)
        data = self._prepare_data(response, include_metadata)

        if isinstance(data, str):
            try:
                data = json_decoder(data)
            except Exception:
                pass

        try:
            options = orjson.OPT_INDENT_2 if indent is not None else 0
            json_bytes = orjson.dumps(data, option=options)
            json_string = json_bytes.decode('utf-8')
        except (TypeError, ImportError):
            json_string = json_encoder(data)

        wrapped_output = self._wrap_output(json_string, environment)
        return json_string, wrapped_output

    def _wrap_output(self, json_string: str, environment: str) -> Any:
        """Wrap the JSON string for different environments."""
        if environment == 'terminal':
            try:
                from rich.panel import Panel as RichPanel
                from rich.syntax import Syntax

                syntax = Syntax(json_string, "json", theme="default", line_numbers=True)
                return RichPanel(syntax, title="JSON Response", border_style="magenta")
            except ImportError:
                return json_string

        elif environment == 'html':
            try:
                from pygments import highlight
                from pygments.lexers import JsonLexer
                from pygments.formatters import HtmlFormatter

                formatter = HtmlFormatter(style='default', full=True, nobackground=True)
                highlighted_code = highlight(json_string, JsonLexer(), formatter)
                return f'<div class="json-response">{highlighted_code}</div>'
            except ImportError:
                return f'<pre><code>{json_string}</code></pre>'

        return json_string
