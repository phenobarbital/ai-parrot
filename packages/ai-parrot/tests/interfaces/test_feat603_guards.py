"""FEAT-603 TASK-3768 — cross-cutting invariants (AC4, AC13, AC15, AC19, AC23)."""

import ast
import hashlib
import json
import pathlib
import sys

import pytest

# The repository-wide test bootstrap installs a non-package compatibility stub
# for this module before collection. This task verifies the real new submodule.
sys.modules.pop("parrot.interfaces.file", None)

ROOT = pathlib.Path(__file__).resolve().parents[4]
SNAPSHOT = pathlib.Path(__file__).with_name("feat603_signature_snapshot.json")
NEW_MODULES = [
    ROOT / "packages/ai-parrot/src/parrot/interfaces/file" / f"{n}.py"
    for n in ("graph", "batch", "sharepoint", "onedrive")
]
FILE_HASHES = {
    "packages/ai-parrot-tools/src/parrot_tools/o365/delta.py": "cdb321b8196e4e097e284d94c9cfb2486dd9f1020af93affa25b6eba6c1022f6",
    "packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py": "c6c82feb0fee7401b7f6c99ce93e8c8807f7381b8ab3bf0d4092eb3d6354bb4f",
    "packages/ai-parrot-tools/src/parrot_tools/o365/base.py": "fd8c5b95d90eaf5d014bbf985b40756899e7443ca936d6cb5b744d383c61f4bb",
    "packages/ai-parrot/src/parrot/interfaces/sharepoint.py": "d65e397bac117f528942503870317c16a2a18dedf940ba7c6cb042c03c264e1d",
    "packages/ai-parrot/src/parrot/interfaces/o365.py": "2a1c94ea77fb8f26bb655b90e173b95359f33cb49087dd1c43a42f8ead480aef",
}
CLASS_HASHES = {
    (
        "packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py",
        "DeltaSharePointFilesArgs",
    ): "ad0ee3f2822201677f421527d9e9a56daaeb149e2911b79af8a1ce488e3f752c",
    (
        "packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py",
        "DeltaSharePointFilesTool",
    ): "41f6aa8e58cdcf5d3c6f5973c1940c93a106c6334b3e4982d9c862387f54b704",
    (
        "packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py",
        "DeltaOneDriveFilesArgs",
    ): "d5d71031daa34a37622c0f1c81f66af9fb729fe949d680a5921c0b22e570baa0",
    (
        "packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py",
        "DeltaOneDriveFilesTool",
    ): "433525bb7d5c177b22bb1af208d2073d21de3b938474aa6f3b22c4c2893ae005",
}
BANNED_MODULES = frozenset(
    {"httpx", "requests", "langchain", "langchain_core", "langchain_community", "langgraph", "langsmith"}
)


@pytest.mark.parametrize("rel,digest", sorted(FILE_HASHES.items()))
def test_protected_files_byte_identical(rel, digest):
    """AC4, AC13: Protected files must be byte-identical to base commit."""
    assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel


@pytest.mark.parametrize("key,digest", sorted(CLASS_HASHES.items()))
def test_delta_class_blocks_unchanged(key, digest):
    """AC13: Delta class blocks must be unchanged."""
    rel, cls = key
    src = (ROOT / rel).read_text(encoding="utf-8")
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == cls)
    assert hashlib.sha256(ast.get_source_segment(src, node).encode()).hexdigest() == digest, cls


def test_no_banned_imports_or_print_in_new_modules():
    """AC15: No httpx/requests/langchain/print in new core modules."""
    for module in NEW_MODULES:
        src = module.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(module))

        for node in ast.walk(tree):
            # Check for banned imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in BANNED_MODULES or any(alias.name.startswith(f"{b}.") for b in BANNED_MODULES):
                        pytest.fail(f"{module.name}: banned import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module in BANNED_MODULES or any(
                    (node.module or "").startswith(f"{b}.") for b in BANNED_MODULES
                ):
                    pytest.fail(f"{module.name}: banned from {node.module}")
                # Also check for parrot_tools imports (core never imports tools)
                if node.module and node.module.startswith("parrot_tools"):
                    pytest.fail(f"{module.name}: core must not import parrot_tools")

            # Check for print() calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "print":
                    pytest.fail(f"{module.name}: print() call is banned")


def _shape(fn):
    """Compute parameter shape for a function."""
    a = fn.args
    pos = a.posonlyargs + a.args
    defs = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    out = [[p.arg, "pos", ast.unparse(d) if d is not None else None] for p, d in zip(pos, defs, strict=True)]
    if a.vararg:
        out.append([a.vararg.arg, "var", None])
    out += [
        [p.arg, "kwonly", ast.unparse(d) if d is not None else None]
        for p, d in zip(a.kwonlyargs, a.kw_defaults, strict=True)
    ]
    if a.kwarg:
        out.append([a.kwarg.arg, "varkw", None])
    return out


def test_public_signatures_unchanged():
    """AC19: Every public method in the snapshot keeps its parameter shape."""
    snapshot_data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    base_commit = snapshot_data["base_commit"]
    signatures = snapshot_data["signatures"]

    # Target classes to check
    TARGETS = {
        "packages/ai-parrot/src/parrot/interfaces/sharepoint.py": ["SharepointClient"],
        "packages/ai-parrot/src/parrot/interfaces/onedrive.py": ["OneDriveClient"],
        "packages/ai-parrot/src/parrot/interfaces/o365.py": ["O365Client"],
        "packages/ai-parrot/src/parrot/tools/filemanager.py": [
            "FileManagerFactory",
            "FileManagerTool",
            "FileManagerToolkit",
        ],
        "packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py": [
            "SharePointToolkit",
            "OneDriveToolkit",
            "Office365FileManagementToolkit",
        ],
    }

    current_keys = set()
    for path, classes in TARGETS.items():
        src = (ROOT / path).read_text(encoding="utf-8")
        for node in ast.parse(src).body:
            if isinstance(node, ast.ClassDef) and node.name in classes:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                        not item.name.startswith("_") or item.name == "__init__"
                    ):
                        key = f"{path}::{node.name}.{item.name}"
                        current_keys.add(key)
                        if key in signatures:
                            current_shape = _shape(item)
                            expected_shape = signatures[key]
                            assert current_shape == expected_shape, f"Signature mismatch for {key}"

    # AC19 gap fix: the loop above only catches a *changed* signature for a method that
    # still exists. It silently misses a *removed* or *renamed* public method, because it
    # only ever looks up `signatures[key]` for a `key` derived from *current* source. Assert
    # the reverse direction too: every snapshotted key for one of these target files must
    # still be present in current source.
    target_paths = set(TARGETS)
    snapshotted_target_keys = {k for k in signatures if k.split("::", 1)[0] in target_paths}
    missing = snapshotted_target_keys - current_keys
    assert not missing, f"Public method(s) removed or renamed since the snapshot: {sorted(missing)}"


async def test_sharepoint_manager_never_populates_srcfiles_across_operations():
    """AC23: _srcfiles stays empty across every SharePoint manager operation."""
    import io

    from parrot.interfaces.file.sharepoint import SharePointFileManager

    from ._graph_fakes import FakeAiohttpSession, FakeDrive, FakeGraphClient, make_sharepoint_client

    fake = FakeGraphClient({"drive-1": FakeDrive()})
    client = make_sharepoint_client(fake, drive_id="drive-1")
    fake.drives_by_id["drive-1"].put_file("test.txt", b"hello world")

    manager = SharePointFileManager("TeamSite")
    manager.adopt_client(client)
    session = FakeAiohttpSession(fake)
    manager._http_session = lambda: session

    # Verify _srcfiles is empty initially
    assert client._srcfiles == [], "Initial _srcfiles should be empty"

    await manager.list_files()
    assert client._srcfiles == [], "_srcfiles should be empty after list_files"

    await manager.list_entries()
    assert client._srcfiles == [], "_srcfiles should be empty after list_entries"

    await manager.find_files(keywords="test")
    assert client._srcfiles == [], "_srcfiles should be empty after find_files"

    await manager.upload_file(io.BytesIO(b"hello world"), "upload.txt")
    assert client._srcfiles == [], "_srcfiles should be empty after upload_file"

    await manager.download_file("test.txt", io.BytesIO())
    assert client._srcfiles == [], "_srcfiles should be empty after download_file"

    await manager.copy_file("test.txt", "test_copy.txt")
    assert client._srcfiles == [], "_srcfiles should be empty after copy_file"

    await manager.rename_file("test_copy.txt", "renamed.txt")
    assert client._srcfiles == [], "_srcfiles should be empty after rename_file"

    await manager.delete_file("renamed.txt")
    assert client._srcfiles == [], "_srcfiles should be empty after delete_file"
