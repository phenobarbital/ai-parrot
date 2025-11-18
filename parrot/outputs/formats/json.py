from typing import Any, Tuple, Optional
from datetime import datetime
from dataclasses import is_dataclass, asdict
import pandas as pd
from pydantic import BaseModel
import orjson
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611  # noqa
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


@register_renderer(OutputMode.JSON)
class JSONRenderer(BaseRenderer):
    """
    Renderer for JSON output.
    Handles PandasAgentResponse, DataFrames, Pydantic models, and generic content.
    Adapts output format to Terminal (Rich), HTML (Pygments), and Jupyter (Widgets).
    """
    def _default_serializer(self, obj: Any) -> Any:
        """Custom serializer for non-JSON-serializable objects."""
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient='records')
        if isinstance(obj, set):
            return list(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def _extract_data(self, response: Any) -> Any:
        """
        Extract serializable data based on response content type rules.
        """
        # 1. Check for PandasAgentResponse (duck typing to avoid circular imports)
        # We check for specific attributes that define a PandasAgentResponse
        output = getattr(response, 'output', None)

        if output is not None:
            # Handle PandasAgentResponse specifically
            if hasattr(output, 'to_dataframe') and hasattr(output, 'explanation') and hasattr(output, 'data'):
                # response.data is usually a PandasTable
                return output.to_dataframe() if output.data is not None else []

            # 2. Handle direct DataFrame output
            if isinstance(output, pd.DataFrame):
                return output.to_dict(orient='records')

            # 3. Handle Pydantic Models
            if isinstance(output, BaseModel):
                return output.model_dump()

            # 4. Handle Dataclasses
            if is_dataclass(output):
                return asdict(output)

        # 5. Fallback for unstructured/plain text responses
        # "if there is no 'structured output response', build a JSON with input/output"
        is_structured = getattr(response, 'is_structured', False)
        if not is_structured and output:
            return {
                "input": getattr(response, 'input', ''),
                "output": output,
                "metadata": getattr(response, 'metadata', {})
            }

        return output

    def _serialize(self, data: Any, indent: Optional[int] = None) -> str:
        """Serialize data to JSON string using orjson if available."""
        try:
            option = orjson.OPT_INDENT_2 if indent is not None else 0
            # orjson returns bytes, decode to str
            return orjson.dumps(
                data,
                default=self._default_serializer,
                option=option
            ).decode('utf-8')
        except Exception:
            return json_encoder(
                data
            )

    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        """
        Render response as JSON.

        Returns:
            Tuple[str, Any]: (json_string, wrapped_content)
        """
        indent = kwargs.get('indent')
        include_metadata = kwargs.get('include_metadata', False)
        data = self._prepare_data(response, include_metadata)

        output_format = kwargs.get('output_format', environment)

        # 1. Extract Data
        data = self._extract_data(response)

        # 2. Serialize to content string
        json_string = self._serialize(data, indent=indent)

        # 3. Wrap content based on environment
        wrapped_output = self._wrap_output(json_string, data, output_format)

        return json_string, wrapped_output

    def _wrap_output(self, json_string: str, data: Any, environment: str) -> Any:
        """
        Wrap the JSON string into an environment-specific container.
        """
        if environment == 'terminal':
            try:
                from rich.panel import Panel
                from rich.syntax import Syntax
                from rich.json import JSON as RichJSON

                # Use Rich's native JSON rendering if possible for better formatting
                return Panel(
                    RichJSON(json_string),
                    title="JSON Output",
                    border_style="green"
                )
            except ImportError:
                return json_string

        elif environment in {'jupyter', 'notebook'}:
            try:
                # For Jupyter, we try to return a Widget or specialized display object
                # Method A: ipywidgets (Interactive)
                from ipywidgets import HTML

                # Create formatted HTML for the JSON
                from pygments import highlight
                from pygments.lexers import JsonLexer
                from pygments.formatters import HtmlFormatter

                formatter = HtmlFormatter(style='colorful', noclasses=True)
                highlighted_html = highlight(json_string, JsonLexer(), formatter)

                # Wrap in a widget
                widget = HTML(
                    value=f'<div style="max-height: 500px; overflow-y: auto; background-color: #f8f8f8; padding: 10px;">{highlighted_html}</div>'
                )
                return widget

            except ImportError:
                # Fallback to HTML representation if widgets not available
                return self._wrap_html(json_string)

        elif environment == 'html':
            return self._wrap_html(json_string)

        # Default / Text
        return json_string

    def _wrap_html(self, json_string: str) -> str:
        """Helper to wrap JSON in HTML with highlighting."""
        try:
            from pygments import highlight
            from pygments.lexers import JsonLexer
            from pygments.formatters import HtmlFormatter

            formatter = HtmlFormatter(style='default', full=False, noclasses=True)
            highlighted_code = highlight(json_string, JsonLexer(), formatter)
            return f'<div class="json-response" style="padding:1em; border:1px solid #ddd; border-radius:4px;">{highlighted_code}</div>'
        except ImportError:
            return f'<pre><code class="language-json">{json_string}</code></pre>'
