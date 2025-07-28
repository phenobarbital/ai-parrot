"""
DataFrame to HTML Tool - Convert pandas DataFrames to styled HTML tables.
"""
from typing import Any, Dict, Optional
from pathlib import Path
import pandas as pd
from pydantic import BaseModel, Field
from .abstract import AbstractTool


class DfToHtmlArgs(BaseModel):
    """Arguments schema for DataFrame to HTML conversion."""

    dataframe: Any = Field(
        description="Pandas DataFrame to convert to HTML"
    )
    filename: Optional[str] = Field(
        default=None,
        description="Optional filename to save the HTML file (without extension)"
    )
    table_id: Optional[str] = Field(
        default=None,
        description="Optional HTML table ID attribute"
    )
    css_classes: str = Field(
        default="dataframe table table-striped table-hover",
        description="CSS classes to apply to the table"
    )
    include_index: bool = Field(
        default=True,
        description="Whether to include the DataFrame index in the HTML"
    )
    escape: bool = Field(
        default=False,
        description="Whether to escape HTML characters in the data"
    )
    max_rows: Optional[int] = Field(
        default=None,
        description="Maximum number of rows to display (None for all rows)"
    )
    max_cols: Optional[int] = Field(
        default=None,
        description="Maximum number of columns to display (None for all columns)"
    )
    table_attributes: Optional[str] = Field(
        default=None,
        description="Additional HTML table attributes as string"
    )
    include_bootstrap: bool = Field(
        default=True,
        description="Whether to include Bootstrap CSS for styling"
    )
    custom_css: Optional[str] = Field(
        default=None,
        description="Custom CSS styles to include"
    )


class DfToHtmlTool(AbstractTool):
    """
    Tool for converting pandas DataFrames to styled HTML tables.

    This tool takes a pandas DataFrame and converts it to a well-formatted HTML table
    with optional CSS styling, Bootstrap integration, and file saving capabilities.
    """

    name: str = "df_to_html"
    description: str = "Convert pandas DataFrame to styled HTML table with optional file saving"
    args_schema = DfToHtmlArgs
    return_direct: bool = False

    def _default_output_dir(self) -> Optional[Path]:
        """Default output directory for HTML files."""
        return self.static_dir / "tables" if self.static_dir else None

    def _get_default_css(self) -> str:
        """Get default CSS styles for the DataFrame table."""
        return """
        <style>
        .dataframe {
            border-collapse: collapse;
            margin: 25px 0;
            font-size: 0.9em;
            font-family: sans-serif;
            min-width: 400px;
            border-radius: 5px 5px 0 0;
            overflow: hidden;
            box-shadow: 0 0 20px rgba(0, 0, 0, 0.15);
        }
        .dataframe thead tr {
            background-color: #009879;
            color: #ffffff;
            text-align: left;
        }
        .dataframe th,
        .dataframe td {
            padding: 12px 15px;
            border: 1px solid #dddddd;
        }
        .dataframe tbody tr {
            border-bottom: 1px solid #dddddd;
        }
        .dataframe tbody tr:nth-of-type(even) {
            background-color: #f3f3f3;
        }
        .dataframe tbody tr:hover {
            background-color: #f1f1f1;
        }
        .dataframe tbody tr:last-of-type {
            border-bottom: 2px solid #009879;
        }
        .dataframe-container {
            overflow-x: auto;
            margin: 20px 0;
        }
        </style>
        """

    def _get_bootstrap_css(self) -> str:
        """Get Bootstrap CSS CDN link."""
        return """
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        """

    def _create_html_wrapper(
        self,
        table_html: str,
        title: str = "DataFrame Table",
        include_bootstrap: bool = True,
        custom_css: Optional[str] = None
    ) -> str:
        """Create a complete HTML document wrapper around the table."""

        css_links = ""
        if include_bootstrap:
            css_links += self._get_bootstrap_css()

        default_css = self._get_default_css()
        custom_styles = f"<style>{custom_css}</style>" if custom_css else ""

        html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {css_links}
    {default_css}
    {custom_styles}
</head>
<body>
    <div class="container-fluid mt-4">
        <div class="row">
            <div class="col-12">
                <h2 class="mb-3">{title}</h2>
                <div class="dataframe-container">
                    {table_html}
                </div>
            </div>
        </div>
    </div>
</body>
</html>
        """
        return html_template.strip()

    async def _execute(
        self,
        dataframe: pd.DataFrame,
        filename: Optional[str] = None,
        table_id: Optional[str] = None,
        css_classes: str = "dataframe table table-striped table-hover",
        include_index: bool = True,
        escape: bool = False,
        max_rows: Optional[int] = None,
        max_cols: Optional[int] = None,
        table_attributes: Optional[str] = None,
        include_bootstrap: bool = True,
        custom_css: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute the DataFrame to HTML conversion.

        Returns:
            Dictionary containing the HTML string and optional file path
        """

        # Validate that we have a DataFrame
        if not isinstance(dataframe, pd.DataFrame):
            raise ValueError("Input must be a pandas DataFrame")

        if dataframe.empty:
            self.logger.warning("DataFrame is empty")

        # Apply row/column limits if specified
        df_to_convert = dataframe.copy()
        if max_rows is not None:
            df_to_convert = df_to_convert.head(max_rows)
        if max_cols is not None:
            df_to_convert = df_to_convert.iloc[:, :max_cols]

        # Build table attributes
        table_attrs = f'class="{css_classes}"'
        if table_id:
            table_attrs += f' id="{table_id}"'
        if table_attributes:
            table_attrs += f' {table_attributes}'

        # Convert DataFrame to HTML using pandas styler for better control
        try:
            # Use pandas styler for more advanced styling options
            styler = df_to_convert.style

            # Set table attributes
            styler = styler.set_table_attributes(table_attrs)

            # Convert to HTML
            table_html = styler.to_html(
                escape=escape,
                table_uuid=table_id
            )

        except Exception as e:
            self.logger.warning(f"Styler approach failed: {e}, falling back to basic to_html")
            # Fallback to basic to_html method
            table_html = df_to_convert.to_html(
                classes=css_classes,
                table_id=table_id,
                index=include_index,
                escape=escape
            )

        # Create complete HTML document
        title = f"DataFrame Table - {filename}" if filename else "DataFrame Table"
        complete_html = self._create_html_wrapper(
            table_html=table_html,
            title=title,
            include_bootstrap=include_bootstrap,
            custom_css=custom_css
        )

        result = {
            "html": complete_html,
            "table_html": table_html,  # Just the table part
            "rows": len(df_to_convert),
            "columns": len(df_to_convert.columns),
            "shape": df_to_convert.shape
        }

        # Save to file if filename is provided
        if filename:
            if not filename.endswith('.html'):
                filename = f"{filename}.html"

            # Ensure output directory exists
            if self.output_dir:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                file_path = self.output_dir / filename
            else:
                file_path = Path(filename)

            # Write HTML to file
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(complete_html)

                self.logger.info(f"HTML table saved to: {file_path}")

                # Add file information to result
                result.update({
                    "file_path": str(file_path),
                    "file_url": self.to_static_url(file_path),
                    "file_size": file_path.stat().st_size
                })

            except Exception as e:
                self.logger.error(f"Failed to save HTML file: {e}")
                result["save_error"] = str(e)

        return result
