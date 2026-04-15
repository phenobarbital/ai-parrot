"""Unit tests for SubmitAction auth extension (TASK-598 / FEAT-086)."""

import pytest
from parrot.formdesigner.core.auth import BearerAuth, ApiKeyAuth, NoAuth
from parrot.formdesigner.core.schema import SubmitAction


class TestSubmitActionAuth:
    """Tests for the new auth field on SubmitAction."""

    def test_without_auth_field(self) -> None:
        """SubmitAction without auth field defaults to None."""
        sa = SubmitAction(action_type="endpoint", action_ref="http://example.com")
        assert sa.auth is None

    def test_with_bearer_auth(self) -> None:
        """SubmitAction accepts BearerAuth configuration."""
        sa = SubmitAction(
            action_type="endpoint",
            action_ref="http://example.com",
            auth=BearerAuth(token_env="MY_TOKEN"),
        )
        assert sa.auth is not None
        assert sa.auth.type == "bearer"

    def test_with_api_key_auth(self) -> None:
        """SubmitAction accepts ApiKeyAuth configuration."""
        sa = SubmitAction(
            action_type="endpoint",
            action_ref="http://example.com",
            auth=ApiKeyAuth(key_env="MY_KEY"),
        )
        assert sa.auth is not None
        assert sa.auth.type == "api_key"

    def test_with_no_auth(self) -> None:
        """SubmitAction accepts explicit NoAuth configuration."""
        sa = SubmitAction(
            action_type="endpoint",
            action_ref="http://example.com",
            auth=NoAuth(),
        )
        assert sa.auth is not None
        assert sa.auth.type == "none"

    def test_backward_compat_deserialize(self) -> None:
        """Dicts without auth field deserialize correctly (backward compat)."""
        d = {
            "action_type": "endpoint",
            "action_ref": "http://x",
            "method": "POST",
        }
        sa = SubmitAction.model_validate(d)
        assert sa.auth is None

    def test_model_dump_includes_auth(self) -> None:
        """model_dump() includes the auth field."""
        sa = SubmitAction(
            action_type="endpoint",
            action_ref="http://example.com",
            auth=BearerAuth(token_env="MY_TOKEN"),
        )
        d = sa.model_dump()
        assert "auth" in d
        assert d["auth"]["type"] == "bearer"
        assert d["auth"]["token_env"] == "MY_TOKEN"

    def test_model_dump_and_validate_roundtrip(self) -> None:
        """model_dump() → model_validate() roundtrip preserves auth config."""
        sa = SubmitAction(
            action_type="endpoint",
            action_ref="http://example.com",
            auth=BearerAuth(token_env="MY_TOKEN"),
        )
        d = sa.model_dump()
        restored = SubmitAction.model_validate(d)
        assert restored.auth is not None
        assert restored.auth.type == "bearer"
        assert restored.auth.token_env == "MY_TOKEN"  # type: ignore[union-attr]

    def test_api_key_roundtrip(self) -> None:
        """ApiKeyAuth roundtrip preserves key_env and header_name."""
        sa = SubmitAction(
            action_type="endpoint",
            action_ref="http://example.com",
            auth=ApiKeyAuth(key_env="THE_KEY", header_name="X-Custom"),
        )
        d = sa.model_dump()
        restored = SubmitAction.model_validate(d)
        assert restored.auth is not None
        assert restored.auth.type == "api_key"
        assert restored.auth.key_env == "THE_KEY"  # type: ignore[union-attr]
        assert restored.auth.header_name == "X-Custom"  # type: ignore[union-attr]

    def test_export_from_package(self) -> None:
        """Auth types are exportable from parrot.formdesigner package."""
        from parrot.formdesigner import (  # noqa: F401
            ApiKeyAuth,
            AuthConfig,
            BearerAuth,
            NoAuth,
            SubmitAction,
        )
