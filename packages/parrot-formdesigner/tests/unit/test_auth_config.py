"""Unit tests for AuthConfig models (TASK-597 / FEAT-086)."""

import pytest
from parrot_formdesigner.core.auth import ApiKeyAuth, AuthConfig, BearerAuth, NoAuth


# ---------------------------------------------------------------------------
# NoAuth
# ---------------------------------------------------------------------------

class TestNoAuth:
    """Tests for NoAuth — the default, no-credentials auth type."""

    def test_resolve_returns_empty(self) -> None:
        """NoAuth.resolve() must return an empty dict."""
        auth = NoAuth()
        assert auth.resolve() == {}

    def test_type_is_none(self) -> None:
        """NoAuth.type must be the literal 'none'."""
        auth = NoAuth()
        assert auth.type == "none"

    def test_serialization_roundtrip(self) -> None:
        """NoAuth serializes and deserializes correctly."""
        auth = NoAuth()
        d = auth.model_dump()
        restored = NoAuth.model_validate(d)
        assert restored.type == "none"

    def test_extra_field_forbidden(self) -> None:
        """Extra fields are rejected (ConfigDict extra='forbid')."""
        with pytest.raises(Exception):
            NoAuth(unexpected="field")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# BearerAuth
# ---------------------------------------------------------------------------

class TestBearerAuth:
    """Tests for BearerAuth — Bearer token authentication."""

    def test_resolve_with_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BearerAuth.resolve() returns Authorization header with token from env."""
        monkeypatch.setenv("TEST_TOKEN", "abc123")
        auth = BearerAuth(token_env="TEST_TOKEN")
        headers = auth.resolve()
        assert headers == {"Authorization": "Bearer abc123"}

    def test_resolve_missing_env_var(self) -> None:
        """BearerAuth.resolve() raises ValueError when env var is not set."""
        auth = BearerAuth(token_env="NONEXISTENT_VAR_12345_FEAT086")
        with pytest.raises(ValueError, match="NONEXISTENT_VAR_12345_FEAT086"):
            auth.resolve()

    def test_type_is_bearer(self) -> None:
        """BearerAuth.type must be the literal 'bearer'."""
        auth = BearerAuth(token_env="X")
        assert auth.type == "bearer"

    def test_serialization_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BearerAuth serializes and deserializes correctly."""
        auth = BearerAuth(token_env="MY_TOKEN")
        d = auth.model_dump()
        restored = BearerAuth.model_validate(d)
        assert restored.token_env == "MY_TOKEN"

    def test_extra_field_forbidden(self) -> None:
        """Extra fields are rejected."""
        with pytest.raises(Exception):
            BearerAuth(token_env="X", unknown="y")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ApiKeyAuth
# ---------------------------------------------------------------------------

class TestApiKeyAuth:
    """Tests for ApiKeyAuth — API key header authentication."""

    def test_resolve_default_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ApiKeyAuth.resolve() uses X-API-Key header by default."""
        monkeypatch.setenv("TEST_API_KEY", "key123")
        auth = ApiKeyAuth(key_env="TEST_API_KEY")
        headers = auth.resolve()
        assert headers == {"X-API-Key": "key123"}

    def test_resolve_custom_header_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ApiKeyAuth.resolve() uses the configured custom header name."""
        monkeypatch.setenv("TEST_API_KEY", "key123")
        auth = ApiKeyAuth(key_env="TEST_API_KEY", header_name="X-Custom-Auth")
        headers = auth.resolve()
        assert headers == {"X-Custom-Auth": "key123"}

    def test_resolve_missing_env_var(self) -> None:
        """ApiKeyAuth.resolve() raises ValueError when env var is not set."""
        auth = ApiKeyAuth(key_env="NONEXISTENT_APIKEY_12345_FEAT086")
        with pytest.raises(ValueError):
            auth.resolve()

    def test_default_header_name(self) -> None:
        """ApiKeyAuth default header_name is 'X-API-Key'."""
        auth = ApiKeyAuth(key_env="X")
        assert auth.header_name == "X-API-Key"

    def test_type_is_api_key(self) -> None:
        """ApiKeyAuth.type must be the literal 'api_key'."""
        auth = ApiKeyAuth(key_env="X")
        assert auth.type == "api_key"

    def test_extra_field_forbidden(self) -> None:
        """Extra fields are rejected."""
        with pytest.raises(Exception):
            ApiKeyAuth(key_env="X", unknown="y")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# AuthConfig union
# ---------------------------------------------------------------------------

class TestAuthConfig:
    """Tests for the AuthConfig discriminated union type alias."""

    def test_no_auth_is_valid(self) -> None:
        """NoAuth is a valid AuthConfig."""
        auth: AuthConfig = NoAuth()
        assert auth.type == "none"

    def test_bearer_auth_is_valid(self) -> None:
        """BearerAuth is a valid AuthConfig."""
        auth: AuthConfig = BearerAuth(token_env="T")
        assert auth.type == "bearer"

    def test_api_key_auth_is_valid(self) -> None:
        """ApiKeyAuth is a valid AuthConfig."""
        auth: AuthConfig = ApiKeyAuth(key_env="K")
        assert auth.type == "api_key"

    def test_import_from_core_auth(self) -> None:
        """All auth types are importable from parrot_formdesigner.core.auth."""
        from parrot_formdesigner.core.auth import (  # noqa: F401
            ApiKeyAuth,
            AuthConfig,
            BearerAuth,
            NoAuth,
        )


# --- TASK-1155: AuthContext model tests ---

class TestAuthContext:
    """Tests for AuthContext runtime auth context model."""

    def test_auth_context_resolve_for_bearer(self) -> None:
        """AuthContext with bearer scheme returns Authorization header."""
        from parrot_formdesigner.services.auth_context import AuthContext

        ctx = AuthContext(scheme="bearer", token="my-token")
        headers = ctx.resolve_for("SOME_REF")
        assert headers == {"Authorization": "Bearer my-token"}

    def test_auth_context_resolve_for_none_scheme(self) -> None:
        """AuthContext with 'none' scheme returns empty dict."""
        from parrot_formdesigner.services.auth_context import AuthContext

        ctx = AuthContext(scheme="none")
        assert ctx.resolve_for(None) == {}
        assert ctx.resolve_for("ANY_REF") == {}

    def test_auth_context_resolve_for_unknown_ref(self) -> None:
        """Unknown auth_ref with bearer still returns Bearer header — no raise."""
        from parrot_formdesigner.services.auth_context import AuthContext

        ctx = AuthContext(scheme="bearer", token="test-token")
        headers = ctx.resolve_for("UNKNOWN_REF")
        assert "Authorization" in headers

    def test_auth_context_custom_headers(self) -> None:
        """Custom scheme returns pre-built headers."""
        from parrot_formdesigner.services.auth_context import AuthContext

        ctx = AuthContext(
            scheme="custom",
            headers={"X-Custom-Auth": "secret", "X-Tenant": "acme"},
        )
        headers = ctx.resolve_for("CUSTOM_REF")
        assert headers["X-Custom-Auth"] == "secret"

    def test_auth_context_default_values(self) -> None:
        """AuthContext defaults are correct."""
        from parrot_formdesigner.services.auth_context import AuthContext

        ctx = AuthContext(scheme="none")
        assert ctx.token is None
        assert ctx.headers == {}
        assert ctx.claims == {}

    def test_auth_context_api_key_scheme(self) -> None:
        """AuthContext with api_key scheme returns X-API-Key header."""
        from parrot_formdesigner.services.auth_context import AuthContext

        ctx = AuthContext(scheme="api_key", token="secret-key")
        headers = ctx.resolve_for("API_KEY_REF")
        assert headers == {"X-API-Key": "secret-key"}

    def test_auth_context_bearer_no_token_returns_empty(self) -> None:
        """Bearer scheme with no token returns headers (empty via custom fallback)."""
        from parrot_formdesigner.services.auth_context import AuthContext

        ctx = AuthContext(scheme="bearer", token=None)
        headers = ctx.resolve_for("REF")
        # No token → falls through to custom headers path → returns {}
        assert headers == {}

    def test_auth_context_none_auth_ref_returns_empty(self) -> None:
        """auth_ref=None always returns empty headers regardless of scheme."""
        from parrot_formdesigner.services.auth_context import AuthContext

        ctx = AuthContext(scheme="bearer", token="tok")
        assert ctx.resolve_for(None) == {}

    def test_auth_context_importable(self) -> None:
        """AuthContext is importable from services.auth_context."""
        from parrot_formdesigner.services.auth_context import AuthContext  # noqa: F401
