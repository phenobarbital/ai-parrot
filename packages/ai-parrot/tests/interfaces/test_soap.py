"""Unit tests for parrot.interfaces.soap.SOAPClient lifecycle.

Regression coverage for FEAT-415 (Workday flowtask homologation): the
flowtask ``SOAPClient`` supports ``async with client:`` and consumer code —
including the ``WorkdayService`` docstring example — relies on it. The parrot
port shipped only ``start()``/``close()``, so swapping the import broke every
``async with svc:`` call site with ``TypeError: 'WorkdayService' object does
not support the asynchronous context manager protocol``.

These tests exercise the real protocol methods rather than mocking them, and
pin the teardown guarantees (idempotent ``close()``, cleanup when ``start()``
itself fails) that a drop-in replacement has to hold.
"""
from __future__ import annotations

import pytest

# soap.py imports zeep at module level; zeep ships only with the optional
# extras (agents / workday), so skip cleanly on a bare install.
pytest.importorskip("zeep", reason="requires the zeep[async] optional extra")

from parrot.interfaces.soap import SOAPClient

CREDENTIALS = {
    "client_id": "cid",
    "client_secret": "secret",
    "token_url": "https://example.test/oauth/token",
    "wsdl_path": "/tmp/fake.wsdl",
    "refresh_token": "refresh",
}


class _RecordingClient(SOAPClient):
    """SOAPClient whose start/close only record their invocation order."""

    def __init__(self, *, fail_start: bool = False, **kwargs) -> None:
        super().__init__(credentials=CREDENTIALS, **kwargs)
        self.calls: list[str] = []
        self._fail_start = fail_start

    async def start(self) -> None:
        self.calls.append("start")
        if self._fail_start:
            raise RuntimeError("token endpoint unreachable")

    async def close(self) -> None:
        self.calls.append("close")


class _FakeSession:
    """Stand-in for the httpx.AsyncClient held by the Zeep transport."""

    def __init__(self) -> None:
        self.aclose_calls = 0

    async def aclose(self) -> None:
        self.aclose_calls += 1


class _FakeTransport:
    def __init__(self) -> None:
        self.session = _FakeSession()


class _FakeRedis:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class TestAsyncContextManagerProtocol:
    def test_protocol_methods_exist(self):
        """The flowtask surface consumer code binds against."""
        assert hasattr(SOAPClient, "__aenter__")
        assert hasattr(SOAPClient, "__aexit__")

    async def test_async_with_starts_then_closes(self):
        client = _RecordingClient()

        async with client as entered:
            assert entered is client
            assert client.calls == ["start"]

        assert client.calls == ["start", "close"]

    async def test_exception_inside_block_still_closes_and_propagates(self):
        client = _RecordingClient()

        with pytest.raises(ValueError, match="inner"):
            async with client:
                raise ValueError("inner")

        assert client.calls == ["start", "close"]

    async def test_subclass_start_taking_kwargs_is_callable(self):
        """``WorkdayService.start`` is declared ``start(self, **_kwargs)``, so
        __aenter__ must call start() with no positional arguments."""

        class _KwargsStartClient(SOAPClient):
            def __init__(self) -> None:
                super().__init__(credentials=CREDENTIALS)
                self.started = False

            async def start(self, **_kwargs) -> None:
                self.started = True

            async def close(self) -> None:
                pass

        client = _KwargsStartClient()
        async with client:
            assert client.started

    async def test_failed_start_releases_resources_and_propagates(self):
        """__aexit__ is never called when __aenter__ raises, so __aenter__
        must clean up after a partially-completed start() itself."""
        client = _RecordingClient(fail_start=True)

        with pytest.raises(RuntimeError, match="token endpoint unreachable"):
            async with client:
                pytest.fail("body must not run when start() fails")

        assert client.calls == ["start", "close"]


class TestClose:
    async def test_close_releases_transport_session_and_redis(self):
        client = SOAPClient(credentials=CREDENTIALS)
        transport = _FakeTransport()
        redis = _FakeRedis()
        client._transport = transport
        client._redis = redis

        await client.close()

        assert transport.session.aclose_calls == 1
        assert redis.close_calls == 1

    async def test_close_is_idempotent(self):
        """An explicit close() nested inside an ``async with`` must not
        double-release the session."""
        client = SOAPClient(credentials=CREDENTIALS)
        transport = _FakeTransport()
        redis = _FakeRedis()
        client._transport = transport
        client._redis = redis

        await client.close()
        await client.close()

        assert transport.session.aclose_calls == 1
        assert redis.close_calls == 1

    async def test_close_without_start_is_a_noop(self):
        """Cleanup after a start() that never got as far as opening anything."""
        client = SOAPClient(credentials=CREDENTIALS)

        await client.close()  # must not raise
