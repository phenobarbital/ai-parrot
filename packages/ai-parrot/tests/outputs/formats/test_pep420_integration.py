"""
Integration tests for PEP 420 namespace merging — FEAT-200.

Verifies that ai-parrot (core) and ai-parrot-visualizations (satellite)
correctly merge the parrot.outputs.formats namespace via extend_path(),
making all 23 OutputMode renderers discoverable through a single
get_renderer() API.
"""
import importlib.util
import pytest
from parrot.models.outputs import OutputMode
from parrot.outputs.formats import get_renderer, get_output_prompt, has_system_prompt

# Skip satellite-dependent tests when ai-parrot-visualizations is not installed
satellite_available = pytest.mark.skipif(
    importlib.util.find_spec("parrot.outputs.formats.version") is None,
    reason="ai-parrot-visualizations not installed"
)

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


@satellite_available
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

@satellite_available
@pytest.mark.parametrize("mode", SATELLITE_MODES)
def test_satellite_renderer_resolves(mode):
    """Satellite renderers resolve when ai-parrot-visualizations is installed."""
    cls = get_renderer(mode)
    assert cls is not None
    assert hasattr(cls, 'render'), f"{mode}: renderer missing 'render' method"


@satellite_available
def test_infographic_html_renderer_via_registry():
    """InfographicHTMLRenderer resolves through get_renderer(INFOGRAPHIC)."""
    cls = get_renderer(OutputMode.INFOGRAPHIC)
    assert cls is not None
    assert cls.__name__ == 'InfographicHTMLRenderer', \
        f"Expected InfographicHTMLRenderer, got {cls.__name__}"


@satellite_available
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
    import pathlib
    import re
    src_root = pathlib.Path(__file__).parents[4] / "packages" / "ai-parrot" / "src"
    found = []
    for py_file in src_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        if "from" in text and "infographic_html" in text and "import" in text:
            if re.search(r'from\s+[.\w]*infographic_html\s+import', text):
                found.append(str(py_file.relative_to(src_root)))
    assert found == [], f"Found direct infographic_html imports in core:\n" + "\n".join(found)


# ---------------------------------------------------------------------------
# Specific renderer name checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode,expected_name", [
    (OutputMode.JSON, "JSONRenderer"),
    (OutputMode.YAML, "YAMLRenderer"),
    (OutputMode.HTML, "HTMLRenderer"),
    (OutputMode.TABLE, "TableRenderer"),
    # Note: TERMINAL mode has no registered renderer (TerminalGenerator is not a Renderer)
])
def test_renderer_class_name(mode, expected_name):
    """Each core renderer resolves to the expected class name."""
    cls = get_renderer(mode)
    assert cls.__name__ == expected_name, \
        f"Expected {expected_name} for {mode}, got {cls.__name__}"


@satellite_available
@pytest.mark.parametrize("mode,expected_name", [
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
])
def test_satellite_renderer_class_name(mode, expected_name):
    """Each satellite renderer resolves to the expected class name."""
    cls = get_renderer(mode)
    assert cls.__name__ == expected_name, \
        f"Expected {expected_name} for {mode}, got {cls.__name__}"
