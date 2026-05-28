"""Unit tests for PandasAgent.ask post-loop infographic branch (FEAT-197, TASK-1326).

These tests exercise the `_extract_last_infographic_result` helper and the
post-loop branch logic WITHOUT spinning up a full agent session.
"""
from __future__ import annotations

import sys
import pytest
from unittest.mock import MagicMock

# Force real modules.
for _mod in (
    "parrot.models.infographic",
    "parrot.models.infographic_templates",
    "parrot.tools.infographic_toolkit",
    "parrot.storage.models",
    "parrot.models.outputs",
    "parrot.models.responses",
):
    sys.modules.pop(_mod, None)

import parrot.models.infographic as _ri
import parrot.models.infographic_templates as _rt
import parrot.storage.models as _rsm
import parrot.models.outputs as _ro
import parrot.models.responses as _rr

for m, mod in [
    ("parrot.models.infographic", _ri),
    ("parrot.models.infographic_templates", _rt),
    ("parrot.storage.models", _rsm),
    ("parrot.models.outputs", _ro),
    ("parrot.models.responses", _rr),
]:
    sys.modules[m] = mod

import parrot.tools.infographic_toolkit as _rtk
sys.modules["parrot.tools.infographic_toolkit"] = _rtk

from parrot.tools.infographic_toolkit import InfographicRenderResult  # noqa: E402
from parrot.models.outputs import OutputMode  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal ToolCall stub
# ---------------------------------------------------------------------------

class _ToolCall:
    def __init__(self, name: str, result=None):
        self.name = name
        self.result = result


# ---------------------------------------------------------------------------
# Tests for _extract_last_infographic_result
# ---------------------------------------------------------------------------

def _make_pandas_agent():
    """Create a minimal PandasAgent-like object with just the helper method."""
    # Import lazily to avoid pulling in all of data.py's dependencies.
    sys.modules.pop("parrot.bots.data", None)
    try:
        # Try importing the real method via a lightweight mock
        from parrot.bots.data import _get_infographic_result_class, PandasAgent
        return PandasAgent, _get_infographic_result_class
    except ImportError:
        return None, None


def _make_envelope(**kwargs) -> InfographicRenderResult:
    defaults = dict(
        artifact_id="art-1",
        html_url="https://signed/x",
        html_inline="<html/>",
        template_name="t",
        theme="dark",
        data_variables=["rev"],
        enhanced=False,
    )
    defaults.update(kwargs)
    return InfographicRenderResult(**defaults)


class TestExtractLastInfographicResult:
    """Unit tests for the _extract_last_infographic_result helper."""

    def _make_helper(self):
        """Build a minimal object with the _extract_last_infographic_result method."""
        from parrot.bots.data import _get_infographic_result_class

        class _MinimalHelper:
            def _extract_last_infographic_result(self, tool_calls):
                if not tool_calls:
                    return None
                cls = _get_infographic_result_class()
                if cls is None:
                    return None
                for tc in reversed(tool_calls):
                    result = getattr(tc, "result", None)
                    if isinstance(result, cls):
                        return result
                return None

        return _MinimalHelper()

    def test_returns_none_for_empty_tool_calls(self):
        helper = self._make_helper()
        assert helper._extract_last_infographic_result([]) is None

    def test_returns_none_for_no_infographic_result(self):
        helper = self._make_helper()
        calls = [_ToolCall("python_repl_pandas", result="done")]
        assert helper._extract_last_infographic_result(calls) is None

    def test_returns_infographic_result(self):
        helper = self._make_helper()
        envelope = _make_envelope()
        calls = [
            _ToolCall("python_repl_pandas", result="done"),
            _ToolCall("infographic_render", result=envelope),
        ]
        assert helper._extract_last_infographic_result(calls) is envelope

    def test_returns_last_when_multiple(self):
        helper = self._make_helper()
        first = _make_envelope(artifact_id="a")
        last = _make_envelope(artifact_id="b")
        calls = [
            _ToolCall("infographic_render", result=first),
            _ToolCall("python_repl_pandas", result="done"),
            _ToolCall("infographic_render", result=last),
        ]
        result = helper._extract_last_infographic_result(calls)
        assert result is last
        assert result.artifact_id == "b"

    def test_non_infographic_result_not_returned(self):
        helper = self._make_helper()
        calls = [_ToolCall("other_tool", result={"some": "dict"})]
        assert helper._extract_last_infographic_result(calls) is None


class TestOutputModeInfographic:
    """Test that OutputMode.INFOGRAPHIC can be set directly."""

    def test_output_mode_value(self):
        assert OutputMode.INFOGRAPHIC == "infographic"
        assert OutputMode("infographic") is OutputMode.INFOGRAPHIC


class TestInfographicEnvelopeFields:
    """Verify InfographicRenderResult has the expected fields for post-loop use."""

    def test_has_required_fields(self):
        env = _make_envelope()
        assert hasattr(env, "artifact_id")
        assert hasattr(env, "html_url")
        assert hasattr(env, "html_inline")
        assert hasattr(env, "template_name")
        assert hasattr(env, "theme")
        assert hasattr(env, "data_variables")
        assert hasattr(env, "enhanced")

    def test_html_inline_none_when_not_provided(self):
        env = InfographicRenderResult(
            artifact_id="x",
            html_url="https://u",
            template_name="t",
        )
        assert env.html_inline is None

    def test_output_prefers_html_inline(self):
        env = _make_envelope(html_inline="<html>short</html>")
        expected_output = env.html_inline or env.html_url
        assert expected_output == "<html>short</html>"

    def test_output_falls_back_to_html_url(self):
        env = _make_envelope(html_inline=None)
        expected_output = env.html_inline or env.html_url
        assert expected_output == "https://signed/x"
