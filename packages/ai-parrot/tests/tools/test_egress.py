"""PA-13: the egress guard refuses private targets before any request reaches them (real local aiohttp servers)."""

from __future__ import annotations

import aiohttp
import pytest
from aiohttp import web
from aiohttp.abc import AbstractResolver

import parrot.tools.egress as egress

pytestmark = pytest.mark.asyncio

PUBLIC_FOR_TEST = {"127.0.0.1"}  # the one loopback address the test pretends is public (the "outside" server)


@pytest.fixture(autouse=True)
def _allow_one_loopback(monkeypatch):
    real = egress.is_public_address
    monkeypatch.setattr(egress, "is_public_address", lambda a: a in PUBLIC_FOR_TEST or real(a))
    yield
    egress.configure(False)


class _Server:
    def __init__(self, host: str) -> None:
        self.host, self.hits, self.runner, self.port = host, [], None, 0

    async def start(self, redirect_to: str | None = None) -> "_Server":
        async def handler(request: web.Request):
            self.hits.append(request.path_qs)
            if redirect_to:
                raise web.HTTPFound(redirect_to)
            return web.Response(text="ok")

        app = web.Application()
        app.router.add_get("/{tail:.*}", handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    async def stop(self) -> None:
        await self.runner.cleanup()


@pytest.fixture
async def servers():
    made: list[_Server] = []

    async def make(host: str, **kw) -> _Server:
        s = await _Server(host).start(**kw)
        made.append(s)
        return s

    yield make
    for s in made:
        await s.stop()


class _FakeResolver(AbstractResolver):
    """Answers a script of addresses, one per lookup."""

    def __init__(self, answers: list[str], port: int = 0) -> None:
        self.answers, self.calls, self.port = list(answers), 0, port

    async def resolve(self, host, port=0, family=0):
        addr = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return [{"hostname": host, "host": addr, "port": port, "family": 2, "proto": 0, "flags": 0}]

    async def close(self):
        return None


async def test_a_literal_private_address_is_refused_with_zero_requests(servers):
    private = await servers("127.0.0.2")
    egress.configure(True)
    async with egress.egress_session() as session:
        with pytest.raises(egress.EgressBlocked):
            await session.get(private.url)
    assert private.hits == []


async def test_localhost_and_numeric_encodings_are_refused():
    for url in ("http://localhost:1/", "http://127.0.0.2:1/", "http://2130706434:1/", "http://0x7f000002:1/",
                "http://169.254.169.254/latest/meta-data/", "http://[::1]:1/", "http://10.0.0.5/"):
        with pytest.raises(egress.EgressBlocked):
            egress.check_url(url)
    egress.check_url("https://example.com/")


# 127.0.0.1 is the test's stand-in for "public" (autouse fixture above), so the loopback spellings use 127.0.0.2.
BYPASS_VECTORS = [
    "http://127.2/", "http://0x7f.0.0.2/", "http://0177.0.0.2/", "http://0x7f000002/", "http://017700000002/",
    "http://127.0.0.2./", "http://localhost./", "http://LOCALHOST/", "http://foo.localhost/",
    "http://metadata.google.internal/", "http://metadata.google.internal./", "http://api.default.svc/",
    "http://db.cluster.local/", "http://printer.local/", "http://0/", "http://0.0.0.0/", "http://[::ffff:127.0.0.2]/",
    "http://\uff11\uff12\uff17.\uff10.\uff10.\uff12/",          # full-width digits fold to 127.0.0.2
    "http://127.0.0.1\\@example.com/",                           # backslash: parsers disagree about the host
    "http://169.254.169.254./latest/meta-data/", "http://2852039166/",
]


@pytest.mark.parametrize("url", BYPASS_VECTORS)
def test_browser_navigation_bypass_vectors_are_refused(url):
    with pytest.raises(egress.EgressBlocked):
        egress.check_url(url)


@pytest.mark.parametrize("url", ["https://example.com/", "http://93.184.216.34/", "https://sub.example.org:8443/a?b=c"])
def test_public_urls_pass_the_canonical_check(url):
    egress.check_url(url)


async def test_resolve_check_refuses_a_name_that_resolves_to_a_private_address():
    class Answers(egress.AbstractResolver):
        def __init__(self, address):
            self.address = address

        async def resolve(self, host, port=0, family=0):
            return [{"hostname": host, "host": self.address, "port": port, "family": family, "proto": 0, "flags": 0}]

        async def close(self):
            pass

    with pytest.raises(egress.EgressBlocked):
        await egress.resolve_check("http://rebind.example.com/", resolver=egress.GuardedResolver(Answers("10.1.2.3")))
    await egress.resolve_check("http://ok.example.com/", resolver=egress.GuardedResolver(Answers("93.184.216.34")))


async def test_a_redirect_to_an_internal_address_is_refused(servers):
    internal = await servers("127.0.0.2")
    outside = await servers("127.0.0.1", redirect_to=internal.url + "secret")
    egress.configure(True)
    async with egress.egress_session() as session:
        with pytest.raises(egress.EgressBlocked):
            await session.get(outside.url)
    assert outside.hits == ["/"]
    assert internal.hits == []


async def test_a_name_resolving_to_a_private_address_is_refused(servers):
    internal = await servers("127.0.0.2")
    resolver = egress.GuardedResolver(_FakeResolver(["127.0.0.2"]))
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=resolver)) as session:
        with pytest.raises(aiohttp.ClientConnectorError):
            await session.get(f"http://intranet.test:{internal.port}/")
    assert internal.hits == []


async def test_a_mixed_answer_is_refused_whole():
    class Mixed(_FakeResolver):
        async def resolve(self, host, port=0, family=0):
            return [
                {"hostname": host, "host": "127.0.0.1", "port": port, "family": 2, "proto": 0, "flags": 0},
                {"hostname": host, "host": "10.1.2.3", "port": port, "family": 2, "proto": 0, "flags": 0},
            ]

    with pytest.raises(egress.EgressBlocked):
        await egress.GuardedResolver(Mixed([])).resolve("mixed.test", 80)


async def test_dns_rebinding_connects_only_to_the_address_that_was_checked(servers):
    first = await servers("127.0.0.1")
    second = await servers("127.0.0.2")
    resolver = egress.GuardedResolver(_FakeResolver(["127.0.0.1", "127.0.0.2"]))
    connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False, force_close=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(f"http://rebind.test:{first.port}/") as resp:
            assert resp.status == 200
        with pytest.raises(aiohttp.ClientConnectorError):
            await session.get(f"http://rebind.test:{second.port}/")
    assert first.hits == ["/"]
    assert second.hits == []


async def test_guard_off_leaves_the_plain_session(servers):
    private = await servers("127.0.0.2")
    assert egress.is_enabled() is False
    async with egress.egress_session() as session:
        async with session.get(private.url) as resp:
            assert resp.status == 200
    assert private.hits == ["/"]
