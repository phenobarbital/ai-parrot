"""Tests for RequestContext output-mode fields (FEAT-224, TASK-1486)."""
from __future__ import annotations

from parrot.utils.helpers import RequestContext


def test_new_fields_default_none():
    ctx = RequestContext()
    assert ctx.output_mode is None
    assert ctx.intent_score is None


def test_existing_fields_preserved():
    ctx = RequestContext(user_id="u1", session_id="s1")
    assert ctx.user_id == "u1" and ctx.session_id == "s1"
    assert ctx.kwargs == {}
    assert ctx.request is None and ctx.app is None and ctx.llm is None
