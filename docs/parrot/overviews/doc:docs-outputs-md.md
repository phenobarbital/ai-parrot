---
type: Wiki Overview
title: Smart OutputFormatter Documentation
id: doc:docs-outputs-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: The **Smart OutputFormatter** is an intelligent rendering system that automatically
  detects visualization types (Folium maps, Plotly charts, DataFrames, etc.) and renders
  them appropriately based on the environment (Terminal, HTML, Jupyter).
---

# Smart OutputFormatter Documentation

## 🎯 Overview

The **Smart OutputFormatter** is an intelligent rendering system that automatically detects visualization types (Folium maps, Plotly charts, DataFrames, etc.) and renders them appropriately based on the environment (Terminal, HTML, Jupyter).

### Key Innovation

Instead of agents returning just text, they can now return **rich, interactive visualizations** that are:
- ✅ **Auto-detected**: No manual type checking
- ✅ **Environment-aware**: Renders appropriately for Terminal/HTML/Jupyter
- ✅ **Embeddable**: Self-contained HTML for web apps
- ✅ **Multi-output**: Handle multiple visualizations in one response

---

## 🏗️ Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    SmartOutputFormatter                      │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ OutputDetector│  │   Renderer   │  │  Mode Handler   │ │
│  │               │  │   Registry   │  │                 │ │
│  │ - Detects type│  │ - Folium     │  │ - Terminal      │ │
│  │ - Multiple    │  │ - Plotly     │  │ - HTML          │ │
│  │   outputs     │  │ - Matplotlib │  │ - Jupyter       │ │
│  │ - Metadata    │  │ - DataFrame  │  │ - JSON          │ │
│  └───────────────┘  │ - Altair     │  └─────────────────┘ │
│                      │ - Bokeh      │                       │
│                      │ - HTML Widget│                       │
│                      └──────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

### Supported Output Types

| Type | Library | Terminal | HTML | Jupyter |
|------|---------|----------|------|---------|
| **Folium Map** | folium | Description | ✅ Embeddable | ✅ Native |
| **Plotly Chart** | plotly | Description | ✅ Embeddable | ✅ Native |
| **Matplotlib** | matplotlib | Description | ✅ Image | ✅ Native |
| **DataFrame** | pandas | Rich Table | ✅ Styled HTML | ✅ Native |
| **Altair Chart** | altair | Description | ✅ Vega-Lite | ✅ Native |
| **Bokeh Plot** | bokeh | Description | ✅ Embeddable | ✅ Native |
| **HTML Widget** | Any | Description | ✅ Direct | ✅ Native |
| **Image** | PIL | Path | ✅ Base64 | ✅ Display |
| **JSON** | dict/list | Formatted | ✅ Pretty | ✅ Display |

---

## 🚀 Quick Start

### Installation

```bash
# Core
pip install aiparrot

# Visualization libraries (install as needed)
pip install folium plotly matplotlib pandas altair bokeh

# For Jupyter
pip install ipywidgets jupyter
```

### Basic Usage

```python
from aiparrot.outputs import SmartOutputFormatter

# Auto-detect environment
formatter = SmartOutputFormatter()

# Format any response
formatter.format(agent_response)
```

---

## 📖 Usage Patterns

### Pattern 1: Agent Returns Visualization

```python
from aiparrot import Agent
from aiparrot.tools import PythonREPLTool
import folium

python_tool = PythonREPLTool(globals_dict={'folium': folium})

agent = Agent(
    name="MapAgent",
    llm=your_llm,
    tools=[python_tool],
    instructions="Create folium maps. Return the map object."
)

# Agent returns folium.Map
response = await agent.run("Create a map of Paris with Eiffel Tower marker")

# Automatic smart rendering
formatter = SmartOutputFormatter()
formatter.format(response)
```

### Pattern 2: Multiple Outputs

```python
# Agent returns dict with multiple visualizations
response = await agent.run("""
Create:
1. A folium map of top cities
2. A pandas DataFrame with population data
3. A plotly bar chart comparing populations
Return all three as {'map': ..., 'data': ..., 'chart': ...}
""")

# Formatter detects and renders all three!
formatter.format(response)
```

### Pattern 3: Embedding in Web App

```python
# Get embeddable HTML
formatter = SmartOutputFormatter(mode=OutputMode.HTML)
html = formatter.format(response, return_html=True, embed_resources=True)

# Use in Streamlit
st.components.v1.html(html, height=600)

# Use in Gradio
gr.HTML(html)

# Use in FastAPI
return HTMLResponse(content=html)
```

---

## 🎨 Output Modes

### Terminal Mode

Best for: CLI applications, scripts, debugging

```python
formatter = SmartOutputFormatter(mode=OutputMode.TERMINAL)
formatter.format(response)
```

**Output:**
```
🗺️  Folium Map (center: [48.8566, 2.3522], zoom: 12)
[View in HTML/Jupyter mode]

📊 DataFrame (150 rows × 5 columns)
┏━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┓
┃ City     ┃ Population┃ Country  ┃
┡━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━┩
│ Paris    │ 2,165,423 │ France   │
│ London   │ 8,982,000 │ UK       │
└──────────┴───────────┴──────────┘

📈 Plotly Chart (traces: 3)
[View in HTML/Jupyter mode]
```

### HTML Mode

Best for: Web apps, email, file export

```python
formatter = SmartOutputFormatter(mode=OutputMode.HTML)
html = formatter.format(response, return_html=True)
```

**Features:**
- ✅ Self-contained HTML
- ✅ All resources embedded
- ✅ Interactive visualizations preserved
- ✅ Styled with CSS
- ✅ Responsive layout

### Jupyter Mode

Best for: Jupyter notebooks, interactive analysis

```python
formatter = SmartOutputFormatter(mode=OutputMode.JUPYTER)
formatter.format(response)
```

**Features:**
- ✅ Native widget display
- ✅ Interactive controls
- ✅ Collapsible sections
- ✅ Rich markdown
- ✅ Inline rendering

### JSON Mode

Best for: APIs, logging, metadata

```python
formatter = SmartOutputFormatter(mode=OutputMode.JSON)
metadata = formatter.format(response)
```

**Output:**
```json
{
  "outputs": [
    {
      "type": "folium_map",
      "title": "City Map",
      "has_object": true
    },
    {
      "type": "dataframe",
      "title": "Population Data",
      "has_object": true
    }
  ],
  "count": 2
}
```

---

## 🔧 Configuration Options

### HTML Embedding Options

```python
formatter.format(
    response,
    return_html=True,         # Return HTML string
    embed_resources=True,     # Embed all CSS/JS
    width='100%',             # Container width
    height='600px',           # Container height
    include_plotlyjs='cdn',   # 'cdn', True, or False
    use_iframe=False          # Wrap in iframe (for Folium)
)
```

### Jupyter Display Options

```python
formatter.format(
    response,
    use_widgets=True,         # Use interactive widgets
    collapsible=True,         # Collapsible sections
    theme='light',            # 'light' or 'dark'
    show_metadata=True,       # Show metadata
    show_titles=True          # Show section titles
)
```

### Terminal Display Options

```python
formatter.format(
    response,
    max_rows=10,              # Max rows for DataFrames
    show_descriptions=True    # Show descriptions
)
```

---

## 🌐 Integration Examples

### Streamlit App

```python
import streamlit as st
from aiparrot.outputs import SmartOutputFormatter, OutputMode

st.title("🗺️ AI Visualization Assistant")

query = st.text_area("What would you like to visualize?")

if st.button("Generate"):
    response = await agent.run(query)

    formatter = SmartOutputFormatter(mode=OutputMode.HTML)
    html = formatter.format(response, return_html=True)

    # Embed in Streamlit
    st.components.v1.html(html, height=600, scrolling=True)
```

### Gradio App

```python
import gradio as gr

def process_query(query):
    response = await agent.run(query)
    formatter = SmartOutputFormatter(mode=OutputMode.HTML)
    return formatter.format(response, return_html=True)

gr.Interface(
    fn=process_query,
    inputs=gr.Textbox(label="Query"),
    outputs=gr.HTML(label="Visualization"),
    title="AI Visualization Assistant"
).launch()
```

### FastAPI Endpoint

```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.post("/visualize", response_class=HTMLResponse)
async def visualize(query: str):
    response = await agent.run(query)
    formatter = SmartOutputFormatter(mode=OutputMode.HTML)
    return formatter.format(response, return_html=True)
```

### Flask App

```python
from flask import Flask, request, render_template_string

app = Flask(__name__)

@app.route('/visualize', methods=['POST'])
async def visualize():
    query = request.form['query']
    response = await agent.run(query)

    formatter = SmartOutputFormatter(mode=OutputMode.HTML)
    html = formatter.format(response, return_html=True)

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <body>
        {{ content|safe }}
    </body>
    </html>
    """, content=html)
```

---

## 🎭 Advanced Features

### Custom Renderers

Add support for custom visualization types:

```python
from aiparrot.outputs import BaseRenderer, OutputType

class MyChartRenderer(BaseRenderer):
    def render_terminal(self, obj, **kwargs):
        return f"📊 My Custom Chart\n{obj.description}"

    def render_html(self, obj, **kwargs):
        return f'<div class="my-chart">{obj.to_html()}</div>'

    def render_jupyter(self, obj, **kwargs):
        return obj

# Register
formatter = SmartOutputFormatter()
formatter.renderers[OutputType.CUSTOM_CHART] = MyChartRenderer()
```

### Conditional Rendering

```python
# Different rendering based on output size
if len(dataframe) > 1000:
    # Large dataset: show summary only
    formatter.format(dataframe, max_rows=50)
else:
    # Small dataset: show all
    formatter.format(dataframe)
```

### Batch Processing

```python
async def batch_visualize(queries: list, output_dir: str):
    formatter = SmartOutputFormatter(mode=OutputMode.HTML)

    for idx, query in enumerate(queries):
        response = await agent.run(query)
        html = formatter.format(response, return_html=True)

        with open(f"{output_dir}/viz_{idx}.html", 'w') as f:
            f.write(html)
```

---

## 📊 Real-World Use Cases

### 1. Geospatial Analysis Agent

```python
# Agent creates interactive maps
response = await geo_agent.run(
    "Map all Starbucks locations in Seattle with heatmap"
)
formatter.format(response)  # Interactive Folium map with heatmap layer
```

### 2. Data Analysis Agent

```python
# Agent returns multiple visualizations
response = await data_agent.run("""
Analyze sales data and create:
1. Line chart showing trends
2. DataFrame with summary statistics
3. Bar chart comparing categories
""")
formatter.format(response)  # All three rendered beautifully
```

### 3. Financial Dashboard Agent

```python
# Agent creates Plotly dashboard
response = await finance_agent.run(
    "Create an interactive dashboard with stock prices, volume, and moving averages"
)
formatter.format(response)  # Interactive Plotly dashboard
```

### 4. Scientific Visualization Agent

```python
# Agent creates matplotlib figures
response = await science_agent.run(
    "Plot the relationship between temperature and pressure with error bars"
)
formatter.format(response)  # High-quality matplotlib figure
```

---

## ⚡ Performance Considerations

### Embedding Strategies

| Strategy | Size | Load Time | Interactivity |
|----------|------|-----------|---------------|
| **Embed All** | Large | Slow | ✅ Full |
| **CDN Links** | Small | Fast | ✅ Full |
| **Static Image** | Medium | Fast | ❌ None |

```python
# Large file but works offline
formatter.format(response, embed_resources=True)

# Small file but needs internet
formatter.format(response, embed_resources=False, include_plotlyjs='cdn')

# Smallest file, no interactivity
formatter.format(response, as_static_image=True)
```

### Caching

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def get_cached_visualization(query: str) -> str:
    response = await agent.run(query)
    formatter = SmartOutputFormatter(mode=OutputMode.HTML)
    return formatter.format(response, return_html=True)
```

---

## 🐛 Troubleshooting

### Issue: Folium map not displaying

**Solution:** Check iframe settings
```python
formatter.format(response, use_iframe=True)
```

### Issue: Plotly chart too large

**Solution:** Use CDN instead of embedding
```python
formatter.format(response, include_plotlyjs='cdn')
```

### Issue: DataFrame truncated

**Solution:** Increase max rows
```python
formatter.format(response, max_rows=1000)
```

### Issue: Images not loading in embedded HTML

**Solution:** Ensure resources are embedded
```python
formatter.format(response, embed_resources=True)
```

---

## 🔮 Future Enhancements

Planned features:
- 📱 Mobile-responsive layouts
- 🎨 Custom themes and styling
- 🔄 Streaming visualizations
- 📦 Export to multiple formats (PDF, PNG, SVG)
- 🎬 Animated visualizations
- 🔗 Deep linking and sharing
- 📊 Dashboard composition
- 🎯 Smart layout optimization

---

## 💡 Best Practices

### ✅ DO

1. **Let agent return visualization objects** directly
2. **Use auto-detection** - let formatter figure out the type
3. **Embed resources for portability** when creating standalone files
4. **Use appropriate modes** for each environment
5. **Cache generated HTML** for repeated queries

### ❌ DON'T

1. **Don't convert to string** before formatting
2. **Don't manually detect types** - let the formatter do it
3. **Don't mix output modes** inconsistently
4. **Don't ignore performance** with large visualizations
5. **Don't forget to handle errors** gracefully

---

# =============================================================================
# 5. Complete Flow Diagram
# =============================================================================

"""
format(response)
    ↓
_extract_content(response)  # Get actual content
    ↓
OutputDetector.detect_multiple(content)
    ↓
    ├─→ [Has visualizations] → renderables = [...]
    │       ↓
    │   _render_terminal/html/jupyter/json(renderables)
    │       ↓
    │   Use specialized renderers (FoliumRenderer, PlotlyRenderer, etc.)
    │
    └─→ [No visualizations] → renderables = None
            ↓
        _format_terminal/html/jupyter/json(response)
            ↓
        Use existing text formatting (Rich, Panel, IPython, etc.)

## 🎓 Summary

The Smart OutputFormatter transforms AI-Parrot into a **complete visualization platform**:

- 🤖 **Agents return rich outputs**: Maps, charts, dataframes, not just text
- 🎨 **Auto-rendering**: Detects and renders appropriately
- 🌐 **Embeddable everywhere**: Streamlit, Gradio, FastAPI, Flask, Django
- 📱 **Environment-aware**: Works in Terminal, HTML, Jupyter
- 🚀 **Production-ready**: Used in real applications

This enables powerful use cases like:
- Geospatial intelligence agents
- Data analysis assistants
- Scientific visualization tools
- Business intelligence dashboards
- Interactive report generators

**The future of AI agents is visual!** 🎉
