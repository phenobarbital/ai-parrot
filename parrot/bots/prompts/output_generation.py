# parrot/prompts/output_generation.py

OUTPUT_SYSTEM_PROMPT = """

Requested Output:
{output_mode}

# Output Mode Descriptions:
- CHART: Generate a chart using one of the specified libraries: plotly, matplotlib, bokeh, or altair.
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
- MAP: Generate a map using the Folium library.
    1. Return ONLY Python code as markdown code block
    2. Use folium library
    3. Store map in variable 'm' or 'map'
    4. DO NOT execute or save - return code only

Example:
```python
import folium

m = folium.Map(location=[40.4168, -3.7038], zoom_start=12)
folium.Marker([40.4168, -3.7038], popup='Madrid').add_to(m)
```

IMPORTANT:
If you need to verify code, use the `python_repl` tool, then return the working code.
"""
