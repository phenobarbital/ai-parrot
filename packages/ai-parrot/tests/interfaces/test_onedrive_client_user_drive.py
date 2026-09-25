"""FEAT-603 TASK-3755 — OneDriveClient._resolve_user_drive."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.interfaces.onedrive import OneDriveClient


def _client(*, auth_mode: str = "direct", credentials: dict | None = None) -> OneDriveClient:
    c = OneDriveClient.__new__(OneDriveClient)
    me = SimpleNamespace(
        drive=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id="me-drive", name="OneDrive")))
    )
    # Stable per-user request builders (same object on repeated by_user_id(u) calls) so tests can assert
    # on a specific user's `get` mock without it being silently replaced by a fresh AsyncMock each call.
    user_builders: dict = {}

    def _by_user_id(u):
        if u not in user_builders:
            user_builders[u] = SimpleNamespace(
                drive=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=f"drive-{u}", name="OneDrive")))
            )
        return user_builders[u]

    users = SimpleNamespace(by_user_id=_by_user_id)
    c.__dict__.update(
        credentials=credentials or {},
        auth_mode=auth_mode,
        _graph_client=SimpleNamespace(me=me, users=users),
        _user_drives={},
        _drive_id=None,
        _drive_info=None,
        logger=logging.getLogger("t"),
    )
    return c


async def test_resolve_user_drive_me_and_upn():
    c = _client(auth_mode="password", credentials={"username": "user@tenant.com"})
    me_drive = await c._resolve_user_drive("me")
    assert me_drive.id == "me-drive"
    upn_drive = await c._resolve_user_drive("A@T.com")
    assert upn_drive.id == "drive-A@T.com"


async def test_resolve_user_drive_app_only_me_rejected():
    c = _client(auth_mode="direct", credentials={})
    with pytest.raises(RuntimeError, match="delegated authentication"):
        await c._resolve_user_drive("me")
    c._graph_client.me.drive.get.assert_not_called()


async def test_resolve_user_drive_error_names_permission():
    c = _client(auth_mode="direct", credentials={})
    c._graph_client.users.by_user_id("B@T.com").drive.get.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="Files.ReadWrite.All"):
        await c._resolve_user_drive("B@T.com")


async def test_resolve_user_drive_cache_per_user_and_leaves_drive_id_alone():
    c = _client(auth_mode="password", credentials={"username": "user@tenant.com"})
    first = await c._resolve_user_drive("A@T.com")
    second = await c._resolve_user_drive("C@T.com")
    assert first.id != second.id

    # Second call for the same user makes no additional Graph call.
    get_mock = c._graph_client.users.by_user_id("A@T.com").drive.get
    calls_before = get_mock.call_count
    cached_again = await c._resolve_user_drive("A@T.com")
    assert cached_again is first
    assert get_mock.call_count == calls_before

    assert c._drive_id is None
    assert c._drive_info is None


async def test_resolve_drive_unchanged():
    c = _client(auth_mode="password", credentials={"username": "user@tenant.com"})
    drive = await c._resolve_drive()
    assert drive.id == "me-drive"
    assert c._drive_id == "me-drive"
