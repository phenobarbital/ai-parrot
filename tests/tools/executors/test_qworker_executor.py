"""Tests for QworkerToolExecutor — both HTTP (Qclient) and Redis transports.

The Qworker service itself is not available in CI. We exercise the
executor against:

* A fake ``Qclient`` (just an object with an async ``run`` method) for
  the happy path of the HTTP transport.
* A monkey-patched ``aiohttp.ClientSession`` for the HTTP fallback path
  used when no Qclient package is installed.
* A fake Redis client for the Streams transport.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.tools.executors import ToolExecutionEnvelope
from parrot.tools.executors.qworker import QworkerToolExecutor


class _FakeQclient:
    """Stand-in Qclient with a single async ``run`` method."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def run(self, payload: dict) -> dict:
        self.calls.append(payload)
        return self.response


def _make_envelope() -> ToolExecutionEnvelope:
    return ToolExecutionEnvelope(
        tool_import_path="tests.tools.executors._fixtures:EchoTool",
        tool_init_kwargs={},
        arguments={"msg": "ping"},
        timeout_seconds=10,
    )


@pytest.mark.asyncio
async def test_http_transport_uses_provided_qclient():
    qclient = _FakeQclient(
        response={"success": True, "status": "success", "result": "echo:ping", "metadata": {}}
    )
    ex = QworkerToolExecutor(transport="http", qclient=qclient)
    result = await ex.execute(_make_envelope())
    assert result.status == "success"
    assert result.result == "echo:ping"
    # Executor stamps its identity in metadata.
    assert result.metadata.get("executor") == "qworker"
    assert result.metadata.get("transport") == "http"
    # Qclient.run got the dumped envelope dict.
    assert qclient.calls and qclient.calls[0]["tool_import_path"].endswith("EchoTool")


@pytest.mark.asyncio
async def test_http_transport_handles_qclient_timeout():
    class _SlowQclient:
        async def run(self, payload):
            import asyncio

            await asyncio.sleep(10)

    ex = QworkerToolExecutor(transport="http", qclient=_SlowQclient())
    env = _make_envelope().model_copy(update={"timeout_seconds": 0})
    result = await ex.execute(env)
    assert result.status == "error"
    assert "timeout" in (result.error or "").lower() or "did not respond" in (
        result.error or ""
    )


@pytest.mark.asyncio
async def test_http_transport_rejects_non_toolresult_payload():
    ex = QworkerToolExecutor(transport="http", qclient=_FakeQclient(response={"foo": "bar"}))
    result = await ex.execute(_make_envelope())
    assert result.status == "error"
    assert "not a ToolResult" in (result.error or "")


@pytest.mark.asyncio
async def test_http_aiohttp_fallback_when_no_qclient(monkeypatch):
    """When no Qclient is installed and endpoint is set, aiohttp is used."""
    # Pretend the qclient and qworker.client modules do not exist by
    # making the executor's discovery fail.
    ex = QworkerToolExecutor(
        transport="http",
        endpoint="http://qworker.test",
        qclient=None,
    )

    # Force the discovery path to return None (no client installed).
    async def _no_qclient(self):
        return None

    monkeypatch.setattr(
        QworkerToolExecutor, "_build_qclient", _no_qclient, raising=True
    )

    captured = {}

    class _FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def json(self):
            return {
                "success": True,
                "status": "success",
                "result": "echo:ping",
                "metadata": {},
            }

        async def text(self):
            return ""

    class _FakeSession:
        def __init__(self, *args, **kwargs):
            captured["session_kwargs"] = kwargs

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            captured["headers"] = kwargs.get("headers")
            return _FakeResponse()

        async def close(self):
            captured["closed"] = True

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", _FakeSession)

    result = await ex.execute(_make_envelope())
    assert result.status == "success"
    assert captured["url"] == "http://qworker.test/run"
    assert captured["json"]["tool_import_path"].endswith("EchoTool")


@pytest.mark.asyncio
async def test_redis_transport_publishes_and_reads_result():
    """The Redis transport posts to a stream and reads from a result stream."""

    class _FakeRedis:
        def __init__(self):
            self.published: list[dict] = []
            self._result_to_return: dict | None = None

        async def xadd(self, stream, fields):
            self.published.append({"stream": stream, "fields": fields})
            # When the executor publishes, queue up a matching reply.
            job_id = fields["job_id"]
            self._result_to_return = {
                "stream": "parrot:tool_results",
                "entry_id": "1-0",
                "fields": {
                    "job_id": job_id,
                    "result": json.dumps(
                        {
                            "success": True,
                            "status": "success",
                            "result": "from-redis",
                            "metadata": {},
                        }
                    ),
                },
            }
            return "1-0"

        async def xread(self, streams, count=0, block=0):
            if self._result_to_return is None:
                return None
            r = self._result_to_return
            self._result_to_return = None
            return [(r["stream"], [(r["entry_id"], r["fields"])])]

        async def aclose(self):
            return None

    fake = _FakeRedis()

    ex = QworkerToolExecutor(transport="redis", redis_url="redis://ignored")
    # Inject the fake redis through the protected ensure-hook.
    ex._redis = fake

    result = await ex.execute(_make_envelope())
    assert result.status == "success"
    assert result.result == "from-redis"
    assert fake.published and fake.published[0]["stream"] == "parrot:tool_tasks"
    assert "job_id" in result.metadata


@pytest.mark.asyncio
async def test_redis_transport_times_out_when_no_result():
    import asyncio

    class _SilentRedis:
        async def xadd(self, *args, **kwargs):
            return "1-0"

        async def xread(self, streams, count=0, block=0):
            # Mirror real Redis xread blocking semantics so the
            # caller's asyncio.wait_for can interrupt this loop.
            await asyncio.sleep(block / 1000 if block else 0.05)
            return None

        async def aclose(self):
            return None

    ex = QworkerToolExecutor(transport="redis", redis_url="redis://ignored")
    ex._redis = _SilentRedis()

    env = _make_envelope().model_copy(update={"timeout_seconds": 1})
    result = await ex.execute(env)
    assert result.status == "error"
    assert "Redis result" in (result.error or "")
    await ex.close()


def test_invalid_transport_raises():
    with pytest.raises(ValueError):
        QworkerToolExecutor(transport="grpc")  # type: ignore[arg-type]
