"""FEAT-603 TASK-3763/3764 — OneDrive O365 tools keep their response shapes on top of OneDriveFileManager."""

import importlib.util
import pathlib
import sys

import pytest

from parrot_tools.o365.onedrive import ListOneDriveFilesTool, SearchOneDriveFilesTool

_FAKES = pathlib.Path(__file__).resolve().parents[2] / "ai-parrot" / "tests" / "interfaces" / "_graph_fakes.py"
_spec = importlib.util.spec_from_file_location("feat603_graph_fakes", _FAKES)
fakes = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fakes
_spec.loader.exec_module(fakes)

FILE_KEYS = {"name", "id", "webUrl", "path", "isFolder", "size", "modified"}


@pytest.fixture
def fake():
    """Build delegated and app-only OneDrive fixtures with paginated responses."""
    me_drive = fakes.FakeDrive(drive_id="drive-me")
    me_drive.put_file("Documents/Projects/plan.docx", b"plan")
    me_drive.put_file("Documents/budget.xlsx", b"budget")
    user_drive = fakes.FakeDrive(drive_id="drive-u")
    user_drive.put_file("Private/user.txt", b"user")
    return fakes.FakeGraphClient(
        {"drive-me": me_drive, "drive-u": user_drive},
        me_drive_id="drive-me",
        user_drives={"u@t.com": "drive-u"},
        page_size=2,
    )


async def test_list_onedrive_files_me_delegated_shape(fake):
    """List the delegated ``me`` drive without changing the camelCase response contract."""
    client = fakes.make_onedrive_client(fake, app_only=False)
    tool = ListOneDriveFilesTool(credentials={})

    result = await tool._execute_graph_operation(client, folder_path="", recursive=True)

    assert set(result) == {"folder_path", "total_items", "files", "recursive"}
    assert result["folder_path"] == "root"
    assert result["recursive"] is True
    assert result["total_items"] == len(result["files"]) == 4
    assert {entry["path"] for entry in result["files"]} == {
        "Documents",
        "Documents/Projects",
        "Documents/Projects/plan.docx",
        "Documents/budget.xlsx",
    }
    for entry in result["files"]:
        assert set(entry) == FILE_KEYS


async def test_list_onedrive_files_user_id_app_only(fake):
    """Select the requested user's drive when using app-only authentication."""
    client = fakes.make_onedrive_client(fake, app_only=True)
    tool = ListOneDriveFilesTool(credentials={})

    result = await tool._execute_graph_operation(client, user_id="u@t.com", recursive=True)

    assert {entry["path"] for entry in result["files"]} == {"Private", "Private/user.txt"}


async def test_list_onedrive_me_under_app_only_raises(fake):
    """Reject app-only access to the implicit delegated ``me`` drive."""
    client = fakes.make_onedrive_client(fake, app_only=True)
    tool = ListOneDriveFilesTool(credentials={})

    with pytest.raises(RuntimeError, match="requires delegated"):
        await tool._execute_graph_operation(client)


async def test_search_onedrive_files_shape_and_max_results(fake):
    """Search all result pages and preserve the capped legacy response shape."""
    client = fakes.make_onedrive_client(fake, app_only=False)
    tool = SearchOneDriveFilesTool(credentials={})

    result = await tool._execute_graph_operation(client, query="", max_results=1)

    assert set(result) == {"query", "total_results", "files"}
    assert result["query"] == ""
    assert result["total_results"] == len(result["files"]) == 1
    assert result["files"][0]["isFolder"] is False
    assert set(result["files"][0]) == FILE_KEYS
