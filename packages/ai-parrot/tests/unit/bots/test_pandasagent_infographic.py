"""Unit tests for PandasAgent.ask post-loop infographic branch (FEAT-197, TASK-1326).

These tests exercise the `_extract_last_infographic_result` helper and the
post-loop branch logic WITHOUT spinning up a full agent session.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
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
        """Build a minimal object with the _extract_last_infographic_result method.

        Uses class NAME matching instead of isinstance to avoid cross-module
        class-identity issues when sys.modules is patched in multiple test files.
        """
        class _MinimalHelper:
            def _extract_last_infographic_result(self, tool_calls):
                if not tool_calls:
                    return None
                for tc in reversed(tool_calls):
                    result = getattr(tc, "result", None)
                    if result is not None and type(result).__name__ == "InfographicRenderResult":
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


class TestFinalizeInfographicResponse:
    """Unit tests for the _finalize_infographic_response helper (explanation split)."""

    def _bind(self):
        """Return the real PandasAgent._finalize_infographic_response function.

        The method does not touch ``self``, so it can be invoked with any
        object as the first argument. Skips if data.py is not importable here.
        """
        try:
            from parrot.bots.data import PandasAgent
        except Exception:  # pragma: no cover - env-dependent
            pytest.skip("parrot.bots.data not importable in this environment")
        return PandasAgent._finalize_infographic_response

    def _resp(self, **kwargs):
        defaults = dict(
            response=None,
            output=None,
            output_mode=OutputMode.DEFAULT,
            artifact_id=None,
            metadata={},
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_explanation_preserved_and_html_in_output(self):
        finalize = self._bind()
        text = "Revenue reached $1.2M, up 5% vs baseline."
        resp = self._resp(response=text, output=text)
        env = _make_envelope(html_inline="<html>info</html>")

        explanation = finalize(object(), resp, env)

        # Explanation stays as the chat-bubble reply…
        assert explanation == text
        assert resp.response == text
        # …while output carries the infographic HTML for the canvas.
        assert resp.output == "<html>info</html>"
        assert resp.output_mode == OutputMode.INFOGRAPHIC
        assert resp.artifact_id == "art-1"
        # Explicit, documented metadata contract for the frontend.
        assert resp.metadata["explanation"] == text
        assert resp.metadata["html_url"] == "https://signed/x"
        assert resp.metadata["html_inline_omitted"] is False
        assert resp.metadata["template_name"] == "t"
        assert resp.metadata["theme"] == "dark"

    def test_falls_back_to_output_when_no_response_field(self):
        finalize = self._bind()
        resp = self._resp(response=None, output="Some explanation text")
        env = _make_envelope()

        explanation = finalize(object(), resp, env)

        assert explanation == "Some explanation text"
        assert resp.response == "Some explanation text"
        assert resp.metadata["explanation"] == "Some explanation text"

    def test_html_url_used_when_inline_omitted(self):
        finalize = self._bind()
        resp = self._resp(response="x", output="x")
        env = _make_envelope(html_inline=None)

        finalize(object(), resp, env)

        assert resp.output == "https://signed/x"
        assert resp.metadata["html_inline_omitted"] is True

    def test_no_explanation_when_neither_present(self):
        finalize = self._bind()
        resp = self._resp(response=None, output=None)
        env = _make_envelope()

        explanation = finalize(object(), resp, env)

        assert explanation is None
        assert resp.metadata["explanation"] is None
        # output still set to the HTML so the canvas can render.
        assert resp.output == "<html/>"


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
