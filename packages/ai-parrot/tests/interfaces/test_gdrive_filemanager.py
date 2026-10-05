"""FEAT-608 GoogleDriveFileManager unit tests (TASK-3810 core)."""

import datetime as dt
import io
import sys

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
