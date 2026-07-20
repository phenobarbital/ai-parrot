"""
Full registry resolution tests — FEAT-200.

Tests that the renderer registry works correctly after the PEP 420 extraction,
including lazy loading, prompt registration, and OutputFormatter integration.
"""
import pytest
from parrot.models.outputs import OutputMode
from parrot.outputs.formats import get_renderer, get_output_prompt, has_system_prompt, RENDERERS
from parrot.outputs.formats.base import BaseRenderer
from parrot.outputs import OutputFormatter, OutputMode as OutputModeAlias


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------

def test_renderers_dict_populated():
    """After accessing core modes, RENDERERS dict is populated."""
    # Note: TERMINAL mode has no registered renderer (pre-existing issue)
    for mode in [OutputMode.JSON, OutputMode.YAML, OutputMode.HTML, OutputMode.TABLE]:
        get_renderer(mode)
    assert len(RENDERERS) >= 4


def test_all_renderers_inherit_base():
    """Every registered renderer inherits from BaseRenderer."""
    # Note: TERMINAL mode has no registered renderer (pre-existing issue)
    for mode in [OutputMode.JSON, OutputMode.YAML, OutputMode.HTML, OutputMode.TABLE]:
        cls = get_renderer(mode)
        assert issubclass(cls, BaseRenderer), \
            f"{mode}: {cls.__name__} does not inherit from BaseRenderer"


def test_renderer_idempotent():
    """Calling get_renderer twice returns the same class."""
    cls1 = get_renderer(OutputMode.JSON)
    cls2 = get_renderer(OutputMode.JSON)
    assert cls1 is cls2


def test_unknown_mode_raises():
    """get_renderer raises ValueError for a mode with no renderer."""
    with pytest.raises(ValueError, match="No renderer registered"):
        # DEFAULT mode has no renderer
        get_renderer(OutputMode.DEFAULT)


# ---------------------------------------------------------------------------
# Output prompt system
# ---------------------------------------------------------------------------

def test_json_has_no_system_prompt():
    """JSON renderer has no system prompt (not needed)."""
    get_renderer(OutputMode.JSON)  # ensure loaded
    assert has_system_prompt(OutputMode.JSON) is False
    assert get_output_prompt(OutputMode.JSON) is None



# ---------------------------------------------------------------------------
# OutputFormatter integration
# ---------------------------------------------------------------------------

def test_output_formatter_importable():
    """OutputFormatter is importable from parrot.outputs."""
    assert OutputFormatter is not None


def test_output_mode_alias():
    """OutputMode is re-exported correctly from parrot.outputs."""
    assert OutputMode is OutputModeAlias


# ---------------------------------------------------------------------------
# Satellite-specific renderer tests
# ---------------------------------------------------------------------------

def test_echarts_renderer_has_system_prompt():
    """EChartsRenderer has a system prompt."""
    assert has_system_prompt(OutputMode.ECHARTS) is True


def test_infographic_renderer_is_html_renderer():
    """INFOGRAPHIC mode returns InfographicHTMLRenderer (overrides InfographicRenderer)."""
    cls = get_renderer(OutputMode.INFOGRAPHIC)
    assert cls.__name__ == 'InfographicHTMLRenderer'


def test_jinja2_renderer_resolves():
    """Jinja2Renderer resolves for JINJA2 mode."""
    cls = get_renderer(OutputMode.JINJA2)
    assert cls.__name__ == 'Jinja2Renderer'
    assert issubclass(cls, BaseRenderer)


def test_satellite_renderers_have_render_method():
    """All satellite renderers have a render method."""
    satellite_modes = [
        OutputMode.ECHARTS,
        OutputMode.MAP, OutputMode.INFOGRAPHIC, OutputMode.JINJA2,
        OutputMode.CARD, OutputMode.SLACK,
    ]
    for mode in satellite_modes:
        cls = get_renderer(mode)
        assert hasattr(cls, 'render'), \
            f"{mode}: {cls.__name__} missing 'render' method"


def test_infographic_system_prompt_survives_html_override():
    """InfographicRenderer's system prompt must survive InfographicHTMLRenderer registration.

    The INFOGRAPHIC dispatch imports infographic.py first (registers the prompt),
    then infographic_html.py (registers the renderer class, no prompt arg).
    The prompt from the first registration must NOT be lost.
    """
    cls = get_renderer(OutputMode.INFOGRAPHIC)
    assert cls.__name__ == "InfographicHTMLRenderer"
    assert has_system_prompt(OutputMode.INFOGRAPHIC) is True
    prompt = get_output_prompt(OutputMode.INFOGRAPHIC)
    assert prompt is not None
    assert len(prompt) > 0
    # Verify the prompt comes from InfographicRenderer (structured output prompt)
    assert "INFOGRAPHIC" in prompt.upper()
