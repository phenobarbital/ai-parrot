"""FEAT-608 TASK-3816 — GoogleDriveToolkit."""

import sys
from pathlib import Path

import pytest

sys.modules.pop("parrot.interfaces.file", None)
from parrot.interfaces.file.gdrive import GoogleDriveFileManager  # noqa: E402
from parrot_tools.google.drive import GoogleDriveToolkit  # noqa: E402

FAKES_DIR = Path(__file__).parents[3] / "ai-parrot" / "tests" / "interfaces"
sys.path.insert(0, str(FAKES_DIR))
from _gdrive_fakes import FakeDrive, FakeDriveClient, make_google_client  # noqa: E402


def _manager_with_files() -> tuple[GoogleDriveFileManager, FakeDriveClient]:
    """Build a real manager wired to the in-memory Drive fake."""
    drive = FakeDrive()
    drive.put_folder("reports")
    drive.put_file("reports/alpha.txt", b"alpha", mime="text/plain")
    drive.put_file("reports/beta.csv", b"beta", mime="text/csv")
    drive.put_file("reports/gamma.txt", b"gamma", mime="text/plain")
    drive.put_file("reports/delta.txt", b"delta", mime="text/plain")
    client = FakeDriveClient(drive, page_size=1)
    manager = GoogleDriveFileManager()
    manager.adopt_client(make_google_client(client))
    return manager, client


async def test_toolkit_builds_manager_or_adopts_google_client():
    """Opening builds a manager and adopts an authenticated Google client."""
    drive = FakeDrive()
    client = FakeDriveClient(drive)
    toolkit = GoogleDriveToolkit(google_client=make_google_client(client))
    await toolkit._ensure_open()
    assert isinstance(toolkit._manager, GoogleDriveFileManager)
    assert toolkit._manager.client is toolkit._google_client


def test_toolkit_tool_names():
    """Toolkit exposes exactly the six namespaced Drive tools."""
    manager, _ = _manager_with_files()
    names = {tool.name for tool in GoogleDriveToolkit(manager=manager).get_tools()}
    assert names == {
        "gdrive_list_files",
        "gdrive_search_files",
        "gdrive_download_file",
        "gdrive_upload_file",
        "gdrive_share_file",
        "gdrive_get_file_link",
    }


async def test_toolkit_response_shapes():
    """List and search responses are JSON-compatible and use their specified keys."""
    manager, _ = _manager_with_files()
    toolkit = GoogleDriveToolkit(manager=manager)
    listed = await toolkit.list_files("reports", "*.txt")
    searched = await toolkit.search_files(keywords="alpha")
    assert set(listed) == {"entries", "count", "path"}
    assert listed["entries"][0].keys() == {
        "name",
        "path",
        "is_folder",
        "size",
        "content_type",
        "modified_at",
        "web_url",
    }
    assert set(searched) == {"files", "count", "truncated"}
    assert searched["files"][0].keys() == {"name", "path", "size", "content_type", "modified_at", "url"}


async def test_toolkit_search_max_results_after_filtering():
    """Search limit is applied after the manager filters all paginated pages."""
    manager, _ = _manager_with_files()
    result = await GoogleDriveToolkit(manager=manager).search_files(extension=".txt", max_results=2)
    assert result["count"] == 2
    assert result["truncated"] is True
    assert {item["name"] for item in result["files"]} == {"alpha.txt", "gamma.txt"}


async def test_toolkit_download_uses_download_dir(tmp_path):
    """Download uses the configured local directory and source basename."""
    manager, _ = _manager_with_files()
    result = await GoogleDriveToolkit(manager=manager, download_dir=tmp_path).download_file("reports/alpha.txt")
    assert Path(result["local_path"]) == tmp_path / "alpha.txt"
    assert (tmp_path / "alpha.txt").read_bytes() == b"alpha"
    assert set(result) == {"downloaded", "path", "local_path", "size", "content_type"}


async def test_toolkit_upload_missing_local_file_raises(tmp_path):
    """Upload reports an absent local source before calling the manager."""
    manager, _ = _manager_with_files()
    with pytest.raises(FileNotFoundError):
        await GoogleDriveToolkit(manager=manager).upload_file(str(tmp_path / "missing.txt"), "missing.txt")


async def test_toolkit_share_and_link():
    """Sharing and plain links return their specified response shapes."""
    manager, _ = _manager_with_files()
    toolkit = GoogleDriveToolkit(manager=manager)
    shared = await toolkit.share_file("reports/alpha.txt", scope="anyone")
    linked = await toolkit.get_file_link("reports/alpha.txt")
    assert set(shared) == {"shared", "path", "scope", "role", "url"}
    assert shared["shared"] is True
    assert linked == {"path": "reports/alpha.txt", "url": shared["url"]}
