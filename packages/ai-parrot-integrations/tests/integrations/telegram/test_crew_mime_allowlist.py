"""Test Telegram crew MIME type allowlist validation."""

import pytest

from parrot.integrations.telegram.crew.payload import DataPayload

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class TestCrewMimeAllowlist:
    def test_accepts_docx_by_default(self):
        """Spec AC14."""
        from parrot.integrations.telegram.crew.payload import DataPayload

        payload = DataPayload()
        assert payload.validate_mime(DOCX) is True

    def test_still_rejects_unlisted_type(self):
        assert not DataPayload().validate_mime("application/x-msdownload")

    def test_explicit_allowlist_is_not_widened(self):
        """A caller-supplied list keeps full control."""
        custom_types = ["text/csv", "application/json"]
        payload = DataPayload(allowed_mime_types=custom_types)
        assert payload.validate_mime(DOCX) is False
        assert payload.validate_mime("application/x-msdownload") is False
