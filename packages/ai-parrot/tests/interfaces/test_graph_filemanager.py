"""FEAT-603 GraphDriveFileManager unit tests (TASK-3749)."""
import datetime as dt
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

from ._graph_fakes import FakeDriveItem, make_probe


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
    folder = FakeDriveItem(id="folder-1", name="reports", folder=SimpleNamespace(), web_url="https://example.test/reports")
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
        BatchItemResult(index=0, source="source", destination="destination", state="succeeded", ok=True, unexpected=True)
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
