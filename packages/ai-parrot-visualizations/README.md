# ai-parrot-visualizations

Visualization renderer backends for the [AI-Parrot](https://github.com/phenobarbital/ai-parrot) framework.

Provides heavy visualization renderers (matplotlib, seaborn, plotly, altair, bokeh,
holoviews, echarts, d3, folium, infographic) as a separate installable package,
keeping the core `ai-parrot` package lightweight.

## Installation

```bash
# Install all renderers
pip install "ai-parrot-visualizations[all]"

# Install specific renderer groups
pip install "ai-parrot-visualizations[matplotlib,seaborn]"
pip install "ai-parrot-visualizations[plotly,altair]"
pip install "ai-parrot-visualizations[charts]"      # all chart renderers
pip install "ai-parrot-visualizations[infographic]"  # infographic renderers
pip install "ai-parrot-visualizations[messaging]"    # card/slack/whatsapp
```

## Usage

Import paths are unchanged — the PEP 420 namespace merging makes satellite
renderers transparent to the consumer:

```python
from parrot.outputs.formats import get_renderer
from parrot.models.outputs import OutputMode

# Works the same whether renderer is in core or satellite
renderer_cls = get_renderer(OutputMode.MATPLOTLIB)
result = renderer_cls.render(data)
```

## Available Extras

| Extra | Renderers | Dependencies |
|-------|-----------|--------------|
| `matplotlib` | MatplotlibRenderer | matplotlib>=3.7 |
| `seaborn` | SeabornRenderer | seaborn>=0.13, matplotlib>=3.7 |
| `plotly` | PlotlyRenderer | plotly>=5.0 |
| `altair` | AltairRenderer | altair>=5.0 |
| `bokeh` | BokehRenderer | bokeh>=3.0, pandas-bokeh>=0.5 |
| `holoviews` | HoloviewsRenderer | holoviews>=1.18 |
| `echarts` | EChartsRenderer | (JS-based, no Python deps) |
| `d3` | D3Renderer | (JS-based, no Python deps) |
| `map` | MapRenderer | folium>=0.14 |
| `infographic` | InfographicRenderer, InfographicHTMLRenderer | cairosvg, svglib, reportlab |
| `jinja2` | Jinja2Renderer, TemplateReportRenderer | jinja2>=3.0 |
| `streamlit` | StreamlitGenerator | streamlit>=1.30 |
| `panel` | PanelGenerator | panel>=1.0 |
| `messaging` | CardRenderer, SlackRenderer, WhatsAppRenderer | (no heavy deps) |
| `charts` | All chart renderers | (all chart deps above) |
| `all` | Everything | (all deps above) |

## Architecture

This package uses **PEP 420 implicit namespace packages** to contribute to the
`parrot.outputs.formats` namespace without requiring entry-points. When both
`ai-parrot` and `ai-parrot-visualizations` are installed, Python merges their
`parrot/outputs/formats/` directories via `extend_path()`.

## License

MIT — see the [LICENSE](https://github.com/phenobarbital/ai-parrot/blob/main/LICENSE) file.
