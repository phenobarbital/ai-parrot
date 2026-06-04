"""FEAT-224 TASK-1462: Unit tests for the FEAT-103 auto-save alignment with the
structured artifact envelope.

Verifies (G5):
- structured_chart → persists definition (config, not rows), artifact_type=CHART
- structured_table → persists definition (config), artifact_type=TABLE
- structured_map   → persists definition (config), artifact_type=MAP
- artifact_id reuses the agent-minted id from response.artifact_id
- legacy chart/dataframe/export path still fires (no regression)
- modes with no artifacts → no save call

Testing approach: replicate the auto-save branch logic in a standalone helper
(mirroring the pattern in TASK-1461 tests) so we can drive it without a full
aiohttp server.  A _FakeStore captures save_artifact() calls.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest


# ── Fake store ────────────────────────────────────────────────────────────────


class _FakeStore:
    """Captures save_artifact() calls without a real DB."""

    def __init__(self) -> None:
        self.saved: List[Any] = []

    async def save_artifact(self, *, user_id: str, agent_id: str, session_id: str, artifact: Any) -> None:
        """Record the saved artifact."""
        self.saved.append(artifact)


# ── Standalone helper that mirrors the auto-save logic from agent.py ──────────


async def _run_autosave(
    *,
    output_mode: str,
    artifacts: Optional[List[Dict]] = None,
    artifact_id: Optional[str] = None,
    data: Any = None,
    store: Optional[_FakeStore] = None,
) -> _FakeStore:
    """Drive the FEAT-224 auto-save branch in isolation.

    Replicates the extended FEAT-103 auto-save block from
    agent.py (~2667-2765) as a standalone coroutine so tests can run without
    a full aiohttp handler.

    Args:
        output_mode: The AIMessage output_mode string value.
        artifacts: The response.artifacts list (may be empty/None).
        artifact_id: The response.artifact_id (from agent-minted envelope).
        data: The response.data (rows, present on legacy path).
        store: Optional pre-constructed fake store (a new one is created if not given).

    Returns:
        The _FakeStore with all captured save_artifact() calls.
    """
    if store is None:
        store = _FakeStore()

    response = SimpleNamespace(
        artifacts=artifacts or [],
        artifact_id=artifact_id,
        data=data,
        input="test query",
    )

    client_message_id = "msg-test-001"
    user_id = "user-1"
    session_id = "session-1"
    agent_name = "test-agent"

    from datetime import datetime as _dt, timezone as _tz
    from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator
    import uuid as _uuid

    _legacy_type_map = {
        'chart': ArtifactType.CHART,
        'dataframe': ArtifactType.DATAFRAME,
        'export': ArtifactType.EXPORT,
    }
    _structured_type_map = {
        'structured_chart': ArtifactType.CHART,
        'structured_map':   ArtifactType.MAP,
        'structured_table': ArtifactType.TABLE,
    }
    _type_map = {**_legacy_type_map, **_structured_type_map}

    _is_structured = output_mode in _structured_type_map
    _is_legacy = (
        output_mode in _legacy_type_map
        and response.data is not None
    )

    if _is_structured and getattr(response, 'artifacts', None):
        _env = next(
            (a for a in response.artifacts if a.get("definition")),
            None,
        )
        if _env is not None:
            _now = _dt.now(_tz.utc)
            _art_id = (
                getattr(response, 'artifact_id', None)
                or _env.get("artifactId")
                or f"{output_mode}-{_uuid.uuid4().hex[:8]}"
            )
            _definition = _env["definition"]
            _atype = _structured_type_map[output_mode]
            _artifact = Artifact(
                artifact_id=_art_id,
                artifact_type=_atype,
                title=f"{output_mode.title()} — {(getattr(response, 'input', None) or '')[:60]}",
                created_at=_now,
                updated_at=_now,
                source_turn_id=client_message_id,
                created_by=ArtifactCreator.AGENT,
                definition=_definition,
            )
            await store.save_artifact(
                user_id=user_id,
                agent_id=agent_name,
                session_id=session_id,
                artifact=_artifact,
            )

    elif _is_legacy:
        _now = _dt.now(_tz.utc)
        _art_id = f"{output_mode}-{_uuid.uuid4().hex[:8]}"
        _definition = (
            response.data if isinstance(response.data, dict)
            else {"raw": str(response.data)[:10000]}
        )
        _artifact = Artifact(
            artifact_id=_art_id,
            artifact_type=_type_map.get(output_mode, ArtifactType.EXPORT),
            title=f"{output_mode.title()} — {(getattr(response, 'input', None) or '')[:60]}",
            created_at=_now,
            updated_at=_now,
            source_turn_id=client_message_id,
            created_by=ArtifactCreator.AGENT,
            definition=_definition,
        )
        await store.save_artifact(
            user_id=user_id,
            agent_id=agent_name,
            session_id=session_id,
            artifact=_artifact,
        )

    return store


# ── Tests — structured modes ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_structured_chart_persists_definition_not_data() -> None:
    """structured_chart: persists envelope definition (config), not response.data (rows)."""
    store = await _run_autosave(
        output_mode="structured_chart",
        artifacts=[{
            "type": "chart",
            "artifactId": "structured_chart-abc12345",
            "definition": {"type": "bar", "x": "m", "y": ["s"]},
        }],
        artifact_id="structured_chart-abc12345",
        data=[{"m": "Jan", "s": 1}],  # rows — must NOT be persisted as definition
    )
    assert len(store.saved) == 1
    art = store.saved[0]
    assert art.artifact_type.value == "chart"
    assert art.definition == {"type": "bar", "x": "m", "y": ["s"]}  # config, NOT rows


@pytest.mark.asyncio
async def test_structured_chart_reuses_artifact_id() -> None:
    """artifact_id must be reused from response.artifact_id (not newly minted)."""
    store = await _run_autosave(
        output_mode="structured_chart",
        artifacts=[{
            "type": "chart",
            "artifactId": "structured_chart-abc12345",
            "definition": {"type": "bar", "x": "m", "y": ["s"]},
        }],
        artifact_id="structured_chart-abc12345",
    )
    assert store.saved[0].artifact_id == "structured_chart-abc12345"


@pytest.mark.asyncio
async def test_structured_table_maps_to_table_type() -> None:
    """structured_table: artifact_type must be TABLE."""
    store = await _run_autosave(
        output_mode="structured_table",
        artifacts=[{
            "type": "table",
            "artifactId": "structured_table-def67890",
            "definition": {"columns": [{"name": "id", "type": "integer", "title": "ID"}]},
        }],
        artifact_id="structured_table-def67890",
        data=[{"id": 1}],
    )
    assert store.saved[0].artifact_type.value == "table"
    assert store.saved[0].artifact_id == "structured_table-def67890"
    assert "columns" in store.saved[0].definition


@pytest.mark.asyncio
async def test_structured_map_maps_to_map_type() -> None:
    """structured_map: artifact_type must be MAP."""
    store = await _run_autosave(
        output_mode="structured_map",
        artifacts=[{
            "type": "map",
            "artifactId": "structured_map-ghi11111",
            "definition": {"layers": []},
        }],
        artifact_id="structured_map-ghi11111",
    )
    assert store.saved[0].artifact_type.value == "map"


@pytest.mark.asyncio
async def test_structured_chart_definition_not_rows() -> None:
    """Even when response.data has rows, the persisted definition is the config."""
    config = {"type": "line", "x": "date", "y": ["revenue"]}
    rows = [{"date": "2026-01", "revenue": 1000}, {"date": "2026-02", "revenue": 2000}]
    store = await _run_autosave(
        output_mode="structured_chart",
        artifacts=[{"type": "chart", "artifactId": "chart-id", "definition": config}],
        artifact_id="chart-id",
        data=rows,
    )
    assert store.saved[0].definition == config
    assert store.saved[0].definition != rows


# ── Tests — no artifact persisted when no envelope ────────────────────────────


@pytest.mark.asyncio
async def test_no_save_when_structured_but_no_artifacts() -> None:
    """structured_chart with empty artifacts list → no save call."""
    store = await _run_autosave(
        output_mode="structured_chart",
        artifacts=[],  # empty
        artifact_id=None,
        data=[{"m": "Jan", "s": 1}],
    )
    assert not store.saved


@pytest.mark.asyncio
async def test_no_save_for_default_mode() -> None:
    """DEFAULT output_mode must not trigger any save."""
    store = await _run_autosave(
        output_mode="default",
        artifacts=[],
        data=[{"id": 1}],
    )
    assert not store.saved


# ── Tests — legacy path unchanged ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_chart_mode_still_fires() -> None:
    """Legacy 'chart' mode (non-structured) must still fire with response.data."""
    data = {"series": [1, 2, 3]}
    store = await _run_autosave(
        output_mode="chart",
        data=data,
    )
    assert len(store.saved) == 1
    art = store.saved[0]
    assert art.artifact_type.value == "chart"
    assert art.definition == data


@pytest.mark.asyncio
async def test_legacy_dataframe_mode_fires() -> None:
    """Legacy 'dataframe' mode must still fire with response.data (as raw str)."""
    store = await _run_autosave(
        output_mode="dataframe",
        data=[{"id": 1}, {"id": 2}],
    )
    assert len(store.saved) == 1
    assert store.saved[0].artifact_type.value == "dataframe"


@pytest.mark.asyncio
async def test_legacy_chart_no_data_no_save() -> None:
    """Legacy 'chart' with data=None must NOT trigger a save."""
    store = await _run_autosave(
        output_mode="chart",
        data=None,
    )
    assert not store.saved


# ── Canary: verify agent.py block uses new structured paths ───────────────────


def test_handler_autosave_contains_structured_type_map() -> None:
    """Canary: agent.py auto-save block must contain the structured type map."""
    from pathlib import Path
    agent_py = (
        Path(__file__).resolve().parents[2]
        / "src" / "parrot" / "handlers" / "agent.py"
    )
    source = agent_py.read_text(encoding="utf-8")

    assert "structured_chart" in source and "_structured_type_map" in source, (
        "FEAT-224 G5: agent.py must contain the _structured_type_map in auto-save block"
    )
    assert "ArtifactType.TABLE" in source, (
        "FEAT-224 G5: ArtifactType.TABLE must appear in auto-save block"
    )
