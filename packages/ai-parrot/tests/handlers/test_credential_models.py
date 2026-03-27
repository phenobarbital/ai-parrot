"""Unit tests for credential Pydantic data models (TASK-437)."""
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from parrot.handlers.models.credentials import (
    CredentialPayload,
    CredentialDocument,
    CredentialResponse,
)


class TestCredentialPayload:
    """Tests for CredentialPayload input validation model."""

    def test_valid_payload(self):
        """Valid asyncdb-style payload passes validation."""
        payload = CredentialPayload(
            name="my-postgres",
            driver="pg",
            params={"host": "localhost", "port": 5432},
        )
        assert payload.name == "my-postgres"
        assert payload.driver == "pg"
        assert payload.params == {"host": "localhost", "port": 5432}

    def test_missing_driver_raises(self):
        """Payload without driver field raises ValidationError."""
        with pytest.raises(ValidationError):
            CredentialPayload(name="test")

    def test_missing_name_raises(self):
        """Payload without name field raises ValidationError."""
        with pytest.raises(ValidationError):
            CredentialPayload(driver="pg")

    def test_name_too_long_raises(self):
        """Name exceeding 128 characters raises ValidationError."""
        with pytest.raises(ValidationError):
            CredentialPayload(name="x" * 129, driver="pg")

    def test_name_exactly_128_passes(self):
        """Name of exactly 128 characters is accepted."""
        payload = CredentialPayload(name="x" * 128, driver="pg")
        assert len(payload.name) == 128

    def test_empty_name_raises(self):
        """Empty string name raises ValidationError."""
        with pytest.raises(ValidationError):
            CredentialPayload(name="", driver="pg")

    def test_empty_driver_raises(self):
        """Empty string driver raises ValidationError."""
        with pytest.raises(ValidationError):
            CredentialPayload(name="test", driver="")

    def test_params_defaults_to_empty(self):
        """params field defaults to empty dict when not provided."""
        payload = CredentialPayload(name="test", driver="pg")
        assert payload.params == {}

    def test_params_with_values(self):
        """params accepts arbitrary dict values."""
        payload = CredentialPayload(
            name="test",
            driver="pg",
            params={"host": "localhost", "port": 5432, "user": "admin"},
        )
        assert payload.params["host"] == "localhost"
        assert payload.params["port"] == 5432


class TestCredentialDocument:
    """Tests for CredentialDocument storage model."""

    def test_valid_document(self):
        """Valid CredentialDocument passes construction."""
        now = datetime.now(timezone.utc)
        doc = CredentialDocument(
            user_id="user-123",
            name="my-pg",
            credential="encrypted-base64-string",
            created_at=now,
            updated_at=now,
        )
        assert doc.user_id == "user-123"
        assert doc.name == "my-pg"
        assert doc.credential == "encrypted-base64-string"

    def test_missing_user_id_raises(self):
        """CredentialDocument without user_id raises ValidationError."""
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            CredentialDocument(
                name="test",
                credential="enc",
                created_at=now,
                updated_at=now,
            )

    def test_missing_credential_raises(self):
        """CredentialDocument without credential field raises ValidationError."""
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            CredentialDocument(
                user_id="user-123",
                name="test",
                created_at=now,
                updated_at=now,
            )


class TestCredentialResponse:
    """Tests for CredentialResponse API response model."""

    def test_valid_response(self):
        """Valid CredentialResponse passes construction."""
        resp = CredentialResponse(
            name="my-pg",
            driver="pg",
            params={"host": "localhost"},
        )
        assert resp.name == "my-pg"
        assert resp.driver == "pg"
        assert resp.params == {"host": "localhost"}

    def test_empty_params_allowed(self):
        """CredentialResponse allows empty params dict."""
        resp = CredentialResponse(name="test", driver="mysql", params={})
        assert resp.params == {}

    def test_missing_driver_raises(self):
        """CredentialResponse without driver raises ValidationError."""
        with pytest.raises(ValidationError):
            CredentialResponse(name="test", params={})
