"""FEAT-603 GraphDriveFileManager unit tests (TASK-3749)."""

import datetime as dt
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# The repository-wide test bootstrap installs a non-package compatibility stub
# for this module before collection. This task verifies the real new submodule.
sys.modules.pop("parrot.interfaces.file", None)
from parrot.interfaces.file.graph import (
    BatchItemResult,
    BatchSummary,
    DriveEntry,
    GraphDriveFileManager,
    GraphFileManagerError,
)

from ._graph_fakes import (
    FakeAPIError,
    FakeDrive,
    FakeDriveItem,
    FakeGraphClient,
    make_onedrive_client,
    make_probe,
    make_sharepoint_client,
)
from parrot.interfaces.sharepoint import SharepointClient


def test_prefix_is_normalised():
    assert make_probe(GraphDriveFileManager, prefix="/reports/2026/").prefix == "reports/2026/"
    assert make_probe(GraphDriveFileManager).prefix == ""


def test_prefixed_unprefixed_roundtrip():
    manager = make_probe(GraphDriveFileManager, prefix="reports/")
    assert manager._prefixed("q3.xlsx") == "reports/q3.xlsx"
    assert manager._unprefixed("reports/q3.xlsx") == "q3.xlsx"
    assert manager._prefixed(r"q3\draft.xlsx") == "reports/q3/draft.xlsx"
    assert manager._prefixed("") == "reports"


def test_rejects_parent_segments():
    with pytest.raises(ValueError):
        make_probe(GraphDriveFileManager)._prefixed("a/../b")


def test_item_ref_root_and_quoted_segments():
    manager = make_probe(GraphDriveFileManager)
    assert manager._item_ref("") == "root"
    assert manager._item_ref("a b/c#d.txt") == "root:/a%20b/c%23d.txt:"


def test_make_metadata_maps_driveitem():
    modified_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    item = FakeDriveItem(
        id="file-1",
        name="q3.xlsx",
        size=42,
        web_url="https://contoso.sharepoint.com/reports/q3.xlsx",
        file=SimpleNamespace(mime_type="application/vnd.ms-excel"),
        last_modified_date_time=modified_at,
        parent_reference=SimpleNamespace(path="/drives/d/root:/reports"),
    )
    manager = make_probe(GraphDriveFileManager)
    metadata = manager._make_metadata(item)
    assert metadata.path == "reports/q3.xlsx"
    assert metadata.size == 42
    assert metadata.content_type == "application/vnd.ms-excel"
    assert metadata.modified_at == modified_at
    assert metadata.url == item.web_url

    folder = FakeDriveItem(id="folder-1", name="reports", size=42, folder=SimpleNamespace())
    folder_metadata = manager._make_metadata(folder, full_path="reports")
    assert folder_metadata.size == 0
    assert folder_metadata.content_type is None
    assert manager._make_metadata(item, full_path="archive/q3.xlsx").path == "archive/q3.xlsx"


def test_make_entry_includes_folders():
    manager = make_probe(GraphDriveFileManager)
    folder = FakeDriveItem(
        id="folder-1", name="reports", folder=SimpleNamespace(), web_url="https://example.test/reports"
    )
    file_item = FakeDriveItem(id="file-1", name="q3.xlsx", file=SimpleNamespace(mime_type="application/xlsx"))
    folder_entry = manager._make_entry(folder, full_path="reports")
    file_entry = manager._make_entry(file_item, full_path="reports/q3.xlsx")
    assert folder_entry.is_folder is True
    assert file_entry.is_folder is False
    assert folder_entry.id == folder.id
    assert folder_entry.name == folder.name
    assert folder_entry.web_url == folder.web_url


def test_models_validate():
    item = BatchItemResult(index=0, source="source", destination="destination", state="succeeded", ok=True)
    with pytest.raises(ValueError):
        BatchItemResult(index=0, source="source", destination="destination", state="succeeded", ok=True, attempts=-1)
    with pytest.raises(ValueError):
        BatchItemResult(
            index=0, source="source", destination="destination", state="succeeded", ok=True, unexpected=True
        )
    summary = BatchSummary(total=1, succeeded=1, failed=0, skipped=0, items=[item])
    assert BatchSummary.model_validate(summary.model_dump()).items == [item]
    assert DriveEntry(id="entry", name="name", path="name", is_folder=False).size == 0


def test_batch_module_is_msgraph_free():
    source_root = Path(__file__).parents[2] / "src"
    environment = {**os.environ, "PYTHONPATH": str(source_root)}
    subprocess.run(
        [sys.executable, "-c", "import parrot.interfaces.file.batch, sys; assert 'msgraph' not in sys.modules"],
        check=True,
        env=environment,
    )


def test_batch_summary_from_items():
    items = [
        BatchItemResult(index=0, source="a", destination="a", state="succeeded", ok=True),
        BatchItemResult(index=1, source="b", destination="b", state="failed", ok=False),
        BatchItemResult(index=2, source="c", destination="c", state="skipped", ok=False, attempts=0),
    ]
    summary = BatchSummary.from_items(items)
    assert (summary.total, summary.succeeded, summary.failed, summary.skipped) == (3, 1, 1, 1)
    assert summary.aborted is True


def test_client_before_connect_raises():
    with pytest.raises(GraphFileManagerError):
        _ = make_probe(GraphDriveFileManager).client


@pytest.mark.parametrize(
    ("auth_mode", "credentials", "user_assertion", "expected"),
    [
        ("direct", {}, None, "acquire_token"),
        ("direct", {"username": "user", "password": "secret"}, None, "user_auth"),
        ("on_behalf_of", {}, "assertion", "acquire_token_on_behalf_of"),
        ("delegated", {}, None, "interactive_login"),
        ("cached", {}, None, "ensure_interactive_session"),
    ],
)
async def test_connect_auth_mode_branches(auth_mode, credentials, user_assertion, expected):
    fake = FakeGraphClient({"drive-1": FakeDrive()})
    client = make_sharepoint_client(fake, drive_id="drive-1")
    calls = []
    client.processing_credentials = lambda: calls.append("processing_credentials")
    client.set_auth_mode = lambda mode: calls.append(("set_auth_mode", mode))
    client.acquire_token = lambda scopes: calls.append("acquire_token")
    client.user_auth = lambda username, password, scopes: calls.append("user_auth")
    client.acquire_token_on_behalf_of = lambda assertion, scopes: calls.append("acquire_token_on_behalf_of")

    async def interactive_login(*, scopes=None):
        calls.append("interactive_login")

    async def ensure_interactive_session(*, scopes=None):
        calls.append("ensure_interactive_session")

    client.interactive_login = interactive_login
    client.ensure_interactive_session = ensure_interactive_session
    manager = make_probe(
        GraphDriveFileManager, credentials=credentials, auth_mode=auth_mode, user_assertion=user_assertion
    )
    manager._build_client = lambda: client
    await manager.connect()
    await manager.connect()
    assert calls.count(expected) == 1


async def test_adopt_client_same_class_is_used_as_is():
    fake = FakeGraphClient({"drive-1": FakeDrive()})
    client = make_sharepoint_client(fake, drive_id="drive-1")
    closed = []

    async def close():
        closed.append(True)

    client.close = close
    manager = make_probe(GraphDriveFileManager)
    manager.client_class = SharepointClient
    manager.adopt_client(client)
    assert manager.client is client
    await manager.close()
    assert closed == []


async def test_adopt_client_generic_builds_wrapper_and_copies_auth_state_only():
    fake = FakeGraphClient({"drive-1": FakeDrive()})
    adopted = make_onedrive_client(fake)
    adopted._credential = "credential"
    adopted._access_token = "token"
    adopted.auth_mode = "cached"
    wrapper = make_sharepoint_client(fake, drive_id="drive-1")
    wrapper.site = "own-site"
    closed = []
    wrapper.processing_credentials = lambda: None

    async def close():
        closed.append(True)

    wrapper.close = close
    manager = make_probe(GraphDriveFileManager)
    manager.client_class = SharepointClient
    manager._build_client = lambda: wrapper
    manager.adopt_client(adopted)
    assert manager.client is wrapper
    assert (wrapper._credential, wrapper._graph_client, wrapper._access_token, wrapper.auth_mode) == (
        adopted._credential,
        adopted._graph_client,
        adopted._access_token,
        adopted.auth_mode,
    )
    assert wrapper.site == "own-site"
    await manager.close()
    assert closed == [True]


async def test_ready_resolves_drive_once():
    manager = make_probe(GraphDriveFileManager)
    manager.adopt_client(make_sharepoint_client(FakeGraphClient({"drive-1": FakeDrive()}), drive_id="drive-1"))
    calls = 0

    async def resolve_drive_id():
        nonlocal calls
        calls += 1
        return "drive-1"

    manager._resolve_drive_id = resolve_drive_id
    assert await asyncio.gather(manager._ready(), manager._ready()) == ["drive-1", "drive-1"]
    assert calls == 1


async def test_retrying_honours_retry_after_and_caps_at_60():
    manager = make_probe(GraphDriveFileManager)
    sleeps = []
    attempts = 0

    async def sleep(seconds):
        sleeps.append(seconds)

    async def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FakeAPIError(429, retry_after=90)
        return "done"

    manager._sleep = sleep
    assert await manager._retrying(operation, label="test") == ("done", 2)
    assert sleeps == [60]


async def test_retrying_non_idempotent_never_retries():
    manager = make_probe(GraphDriveFileManager)

    async def operation():
        raise FakeAPIError(429)

    with pytest.raises(FakeAPIError):
        await manager._retrying(operation, label="test", idempotent=False)


def test_map_error_types():
    manager = make_probe(GraphDriveFileManager)
    assert isinstance(manager._map_error(FakeAPIError(404), path="file"), FileNotFoundError)
    assert isinstance(manager._map_error(FakeAPIError(401), path="file"), PermissionError)
    assert isinstance(manager._map_error(FakeAPIError(403), path="file"), PermissionError)
    assert isinstance(manager._map_error(FakeAPIError(409), path="file"), FileExistsError)
    error = manager._map_error(FakeAPIError(500), path="file")
    assert isinstance(error, GraphFileManagerError)
    assert error.status_code == 500


def test_validate_graph_url_accepts_graph_and_sharepoint_hosts():
    manager = make_probe(GraphDriveFileManager)
    for url in (
        "https://graph.microsoft.com/v1.0/me",
        "https://contoso.sharepoint.com/path",
        "https://contoso-my.sharepoint.com/path",
        "https://x.files.1drv.com/path",
    ):
        assert manager._validate_graph_url(url, purpose="test") == url


def test_validate_graph_url_rejects_http_and_foreign_hosts():
    manager = make_probe(GraphDriveFileManager)
    for url in ("http://contoso.sharepoint.com", "https://evil.example", "https://sharepoint.com.evil.example"):
        with pytest.raises(GraphFileManagerError) as exc_info:
            manager._validate_graph_url(url, purpose="test")
        assert url not in str(exc_info.value)


@pytest.fixture
def paged_manager():
    drive = FakeDrive("drive-1")
    drive.put_file("reports/file1.csv", b"data1")
    drive.put_file("reports/file2.csv", b"data2")
    drive.put_file("reports/file3.csv", b"data3")
    drive.put_file("reports/file4.txt", b"data4")
    drive.put_file("reports/file5.txt", b"data5")
    drive.put_folder("reports/archive")
    fake = FakeGraphClient({"drive-1": drive}, page_size=2)
    manager = make_probe(GraphDriveFileManager, prefix="reports/")
    manager.client_class = SharepointClient
    manager.adopt_client(make_sharepoint_client(fake, drive_id="drive-1"))
    return manager, fake, drive


async def test_list_files_follows_next_link(paged_manager):
    manager, fake, _drive = paged_manager
    files = await manager.list_files()
    assert sorted(f.name for f in files) == ["file1.csv", "file2.csv", "file3.csv", "file4.txt", "file5.txt"]
    assert all(f.path == f"{f.name}" for f in files)
    children_calls = [call for call in fake.calls if call[0] == "children"]
    assert len(children_calls) == 3


async def test_list_files_pattern_excludes_folders(paged_manager):
    manager, _fake, _drive = paged_manager
    files = await manager.list_files(pattern="*.csv")
    assert sorted(f.name for f in files) == ["file1.csv", "file2.csv", "file3.csv"]
    assert all(name.endswith(".csv") for name in (f.name for f in files))


async def test_list_entries_includes_folders_all_pages(paged_manager):
    manager, _fake, _drive = paged_manager
    entries = await manager.list_entries()
    assert len(entries) == 6
    folders = [entry for entry in entries if entry.is_folder]
    assert len(folders) == 1
    assert folders[0].name == "archive"


async def test_exists_true_for_folder_and_false_when_missing(paged_manager):
    manager, _fake, _drive = paged_manager
    assert await manager.exists("archive") is True
    assert await manager.exists("file1.csv") is True
    assert await manager.exists("does-not-exist.csv") is False


async def test_find_files_server_search_vs_recursive_fallback(paged_manager):
    manager, fake, _drive = paged_manager
    safe_hits = await manager.find_files(keywords="file1")
    assert [entry.name for entry in safe_hits] == ["file1.csv"]
    assert any(call[0] == "search" for call in fake.calls)

    fake.calls.clear()
    unsafe_hits = await manager.find_files(keywords="file*")
    assert not any(call[0] == "search" for call in fake.calls)
    assert any(call[0] == "children" for call in fake.calls)
    assert unsafe_hits == []

    fake.calls.clear()
    filtered = await manager.find_files(extension=".csv")
    assert sorted(entry.name for entry in filtered) == ["file1.csv", "file2.csv", "file3.csv"]
    assert not any(call[0] == "search" for call in fake.calls)


async def test_search_paginates_then_applies_filters(paged_manager):
    manager, fake, drive = paged_manager
    drive.put_file("reports/keyword1.csv", b"a")
    drive.put_file("reports/keyword2.csv", b"b")
    drive.put_file("reports/keyword3.txt", b"c")
    hidden = FakeDriveItem(id="hidden-1", name="keyword-hidden.csv")
    drive.by_id[hidden.id] = hidden
    drive.path_of[hidden.id] = "reports/keyword-hidden.csv"

    fake.calls.clear()
    hits = await manager.find_entries(keywords="keyword", extension=".csv")
    assert {entry.name for entry in hits} == {"keyword1.csv", "keyword2.csv"}
    assert any(call == ("get", "drive-1", "hidden-1", None) for call in fake.calls)
    search_calls = [call for call in fake.calls if call[0] == "search"]
    assert len(search_calls) >= 2


async def test_delete_recycle_bin_and_missing_returns_false(paged_manager):
    manager, fake, _drive = paged_manager
    assert await manager.delete_file("file5.txt") is True
    assert any(call[0] == "delete" for call in fake.calls)
    assert await manager.exists("file5.txt") is False
    assert await manager.delete_file("does-not-exist.csv") is False


async def test_public_errors_are_mapped(paged_manager):
    manager, fake, _drive = paged_manager
    fake.fail_next(500, op="get")
    with pytest.raises(GraphFileManagerError):
        await manager.exists("file1.csv")

    with pytest.raises(FileNotFoundError):
        await manager.get_file_metadata("does-not-exist.csv")
