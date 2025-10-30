# parrot/outputs/formats/charts/altair.py
from typing import Any, Optional, Tuple, Dict
import json
import uuid
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


@register_renderer(OutputMode.ALTAIR)
class AltairRenderer(BaseChart):
    """Renderer for Altair/Vega-Lite charts"""

    def execute_code(self, code: str) -> Tuple[Any, Optional[str]]:
        """Execute Altair code and return chart object."""
        try:
            namespace = {}
            exec(code, namespace)

            chart = next(
                (
                    namespace[var_name]
                    for var_name in ['chart', 'fig', 'c', 'plot']
                    if var_name in namespace
                ),
                None,
            )

            if chart is None:
                return None, "Code must define a chart variable (chart, fig, c, plot)"

            if not hasattr(chart, 'to_dict'):
                return None, f"Object is not an Altair chart: {type(chart)}"

            return chart, None

        except Exception as e:
            return None, f"Execution error: {str(e)}"

    def to_html(self, chart_obj: Any, **kwargs) -> str:
        """Convert Altair chart to HTML with vega-embed."""
        embed_options = kwargs.get('embed_options', {})
        spec = chart_obj.to_dict()
        spec_json = json.dumps(spec, indent=2)
        chart_id = f"altair-chart-{uuid.uuid4().hex[:8]}"

        default_options = {
            'actions': {'export': True, 'source': False, 'editor': False},
            'theme': 'latimes'
        }
        default_options |= embed_options
        options_json = json.dumps(default_options)

        return f'''
        <div id="{chart_id}"></div>
        <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
        <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
        <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
        <script type="text/javascript">
            vegaEmbed('#{chart_id}', {spec_json}, {options_json})
                .catch(console.error);
        </script>
        '''

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Export Vega-Lite JSON specification."""
        try:
            return chart_obj.to_dict()
        except Exception as e:
            return {'error': str(e)}

    def render(
        self,
        response: Any,
        export_format: str = 'html',
        return_code: bool = True,
        theme: str = 'monokai',
        environment: str = 'terminal',
        **kwargs
    ) -> Any:
        """Render Altair chart."""
        content = self._get_content(response)
        code = self._extract_code(content)

        if not code:
            return self._wrap_for_environment(
                "<div class='error'>No chart code found</div>",
                environment
            )

        chart_obj, error = self.execute_code(code)

        if error:
            return self._wrap_for_environment(
                self._render_error(error, code, theme),
                environment
            )

        if export_format == 'json':
            return self.to_json(chart_obj)

        elif export_format == 'html':
            html = self.to_html(chart_obj, **kwargs)
            if return_code:
                html += self._build_code_section(code, theme, "📊")
            return self._wrap_for_environment(html, environment)

        elif export_format == 'both':
            html = self.to_html(chart_obj, **kwargs)
            if return_code:
                html += self._build_code_section(code, theme, "📊")

            return {
                'html': self._wrap_for_environment(html, environment),
                'json': self.to_json(chart_obj),
                'code': code
            }

        return f"<div class='error'>Unknown export format: {export_format}</div>"
