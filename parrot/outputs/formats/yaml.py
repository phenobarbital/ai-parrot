from typing import Any, Tuple
import json
from dataclasses import is_dataclass, asdict
from pydantic import BaseModel
try:
    import yaml_rs  # pylint: disable=E0401  # noqa
    YAML_RS_AVAILABLE = True
except ImportError:
    YAML_RS_AVAILABLE = False
import pandas as pd
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611  # noqa
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


@register_renderer(OutputMode.YAML)
class YAMLRenderer(BaseRenderer):
    """Renderer for YAML output using yaml-rs (Rust) or PyYAML fallback"""

    def _json_as_yaml(self, data: Any, indent: int = 2) -> str:
        """
        Fallback: Format JSON as YAML-like structure.
        Useful when yaml_rs is missing or fails on specific types.
        """
        try:
            # First ensure it's serializable via json_encoder logic
            if not isinstance(data, str):
                data = json.loads(json_encoder(data))

            import yaml
            return yaml.dump(data, indent=indent, sort_keys=False, default_flow_style=False)
        except ImportError:
            # Manual JSON-to-YAML-ish conversion if PyYAML is also missing
            json_str = json.dumps(data, indent=indent, sort_keys=False)
            yaml_like = json_str.replace('{', '').replace('}', '')
            yaml_like = yaml_like.replace('[', '').replace(']', '')
            yaml_like = yaml_like.replace('",', '"')
            return yaml_like.replace('"', '')

    def _serialize(self, data: Any, indent: int = 2, sort_keys: bool = False) -> str:
        """Serialize data to YAML string."""
        try:
            if isinstance(data, pd.DataFrame):
                data = data.to_dict(orient='records')
            elif is_dataclass(data):
                data = asdict(data)
            elif isinstance(data, BaseModel):
                data = data.model_dump()
            if not YAML_RS_AVAILABLE:
                return self._json_as_yaml(data, indent)
            try:
                return yaml_rs.dumps(data, indent=indent, sort_keys=sort_keys)
            except Exception:
                # Fallback to python implementation on error
                return self._json_as_yaml(data, indent)
        except Exception as e:
            print('DATA > ', data)
            return f"error_serializing_to_yaml: {str(e)}"

    def _wrap_output(self, yaml_string: str, environment: str) -> Any:
        """
        Wrap the YAML string into an environment-specific container.
        """
        # --- Terminal (Rich) ---
        if environment == 'terminal':
            try:
                from rich.panel import Panel as RichPanel
                from rich.syntax import Syntax

                syntax = Syntax(yaml_string, "yaml", theme="monokai", line_numbers=True)
                return RichPanel(syntax, title="YAML Output", border_style="green")
            except ImportError:
                return yaml_string

        # --- Jupyter / Notebook ---
        elif environment in {'jupyter', 'notebook'}:
            try:
                from ipywidgets import HTML
                from pygments import highlight
                from pygments.lexers import YamlLexer
                from pygments.formatters import HtmlFormatter

                formatter = HtmlFormatter(style='colorful', noclasses=True)
                highlighted_html = highlight(yaml_string, YamlLexer(), formatter)

                return HTML(
                    value=f'<div style="max-height: 500px; overflow-y: auto; background-color: #f8f8f8; padding: 10px;">{highlighted_html}</div>'
                )
            except ImportError:
                return self._wrap_html(yaml_string)

        # --- HTML ---
        elif environment == 'html':
            return self._wrap_html(yaml_string)

        # Default
        return yaml_string

    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        **kwargs,
    ) -> Tuple[str, Any]:
        """
        Render response as YAML.

        Returns:
            Tuple[str, Any]: (yaml_string, wrapped_content)
        """
        indent = kwargs.get('indent', 2)
        sort_keys = kwargs.get('sort_keys', False)
        output_format = kwargs.get('output_format', environment)

        # 1. Extract Data
        data = self._extract_data(response)

        # 2. Serialize to content string
        yaml_string = self._serialize(data, indent=indent, sort_keys=sort_keys)

        # 3. Wrap content based on environment
        wrapped_output = self._wrap_output(yaml_string, output_format)

        return yaml_string, wrapped_output
