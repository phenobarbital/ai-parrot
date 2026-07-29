---
type: Wiki Summary
title: parrot.outputs
id: mod:parrot.outputs
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Output formatters for AI-Parrot using Rich (terminal) and Panel (HTML) with
  Jupyter support.
relates_to:
- concept: mod:parrot
  rel: references
---

# `parrot.outputs`

Output formatters for AI-Parrot using Rich (terminal) and Panel (HTML) with Jupyter support.
- Interactive widgets and controls
- Rich markdown rendering
- Collapsible sections
- Inline visualizations
- Syntax highlighting
- Tables and structured data

Automatically detects and renders:
- Folium maps
- Plotly charts
- Matplotlib figures
- DataFrames
- Altair charts
- Panel dashboards
- HTML widgets
- Images

Each output type is rendered appropriately based on the output mode (Terminal, HTML, Jupyter).
HTML mode generates embeddable widgets for integration with Streamlit, Gradio, web apps, etc.
