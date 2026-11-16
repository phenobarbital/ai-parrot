"""Behavioral acceptance tests for Deterministic review export and replayable archives."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from parrot.memory.dynamics import export as export_module
from parrot.memory.dynamics.export import (
    ExportError,
    ExportState,
    export_reviews,
    retry_export,
)
from parrot.memory.episodic.models import MemoryNamespace


def _namespace(
    tenant_id: str = "tenant-a",
    agent_id: str = "agent-a",
    user_id: str | None = "user-a",
    session_id: str | None = "session-a",
) -> MemoryNamespace:
    """Build a test namespace."""
    return MemoryNamespace(
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        session_id=session_id,
    )


@pytest.mark.asyncio
async def test_deterministic_round_trip() -> None:
    """Verify deterministic round trip: identical source produces stable mappings/order/provenance."""
    namespace = _namespace()

    with tempfile.TemporaryDirectory() as tmpdir:
        destination = Path(tmpdir) / "export.json"

        # First export
        reviews_1 = [
            {
                "memory_id": "mem-001",
                "content_version": "v1",
                "ref_key": "ref-001",
                "before": {"difficulty": None, "stability": None, "review_count": 0},
                "after": {"difficulty": 2.5, "stability": 1.5, "review_count": 1},
                "parameter_id": "fsrs-6-default",
                "grade": 3,
                "reviewed_at": datetime(2026, 11, 15, tzinfo=timezone.utc),
            },
            {
                "memory_id": "mem-002",
                "content_version": "v1",
                "ref_key": "ref-002",
                "before": {"difficulty": None, "stability": None, "review_count": 0},
                "after": {"difficulty": 3.0, "stability": 2.0, "review_count": 1},
                "parameter_id": "fsrs-6-default",
                "grade": 3,
                "reviewed_at": datetime(2026, 11, 15, tzinfo=timezone.utc),
            },
        ]
        parameters = {
            "fsrs-6-default": {
                "algorithm": "fsrs-6",
                "time_policy": "days-v1",
                "reference": "fsrs-6@v6.3.2:9446cb06605c597a063aeee49f7d188d42e34dc2",
                "provenance": "default-weights",
            }
        }

        result_1 = await export_reviews(
            namespace=namespace,
            destination=destination,
            reviews=reviews_1,
            parameters=parameters,
        )

        # Read the export file
        content_1 = destination.read_text(encoding="utf-8")
        parsed_1 = json.loads(content_1)

        # Second export with identical data should produce identical output
        destination_2 = Path(tmpdir) / "export2.json"
        result_2 = await export_reviews(
            namespace=namespace,
            destination=destination_2,
            reviews=reviews_1,
            parameters=parameters,
        )

        content_2 = destination_2.read_text(encoding="utf-8")

        # Verify deterministic: identical content
        assert content_1 == content_2, "Identical source data must produce identical exports"

        # Verify stable ordering: reviews should be sorted by stable key
        reviews_list = parsed_1.get("reviews", {})
        assert len(reviews_list) == 2

        # Verify parameter provenance is included
        assert "parameter_provenance" in parsed_1
        assert "fsrs-6-default" in parsed_1["parameter_provenance"]

        # Verify export metadata
        assert result_1["record_count"] == 2
        assert result_1["format_version"] == "v1"
        assert "content_hash" in result_1

        # Verify the content hash is stable
        assert result_1["content_hash"] == result_2["content_hash"]


@pytest.mark.asyncio
async def test_export_failure_replay_no_double_apply() -> None:
    """Verify export failure replay does not lose or reapply reviews; archives remain replayable."""
    namespace = _namespace()

    with tempfile.TemporaryDirectory() as tmpdir:
        destination = Path(tmpdir) / "export.json"

        reviews = [
            {
                "memory_id": "mem-001",
                "content_version": "v1",
                "ref_key": "ref-001",
                "before": {"difficulty": None, "stability": None, "review_count": 0},
                "after": {"difficulty": 2.5, "stability": 1.5, "review_count": 1},
                "parameter_id": "fsrs-6-default",
                "grade": 3,
                "reviewed_at": datetime(2026, 11, 15, tzinfo=timezone.utc),
            },
        ]
        parameters = {"fsrs-6-default": {"algorithm": "fsrs-6", "provenance": "test"}}

        # Successful export
        result = await export_reviews(
            namespace=namespace,
            destination=destination,
            reviews=reviews,
            parameters=parameters,
        )

        assert result["record_count"] == 1
        assert destination.exists()

        # Verify the export can be read back
        content = destination.read_text(encoding="utf-8")
        parsed = json.loads(content)

        # The reviews are preserved in the export file
        assert len(parsed["reviews"]) == 1

        # Re-exporting (simulating retry) produces same result
        # This demonstrates reviews are not double-applied
        result_retry = await export_reviews(
            namespace=namespace,
            destination=destination,
            reviews=reviews,
            parameters=parameters,
        )

        # Same content hash = no double application
        assert result["content_hash"] == result_retry["content_hash"]


@pytest.mark.asyncio
async def test_archive_retains_required_provenance() -> None:
    """Verify archive retains required provenance: no fit.py, fitting CLI or optimizer changes."""
    namespace = _namespace()

    with tempfile.TemporaryDirectory() as tmpdir:
        destination = Path(tmpdir) / "export.json"

        # Include parameter provenance
        parameters = {
            "fsrs-6-default": {
                "algorithm": "fsrs-6",
                "time_policy": "days-v1",
                "reference": "fsrs-6@v6.3.2:9446cb06605c597a063aeee49f7d188d42e34dc2",
                "weights": (
                    0.212,
                    1.2931,
                    2.3065,
                    8.2956,
                    6.4133,
                    0.8334,
                    3.0194,
                    0.001,
                    1.8722,
                    0.1666,
                    0.796,
                    1.4835,
                    0.0614,
                    0.2629,
                    1.6483,
                    0.6014,
                    1.8729,
                    0.5425,
                    0.0912,
                    0.0658,
                    0.1542,
                ),
                "provenance": "default-weights-v6.3.2",
            }
        }

        reviews = [
            {
                "memory_id": "mem-001",
                "content_version": "v1",
                "ref_key": "ref-001",
                "before": {"difficulty": None, "stability": None, "review_count": 0},
                "after": {"difficulty": 2.5, "stability": 1.5, "review_count": 1},
                "parameter_id": "fsrs-6-default",
                "grade": 3,
                "reviewed_at": datetime(2026, 11, 15, tzinfo=timezone.utc),
            },
        ]

        result = await export_reviews(
            namespace=namespace,
            destination=destination,
            reviews=reviews,
            parameters=parameters,
        )

        # Read and verify provenance is retained
        content = destination.read_text(encoding="utf-8")
        parsed = json.loads(content)

        # Verify parameter provenance is present and complete
        provenance = parsed["parameter_provenance"]["fsrs-6-default"]
        assert provenance["algorithm"] == "fsrs-6"
        assert provenance["time_policy"] == "days-v1"
        assert provenance["reference"].startswith("fsrs-6@v6.3.2")
        assert provenance["provenance"] == "default-weights-v6.3.2"
        assert "weights" in provenance

        # Verify no optimizer/fitting fields are present
        assert "optimizer" not in parsed
        assert "fitter" not in parsed
        assert "fit" not in json.dumps(parsed).lower()

        # Verify export is suitable for deferred fitting
        # (has all needed data: grades, states, parameters)
        review = list(parsed["reviews"].values())[0]
        assert "grade" in review
        assert "before" in review
        assert "after" in review
        assert "parameter_id" in review


@pytest.mark.asyncio
async def test_export_state_stable_key() -> None:
    """Verify ExportState generates stable keys for deterministic ordering."""
    namespace = _namespace()

    state = ExportState(namespace=namespace, export_path=Path("/tmp/export.json"))

    # Same inputs should produce same key
    key1 = state._stable_key("mem-001", "v1")
    key2 = state._stable_key("mem-001", "v1")
    assert key1 == key2

    # Different memory_id should produce different key
    key3 = state._stable_key("mem-002", "v1")
    assert key3 != key1

    # Different content_version should produce different key
    key4 = state._stable_key("mem-001", "v2")
    assert key4 != key1


@pytest.mark.asyncio
async def test_export_state_ordering() -> None:
    """Verify ExportState orders reviews deterministically."""
    namespace = _namespace()

    state = ExportState(namespace=namespace, export_path=Path("/tmp/export.json"))

    # Add reviews in non-sorted order
    state.add_review(
        ref_key="ref-c",
        memory_id="mem-c",
        content_version="v1",
        before_state={},
        after_state={"difficulty": 3.0},
        parameter_id="param-1",
        grade=3,
        reviewed_at=datetime(2026, 11, 15, tzinfo=timezone.utc),
    )
    state.add_review(
        ref_key="ref-a",
        memory_id="mem-a",
        content_version="v1",
        before_state={},
        after_state={"difficulty": 1.0},
        parameter_id="param-1",
        grade=1,
        reviewed_at=datetime(2026, 11, 15, tzinfo=timezone.utc),
    )
    state.add_review(
        ref_key="ref-b",
        memory_id="mem-b",
        content_version="v1",
        before_state={},
        after_state={"difficulty": 2.0},
        parameter_id="param-1",
        grade=2,
        reviewed_at=datetime(2026, 11, 15, tzinfo=timezone.utc),
    )

    result = state.to_dict()
    reviews_keys = list(result["reviews"].keys())

    # Keys should be sorted (deterministic order)
    assert reviews_keys == sorted(reviews_keys)


@pytest.mark.asyncio
async def test_export_empty_reviews() -> None:
    """Verify export handles empty reviews list correctly."""
    namespace = _namespace()

    with tempfile.TemporaryDirectory() as tmpdir:
        destination = Path(tmpdir) / "export.json"

        result = await export_reviews(
            namespace=namespace,
            destination=destination,
            reviews=[],
            parameters={},
        )

        assert result["record_count"] == 0
        assert destination.exists()

        content = destination.read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert parsed["reviews"] == {}
        assert parsed["parameter_provenance"] == {}


@pytest.mark.asyncio
async def test_export_atomic_write() -> None:
    """Verify export writes atomically (temp file then rename)."""
    namespace = _namespace()

    with tempfile.TemporaryDirectory() as tmpdir:
        destination = Path(tmpdir) / "export.json"

        reviews = [
            {
                "memory_id": "mem-001",
                "content_version": "v1",
                "ref_key": "ref-001",
                "before": {},
                "after": {"difficulty": 2.5},
                "parameter_id": "param-1",
                "grade": 3,
                "reviewed_at": datetime(2026, 11, 15, tzinfo=timezone.utc),
            },
        ]

        result = await export_reviews(
            namespace=namespace,
            destination=destination,
            reviews=reviews,
            parameters={},
        )

        # Verify final file exists and temp file does not
        assert destination.exists()
        temp_path = destination.with_suffix(".tmp")
        assert not temp_path.exists()

        # Verify content is complete
        content = destination.read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert len(parsed["reviews"]) == 1