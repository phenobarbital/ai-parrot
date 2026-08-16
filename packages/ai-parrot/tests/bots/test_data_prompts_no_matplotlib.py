"""FEAT-423 (TASK-2219): system prompts must direct the LLM away from matplotlib.

Verifies that ``REACT_PROMPT_PREFIX`` / ``TOOL_CALLING_PROMPT_PREFIX`` in
``parrot.bots.prompts.data`` no longer advertise matplotlib/seaborn as
available libraries, and instead carry a ``## Visualization Policy`` section
directing the LLM to structured-chart/A2UI output (with altair as the sole
fallback for complex visualizations).
"""

from parrot.bots.prompts.data import (
    REACT_PROMPT_PREFIX,
    TOOL_CALLING_PROMPT_PREFIX,
)


def test_no_matplotlib_in_react_prompt():
    """REACT prompt must not mention matplotlib as available."""
    assert "matplotlib" not in REACT_PROMPT_PREFIX.lower() or \
           "do not use matplotlib" in REACT_PROMPT_PREFIX.lower()


def test_no_seaborn_in_react_prompt():
    """REACT prompt must not mention seaborn as available."""
    assert "seaborn" not in REACT_PROMPT_PREFIX.lower() or \
           "do not use seaborn" in REACT_PROMPT_PREFIX.lower()


def test_visualization_policy_in_react():
    """REACT prompt must include visualization policy section."""
    assert "Visualization Policy" in REACT_PROMPT_PREFIX


def test_no_matplotlib_in_tool_calling_prompt():
    """Tool-calling prompt must not list matplotlib as available."""
    assert "matplotlib" not in TOOL_CALLING_PROMPT_PREFIX.lower() or \
           "do not use matplotlib" in TOOL_CALLING_PROMPT_PREFIX.lower()


def test_visualization_policy_in_tool_calling():
    """Tool-calling prompt must include visualization policy section."""
    assert "Visualization Policy" in TOOL_CALLING_PROMPT_PREFIX


def test_altair_mentioned():
    """Both prompts should mention altair as the viz fallback."""
    assert "altair" in REACT_PROMPT_PREFIX.lower()
    assert "altair" in TOOL_CALLING_PROMPT_PREFIX.lower()


def test_databot_default_capabilities_no_matplotlib():
    """DataBot._define_prompt()'s default capabilities text (bots/data.py)
    must not advertise matplotlib/seaborn (FEAT-423 Module 2)."""
    import inspect

    import parrot.bots.data as data_module

    source = inspect.getsource(data_module)
    assert "Create visualizations (matplotlib, seaborn, plotly)" not in source
