"""FEAT-608 GoogleDriveFileManager unit tests (TASK-3810 core)."""

import datetime as dt
import io
import sys
from pathlib import Path

import pytest

sys.modules.pop("parrot.interfaces.file", None)
from parrot.interfaces.file.gdrive import GoogleDriveFileManager, GoogleDriveFileManagerError  # noqa: E402

from ._gdrive_fakes import FakeDrive, FakeDriveClient, FakeHTTPError, make_google_client, make_manager  # noqa: E402


async def _no_sleep(seconds: float) -> None:
    """Avoid retry waits in deterministic tests."""


@pytest.fixture(autouse=True)
def _concrete(monkeypatch):
    monkeypatch.setattr(GoogleDriveFileManager, "__abstractmethods__", frozenset())


@pytest.fixture
def manager(monkeypatch):
    drive = FakeDrive()
    drive.put_folder("reports/2026")
    drive.put_file("reports/2026/q3.xlsx", b"x" * 10)
    client = FakeDriveClient(drive)
    result = make_manager(client, root_path="reports", prefix="2026/")
    monkeypatch.setattr(result, "_sleep", _no_sleep)
    return result, client


def test_constructor_defaults_and_validation():
    manager = GoogleDriveFileManager(prefix="/a/b/")
    assert manager.prefix == "a/b/"
    with pytest.raises(ValueError):
        GoogleDriveFileManager(root_id="one", root_path="two")
    with pytest.raises(ValueError):
        GoogleDriveFileManager(chunk_size=1)


@pytest.mark.asyncio
async def test_adopt_client_skips_auth_and_never_closes(manager):
    result, drive = manager
    await result.connect()
    client = result.client
    await result.close()
    assert drive.closed == 1
    assert client.closes == []


@pytest.mark.asyncio
async def test_connect_auth_mode_branches(monkeypatch):
    calls = []

    class Client:
        async def initialize(self):
            calls.append("initialize")

        async def interactive_login(self, **kwargs):
            calls.append("login")

    await GoogleDriveFileManager(auth_mode="service_account")._authenticate(Client())
    await GoogleDriveFileManager(auth_mode="user")._authenticate(Client())
    assert calls == ["initialize", "login", "initialize"]


@pytest.mark.asyncio
async def test_resolve_root_and_walks_segments_with_cache(manager):
    result, drive = manager
    await result._ready()
    found = await result._resolve("2026/q3.xlsx")
    calls = len(drive.drive.calls)
    assert found[1] is False
    assert await result._resolve("2026/q3.xlsx") == found
    assert len(drive.drive.calls) == calls


@pytest.mark.asyncio
async def test_resolve_root_shared_drive_root_id_root_path():
    drive = FakeDrive(drive_id="shared")
    client = FakeDriveClient(drive)
    result = make_manager(client, shared_drive_id="shared")
    assert await result._ready() == "shared"


@pytest.mark.asyncio
async def test_resolve_duplicate_names_newest_then_smallest_id(manager):
    result, drive = manager
    drive.drive.duplicate("reports/2026/q3.xlsx", b"y", modified=dt.datetime(2020, 1, 1, tzinfo=dt.UTC))
    await result._ready()
    assert (await result._resolve("2026/q3.xlsx"))[0]


def test_prefixed_unprefixed_roundtrip():
    result = GoogleDriveFileManager(prefix="base")
    assert result._unprefixed(result._prefixed("/thing")) == "thing"


def test_rejects_parent_segments():
    with pytest.raises(ValueError, match="path"):
        GoogleDriveFileManager()._prefixed("one/../two")


def test_map_error_and_status_from_httperror():
    result = GoogleDriveFileManager()
    assert isinstance(result._map_error(FakeHTTPError(404), path="x"), FileNotFoundError)
    assert isinstance(
        result._map_error(FakeHTTPError(403, reason="rateLimitExceeded"), path="x"), GoogleDriveFileManagerError
    )


@pytest.mark.asyncio
async def test_retry_policy_caps_retry_after_and_never_non_idempotent(manager):
    result, _ = manager
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FakeHTTPError(429, retry_after=999)
        return "ok"

    assert await result._retrying(flaky, label="test") == ("ok", 2)

    async def non_idempotent():
        raise FakeHTTPError(429)

    with pytest.raises(FakeHTTPError):
        await result._retrying(non_idempotent, label="test", idempotent=False)


@pytest.mark.asyncio
async def test_rate_limited_403_is_retried(manager):
    result, _ = manager
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FakeHTTPError(403, reason="userRateLimitExceeded")
        return "ok"

    assert await result._retrying(flaky, label="rate") == ("ok", 2)


def test_validate_upload_url_rejects_http_and_foreign_hosts(caplog):
    result = GoogleDriveFileManager()
    assert result._validate_upload_url("https://www.googleapis.com/upload")
    with pytest.raises(GoogleDriveFileManagerError):
        result._validate_upload_url("http://www.googleapis.com/token")
    with pytest.raises(GoogleDriveFileManagerError):
        result._validate_upload_url("https://example.test/token")


@pytest.mark.asyncio
async def test_list_files_excludes_folders_and_follows_page_tokens(manager):
    result, drive = manager
    for index in range(5):
        drive.drive.put_file(f"reports/2026/file-{index}.txt", b"x")
    drive.drive.put_folder("reports/2026/folder")

    files = await result.list_files("", pattern="*.txt")

    assert [file.name for file in files] == [f"file-{index}.txt" for index in range(5)]
    assert [file.path for file in files] == [f"file-{index}.txt" for index in range(5)]
    calls = [call for call in drive.drive.calls if call[1] == "list" and "in parents" in call[2]["q"]]
    assert len(calls) >= 3


@pytest.mark.asyncio
async def test_list_entries_includes_folders_all_pages(manager):
    result, drive = manager
    for index in range(4):
        drive.drive.put_file(f"reports/2026/file-{index}.txt", b"x")
    drive.drive.put_folder("reports/2026/child")

    entries = await result.list_entries()

    assert {entry.name for entry in entries} == {"q3.xlsx", "child", *(f"file-{index}.txt" for index in range(4))}
    assert next(entry for entry in entries if entry.name == "child").is_folder


@pytest.mark.asyncio
async def test_list_params_shared_drive_flags():
    drive = FakeDrive(drive_id="shared")
    drive.put_file("report.txt", b"x")
    result = make_manager(FakeDriveClient(drive), shared_drive_id="shared")

    await result.list_files()

    params = result.drive.drive.calls[-1][2]
    assert params["supportsAllDrives"] is True
    assert params["includeItemsFromAllDrives"] is True
    assert params["corpora"] == "drive"
    assert params["driveId"] == "shared"
    assert GoogleDriveFileManager()._list_params() == {"supportsAllDrives": True}


@pytest.mark.asyncio
async def test_exists_and_metadata(manager):
    result, _ = manager

    assert await result.exists("q3.xlsx")
    assert await result.exists("")
    assert not await result.exists("missing.txt")
    metadata = await result.get_file_metadata("q3.xlsx")
    assert metadata.name == "q3.xlsx"
    assert metadata.path == "q3.xlsx"


@pytest.mark.asyncio
async def test_find_files_server_side_contains_then_client_filters(manager):
    result, drive = manager
    drive.drive.put_file("reports/2026/nested/budget-q3.xlsx", b"x")
    drive.drive.put_file("reports/2026/nested/budget-q4.csv", b"x")
    drive.drive.put_file("reports/2026/budget-q3.txt", b"x")

    files = await result.find_files(keywords=["budget", "q3"], extension="xlsx", prefix="")

    assert [file.path for file in files] == ["nested/budget-q3.xlsx"]
    queries = [call[2]["q"] for call in drive.drive.calls if call[1] == "list"]
    assert any("name contains 'budget'" in query for query in queries)


@pytest.mark.asyncio
async def test_search_paginates_then_applies_extension(manager):
    result, drive = manager
    for index in range(5):
        drive.drive.put_file(f"reports/2026/match-{index}.txt", b"x")
    drive.drive.put_file("reports/2026/match-final.csv", b"x")

    files = await result.find_files(keywords="match", extension="csv")

    assert [file.name for file in files] == ["match-final.csv"]
    search_calls = [call for call in drive.drive.calls if "name contains 'match'" in call[2].get("q", "")]
    assert len(search_calls) >= 3


@pytest.mark.asyncio
async def test_download_to_path_and_binaryio_streams(manager, tmp_path):
    result, _ = manager
    target = tmp_path / "nested" / "q3.xlsx"

    assert await result.download_file("q3.xlsx", target) == target
    assert target.read_bytes() == b"x" * 10
    buffer = io.BytesIO()
    assert await result.download_file("q3.xlsx", buffer) == Path("q3.xlsx")
    assert buffer.getvalue() == b"x" * 10


@pytest.mark.asyncio
async def test_download_workspace_native_raises(manager):
    result, drive = manager
    drive.drive.put_file(
        "reports/2026/sheet",
        b"",
        mime="application/vnd.google-apps.spreadsheet",
    )

    with pytest.raises(GoogleDriveFileManagerError, match="export is not supported"):
        await result.download_file("sheet", Path("unused"))


# ---- uploads (TASK-3812) -------------------------------------------------
def _children(drive, name):
    return [item for item in drive.drive.by_id.values() if item.name == name and not item.trashed]


@pytest.mark.asyncio
async def test_upload_small_multipart_create_and_replace(manager, tmp_path):
    result, drive = manager
    source = tmp_path / "new.txt"
    source.write_bytes(b"hello")

    metadata = await result.upload_file(source, "sub/new.txt")
    assert metadata.path == "sub/new.txt"
    assert _children(drive, "new.txt")[0].content == b"hello"

    again = await result.upload_file(io.BytesIO(b"bye"), "sub/new.txt")
    assert again.size == 3
    assert len(_children(drive, "new.txt")) == 1
    assert _children(drive, "new.txt")[0].content == b"bye"
    assert any(call[1] == "update" for call in drive.drive.calls)


@pytest.mark.asyncio
async def test_upload_resumable_session_chunks_308_and_range_resume(manager, monkeypatch):
    result, drive = manager
    result.chunk_size = result.small_file_threshold = 262144
    payload = bytes(range(256)) * 2400  # 600 KiB
    size = len(payload)

    metadata = await result.upload_file(io.BytesIO(payload), "big.bin")

    assert metadata.size == size
    assert _children(drive, "big.bin")[0].content == payload
    puts = [req for req in drive.requests if req.method == "PUT"]
    assert [req.headers["Content-Range"] for req in puts] == [
        f"bytes 0-262143/{size}",
        f"bytes 262144-524287/{size}",
        f"bytes 524288-{size - 1}/{size}",
    ]
    assert all("Authorization" not in req.headers for req in puts)
    assert len([req for req in drive.requests if req.method == "POST"]) == 1

    drive.fail_next(503, method="PUT")
    await result.upload_file(io.BytesIO(payload), "retry.bin")
    assert _children(drive, "retry.bin")[0].content == payload

    drive.fail_next(503, method="POST")
    with pytest.raises(GoogleDriveFileManagerError) as excinfo:
        await result.upload_file(io.BytesIO(payload), "nope.bin")
    assert excinfo.value.status_code == 503
    assert not _children(drive, "nope.bin")


@pytest.mark.asyncio
async def test_upload_session_url_validated_and_not_logged(manager, caplog):
    result, drive = manager
    result.chunk_size = result.small_file_threshold = 262144
    original = drive.send_raw
    secret = "https://evil.example/upload?upload_id=SECRET-TOKEN"

    async def hostile(request, **kwargs):
        response = await original(request, **kwargs)
        if request.method == "POST":
            response.headers["Location"] = secret
        return response

    drive.send_raw = hostile
    with caplog.at_level("DEBUG"):
        with pytest.raises(GoogleDriveFileManagerError):
            await result.upload_file(io.BytesIO(b"x" * 300000), "big.bin")
    assert "SECRET-TOKEN" not in caplog.text
    assert not [req for req in drive.requests if req.method == "PUT"]


@pytest.mark.asyncio
async def test_upload_conflict_replace_fail_rename(manager):
    result, drive = manager

    await result.upload_file(io.BytesIO(b"new"), "q3.xlsx")
    assert len(_children(drive, "q3.xlsx")) == 1
    assert _children(drive, "q3.xlsx")[0].content == b"new"

    result.conflict_behavior = "fail"
    with pytest.raises(FileExistsError):
        await result.upload_file(io.BytesIO(b"z"), "q3.xlsx")

    result.conflict_behavior = "rename"
    first = await result.upload_file(io.BytesIO(b"a"), "q3.xlsx")
    second = await result.upload_file(io.BytesIO(b"b"), "q3.xlsx")
    assert first.name == "q3 (1).xlsx"
    assert second.name == "q3 (2).xlsx"
    assert result._renamed("README", {"README (1)"}) == "README (2)"


@pytest.mark.asyncio
async def test_upload_unseekable_stream_above_threshold_refused(manager):
    result, drive = manager
    result.small_file_threshold = 8

    class Unseekable(io.RawIOBase):
        def __init__(self, data):
            self._buffer = io.BytesIO(data)

        def readable(self):
            return True

        def seekable(self):
            return False

        def read(self, size=-1):
            return self._buffer.read(size)

    with pytest.raises(ValueError, match="unseekable"):
        await result.upload_file(Unseekable(b"x" * 100), "stream.bin")
    assert not _children(drive, "stream.bin")
    await result.upload_file(Unseekable(b"tiny"), "stream-ok.bin")
    assert _children(drive, "stream-ok.bin")[0].content == b"tiny"


@pytest.mark.asyncio
async def test_create_file_and_upload_file_from_bytes_returns_webviewlink(manager):
    result, drive = manager

    assert await result.create_file("made.txt", b"abc") is True
    assert _children(drive, "made.txt")[0].content == b"abc"
    url = await result.upload_file_from_bytes(b"<b/>", "page.html", "text/html")
    assert url.startswith("https://drive.google.com/file/d/")
    assert _children(drive, "page.html")[0].mimeType == "text/html"


# ---- mutations & sharing (TASK-3813) -------------------------------------
@pytest.mark.asyncio
async def test_copy_is_synchronous_and_never_retried(manager):
    result, drive = manager
    drive.drive.put_file("reports/2026/copy-source.txt", b"copy")
    drive.fail_next(503, method="files.copy")

    with pytest.raises(GoogleDriveFileManagerError) as excinfo:
        await result.copy_file("copy-source.txt", "copies/copied.txt")
    assert excinfo.value.status_code == 503

    assert len([call for call in drive.drive.calls if call[1] == "copy"]) == 0
    copied = await result.copy_file("copy-source.txt", "copies/copied.txt")
    assert copied.path == "copies/copied.txt"
    assert _children(drive, "copied.txt")[0].content == b"copy"
    assert len([call for call in drive.drive.calls if call[1] == "copy"]) == 1


@pytest.mark.asyncio
async def test_delete_trashes_by_default_permanent_optional_missing_false():
    fake_drive = FakeDrive()
    client = FakeDriveClient(fake_drive)
    result = make_manager(client)
    item = fake_drive.put_file("delete.txt", b"x")

    assert await result.delete_file("delete.txt") is True
    assert fake_drive.by_id[item.id].trashed is True
    assert await result.delete_file("missing.txt") is False

    permanent = fake_drive.put_file("permanent.txt", b"x")
    result.permanent_delete = True
    assert await result.delete_file("permanent.txt") is True
    assert permanent.id not in fake_drive.by_id


@pytest.mark.asyncio
async def test_folders_create_remove_rename_and_move_across_parents(manager):
    result, drive = manager

    await result.create_folder("created/nested")
    await result.create_folder("created/nested")
    await result.rename_folder("created/nested", "moved/renamed")
    await result.rename_file("q3.xlsx", "moved/quarter.xlsx")

    folder_id, is_folder = await result._resolve("2026/moved/renamed", want_folder=True)
    assert is_folder is True
    assert (await result._resolve("2026/moved/quarter.xlsx", want_folder=False))[1] is False
    await result.remove_folder("moved/renamed")
    assert drive.drive.by_id[folder_id].trashed is True


@pytest.mark.asyncio
async def test_get_file_url_returns_webviewlink_without_permissions(manager, caplog):
    result, drive = manager

    with caplog.at_level("DEBUG"):
        url = await result.get_file_url("q3.xlsx", expiry=12)

    assert url.startswith("https://drive.google.com/file/d/")
    assert "expiry=12 ignored" in caplog.text
    assert not [call for call in drive.drive.calls if call[0] == "permissions"]


@pytest.mark.asyncio
async def test_create_sharing_link_bodies_per_scope_and_expiry_rules(manager):
    result, drive = manager

    url = await result.create_sharing_link("q3.xlsx", email_address="reader@example.test", expiry=120)
    assert url.startswith("https://drive.google.com/file/d/")
    user_body = [call[2]["body"] for call in drive.drive.calls if call[0] == "permissions"][-1]
    assert user_body["type"] == "user"
    assert user_body["emailAddress"] == "reader@example.test"
    assert user_body["expirationTime"].endswith("Z")

    await result.create_sharing_link("q3.xlsx", scope="domain", domain="example.test", expiry=120)
    domain_body = [call[2]["body"] for call in drive.drive.calls if call[0] == "permissions"][-1]
    assert domain_body == {"type": "domain", "role": "reader", "domain": "example.test"}

    await result.create_sharing_link("q3.xlsx", scope="anyone", role="commenter", expiry=120)
    anyone_body = [call[2]["body"] for call in drive.drive.calls if call[0] == "permissions"][-1]
    assert anyone_body == {"type": "anyone", "role": "commenter"}


@pytest.mark.asyncio
async def test_create_sharing_link_missing_field_value_error(manager):
    result, _ = manager

    with pytest.raises(ValueError, match="email_address"):
        await result.create_sharing_link("q3.xlsx")
    with pytest.raises(ValueError, match="domain"):
        await result.create_sharing_link("q3.xlsx", scope="domain")


@pytest.mark.asyncio
async def test_create_sharing_link_forbidden_scope_permission_error(manager):
    result, drive = manager
    drive.fail_next(403, method="permissions.create")

    with pytest.raises(PermissionError, match="sharing scope"):
        await result.create_sharing_link("q3.xlsx", scope="anyone")
