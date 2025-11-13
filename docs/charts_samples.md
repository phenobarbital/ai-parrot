from parrot.bots import BasicAgent
from parrot.models.outputs import OutputMode

agent = BasicAgent(name="map_maker")
await agent.configure()

response = await agent.ask(
    "Create a map of California with markers for major cities",
    output_mode=OutputMode.MAP,
    format_kwargs={'html_mode': 'complete'}
)

response = await agent.ask(
    "Create a map of San Francisco with markers at Golden Gate Bridge, Fisherman's Wharf, and Alcatraz",
    output_mode=OutputMode.MAP,
    format_kwargs={
        'export_format': 'both',
        'return_code': True,
        'html_mode': 'complete',
        'title': 'San Francisco Tourist Map'
    }
)

with open("sf_map.html", "w") as f:
    f.write(response.response)



response = await agent.ask(
    """Create a Folium map centered on New York City with:
    - A heatmap showing population density data points
    - Markers for major landmarks (Empire State, Statue of Liberty, Central Park)
    - Different tile layers (OpenStreetMap and Stamen Terrain)
    - Layer control to toggle between layers
    """,
    output_mode=OutputMode.MAP,
    format_kwargs={
        'html_mode': 'complete',
        'title': 'NYC Population Density'
    }
)

response = await agent.ask(
    """Create a map showing a route from Boston to New York with:
    - Start and end markers
    - A polyline showing the route
    - Distance markers every 50 miles
    """,
    output_mode=OutputMode.MAP,
    format_kwargs={
        'html_mode': 'partial'  # For embedding in a web app
    }
)


response = await agent.ask(
    "Create a bar chart showing sales by region: North=150, South=200, East=175, West=190",
    output_mode=OutputMode.PLOTLY,
    format_kwargs={'export_format': 'both', 'return_code': True, 'html_mode': 'complete'}
)

response = await agent.ask(
    "Create a bar chart showing sales by region: North=150, South=200, East=175, West=190",
    output_mode=OutputMode.ALTAIR,
    format_kwargs={'export_format': 'both', 'return_code': True, 'html_mode': 'complete'}
)

response = await agent.ask(
    "Create a bar chart showing sales by region: North=150, South=200, East=175, West=190",
    output_mode=OutputMode.BOKEH,
    format_kwargs={'return_code': True, 'html_mode': 'complete'}
)

with open("chart.html", "w") as f:
    f.write(response.response)



agent = BasicAgent(name="viz_master")

# === D3.js ===
response = await agent.ask(
    """Create a sample D3.js force-directed graph showing:
    - 10 nodes representing team members
    - Links between nodes showing collaboration
    - Interactive dragging
    - Color coding by department
    """,
    output_mode=OutputMode.D3,
    format_kwargs={
        'html_mode': 'complete',
        'title': 'Team Collaboration Network',
        'd3_version': '7'
    }
)

# === D3 - Line Chart with Transitions ===
response = await agent.ask(
    """Create a sample D3 line chart showing temperature over time with:
    - Smooth curves
    - Animated transitions
    - Hover tooltips
    - Zoom and pan functionality
    """,
    output_mode=OutputMode.D3,
    format_kwargs={'html_mode': 'partial'}
)


with open("d3_network.html", "w") as f:
    f.write(response.response)


response = await agent.ask(
    "Create a bar chart showing sales by region: North=150, South=200, East=175, West=190",
    output_mode=OutputMode.ECHARTS,
    format_kwargs={'return_code': True, 'html_mode': 'complete'}
)



# === ECharts ===
response = await agent.ask(
    """Create a sample ECharts visualization showing:
    - A combination chart with bars and lines
    - Monthly revenue (bars) and profit margin (line)
    - Last 12 months of data
    - Tooltip with detailed information
    - Legend to toggle series
    """,
    output_mode=OutputMode.ECHARTS,
    format_kwargs={
        'html_mode': 'complete',
        'title': 'Revenue & Profit Analysis',
        'height': '600px'
    }
)


with open("chart.html", "w") as f:
    f.write(response.response)
