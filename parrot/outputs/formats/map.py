# parrot/outputs/formats/map.py
from typing import Any, Optional, Tuple
import re
from io import StringIO
from . import register_renderer
from .base import BaseChart
from ...models.outputs import OutputMode


@register_renderer(OutputMode.MAP)
class MapRenderer(BaseChart):
    """Render Folium maps - inherits chart functionality"""

    def render(self, response: Any, **kwargs) -> Any:
        """Render map as HTML or ipywidget."""
        partial = kwargs.get('partial', True)
        return_code = kwargs.get('return_code', True)
        execute_code = kwargs.get('execute_code', True)
        theme = kwargs.get('theme', 'monokai')
        environment = kwargs.get('environment', 'terminal')

        content = self._get_content(response)
        code = self._extract_code(content)

        if not code:
            error_html = "<div class='error'>No map code found</div>"
            return self._wrap_for_environment(error_html, environment)

        if execute_code:
            map_obj, error = self.execute_code(code)
            if error:
                error_html = self._render_error(error, code, theme)
                return self._wrap_for_environment(error_html, environment)

            map_html = self.to_html(map_obj, partial=partial)

            if return_code:
                map_html += self._build_code_section(code, theme, "🗺️")

            return self._wrap_for_environment(map_html, environment)

        return f"<pre>{code}</pre>"

    def execute_code(self, code: str) -> Tuple[Any, Optional[str]]:
        """Execute Folium map code."""
        try:
            namespace = {}
            exec(code, namespace)

            map_obj = next(
                (
                    namespace[var_name]
                    for var_name in ['m', 'map', 'folium_map', 'my_map']
                    if var_name in namespace
                ),
                None,
            )

            if map_obj is None:
                return None, "Code must define a map variable (m, map, folium_map)"

            return map_obj, None

        except Exception as e:
            return None, f"Execution error: {str(e)}"

    def to_html(self, map_obj: Any, partial: bool = True, **kwargs) -> str:
        """Convert Folium map to HTML."""
        output = StringIO()
        map_obj.save(output, close_file=False)
        html = output.getvalue()
        output.close()

        return self._extract_partial(html) if partial else html

    @staticmethod
    def _extract_partial(full_html: str) -> str:
        """Extract map div and scripts for embedding."""


        style_match = re.search(r'<style>(.*?)</style>', full_html, re.DOTALL)
        styles = style_match[0] if style_match else ''

        script_pattern = r'<script[^>]*src=[^>]*></script>'
        scripts = re.findall(script_pattern, full_html)

        inline_scripts = re.findall(r'<script[^>]*>(.*?)</script>', full_html, re.DOTALL)

        div_match = re.search(
            r'<div[^>]*class="folium-map"[^>]*>.*?</div>',
            full_html,
            re.DOTALL
        )
        map_div = div_match[0] if div_match else full_html

        partial = styles + '\n'
        partial += '\n'.join(scripts) + '\n'
        partial += map_div + '\n'
        if inline_scripts:
            partial += '<script>\n' + '\n'.join(inline_scripts) + '\n</script>'

        return partial
