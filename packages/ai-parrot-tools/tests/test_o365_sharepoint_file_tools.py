"""FEAT-603 TASK-3761/3762 — SharePoint O365 tools keep their response shapes on top of SharePointFileManager."""

import importlib.util
import pathlib
import sys

import pytest

from parrot_tools.o365.sharepoint import ListSharePointFilesTool, SearchSharePointFilesTool

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
