"""
Card Renderer for AI-Parrot
Displays metrics in HTML card format with comparisons (vs last month, vs last year, etc.)
"""
from typing import Any, Optional, Tuple, Dict, List
import re
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


CARD_SYSTEM_PROMPT = """CARD METRIC OUTPUT MODE - CRITICAL INSTRUCTIONS:

Generate an HTML card displaying key metrics with comparisons.

**CRITICAL RULES:**
1. The "explanation" can contain your analysis text
2. Format the "value" field appropriately (e.g., "$29.58K", "20.94 minutes", "1,234 users")
3. Include at least one comparison if historical data is available
  - Comparison vs Previous Month (if data available)
  - Comparison vs Previous Year (if data available)
4. Use "increase" or "decrease" for trend direction
5. Choose an appropriate icon: money, dollar, chart, percent, users, growth, target, star, trophy

Example: If calculating average for May 2025:
- Calculate May 2025 average
- Calculate April 2025 average (previous month)
- Calculate May 2024 average (previous year)
- Calculate percentage changes
- Include ALL in your data table

Your data table MUST have these rows:
| Metric | Value | Change | Trend |
| Current Period | [value] [unit] | - | - |
| vs Previous Month | [value] [unit] | +X.X% | increase/decrease |
| vs Previous Year | [value] [unit] | +X.X% | increase/decrease |

If previous data is not available, only include the current value row.
"""


@register_renderer(OutputMode.CARD, system_prompt=CARD_SYSTEM_PROMPT)
class CardRenderer(BaseRenderer):
    """
    Renderer for metric cards with comparison data.
    Extends BaseRenderer to display metrics in styled HTML cards.
    """

    CARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        .ap-card-wrapper {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            box-sizing: border-box;
        }}
        .ap-card-wrapper * {{
            box-sizing: border-box;
        }}
        .ap-card-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 24px;
            max-width: 1200px;
            width: 100%;
            justify-content: center;
        }}
        .ap-metric-card {{
            background: white;
            border-radius: 16px;
            padding: 28px 32px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
            min-width: 280px;
            max-width: 400px;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }}
        .ap-metric-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 15px 50px rgba(0, 0, 0, 0.2);
        }}
        .ap-card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}
        .ap-card-title {{
            font-size: 15px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .ap-card-icon {{
            width: 48px;
            height: 48px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 12px;
            color: white;
        }}
        .ap-card-value {{
            font-size: 42px;
            font-weight: 700;
            color: #1e293b;
            margin-bottom: 20px;
            line-height: 1;
        }}
        .ap-comparisons {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .ap-comparison-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-top: 1px solid #f1f5f9;
        }}
        .ap-comparison-item:first-child {{
            border-top: none;
            padding-top: 0;
        }}
        .ap-comparison-period {{
            font-size: 14px;
            color: #64748b;
            font-weight: 500;
        }}
        .ap-comparison-value {{
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 16px;
            font-weight: 700;
        }}
        .ap-comparison-value.increase {{ color: #10b981; }}
        .ap-comparison-value.decrease {{ color: #ef4444; }}
        .ap-trend-icon {{ font-size: 14px; }}
    </style>
</head>
<body>
    <div class="ap-card-wrapper">
        <div class="ap-card-container">
            {cards_html}
        </div>
    </div>
</body>
</html>
"""

    SINGLE_CARD_TEMPLATE = """
        <div class="ap-metric-card">
            <div class="ap-card-header">
                <div class="ap-card-title">{title}</div>
                {icon_html}
            </div>
            <div class="ap-card-value">{value}</div>
            <div class="ap-comparisons">
                {comparisons_html}
            </div>
        </div>
"""

    COMPARISON_ITEM_TEMPLATE = """
                <div class="ap-comparison-item">
                    <span class="ap-comparison-period">{period}</span>
                    <div class="ap-comparison-value {trend}">
                        <span class="ap-trend-icon">{trend_icon}</span>
                        <span>{value}%</span>
                    </div>
                </div>
"""

    ICON_MAP = {
        'money': '💰', 'dollar': '💵', 'chart': '📊', 'percent': '%',
        'users': '👥', 'growth': '📈', 'target': '🎯', 'time': '⏱️',
        'default': '📊'
    }

    def _extract_data(self, response: Any) -> Dict:
        """Extract card data from AIMessage response"""
        # Get the PandasAgentResponse from response.output or response.structured_output
        output = None
        if hasattr(response, 'output'):
            output = response.output
        elif hasattr(response, 'structured_output'):
            output = response.structured_output
        else:
            output = response

        # Extract explanation and data
        explanation = ""
        data_table = None

        if hasattr(output, 'explanation'):
            explanation = output.explanation

        if hasattr(output, 'data'):
            data_table = output.data

        # Parse the explanation to extract metric info
        card_data = self._parse_explanation_and_data(explanation, data_table)

        return card_data

    def _parse_explanation_and_data(self, explanation: str, data_table: Any) -> Dict:
        """Parse explanation and data table to extract card information"""
        # Extract main value from explanation
        title = "Metric"
        value = "N/A"
        icon = "chart"
        comparisons = []

        # Try to extract value patterns
        value_patterns = [
            (r'(\d+\.?\d*)\s*minutes?', 'time', 'Average Time'),
            (r'\$\s*(\d+[\d,]*\.?\d*[KMB]?)', 'money', 'Revenue'),
            (r'(\d+[\d,]*\.?\d*)\s*users?', 'users', 'Users'),
            (r'(\d+[\d,]*\.?\d*)%', 'percent', 'Percentage'),
            (r'(\d+[\d,]*\.?\d*)', 'chart', 'Value'),
        ]

        for pattern, icon_type, title_type in value_patterns:
            match = re.search(pattern, explanation, re.IGNORECASE)
            if match:
                value = match.group(0)
                icon = icon_type
                title = title_type
                break

        # Extract comparisons from explanation
        # Look for patterns like "5.8% increase" or "15.1% decrease"
        comparison_patterns = [
            (r'(\d+\.?\d*)%\s+(increase|growth|higher)', 'increase'),
            (r'(\d+\.?\d*)%\s+(decrease|decline|lower)', 'decrease'),
        ]

        periods = ["vs Previous Month", "vs Previous Year"]
        period_idx = 0

        for pattern, trend in comparison_patterns:
            matches = re.finditer(pattern, explanation, re.IGNORECASE)
            for match in matches:
                if period_idx < len(periods):
                    comparisons.append({
                        "period": periods[period_idx],
                        "value": float(match.group(1)),
                        "trend": trend
                    })
                    period_idx += 1

        # Also try to extract from data table if available
        if data_table and hasattr(data_table, 'rows'):
            rows = data_table.rows
            if rows and len(rows) > 0:
                # First row should be the main value
                main_row = rows[0]
                if len(main_row) >= 2:
                    # Try to get a better value from the table
                    table_value = str(main_row[1])
                    if table_value and table_value != 'Value':
                        # Check if we have units in column 2 or 3
                        if len(main_row) >= 3:
                            unit = str(main_row[2])
                            value = f"{table_value} {unit}" if unit not in ['Unit', ''] else table_value
                        else:
                            value = table_value

                # Look for comparison rows (skip first row)
                for row in rows[1:]:
                    # Handle both 3-column and 5-column tables
                    if len(row) >= 5:
                        # 5-column: metric, value, unit, change_percentage, trend
                        period_name = str(row[0])
                        change_pct = str(row[3])
                        trend_val = str(row[4]).lower()

                        # Skip if no change data
                        if change_pct in ['N/A', '', 'None']:
                            continue

                        # Clean up period name to create comparison label
                        # "April 2025 Average" -> "vs April 2025"
                        if 'vs' not in period_name.lower():
                            # Extract the month/year part
                            period_match = re.search(
                                r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',  # noqa
                                period_name,
                                re.IGNORECASE
                            )
                            if period_match:
                                period = f"vs {period_match[1]} {period_match[2]}"
                            else:
                                period = f"vs {period_name.replace(' Average', '')}"
                        else:
                            period = period_name

                        # Parse percentage
                        try:
                            percent = abs(float(change_pct))
                            trend = "decrease" if trend_val == 'decrease' or float(change_pct) < 0 else "increase"
                            comparisons.append({
                                "period": period,
                                "value": percent,
                                "trend": trend
                            })
                        except ValueError:
                            continue

                    elif len(row) >= 3:
                        # 3-column: Metric, Value, Change
                        period = str(row[0])
                        change_val = str(row[2])
                        # Extract percentage and trend
                        change_match = re.search(r'([+-]?\d+\.?\d*)%', change_val)
                        if change_match:
                            percent = abs(float(change_match.group(1)))
                            trend = "increase" if '+' in change_val or float(change_match.group(1)) > 0 else "decrease"
                            comparisons.append({
                                "period": period,
                                "value": percent,
                                "trend": trend
                            })

        return {
            "title": title,
            "value": value,
            "icon": icon,
            "comparisons": comparisons
        }

    def _render_icon(self, icon: Optional[str] = None) -> str:
        """Render icon HTML"""
        if not icon:
            return ''
        icon_char = self.ICON_MAP.get(icon.lower(), self.ICON_MAP['default'])
        return f'<div class="ap-card-icon">{icon_char}</div>'

    def _render_comparison_items(self, comparisons: List[Dict]) -> str:
        """Render comparison items HTML"""
        if not comparisons:
            return ''

        items_html = []
        for comp in comparisons:
            period = comp.get('period', 'vs Previous')
            value = comp.get('value', 0)
            trend = comp.get('trend', 'increase').lower()
            trend_icon = '▲' if trend == 'increase' else '▼'

            item_html = self.COMPARISON_ITEM_TEMPLATE.format(
                period=period,
                value=abs(value),
                trend=trend,
                trend_icon=trend_icon
            )
            items_html.append(item_html)

        return '\n'.join(items_html)

    def _render_single_card(self, data: Dict) -> str:
        """Render a single metric card"""
        title = data.get('title', 'Metric')
        value = data.get('value', 'N/A')
        icon = data.get('icon')
        comparisons = data.get('comparisons', [])

        icon_html = self._render_icon(icon)
        comparisons_html = self._render_comparison_items(comparisons)

        return self.SINGLE_CARD_TEMPLATE.format(
            title=title,
            value=value,
            icon_html=icon_html,
            comparisons_html=comparisons_html
        )

    async def render(
        self,
        response: Any,
        environment: str = 'html',
        **kwargs
    ) -> Tuple[str, str]:
        """
        Render card(s) as HTML.

        Args:
            response: AIMessage with PandasAgentResponse output
            environment: Output environment (default: 'html')
            **kwargs: Additional options

        Returns:
            Tuple[str, str]: (code, html_content)
        """
        # Extract data from AIMessage
        code = response.code if hasattr(response, 'code') else ''
        card_data = self._extract_data(response)

        # Generate card HTML
        cards_html = self._render_single_card(card_data)

        # Determine title
        page_title = card_data.get('title', 'Metric Card')

        # Generate final HTML
        html_content = self.CARD_TEMPLATE.format(
            title=page_title,
            cards_html=cards_html
        )

        return code, html_content
