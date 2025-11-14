from typing import Any, Optional, Tuple
import pandas as pd
from .base import BaseRenderer
from . import register_renderer
from ...models.outputs import OutputMode


GRIDJS_SYSTEM_PROMPT = """
**GRID.JS CODE GENERATION MODE**

**Objective:** Generate a single, valid Grid.js Javascript code block.

**INSTRUCTIONS:**
1.  **Analyze Request:** Understand the user's goal for the table.
2.  **Generate Grid.js Code:** Create a complete Grid.js configuration.
3.  **Use Sample Data:** If the user asks for a type of table but doesn't provide data, generate appropriate sample data to illustrate the table's structure.
4.  **Output:** Return ONLY the Javascript code inside a ```javascript code block. Do not add explanations.

**BASIC STRUCTURE EXAMPLE:**
```javascript
new gridjs.Grid({
  columns: ["Name", "Email", "Phone Number"],
  data: [
    ["John", "john@example.com", "(353) 01 222 3333"],
    ["Mark", "mark@gmail.com", "(01) 22 888 4444"],
    ["Eoin", "eoin@gmail.com", "0097 22 654 00033"],
    ["Sarah", "sarahcdd@gmail.com", "+322 876 1233"],
    ["Afshin", "afshin@mail.com", "(353) 22 87 8356"]
  ]
}).render(document.getElementById("wrapper"));
```
"""

@register_renderer(OutputMode.TABLE, system_prompt=GRIDJS_SYSTEM_PROMPT)
class TableRenderer(BaseRenderer):
    """Renderer for HTML tables and Grid.js tables."""

    def _render_simple_table(self, data: Any) -> str:
        if isinstance(data, pd.DataFrame):
            return data.to_html(index=False)
        elif isinstance(data, list) and all(isinstance(i, dict) for i in data):
            df = pd.DataFrame(data)
            return df.to_html(index=False)
        elif isinstance(data, str):
            return data
        else:
            raise TypeError(f"Unsupported data type for simple table: {type(data)}")

    def _render_gridjs_table(self, data: Any) -> str:
        if isinstance(data, pd.DataFrame):
            columns = data.columns.tolist()
            table_data = data.values.tolist()
            return f"""
                new gridjs.Grid({{
                    columns: {columns},
                    data: {table_data}
                }}).render(document.getElementById("wrapper"));
            """
        elif isinstance(data, str):
            return data
        else:
            raise TypeError(f"Unsupported data type for Grid.js table: {type(data)}")

    def _build_html_document(
        self,
        table_content: str,
        table_mode: str,
        title: str = "Table",
        html_mode: str = "partial",
        ) -> str:
        extra_head = ""
        if table_mode == "grid":
            extra_head = """
                <link href="https://unpkg.com/gridjs/dist/theme/mermaid.min.css" rel="stylesheet" />
                <script src="https://unpkg.com/gridjs/dist/gridjs.umd.js"></script>
            """
        if html_mode == "partial":
            # return table content with adding extra head for dependencies:
            return f'''
            <span>{extra_head}</span>
            <div id="wrapper">{table_content if table_mode == 'simple' else ''}</div>
            <script>
                {table_content if table_mode == 'grid' else ''}
            </script>
            '''
        # complete HTML document
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {extra_head}
</head>
<body>
    <div id="wrapper">{table_content if table_mode == 'simple' else ''}</div>
    <script>
        {table_content if table_mode == 'grid' else ''}
    </script>
</body>
</html>'''

    async def render(
        self,
        response: Any,
        table_mode: str = 'simple',
        title: str = 'Table',
        theme: str = 'monokai',
        environment: str = 'terminal',
        html_mode: str = 'partial',
        **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        """Render table in the appropriate format."""
        content = self._get_content(response)

        # evaluate if content is html code block


        if table_mode == 'simple':
            table_content = self._render_simple_table(content)
        elif table_mode == 'grid':
            table_content = self._render_gridjs_table(content)
        else:
            raise ValueError(f"Invalid table mode: {table_mode}")

        if environment in {'terminal', 'console', 'jupyter', 'notebook', 'ipython', 'colab'}:
            # For Jupyter, return the figure object directly
            # The frontend will handle rendering it
            return content, table_content

        wrapped_html = self._build_html_document(
            table_content,
            table_mode,
            html_mode=html_mode,
            title=title
        )

        return table_content, wrapped_html
