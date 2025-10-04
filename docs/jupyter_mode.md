# Jupyter Output Mode Documentation

## Overview

The **Jupyter Output Mode** provides specialized formatting for Jupyter notebooks with interactive widgets, rich markdown rendering, and collapsible sections. It automatically detects Jupyter environments and provides the best possible display experience.

## Features

### 🎨 Rich Visual Display
- Beautiful markdown rendering with syntax highlighting
- Color-coded sections and status indicators
- Responsive layouts that adapt to notebook width
- Theme support (light/dark modes)

### 🎛️ Interactive Widgets
- Collapsible accordions for metadata, tools, and sources
- Interactive buttons and controls
- Tabbed interfaces for multi-section content
- Progress indicators for long-running operations

### 📊 Smart Content Rendering
- Automatic markdown-to-HTML conversion
- Syntax-highlighted code blocks
- Formatted tables and lists
- Inline LaTeX support

### 🔍 Contextual Information
- Tool call history with status indicators
- Metadata with token usage and timing
- Source documents with relevance scores
- Context information (vector search, conversation history)

---

## Installation

### Required Dependencies

```bash
# Core dependencies (already in AI-Parrot)
pip install rich panel

# Jupyter-specific dependencies
pip install ipython ipywidgets jupyter

# Optional: Markdown rendering
pip install markdown
```

### Enable Jupyter Widgets

```bash
# For Jupyter Notebook
jupyter nbextension enable --py widgetsnbextension

# For JupyterLab
jupyter labextension install @jupyter-widgets/jupyterlab-manager
```

---

## Usage

### Basic Usage

```python
from aiparrot.outputs import OutputFormatter, OutputMode

# Create formatter with Jupyter mode
formatter = OutputFormatter(mode=OutputMode.JUPYTER)

# Format and display response
formatter.format(agent_response)
```

### Auto-Detection

The formatter automatically detects Jupyter environments:

```python
# Will automatically use JUPYTER mode if in a notebook
formatter = OutputFormatter(mode=OutputMode.DEFAULT)

# The formatter detects:
# - IPython environment
# - Jupyter notebook kernel
# - Available widget libraries
```

### Configuration Options

```python
formatter.format(
    response,
    show_metadata=True,      # Show metadata section
    show_sources=True,       # Show source documents
    show_tools=True,         # Show tool calls
    show_context=False,      # Show context info (vector search, etc.)
    use_widgets=True,        # Use interactive widgets
    collapsible=True,        # Make sections collapsible
    theme='light'            # Theme: 'light' or 'dark'
)
```

---

## Examples

### Example 1: Basic Agent Response

```python
from aiparrot import Agent
from aiparrot.outputs import OutputFormatter, OutputMode

# Create agent
agent = Agent(
    name="AssistantAgent",
    llm=your_llm_client
)

# Create Jupyter formatter
formatter = OutputFormatter(mode=OutputMode.JUPYTER)

# Run query and format output
response = await agent.run("Explain quantum computing")
formatter.format(response)
```

**Output:**
- 🤖 Main response in a styled box with markdown rendering
- 📊 Collapsible metadata section showing model, tokens, timing
- All sections beautifully formatted with consistent styling

---

### Example 2: RAG Agent with Sources

```python
from aiparrot import Agent
from aiparrot.outputs import OutputFormatter, OutputMode

# RAG agent with knowledge base
agent = Agent(
    name="RAGAgent",
    llm=your_llm_client,
    knowledge_base=kb,
    rag_enabled=True
)

formatter = OutputFormatter(mode=OutputMode.JUPYTER)

# Query with source tracking
response = await agent.run("What are the benefits of solar energy?")

# Display with sources
formatter.format(
    response,
    show_sources=True,
    show_context=True,  # Show RAG context info
    theme='light'
)
```

**Output:**
- 🤖 Main answer with citations
- 🔍 Context section showing vector search details
- 📄 Sources accordion with relevance scores (color-coded)

---

### Example 3: Tool-Using Agent

```python
from aiparrot import Agent
from aiparrot.tools import WebScrapingTool, PythonREPLTool
from aiparrot.outputs import OutputFormatter, OutputMode

# Agent with tools
scraper = WebScrapingTool()
python = PythonREPLTool()

agent = Agent(
    name="ToolAgent",
    llm=your_llm_client,
    tools=[scraper, python]
)

formatter = OutputFormatter(mode=OutputMode.JUPYTER)

# Task requiring tools
response = await agent.run(
    "Scrape weather data from weather.com and calculate average temperature"
)

# Display with tool information
formatter.format(
    response,
    show_tools=True,
    use_widgets=True,
    collapsible=True
)
```

**Output:**
- 🤖 Main response with analysis results
- 🔧 Tool calls accordion showing:
  - WebScrapingTool: ✓ completed
  - PythonREPLTool: ✓ completed
- Each tool with status indicator (green dot = success)

---

### Example 4: Dark Theme

```python
formatter = OutputFormatter(mode=OutputMode.JUPYTER)

formatter.format(
    response,
    theme='dark',  # Dark mode
    show_metadata=True,
    show_sources=True
)
```

**Styling:**
- Dark background (#1e1e1e)
- Light text (#d4d4d4)
- Blue accent (#007acc)
- Optimized for dark notebook themes

---

### Example 5: Minimal Output (No Widgets)

```python
# Fallback to simple display (no ipywidgets)
formatter = OutputFormatter(mode=OutputMode.JUPYTER)

formatter.format(
    response,
    use_widgets=False,  # Disable interactive widgets
    show_metadata=True,
    show_sources=True
)
```

**Output:**
- Clean markdown sections
- No collapsible elements
- Faster rendering
- Works without ipywidgets installed

---

### Example 6: Custom Integration

```python
from aiparrot.outputs import OutputFormatter, OutputMode

class CustomAgent:
    def __init__(self):
        self.formatter = OutputFormatter(mode=OutputMode.JUPYTER)

    async def run(self, query: str):
        # Your agent logic
        response = await self._process_query(query)

        # Auto-format in Jupyter
        self.formatter.format(
            response,
            show_metadata=True,
            show_tools=True,
            collapsible=True
        )

        return response

# Usage
agent = CustomAgent()
await agent.run("Analyze this dataset")
```

---

## Output Modes Comparison

| Feature | TERMINAL | HTML | JUPYTER | JSON |
|---------|----------|------|---------|------|
| **Rich Formatting** | ✅ (Rich) | ✅ (Panel) | ✅ (Native) | ❌ |
| **Interactive Widgets** | ❌ | ⚠️ (Panel) | ✅ | ❌ |
| **Markdown Rendering** | ✅ | ✅ | ✅ | ❌ |
| **Collapsible Sections** | ❌ | ⚠️ | ✅ | ❌ |
| **Syntax Highlighting** | ✅ | ⚠️ | ✅ | ❌ |
| **Best For** | CLI | Web Apps | Notebooks | APIs |

---

## Advanced Features

### 1. Inline Visualizations

The Jupyter mode automatically detects and displays visualizations:

```python
import matplotlib.pyplot as plt
import pandas as pd

# Agent generates visualization code
response = await agent.run("Create a bar chart of sales data")

# Visualizations are embedded inline
formatter.format(response)

# If response contains matplotlib figures, they display inline
```

### 2. Code Execution Display

```python
from IPython.display import Code

# Display code with syntax highlighting
formatter.format(response, show_tools=True)

# Tool outputs with code are highlighted:
# - Python code: Python syntax
# - JavaScript: JS syntax
# - SQL: SQL syntax
```

### 3. Progress Indicators

```python
from ipywidgets import IntProgress
from IPython.display import display

# For long-running agents
progress = IntProgress(min=0, max=100, description='Processing:')
display(progress)

# Update progress
for i in range(100):
    progress.value = i
    # Agent processing...

formatter.format(response)
```

### 4. LaTeX Support

```python
# Responses with LaTeX are rendered beautifully
response_with_math = """
The quadratic formula is:

$$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$$
"""

# IPython automatically renders LaTeX in markdown
formatter.format(response_with_math)
```

---

## Customization

### Custom Widget Styling

```python
from ipywidgets import HTML, Layout

class CustomJupyterFormatter(OutputFormatter):
    def _create_custom_widget(self, content: str) -> HTML:
        return HTML(
            value=f"""
            <div style="
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 20px;
                border-radius: 10px;
                color: white;
            ">
                {content}
            </div>
            """,
            layout=Layout(width='100%')
        )

formatter = CustomJupyterFormatter(mode=OutputMode.JUPYTER)
```

### Custom Theme

```python
# Define custom color scheme
custom_theme = {
    'bg_color': '#2d2d2d',
    'text_color': '#f0f0f0',
    'accent_color': '#ff6b6b',
    'border_color': '#4a4a4a'
}

# Apply to formatter (extend the class)
class ThemedFormatter(OutputFormatter):
    def __init__(self, *args, custom_theme=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.custom_theme = custom_theme or {}
```

---

## Best Practices

### 1. ✅ Use Auto-Detection

```python
# Let the formatter detect the environment
formatter = OutputFormatter()  # Automatically uses JUPYTER in notebooks
```

### 2. ✅ Enable Widgets for Rich Experience

```python
# Full feature set
formatter.format(response, use_widgets=True, collapsible=True)
```

### 3. ✅ Show Context for RAG Applications

```python
# Always show context for RAG agents
formatter.format(
    response,
    show_context=True,
    show_sources=True
)
```

### 4. ✅ Use Dark Theme for Dark Notebooks

```python
# Match your notebook theme
formatter.format(response, theme='dark')
```

### 5. ❌ Don't Mix Output Modes

```python
# Bad: Multiple formatters
formatter1 = OutputFormatter(mode=OutputMode.TERMINAL)
formatter2 = OutputFormatter(mode=OutputMode.JUPYTER)

# Good: Single formatter for consistency
formatter = OutputFormatter(mode=OutputMode.JUPYTER)
```

---

## Troubleshooting

### Issue: Widgets Not Displaying

**Solution:** Enable Jupyter widgets extension:

```bash
# Jupyter Notebook
jupyter nbextension enable --py widgetsnbextension --sys-prefix

# JupyterLab 3.x
pip install jupyterlab_widgets
```

### Issue: Markdown Not Rendering

**Solution:** Install markdown library:

```bash
pip install markdown
```

### Issue: Accordions Not Collapsible

**Solution:** Ensure ipywidgets is installed and enabled:

```python
import ipywidgets
print(ipywidgets.__version__)  # Should be >= 7.0
```

### Issue: Display Errors in Async Context

**Solution:** The formatter handles async contexts automatically, but you can force synchronous display:

```python
formatter.format(response, use_widgets=False)
```

---

## Performance Considerations

### Widget Overhead

Interactive widgets add minimal overhead (~50-100ms) but provide significant UX benefits:

```python
# Fast rendering (no widgets)
formatter.format(response, use_widgets=False)

# Rich experience (with widgets)
formatter.format(response, use_widgets=True)  # +50-100ms
```

### Large Outputs

For very large responses, consider limiting displayed content:

```python
# Limit sources displayed
if hasattr(response, 'source_documents'):
    response.source_documents = response.source_documents[:10]

formatter.format(response)
```

---

## Integration Examples

### With Streamlit (Hybrid)

```python
import streamlit as st
from aiparrot.outputs import OutputFormatter, OutputMode

# Use HTML mode for Streamlit
formatter = OutputFormatter(mode=OutputMode.HTML)
html_output = formatter.format(response, return_html=True)
st.markdown(html_output, unsafe_allow_html=True)
```

### With Gradio

```python
import gradio as gr
from aiparrot.outputs import OutputFormatter, OutputMode

def process_query(query):
    response = agent.run(query)
    formatter = OutputFormatter(mode=OutputMode.HTML)
    return formatter.format(response, return_html=True)

gr.Interface(
    fn=process_query,
    inputs="text",
    outputs="html"
).launch()
```

---

## Future Enhancements

Planned features for future releases:

- 🎯 **Interactive Chat History**: Scroll through conversation with navigation
- 📊 **Live Token Counter**: Real-time token usage visualization
- 🎨 **Custom Themes**: User-defined color schemes
- 🔄 **Streaming Output**: Progressive rendering for streaming responses
- 📱 **Mobile Optimization**: Better display on mobile Jupyter clients
- 🎭 **Animation**: Smooth transitions and loading animations
- 🔗 **Linked Sources**: Clickable source references in response
- 💾 **Export Options**: Save formatted output as HTML/PDF

---

## Summary

The Jupyter output mode provides:

✅ **Rich Visual Experience** - Beautiful, interactive displays
✅ **Native Integration** - Works seamlessly with Jupyter ecosystem
✅ **Flexible Configuration** - Customize to your needs
✅ **Auto-Detection** - Automatically uses best mode
✅ **Performance** - Fast rendering with minimal overhead
✅ **Accessibility** - Fallbacks for all environments

Use Jupyter mode for the best AI-Parrot experience in notebooks! 🚀
