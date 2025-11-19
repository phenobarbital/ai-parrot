from typing import Any, Optional, Tuple, Dict
import json
import pandas as pd
from .base import BaseRenderer
from . import register_renderer
from ...models.outputs import OutputMode


OUTPUT_APPLICATION_PROMPT = """
APPLICATION OUTPUT MODE:
Wrap the agent's response into a standalone application using Streamlit or Panel.
"""


@register_renderer(OutputMode.APPLICATION, system_prompt=OUTPUT_APPLICATION_PROMPT)
class ApplicationRenderer(BaseRenderer):
    """
    Renderer that wraps the Agent Response into a standalone Application.
    Supports: Streamlit, Panel.
    """

    def _extract_payload(self, response: Any) -> Dict[str, Any]:
        """Extract all necessary components for the app."""
        payload = {
            "input": getattr(response, "input", "No query provided"),
            "explanation": "",
            "data": None,
            "code": None
        }

        # Extract Output/Explanation
        output = getattr(response, "output", "")
        if hasattr(output, "explanation"):
            payload["explanation"] = output.explanation
        elif hasattr(output, "response"):
            payload["explanation"] = output.response
        elif isinstance(output, str):
            payload["explanation"] = output

        # Extract Data
        if hasattr(output, "to_dataframe"):
            payload["data"] = output.to_dataframe()
        elif hasattr(output, "data") and output.data is not None:
            payload["data"] = pd.DataFrame(output.data)
        elif hasattr(response, "data") and response.data is not None:
            if isinstance(response.data, pd.DataFrame):
                payload["data"] = response.data
            else:
                payload["data"] = pd.DataFrame(response.data)

        # Extract Code
        if hasattr(output, "code") and output.code:
            payload["code"] = output.code
        elif hasattr(response, "code") and response.code:
            payload["code"] = response.code

        return payload

    def _generate_streamlit_app(self, payload: Dict[str, Any]) -> str:
        """Generates a standalone Streamlit application script."""

        # Serialize data to embed directly in the script
        data_str = "[]"
        if payload["data"] is not None and not payload["data"].empty:
            data_str = payload["data"].to_json(orient="records")

        # Sanitize inputs for f-string
        explanation = payload["explanation"].replace('"""', "\\\"\\\"\\\"")
        query = payload["input"].replace('"', '\\"')
        code_snippet = payload["code"]

        code_section = ""
        if code_snippet:
            # If code is JSON (e.g. Vega-Lite), render it
            if isinstance(code_snippet, (dict, list)):
                 code_section = f"""
    st.subheader("📊 Generated Visualization")
    st.json({json.dumps(code_snippet)})
    try:
        st.vega_lite_chart(data=df, spec={json.dumps(code_snippet)}, use_container_width=True)
    except Exception as e:
        st.error(f"Could not render chart: {{e}}")
                 """
            # If code is Python string
            elif isinstance(code_snippet, str):
                code_section = f"""
    with st.expander("See Analysis Code"):
        st.code('''{code_snippet}''', language='python')
                """

        return f"""
import streamlit as st
import pandas as pd
import json
import altair as alt
import plotly.express as px

# --- Page Configuration ---
st.set_page_config(page_title="Agent Analysis", page_icon="🤖", layout="wide")

# --- Data Loading (Embedded) ---
@st.cache_data
def load_data():
    raw_json = '{data_str}'
    try:
        data = json.loads(raw_json)
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

df = load_data()

# --- Header ---
st.title("🤖 AI Agent Analysis Report")
st.markdown(f"**Query:** *{query}*")
st.divider()

# --- Main Content Layout ---
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("📝 Analysis & Explanation")
    st.markdown(\"\"\"{explanation}\"\"\")

with col2:
    st.subheader("🔢 Data Summary")
    if not df.empty:
        st.metric("Rows", df.shape[0])
        st.metric("Columns", df.shape[1])
        st.dataframe(df.describe().T, height=300)
    else:
        st.info("No structured data generated.")

# --- Detailed Data View ---
st.divider()
st.subheader("🗃️ Source Data")
if not df.empty:
    st.dataframe(df, use_container_width=True)

    # Auto-Visualization for exploration
    st.subheader("📈 Quick Visualizer")

    chart_type = st.selectbox("Choose Chart Type", ["Bar", "Line", "Scatter", "Area"])
    num_cols = df.select_dtypes(include=['number']).columns.tolist()
    cat_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()

    if num_cols:
        x_axis = st.selectbox("X Axis", df.columns, index=0)
        y_axis = st.selectbox("Y Axis", num_cols, index=0)

        if chart_type == "Bar":
            st.plotly_chart(px.bar(df, x=x_axis, y=y_axis), use_container_width=True)
        elif chart_type == "Line":
            st.plotly_chart(px.line(df, x=x_axis, y=y_axis), use_container_width=True)
        elif chart_type == "Scatter":
            st.plotly_chart(px.scatter(df, x=x_axis, y=y_axis), use_container_width=True)
        elif chart_type == "Area":
            st.plotly_chart(px.area(df, x=x_axis, y=y_axis), use_container_width=True)
    else:
        st.warning("Not enough numeric columns for auto-visualization.")

# --- Generated Code / Artifacts ---
{code_section}
"""

    def _generate_panel_app(self, payload: Dict[str, Any]) -> str:
        """Generates a standalone Panel application script."""

        data_str = "[]"
        if payload["data"] is not None and not payload["data"].empty:
            data_str = payload["data"].to_json(orient="records")

        explanation = payload["explanation"].replace('"""', "\\\"\\\"\\\"")
        query = payload["input"].replace('"', '\\"')

        return f"""
import panel as pn
import pandas as pd
import json
import hvplot.pandas

pn.extension('tabulator')

# --- Data Loading ---
raw_json = '{data_str}'
try:
    data = json.loads(raw_json)
    df = pd.DataFrame(data)
except Exception:
    df = pd.DataFrame()

# --- Components ---
title = pn.pane.Markdown(f"# 🤖 AI Agent Analysis\\n**Query:** *{query}*")
explanation = pn.pane.Markdown(\"\"\"{explanation}\"\"\")

data_view = pn.widgets.Tabulator(df, pagination='remote', page_size=10, sizing_mode='stretch_width')

# --- Dashboard Layout ---
template = pn.template.FastListTemplate(
    title='AI Analysis Report',
    sidebar=[
        pn.pane.Markdown("## Summary"),
        pn.indicators.Number(name='Rows', value=df.shape[0] if not df.empty else 0),
        pn.indicators.Number(name='Columns', value=df.shape[1] if not df.empty else 0),
    ],
    main=[
        pn.Row(title),
        pn.Row(
            pn.Column("### Analysis", explanation, sizing_mode='stretch_width'),
        ),
        pn.Row("### Data", data_view)
    ],
    accent_base_color="#88d8b0",
    header_background="#88d8b0",
)

if __name__.startswith("bokeh"):
    template.servable()
"""

    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        app_type: str = 'streamlit', # streamlit, panel
        return_code: bool = True,
        **kwargs,
    ) -> Tuple[str, Any]:
        """
        Render response as a source code string for an application.

        Returns:
            (source_code, wrapped_instruction)
        """
        # 1. Extract Payload
        payload = self._extract_payload(response)

        # 2. Generate Code
        if app_type == 'panel':
            app_code = self._generate_panel_app(payload)
            filename = "app_panel.py"
            run_cmd = "panel serve app_panel.py"
        else:
            # Default to Streamlit
            app_code = self._generate_streamlit_app(payload)
            filename = "app.py"
            run_cmd = "streamlit run app.py"

        # 3. Wrap output (Instruction card)
        if environment == 'terminal':
            try:
                from rich.panel import Panel as RichPanel
                from rich.syntax import Syntax
                from rich.console import Group
                from rich.markdown import Markdown

                code_view = Syntax(app_code, "python", theme="monokai", line_numbers=True)
                instructions = Markdown(f"""
### 🚀 Application Generated!
I have wrapped your analysis into a standalone **{app_type.title()}** application.

**To run this app:**
1. Save the code below to `{filename}`
2. Run: `{run_cmd}`
                """)

                wrapped = RichPanel(Group(instructions, code_view), title="📱 Application Generator", border_style="cyan")
            except ImportError:
                wrapped = f"Save this code to {filename} and run: {run_cmd}\n\n{app_code}"

        elif environment in {'jupyter', 'notebook', 'colab'}:
            from ipywidgets import HTML, VBox, Textarea, Layout

            html_instr = HTML(f"""
            <div style="background-color:#f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #ff4b4b;">
                <h3 style="margin:0">🚀 {app_type.title()} App Generated</h3>
                <p>Copy the code below to a file named <code>{filename}</code> and run <code>{run_cmd}</code> in your terminal.</p>
            </div>
            """)
            # Simple textarea for copy-pasting
            code_area = Textarea(value=app_code, layout=Layout(width='100%', height='300px'))
            wrapped = VBox([html_instr, code_area])

        else:
            wrapped = app_code

        return app_code, wrapped
