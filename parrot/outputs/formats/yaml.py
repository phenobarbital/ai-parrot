from typing import Any, Tuple, Optional
import json
import yaml_rs
from datamodel.parsers.json import json_encoder
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


@register_renderer(OutputMode.YAML)
class YAMLRenderer(BaseRenderer):
    """Renderer for YAML output using yaml-rs (Rust) or PyYAML fallback"""

    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        """
        Render response as YAML.
        """
        indent = kwargs.get('indent', 2)
        sort_keys = kwargs.get('sort_keys', False)
        include_metadata = kwargs.get('include_metadata', False)

        data = self._prepare_data(response, include_metadata)
        try:
            yaml_string = yaml_rs.dumps(data, indent=indent, sort_keys=sort_keys)
        except Exception:
            yaml_string = self._json_as_yaml(data, indent)

        wrapped_output = self._wrap_output(yaml_string, environment)
        return yaml_string, wrapped_output

    def _json_as_yaml(self, data: Any, indent: int = 2) -> str:
        """
        Fallback: Format JSON as YAML-like structure.
        """
        try:
            json_str = json_encoder(data)
        except ImportError:
            json_str = json.dumps(data, indent=indent, sort_keys=True)

        yaml_like = json_str.replace('{', '').replace('}', '')
        yaml_like = yaml_like.replace('[', '').replace(']', '')
        yaml_like = yaml_like.replace('",', '"')
        yaml_like = yaml_like.replace('":', ':')
        return yaml_like.replace('"', '')

    def _wrap_output(self, yaml_string: str, environment: str) -> Any:
        if environment == 'terminal':
            try:
                from rich.panel import Panel as RichPanel
                from rich.syntax import Syntax

                syntax = Syntax(yaml_string, "yaml", theme="default", line_numbers=True)
                return RichPanel(syntax, title="YAML Response", border_style="green")
            except ImportError:
                return yaml_string
        elif environment == 'html':
            from pygments import highlight
            from pygments.lexers import YamlLexer
            from pygments.formatters import HtmlFormatter

            formatter = HtmlFormatter(style='default', full=True, nobackground=True)
            highlighted_code = highlight(yaml_string, YamlLexer(), formatter)
            return f'<div class="yaml-response">{highlighted_code}</div>'

        return yaml_string
