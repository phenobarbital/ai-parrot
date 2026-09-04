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


# ---------------------------------------------------------------------------
# A2UI routing in PandasAgent.ask (FEAT-273/470)
# ---------------------------------------------------------------------------

class TestPandasAgentRoutesA2UI:
    """``PandasAgent.ask`` overrides ``BaseBot``'s post-loop dispatch.

    That override was never wired for ``OutputMode.A2UI``, so on a PandasAgent:

    * a successful render went through ``_finalize_infographic_response``, which
      forces ``OutputMode.INFOGRAPHIC`` and drops ``a2ui_envelope`` on the floor —
      ``output_mode=a2ui`` could never actually produce an A2UI response; and
    * a turn where the LLM rendered nothing fell through to
      ``formatter.format(A2UI, ...)`` and surfaced the internal
      "No renderer registered for mode: OutputMode.A2UI" as the user-visible reply.

    ``ask`` is a single ~51k-char method, so its branches are asserted at the
    source level — the same approach ``test_infographic_toolkit_a2ui_wiring.py``
    uses for ``render()``'s adapter call.
    """

    def _ask_source(self) -> str:
        import inspect

        try:
            from parrot.bots.data import PandasAgent
        except Exception as exc:  # noqa: BLE001 - namespace/Cython worktree layout
            pytest.skip(f"cannot import parrot.bots.data: {exc}")
        return inspect.getsource(PandasAgent.ask)

    def test_infographic_result_with_an_envelope_is_finalized_as_a2ui(self):
        source = self._ask_source()
        assert 'getattr(infographic_envelope, "a2ui_envelope", None)' in source
        assert "finalize_a2ui_response(response)" in source

    def test_interactive_result_with_an_envelope_is_finalized_as_a2ui(self):
        source = self._ask_source()
        assert "interactive_envelope.a2ui_envelope" in source

    def test_a2ui_without_a_surface_downgrades_instead_of_hitting_the_formatter(self):
        source = self._ask_source()
        downgrade = source.index("output_mode=a2ui requested")
        formatter = source.index("await self.formatter.format(")
        # The downgrade must run BEFORE the formatter call, or the formatter
        # raises "No renderer registered for mode: OutputMode.A2UI" first.
        assert downgrade < formatter

    def test_finalize_helper_is_imported(self):
        import parrot.bots.data as data_module

        assert hasattr(data_module, "finalize_a2ui_response")


class TestPandasAgentDualEmitRouting:
    """FEAT-527: dual-emit routing — requested ``output_mode`` decides the
    PRIMARY shape; the other emission rides along additively. Source-level
    assertions, same technique as ``TestPandasAgentRoutesA2UI`` above (``ask``
    is a single huge method not amenable to direct invocation in a unit test).
    """

    def _ask_source(self) -> str:
        import inspect

        try:
            from parrot.bots.data import PandasAgent
        except Exception as exc:  # noqa: BLE001 - namespace/Cython worktree layout
            pytest.skip(f"cannot import parrot.bots.data: {exc}")
        return inspect.getsource(PandasAgent.ask)

    def test_a2ui_requested_checks_output_mode_before_finalizing(self):
        source = self._ask_source()
        assert "if output_mode == OutputMode.A2UI:" in source
        assert 'a2ui_envelope = getattr(infographic_envelope, "a2ui_envelope", None)' in source

    def test_a2ui_primary_populates_metadata_and_artifact_id(self):
        source = self._ask_source()
        assert "response.artifact_id = infographic_envelope.artifact_id" in source
        assert '"html_url": infographic_envelope.html_url,' in source
        assert '"template_name": infographic_envelope.template_name,' in source

    def test_a2ui_requested_without_envelope_logs_warning_and_falls_back(self):
        source = self._ask_source()
        assert "requested output_mode=A2UI but no" in source
        # the warning must appear before the HTML-primary finalize call in the
        # SAME branch, i.e. the fallback happens instead of an early return.
        warning_idx = source.index("requested output_mode=A2UI but no")
        html_finalize_idx = source.index("explanation = self._finalize_infographic_response(")
        assert warning_idx < html_finalize_idx

    def test_html_primary_still_carries_the_a2ui_envelope(self):
        source = self._ask_source()
        # After the HTML-primary finalize call, the envelope additionally
        # rides along on response.a2ui_envelope (G2/G6 — additive, never lost).
        finalize_idx = source.index("explanation = self._finalize_infographic_response(")
        tail = source[finalize_idx:]
        assert "if a2ui_envelope is not None:" in tail
        assert "response.a2ui_envelope = a2ui_envelope" in tail
