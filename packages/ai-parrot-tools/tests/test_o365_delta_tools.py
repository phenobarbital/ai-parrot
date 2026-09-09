"""SharePoint/OneDrive delta tool tests (TASK-3042)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Optional

import pytest

from parrot_tools.o365 import (
    DeltaOneDriveFilesTool,
    DeltaSharePointFilesTool,
)
from parrot_tools.o365.base import O365Tool
from parrot_tools.o365.onedrive import (
    DeltaOneDriveFilesArgs,
    DownloadOneDriveFileTool,
    ListOneDriveFilesTool,
    SearchOneDriveFilesTool,
    UploadOneDriveFileTool,
)
from parrot_tools.o365.sharepoint import (
    DeltaSharePointFilesArgs,
    DownloadSharePointFileTool,
    ListSharePointFilesTool,
    SearchSharePointFilesTool,
    UploadSharePointFileTool,
)

from .test_o365_delta_protocol import FakeGraph, FakeResponse, GraphError, item

GRAPH = "https://graph.microsoft.com"
O365_DIR = Path(__file__).resolve().parents[1] / "src" / "parrot_tools" / "o365"


class FakeClient:
    """An authenticated client exposing only ``graph_client``."""

    def __init__(self, graph: FakeGraph) -> None:
        self.graph_client = graph


def tool_pair() -> list[Any]:
    """Both delta tools, constructed the way a toolkit builds them."""
    return [DeltaSharePointFilesTool(), DeltaOneDriveFilesTool()]


@pytest.mark.parametrize("tool", tool_pair(), ids=lambda tool: tool.name)
def test_delta_tools_are_o365_tools_with_typed_arguments(tool):
    assert isinstance(tool, O365Tool)
    assert tool.name in {"delta_sharepoint_files", "delta_onedrive_files"}
    assert tool.description
    fields = set(tool.args_schema.model_fields)
    assert {"drive_id", "delta_token", "folder_path", "max_pages"} <= fields
    # The O365 auth lifecycle fields are inherited, not redefined.
    assert {"auth_mode", "user_assertion", "user_id"} <= fields


@pytest.mark.parametrize("tool", tool_pair(), ids=lambda tool: tool.name)
def test_the_graph_operation_hook_is_the_only_entry_point(tool):
    """Authentication and ToolResult wrapping stay in ``O365Tool._execute``."""
    assert type(tool)._execute is O365Tool._execute
    assert "_execute_graph_operation" in vars(type(tool))


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", tool_pair(), ids=lambda tool: tool.name)
async def test_both_tools_produce_equivalent_typed_outcomes(tool):
    graph = FakeGraph(
        {
            None: FakeResponse([item("a")], next_link=f"{GRAPH}/page2"),
            f"{GRAPH}/page2": FakeResponse(
                [item("b"), {"id": "c", "deleted": {"state": "deleted"}}],
                delta_link=f"{GRAPH}/final",
            ),
        }
    )
    result = await tool._execute_graph_operation(FakeClient(graph), drive_id="drive-1")

    assert result["drive_id"] == "drive-1"
    assert [entry["item_id"] for entry in result["items"]] == ["a", "b", "c"]
    assert result["tombstones"] == ["c"]
    assert result["delta_link"] == f"{GRAPH}/final"
    assert result["pages"] == 2
    assert result["complete"] is True
    assert result["truncated"] is False
    assert result["rescan_required"] is False
    assert set(graph.item_ids) == {"root"}, "drive-level delta"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", tool_pair(), ids=lambda tool: tool.name)
async def test_both_tools_resume_from_a_committed_cursor(tool):
    graph = FakeGraph({f"{GRAPH}/previous": FakeResponse([item("a")], delta_link=f"{GRAPH}/final")})
    result = await tool._execute_graph_operation(FakeClient(graph), drive_id="drive-1", delta_token=f"{GRAPH}/previous")
    assert graph.requested == [f"{GRAPH}/previous"]
    assert result["delta_link"] == f"{GRAPH}/final"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", tool_pair(), ids=lambda tool: tool.name)
async def test_both_tools_report_a_required_rescan_rather_than_deletions(tool):
    graph = FakeGraph({f"{GRAPH}/expired": GraphError(410)})
    result = await tool._execute_graph_operation(FakeClient(graph), drive_id="drive-1", delta_token=f"{GRAPH}/expired")
    assert result["rescan_required"] is True
    assert result["items"] == []
    assert result["tombstones"] == []
    assert result["delta_link"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", tool_pair(), ids=lambda tool: tool.name)
async def test_folder_filtering_and_page_bounds_are_forwarded(tool):
    graph = FakeGraph(
        {
            None: FakeResponse(
                [
                    item("a", path="/drive/root:/legal"),
                    item("b", path="/drive/root:/marketing"),
                ],
                next_link=f"{GRAPH}/page2",
            ),
            f"{GRAPH}/page2": FakeResponse([item("c")], delta_link=f"{GRAPH}/final"),
        }
    )
    result = await tool._execute_graph_operation(
        FakeClient(graph), drive_id="drive-1", folder_path="legal", max_pages=1
    )
    assert [entry["item_id"] for entry in result["items"]] == ["a"]
    assert result["truncated"] is True
    assert result["delta_link"] is None, "an unfinished walk commits no cursor"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", tool_pair(), ids=lambda tool: tool.name)
async def test_graph_errors_propagate_to_the_o365_error_wrapping(tool):
    graph = FakeGraph({None: GraphError(403)})
    with pytest.raises(Exception, match="403"):
        await tool._execute_graph_operation(FakeClient(graph), drive_id="drive-1")


# --------------------------------------------------------------------------
# Registration and regression
# --------------------------------------------------------------------------


def test_the_o365_package_exports_both_delta_tools():
    from parrot_tools import o365

    assert "DeltaSharePointFilesTool" in o365.__all__
    assert "DeltaOneDriveFilesTool" in o365.__all__
    # Pre-existing exports survive.
    for name in (
        "ListOneDriveFilesTool",
        "SearchOneDriveFilesTool",
        "DownloadOneDriveFileTool",
        "UploadOneDriveFileTool",
        "SendEmailTool",
        "ListEventsTool",
    ):
        assert name in o365.__all__, name


def test_bundles_register_the_delta_tools_alongside_the_existing_ones():
    from parrot_tools.o365 import bundle

    source = inspect.getsource(bundle)
    tree = ast.parse(source)
    constructed = {
        node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for name in (
        "ListSharePointFilesTool",
        "SearchSharePointFilesTool",
        "DownloadSharePointFileTool",
        "UploadSharePointFileTool",
        "DeltaSharePointFilesTool",
        "ListOneDriveFilesTool",
        "SearchOneDriveFilesTool",
        "DownloadOneDriveFileTool",
        "UploadOneDriveFileTool",
        "DeltaOneDriveFilesTool",
    ):
        assert name in constructed, name


def test_existing_tool_classes_are_untouched():
    for tool_class in (
        ListSharePointFilesTool,
        SearchSharePointFilesTool,
        DownloadSharePointFileTool,
        UploadSharePointFileTool,
        ListOneDriveFilesTool,
        SearchOneDriveFilesTool,
        DownloadOneDriveFileTool,
        UploadOneDriveFileTool,
    ):
        assert issubclass(tool_class, O365Tool)
        assert isinstance(getattr(tool_class, "name", None), str)


def test_argument_schemas_are_distinct_and_documented():
    assert DeltaSharePointFilesArgs is not DeltaOneDriveFilesArgs
    for schema in (DeltaSharePointFilesArgs, DeltaOneDriveFilesArgs):
        assert schema.model_fields["drive_id"].description
        assert "never expanded from model-supplied" in (schema.model_fields["drive_id"].description)


@pytest.mark.parametrize("module", ["sharepoint.py", "onedrive.py", "bundle.py", "delta.py"])
def test_no_contracts_or_scheduler_import_reaches_the_o365_lane(module):
    tree = ast.parse((O365_DIR / module).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("contracts" in name for name in imported), imported
    assert not any("scheduler" in name for name in imported), imported
