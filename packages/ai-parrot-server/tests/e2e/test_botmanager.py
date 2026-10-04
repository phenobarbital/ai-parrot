"""Process-boundary BotManager scenarios for the deterministic E2E plan."""

from __future__ import annotations

import aiohttp
import pytest

from parrot.e2e.models import TargetConfig
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets import botmanager
from parrot.e2e.targets.botmanager import build_botmanager_adapter


@pytest.mark.e2e
async def test_authenticated_minimal_profile(e2e_supervisor_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise anonymous denial and the private-Redis cookie round trip.

    A missing ``redis-server`` is deliberately allowed to propagate as
    ``E2EPrerequisiteError`` from ``supervisor.start``.  The deterministic
    runner records that typed error as BLOCKED rather than treating this
    required authentication scenario as a passing skip.
    """
    bootstrap_secret = "e2e-test-bootstrap-secret"
    monkeypatch.setattr(botmanager.secrets, "token_urlsafe", lambda _size: bootstrap_secret)
    adapter = build_botmanager_adapter()
    supervisor: E2ESupervisor = e2e_supervisor_factory(lambda _kind: adapter)
    state = await supervisor.start("botmanager-auth", TargetConfig(kind="botmanager", startup_timeout_s=30))

    try:
        endpoint = adapter._endpoints[state.run_id]
        base_url = f"http://{endpoint.host}:{endpoint.port}"
        timeout = aiohttp.ClientTimeout(total=10)
        cookie_jar = aiohttp.CookieJar(unsafe=True)

        async with aiohttp.ClientSession(timeout=timeout, cookie_jar=cookie_jar) as session:
            async with session.get(f"{base_url}/e2e/protected/bot") as response:
                assert response.status == 401
                assert await response.json() == {"anonymous": True}

            async with session.get(
                f"{base_url}/e2e/protected/bot", headers={"Cookie": "csrf_secure=not-valid-json-or-encrypted"}
            ) as response:
                assert response.status == 401
                assert await response.json() == {"error": "invalid_session"}

            async with session.post(f"{base_url}/e2e/bootstrap-login") as response:
                assert response.status == 403

            async with session.post(
                f"{base_url}/e2e/bootstrap-login", headers={"Authorization": f"Bearer {bootstrap_secret}"}
            ) as response:
                assert response.status == 200
                assert "session_id" in await response.json()

            async with session.get(f"{base_url}/e2e/protected/bot") as response:
                assert response.status == 200
                assert await response.json() == {"bot": None, "user_id": "e2e-test-user-3518"}
    finally:
        final_state = await supervisor.stop(state.run_id)
        assert final_state.status == "stopped"
        assert final_state.cleanup_complete is True


@pytest.mark.e2e
async def test_botmanager_offline_boot(e2e_supervisor_factory, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Boot the minimal child with an empty tokenizer cache and loopback-only traffic.

    The child imports the real target entry point.  It is intentionally not
    supplied a provider credential or an injected module stub: readiness
    only uses its private Redis and loopback HTTP endpoints.  If Redis is
    absent, startup raises the typed BLOCKED prerequisite error.
    """
    cache_dir = tmp_path / "empty-tiktoken-cache"
    cache_dir.mkdir()
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    adapter = build_botmanager_adapter()
    supervisor: E2ESupervisor = e2e_supervisor_factory(lambda _kind: adapter)
    state = await supervisor.start("botmanager-offline", TargetConfig(kind="botmanager", startup_timeout_s=30))

    try:
        endpoint = adapter._endpoints[state.run_id]
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(f"http://{endpoint.host}:{endpoint.port}/healthz") as response:
                assert response.status == 200
                assert await response.json() == {"status": "ok", "name": f"e2e-botmanager-{state.run_id}"}
        assert not any(cache_dir.iterdir())
    finally:
        final_state = await supervisor.stop(state.run_id)
        assert final_state.status == "stopped"
        assert final_state.cleanup_complete is True
