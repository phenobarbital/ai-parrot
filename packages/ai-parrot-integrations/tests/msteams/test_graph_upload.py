"""Unit tests for GraphClient.upload_file (TASK-1734)."""

from pathlib import Path

import pytest

from parrot.integrations.msteams.graph import GraphClient

pytestmark = pytest.mark.asyncio


class _FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status = status
        self._payload = payload or {}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return self._text


class _FakeSession:
    def __init__(self, put_resp, post_resp=None):
        self._put_resp = put_resp
        self._post_resp = post_resp
        self.put_calls = []
        self.post_calls = []

    def put(self, url, headers=None, data=None):
        self.put_calls.append((url, headers, data))
        return self._put_resp

    def post(self, url, headers=None, json=None):
        self.post_calls.append((url, headers, json))
        return self._post_resp


def _client(session):
    c = GraphClient(client_id="c", client_secret="s", tenant_id="t")
    c._token = "tok"
    c._token_expiry = 10**12  # far future → cached token used

    async def _fake_get_session():
        return session

    c._get_session = _fake_get_session  # type: ignore[assignment]
    return c


class TestGraphClientUpload:
    async def test_upload_success_returns_reference(self, tmp_path):
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1")
        session = _FakeSession(
            put_resp=_FakeResp(201, {"id": "item-1", "webUrl": "https://drive/item-1"}),
            post_resp=_FakeResp(201, {"link": {"webUrl": "https://share/link-1"}}),
        )
        client = _client(session)
        url = await client.upload_file(f, user="svc@x.com")
        assert url == "https://share/link-1"
        assert "/drive/root:/A2UI-Artifacts/report.pdf:/content" in session.put_calls[0][0]

    async def test_upload_falls_back_to_weburl_when_createlink_fails(self, tmp_path):
        f = tmp_path / "a.html"
        f.write_bytes(b"<html>")
        session = _FakeSession(
            put_resp=_FakeResp(200, {"id": "item-2", "webUrl": "https://drive/item-2"}),
            post_resp=_FakeResp(403, text="Forbidden"),
        )
        client = _client(session)
        url = await client.upload_file(f, user="svc@x.com")
        assert url == "https://drive/item-2"

    async def test_upload_permission_denied_returns_none(self, tmp_path):
        f = tmp_path / "a.pdf"
        f.write_bytes(b"x")
        session = _FakeSession(put_resp=_FakeResp(403, text="insufficient privileges"))
        client = _client(session)
        assert await client.upload_file(f, user="svc@x.com") is None

    async def test_upload_without_token_returns_none(self, tmp_path):
        f = tmp_path / "a.pdf"
        f.write_bytes(b"x")
        client = GraphClient(client_id="c", client_secret="s", tenant_id="t")

        async def _no_token():
            return None

        client._get_access_token = _no_token  # type: ignore[assignment]
        assert await client.upload_file(f, user="svc@x.com") is None

    async def test_upload_missing_file_returns_none(self):
        session = _FakeSession(put_resp=_FakeResp(201, {"id": "x"}))
        client = _client(session)
        assert await client.upload_file(Path("/no/such/file.pdf"), user="svc@x.com") is None
