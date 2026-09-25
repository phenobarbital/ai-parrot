"""FEAT-603 TASK-3761/3762 — SharePoint O365 tools keep their response shapes on top of SharePointFileManager."""

import importlib.util
import pathlib
import sys

import pytest

from parrot.interfaces.file.sharepoint import SharePointFileManager
from parrot_tools.o365.sharepoint import (
    DownloadSharePointFileTool,
    ListSharePointFilesTool,
    SearchSharePointFilesTool,
    UploadSharePointFileTool,
)

_FAKES = pathlib.Path(__file__).resolve().parents[2] / "ai-parrot" / "tests" / "interfaces" / "_graph_fakes.py"
_spec = importlib.util.spec_from_file_location("feat603_graph_fakes", _FAKES)
fakes = importlib.util.module_from_spec(_spec)
# `_graph_fakes.py` combines `from __future__ import annotations` with `@dataclass`; on
# Python 3.12 dataclass's own type resolution looks the module up via
# `sys.modules[cls.__module__]`, so it must be registered before exec_module runs.
sys.modules[_spec.name] = fakes
_spec.loader.exec_module(fakes)

LIST_KEYS = {"site", "library", "folder_path", "total_items", "files", "recursive"}
LIST_FILE_KEYS = {"name", "path", "is_folder", "size", "modified", "web_url", "id"}
SEARCH_KEYS = {"site", "query", "library", "folder_path", "file_extension", "total_results", "files"}
SEARCH_FILE_KEYS = {"name", "path", "size", "modified", "web_url", "id"}


@pytest.fixture
def fake():
    drive = fakes.FakeDrive(drive_id="drive-1")
    drive.put_file("Reports/2025/q4.pdf", b"pdf-bytes")
    drive.put_file("Reports/2025/q4.xlsx", b"xlsx-bytes")
    drive.put_file("Reports/notes.txt", b"notes")
    return fakes.FakeGraphClient({"drive-1": drive}, page_size=2)


async def test_list_sharepoint_files_tool_response_shape(fake):
    client = fakes.make_sharepoint_client(fake, drive_id="drive-1")
    tool = ListSharePointFilesTool(credentials={})

    result = await tool._execute_graph_operation(
        client, site="TeamSite", library="Documents", folder_path="Reports", recursive=False
    )

    assert set(result) == LIST_KEYS
    assert result["site"] == "TeamSite"
    assert result["library"] == "Documents"
    assert result["folder_path"] == "Reports"
    assert result["recursive"] is False
    assert result["total_items"] == len(result["files"]) == 2

    by_name = {entry["name"]: entry for entry in result["files"]}
    assert set(by_name) == {"2025", "notes.txt"}
    for entry in result["files"]:
        assert set(entry) == LIST_FILE_KEYS

    folder_entry = by_name["2025"]
    assert folder_entry["is_folder"] is True
    assert folder_entry["path"] == "Reports/2025"

    file_entry = by_name["notes.txt"]
    assert file_entry["is_folder"] is False
    assert file_entry["path"] == "Reports/notes.txt"


async def test_list_recursive_includes_descendants_all_pages(fake):
    client = fakes.make_sharepoint_client(fake, drive_id="drive-1")
    tool = ListSharePointFilesTool(credentials={})

    result = await tool._execute_graph_operation(
        client, site="TeamSite", library="Documents", folder_path="Reports", recursive=True
    )

    assert result["recursive"] is True
    paths = {entry["path"] for entry in result["files"]}
    assert paths == {"Reports/2025", "Reports/notes.txt", "Reports/2025/q4.pdf", "Reports/2025/q4.xlsx"}
    assert result["total_items"] == len(result["files"]) == 4

    by_path = {entry["path"]: entry for entry in result["files"]}
    assert by_path["Reports/2025"]["is_folder"] is True
    assert by_path["Reports/2025/q4.pdf"]["is_folder"] is False
    assert by_path["Reports/2025/q4.xlsx"]["is_folder"] is False


async def test_search_sharepoint_files_tool_response_shape_and_max_results(fake):
    client = fakes.make_sharepoint_client(fake, drive_id="drive-1")
    tool = SearchSharePointFilesTool(credentials={})

    # file_extension="pdf" narrows the two "q4" name matches down to the single PDF hit.
    filtered = await tool._execute_graph_operation(
        client, site="TeamSite", library="Documents", query="q4", file_extension="pdf", max_results=20
    )
    assert set(filtered) == SEARCH_KEYS
    assert filtered["total_results"] == 1
    assert set(filtered["files"][0]) == SEARCH_FILE_KEYS
    assert filtered["files"][0]["name"] == "q4.pdf"
    assert filtered["files"][0]["path"] == "Reports/2025/q4.pdf"

    # max_results is applied AFTER filtering: two "q4" name matches exist, capped to one.
    limited = await tool._execute_graph_operation(
        client, site="TeamSite", library="Documents", query="q4", max_results=1
    )
    assert limited["total_results"] == 1
    assert len(limited["files"]) == 1


async def test_tools_do_not_close_the_adopted_client(fake):
    client = fakes.make_sharepoint_client(fake, drive_id="drive-1")
    tool = ListSharePointFilesTool(credentials={})

    await tool._execute_graph_operation(client, site="TeamSite", library="Documents", folder_path="Reports")

    assert client._graph_client is fake


DOWNLOAD_KEYS = {"site", "library", "file_path", "local_path", "download_url", "size"}
UPLOAD_KEYS = {"site", "library", "folder_path", "uploaded_file", "size", "web_url", "server_relative_url"}


async def test_download_sharepoint_file_tool_response_shape(fake, tmp_path, monkeypatch):
    session = fakes.FakeAiohttpSession(fake)
    monkeypatch.setattr(SharePointFileManager, "_http_session", lambda self: session)
    client = fakes.make_sharepoint_client(fake, drive_id="drive-1")
    tool = DownloadSharePointFileTool(credentials={})

    result = await tool._execute_graph_operation(
        client,
        site="TeamSite",
        library="Documents",
        file_path="Reports/2025/q4.pdf",
        local_destination=str(tmp_path),
        rename_as="renamed.pdf",
    )

    assert set(result) == DOWNLOAD_KEYS
    assert result["site"] == "TeamSite"
    assert result["library"] == "Documents"
    assert result["file_path"] == "Reports/2025/q4.pdf"
    local_path = tmp_path / "renamed.pdf"
    assert result["local_path"] == str(local_path)
    assert local_path.exists()
    assert local_path.read_bytes() == b"pdf-bytes"
    assert result["size"] == len(b"pdf-bytes")
    # download_url is the item's web_url, never the pre-authenticated @microsoft.graph.downloadUrl
    assert result["download_url"] == "https://contoso.sharepoint.com/Reports/2025/q4.pdf"
    assert not result["download_url"].startswith(fakes.FAKE_DOWNLOAD)


async def test_download_missing_file_raises_filenotfound(fake, tmp_path, monkeypatch):
    session = fakes.FakeAiohttpSession(fake)
    monkeypatch.setattr(SharePointFileManager, "_http_session", lambda self: session)
    client = fakes.make_sharepoint_client(fake, drive_id="drive-1")
    tool = DownloadSharePointFileTool(credentials={})

    with pytest.raises(FileNotFoundError):
        await tool._execute_graph_operation(
            client,
            site="TeamSite",
            library="Documents",
            file_path="Reports/does-not-exist.pdf",
            local_destination=str(tmp_path),
        )


async def test_upload_sharepoint_file_tool_response_shape_and_overwrite(fake, tmp_path, monkeypatch):
    session = fakes.FakeAiohttpSession(fake)
    monkeypatch.setattr(SharePointFileManager, "_http_session", lambda self: session)
    client = fakes.make_sharepoint_client(fake, drive_id="drive-1")
    tool = UploadSharePointFileTool(credentials={})
    local_file = tmp_path / "upload.txt"
    local_file.write_bytes(b"0123456789abcdefghij")

    result = await tool._execute_graph_operation(
        client,
        site="TeamSite",
        library="Documents",
        local_file_path=str(local_file),
        folder_path="Uploads",
        overwrite=True,
    )

    assert set(result) == UPLOAD_KEYS
    assert result["site"] == "TeamSite"
    assert result["library"] == "Documents"
    assert result["folder_path"] == "Uploads"
    assert result["uploaded_file"] == "upload.txt"
    assert result["size"] == len(b"0123456789abcdefghij")
    assert result["web_url"] == "https://contoso.sharepoint.com/Uploads/upload.txt"
    assert result["server_relative_url"] == "/Uploads/upload.txt"

    # overwrite=False -> the upload session body carries conflictBehavior "fail".
    # The upload-session route addresses the target by path, so the fake (like the manager-level
    # xfer_manager tests in test_graph_filemanager.py) requires the destination to already exist.
    fake.drives_by_id["drive-1"].put_file("Uploads/other.txt", b"")
    session.requests.clear()
    fake.calls.clear()
    await tool._execute_graph_operation(
        client,
        site="TeamSite",
        library="Documents",
        local_file_path=str(local_file),
        folder_path="Uploads",
        rename_as="other.txt",
        overwrite=False,
    )
    body = next(call[3] for call in fake.calls if call[0] == "create_upload_session")
    assert body.item.additional_data["@microsoft.graph.conflictBehavior"] == "fail"


def test_sharepoint_client_import_removed():
    import parrot_tools.o365.sharepoint as mod

    assert "SharepointClient" not in vars(mod)
