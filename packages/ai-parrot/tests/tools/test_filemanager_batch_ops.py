"""FEAT-603 TASK-3759/3760 — find / batch operations on FileManagerToolkit and FileManagerTool."""
import json
import sys
from pathlib import Path

# The repository-wide test bootstrap (root conftest.py) installs non-package
# compatibility stubs for these modules before collection, predating FEAT-603
# turning them into real packages/modules. Pop the stale stubs so the real
# ones are imported fresh (same workaround as TASK-3749's test_graph_filemanager.py).
sys.modules.pop("parrot.interfaces.file", None)
sys.modules.pop("parrot.tools.filemanager", None)

from navigator.utils.file import FileMetadata  # noqa: E402
from parrot.interfaces.file.batch import BatchItemResult  # noqa: E402
from parrot.tools.filemanager import FileManagerToolkit  # noqa: E402


def _fake_metadata(path: str) -> FileMetadata:
    """Build a real ``FileMetadata`` instance (pydantic validates the dataclass type strictly)."""
    return FileMetadata(
        name=Path(path).name,
        path=path,
        size=1,
        content_type="text/plain",
        modified_at=None,
        url=None,
    )


class _LoopOnlyManager:
    """Fake manager exposing only single-item ops (no native batch methods)."""

    def __init__(self) -> None:
        self.upload_calls = []
        self.download_calls = []

    async def upload_file(self, source: Path, destination: str) -> FileMetadata:
        self.upload_calls.append((source, destination))
        return _fake_metadata(destination)

    async def download_file(self, source: str, destination: Path) -> Path:
        self.download_calls.append((source, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"data")
        return destination


class _NativeBatchManager:
    """Fake manager exposing native ``upload_files`` / ``download_files``."""

    def __init__(self) -> None:
        self.upload_files_calls = []
        self.download_files_calls = []

    async def upload_files(self, pairs):
        self.upload_files_calls.append(pairs)
        return [
            BatchItemResult(
                index=i,
                source=str(src),
                destination=dst,
                state="succeeded",
                ok=True,
            )
            for i, (src, dst) in enumerate(pairs)
        ]

    async def download_files(self, pairs):
        self.download_files_calls.append(pairs)
        return [
            BatchItemResult(
                index=i,
                source=src,
                destination=str(dst),
                state="succeeded",
                ok=True,
            )
            for i, (src, dst) in enumerate(pairs)
        ]


class _FindManager:
    """Fake manager recording the kwargs its ``find_files`` was invoked with."""

    def __init__(self) -> None:
        self.calls = []

    async def find_files(self, keywords=None, extension=None, prefix=None):
        self.calls.append({"keywords": keywords, "extension": extension, "prefix": prefix})
        return []


async def test_toolkit_exposes_new_tools():
    tk = FileManagerToolkit(manager_type="temp")
    names = {t.name for t in tk.get_tools()}
    assert {"fs_find_files", "fs_batch_upload", "fs_batch_download"} <= names


def test_allowed_operations_accepts_new_keys():
    tk = FileManagerToolkit(
        manager_type="temp",
        allowed_operations={"find", "batch_upload"},
    )
    names = set(tk.list_tool_names())
    assert names == {"fs_find_files", "fs_batch_upload"}


async def test_toolkit_batch_fallback_loops_single_ops(tmp_path):
    tk = FileManagerToolkit(manager_type="temp", default_output_dir=str(tmp_path))
    fake_manager = _LoopOnlyManager()
    tk.manager = fake_manager

    good_a = tmp_path / "a.txt"
    good_a.write_text("aaa")
    missing = tmp_path / "missing.txt"
    good_b = tmp_path / "b.txt"
    good_b.write_text("bbb")

    items = [
        {"source": str(good_a), "destination": "dest/a.txt"},
        {"source": str(missing), "destination": "dest/missing.txt"},
        {"source": str(good_b), "destination": "dest/b.txt"},
    ]
    result = await tk.batch_upload(items)

    assert result["total"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    states = [item["state"] for item in result["items"]]
    assert states == ["succeeded", "failed", "succeeded"]
    # Fallback loop was used, not any native batch method.
    assert len(fake_manager.upload_calls) == 2
    # The returned dict must be JSON-serialisable.
    json.dumps(result)


async def test_toolkit_batch_uses_native_when_available(tmp_path):
    tk = FileManagerToolkit(manager_type="temp", default_output_dir=str(tmp_path))
    fake_manager = _NativeBatchManager()
    tk.manager = fake_manager

    good = tmp_path / "good.txt"
    good.write_text("data")

    items = [{"source": str(good), "destination": "dest/good.txt"}]
    result = await tk.batch_upload(items)

    assert len(fake_manager.upload_files_calls) == 1
    called_pairs = fake_manager.upload_files_calls[0]
    assert called_pairs == [(Path(str(good)), tk._storage_path("dest/good.txt"))]
    assert result["succeeded"] == 1
    json.dumps(result)


async def test_toolkit_find_uses_backend_override():
    tk = FileManagerToolkit(manager_type="temp")
    fake_manager = _FindManager()
    tk.manager = fake_manager

    result = await tk.find_files(keywords=["a", "b"], extension=".csv", prefix="folder")

    assert fake_manager.calls == [
        {"keywords": ["a", "b"], "extension": ".csv", "prefix": tk._storage_path("folder")}
    ]
    assert result == {"files": [], "count": 0}


def test_storage_path_is_drive_relative_for_graph_and_unchanged_otherwise():
    # GraphDriveFileManager subclasses are currently abstract (missing unrelated methods),
    # and constructing a real one isn't needed to exercise _storage_path: bypass __init__
    # and stub just the attribute it reads (manager_type), per project convention for
    # toolkits/agents whose real constructor has heavyweight side effects.
    tk_graph = FileManagerToolkit.__new__(FileManagerToolkit)
    tk_graph.manager_type = "sharepoint"
    assert tk_graph._storage_path("a/b.txt") == "a/b.txt"

    tk_local = FileManagerToolkit(manager_type="temp")
    assert tk_local._storage_path("a/b.txt") == tk_local._resolve_output_path("a/b.txt")
