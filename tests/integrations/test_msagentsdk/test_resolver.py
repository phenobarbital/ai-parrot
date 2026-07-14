"""
Unit tests for BFTokenServiceResolver and CredentialRequired.

Covers FEAT-261 Module 5 (BFTokenServiceResolver).
"""
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock


class MockTokenResult:
    """Simulates a token result from the token service."""

    def __init__(self, token: str):
        self.token = token


class MockTurnContextWithToken:
    """Turn context mock that has a token available."""

    def __init__(self, token: str):
        self._token = token
        self.turn_state = {}
        self.activity = MagicMock()
        self.activity.channel_id = "msteams"
        self.adapter = AsyncMock()
        self.adapter.get_user_token = AsyncMock(
            return_value=MockTokenResult(token)
        )


class MockTurnContextNoToken:
    """Turn context mock that has NO token (sign-in not completed)."""

    def __init__(self):
        self.turn_state = {}
        self.activity = MagicMock()
        self.activity.channel_id = "msteams"
        self.adapter = AsyncMock()
        self.adapter.get_user_token = AsyncMock(return_value=None)


class TestCredentialRequired:
    """Tests for the CredentialRequired exception."""

    def test_credential_required_attributes(self):
        """CredentialRequired carries provider, auth_url, and auth_kind."""
        # FEAT-264: the canonical exception lives in parrot.auth.credentials and
        # is surface-neutral (provider/auth_url/auth_kind), not the old
        # msagentsdk-local tool/connection_name shape.
        from parrot.auth.credentials import CredentialRequired

        exc = CredentialRequired(
            provider="graph_sso",
            auth_url="https://login.example/consent",
            auth_kind="oauth2",
        )
        assert exc.provider == "graph_sso"
        assert exc.auth_url == "https://login.example/consent"
        assert exc.auth_kind == "oauth2"
        assert "graph_sso" in str(exc)

    def test_credential_required_is_exception(self):
        """CredentialRequired is a subclass of Exception."""
        from parrot.auth.credentials import CredentialRequired

        assert issubclass(CredentialRequired, Exception)


class TestBFTokenServiceResolver:
    """Tests for BFTokenServiceResolver."""

    @pytest.mark.asyncio
    async def test_resolver_no_connection_returns_none(self):
        """Returns None when no connection is configured for the tool."""
        from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver

        resolver = BFTokenServiceResolver(
            oauth_connections={},
            obo_scopes={},
        )
        result = await resolver.resolve(
            "msagentsdk", "user-1", tool="unknown_tool"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_resolver_no_token_returns_none(self):
        """Returns None when the token service has no token.

        FEAT-264: resolve() no longer raises CredentialRequired directly — it
        returns None and the broker converts that to a NeedsAuth signal (which
        surfaces the canonical CredentialRequired upstream).
        """
        from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver

        resolver = BFTokenServiceResolver(
            oauth_connections={"o365": "graph_sso"},
            obo_scopes={},
        )
        mock_ctx = MockTurnContextNoToken()

        result = await resolver.resolve(
            "msagentsdk", "user-1", tool="o365", turn_context=mock_ctx
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_resolver_returns_token(self):
        """Returns token when the token service has a valid token."""
        from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver

        resolver = BFTokenServiceResolver(
            oauth_connections={"o365": "graph_sso"},
            obo_scopes={},
        )
        mock_ctx = MockTurnContextWithToken("fake-token-abc")

        result = await resolver.resolve(
            "msagentsdk", "user-1", tool="o365", turn_context=mock_ctx
        )
        assert result == "fake-token-abc"

    @pytest.mark.asyncio
    async def test_resolver_returns_token_and_records_audit(self):
        """resolve() records audit entry when ledger is provided."""
        from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver
        from parrot.security.audit_ledger import AuditLedger

        ledger = AuditLedger()
        resolver = BFTokenServiceResolver(
            oauth_connections={"o365": "graph_sso"},
            obo_scopes={},
            audit_ledger=ledger,
        )
        mock_ctx = MockTurnContextWithToken("fake-token-abc")

        result = await resolver.resolve(
            "msagentsdk", "user-1", tool="o365", turn_context=mock_ctx
        )
        assert result == "fake-token-abc"
        assert ledger.entry_count == 1
        entry = next(iter(ledger._entries.values()))
        # _record_audit records the action in the tool label ("<tool>:<action>")
        # and the OAuth connection name as the provider.
        assert entry.tool == "o365:resolve"
        assert entry.provider == "graph_sso"
        assert entry.user_id == "user-1"
        # Fingerprint must be SHA-256 hex, not the token itself
        assert len(entry.key_fingerprint) == 64
        assert entry.key_fingerprint != "fake-token-abc"

    @pytest.mark.asyncio
    async def test_resolver_key_fingerprint_formula(self):
        """key_fingerprint is SHA-256 of the full token (I1 fix: not first 8 bytes)."""
        from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver
        from parrot.security.audit_ledger import AuditLedger

        token = "fake-token-abc"
        expected_fp = hashlib.sha256(token.encode("utf-8")).hexdigest()

        ledger = AuditLedger()
        resolver = BFTokenServiceResolver(
            oauth_connections={"o365": "graph_sso"},
            obo_scopes={},
            audit_ledger=ledger,
        )
        mock_ctx = MockTurnContextWithToken(token)
        await resolver.resolve(
            "msagentsdk", "user-1", tool="o365", turn_context=mock_ctx
        )
        entry = next(iter(ledger._entries.values()))
        assert entry.key_fingerprint == expected_fp

    @pytest.mark.asyncio
    async def test_resolver_no_turn_context_returns_none(self):
        """With no turn_context and a configured connection, resolve() returns None.

        FEAT-264: a missing token (here because there is no turn_context to
        fetch one) yields None; the broker turns that into NeedsAuth upstream.
        """
        from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver

        resolver = BFTokenServiceResolver(
            oauth_connections={"o365": "graph_sso"},
            obo_scopes={},
        )

        result = await resolver.resolve(
            "msagentsdk", "user-1", tool="o365", turn_context=None
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_resolver_get_auth_url_raises(self):
        """get_auth_url() raises NotImplementedError."""
        from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver

        resolver = BFTokenServiceResolver(
            oauth_connections={"o365": "graph_sso"},
            obo_scopes={},
        )
        with pytest.raises(NotImplementedError):
            await resolver.get_auth_url("msagentsdk", "user-1")

    @pytest.mark.asyncio
    async def test_resolver_obo_scopes_passthrough(self):
        """Configuring OBO scopes does not alter the returned token.

        OBO exchange is not yet performed by resolve() — the fetched token is
        returned verbatim and the audit entry records the plain "resolve"
        action even when obo_scopes is configured for the tool.
        """
        from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver
        from parrot.security.audit_ledger import AuditLedger

        ledger = AuditLedger()
        resolver = BFTokenServiceResolver(
            oauth_connections={"o365": "graph_sso"},
            obo_scopes={"o365": ["https://graph.microsoft.com/.default"]},
            audit_ledger=ledger,
        )
        mock_ctx = MockTurnContextWithToken("entra-token-xyz")

        result = await resolver.resolve(
            "msagentsdk", "user-1", tool="o365", turn_context=mock_ctx
        )
        # OBO is a pass-through for now; token is preserved
        assert result == "entra-token-xyz"
        entry = next(iter(ledger._entries.values()))
        assert entry.tool == "o365:resolve"
