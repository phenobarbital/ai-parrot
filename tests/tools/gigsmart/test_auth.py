"""Unit tests for GigSmartAuth — OAuth 2.1 token lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.interfaces.gigsmart.auth import GigSmartAuth
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig
from parrot_tools.interfaces.gigsmart.exceptions import GigSmartAuthError


@pytest.fixture
def config():
    """GigSmartConfig with test credentials."""
    return GigSmartConfig(client_id="test-id", client_secret="test-secret")


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

class TestPKCEGeneration:
    """Tests for PKCE pair generation."""

    def test_verifier_length(self):
        """code_verifier must be at least 43 characters."""
        verifier, _ = GigSmartAuth.generate_pkce_pair()
        assert len(verifier) >= 43

    def test_challenge_nonempty(self):
        """code_challenge must be a non-empty string."""
        _, challenge = GigSmartAuth.generate_pkce_pair()
        assert len(challenge) > 0

    def test_pair_is_unique(self):
        """Each call returns a different pair."""
        v1, c1 = GigSmartAuth.generate_pkce_pair()
        v2, c2 = GigSmartAuth.generate_pkce_pair()
        assert v1 != v2
        assert c1 != c2

    def test_challenge_is_url_safe(self):
        """code_challenge contains only base64url characters."""
        import re
        _, challenge = GigSmartAuth.generate_pkce_pair()
        assert re.fullmatch(r"[A-Za-z0-9_\-]+", challenge), f"Not base64url: {challenge}"

    def test_verifier_is_url_safe(self):
        """code_verifier contains only base64url characters."""
        import re
        verifier, _ = GigSmartAuth.generate_pkce_pair()
        assert re.fullmatch(r"[A-Za-z0-9_\-]+", verifier), f"Not base64url: {verifier}"


# ---------------------------------------------------------------------------
# Token caching and refresh
# ---------------------------------------------------------------------------

class TestTokenCaching:
    """Tests for token caching and proactive refresh logic."""

    def _make_token_response(self, expires_in=3600, scope="read:gigs"):
        return {
            "access_token": "tok-abc",
            "token_type": "bearer",
            "expires_in": expires_in,
            "scope": scope,
        }

    @pytest.mark.asyncio
    async def test_client_credentials_token(self, config):
        """get_token() returns an access token from client_credentials grant."""
        auth = GigSmartAuth(config)
        with patch.object(auth, "_post_token", new=AsyncMock(return_value=self._make_token_response())):
            token = await auth.get_token(scopes=["read:gigs"])
        assert token == "tok-abc"

    @pytest.mark.asyncio
    async def test_second_call_uses_cache(self, config):
        """Second call within token lifetime uses cached token without re-requesting."""
        auth = GigSmartAuth(config)
        call_count = 0

        async def fake_post(data, auth=None):
            nonlocal call_count
            call_count += 1
            return self._make_token_response(expires_in=3600)

        with patch.object(auth, "_post_token", side_effect=fake_post):
            t1 = await auth.get_token()
            t2 = await auth.get_token()

        assert t1 == t2
        assert call_count == 1  # only one network call

    @pytest.mark.asyncio
    async def test_proactive_refresh_when_near_expiry(self, config):
        """A token expiring within 2 min triggers a refresh on next get_token()."""
        auth = GigSmartAuth(config)
        # Seed the cache with a token that expires in 60 seconds
        auth._cache.access_token = "old-token"
        auth._cache.expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        auth._cache.scopes = frozenset(["read:gigs"])
        auth._cache.grant_type = "client_credentials"

        with patch.object(auth, "_post_token", new=AsyncMock(return_value=self._make_token_response())):
            token = await auth.get_token()

        assert token == "tok-abc"  # fresh token

    @pytest.mark.asyncio
    async def test_build_headers_returns_bearer(self, config):
        """build_headers() returns Authorization: Bearer <token>."""
        auth = GigSmartAuth(config)
        with patch.object(auth, "_post_token", new=AsyncMock(return_value=self._make_token_response())):
            headers = await auth.build_headers()

        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer tok-abc"


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------

class TestScopeEnforcement:
    """Tests for write-scope validation."""

    @pytest.mark.asyncio
    async def test_write_scope_rejected_for_client_credentials(self, config):
        """ensure_scope() raises GigSmartAuthError for write scopes on CC tokens."""
        auth = GigSmartAuth(config)
        # Simulate a client_credentials token
        auth._cache.access_token = "tok"
        auth._cache.grant_type = "client_credentials"
        auth._cache.scopes = frozenset(["read:gigs"])
        from datetime import timedelta
        auth._cache.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        with pytest.raises(GigSmartAuthError, match="write.*scope|auth_code"):
            await auth.ensure_scope("write:gigs")

    @pytest.mark.asyncio
    async def test_read_scope_allowed_for_client_credentials(self, config):
        """ensure_scope() does not raise for read scopes on CC tokens."""
        auth = GigSmartAuth(config)
        auth._cache.access_token = "tok"
        auth._cache.grant_type = "client_credentials"
        auth._cache.scopes = frozenset(["read:gigs", "read:engagements"])
        from datetime import timedelta
        auth._cache.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Should not raise
        await auth.ensure_scope("read:gigs")

    @pytest.mark.asyncio
    async def test_write_scope_allowed_for_auth_code(self, config):
        """ensure_scope() does not raise for write scopes on auth_code tokens."""
        auth = GigSmartAuth(config)
        auth._cache.access_token = "tok"
        auth._cache.grant_type = "auth_code"
        auth._cache.scopes = frozenset(["write:gigs", "read:gigs"])
        from datetime import timedelta
        auth._cache.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Should not raise
        await auth.ensure_scope("write:gigs")


# ---------------------------------------------------------------------------
# Authorize URL generation
# ---------------------------------------------------------------------------

class TestAuthorizeUrl:
    """Tests for building OAuth authorisation URLs."""

    def test_build_authorize_url_contains_params(self, config):
        """build_authorize_url() includes required OAuth params."""
        auth = GigSmartAuth(config)
        _, challenge = GigSmartAuth.generate_pkce_pair()
        url = auth.build_authorize_url(
            redirect_uri="https://app.example.com/callback",
            scopes=["read:gigs", "write:gigs"],
            code_challenge=challenge,
        )
        assert "response_type=code" in url
        assert "client_id=test-id" in url
        assert "code_challenge_method=S256" in url
        assert challenge in url

    def test_state_included_when_provided(self, config):
        """Optional state parameter is included in the URL."""
        auth = GigSmartAuth(config)
        _, challenge = GigSmartAuth.generate_pkce_pair()
        url = auth.build_authorize_url(
            redirect_uri="https://app.example.com/callback",
            scopes=["read:gigs"],
            code_challenge=challenge,
            state="csrf-token-abc",
        )
        assert "state=csrf-token-abc" in url
