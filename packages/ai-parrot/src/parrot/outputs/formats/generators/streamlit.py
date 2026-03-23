import json
from .abstract import AbstractAppGenerator

class StreamlitGenerator(AbstractAppGenerator):
    """Generates a single-file Streamlit application."""

    def generate(self) -> str:
        # Serialize data for embedding
        data_str = "[]"
        if not self.payload["data"].empty:
            data_str = self.payload["data"].to_json(orient="records")

        # Sanitize strings
        explanation = self.payload["explanation"].replace('"""', "\\\"\\\"\\\"")
        query = self.payload["input"].replace('"', '\\"')
        # Dynamic Code Injection
        code_section = ""
        if code_snippet := self.payload["code"]:
            if isinstance(code_snippet, (dict, list)):
                # JSON Chart (Vega/Altair)
                code_section = f"""
st.subheader("📊 Generated Visualization")
spec = {json.dumps(code_snippet)}
st.vega_lite_chart(data=df, spec=spec, use_container_width=True)
                """
            elif isinstance(code_snippet, str):
                # Python Code
                # We wrap it to ensure it uses the local 'df' and 'st' context
                code_section = f"""
    st.subheader("📊 Analysis Visualization")
    with st.container():
        # Injected Code Execution
        try:
            {self._indent_code(code_snippet)}
        except Exception as e:
            st.error(f"Error rendering visualization: {{e}}")
            st.code('''{code_snippet}''', language='python')
                """

        return f"""
import streamlit as st
import pandas as pd
import json
import altair as alt
import plotly.express as px
import matplotlib.pyplot as plt

st.set_page_config(page_title="Agent Analysis", layout="wide")

@st.cache_data
def load_data():
    try:
        return pd.DataFrame(json.loads('{data_str}'))
    except:
        return pd.DataFrame()

df = load_data()

st.title("🤖 Analysis Report")
st.markdown(f"**Query:** {query}")
st.divider()

col1, col2 = st.columns([2, 1])
with col1:
    st.subheader("📝 Findings")
    st.markdown(\"\"\"{explanation}\"\"\")

with col2:
    st.subheader("🔢 Data Stats")
    if not df.empty:
        st.dataframe(df.describe().T, height=300)
    else:
        st.info("No data available")

st.divider()
if not df.empty:
    with st.expander("🗃️ Source Data", expanded=True):
        st.dataframe(df, use_container_width=True)

{code_section}
"""

    def _indent_code(self, code: str, spaces: int = 8) -> str:
        """Helper to indent injected code correctly."""
        indentation = " " * spaces
        return "\n".join(f"{indentation}{line}" for line in code.splitlines())
