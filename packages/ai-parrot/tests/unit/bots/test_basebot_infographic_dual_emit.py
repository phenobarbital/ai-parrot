"""Unit tests for ``BaseBot``'s dual-emit infographic routing (FEAT-527).

Mirrors ``test_pandasagent_infographic.py``'s ``TestPandasAgentDualEmitRouting``:
``BaseBot.ask`` is a single huge method not amenable to direct invocation in a
unit test, so the routing rule is asserted at the source level (same technique
``TestPandasAgentRoutesA2UI`` already uses for the sibling ``PandasAgent.ask``
FEAT-273/470 A2UI-routing regression). ``_finalize_infographic_response`` itself
IS a small, self-independent method, so it is exercised behaviourally.
"""
from __future__ import annotations

import inspect
import sys
from types import SimpleNamespace

import pytest

# Force real modules (same pattern as test_pandasagent_infographic.py).
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


def _make_envelope(**kwargs) -> InfographicRenderResult:
    defaults = dict(
        artifact_id="art-1",
        html_url="https://signed/x",
        html_inline="<html/>",
        template_name="t",
        theme="dark",
        data_variables=["rev"],
        enhanced=False,
        a2ui_envelope={
            "version": "v1.0",
            "createSurface": {"surfaceId": "art-1", "components": []},
        },
    )
    defaults.update(kwargs)
    return InfographicRenderResult(**defaults)


def _base_bot_class():
    try:
        from parrot.bots.base import BaseBot
    except Exception as exc:  # noqa: BLE001 - namespace/Cython worktree layout
        pytest.skip(f"cannot import parrot.bots.base: {exc}")
    return BaseBot


class TestBaseBotFinalizeInfographicResponse:
    """Behavioural tests: ``_finalize_infographic_response`` does not touch
    ``self``, so it can be invoked with any object as the first argument (same
    approach as ``TestFinalizeInfographicResponse`` for ``PandasAgent``).
    """

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
        finalize = _base_bot_class()._finalize_infographic_response
        text = "Revenue grew."
        resp = self._resp(response=text, output=text)
        env = _make_envelope(html_inline="<html>info</html>")

        explanation = finalize(object(), resp, env)

        assert explanation == text
        assert resp.response == text
        assert resp.output == "<html>info</html>"
        assert resp.output_mode == OutputMode.INFOGRAPHIC
        assert resp.artifact_id == "art-1"
        assert resp.metadata["html_url"] == "https://signed/x"


class TestBaseBotDualEmitRouting:
    """Source-level assertions on ``BaseBot.ask``'s infographic post-loop branch."""

    def _ask_source(self) -> str:
        return inspect.getsource(_base_bot_class().ask)

    def test_a2ui_requested_checks_output_mode_before_finalizing(self):
        source = self._ask_source()
        assert "if output_mode == OutputMode.A2UI and a2ui_envelope is not None:" in source

    def test_a2ui_primary_populates_metadata_and_artifact_id(self):
        source = self._ask_source()
        assert "response.artifact_id = infographic_envelope.artifact_id" in source
        assert '"html_url": infographic_envelope.html_url,' in source
        assert '"template_name": infographic_envelope.template_name,' in source

    def test_a2ui_requested_without_envelope_logs_warning_and_falls_back(self):
        source = self._ask_source()
        assert "requested output_mode=A2UI but" in source
        warning_idx = source.index("requested output_mode=A2UI but")
        html_finalize_idx = source.index("self._finalize_infographic_response(response, infographic_envelope)")
        assert warning_idx < html_finalize_idx

    def test_html_primary_still_carries_the_a2ui_envelope(self):
        source = self._ask_source()
        finalize_idx = source.index("self._finalize_infographic_response(response, infographic_envelope)")
        tail = source[finalize_idx:]
        assert "if a2ui_envelope is not None:" in tail
        assert "response.a2ui_envelope = a2ui_envelope" in tail

    def test_finalize_helper_is_imported(self):
        import parrot.bots.base as base_module

        assert hasattr(base_module, "finalize_a2ui_response")
