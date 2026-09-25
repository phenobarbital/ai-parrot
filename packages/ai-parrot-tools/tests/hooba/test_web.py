"""FEAT-602 TASK-3738 — web adapter and catalog seeding (no real browser)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.hooba.web import HoobaWebAdapter, seed_catalog


async def _resolver(action: Any) -> None:
    """Return no credentials for the fake adapter tests."""
    return None


def test_adapter_is_lazy(tmp_path: Any) -> None:
    """Constructing the adapter does not construct its toolkit."""
    adapter = HoobaWebAdapter(tmp_path, _resolver)

    assert adapter.started is False


@pytest.mark.asyncio
async def test_recover_session_returns_sid(tmp_path: Any) -> None:
    """Recovery exports the requested context-level sid cookie."""
    adapter = HoobaWebAdapter(tmp_path, _resolver)
    driver = MagicMock()
    driver.get_cookies = AsyncMock(return_value=[{"name": "sid", "value": "v", "httpOnly": True}])
    toolkit = MagicMock()
    toolkit.run_site_action = AsyncMock(return_value={"success": True})
    toolkit._ensure_session_driver = AsyncMock(return_value=driver)
    adapter._toolkit = toolkit

    assert await adapter.recover_session() == {"sid": "v"}
    driver.get_cookies.assert_awaited_once_with(["https://api.hooba.com", "https://app.hooba.com"])


@pytest.mark.asyncio
async def test_recover_session_fails_closed(tmp_path: Any) -> None:
    """Login failure, unsupported cookies, and missing sid all fail closed."""
    adapter = HoobaWebAdapter(tmp_path, _resolver)
    toolkit = MagicMock()
    toolkit.run_site_action = AsyncMock(return_value={"success": False})
    adapter._toolkit = toolkit
    assert await adapter.recover_session() == {}

    toolkit.run_site_action = AsyncMock(return_value={"success": True})
    toolkit._ensure_session_driver = AsyncMock(side_effect=NotImplementedError)
    assert await adapter.recover_session() == {}

    driver = MagicMock()
    driver.get_cookies = AsyncMock(return_value=[{"name": "other", "value": "v"}])
    toolkit._ensure_session_driver = AsyncMock(return_value=driver)
    assert await adapter.recover_session() == {}


@pytest.mark.asyncio
async def test_run_navigation_refuses_non_navigation(tmp_path: Any) -> None:
    """Non-navigation catalog actions never reach the execution method."""
    adapter = HoobaWebAdapter(tmp_path, _resolver)
    toolkit = MagicMock()
    toolkit.get_site_action = AsyncMock(return_value={"kind": "composite"})
    toolkit.run_site_action = AsyncMock()
    adapter._toolkit = toolkit

    assert await adapter.run_navigation("not-navigation") == {
        "status": "error",
        "error": "only navigation actions are allowed",
    }
    toolkit.run_site_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_seed_catalog_writes_login_and_sections_without_secrets(tmp_path: Any, monkeypatch: Any) -> None:
    """Seeded JSON contains the broker provider but no environment secrets."""
    monkeypatch.setenv("HOOBA_USERNAME", "sentinel-user")
    monkeypatch.setenv("HOOBA_PASSWORD", "sentinel-password")

    assert await seed_catalog(tmp_path) == "hooba"
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 4
    payloads = [path.read_text() for path in files]
    assert all("sentinel-user" not in payload and "sentinel-password" not in payload for payload in payloads)
    login = next(path for path in files if path.name == "hooba-login.json").read_text()
    assert '"credential_provider": "hooba"' in login
    for path in files:
        if path.name not in {"_site.json", "hooba-login.json"}:
            assert '"requires": ["hooba-login"]' in path.read_text()
