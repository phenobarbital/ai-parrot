"""
Card Renderer for AI-Parrot
Displays metrics in HTML card format with comparisons (vs last month, vs last year, etc.)
"""
from typing import Any, Optional, Tuple, Dict, List, Union
import json
from dataclasses import is_dataclass, asdict
from pydantic import BaseModel
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


CARD_SYSTEM_PROMPT = """CARD METRIC OUTPUT MODE - CRITICAL INSTRUCTIONS:

You MUST structure your response with BOTH an explanation AND card_data fields.

**RESPONSE FORMAT:**
```json
{
  "explanation": "Your analysis text here...",
  "card_data": {
    "title": "Metric Name",
    "value": "Formatted Value",
    "icon": "optional_icon",
    "comparisons": [
      {"period": "vs Previous Period", "value": 12.5, "trend": "increase"}
    ]
  }
}
```

**CRITICAL RULES:**
1. ALWAYS include a "card_data" field with the metric card structure
2. The "explanation" can contain your analysis text
3. Format the "value" field appropriately (e.g., "$29.58K", "20.94 minutes", "1,234 users")
4. Include at least one comparison if historical data is available
5. Use "increase" or "decrease" for trend direction
6. Choose an appropriate icon: money, dollar, chart, percent, users, growth, target, star, trophy

**EXAMPLES:**

Example 1: Average calculation
Query: "What is the average visit time in May 2025?"
Response:
```json
{
  "explanation": "The average total visit time in May 2025 was approximately 20.94 minutes.",
  "card_data": {
    "title": "Average Visit Time",
    "value": "20.94 min",
    "icon": "chart",
    "comparisons": [
      {"period": "vs April 2025", "value": 5.2, "trend": "increase"},
      {"period": "vs May 2024", "value": 12.8, "trend": "decrease"}
    ]
  }
}
```

Example 2: Revenue metric
Query: "Show Best Buy revenue for June 2025"
Response:
```json
{
  "explanation": "Best Buy's total revenue for June 2025 was $29.58K, showing a decline from the previous month but strong year-over-year growth.",
  "card_data": {
    "title": "Revenue",
    "value": "$29.58K",
    "icon": "money",
    "comparisons": [
      {"period": "vs Last Month", "value": 44.3, "trend": "decrease"},
      {"period": "vs Last Year", "value": 86.1, "trend": "increase"}
    ]
  }
}
```

Example 3: Count metric
Query: "How many users signed up this month?"
Response:
```json
{
  "explanation": "A total of 1,234 new users signed up this month, representing strong growth.",
  "card_data": {
    "title": "New Sign-ups",
    "value": "1,234",
    "icon": "users",
    "comparisons": [
      {"period": "vs Last Month", "value": 23.5, "trend": "increase"}
    ]
  }
}
```

**IMPORTANT:** Even if you can't calculate exact comparisons, you MUST still include the card_data structure with at least the title and value.
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
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}

        .card-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 24px;
            max-width: 1200px;
            width: 100%;
            justify-content: center;
        }}

        .metric-card {{
            background: white;
            border-radius: 16px;
            padding: 28px 32px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
            position: relative;
            min-width: 280px;
            max-width: 400px;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }}

        .metric-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 15px 50px rgba(0, 0, 0, 0.2);
        }}

        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}

        .card-title {{
            font-size: 15px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .card-icon {{
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

        .card-value {{
            font-size: 42px;
            font-weight: 700;
            color: #1e293b;
            margin-bottom: 20px;
            line-height: 1;
        }}

        .comparisons {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}

        .comparison-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-top: 1px solid #f1f5f9;
        }}

        .comparison-item:first-child {{
            border-top: none;
            padding-top: 0;
        }}

        .comparison-period {{
            font-size: 14px;
            color: #64748b;
            font-weight: 500;
        }}

        .comparison-value {{
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 16px;
            font-weight: 700;
        }}

        .comparison-value.increase {{
            color: #10b981;
        }}

        .comparison-value.decrease {{
            color: #ef4444;
        }}

        .trend-icon {{
            font-size: 14px;
        }}

        .explanation {{
            background: white;
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
            max-width: 800px;
        }}

        .explanation h3 {{
            color: #1e293b;
            font-size: 18px;
            margin-bottom: 12px;
        }}

        .explanation p {{
            color: #64748b;
            line-height: 1.6;
        }}

        @media (max-width: 768px) {{
            .card-container {{
                flex-direction: column;
                align-items: center;
            }}

            .metric-card {{
                width: 100%;
                max-width: 100%;
            }}
        }}
    </style>
</head>
<body>
    <div class="card-container">
        {explanation_html}
        {cards_html}
    </div>
</body>
</html>
"""

    SINGLE_CARD_TEMPLATE = """
        <div class="metric-card">
            <div class="card-header">
                <div class="card-title">{title}</div>
                {icon_html}
            </div>
            <div class="card-value">{value}</div>
            <div class="comparisons">
                {comparisons_html}
            </div>
        </div>
"""

    COMPARISON_ITEM_TEMPLATE = """
                <div class="comparison-item">
                    <span class="comparison-period">{period}</span>
                    <div class="comparison-value {trend}">
                        <span class="trend-icon">{trend_icon}</span>
                        <span>{value}%</span>
                    </div>
                </div>
"""

    EXPLANATION_TEMPLATE = """
        <div class="explanation">
            <h3>Analysis</h3>
            <p>{explanation}</p>
        </div>
"""

    ICON_MAP = {
        'money': '💰',
        'dollar': '💵',
        'chart': '📊',
        'percent': '%',
        'users': '👥',
        'growth': '📈',
        'target': '🎯',
        'star': '⭐',
        'trophy': '🏆',
        'default': '📊'
    }

    @classmethod
    def get_expected_content_type(cls) -> type:
        """Define expected content type"""
        return dict

    def _extract_card_data(self, response: Any) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Extract card data and explanation from various response types.
        Returns: (card_data, explanation)
        """
        explanation = None
        card_data = None
        
        # Try to get the response as dict
        data = None
        
        if isinstance(response, dict):
            data = response
        elif isinstance(response, BaseModel):
            data = response.model_dump()
        elif is_dataclass(response):
            data = asdict(response)
        elif hasattr(response, 'output'):
            output = response.output
            if isinstance(output, dict):
                data = output
            elif isinstance(output, BaseModel):
                data = output.model_dump()
            elif is_dataclass(output):
                data = asdict(output)
            elif isinstance(output, str):
                # Try to parse as JSON
                try:
                    data = json.loads(output)
                except json.JSONDecodeError:
                    # Maybe it's in the response text
                    pass
        
        # If we still don't have data, try to parse as string
        if data is None and isinstance(response, str):
            try:
                data = json.loads(response)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code blocks
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
                if json_match:
                    try:
                        data = json.loads(json_match.group(1))
                    except json.JSONDecodeError:
                        pass
        
        # Extract card_data and explanation from parsed data
        if isinstance(data, dict):
            # Check for explicit card_data field
            if 'card_data' in data:
                card_data = data['card_data']
                explanation = data.get('explanation')
            # Check for direct card structure
            elif 'title' in data and 'value' in data:
                card_data = data
                explanation = data.get('explanation')
            # Check for explanation with embedded values
            elif 'explanation' in data:
                explanation = data['explanation']
                # Try to extract values from explanation
                card_data = self._extract_from_explanation(explanation, response)
        
        return card_data, explanation

    def _extract_from_explanation(self, explanation: str, response: Any) -> Dict:
        """
        Attempt to extract card data from explanation text.
        This is a fallback when the LLM doesn't provide structured card_data.
        """
        # Try to extract a numeric value from the explanation
        # Look for patterns like "20.94 minutes", "$29.58K", "1,234 users"
        
        value_patterns = [
            (r'(\$[\d,]+\.?\d*[KMB]?)', 'Revenue'),  # Money
            (r'([\d,]+\.?\d+)\s*minutes?', 'Time'),  # Time
            (r'([\d,]+\.?\d+)\s*hours?', 'Duration'),  # Hours
            (r'([\d,]+\.?\d+)%', 'Percentage'),  # Percentage
            (r'([\d,]+)', 'Count'),  # Generic number
        ]
        
        extracted_value = None
        title = "Metric"
        icon = "chart"
        
        for pattern, metric_type in value_patterns:
            match = re.search(pattern, explanation)
            if match:
                extracted_value = match.group(1)
                title = metric_type
                if 'revenue' in explanation.lower() or '$' in extracted_value:
                    icon = 'money'
                    title = "Revenue"
                elif 'time' in explanation.lower() or 'minute' in explanation.lower():
                    icon = 'chart'
                    title = "Average Time"
                elif 'user' in explanation.lower():
                    icon = 'users'
                    title = "Users"
                break
        
        if not extracted_value:
            extracted_value = "N/A"
        
        # Try to extract trend information
        comparisons = []
        
        # Look for percentage changes
        trend_patterns = [
            r'(\d+\.?\d*)%\s*(?:increase|growth|up|higher)',
            r'(\d+\.?\d*)%\s*(?:decrease|decline|down|lower)',
        ]
        
        for pattern in trend_patterns:
            matches = re.finditer(pattern, explanation, re.IGNORECASE)
            for i, match in enumerate(matches):
                percent = float(match.group(1))
                trend = "increase" if "increase" in match.group(0).lower() or "growth" in match.group(0).lower() or "up" in match.group(0).lower() else "decrease"
                period = f"vs Previous Period {i+1}" if i > 0 else "vs Previous Period"
                comparisons.append({
                    "period": period,
                    "value": percent,
                    "trend": trend
                })
        
        return {
            "title": title,
            "value": extracted_value,
            "icon": icon,
            "comparisons": comparisons
        }

    def _render_icon(self, icon: Optional[str] = None) -> str:
        """Render icon HTML"""
        if not icon:
            return ''
        
        icon_char = self.ICON_MAP.get(icon.lower(), self.ICON_MAP['default'])
        return f'<div class="card-icon">{icon_char}</div>'

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
        include_explanation: bool = True,
        **kwargs
    ) -> Tuple[str, str]:
        """
        Render card(s) as HTML with optional explanation.
        """
        # Extract card data and explanation
        card_data, explanation = self._extract_card_data(response)
        
        # Generate explanation HTML if available
        explanation_html = ''
        if include_explanation and explanation:
            explanation_html = self.EXPLANATION_TEMPLATE.format(
                explanation=explanation
            )
        
        # Generate card HTML
        if card_data:
            cards_html = self._render_single_card(card_data)
        else:
            # Fallback: create a basic card
            cards_html = self._render_single_card({
                'title': 'Result',
                'value': str(response)[:50],
                'icon': 'chart'
            })
        
        # Determine title
        if isinstance(card_data, dict):
            page_title = card_data.get('title', 'Metric Card')
        else:
            page_title = 'Metric Card'
        
        # Generate final HTML
        html_content = self.CARD_TEMPLATE.format(
            title=page_title,
            explanation_html=explanation_html,
            cards_html=cards_html
        )
        
        return html_content, html_content