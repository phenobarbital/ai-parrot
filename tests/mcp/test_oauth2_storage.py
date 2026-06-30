"""Tests for parrot.mcp.oauth2_storage — VaultMCPTokenStorage adapter."""
import pytest
from unittest.mock import AsyncMock, patch

from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull


@pytest.fixture
def storage():
    """Create a VaultMCPTokenStorage with a default vault."""
    return VaultMCPTokenStorage(user_id="test@co.com", server_name="test-server")


class TestVaultMCPTokenStorageInit:
    """Tests for initialization."""

    def test_creates_with_defaults(self):
        """VaultMCPTokenStorage creates a default VaultTokenStore when none given."""
        s = VaultMCPTokenStorage("user@co.com", "netsuite")
        assert s._user_id == "user@co.com"
        assert s._server_name == "netsuite"
        assert s._vault is not None

    def test_accepts_external_vault(self):
        """VaultMCPTokenStorage accepts an external vault store."""
        from parrot.mcp.oauth import InMemoryTokenStore
        vault = InMemoryTokenStore()
        s = VaultMCPTokenStorage("user@co.com", "netsuite", vault_store=vault)
        assert s._vault is vault

    def test_client_info_server_name(self, storage):
        """Client info uses a distinct vault key."""
        key = storage._client_info_server_name()
        assert "test-server" in key
        assert key != "test-server"


class TestGetTokens:
    """Tests for get_tokens()."""

    @pytest.mark.asyncio
    async def test_get_tokens_returns_none_when_empty(self, storage):
        """get_tokens() returns None when vault has no data."""
        with patch.object(storage._vault, "get", new_callable=AsyncMock, return_value=None):
            result = await storage.get_tokens()
            assert result is None

    @pytest.mark.asyncio
    async def test_get_tokens_returns_oauth_token(self, storage):
        """get_tokens() converts dict to OAuthToken."""
        token_data = {
            "access_token": "abc123",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        with patch.object(storage._vault, "get", new_callable=AsyncMock, return_value=token_data):
            result = await storage.get_tokens()
            assert result is not None
            assert isinstance(result, OAuthToken)
            assert result.access_token == "abc123"
            assert result.token_type == "Bearer"

    @pytest.mark.asyncio
    async def test_get_tokens_vault_unavailable_returns_none(self, storage):
        """get_tokens() returns None when vault raises RuntimeError."""
        with patch.object(
            storage._vault, "get",
            new_callable=AsyncMock,
            side_effect=RuntimeError("vault keys unavailable"),
        ):
            result = await storage.get_tokens()
            assert result is None

    @pytest.mark.asyncio
    async def test_get_tokens_ignores_extra_fields(self, storage):
        """get_tokens() filters out fields not in OAuthToken schema."""
        token_data = {
            "access_token": "abc",
            "token_type": "Bearer",
            "expires_at": 9999999999,  # extra field not in OAuthToken
            "raw": {"some": "stuff"},   # extra field not in OAuthToken
        }
        with patch.object(storage._vault, "get", new_callable=AsyncMock, return_value=token_data):
            result = await storage.get_tokens()
            assert result is not None
            assert result.access_token == "abc"


class TestSetTokens:
    """Tests for set_tokens()."""

    @pytest.mark.asyncio
    async def test_set_tokens_calls_vault(self, storage):
        """set_tokens() stores token in vault."""
        token = OAuthToken(access_token="tok123", token_type="Bearer")
        with patch.object(storage._vault, "set", new_callable=AsyncMock) as mock_set:
            await storage.set_tokens(token)
            mock_set.assert_called_once()
            args = mock_set.call_args[0]
            assert args[0] == "test@co.com"
            assert args[1] == "test-server"
            assert args[2]["access_token"] == "tok123"

    @pytest.mark.asyncio
    async def test_set_tokens_vault_unavailable_no_raise(self, storage):
        """set_tokens() does not raise when vault is unavailable."""
        token = OAuthToken(access_token="tok", token_type="Bearer")
        with patch.object(
            storage._vault, "set",
            new_callable=AsyncMock,
            side_effect=RuntimeError("vault unavailable"),
        ):
            # Should not raise
            await storage.set_tokens(token)

    @pytest.mark.asyncio
    async def test_set_tokens_excludes_none_values(self, storage):
        """set_tokens() excludes None values from stored data."""
        token = OAuthToken(access_token="tok", token_type="Bearer")
        with patch.object(storage._vault, "set", new_callable=AsyncMock) as mock_set:
            await storage.set_tokens(token)
            stored_data = mock_set.call_args[0][2]
            assert None not in stored_data.values()


class TestGetClientInfo:
    """Tests for get_client_info()."""

    @pytest.mark.asyncio
    async def test_get_client_info_returns_none_when_empty(self, storage):
        """get_client_info() returns None when not stored."""
        with patch.object(storage._vault, "get", new_callable=AsyncMock, return_value=None):
            result = await storage.get_client_info()
            assert result is None

    @pytest.mark.asyncio
    async def test_get_client_info_returns_client_info(self, storage):
        """get_client_info() converts dict to OAuthClientInformationFull."""
        client_data = {
            "client_id": "my-client-id",
            "client_secret": "my-secret",
            "redirect_uris": ["https://example.com/callback"],
        }
        with patch.object(storage._vault, "get", new_callable=AsyncMock, return_value=client_data):
            result = await storage.get_client_info()
            assert result is not None
            assert isinstance(result, OAuthClientInformationFull)
            assert result.client_id == "my-client-id"

    @pytest.mark.asyncio
    async def test_get_client_info_uses_separate_vault_key(self, storage):
        """get_client_info() uses a different vault key than get_tokens()."""
        calls = []
        async def mock_get(user_id, server_name):
            calls.append(server_name)
            return None

        with patch.object(storage._vault, "get", side_effect=mock_get):
            await storage.get_tokens()
            await storage.get_client_info()

        assert len(calls) == 2
        assert calls[0] != calls[1]
        assert "test-server" in calls[0]
        assert "__client_info_test-server" in calls[1]

    @pytest.mark.asyncio
    async def test_get_client_info_vault_unavailable_returns_none(self, storage):
        """get_client_info() returns None when vault raises."""
        with patch.object(
            storage._vault, "get",
            new_callable=AsyncMock,
            side_effect=RuntimeError("vault down"),
        ):
            result = await storage.get_client_info()
            assert result is None


class TestSetClientInfo:
    """Tests for set_client_info()."""

    @pytest.mark.asyncio
    async def test_set_client_info_calls_vault(self, storage):
        """set_client_info() stores data in vault with separate key."""
        client_info = OAuthClientInformationFull(
            client_id="test-client",
            redirect_uris=["https://example.com/callback"],
        )
        with patch.object(storage._vault, "set", new_callable=AsyncMock) as mock_set:
            await storage.set_client_info(client_info)
            mock_set.assert_called_once()
            args = mock_set.call_args[0]
            assert args[1] == "__client_info_test-server"

    @pytest.mark.asyncio
    async def test_set_client_info_vault_unavailable_no_raise(self, storage):
        """set_client_info() does not raise when vault is unavailable."""
        client_info = OAuthClientInformationFull(
            client_id="test-client",
            redirect_uris=["https://example.com/callback"],
        )
        with patch.object(
            storage._vault, "set",
            new_callable=AsyncMock,
            side_effect=RuntimeError("vault unavailable"),
        ):
            # Should not raise
            await storage.set_client_info(client_info)


class TestRoundTrip:
    """Integration-style round-trip tests using InMemoryTokenStore."""

    @pytest.mark.asyncio
    async def test_tokens_round_trip(self):
        """Token stored then retrieved preserves fields."""
        from parrot.mcp.oauth import InMemoryTokenStore

        vault = InMemoryTokenStore()
        storage = VaultMCPTokenStorage("user@co.com", "server1", vault_store=vault)

        token = OAuthToken(
            access_token="access123",
            token_type="Bearer",
            expires_in=3600,
            scope="read write",
        )
        await storage.set_tokens(token)
        retrieved = await storage.get_tokens()

        assert retrieved is not None
        assert retrieved.access_token == "access123"
        assert retrieved.token_type == "Bearer"
        assert retrieved.scope == "read write"
