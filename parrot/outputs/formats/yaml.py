from typing import Any
import json
import yaml_rs  # pylint: disable=E0401 # noqa
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611 # noqa
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


@register_renderer(OutputMode.YAML)
class YAMLRenderer(BaseRenderer):
    """Renderer for YAML output using yaml-rs (Rust) or PyYAML fallback"""

    @staticmethod
    def render(response: Any, **kwargs) -> str:
        """
        Render response as YAML.

        Args:
            response: AIMessage or any serializable object
            **kwargs: Additional rendering options
                - indent: Number of spaces for indentation (default: 2)
                - sort_keys: Sort dictionary keys (default: False)
                - include_metadata: Include full metadata (default: False)

        Returns:
            YAML string representation
        """
        indent = kwargs.get('indent', 2)
        sort_keys = kwargs.get('sort_keys', False)
        include_metadata = kwargs.get('include_metadata', False)

        # Get the data to serialize
        data = YAMLRenderer._prepare_data(response, include_metadata)
        try:
            return yaml_rs.dumps(
                data,
                indent=indent,
                sort_keys=sort_keys
            )
        except Exception as e:
            # Ultimate fallback: JSON with YAML-like formatting
            return YAMLRenderer._json_as_yaml(data, indent)

    @staticmethod
    def _json_as_yaml(data: Any, indent: int = 2) -> str:
        """
        Fallback: Format JSON as YAML-like structure.
        This is used when neither yaml-rs nor PyYAML is available.
        """
        try:
            json_str = json_encoder(data)
        except ImportError:
            json_str = json.dumps(data, indent=indent, sort_keys=True)

        # Convert JSON to YAML-like format (simple transformation)
        yaml_like = json_str.replace('{', '').replace('}', '')
        yaml_like = yaml_like.replace('[', '').replace(']', '')
        yaml_like = yaml_like.replace('",', '"')
        yaml_like = yaml_like.replace('":', ':')
        return yaml_like.replace('"', '')
