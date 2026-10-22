"""FEAT-608 TASK-3817 — cross-cutting invariants (AC1, AC2, AC16, AC18, AC23)."""

import ast
import inspect
import json
import os
import pathlib
import subprocess
import sys

import pytest

# The repository-wide test bootstrap installs a non-package compatibility stub
# for this module before collection. This task verifies the real new submodule.
sys.modules.pop("parrot.interfaces.file", None)
sys.modules.pop("parrot.tools.filemanager", None)

from navigator.utils.file import FileManagerInterface  # noqa: E402
from parrot.interfaces.file import entries, graph  # noqa: E402
from parrot.interfaces.file.gdrive import GoogleDriveFileManager  # noqa: E402
from parrot.interfaces.file.graph import GraphDriveFileManager  # noqa: E402
from parrot.interfaces.file.onedrive import OneDriveFileManager  # noqa: E402
from parrot.interfaces.file.sharepoint import SharePointFileManager  # noqa: E402
from parrot.interfaces.google import CalendarClient, GoogleClient  # noqa: E402
from parrot.tools.filemanager import (  # noqa: E402
    FileManagerFactory,
    FileManagerTool,
    FileManagerToolkit,
)
from parrot_tools.google.base import GoogleBaseTool  # noqa: E402
from parrot_tools.google.calendar import GoogleCalendarToolkit  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[4]
SNAPSHOT = pathlib.Path(__file__).with_name("gdrive_signature_snapshot.json")
NEW_MODULES = [
    ROOT / "packages/ai-parrot/src/parrot/interfaces/file/gdrive.py",
    ROOT / "packages/ai-parrot/src/parrot/interfaces/file/entries.py",
    ROOT / "packages/ai-parrot-tools/src/parrot_tools/google/drive.py",
]
BANNED_MODULES = frozenset(
    {"httpx", "requests", "langchain", "langchain_core", "langchain_community", "langgraph", "langsmith"}
)
INTERFACE_METHODS = (
    "list_files",
    "get_file_url",
    "upload_file",
    "download_file",
    "copy_file",
    "delete_file",
    "exists",
    "get_file_metadata",
    "create_file",
    "create_folder",
    "remove_folder",
    "rename_folder",
    "rename_file",
    "find_files",
)
SNAPSHOT_CLASSES = {
    cls.__name__: cls
    for cls in (
        GoogleClient,
        CalendarClient,
        GoogleBaseTool,
        GoogleCalendarToolkit,
        FileManagerFactory,
        FileManagerTool,
        FileManagerToolkit,
        GraphDriveFileManager,
        SharePointFileManager,
        OneDriveFileManager,
    )
}


def _shape(fn):
    """Return a callable's parameter names, kinds, and defaults."""
    return [
        (parameter.name, parameter.kind, parameter.default) for parameter in inspect.signature(fn).parameters.values()
    ]


def test_all_interface_methods_implemented_with_exact_signatures():
    """AC1: no abstract method left; parameter shapes equal navigator's; independent of Graph."""
    assert issubclass(GoogleDriveFileManager, FileManagerInterface)
    assert not issubclass(GoogleDriveFileManager, GraphDriveFileManager)
    names = set(FileManagerInterface.__abstractmethods__)
    assert not (names & GoogleDriveFileManager.__abstractmethods__)
    for name in names | set(INTERFACE_METHODS):
        assert _shape(getattr(GoogleDriveFileManager, name)) == _shape(getattr(FileManagerInterface, name)), name


def test_get_file_url_signature_matches_interface():
    """AC1: get_file_url keeps the interface's (path, expiry) shape."""
    assert _shape(GoogleDriveFileManager.get_file_url) == _shape(FileManagerInterface.get_file_url)


def test_no_httpx_or_requests_in_new_modules():
    """AC18: no banned imports and no print() calls in the new modules."""
    for module in NEW_MODULES:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".")[0]
                    assert root_name not in BANNED_MODULES, f"{module.name}: banned import {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                root_name = (node.module or "").split(".")[0]
                assert root_name not in BANNED_MODULES, f"{module.name}: banned from {node.module}"
            elif isinstance(node, ast.Call):
                is_print = isinstance(node.func, ast.Name) and node.func.id == "print"
                assert not is_print, f"{module.name}: print() call is banned"


def test_public_signatures_unchanged_vs_snapshot():
    """AC23: every public signature captured on the base commit is unchanged."""
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert data["base_commit"]
    assert data["signatures"]
    for key, expected in data["signatures"].items():
        cls_name, method = key.split(".", 1)
        if key == "GoogleClient.get_drive_client":
            continue
        fn = inspect.getattr_static(SNAPSHOT_CLASSES[cls_name], method)
        fn = fn.__func__ if isinstance(fn, (staticmethod, classmethod)) else fn
        live = str(inspect.signature(fn))
        # The only allowed change: the manager_type Literal gains 'gdrive' (FEAT-608).
        live = live.replace(", 'gdrive']", "]")
        assert live == expected, f"Signature mismatch for {key}"


def test_graph_reexports_relocated_names():
    """AC16: names relocated into entries.py are still importable from graph.py."""
    assert graph.DriveEntry is entries.DriveEntry
    assert graph._GuardedFileServingExtension is entries.GuardedFileServingExtension


def _loaded_modules(import_stmt: str) -> set:
    """Run ``import_stmt`` in a fresh interpreter; return which watched modules got loaded."""
    code = (
        "import json, sys\n"
        f"{import_stmt}\n"
        "print('LOADED=' + json.dumps([m for m in ('parrot.interfaces.google', 'aiogoogle') if m in sys.modules]))\n"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, env=env, check=False
    )
    assert result.returncode == 0, result.stderr[-2000:]
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("LOADED="))
    return set(json.loads(line[len("LOADED=") :]))


def test_gdrive_module_imports_no_google_client_at_module_level():
    """AC2: importing the manager module does not pull GoogleClient or aiogoogle.

    Third-party dependencies (navigator_auth) may import ``aiogoogle`` on their own, so the
    baseline is measured with ``navigator.utils.file`` alone and only *extra* modules fail.
    """
    baseline = _loaded_modules("import navigator.utils.file")
    loaded = _loaded_modules("import parrot.interfaces.file.gdrive")
    assert not (loaded - baseline), f"gdrive import pulled {sorted(loaded - baseline)}"
    assert "parrot.interfaces.google" not in loaded
