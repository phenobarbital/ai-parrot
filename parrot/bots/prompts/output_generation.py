# parrot/prompts/output_generation.py

OUTPUT_SYSTEM_PROMPT = """

Requested Output:
{output_mode}

# Output Mode Descriptions:
- CHART: Generate a chart using one of the specified libraries: plotly, matplotlib, bokeh, holoviews, seaborn or altair.
    1. Return ONLY the Python code as a markdown code block
    2. Use one of: plotly, matplotlib, bokeh, or altair
    3. Code must be self-contained and executable
    4. Store the figure in a variable named 'fig'
    5. DO NOT execute the code or save files - return code only

    Example format:
```python
import plotly.graph_objects as go

# Create chart
fig = go.Figure(data=[go.Bar(x=[1, 2, 3], y=[4, 5, 6])])
fig.update_layout(title="My Chart")
```
- MAP: Generate a map using the Folium library or Echarts JSON configuration.
    1. Return ONLY the generated code (python, json) as markdown code block
    2. Use folium library or Echarts JSON configuration
    3. Code must be self-contained and executable
    4. For Folium:
        - Store map in variable 'm' or 'map'
    5. For Echarts:
        - Generate a single, valid JSON configuration object for an Apache ECharts map chart
    6. DO NOT execute or save - return code only
    7. If using Echarts, return only the JSON configuration object
    8. DO NOT generate Python code if using Echarts - ONLY JSON configuration
    9. If using Folium, return Python code only
    10. DO NOT mix Folium and Echarts - choose one based on the request

- CARD: Generate an HTML card displaying key metrics with comparisons.
    CRITICAL: When calculating metrics, ALWAYS include comparisons with:
    1. Previous month (if data exists)
    2. Previous year, same month (if data exists)
    3. Show percentage changes for each comparison

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

    In your explanation, mention: "showing a X.X% increase/decrease compared to [previous month] and X.X% increase/decrease compared to [previous year]"
    If previous data doesn't exist, omit that comparison row.

IMPORTANT:
If you need to verify code, use the `python_repl` tool, then return the working code.
"""
