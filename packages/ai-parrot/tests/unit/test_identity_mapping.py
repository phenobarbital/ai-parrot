"""Unit tests for IdentityMappingService (FEAT-108 / TASK-760)."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.services.identity_mapping import (
    IdentityMappingService,
    _decode_auth_data,
)


@pytest.fixture
def mock_pool_and_conn():
    """Return (pool, conn) where `pool.acquire()` yields `conn` as an async CM."""
    conn = AsyncMock()
    pool = MagicMock()
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acquire_cm
    return pool, conn


@pytest.fixture
def service(mock_pool_and_conn):
    pool, _ = mock_pool_and_conn
    return IdentityMappingService(pool)


class TestDecodeAuthData:
    """_decode_auth_data helper handles dict, str, bytes, None, bad JSON."""

    def test_none(self):
        assert _decode_auth_data(None) == {}

    def test_dict_passthrough(self):
        d = {"key": "value"}
        assert _decode_auth_data(d) == d

    def test_json_string(self):
        assert _decode_auth_data('{"a": 1}') == {"a": 1}

    def test_json_bytes(self):
        assert _decode_auth_data(b'{"a": 1}') == {"a": 1}

    def test_malformed_json_returns_empty(self):
        assert _decode_auth_data("not json") == {}


class TestUpsertIdentity:
    async def test_upsert_identity_executes_sql(self, service, mock_pool_and_conn):
        _, conn = mock_pool_and_conn
        await service.upsert_identity(
            nav_user_id="user-123",
            auth_provider="jira",
            auth_data={"account_id": "jira-456", "cloud_id": "cloud-789"},
            display_name="Jira User",
            email="jira@example.com",
        )
        conn.execute.assert_called_once()
        args = conn.execute.call_args[0]
        assert "INSERT INTO auth.user_identities" in args[0]
        assert "ON CONFLICT (user_id, auth_provider)" in args[0]
        # positional arg order: sql, nav_user_id, provider, json-payload, name, email
        assert args[1] == "user-123"
        assert args[2] == "jira"
        payload = json.loads(args[3])
        assert payload == {"account_id": "jira-456", "cloud_id": "cloud-789"}
        assert args[4] == "Jira User"
        assert args[5] == "jira@example.com"

    async def test_upsert_without_optional_fields(
        self, service, mock_pool_and_conn
    ):
        _, conn = mock_pool_and_conn
        await service.upsert_identity(
            nav_user_id="u", auth_provider="telegram",
            auth_data={"telegram_id": 999},
        )
        args = conn.execute.call_args[0]
        assert args[4] is None  # display_name
        assert args[5] is None  # email

    async def test_upsert_empty_auth_data(self, service, mock_pool_and_conn):
        _, conn = mock_pool_and_conn
        await service.upsert_identity(
            nav_user_id="u", auth_provider="telegram", auth_data={},
        )
        payload = json.loads(conn.execute.call_args[0][3])
        assert payload == {}


class TestGetIdentity:
    async def test_get_identity_found(self, service, mock_pool_and_conn):
        _, conn = mock_pool_and_conn
        conn.fetchrow = AsyncMock(return_value={
            "identity_id": "id-1",
            "user_id": "user-123",
            "auth_provider": "jira",
            "auth_data": '{"account_id": "jira-456"}',
            "display_name": "Jira User",
            "email": "jira@example.com",
            "created_at": "2026-01-01",
        })
        result = await service.get_identity("user-123", "jira")
        assert result is not None
        assert result["auth_provider"] == "jira"
        assert result["auth_data"] == {"account_id": "jira-456"}
        assert result["display_name"] == "Jira User"

    async def test_get_identity_not_found(self, service, mock_pool_and_conn):
        _, conn = mock_pool_and_conn
        conn.fetchrow = AsyncMock(return_value=None)
        result = await service.get_identity("user-123", "nonexistent")
        assert result is None

    async def test_get_identity_passes_correct_sql(
        self, service, mock_pool_and_conn
    ):
        _, conn = mock_pool_and_conn
        conn.fetchrow = AsyncMock(return_value=None)
        await service.get_identity("u", "jira")
        sql = conn.fetchrow.call_args[0][0]
        assert "FROM auth.user_identities" in sql
        assert "WHERE user_id = $1 AND auth_provider = $2" in sql
        assert conn.fetchrow.call_args[0][1] == "u"
        assert conn.fetchrow.call_args[0][2] == "jira"


class TestGetAllIdentities:
    async def test_get_all_returns_multiple(self, service, mock_pool_and_conn):
        _, conn = mock_pool_and_conn
        conn.fetch = AsyncMock(return_value=[
            {
                "identity_id": "i1",
                "user_id": "user-123",
                "auth_provider": "telegram",
                "auth_data": '{"telegram_id": 123}',
                "display_name": None,
                "email": None,
                "created_at": None,
            },
            {
                "identity_id": "i2",
                "user_id": "user-123",
                "auth_provider": "jira",
                "auth_data": {"account_id": "abc"},  # dict from jsonb codec
                "display_name": "J",
                "email": "j@e",
                "created_at": None,
            },
        ])
        results = await service.get_all_identities("user-123")
        assert len(results) == 2
        providers = {r["auth_provider"] for r in results}
        assert providers == {"telegram", "jira"}
        # auth_data always decoded to dict
        for r in results:
            assert isinstance(r["auth_data"], dict)

    async def test_get_all_empty(self, service, mock_pool_and_conn):
        _, conn = mock_pool_and_conn
        conn.fetch = AsyncMock(return_value=[])
        results = await service.get_all_identities("user-123")
        assert results == []


class TestDeleteIdentity:
    async def test_delete_executes_sql(self, service, mock_pool_and_conn):
        _, conn = mock_pool_and_conn
        await service.delete_identity("user-123", "jira")
        args = conn.execute.call_args[0]
        assert "DELETE FROM auth.user_identities" in args[0]
        assert args[1] == "user-123"
        assert args[2] == "jira"
