from typing import Any, Optional, Tuple, List, Dict, Union
import json
import pandas as pd
from .base import BaseRenderer
from . import register_renderer
from ...models.outputs import OutputMode

try:
    from rich.table import Table as RichTable
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from ipywidgets import HTML as IPyHTML
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False


GRIDJS_SYSTEM_PROMPT = """
**GRID.JS CODE GENERATION MODE**

**Objective:** Generate a single, valid Grid.js Javascript code block.

**INSTRUCTIONS:**
1.  **Analyze Request:** Understand the user's goal for the table.
2.  **Generate Grid.js Code:** Create a complete Grid.js or ag-grid configuration.
3.  **Use Sample Data:** If the user asks for a type of table but doesn't provide data, generate appropriate sample data to illustrate the table's structure.
4.  **Output:** Return ONLY the Javascript code inside a ```javascript code block. Do not add explanations.

**BASIC STRUCTURE EXAMPLE:**

* If the user requests a gridjs table, respond with code similar to the following:
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

* if the user requests a ag-grid table, respond with code similar to the following:
```javascript
const columnDefs = [
    { headerName: "Make", field: "make" },
    { headerName: "Model", field: "model" },
    { headerName: "Price", field: "price" }
];
const rowData = [
    { make: "Toyota", model: "Celica", price: 35000 },
    { make: "Ford", model: "Mondeo", price: 32000 },
    { make: "Porsche", model: "Boxster", price: 72000 }
];
const gridOptions = {
    columnDefs: columnDefs,
    rowData: rowData
};
new agGrid.Grid(document.getElementById('myGrid'), gridOptions);
```
"""

@register_renderer(OutputMode.TABLE, system_prompt=GRIDJS_SYSTEM_PROMPT)
class TableRenderer(BaseRenderer):
    """
    Renderer for Tables supporting Rich (Terminal), HTML (Simple), Grid.js, and Ag-Grid.
    """

    def _extract_data(self, response: Any) -> pd.DataFrame:
        """Extract data into a Pandas DataFrame."""
        # 1. Handle PandasAgentResponse
        output = getattr(response, 'output', None)

        if output is not None:
            if hasattr(output, 'to_dataframe'):
                return output.to_dataframe()
            if hasattr(output, 'data') and output.data is not None:
                return pd.DataFrame(output.data)

        # 2. Handle direct DataFrame
        if isinstance(output, pd.DataFrame):
            return output

        # 3. Handle list of dicts
        if isinstance(output, list):
            return pd.DataFrame(output)

        # 4. Handle dict (single record or dict of lists)
        if isinstance(output, dict):
            return pd.DataFrame(output) if all(isinstance(v, list) for v in output.values()) else pd.DataFrame([output])

        # 5. Fallback: Check response.data attribute directly (AIMessage)
        if hasattr(response, 'data') and response.data is not None:
            if isinstance(response.data, pd.DataFrame):
                return response.data
            return pd.DataFrame(response.data)

        return pd.DataFrame()

    def _render_rich_table(self, df: pd.DataFrame, title: str) -> Any:
        """Render a Rich Table object."""
        if not RICH_AVAILABLE:
            return df.to_string()

        table = RichTable(title=title, show_header=True, header_style="bold magenta")

        # Add columns
        for column in df.columns:
            table.add_column(str(column), overflow="fold")

        # Add rows
        for _, row in df.iterrows():
            table.add_row(*[str(item) for item in row])

        return table

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

    def _generate_gridjs_code(self, df: pd.DataFrame, element_id: str = "wrapper") -> str:
        """Generate Grid.js configuration and render code."""
        columns = df.columns.tolist()
        # Convert data to JSON-serializable list of lists
        data = df.values.tolist()

        # Serialize safely to avoid JS syntax errors
        json_data = json.dumps(data)
        json_columns = json.dumps(columns)

        return f"""
            new gridjs.Grid({{
                columns: {json_columns},
                data: {json_data},
                search: true,
                sort: true,
                pagination: {{
                    limit: 10
                }},
                className: {{
                    table: 'table-body'
                }}
            }}).render(document.getElementById("{element_id}"));
        """

    def _generate_aggrid_code(self, df: pd.DataFrame, element_id: str = "wrapper") -> str:
        """Generate Ag-Grid configuration and render code."""
        # Define columns definition
        column_defs = [{"headerName": col, "field": col, "sortable": True, "filter": True} for col in df.columns]

        # Data is list of dicts for Ag-Grid
        row_data = df.to_dict(orient='records')

        json_col_defs = json.dumps(column_defs)
        json_row_data = json.dumps(row_data)

        return f"""
            const gridOptions = {{
                columnDefs: {json_col_defs},
                rowData: {json_row_data},
                pagination: true,
                paginationPageSize: 10,
                defaultColDef: {{
                    flex: 1,
                    minWidth: 100,
                    resizable: true,
                }}
            }};
            const gridDiv = document.getElementById("{element_id}");
            new agGrid.Grid(gridDiv, gridOptions);
        """

    def _build_html_document(
        self,
        table_content: str,
        table_mode: str,
        title: str = "Table",
        html_mode: str = "partial",
        element_id: str = "wrapper"
    ) -> str:
        """
        Build the final HTML output (partial or complete).

        Args:
            table_content: The HTML table or JS code.
            table_mode: 'simple', 'grid', or 'ag-grid'.
            html_mode: 'partial' (embeddable) or 'complete' (standalone).
        """
        head_content = ""
        body_content = ""

        # 1. Configuration based on mode
        if table_mode == 'grid':
            # Grid.js CDNs
            head_content = """
                <link href="https://unpkg.com/gridjs/dist/theme/mermaid.min.css" rel="stylesheet" />
                <script src="https://unpkg.com/gridjs/dist/gridjs.umd.js"></script>
            """
            body_content = f"""
                <div id="{element_id}"></div>
                <script>
                    {table_content}
                </script>
            """

        elif table_mode == 'ag-grid':
            # Ag-Grid CDNs
            head_content = """
                <script src="https://cdn.jsdelivr.net/npm/ag-grid-community/dist/ag-grid-community.min.js"></script>
            """
            # Note: Ag-Grid requires a height on the container
            body_content = f"""
                <div id="{element_id}" class="ag-theme-alpine" style="height: 500px; width: 100%;"></div>
                <script>
                    {table_content}
                </script>
            """

        else: # simple
            # Basic Bootstrap for simple tables
            head_content = """
                <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css">
                <style>
                    .dataframe { width: 100%; }
                    .dataframe td, .dataframe th { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
                </style>
            """
            body_content = f'<div class="table-responsive">{table_content}</div>'

        # 2. Return Partial (Embeddable)
        if html_mode == "partial":
            return f"""
            <div>
                {head_content}
                {body_content}
            </div>
            """

        # 3. Return Complete (Standalone)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {head_content}
</head>
<body>
    <div class="container mt-4">
        <h2>{title}</h2>
        {body_content}
    </div>
</body>
</html>"""

    async def render(
        self,
        response: Any,
        table_mode: str = 'simple', # simple, grid, ag-grid
        title: str = 'Table',
        environment: str = 'terminal',
        html_mode: str = 'partial',
        **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        """
        Render table in the appropriate format.

        Returns:
            Tuple[Any, Optional[Any]]: (raw_data_df, rendered_output)
        """
        # 1. Extract Data
        df = self._extract_data(response)

        if df.empty:
            return "No Data Available", None

        # 2. Environment: Terminal -> Rich Table
        if environment == 'terminal':
            rich_table = self._render_rich_table(df, title)
            return df, rich_table

        # 3. Prepare Content for HTML/JS
        content = ""
        if table_mode == 'simple':
            # Convert to HTML Table
            content = df.to_html(classes="table table-striped table-bordered", index=False)

        elif table_mode == 'grid':
            # Generate Grid.js Code
            # Check if code was pre-generated by LLM (in response.code) - Future proofing
            if hasattr(response, 'code') and isinstance(response.code, str) and "new gridjs.Grid" in response.code:
                content = response.code
            else:
                content = self._generate_gridjs_code(df, "wrapper_grid")

        elif table_mode == 'ag-grid':
            # Generate Ag-Grid Code
            if hasattr(response, 'code') and isinstance(response.code, str) and "new agGrid.Grid" in response.code:
                content = response.code
            else:
                content = self._generate_aggrid_code(df, "wrapper_ag")

        # 4. Build Wrapped HTML
        wrapper_id = f"wrapper_{table_mode}" if table_mode != 'simple' else "wrapper"
        wrapped_html = self._build_html_document(
            content,
            table_mode,
            title=title,
            html_mode=html_mode,
            element_id=wrapper_id
        )

        # 5. Environment: Jupyter -> Widget
        if environment in {'jupyter', 'notebook', 'colab'}:
            if IPYWIDGETS_AVAILABLE:
                return df, IPyHTML(value=wrapped_html)
            return df, wrapped_html

        # 6. Environment: HTML (return string)
        return df, wrapped_html
