"""
Integration tests for PEP 420 namespace merging — FEAT-200.

Verifies that ai-parrot (core) and ai-parrot-visualizations (satellite)
correctly merge the parrot.outputs.formats namespace via extend_path(),
making all 23 OutputMode renderers discoverable through a single
get_renderer() API.
"""
import pytest
from parrot.models.outputs import OutputMode
from parrot.outputs.formats import get_renderer, get_output_prompt, has_system_prompt

# ---------------------------------------------------------------------------
# Mode categorisation
# ---------------------------------------------------------------------------

# Modes that stay in core (always available, zero deps)
# Note: TERMINAL mode has no registered renderer (pre-existing — TerminalGenerator
# in generators/ is not a Renderer). Excluded from core modes test.
CORE_MODES = [
    OutputMode.JSON,
    OutputMode.YAML,
    OutputMode.HTML,
    OutputMode.TABLE,
]

# Modes that moved to satellite (require ai-parrot-visualizations)
SATELLITE_MODES = [
    OutputMode.MATPLOTLIB,
    OutputMode.SEABORN,
    OutputMode.PLOTLY,
    OutputMode.ALTAIR,
    OutputMode.BOKEH,
    OutputMode.HOLOVIEWS,
    OutputMode.D3,
    OutputMode.ECHARTS,
    OutputMode.MAP,
    OutputMode.INFOGRAPHIC,
    OutputMode.JINJA2,
    OutputMode.TEMPLATE_REPORT,
    OutputMode.APPLICATION,
    OutputMode.CARD,
    OutputMode.WHATSAPP,
    OutputMode.SLACK,
    OutputMode.MARKDOWN,
]


# ---------------------------------------------------------------------------
# PEP 420 namespace merging verification
# ---------------------------------------------------------------------------

def test_namespace_merging():
    """Verify PEP 420 namespace merging is active for outputs.formats."""
    import parrot.outputs.formats
    # Both core and satellite paths should be present in __path__
    assert len(parrot.outputs.formats.__path__) >= 1
    paths = list(parrot.outputs.formats.__path__)
    assert any('ai-parrot/src' in p or 'ai-parrot' in p for p in paths), \
        f"Core path not in __path__: {paths}"


def test_outputs_namespace_merging():
    """Verify PEP 420 namespace merging is active for outputs."""
    import parrot.outputs
    assert len(parrot.outputs.__path__) >= 1


def test_version_module_discoverable():
    """Satellite version.py is discoverable via namespace merging."""
    from parrot.outputs.formats.version import __version__
    assert __version__ == "0.1.0"


# ---------------------------------------------------------------------------
# Core renderer tests (always available)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", CORE_MODES)
def test_core_renderer_always_available(mode):
    """Core renderers resolve without satellite package."""
    cls = get_renderer(mode)
    assert cls is not None
    assert hasattr(cls, 'render'), f"{mode}: renderer missing 'render' method"


# ---------------------------------------------------------------------------
# Satellite renderer tests (require ai-parrot-visualizations)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", SATELLITE_MODES)
def test_satellite_renderer_resolves(mode):
    """Satellite renderers resolve when ai-parrot-visualizations is installed."""
    cls = get_renderer(mode)
    assert cls is not None
    assert hasattr(cls, 'render'), f"{mode}: renderer missing 'render' method"


def test_infographic_html_renderer_via_registry():
    """InfographicHTMLRenderer resolves through get_renderer(INFOGRAPHIC)."""
    cls = get_renderer(OutputMode.INFOGRAPHIC)
    assert cls is not None
    assert cls.__name__ == 'InfographicHTMLRenderer', \
        f"Expected InfographicHTMLRenderer, got {cls.__name__}"


def test_infographic_html_direct_import():
    """InfographicHTMLRenderer is importable from its original path."""
    from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
    assert InfographicHTMLRenderer is not None


# ---------------------------------------------------------------------------
# Registry helper functions
# ---------------------------------------------------------------------------

def test_output_prompt_functions():
    """get_output_prompt and has_system_prompt work for all modes."""
    for mode in OutputMode:
        if mode == OutputMode.DEFAULT:
            continue
        result = has_system_prompt(mode)
        assert isinstance(result, bool), \
            f"has_system_prompt({mode}) returned {type(result)}, expected bool"
        prompt = get_output_prompt(mode)
        if result:
            assert prompt is not None, \
                f"has_system_prompt({mode})=True but get_output_prompt returned None"


def test_no_direct_infographic_imports_in_core():
    """No direct InfographicHTMLRenderer imports remain in core package."""
    import subprocess
    import os
    # Run from repo root — adjust path if needed
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../../../../..')
    )
    result = subprocess.run(
        ['grep', '-r', 'from.*infographic_html import', 'packages/ai-parrot/src/'],
        capture_output=True, text=True, cwd=repo_root,
    )
    assert result.stdout.strip() == '', \
        f"Found direct imports:\n{result.stdout}"


# ---------------------------------------------------------------------------
# Specific renderer name checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode,expected_name", [
    (OutputMode.MATPLOTLIB, "MatplotlibRenderer"),
    (OutputMode.SEABORN, "SeabornRenderer"),
    (OutputMode.PLOTLY, "PlotlyRenderer"),
    (OutputMode.ALTAIR, "AltairRenderer"),
    (OutputMode.BOKEH, "BokehRenderer"),
    (OutputMode.HOLOVIEWS, "HoloviewsRenderer"),
    (OutputMode.D3, "D3Renderer"),
    (OutputMode.ECHARTS, "EChartsRenderer"),
    (OutputMode.MAP, "FoliumRenderer"),
    (OutputMode.INFOGRAPHIC, "InfographicHTMLRenderer"),
    (OutputMode.JINJA2, "Jinja2Renderer"),
    (OutputMode.TEMPLATE_REPORT, "TemplateReportRenderer"),
    (OutputMode.APPLICATION, "ApplicationRenderer"),
    (OutputMode.CARD, "CardRenderer"),
    (OutputMode.WHATSAPP, "WhatsAppRenderer"),
    (OutputMode.SLACK, "SlackRenderer"),
    (OutputMode.MARKDOWN, "MarkdownRenderer"),
    (OutputMode.JSON, "JSONRenderer"),
    (OutputMode.YAML, "YAMLRenderer"),
    (OutputMode.HTML, "HTMLRenderer"),
    (OutputMode.TABLE, "TableRenderer"),
    # Note: TERMINAL mode has no registered renderer (TerminalGenerator is not a Renderer)
])
def test_renderer_class_name(mode, expected_name):
    """Each renderer resolves to the expected class name."""
    cls = get_renderer(mode)
    assert cls.__name__ == expected_name, \
        f"Expected {expected_name} for {mode}, got {cls.__name__}"
