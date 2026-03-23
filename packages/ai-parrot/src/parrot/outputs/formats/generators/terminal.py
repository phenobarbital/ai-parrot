from typing import Any
import json
try:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.table import Table
    from rich.layout import Layout
    from rich.syntax import Syntax
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
from .abstract import AbstractAppGenerator


class TerminalGenerator(AbstractAppGenerator):
    """Generates a Rich Console Dashboard."""

    def generate(self) -> Any:
        if not RICH_AVAILABLE:
            return f"Query: {self.payload['input']}\n\n{self.payload['explanation']}"

        # 1. Header
        header = Panel(
            f"[bold blue]Query:[/bold blue] {self.payload['input']}",
            title="🤖 AI Agent Analysis",
            border_style="green"
        )

        # 2. Explanation (Markdown)
        explanation = Panel(
            Markdown(self.payload["explanation"]),
            title="📝 Analysis",
            border_style="blue"
        )

        # 3. Data Table
        df = self.payload["data"]
        if not df.empty:
            table = Table(show_header=True, header_style="bold magenta")
            # Limit to first 5 columns and 10 rows for terminal readability
            show_cols = df.columns[:5]
            for col in show_cols:
                table.add_column(str(col))

            for _, row in df.head(10).iterrows():
                table.add_row(*[str(item) for item in row])

            data_panel = Panel(table, title=f"🔢 Data Preview ({len(df)} rows)", border_style="yellow")
        else:
            data_panel = Panel("No structured data returned.", title="🔢 Data", border_style="yellow")

        # 4. Code View
        if code_content := self.payload["code"]:
            if isinstance(code_content, (dict, list)):
                syntax = Syntax(json.dumps(code_content, indent=2), "json", theme="monokai")
            else:
                syntax = Syntax(code_content, "python", theme="monokai", line_numbers=True)

            code_panel = Panel(syntax, title="📊 Generated Code", border_style="cyan")
            return Group(header, explanation, data_panel, code_panel)

        return Group(header, explanation, data_panel)
