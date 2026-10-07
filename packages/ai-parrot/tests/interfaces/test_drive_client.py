"""FEAT-608 TASK-3807 — DriveClient + get_drive_client promotion."""

import pytest

import parrot.interfaces.google as google_mod
from parrot.interfaces.google import DriveClient, GoogleClient


class _Files:
    def __getattr__(self, name):
        return lambda **kw: ("files", name, kw)


class _Api:
    files = _Files()


class _FakeAiogoogle:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.discovered = []
        self.sent = []
        self.entered = 0
        self.exited = 0
        _FakeAiogoogle.instances.append(self)

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *a):
        self.exited += 1

    async def discover(self, name, version=None):
        self.discovered.append((name, version))
        return _Api()

    async def as_service_account(self, req, **kw):
        self.sent.append(("sa", req, kw))
        return {"via": "sa"}

    async def as_user(self, req, **kw):
        self.sent.append(("user", req, kw))
        return {"via": "user"}


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    _FakeAiogoogle.instances = []
    monkeypatch.setattr(google_mod, "Aiogoogle", _FakeAiogoogle)


def _client(auth_type: str = "service_account") -> GoogleClient:
    c = GoogleClient.__new__(GoogleClient)
    c._authenticated = True
    c.auth_type = auth_type
    c._service_account_creds = "SA" if auth_type == "service_account" else None
    c._user_creds = "USER" if auth_type == "user" else None
    return c


async def test_drive_client_open_is_idempotent_and_discovers_once():
    d = DriveClient(_client())
    await d.open()
    await d.open()
    assert len(_FakeAiogoogle.instances) == 1
    ag = _FakeAiogoogle.instances[0]
    assert ag.discovered == [("drive", "v3")]
    assert ag.kwargs == {"service_account_creds": "SA", "user_creds": None}
    await d.close()
    await d.close()
    assert ag.exited == 1
    with pytest.raises(RuntimeError):
        _ = d.api


async def test_drive_client_dispatches_service_account_vs_user():
    async with DriveClient(_client("service_account")) as d:
        assert await d.files_get("x", fields="id") == {"via": "sa"}
    async with DriveClient(_client("user")) as d:
        assert await d.files_get("x", fields="id") == {"via": "user"}


async def test_drive_client_send_raw_authorises_request():
    async with DriveClient(_client()) as d:
        res = await d.send_raw("REQ", raise_for_status=False)
    assert res == {"via": "sa"}
    assert _FakeAiogoogle.instances[0].sent == [("sa", "REQ", {"full_res": True, "raise_for_status": False})]


async def test_get_drive_client_returns_drive_client():
    d = await _client().get_drive_client()
    assert isinstance(d, DriveClient)
    assert d.version == "v3"


def test_aiogoogle_credentials_requires_initialised():
    c = _client()
    c._authenticated = False
    with pytest.raises(RuntimeError):
        c.aiogoogle_credentials()


async def test_files_list_maps_params_and_supports_all_drives():
    async with DriveClient(_client()) as d:
        await d.files_list(q="q", fields="f", page_size=5, page_token="t", order_by="name", drive_id="D", pageExtra=1)
    req = _FakeAiogoogle.instances[0].sent[0][1]
    assert req == (
        "files",
        "list",
        {
            "q": "q",
            "fields": "f",
            "pageSize": 5,
            "pageToken": "t",
            "orderBy": "name",
            "driveId": "D",
            "pageExtra": 1,
            "supportsAllDrives": True,
        },
    )
    async with DriveClient(_client(), supports_all_drives=False) as d:
        await d.files_update("i", {"name": "n"}, fields="id", add_parents="a", remove_parents="b")
    req = _FakeAiogoogle.instances[1].sent[0][1]
    assert req[2] == {"fileId": "i", "fields": "id", "json": {"name": "n"}, "addParents": "a", "removeParents": "b"}
