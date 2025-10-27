from typing import Any
import orjson
from datamodel.parsers.json import JSONContent, json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


@register_renderer(OutputMode.JSON)
class JSONRenderer(BaseRenderer):
    """Renderer for JSON output using orjson (Rust) or standard json"""

    @staticmethod
    def render(response: Any, **kwargs) -> str:
        """
        Render response as JSON.

        Args:
            response: AIMessage or any serializable object
            **kwargs: Additional rendering options
                - indent: Number of spaces (default: 2)
                - sort_keys: Sort keys (default: False)
                - include_metadata: Include full metadata (default: False)

        Returns:
            JSON string
        """
        indent = kwargs.get('indent')
        include_metadata = kwargs.get('include_metadata', False)
        data = JSONRenderer._prepare_data(response, include_metadata)
        if isinstance(data, str):
            data = json_decoder(data)
        try:
            options = orjson.OPT_INDENT_2 if indent else None  # pylint: disable=E1101 # noqa
            return JSONContent().dumps(data, option=options)
        except ImportError:
            # Fallback to standard json
            return json_encoder(data)
