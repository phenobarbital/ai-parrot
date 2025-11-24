# parrot/outputs/formats/charts/altair.py
from typing import Any, Optional, Tuple, Dict
import json
import uuid
from .chart import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


ALTAIR_SYSTEM_PROMPT = """ALTAIR CHART OUTPUT MODE:
Generate an interactive chart using Altair (Vega-Lite).

REQUIREMENTS:
1. Return Python code in a markdown code block (```python)
2. Use altair library (import altair as alt)
3. Store the chart in a variable named 'chart', 'fig', 'c', or 'plot'
4. Make the chart self-contained with inline data when possible
5. Use appropriate mark types (mark_bar, mark_line, mark_point, etc.)
6. Include proper encodings (x, y, color, size, etc.)
7. Add titles and labels for clarity
8. DO NOT execute the code or save files - return code only

EXAMPLE:
```python
import altair as alt
import pandas as pd

data = pd.DataFrame({
    'category': ['A', 'B', 'C', 'D'],
    'values': [23, 45, 12, 67]
})

chart = alt.Chart(data).mark_bar().encode(
    x='category',
    y='values',
    color='category'
).properties(
    title='Sample Bar Chart',
    width=400,
    height=300
)
```
"""


@register_renderer(OutputMode.ALTAIR, system_prompt=ALTAIR_SYSTEM_PROMPT)
class AltairRenderer(BaseChart):
    """Renderer for Altair/Vega-Lite charts"""

    def execute_code(
        self,
        code: str,
        pandas_tool: Any = None,
        execution_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute Altair code within the agent's Python environment."""
        extra_namespace = None
        if pandas_tool is None:
            try:
                import altair as alt
                extra_namespace = {'alt': alt}
            except ImportError:
                pass

        # Execute using BaseRenderer logic
        context, error = super().execute_code(
            code,
            pandas_tool=pandas_tool,
            execution_state=execution_state,
            extra_namespace=extra_namespace,
            **kwargs,
        )

        if error:
            return None, error

        if not context:
            return None, "Execution context was empty"

        # Find the chart object (Altair typically produces single charts)
        chart, chart_error = self._find_chart_object(context)

        if chart:
            return chart, None

        if chart_error:
            return None, chart_error

        return None, "Code must define a chart variable (chart, fig, c, or plot)"

    @staticmethod
    def _find_chart_object(context: Dict[str, Any]) -> Tuple[Optional[Any], Optional[str]]:
        """Locate the Altair chart object in the local namespace.

        Returns a tuple of (chart_obj, error_message). The error_message is
        populated when a chart-like object is found but fails serialization
        (e.g., ``to_dict`` raises)."""

        def is_altair_chart(obj: Any) -> bool:
            """Check if object is an Altair chart."""
            if obj is None:
                return False

            # Skip renderer / BaseChart instances
            if isinstance(obj, BaseChart):
                return False

            # Altair charts have to_dict method
            if not hasattr(obj, 'to_dict'):
                return False

            # Check by class name
            class_name = obj.__class__.__name__
            altair_classes = ['Chart', 'LayerChart', 'HConcatChart', 'VConcatChart', 'FacetChart']
            if any(ac in class_name for ac in altair_classes):
                return True

            # Check module
            module = getattr(obj.__class__, '__module__', '')
            if 'altair' in module or 'vega' in module:
                return True

            return False

        def is_valid_chart(obj: Any) -> Tuple[bool, Optional[str]]:
            """Verify the chart can be serialized."""
            try:
                obj.to_dict()
                return True, None
            except Exception as exc:
                return False, str(exc)

        serialization_error = None

        # Priority search for common variable names
        priority_vars = ['chart', 'fig', 'c', 'plot', 'figure']
        for var_name in priority_vars:
            if var_name in context:
                obj = context[var_name]
                if is_altair_chart(obj):
                    is_valid, err_msg = is_valid_chart(obj)
                    if is_valid:
                        return obj, None
                    serialization_error = serialization_error or f"Chart variable '{var_name}' could not be serialized: {err_msg}"

        # Scan all locals for chart objects
        for var_name, obj in context.items():
            if var_name.startswith('_'):
                continue
            if is_altair_chart(obj):
                is_valid, err_msg = is_valid_chart(obj)
                if is_valid:
                    return obj, None
                serialization_error = serialization_error or f"Found a chart-like object in '{var_name}' but serialization failed: {err_msg}"

        if serialization_error:
            return None, serialization_error

        return None, None

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Render Altair-specific chart content with vega-embed."""
        embed_options = kwargs.get('embed_options', {})

        try:
            spec = chart_obj.to_dict()

            # Ensure charts expand to the available container space
            if not spec.get('autosize'):
                spec['autosize'] = {
                    'type': 'fit',
                    'contains': 'padding',
                    'resize': True
                }

            config = spec.setdefault('config', {})
            view_config = config.setdefault('view', {})
            view_config.setdefault('continuousWidth', 'container')
            view_config.setdefault('continuousHeight', 400)

            spec_json = json.dumps(spec, indent=2)
        except Exception as e:
            return f'''
            <div class="error-container">
                <h3>⚠️ Chart Serialization Error</h3>
                <p class="error-message">{str(e)}</p>
            </div>
            '''

        chart_id = f"altair-chart-{uuid.uuid4().hex[:8]}"

        default_options = {
            'actions': {'export': True, 'source': False, 'editor': False},
            'theme': kwargs.get('vega_theme', 'latimes')
        }
        default_options |= embed_options
        options_json = json.dumps(default_options)

        return f'''
        <div class="altair-chart-wrapper" style="margin-bottom: 20px;">
            <div id="{chart_id}" style="width: 100%; min-height: 400px;"></div>
            <script type="text/javascript">
                (function() {{
                    if (typeof vegaEmbed === 'undefined') {{
                        console.error("Vega-Embed library not loaded");
                        document.getElementById('{chart_id}').innerHTML =
                            '<div class="error-container">' +
                            '<h3>⚠️ Library Error</h3>' +
                            '<p class="error-message">Vega-Embed library not loaded</p>' +
                            '</div>';
                        return;
                    }}

                    vegaEmbed('#{chart_id}', {spec_json}, {options_json})
                        .then(result => {{
                            console.log('Altair chart {chart_id} rendered successfully');
                        }})
                        .catch(error => {{
                            console.error('Error rendering Altair chart:', error);
                            document.getElementById('{chart_id}').innerHTML =
                                '<div class="error-container">' +
                                '<h3>⚠️ Chart Rendering Error</h3>' +
                                '<p class="error-message">' + error.message + '</p>' +
                                '</div>';
                        }});
                }})();
            </script>
        </div>
        '''

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """
        Convert Altair chart to HTML.

        Args:
            chart_obj: Altair chart object
            mode: 'partial' or 'complete'
            **kwargs: Additional parameters

        Returns:
            HTML string
        """
        # Vega libraries for <head>
        extra_head = '''
    <!-- Vega/Vega-Lite/Vega-Embed -->
    <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
        '''

        kwargs['extra_head'] = kwargs.get('extra_head', extra_head)

        # Call parent to_html which uses _render_chart_content
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Export Vega-Lite JSON specification."""
        try:
            return chart_obj.to_dict()
        except Exception as e:
            return {'error': str(e)}

    async def render(
        self,
        response: Any,
        theme: str = 'monokai',
        environment: str = 'html',
        include_code: bool = False,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """
        Render Altair chart.

        Environments:
        - 'html': Returns HTML with embedded Vega-Embed
        - 'default': Returns JSON specification (Vega-Lite spec)
        - 'json': Returns JSON specification
        - 'jupyter'/'notebook': Returns chart object for native rendering
        - 'terminal': Returns code only

        Returns:
            Tuple[Any, Optional[Any]]: (code, output)
            - code goes to response.output
            - output goes to response.response
        """

        # 1. Extract Code
        code = getattr(response, 'code', None)
        output_format = kwargs.get('output_format', environment)

        # Fallback to extracting from text content
        if not code:
            content = self._get_content(response)
            code = self._extract_code(content)

        if not code:
            error_msg = "No chart code found in response"
            if output_format == 'terminal':
                return error_msg, None
            return self._wrap_for_environment(
                f"<div class='error'>{error_msg}</div>",
                output_format
            ), None

        # 2. Execute Code
        chart_obj, error = self.execute_code(
            code,
            pandas_tool=kwargs.pop('pandas_tool', None),
            execution_state=kwargs.pop('execution_state', None),
            **kwargs,
        )

        if error:
            if output_format == 'terminal':
                return f"Error generating chart: {error}", None
            return self._wrap_for_environment(
                self._render_error(error, code, theme),
                output_format
            ), None

        # 3. Handle different output formats

        # Terminal: just return code
        if output_format == 'terminal':
            return code, None

        # Jupyter/Notebook: return chart object for native rendering
        if output_format in {'jupyter', 'notebook', 'ipython', 'colab'}:
            return code, chart_obj

        # Default: return JSON specification (Vega-Lite spec)
        if output_format == 'default':
            json_spec = self.to_json(chart_obj)
            return code, json_spec

        # JSON: explicit JSON request
        if output_format == 'json':
            return code, self.to_json(chart_obj)

        # HTML (default): Generate embedded HTML
        html_output = self.to_html(
            chart_obj,
            mode=html_mode,
            include_code=include_code,
            code=code,
            theme=theme,
            title=kwargs.get('title', 'Altair Chart'),
            icon='📊',
            **kwargs
        )

        return code, html_output
