"""FEAT-611 M5 — BaseBot linked-surface lift, precedence and a2ui_surface_id (spec §4)."""

from __future__ import annotations

import copy
import inspect

import pytest

from parrot.models.basic import ToolCall

INNER = {"surfaceId": "linked-activity", "components": [{"id": "root", "component": "Chart"}], "dataModel": {}}
LINKED_RESULT = {"a2ui_envelope": INNER, "artifacts": [{"type": "a2ui_linked_surface", "surface_id": "linked-activity"}]}


def _base_bot():
    try:
        from parrot.bots.base import BaseBot
    except Exception as exc:  # noqa: BLE001 - same guard as test_basebot_infographic_dual_emit.py:71-76
        pytest.skip(f"cannot import parrot.bots.base: {exc}")
    return BaseBot


def _tc(name: str, result=None, error: str | None = None) -> ToolCall:
    return ToolCall(id=f"call-{name}", name=name, arguments={}, result=result, error=error)


def test_extract_last_linked_surface_result_wraps() -> None:
    extract = _base_bot()._extract_last_linked_surface_result
    assert extract(object(), [_tc("qs_build_linked_surface", LINKED_RESULT)]) == {"version": "v1.0", "createSurface": INNER}


def test_extract_last_linked_surface_result_ignores_non_linked() -> None:
    extract = _base_bot()._extract_last_linked_surface_result
    snapshot = copy.deepcopy(LINKED_RESULT)

    assert extract(object(), []) is None
    assert extract(object(), None) is None
    assert extract(object(), [_tc("t", {"a2ui_envelope": INNER})]) is None
    assert extract(object(), [_tc("t", {"a2ui_envelope": INNER, "artifacts": [{"type": "chart"}]})]) is None
    assert extract(object(), [_tc("qs_build_linked_surface", LINKED_RESULT, error="boom")]) is None
    assert extract(object(), [_tc("t", "not a dict")]) is None
    assert extract(object(), [_tc("t", {"a2ui_envelope": "bare", "artifacts": LINKED_RESULT["artifacts"]})]) is None

    assert extract(object(), [_tc("qs_build_linked_surface", LINKED_RESULT)]) is not None
    assert LINKED_RESULT == snapshot
    assert "version" not in LINKED_RESULT["a2ui_envelope"]


def test_extract_last_linked_surface_result_last_wins() -> None:
    extract = _base_bot()._extract_last_linked_surface_result
    second_inner = dict(INNER, surfaceId="linked-second")
    second = {"a2ui_envelope": second_inner, "artifacts": [{"type": "a2ui_linked_surface", "surface_id": "linked-second"}]}
    got = extract(object(), [_tc("a", LINKED_RESULT), _tc("b", second)])
    assert got == {"version": "v1.0", "createSurface": second_inner}
    # A later errored call does not shadow an earlier successful one.
    got = extract(object(), [_tc("a", LINKED_RESULT), _tc("b", second, error="boom")])
    assert got["createSurface"]["surfaceId"] == "linked-activity"


def test_extract_last_published_surface_id() -> None:
    extract = _base_bot()._extract_last_published_surface_id
    ok = {"surface_id": "srf-1", "kind": "dashboard", "refreshable": True}
    assert extract(object(), [_tc("publish_surface", ok)]) == "srf-1"
    assert extract(object(), [_tc("publish_surface", ok, error="boom")]) is None
    assert extract(object(), [_tc("other_tool", ok)]) is None
    assert extract(object(), [_tc("publish_surface", {"kind": "dashboard"})]) is None
    assert extract(object(), [_tc("publish_surface", {"surface_id": ""})]) is None
    assert extract(object(), None) is None
    later = {"surface_id": "srf-2", "kind": "dashboard", "refreshable": False}
    assert extract(object(), [_tc("publish_surface", ok), _tc("publish_surface", later)]) == "srf-2"


def test_ask_linked_lift_precedence_source_level() -> None:
    """ask() lifts linked only after the interactive and infographic lifts, and never over an existing envelope."""
    source = inspect.getsource(_base_bot().ask)
    infographic_idx = source.index("_extract_last_infographic_result(")
    interactive_idx = source.index("_extract_last_interactive_result(")
    linked_idx = source.index("_extract_last_linked_surface_result(")
    assert interactive_idx < infographic_idx < linked_idx

    guard = source[source.rindex("if (", 0, linked_idx):linked_idx]
    assert "interactive_envelope is None" in guard
    assert "infographic_envelope is None" in guard
    assert 'getattr(response, "a2ui_envelope", None) is None' in guard

    assert '"a2ui_surface_id"' in source
    skip_line = next(
        line for line in source.splitlines() if "interactive_envelope is not None or infographic_envelope is not None" in line
    )
    assert skip_line.strip() == "if interactive_envelope is not None or infographic_envelope is not None:"
    assert "linked_envelope" not in skip_line
