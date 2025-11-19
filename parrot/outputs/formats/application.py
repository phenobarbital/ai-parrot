from typing import Any, Optional, Tuple, Dict, Type
import json
import pandas as pd
from .base import BaseRenderer
from . import register_renderer
from ...models.outputs import OutputMode
from .generators.abstract import AbstractAppGenerator
from .generators.streamlit import StreamlitGenerator
from .generators.panel import PanelGenerator
from .generators.terminal import TerminalGenerator


# Define available generators mapping
GENERATORS: Dict[str, Type[AbstractAppGenerator]] = {
    'streamlit': StreamlitGenerator,
    'panel': PanelGenerator,
    'terminal': TerminalGenerator,
}


OUTPUT_APPLICATION_PROMPT = """
**APPLICATION GENERATION MODE**

**Objective:**
Transform the user's query and the agent's analysis into a fully functional, standalone application (Streamlit, Panel, or Terminal Dashboard).

**INSTRUCTIONS:**
1.  **Analyze & Compute:**
    - Use the provided Python tools to query the dataframes (`df1`, `df2`, etc.).
    - Ensure all data processing happens within the tool execution.

2.  **Visualize (Code Generation):**
    - If the user asks for charts, maps, or visual insights, generate the Python code to create them.
    - **Crucial:** The code MUST be self-contained (using `df` as the variable name for the data).
    - Support libraries: `plotly`, `altair`, `matplotlib`, `bokeh`.

3.  **Structured Response:**
    - Return the response strictly following the `PandasAgentResponse` schema.
    - `explanation`: A clear, formatted text summary of findings.
    - `data`: The relevant subset of data (rows/columns) to display in the app.
    - `code`: The specific Python code block that generates the visualizations.

**Example Code Snippet (for 'code' field):**
```python
import plotly.express as px
# Assume 'df' is already loaded in the app context
fig = px.bar(df, x='Category', y='Sales', title='Sales Performance')
st.plotly_chart(fig) # For Streamlit
# or
fig.show() # For generic
"""


@register_renderer(OutputMode.APPLICATION, system_prompt=OUTPUT_APPLICATION_PROMPT)
class ApplicationRenderer(BaseRenderer):
    """
    Renderer that wraps the Agent Response into a standalone Application.
    Supports: Streamlit, Panel.
    """
    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        app_type: str = 'streamlit',
        **kwargs,
    ) -> Tuple[Any, Any]:
        """
        Render response using the requested Application Generator.
        """
        # 1. Select Generator Class
        output_format = kwargs.get('output_format', environment)
        # If environment is terminal and no specific app_type requested, default to terminal app
        if output_format == 'terminal':
            generator_cls = TerminalGenerator
        else:
            generator_cls = GENERATORS.get(app_type.lower(), StreamlitGenerator)

        # 2. Instantiate and Generate
        generator = generator_cls(response)
        output = generator.generate()

        # 3. Wrap Output
        # For TerminalApp, the output IS the renderable object
        if isinstance(generator, TerminalGenerator):
            return "", output

        # For Code Generators (Streamlit/Panel)
        wrapped = self._wrap_code_instruction(output, app_type, environment)

        return output, wrapped

    def _wrap_code_instruction(self, code: str, app_type: str, environment: str) -> Any:
        """Wraps the generated code with run instructions."""
        filename = f"app_{app_type}.py"
        cmd = f"streamlit run {filename}" if app_type == 'streamlit' else f"panel serve {filename}"

        if environment == 'terminal':
            try:
                from rich.panel import Panel
                from rich.syntax import Syntax
                from rich.console import Group
                from rich.markdown import Markdown

                return Panel(
                    Group(
                        Markdown(f"**To run this {app_type.title()} app:**\n1. Save to `{filename}`\n2. Run `{cmd}`"),
                        Syntax(code, "python", theme="monokai")
                    ),
                    title=f"🚀 {app_type.title()} App Generated",
                    border_style="green"
                )
            except ImportError:
                return f"Save to {filename} and run: {cmd}\n\n{code}"

        elif environment in {'jupyter', 'notebook', 'colab'}:
            from ipywidgets import HTML, VBox, Textarea, Layout
            return VBox([
                HTML(f"<b>{app_type.title()} App Generated.</b> Save code below and run: <code>{cmd}</code>"),
                Textarea(value=code, layout=Layout(width='100%', height='300px'))
            ])

        return code
