"""Unit tests for AgentTalk._extract_infographic_explanation (FEAT-197).

The infographic post-loop branch in PandasAgent returns early and bypasses
the formatter, so the LLM's narrative explanation survives only on
``response.response`` / ``response.content``.  ``_format_infographic_response``
must surface it in the envelope's ``response`` field; this helper extracts it
(unwrapping raw ``{"explanation": ...}`` structured-output JSON when present).
"""
from __future__ import annotations

from types import SimpleNamespace

from parrot.handlers.agent import AgentTalk


_extract = AgentTalk._extract_infographic_explanation


def test_prefers_response_attribute():
    msg = SimpleNamespace(response="Computed the KPIs.", content="raw")
    assert _extract(msg) == "Computed the KPIs."


def test_falls_back_to_content():
    msg = SimpleNamespace(response=None, content="Fallback narrative.")
    assert _extract(msg) == "Fallback narrative."


def test_unwraps_structured_json_explanation():
    raw = '{"explanation": "I have successfully computed the daily KPIs."}'
    msg = SimpleNamespace(response=raw, content=None)
    assert _extract(msg) == "I have successfully computed the daily KPIs."


def test_returns_raw_on_unparseable_json():
    raw = '{"explanation": broken'
    msg = SimpleNamespace(response=raw, content=None)
    assert _extract(msg) == raw


def test_empty_when_nothing_present():
    msg = SimpleNamespace(response=None, content=None)
    assert _extract(msg) == ""


def test_non_string_coerced_to_str():
    msg = SimpleNamespace(response=12345, content=None)
    assert _extract(msg) == "12345"
