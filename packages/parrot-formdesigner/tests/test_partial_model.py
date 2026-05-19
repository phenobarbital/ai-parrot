"""Unit tests for PartialFormData Pydantic model (TASK-1247).

Tests:
- Basic construction with all required fields
- Empty data / field_errors defaults
- field_errors population
- JSON round-trip via model_dump_json / model_validate_json
"""

from datetime import datetime, timedelta, timezone

import pytest

from parrot_formdesigner.core.partial import PartialFormData


class TestPartialFormData:
    """Tests for the PartialFormData model."""

    def test_basic_construction(self):
        """model accepts all required fields and stores them correctly."""
        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id="test-form",
            session_id="session-123",
            data={"name": "Alice", "age": 30},
            field_errors={},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert partial.form_id == "test-form"
        assert partial.session_id == "session-123"
        assert partial.data["name"] == "Alice"
        assert partial.data["age"] == 30

    def test_empty_data(self):
        """model allows empty data dict."""
        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id="f1",
            session_id="s1",
            data={},
            field_errors={},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert partial.data == {}

    def test_data_default_factory(self):
        """data defaults to an empty dict when omitted."""
        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id="f1",
            session_id="s1",
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert partial.data == {}
        assert partial.field_errors == {}

    def test_field_errors(self):
        """field_errors stores per-field error message lists."""
        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id="f1",
            session_id="s1",
            data={"age": -5},
            field_errors={"age": ["Age must be at least 0"]},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert "age" in partial.field_errors
        assert len(partial.field_errors["age"]) == 1
        assert partial.field_errors["age"][0] == "Age must be at least 0"

    def test_json_round_trip(self):
        """model_dump_json / model_validate_json preserves all fields."""
        now = datetime.now(tz=timezone.utc)
        original = PartialFormData(
            form_id="test-form",
            session_id="session-456",
            data={"name": "Bob", "tags": ["a", "b"]},
            field_errors={"email": ["Invalid email"]},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        json_str = original.model_dump_json()
        restored = PartialFormData.model_validate_json(json_str)
        assert restored.form_id == original.form_id
        assert restored.session_id == original.session_id
        assert restored.data == original.data
        assert restored.field_errors == original.field_errors
        assert restored.saved_at == original.saved_at
        assert restored.expires_at == original.expires_at

    def test_json_round_trip_complex_values(self):
        """JSON round-trip preserves nested dict/list values."""
        now = datetime.now(tz=timezone.utc)
        original = PartialFormData(
            form_id="f1",
            session_id="s1",
            data={
                "address": {"street": "123 Main St", "city": "Springfield"},
                "hobbies": ["reading", "coding"],
                "score": 42.5,
                "active": True,
            },
            field_errors={},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        json_str = original.model_dump_json()
        restored = PartialFormData.model_validate_json(json_str)
        assert restored.data["address"]["city"] == "Springfield"
        assert restored.data["hobbies"] == ["reading", "coding"]
        assert restored.data["score"] == 42.5
        assert restored.data["active"] is True

    def test_multiple_field_errors(self):
        """field_errors can hold multiple errors per field."""
        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id="f1",
            session_id="s1",
            data={"age": -5},
            field_errors={
                "age": ["Age must be at least 0", "Age must be an integer"],
                "name": ["Name is required"],
            },
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert len(partial.field_errors["age"]) == 2
        assert len(partial.field_errors["name"]) == 1

    def test_produced_json_is_valid(self):
        """model_dump_json produces a parseable JSON string."""
        import json

        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id="f1",
            session_id="s1",
            data={"x": 1},
            field_errors={},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        raw = partial.model_dump_json()
        parsed = json.loads(raw)
        assert parsed["form_id"] == "f1"
        assert parsed["session_id"] == "s1"
        assert parsed["data"] == {"x": 1}
