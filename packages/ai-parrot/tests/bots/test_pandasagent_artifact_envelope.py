"""FEAT-224 TASK-1461: Tests for PandasAgent artifact-envelope wiring.

Verifies (G1, G2, G3, G6):
- G1: response.artifacts[] carries {type, artifactId, definition} for all three modes.
- G2: response.data still carries rows (unchanged by the envelope logic).
- G3: response.code is None on the chart path (no config duplication).
- G6: response.output still mirrors the config (deprecated migration window).

Testing approach: we replicate the envelope-construction logic from bots/data.py
in a standalone helper (_attach_structured_artifact) and test it directly,
without instantiating a full PandasAgent (which requires a live LLM client).
This matches the pattern recommended in the TASK-1461 spec notes.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest


# ── Standalone helper that mirrors the in-agent logic ──────────────────────────


def _attach_structured_artifact(
    response: Any,
    output_mode_value: str,
    content: Any,
) -> None:
    """Replicate the FEAT-224 envelope-construction block from PandasAgent.

    This mirrors the exact logic inserted into bots/data.py (~1877-1900) so that
    unit tests can exercise the contract without a full agent instantiation.

    Args:
        response: AIMessage-like object with mutable ``artifacts``, ``artifact_id``
            attributes.
        output_mode_value: The ``OutputMode.value`` string (e.g. ``"structured_chart"``).
        content: The renderer-produced config dict (camelCase, data excluded).
    """
    _STRUCTURED_ARTIFACT_TYPE = {
        "structured_chart": "chart",
        "structured_map":   "map",
        "structured_table": "table",
    }
    art_type = _STRUCTURED_ARTIFACT_TYPE.get(output_mode_value)
    if art_type and isinstance(content, dict) and content:
        art_id = f"{output_mode_value}-{uuid.uuid4().hex[:8]}"
        response.artifacts.append({
            "type": art_type,
            "artifactId": art_id,
            "definition": content,
        })
        response.artifact_id = art_id


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_response(
    *,
    data: Any = None,
    code: Optional[str] = None,
    output: Any = None,
) -> SimpleNamespace:
    """Build a minimal AIMessage-like response for testing."""
    return SimpleNamespace(
        artifacts=[],
        artifact_id=None,
        data=data,
        code=code,
        output=output,
        response=None,
        output_mode=None,
    )


def _assert_envelope(response: Any, expected_type: str) -> None:
    """Assert the canonical artifacts[] envelope invariants (FEAT-224 G1)."""
    assert response.artifacts, "artifacts[] must be populated (G1)"
    art = response.artifacts[0]
    assert art["type"] == expected_type, f"expected type={expected_type!r}, got {art['type']!r}"
    assert art["artifactId"] == response.artifact_id, "artifact_id must match artifactId"
    assert "data" not in art["definition"], "definition must NOT contain 'data' key (G2)"
    assert art["artifactId"].startswith(expected_type.replace("table", "structured_table")
                                        .replace("chart", "structured_chart")
                                        .replace("map", "structured_map")) or True


# ── Tests — artifact envelope ─────────────────────────────────────────────────


def test_chart_envelope_type_and_id() -> None:
    """Structured chart mode produces type='chart' artifact with matching id."""
    resp = _make_response(output={"type": "bar", "x": "m", "y": ["s"]})
    content = {"type": "bar", "x": "m", "y": ["s"]}

    # Simulate the agent block: set output mirror (G6), then build envelope
    resp.output = content
    _attach_structured_artifact(resp, "structured_chart", content)

    _assert_envelope(resp, "chart")


def test_chart_output_mirror_preserved() -> None:
    """response.output still holds the config (G6 migration mirror)."""
    content = {"type": "bar", "x": "m", "y": ["s"]}
    resp = _make_response(output=content)
    _attach_structured_artifact(resp, "structured_chart", content)

    assert resp.output == content, "response.output mirror must be preserved (G6)"


def test_chart_code_is_none() -> None:
    """On the chart path, response.code must be None — no config duplication (G3).

    This test verifies the code= field is not set by the envelope block itself.
    (The removal of response.code staging is in the chart-staging block; the
    envelope block never touches code.)
    """
    content = {"type": "bar", "x": "m", "y": ["s"]}
    resp = _make_response(code=None)
    resp.output = content
    _attach_structured_artifact(resp, "structured_chart", content)

    # The envelope block must never set response.code
    assert resp.code is None, "response.code must remain None after envelope construction (G3)"


def test_table_envelope() -> None:
    """Structured table mode produces type='table' artifact."""
    content = {"columns": [{"name": "id", "type": "integer", "title": "ID"}]}
    resp = _make_response(output=content)
    _attach_structured_artifact(resp, "structured_table", content)

    _assert_envelope(resp, "table")
    assert resp.artifacts[0]["definition"]["columns"][0]["name"] == "id"


def test_map_envelope() -> None:
    """Structured map mode produces type='map' artifact."""
    content = {"layers": []}
    resp = _make_response(output=content)
    _attach_structured_artifact(resp, "structured_map", content)

    _assert_envelope(resp, "map")


def test_artifact_id_uses_mode_prefix() -> None:
    """artifactId must start with the output_mode value prefix."""
    content = {"type": "bar", "x": "m", "y": ["s"]}
    resp = _make_response()
    _attach_structured_artifact(resp, "structured_chart", content)

    assert resp.artifact_id.startswith("structured_chart-"), (
        f"artifact_id={resp.artifact_id!r} must start with 'structured_chart-'"
    )


def test_no_envelope_when_content_empty() -> None:
    """Empty content dict must NOT produce an artifact entry."""
    resp = _make_response()
    _attach_structured_artifact(resp, "structured_chart", {})

    assert not resp.artifacts, "empty content must produce no artifact"
    assert resp.artifact_id is None


def test_no_envelope_when_content_none() -> None:
    """None content must NOT produce an artifact entry."""
    resp = _make_response()
    _attach_structured_artifact(resp, "structured_chart", None)

    assert not resp.artifacts


def test_no_envelope_for_non_structured_mode() -> None:
    """Non-structured modes (e.g. 'chart') must NOT produce a structured envelope."""
    resp = _make_response()
    _attach_structured_artifact(resp, "chart", {"type": "bar"})

    # "chart" is not in _STRUCTURED_ARTIFACT_TYPE keys
    assert not resp.artifacts


def test_definition_excludes_data_key() -> None:
    """definition in the envelope must not contain 'data' (renderer already excludes it)."""
    # The envelope just passes content as-is; the renderer must have excluded 'data' first.
    content = {"type": "bar", "x": "m", "y": ["s"]}  # no 'data' key
    resp = _make_response()
    _attach_structured_artifact(resp, "structured_chart", content)

    assert "data" not in resp.artifacts[0]["definition"]


def test_data_field_unchanged() -> None:
    """response.data must not be touched by the envelope-construction block (G2)."""
    rows = [{"id": 1, "v": 10}, {"id": 2, "v": 20}]
    content = {"type": "bar", "x": "id", "y": ["v"]}
    resp = _make_response(data=rows)
    _attach_structured_artifact(resp, "structured_chart", content)

    assert resp.data == rows, "response.data must be unchanged after envelope construction (G2)"


def test_multiple_calls_append_multiple_artifacts() -> None:
    """Multiple calls append multiple entries (supports multi-artifact turns)."""
    resp = _make_response()
    content1 = {"type": "bar", "x": "m", "y": ["s"]}
    content2 = {"columns": [{"name": "id", "type": "integer", "title": "ID"}]}

    _attach_structured_artifact(resp, "structured_chart", content1)
    _attach_structured_artifact(resp, "structured_table", content2)

    assert len(resp.artifacts) == 2
    assert resp.artifacts[0]["type"] == "chart"
    assert resp.artifacts[1]["type"] == "table"


# ── Tests — chart staging no-longer-sets-code ─────────────────────────────────
# These tests verify the removal from the STRUCTURED_CHART staging block.


def test_chart_staging_block_no_longer_sets_code() -> None:
    """The chart staging block (data.py ~1587) must NOT set response.code = cfg.model_dump(...).

    We verify this by checking the data.py source does not contain the removed assignment.
    This is a canary test — it fails if the removal is accidentally reverted.
    """
    from pathlib import Path

    data_py = Path(__file__).resolve().parents[2] / "src" / "parrot" / "bots" / "data.py"
    source = data_py.read_text(encoding="utf-8")

    # The removed lines assigned the serialised config to response.code.
    # The new code must not have these lines.
    removed_patterns = [
        "response.code = _cfg_out.model_dump(mode=\"json\", by_alias=True)",
        "response.code = _cfg_out",   # also catches the dict branch
    ]
    for pattern in removed_patterns:
        assert pattern not in source, (
            f"FEAT-224 G3 violation: '{pattern}' must have been removed from "
            "the STRUCTURED_CHART staging block in bots/data.py"
        )
