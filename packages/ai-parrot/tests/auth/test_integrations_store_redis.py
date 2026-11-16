"""Tests for Redis-backed OAuth2 integration persistence."""

from datetime import datetime, timezone

import pytest

from parrot.auth.oauth2 import persistence
from parrot.auth.oauth2.models import UsersIntegrationRow
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USERS_INTEGRATIONS
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def redis_integrations(monkeypatch: pytest.MonkeyPatch):
    """Use an isolated Redis prefix and reset the cached integration store."""
    monkeypatch.delenv("INTEGRATIONS_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr(persistence, "_REDIS_STORE", None)
    async with redis_test_settings(monkeypatch):
        yield


def _row(**overrides: object) -> UsersIntegrationRow:
    """Build a valid integration row with optional field overrides."""
    values: dict[str, object] = {
        "user_id": "35",
        "provider": "jira",
        "account_id": "a",
        "display_name": "A",
        "scopes": ["read"],
        "connected_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return UsersIntegrationRow(**values)


async def test_integrations_redis_roundtrip(redis_integrations: None) -> None:
    """Upsert, read, list, and delete an integration through dispatch."""
    updated_at = datetime.now(timezone.utc)
    row = _row(updated_at=updated_at)

    await persistence.upsert_users_integration(row)

    stored = await persistence.get_users_integration("35", "jira")
    assert stored is not None
    assert stored.account_id == "a"
    assert stored.connected_at == row.connected_at
    assert stored.updated_at == updated_at
    assert await persistence.list_users_integrations("35") == [stored]

    await persistence.delete_users_integration("35", "jira")
    assert await persistence.get_users_integration("35", "jira") is None


async def test_invalid_document_skipped(redis_integrations: None, caplog: pytest.LogCaptureFixture) -> None:
    """Malformed Redis documents do not prevent valid integrations from listing."""
    documents = RedisDocumentStore(USERS_INTEGRATIONS)
    await documents.put({"user_id": "35", "provider": "invalid"})
    await persistence.upsert_users_integration(_row())

    rows = await persistence.list_users_integrations("35")

    assert [row.provider for row in rows] == ["jira"]
    assert "Skipping invalid users_integration for user_id=35" in caplog.text
