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


IMPORTANT:
If you need to verify code, use the `python_repl` tool, then return the working code.
"""
