# parrot/outputs/formats/map.py
from typing import Any, Optional
import re
from io import StringIO
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode

# Check for ipywidgets
try:
    from ipywidgets import HTML as IPyHTML
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False


@register_renderer(OutputMode.MAP)
class MapRenderer(BaseRenderer):
    """Render Folium maps from code or pre-generated HTML"""

    @staticmethod
    def render(response: Any, **kwargs) -> Any:
        """
        Render map as HTML or ipywidget.

        Args:
            response: AIMessage with map code
            **kwargs:
                - partial: Return partial HTML (default: True)
                - return_code: Show code in collapsible section (default: True)
                - execute_code: Execute code to generate map (default: True)
                - theme: Code highlight theme (default: 'monokai')
                - environment: Execution environment ('jupyter', 'terminal', 'colab')

        Returns:
            ipywidgets.HTML widget (Jupyter) or HTML string
        """
        partial = kwargs.get('partial', True)
        return_code = kwargs.get('return_code', True)
        execute_code = kwargs.get('execute_code', True)
        theme = kwargs.get('theme', 'monokai')
        environment = kwargs.get('environment', 'terminal')

        content = MapRenderer._get_content(response)
        code = MapRenderer._extract_code(content)

        if not code:
            error_html = "<div class='error'>No map code found in response</div>"
            return MapRenderer._wrap_for_environment(error_html, environment)

        if execute_code:
            map_html, error = MapRenderer._execute_map_code(code)
            if error:
                error_html = MapRenderer._render_error(error, code, theme)
                return MapRenderer._wrap_for_environment(error_html, environment)

            # Extract components from Folium HTML
            if partial:
                map_html = MapRenderer._extract_partial(map_html)

            final_html = MapRenderer._build_html(
                map_html,
                code if return_code else None,
                theme,
                partial
            )

            # Return ipywidget in Jupyter, HTML string otherwise
            return MapRenderer._wrap_for_environment(final_html, environment)

        return f"<pre>{code}</pre>"

    @staticmethod
    def _wrap_for_environment(html: str, environment: str) -> Any:
        """Wrap HTML based on environment."""
        if environment in ('jupyter', 'colab') and IPYWIDGETS_AVAILABLE:
            return IPyHTML(value=html)
        return html

    @staticmethod
    def _extract_code(content: str) -> Optional[str]:
        """Extract Python code from markdown blocks."""
        pattern = r'```(?:python)?\n(.*?)```'
        matches = re.findall(pattern, content, re.DOTALL)
        return matches[0].strip() if matches else None

    @staticmethod
    def _execute_map_code(code: str) -> tuple[str, Optional[str]]:
        """Execute Folium code and return HTML."""
        try:
            namespace = {}
            exec(code, namespace)

            # Look for map variable
            map_obj = None
            for var_name in ['m', 'map', 'folium_map', 'my_map']:
                if var_name in namespace:
                    map_obj = namespace[var_name]
                    break

            if map_obj is None:
                return None, "Code must define a map variable (m, map, folium_map)"

            # Save to StringIO
            output = StringIO()
            map_obj.save(output, close_file=False)
            html = output.getvalue()
            output.close()

            return html, None

        except Exception as e:
            return None, f"Execution error: {str(e)}"

    @staticmethod
    def _extract_partial(full_html: str) -> str:
        """Extract just the map div and required scripts."""
        # Extract styles
        style_match = re.search(r'<style>(.*?)</style>', full_html, re.DOTALL)
        styles = style_match.group(0) if style_match else ''

        # Extract scripts (Leaflet, etc.)
        script_pattern = r'<script[^>]*src=[^>]*></script>'
        scripts = re.findall(script_pattern, full_html)

        # Extract inline scripts
        inline_scripts = re.findall(
            r'<script[^>]*>(.*?)</script>',
            full_html,
            re.DOTALL
        )

        # Extract map div
        div_match = re.search(
            r'<div[^>]*class="folium-map"[^>]*>.*?</div>',
            full_html,
            re.DOTALL
        )
        map_div = div_match.group(0) if div_match else full_html

        # Combine
        partial = styles + '\n'
        partial += '\n'.join(scripts) + '\n'
        partial += map_div + '\n'
        if inline_scripts:
            partial += '<script>\n' + '\n'.join(inline_scripts) + '\n</script>'

        return partial

    @staticmethod
    def _build_html(
        map_html: str,
        code: Optional[str],
        theme: str,
        partial: bool
    ) -> str:
        """Build final HTML with map and optional code."""
        if partial:
            parts = [map_html]
            if code:
                parts.append(MapRenderer._build_code_section(code, theme))
            return '\n'.join(parts)

        # Complete document
        html_parts = ['''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Map Visualization</title>
        ''']

        html_parts.append(MapRenderer._get_html_styles())
        html_parts.append('</head><body>')
        html_parts.append('<div class="map-container">')
        html_parts.append(map_html)
        html_parts.append('</div>')

        if code:
            html_parts.append(MapRenderer._build_code_section(code, theme))

        html_parts.append('</body></html>')
        return '\n'.join(html_parts)

    @staticmethod
    def _build_code_section(code: str, theme: str) -> str:
        """Build collapsible code section."""
        from .charts import ChartRenderer
        highlighted = ChartRenderer._highlight_code(code, theme)

        return f'''
        <details class="code-accordion">
            <summary class="code-header">
                <span>🗺️ View Map Code</span>
                <span class="toggle-icon">▶</span>
            </summary>
            <div class="code-content">
                {highlighted}
            </div>
        </details>
        '''

    @staticmethod
    def _render_error(error: str, code: str, theme: str) -> str:
        """Render error with code."""
        from .charts import ChartRenderer
        highlighted = ChartRenderer._highlight_code(code, theme)

        return f'''
        {MapRenderer._get_html_styles()}
        <div class="error-container">
            <h3>⚠️ Map Generation Error</h3>
            <p class="error-message">{error}</p>
            <details class="code-accordion" open>
                <summary class="code-header">Code with Error</summary>
                <div class="code-content">{highlighted}</div>
            </details>
        </div>
        '''

    @staticmethod
    def _get_html_styles() -> str:
        """CSS styles for map rendering."""
        return '''
        <style>
            .map-container {
                width: 100%;
                height: 600px;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                overflow: hidden;
                margin: 20px 0;
            }
            .code-accordion {
                margin-top: 20px;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                overflow: hidden;
            }
            .code-header {
                background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
                color: white;
                padding: 12px 20px;
                cursor: pointer;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-weight: 600;
                user-select: none;
            }
            .code-header:hover {
                background: linear-gradient(135deg, #0e8577 0%, #2dd368 100%);
            }
            .toggle-icon {
                transition: transform 0.3s ease;
            }
            details[open] .toggle-icon {
                transform: rotate(90deg);
            }
            .code-content {
                background: #272822;
                padding: 15px;
                overflow-x: auto;
            }
            .error-container {
                background: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }
            .error-message {
                color: #856404;
                font-weight: 500;
            }
        </style>
        '''
