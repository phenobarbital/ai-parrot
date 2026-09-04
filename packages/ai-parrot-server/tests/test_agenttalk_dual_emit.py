"""Unit tests for ``AgentTalk`` dual-emit envelopes (FEAT-527).

Covers the two additive changes on top of the documented shapes (spec §1
G2/G6, §2 Overview step 3):

- ``_format_infographic_response`` (the INFOGRAPHIC JSON envelope) gains an
  ``a2ui_envelope`` key, present only when the response carries one.
- The ``OutputMode.A2UI`` early return in ``_format_response`` gains
  ``metadata`` (with ``html_url`` when set) and ``artifact_id``.

Unit-level, no aiohttp server — same style as
``test_agenttalk_infographic_explanation.py``: the handler is constructed via
``__new__`` and ``self.request`` is a minimal stub exposing ``.headers`` and
``.query`` (only what ``_format_infographic_response`` reads).
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from parrot.handlers.agent import AgentTalk
from parrot.models.outputs import OutputMode


def _handler() -> AgentTalk:
    h = AgentTalk.__new__(AgentTalk)
    h.logger = logging.getLogger("test.agenttalk_dual_emit")
    h._request = SimpleNamespace(headers={}, query={})
    return h


def _a2ui_envelope(surface_id: str = "infographic-abc123") -> dict:
    return {
        "version": "v1.0",
        "createSurface": {"surfaceId": surface_id, "components": []},
    }


def _infographic_response(**overrides) -> SimpleNamespace:
    defaults = dict(
        input="Render Q3 variance",
        output="<html>Q3 report</html>",
        response="Revenue grew 5% QoQ.",
        artifact_id="infographic-abc123",
        data=None,
        metadata={
            "html_url": "https://signed/infographic-abc123.html",
            "html_inline_omitted": False,
            "enhanced": False,
            "template_name": "financial_variance",
            "theme": "corporate",
        },
        model="test-model",
        provider="test",
        session_id="sess-1",
        turn_id="turn-1",
        a2ui_envelope=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# _format_infographic_response — a2ui_envelope additive key
# ---------------------------------------------------------------------------

class TestInfographicEnvelopeIncludesA2UI:
    def test_a2ui_envelope_present_when_response_carries_one(self):
        handler = _handler()
        response = _infographic_response(a2ui_envelope=_a2ui_envelope())

        resp = handler._format_infographic_response(response=response, format_kwargs={})
        body = json.loads(resp.text)

        assert body["output_mode"] == "infographic"
        assert body["a2ui_envelope"]["version"] == "v1.0"
        assert body["a2ui_envelope"]["createSurface"]["surfaceId"] == "infographic-abc123"
        # Byte-identical body otherwise: every previously documented key intact.
        assert set(body) >= {
            "input", "output", "response", "output_mode", "artifact_id",
            "data", "metadata", "sources", "tool_calls", "a2ui_envelope",
        }

    def test_a2ui_envelope_omitted_when_none(self):
        handler = _handler()
        response = _infographic_response(a2ui_envelope=None)

        resp = handler._format_infographic_response(response=response, format_kwargs={})
        body = json.loads(resp.text)

        assert "a2ui_envelope" not in body
        assert body["output_mode"] == "infographic"

    def test_html_accept_body_and_shape_unchanged(self):
        handler = _handler()
        handler._request = SimpleNamespace(headers={"Accept": "text/html"}, query={})
        response = _infographic_response(a2ui_envelope=_a2ui_envelope())

        resp = handler._format_infographic_response(response=response, format_kwargs={})

        assert resp.content_type == "text/html"
        assert resp.text == "<html>Q3 report</html>"


# ---------------------------------------------------------------------------
# OutputMode.A2UI early return — metadata + artifact_id additive keys
# ---------------------------------------------------------------------------

class TestA2UIReturnCarriesHtmlMetadata:
    def test_a2ui_return_includes_metadata_and_artifact_id(self):
        handler = _handler()
        handler.json_response = MagicMock(side_effect=lambda body: SimpleNamespace(body=body))

        response = SimpleNamespace(
            output_mode=OutputMode.A2UI,
            input="Render as A2UI",
            response="Here is your dashboard.",
            a2ui_envelope=_a2ui_envelope(),
            artifact_id="infographic-abc123",
            metadata={"html_url": "https://signed/infographic-abc123.html"},
            model="test-model",
            provider="test",
            session_id="sess-1",
            turn_id="turn-1",
        )

        result = handler._format_response(
            response=response,
            format_kwargs={},
            output_format="json",
            response_time_ms=42,
        )

        body = result.body
        assert body["a2ui_envelope"]["version"] == "v1.0"
        assert body["artifact_id"] == "infographic-abc123"
        assert body["metadata"]["html_url"] == "https://signed/infographic-abc123.html"
        assert body["metadata"]["response_time"] == 42
        # Existing four keys intact.
        assert set(body) >= {"input", "output", "output_mode", "a2ui_envelope"}

    def test_a2ui_return_metadata_defaults_to_empty_dict(self):
        handler = _handler()
        handler.json_response = MagicMock(side_effect=lambda body: SimpleNamespace(body=body))

        response = SimpleNamespace(
            output_mode=OutputMode.A2UI,
            input="Render as A2UI",
            response="Here is your dashboard.",
            a2ui_envelope=_a2ui_envelope(),
            artifact_id=None,
            metadata=None,
            model=None,
            provider=None,
            session_id=None,
            turn_id=None,
        )

        result = handler._format_response(
            response=response, format_kwargs={}, output_format="json",
        )

        assert result.body["artifact_id"] is None
        assert result.body["metadata"]["session_id"] == ""


# ---------------------------------------------------------------------------
# Streaming gate (unchanged — regression guard)
# ---------------------------------------------------------------------------

class TestStreamingGateUnchangedForInfographic:
    def test_infographic_and_interactive_force_stream_off(self):
        import inspect

        source = inspect.getsource(AgentTalk)
        assert (
            "if output_mode in (OutputMode.INFOGRAPHIC, OutputMode.INTERACTIVE):" in source
            or "OutputMode.INFOGRAPHIC, OutputMode.INTERACTIVE" in source
        )
