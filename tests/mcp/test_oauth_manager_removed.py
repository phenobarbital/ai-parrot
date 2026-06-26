"""Tests verifying OAuthManager has been removed from parrot.mcp.oauth (FEAT-262, TASK-1665)."""
import parrot.mcp.oauth as mod


def test_oauth_manager_not_importable():
    """OAuthManager no longer exists in parrot.mcp.oauth."""
    assert not hasattr(mod, "OAuthManager"), (
        "OAuthManager should have been removed in FEAT-262 (TASK-1665). "
        "Use parrot.mcp.oauth2_config.MCPOAuth2Config instead."
    )


def test_token_stores_still_exist():
    """Token store classes are preserved after OAuthManager removal."""
    from parrot.mcp.oauth import (
        TokenStore,
        VaultTokenStore,
        InMemoryTokenStore,
        RedisTokenStore,
    )
    assert TokenStore is not None
    assert VaultTokenStore is not None
    assert InMemoryTokenStore is not None
    assert RedisTokenStore is not None


def test_netsuite_m2m_still_exists():
    """NetSuiteM2MAuth is preserved after OAuthManager removal."""
    from parrot.mcp.oauth import NetSuiteM2MAuth
    assert NetSuiteM2MAuth is not None


def test_in_memory_token_store_functional():
    """InMemoryTokenStore still operates correctly."""
    import asyncio
    from parrot.mcp.oauth import InMemoryTokenStore

    store = InMemoryTokenStore()

    async def run():
        await store.set("user1", "server1", {"access_token": "tok"})
        result = await store.get("user1", "server1")
        assert result == {"access_token": "tok"}
        await store.delete("user1", "server1")
        assert await store.get("user1", "server1") is None

    asyncio.get_event_loop().run_until_complete(run())


def test_helper_functions_preserved():
    """Module-level helper functions _b64url and _now are preserved."""
    assert hasattr(mod, "_b64url"), "_b64url helper should be preserved"
    assert hasattr(mod, "_now"), "_now helper should be preserved"
