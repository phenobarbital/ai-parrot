"""Unit tests for AIMessage.artifact_id field (FEAT-197, TASK-1318).

NOTE: The parent tests/conftest.py registers a lightweight _AIMessage stub via
sys.modules.setdefault().  This test needs the real Pydantic AIMessage, so we
temporarily remove the stub from sys.modules and import the real module.
"""
from __future__ import annotations

import json
import sys
import pytest


# -- Force the real parrot.models.responses module into sys.modules ----------
# The parent conftest puts a stub in sys.modules["parrot.models.responses"].
# Deleting that entry and re-importing forces Python to load the real module.
_stub = sys.modules.pop("parrot.models.responses", None)
import parrot.models.responses as _real_responses  # noqa: E402
sys.modules["parrot.models.responses"] = _real_responses

from parrot.models.responses import AIMessage  # noqa: E402


def _minimal_kwargs():
    """Return the minimum kwargs needed to construct an AIMessage."""
    return dict(
        input="q",
        output="a",
        model="m",
        provider="p",
        usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    )


class TestAIMessageArtifactId:
    """Tests for the artifact_id top-level field on AIMessage."""

    def test_artifact_id_defaults_to_none(self):
        """AIMessage without artifact_id should default to None."""
        msg = AIMessage(**_minimal_kwargs())
        assert msg.artifact_id is None

    def test_artifact_id_set_to_string(self):
        """AIMessage with a string artifact_id should validate correctly."""
        msg = AIMessage(**_minimal_kwargs(), artifact_id="art-001")
        assert msg.artifact_id == "art-001"

    def test_artifact_id_round_trips(self):
        """artifact_id should survive a model_dump / model_validate round trip."""
        msg = AIMessage(**_minimal_kwargs(), artifact_id="art-001")
        dumped = json.loads(msg.model_dump_json())
        restored = AIMessage.model_validate(dumped)
        assert restored.artifact_id == "art-001"

    def test_artifact_id_none_round_trips(self):
        """artifact_id=None should survive a round trip."""
        msg = AIMessage(**_minimal_kwargs())
        dumped = json.loads(msg.model_dump_json())
        restored = AIMessage.model_validate(dumped)
        assert restored.artifact_id is None

    def test_artifact_id_in_model_dump(self):
        """artifact_id should appear in model_dump() as None by default."""
        msg = AIMessage(**_minimal_kwargs())
        data = msg.model_dump()
        assert "artifact_id" in data
        assert data["artifact_id"] is None

    def test_artifact_id_independent_of_artifacts_list(self):
        """artifact_id should be independent of the generic artifacts list."""
        msg = AIMessage(**_minimal_kwargs(), artifact_id="art-001")
        assert msg.artifacts == []   # untouched
        msg.add_artifact("dataset", {"foo": "bar"})
        # artifact_id must still be the same
        assert msg.artifact_id == "art-001"
        # generic list grew
        assert len(msg.artifacts) == 1

    def test_existing_artifacts_field_unchanged(self):
        """The generic artifacts: List[Dict] field must remain independent."""
        msg = AIMessage(**_minimal_kwargs())
        msg.add_artifact("code", "print('hello')")
        assert len(msg.artifacts) == 1
        assert msg.artifact_id is None  # completely separate
