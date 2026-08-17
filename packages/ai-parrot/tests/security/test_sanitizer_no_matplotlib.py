"""FEAT-423 (TASK-2220): matplotlib/seaborn must not be sandbox-allowlisted.

``_GENERAL_IMPORTS`` (the allowlist consumed by ``general_profile()``) must
no longer grant ``matplotlib``/``matplotlib.pyplot``/``seaborn`` — consistent
with ``PythonREPLTool.BLOCKED_IMPORTS`` (TASK-2218) and the sandbox's
"structured-chart/A2UI/altair only" visualization policy.
"""

from parrot.security.python_sanitizer import general_profile


def test_matplotlib_not_in_general_imports():
    """matplotlib must not be in the general profile allowlist."""
    profile = general_profile()
    allowed = profile.allowed_imports
    assert "matplotlib" not in allowed
    assert "matplotlib.pyplot" not in allowed


def test_seaborn_not_in_general_imports():
    """seaborn must not be in the general profile allowlist."""
    profile = general_profile()
    assert "seaborn" not in profile.allowed_imports


def test_altair_still_allowed():
    """altair must remain in the general profile allowlist."""
    profile = general_profile()
    assert "altair" in profile.allowed_imports


def test_plotly_still_allowed():
    """plotly must remain in the general profile allowlist."""
    profile = general_profile()
    assert "plotly" in profile.allowed_imports
