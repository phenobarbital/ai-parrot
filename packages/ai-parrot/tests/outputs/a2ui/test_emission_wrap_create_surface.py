"""FEAT-611 M5 / §9 S1 — finalize_a2ui_response normalizes bare CreateSurface dumps to the v1.0 wrapper."""

from __future__ import annotations

from types import SimpleNamespace

from parrot.models.outputs import OutputMode
from parrot.outputs.a2ui.emission import _wrap_create_surface, finalize_a2ui_response

BARE = {"surfaceId": "linked-activity", "components": [{"id": "root", "component": "Chart"}], "dataModel": {}}
WRAPPED = {"version": "v1.0", "createSurface": BARE}


def _resp(**kwargs) -> SimpleNamespace:
    defaults = dict(a2ui_envelope=None, output=None, response=None, output_mode=OutputMode.DEFAULT)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_wrap_bare_create_surface() -> None:
    assert _wrap_create_surface(BARE) == WRAPPED


def test_wrap_is_idempotent() -> None:
    assert _wrap_create_surface(WRAPPED) == WRAPPED
    assert _wrap_create_surface(WRAPPED) is WRAPPED
    assert _wrap_create_surface(_wrap_create_surface(BARE)) == WRAPPED


def test_wrap_leaves_non_create_surface_untouched() -> None:
    assert _wrap_create_surface(None) is None
    sobres = [WRAPPED]
    assert _wrap_create_surface(sobres) is sobres
    legacy_a = {"surfaceId": "s"}
    legacy_b = {"messageType": "createSurface", "surfaceId": "main"}
    assert _wrap_create_surface(legacy_a) is legacy_a
    assert _wrap_create_surface(legacy_b) is legacy_b


def test_wrap_does_not_mutate_input() -> None:
    bare = dict(BARE)
    wrapped = _wrap_create_surface(bare)
    assert bare == BARE
    assert "version" not in bare
    assert wrapped["createSurface"] is bare


def test_finalize_wraps_bare_create_surface_direct_output() -> None:
    """Direct output: the LLM/structured path put a bare CreateSurface dict in response.output."""
    resp = _resp(output=dict(BARE))
    finalize_a2ui_response(resp)
    assert resp.a2ui_envelope == WRAPPED
    assert resp.output_mode == OutputMode.A2UI
    assert "linked-activity" in resp.response


def test_finalize_wraps_bare_create_surface_tool_loop_output() -> None:
    """Tool-loop output: ask() pre-set response.a2ui_envelope from a tool result."""
    resp = _resp(a2ui_envelope=dict(BARE), output="prose")
    finalize_a2ui_response(resp)
    assert resp.a2ui_envelope == WRAPPED
    assert resp.output == "prose"
    assert resp.output_mode == OutputMode.A2UI


def test_finalize_non_a2ui_output_unchanged() -> None:
    """Non-A2UI output: a string output / non-surface dict passes through verbatim."""
    resp = _resp(output="plain text")
    finalize_a2ui_response(resp)
    assert resp.a2ui_envelope is None
    assert resp.output == "plain text"

    resp2 = _resp(output={"rows": [1]})
    finalize_a2ui_response(resp2)
    assert resp2.a2ui_envelope == {"rows": [1]}
