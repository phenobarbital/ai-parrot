from typing import Any, Dict
import json
import pandas as pd
from .abstract import AbstractAppGenerator


class PanelGenerator(AbstractAppGenerator):
    """Generates a single-file Panel application."""

    def generate(self) -> str:
        # 1. Serialize Data for Embedding
        data_str = "[]"
        if not self.payload["data"].empty:
            data_str = self.payload["data"].to_json(orient="records")

        # 2. Sanitize Strings
        explanation = self.payload["explanation"].replace('"""', "\\\"\\\"\\\"")
        query = self.payload["input"].replace('"', '\\"')
        # 3. Construct Visualization Logic
        viz_code = ""
        imports = ["import panel as pn", "import pandas as pd", "import json"]

        if code_snippet := self.payload["code"]:
            if isinstance(code_snippet, (dict, list)):
                # JSON Specification (Altair/Vega-Lite)
                imports.append("import altair as alt")
                viz_code = f"""
# --- Visualization (Vega-Lite JSON) ---
spec = {json.dumps(code_snippet)}
viz_pane = pn.pane.Vega(spec, sizing_mode='stretch_width', height=400)
                """
            elif isinstance(code_snippet, str):
                # Python Code Execution
                # We wrap the execution to capture the figure
                viz_code = f"""
# --- Visualization (Dynamic Code) ---
def get_visualization(df):
    try:
        # Inject dataframe into local scope
        local_vars = {{'df': df, 'pd': pd, 'pn': pn}}

        # Execute the generated code
        exec('''{code_snippet}''', globals(), local_vars)

        # Attempt to find a renderable object in locals
        # Priority: 'fig', 'chart', 'map', or the last expression
        for var_name in ['fig', 'chart', 'map', 'm']:
            if var_name in local_vars:
                return local_vars[var_name]
        return None
    except Exception as e:
        return pn.pane.Alert(f"Error rendering chart: {{e}}", alert_type="danger")

viz_obj = get_visualization(df)

# Determine appropriate pane type based on object
if viz_obj:
    if hasattr(viz_obj, 'to_dict') and 'data' in viz_obj.to_dict(): # Plotly
        viz_pane = pn.pane.Plotly(viz_obj, sizing_mode='stretch_width', height=400)
    elif hasattr(viz_obj, 'savefig'): # Matplotlib
        viz_pane = pn.pane.Matplotlib(viz_obj, sizing_mode='stretch_width', height=400, tight=True)
    elif hasattr(viz_obj, 'save') and hasattr(viz_obj, '_repr_html_'): # Folium/Altair
        viz_pane = pn.pane.plot.Folium(viz_obj, sizing_mode='stretch_width', height=400)
    else:
        # Fallback/Generic (HoloViews, Bokeh, etc.)
        viz_pane = pn.panel(viz_obj, sizing_mode='stretch_width')
else:
    viz_pane = pn.pane.Markdown("No visualization generated.")
                """
                # Add common imports just in case the generated code needs them
                imports.extend([
                    "import matplotlib.pyplot as plt",
                    "import plotly.express as px",
                    "import plotly.graph_objects as go",
                    "import altair as alt"
                ])
        else:
            viz_pane = "viz_pane = pn.pane.Markdown('No visualization requested.')"
            viz_code = viz_pane

        imports = "\n".join(sorted(list(set(imports))))

        # 4. Generate Full Script
        return f"""
{imports}
pn.extension('tabulator', 'vega', 'plotly', 'katex', design='bootstrap')

# --- Data Loading ---
@pn.cache
def load_data():
    raw_json = '{data_str}'
    try:
        data = json.loads(raw_json)
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

df = load_data()

# --- Visualizations ---
{viz_code}

# --- Layout Components ---
title = pn.pane.Markdown(f"# 🤖 AI Analysis Report\\n**Query:** `{query}`", sizing_mode='stretch_width')

explanation_pane = pn.pane.Markdown(
    f\"\"\"{explanation}\"\"\",
    sizing_mode='stretch_width',
    styles={{'padding': '10px', 'background': '#f8f9fa', 'border-radius': '5px'}}
)

data_view = pn.widgets.Tabulator(
    df,
    pagination='remote',
    page_size=10,
    sizing_mode='stretch_width',
    theme='bootstrap',
)

# --- Dashboard Template ---
template = pn.template.FastListTemplate(
    title='AI-Parrot Dashboard',
    sidebar=[
        pn.pane.Markdown("## 📊 Data Summary"),
        pn.indicators.Number(name='Total Rows', value=df.shape[0] if not df.empty else 0, format='{{value}}'),
        pn.indicators.Number(name='Total Columns', value=df.shape[1] if not df.empty else 0, format='{{value}}'),
        pn.layout.Divider(),
        pn.pane.Markdown("### Columns"),
        pn.pane.DataFrame(pd.DataFrame(df.columns, columns=['Name']), height=300, sizing_mode='stretch_width') if not df.empty else ""
    ],
    main=[
        pn.Row(title),
        pn.Row(
            pn.Column("### 📝 Analysis", explanation_pane, sizing_mode='stretch_width'),
            pn.Column("### 📈 Visualization", viz_pane, sizing_mode='stretch_width')
        ),
        pn.Row("### 🗃️ Source Data", data_view)
    ],
    accent_base_color="#2E86C1",
    header_background="#2E86C1",
)

if __name__.startswith("bokeh"):
    template.servable()
"""
