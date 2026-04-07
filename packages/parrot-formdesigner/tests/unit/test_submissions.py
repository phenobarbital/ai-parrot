"""Unit tests for FormSubmission model (TASK-599 / FEAT-086)."""

from datetime import datetime, timezone

import pytest
from parrot.formdesigner.services.submissions import FormSubmission, FormSubmissionStorage


class TestFormSubmission:
    """Tests for the FormSubmission Pydantic model."""

    def test_model_creation_minimal(self) -> None:
        """FormSubmission creates correctly with minimal required fields."""
        sub = FormSubmission(
            form_id="test-form",
            form_version="1.0",
            data={"name": "John"},
            is_valid=True,
        )
        assert sub.form_id == "test-form"
        assert sub.form_version == "1.0"
        assert sub.is_valid is True
        assert sub.forwarded is False
        assert sub.forward_status is None
        assert sub.forward_error is None

    def test_submission_id_auto_generated(self) -> None:
        """submission_id is auto-generated when not provided."""
        sub = FormSubmission(
            form_id="f", form_version="1.0", data={}, is_valid=True
        )
        assert sub.submission_id is not None
        assert len(sub.submission_id) > 0

    def test_submission_id_explicit(self) -> None:
        """Explicit submission_id is preserved."""
        sub = FormSubmission(
            submission_id="sub-001",
            form_id="test-form",
            form_version="1.0",
            data={"name": "John", "email": "john@example.com"},
            is_valid=True,
            created_at=datetime.now(timezone.utc),
        )
        assert sub.submission_id == "sub-001"

    def test_created_at_auto_set(self) -> None:
        """created_at defaults to current UTC time when not provided."""
        before = datetime.now(timezone.utc)
        sub = FormSubmission(
            form_id="f", form_version="1.0", data={}, is_valid=True
        )
        after = datetime.now(timezone.utc)
        assert before <= sub.created_at <= after

    def test_forwarded_defaults_false(self) -> None:
        """forwarded defaults to False."""
        sub = FormSubmission(
            form_id="f", form_version="1.0", data={}, is_valid=True
        )
        assert sub.forwarded is False

    def test_forward_error_optional(self) -> None:
        """forward_error can be set on a failed submission."""
        sub = FormSubmission(
            form_id="f",
            form_version="1.0",
            data={},
            is_valid=True,
            forwarded=False,
            forward_error="Connection refused",
        )
        assert sub.forward_error == "Connection refused"

    def test_serialization_roundtrip(self) -> None:
        """model_dump() → model_validate() preserves all fields."""
        sub = FormSubmission(
            submission_id="sub-001",
            form_id="test-form",
            form_version="1.0",
            data={"key": "value"},
            is_valid=True,
            created_at=datetime.now(timezone.utc),
        )
        d = sub.model_dump()
        restored = FormSubmission.model_validate(d)
        assert restored.submission_id == "sub-001"
        assert restored.form_id == "test-form"
        assert restored.data == {"key": "value"}

    def test_two_submissions_different_ids(self) -> None:
        """Auto-generated submission_ids are unique."""
        sub1 = FormSubmission(form_id="f", form_version="1.0", data={}, is_valid=True)
        sub2 = FormSubmission(form_id="f", form_version="1.0", data={}, is_valid=True)
        assert sub1.submission_id != sub2.submission_id
