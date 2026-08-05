"""TASK-2138: WorkdayRestClient — REST /ccx/api client on aiohttp."""
from __future__ import annotations

import time

import pytest
from aiohttp import web
from parrot_tools.interfaces.workday.config import WorkdayConfig
from parrot_tools.interfaces.workday.rest import WorkdayRestClient, WorkdayRestError


def _make_config(base_url: str, tenant: str = "testtenant") -> WorkdayConfig:
    return WorkdayConfig(
        client_id="cid",
        client_secret="secret",
        token_url=f"{base_url.rstrip('/')}/token",
        refresh_token="refresh",
        tenant=tenant,
        workday_url=base_url.rstrip("/"),
    )


class TestTokenHandling:
    async def test_token_cached_until_expiry(self, aiohttp_server):
        calls = {"n": 0}

        async def token_handler(request):
            calls["n"] += 1
            return web.json_response({"access_token": "tok", "expires_in": 300})

        app = web.Application()
        app.router.add_post("/token", token_handler)
        server = await aiohttp_server(app)

        client = WorkdayRestClient(config=_make_config(str(server.make_url(""))))
        try:
            t1 = await client.get_token()
            t2 = await client.get_token()
        finally:
            await client.close()

        assert t1 == t2 == "tok"
        assert calls["n"] == 1  # second call reused the cached bearer

    async def test_token_refreshed_before_expiry(self, aiohttp_server):
        calls = {"n": 0}

        async def token_handler(request):
            calls["n"] += 1
            return web.json_response({"access_token": f"tok-{calls['n']}", "expires_in": 300})

        app = web.Application()
        app.router.add_post("/token", token_handler)
        server = await aiohttp_server(app)

        client = WorkdayRestClient(config=_make_config(str(server.make_url(""))))
        try:
            t1 = await client.get_token()
            assert calls["n"] == 1
            client._token_expires_at = time.monotonic() - 1  # simulate near-expiry
            t2 = await client.get_token()
        finally:
            await client.close()

        assert calls["n"] == 2
        assert t1 != t2

    async def test_401_reauthenticates_exactly_once(self, aiohttp_server):
        token_calls = {"n": 0}
        endpoint_calls = {"n": 0}

        async def token_handler(request):
            token_calls["n"] += 1
            return web.json_response({"access_token": f"tok-{token_calls['n']}", "expires_in": 300})

        async def workers_handler(request):
            endpoint_calls["n"] += 1
            if endpoint_calls["n"] == 1:
                return web.json_response({"error": "unauthorized"}, status=401)
            return web.json_response({"data": [{"id": "WID1", "descriptor": "Alice"}]})

        app = web.Application()
        app.router.add_post("/token", token_handler)
        app.router.add_get("/ccx/api/v1/testtenant/workers", workers_handler)
        server = await aiohttp_server(app)

        client = WorkdayRestClient(config=_make_config(str(server.make_url(""))))
        client.set_token("stale-cached-token", expires_in=300)  # already "valid" client-side
        try:
            result = await client.find_worker("Alice")
        finally:
            await client.close()

        assert result == [{"id": "WID1", "descriptor": "Alice"}]
        assert endpoint_calls["n"] == 2  # first 401, then a single retry
        assert token_calls["n"] == 1  # exactly one re-authentication


class TestEndpoints:
    async def test_find_worker_returns_wid_rows(self, aiohttp_server):
        async def token_handler(request):
            return web.json_response({"access_token": "tok", "expires_in": 300})

        async def workers_handler(request):
            assert request.query.get("search") == "Alice"
            return web.json_response(
                {"data": [{"id": "9d1b2b405cca010fe5b8b3a05e9a0000", "descriptor": "Alice Smith"}]}
            )

        app = web.Application()
        app.router.add_post("/token", token_handler)
        app.router.add_get("/ccx/api/v1/testtenant/workers", workers_handler)
        server = await aiohttp_server(app)

        client = WorkdayRestClient(config=_make_config(str(server.make_url(""))))
        try:
            result = await client.find_worker("Alice")
        finally:
            await client.close()

        assert result[0]["id"] == "9d1b2b405cca010fe5b8b3a05e9a0000"
        assert result[0]["descriptor"] == "Alice Smith"

    async def test_time_clock_events_requires_wid(self, aiohttp_server):
        async def token_handler(request):
            return web.json_response({"access_token": "tok", "expires_in": 300})

        async def clock_events_handler(request):
            return web.json_response({"error": "not found"}, status=400)

        app = web.Application()
        app.router.add_post("/token", token_handler)
        app.router.add_get(
            "/ccx/api/timeTracking/v5/testtenant/timeClockEvents", clock_events_handler
        )
        server = await aiohttp_server(app)

        client = WorkdayRestClient(config=_make_config(str(server.make_url(""))))
        try:
            with pytest.raises(WorkdayRestError, match="WID"):
                await client.get_time_clock_events("123456")  # Employee_ID, not a WID
        finally:
            await client.close()

    async def test_find_time_clock_event_matches_reference_id(self, aiohttp_server):
        async def token_handler(request):
            return web.json_response({"access_token": "tok", "expires_in": 300})

        async def clock_events_handler(request):
            return web.json_response(
                {
                    "data": [
                        {"reference_ID": "evt-1", "eventType": "In"},
                        {"reference_ID": "evt-2", "eventType": "Out"},
                    ]
                }
            )

        app = web.Application()
        app.router.add_post("/token", token_handler)
        app.router.add_get(
            "/ccx/api/timeTracking/v5/testtenant/timeClockEvents", clock_events_handler
        )
        server = await aiohttp_server(app)

        client = WorkdayRestClient(config=_make_config(str(server.make_url(""))))
        try:
            event = await client.find_time_clock_event("WID1", "evt-2")
            missing = await client.find_time_clock_event("WID1", "evt-does-not-exist")
        finally:
            await client.close()

        assert event is not None
        assert event["eventType"] == "Out"
        assert missing is None


class TestLifecycle:
    async def test_close_leaves_no_open_session(self, aiohttp_server):
        async def token_handler(request):
            return web.json_response({"access_token": "tok", "expires_in": 300})

        app = web.Application()
        app.router.add_post("/token", token_handler)
        server = await aiohttp_server(app)

        client = WorkdayRestClient(config=_make_config(str(server.make_url(""))))
        await client.get_token()  # opens the lazily-created session
        assert client._session is not None
        assert not client._session.closed

        await client.close()
        assert client._session is None

    def test_module_does_not_import_httpx(self):
        import parrot_tools.interfaces.workday.rest as mod

        with open(mod.__file__) as fh:
            src = fh.read()
        assert "httpx" not in src
        assert "requests" not in src


class TestEnvironmentSelector:
    def test_base_url_honors_environment_selector(self, monkeypatch):
        from parrot_tools.interfaces.workday import config as config_module

        monkeypatch.setattr(
            config_module, "WORKDAY_TOKEN_URL_IMPL", "https://impl.example.com/oauth/token"
        )
        cfg = WorkdayConfig(env="sandbox")
        client = WorkdayRestClient(config=cfg)
        assert client.base_url == "https://impl.example.com/ccx/api"
