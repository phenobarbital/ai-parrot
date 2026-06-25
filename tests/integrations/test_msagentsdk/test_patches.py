"""
Unit tests for the MS Agent SDK runtime patches.

Covers the MCS connector patch that makes Copilot Studio's (pva-studio) reply
path tolerate the runtime's empty / non-JSON 200 acknowledgement instead of
crashing with ``aiohttp.ContentTypeError``.
"""
import json
import pytest


class _FakeResp:
    """Minimal aiohttp-response stand-in usable as an async context manager."""

    def __init__(self, status, body):
        self.status = status
        self._body = body
        self.raised = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self):
        return self._body

    def raise_for_status(self):
        self.raised = True
        raise RuntimeError("HTTP error")


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp

    def post(self, *args, **kwargs):
        return self._resp


@pytest.fixture
def conversations(monkeypatch):
    """A patched ``MCSConversations`` bound to a fake client (set per-test)."""
    from parrot.integrations.msagentsdk._patches import (
        patch_mcs_connector_empty_response,
    )

    patch_mcs_connector_empty_response()
    from microsoft_agents.hosting.core.connector.mcs.mcs_connector_client import (
        MCSConversations,
    )

    def _make(body, status=200):
        return MCSConversations(_FakeClient(_FakeResp(status, body)), "http://x")

    return _make


def _activity():
    from microsoft_agents.activity import Activity

    return Activity(type="message", text="hi")


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"   ", b"not json", b"<html>oops</html>"])
async def test_empty_or_non_json_200_is_tolerated(conversations, body):
    """A 200 with an empty / non-JSON body returns an empty ResourceResponse."""
    conv = conversations(body)
    resp = await conv.send_to_conversation("c1", _activity())
    assert resp.id is None


@pytest.mark.asyncio
async def test_valid_json_200_is_parsed(conversations):
    """A 200 with a JSON body is parsed into the ResourceResponse."""
    conv = conversations(json.dumps({"id": "abc"}).encode())
    resp = await conv.send_to_conversation("c1", _activity())
    assert resp.id == "abc"


@pytest.mark.asyncio
async def test_http_error_still_raises(conversations):
    """A >= 300 status still raises (real delivery failure is not swallowed)."""
    conv = conversations(b"", status=502)
    with pytest.raises(RuntimeError):
        await conv.send_to_conversation("c1", _activity())


@pytest.mark.asyncio
async def test_none_activity_rejected(conversations):
    """A None activity is rejected before any network call."""
    conv = conversations(b"")
    with pytest.raises(ValueError):
        await conv.send_to_conversation("c1", None)


def test_patch_is_idempotent():
    """Applying the patch repeatedly is safe."""
    from parrot.integrations.msagentsdk._patches import (
        patch_mcs_connector_empty_response,
    )

    patch_mcs_connector_empty_response()
    patch_mcs_connector_empty_response()
