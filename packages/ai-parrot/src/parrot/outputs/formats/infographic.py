"""
Infographic Renderer for AI-Parrot.

Renders InfographicResponse structured output as JSON suitable
for frontend consumption. The renderer validates the block structure
and serializes it; the frontend handles all visual rendering.
"""
from typing import Any, Tuple, Optional
import orjson
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode
from ...models.infographic import InfographicResponse


INFOGRAPHIC_SYSTEM_PROMPT = """INFOGRAPHIC STRUCTURED OUTPUT MODE - CRITICAL INSTRUCTIONS:

You MUST respond with a valid JSON object matching the InfographicResponse schema.
The response contains an ordered list of typed "blocks" that form the infographic.

Available block types:
- title: Main heading with subtitle, author, date
- hero_card: Key metric card with value, label, trend, icon
- summary: Rich text paragraph (supports markdown)
- chart: Data visualization spec with chart_type, labels, series
- bullet_list: Ordered/unordered list of items
- table: Tabular data with columns and rows
- image: Image reference with URL/base64 and alt text
- quote: Highlighted quote with attribution
- callout: Alert/info/warning/success box
- divider: Visual separator
- timeline: Chronological sequence of events
- progress: Completion/progress indicators

Rules:
- Every block MUST include a "type" field
- hero_card blocks: use descriptive labels and formatted values (e.g., "$1.2M", "98%")
- chart blocks: include labels array and series with name+values
- All text fields support markdown formatting
- Output ONLY valid JSON, no explanatory text before or after
"""


@register_renderer(OutputMode.INFOGRAPHIC, system_prompt=INFOGRAPHIC_SYSTEM_PROMPT)
class InfographicRenderer(BaseRenderer):
    """Renderer for structured infographic output.

    Validates and serializes InfographicResponse blocks as JSON.
    The frontend is responsible for visual rendering.
    """

    async def render(
        self,
        response: Any,
        environment: str = 'default',
        **kwargs,
    ) -> Tuple[str, Optional[Any]]:
        """Render infographic response as structured JSON.

        Args:
            response: AIMessage containing InfographicResponse data.
            environment: Output environment ('default', 'html', 'terminal').
            **kwargs: Additional rendering options.

        Returns:
            Tuple[str, Any]: (json_string, wrapped_content)
        """
        data = self._extract_infographic_data(response)
        json_bytes = orjson.dumps(data, option=orjson.OPT_INDENT_2)
        json_string = json_bytes.decode("utf-8")

        wrapped = self._wrap_output(json_string, data, environment)
        return json_string, wrapped

    def _extract_infographic_data(self, response: Any) -> dict:
        """Extract infographic data from the AIMessage response.

        Handles multiple scenarios:
        1. response.structured_output is an InfographicResponse
        2. response.output is an InfographicResponse
        3. response.output is a dict with blocks
        4. Raw dict/string fallback

        Args:
            response: The AIMessage or raw data.

        Returns:
            Dict representation of the InfographicResponse.
        """
        # Try structured_output first (immutable original)
        output = None
        if hasattr(response, 'structured_output') and response.structured_output:
            output = response.structured_output
        elif hasattr(response, 'output') and response.output:
            output = response.output
        elif hasattr(response, 'data') and response.data:
            output = response.data
        else:
            output = response

        # Already an InfographicResponse model
        if isinstance(output, InfographicResponse):
            return output.model_dump(exclude_none=True)

        # Dict with blocks key
        if isinstance(output, dict) and 'blocks' in output:
            return output

        # Try parsing as InfographicResponse
        if isinstance(output, dict):
            try:
                parsed = InfographicResponse.model_validate(output)
                return parsed.model_dump(exclude_none=True)
            except Exception:
                pass

        # String fallback - try JSON parse
        if isinstance(output, str):
            try:
                parsed_dict = orjson.loads(output)
                if isinstance(parsed_dict, dict) and 'blocks' in parsed_dict:
                    return parsed_dict
            except Exception:
                pass

        # Last resort: wrap raw content as a single summary block
        return {
            "blocks": [
                {
                    "type": "summary",
                    "content": str(output),
                }
            ]
        }

    def _wrap_output(self, json_string: str, data: dict, environment: str) -> Any:
        """Wrap JSON output for the target environment.

        Args:
            json_string: Serialized JSON string.
            data: The infographic data dict.
            environment: Target environment.

        Returns:
            Environment-appropriate wrapped content.
        """
        if environment == 'terminal':
            try:
                from rich.panel import Panel
                from rich.json import JSON as RichJSON
                return Panel(
                    RichJSON(json_string),
                    title="Infographic Output",
                    border_style="blue",
                )
            except ImportError:
                return json_string

        if environment == 'html':
            return self._wrap_html(json_string)

        # Default: return the dict directly for API consumers
        return data

    def _wrap_html(self, json_string: str) -> str:
        """Wrap JSON in syntax-highlighted HTML.

        Args:
            json_string: The JSON string to highlight.

        Returns:
            HTML string with syntax highlighting.
        """
        try:
            from pygments import highlight
            from pygments.lexers import JsonLexer
            from pygments.formatters import HtmlFormatter
            formatter = HtmlFormatter(style='monokai', noclasses=True)
            highlighted = highlight(json_string, JsonLexer(), formatter)
            return (
                '<div style="background:#272822;padding:16px;border-radius:8px;'
                f'overflow-x:auto;font-size:13px;">{highlighted}</div>'
            )
        except ImportError:
            return f"<pre><code>{json_string}</code></pre>"
