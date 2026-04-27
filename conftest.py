"""Root conftest.py for the worktree.

Ensures the worktree's package sources take precedence over the main-repo
editable installs registered via .pth files in site-packages.  Without this,
pytest would silently import from the main-repo sources, making feature
changes invisible to tests.

IMPORTANT: The packages/ai-parrot/tests/conftest.py installs lightweight stubs
for many ``parrot.*`` modules via ``sys.modules.setdefault()``.  That conftest
is processed AFTER this root conftest — so we must ensure that the real
``parrot.models.responses`` (and ``parrot.clients.base``) are fully imported
and registered in ``sys.modules`` BEFORE the test conftest runs.  Once
``sys.modules[key]`` is populated, ``setdefault`` is a no-op.

FEAT-125 NOTE: parrot.interfaces.file and parrot.tools.filemanager were added
by FEAT-124 and depend on navigator.utils.file symbols that aren't present in
the currently-installed navigator version.  We stub those out here so ALL
test suites can collect without requiring the newer navigator.
"""
import sys
import os
import types

# Worktree root — the directory that contains THIS file.
_WORKTREE_ROOT = os.path.dirname(os.path.abspath(__file__))

# Prepend the worktree package src directories so they shadow the main-repo
# editable-install .pth entries.
_EXTRA_PATHS = [
    # ai-parrot core: prepend worktree src so changes are visible to tests.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot", "src"),
    # ai-parrot-loaders: include worktree version.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot-loaders", "src"),
    # ai-parrot-tools: also include worktree version.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot-tools", "src"),
]
for _p in reversed(_EXTRA_PATHS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── navigator.utils.file stubs (pre-FEAT-124 navigator compatibility) ──────
# FEAT-124 added parrot.interfaces.file and parrot.tools.filemanager that
# import symbols from navigator.utils.file which only exist in
# navigator-api >= 2.15.  Stub them before any parrot package is imported.
try:
    import navigator.utils.file as _nuf

    _FileManagerInterface = type(
        "FileManagerInterface",
        (),
        {"__init__": lambda self, *a, **kw: None},
    )
    _FileMetadata = type("FileMetadata", (), {})
    _LocalFileManager = type("LocalFileManager", (_FileManagerInterface,), {})
    _TempFileManager = type("TempFileManager", (_FileManagerInterface,), {})
    _FileManagerFactory = type(
        "FileManagerFactory",
        (),
        {"get": staticmethod(lambda *a, **kw: _LocalFileManager())},
    )

    for _attr, _val in [
        ("FileManagerInterface", _FileManagerInterface),
        ("FileMetadata", _FileMetadata),
        ("LocalFileManager", _LocalFileManager),
        ("TempFileManager", _TempFileManager),
        ("FileManagerFactory", _FileManagerFactory),
    ]:
        if not hasattr(_nuf, _attr):
            setattr(_nuf, _attr, _val)

    # navigator.utils.file.abstract stub
    _nuf_abstract = types.ModuleType("navigator.utils.file.abstract")
    _nuf_abstract.FileManagerInterface = _FileManagerInterface
    _nuf_abstract.FileMetadata = _FileMetadata
    sys.modules.setdefault("navigator.utils.file.abstract", _nuf_abstract)

    # parrot.interfaces.file shim
    _parrot_interfaces_file = types.ModuleType("parrot.interfaces.file")
    _parrot_interfaces_file.FileManagerInterface = _FileManagerInterface
    _parrot_interfaces_file.FileMetadata = _FileMetadata
    _parrot_interfaces_file.LocalFileManager = _LocalFileManager
    _parrot_interfaces_file.TempFileManager = _TempFileManager
    _parrot_interfaces_file.S3FileManager = type(
        "S3FileManager", (_FileManagerInterface,), {}
    )
    _parrot_interfaces_file.GCSFileManager = type(
        "GCSFileManager", (_FileManagerInterface,), {}
    )
    sys.modules.setdefault("parrot.interfaces.file", _parrot_interfaces_file)

    # parrot.tools.filemanager stub
    _parrot_tools_fm = types.ModuleType("parrot.tools.filemanager")
    _parrot_tools_fm.FileManagerFactory = _FileManagerFactory
    sys.modules.setdefault("parrot.tools.filemanager", _parrot_tools_fm)

except Exception:  # noqa: BLE001
    pass  # If navigator isn't available at all, downstream errors will be informative

# Force the real parrot.models.responses to be imported NOW (before the
# test conftest registers its stub via setdefault).  The test conftest's
# _install_parrot_stubs() uses setdefault so it won't override a module
# that's already present.
import importlib as _importlib

for _mod_name in (
    "parrot.models.responses",
    "parrot.clients.base",
):
    if _mod_name not in sys.modules:
        try:
            _importlib.import_module(_mod_name)
        except ImportError:
            pass  # noqa: S110 — some deps may not be available in all envs
