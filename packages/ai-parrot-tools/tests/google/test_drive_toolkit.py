"""FEAT-608 TASK-3816 — GoogleDriveToolkit."""

import importlib.util
import sys
from pathlib import Path

import pytest

from parrot.interfaces.file.gdrive import GoogleDriveFileManager
from parrot_tools.google.drive import GoogleDriveToolkit

# `_gdrive_fakes` lives in another distribution's test tree. Load it by
# absolute path instead of putting its directory on the import search path:
# that directory also holds a `jira/` test package, and such an entry would
# shadow the PyPI `jira` distribution for every module collected afterwards
# (issue:265b7797ae9b).
_FAKES_PATH = (
    Path(__file__).parents[3] / "ai-parrot" / "tests" / "interfaces" / "_gdrive_fakes.py"
)


def _load_gdrive_fakes():
    """Load ``_gdrive_fakes`` by file path under a private module name."""
    name = "_gdrive_fakes_tools"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, _FAKES_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load the Drive fakes from {_FAKES_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_fakes = _load_gdrive_fakes()
FakeDrive = _fakes.FakeDrive
FakeDriveClient = _fakes.FakeDriveClient
make_google_client = _fakes.make_google_client


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
        await GoogleDriveToolkit(manager=manager, upload_root=tmp_path).upload_file("missing.txt", "missing.txt")


async def test_toolkit_upload_absolute_path_rejected(tmp_path):
    """Absolute paths are rejected as a path-confinement violation (FEAT-690)."""
    manager, _ = _manager_with_files()
    with pytest.raises(ValueError, match="must be relative"):
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
