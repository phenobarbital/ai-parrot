"""Tests for the legacy OAuth2 key audit and its documentation contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.auth.oauth2.legacy_audit import audit_legacy_keys
from parrot.auth.principal import Principal

from ._oauth2_fakes import FakePrincipalResolver, MemRedis


@pytest.mark.asyncio
async def test_legacy_audit_counts() -> None:
    """Count channel-scoped keys while ignoring principal and nonce keys."""
    redis = MemRedis()
    await redis.set("oauth2:jira:telegram:1", "token-1")
    await redis.set("oauth2:jira:telegram:2", "token-2")
    await redis.set("jira:oauth:slack:T:U", "token-3")
    await redis.set("oauth2:jira:1042", "principal-token")
    await redis.set("oauth2:jira:nonce:x", "nonce")
    resolver = FakePrincipalResolver({("telegram", "1"): Principal(user_id="42", channel="telegram", channel_user_id="1")})

    counts = await audit_legacy_keys(redis, resolver, providers=["jira"])

    assert counts == {
        "jira": {
            "slack": {"bound": 0, "unbound": 1},
            "telegram": {"bound": 1, "unbound": 1},
        }
    }


def test_connections_docs_exist() -> None:
    """Document the AC-15 ownership and migration contract."""
    root = Path(__file__).resolve().parents[5]
    connections = (root / "docs/auth/connections.md").read_text()
    ownership = (root / "docs/auth/jira-credential-ownership.md").read_text()

    assert "OAUTH2_LEGACY_KEYS_UNTIL" in connections
    assert "integration:connect" in connections
    assert "integration:disconnect" in connections
    assert "Identity Vault" in ownership
    assert "every 3LO provider" in ownership
