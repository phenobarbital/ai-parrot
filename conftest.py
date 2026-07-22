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
    # Worktree root — exposes scripts/ to tests (FEAT-145 / TASK-994).
    _WORKTREE_ROOT,
    # ai-parrot core: prepend worktree src so changes are visible to tests.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot", "src"),
    # ai-parrot-loaders: include worktree version.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot-loaders", "src"),
    # ai-parrot-visualizations: FEAT-324 adds interactive_html.py to the
    # parrot.outputs.a2ui_renderers PEP 420 namespace (merged via
    # pkgutil.extend_path in parrot/outputs/__init__.py, which walks
    # sys.path) — without this entry the namespace merge only ever finds
    # the main-repo editable-install copy, hiding worktree-local renderer
    # changes entirely.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot-visualizations", "src"),
    # ai-parrot-tools: also include worktree version.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot-tools", "src"),
    # ai-parrot-server: FEAT-204 adds new modules (SuspendingWebHumanTool,
    # SuspendedExecutionStore) — prepend worktree src so they shadow the
    # main-repo editable install.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot-server", "src"),
    # ai-parrot-integrations: FEAT-261 adds auth.py — prepend worktree src
    # so the new module is discoverable by tests.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot-integrations", "src"),
]
for _p in reversed(_EXTRA_PATHS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# FEAT-204: Extend the parrot namespace package __path__ to include the
# worktree's package sources.  The `parrot` namespace package (namespace
# __init__.py loaded from the editable install) holds a __path__ list that
# Python uses to locate sub-packages.  Simply inserting the worktree src
# into sys.path is not enough because Python follows parrot.__path__ for
# sub-package lookup.  We must prepend the worktree's parrot directory to
# parrot.__path__ AND parrot.human.__path__ (and parrot.handlers.__path__)
# so that worktree-specific modules shadow the main-repo copies.
try:
    import parrot as _parrot_pkg
    _wt_parrot_src = os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot", "src", "parrot")
    _wt_server_src = os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot-server", "src", "parrot")
    _wt_integrations_src = os.path.join(
        _WORKTREE_ROOT, "packages", "ai-parrot-integrations", "src", "parrot"
    )
    for _wt_dir in [_wt_integrations_src, _wt_server_src, _wt_parrot_src]:
        if _wt_dir not in _parrot_pkg.__path__:
            _parrot_pkg.__path__.insert(0, _wt_dir)
except Exception:
    pass  # If parrot isn't importable yet, the sys.path insertion above covers it

# FEAT-226: Extend parrot_tools.__path__ so that new submodules added in this
# worktree (advisory_engine, soc2_advisory) are discoverable even when
# parrot_tools was already cached from the main-repo editable install.
try:
    import parrot_tools as _parrot_tools_pkg
    _wt_parrot_tools_src = os.path.join(
        _WORKTREE_ROOT, "packages", "ai-parrot-tools", "src", "parrot_tools"
    )
    if _wt_parrot_tools_src not in _parrot_tools_pkg.__path__:
        _parrot_tools_pkg.__path__.insert(0, _wt_parrot_tools_src)
    # Also extend the security sub-package path
    import parrot_tools.security as _pt_security
    _wt_security_src = os.path.join(_wt_parrot_tools_src, "security")
    if _wt_security_src not in _pt_security.__path__:
        _pt_security.__path__.insert(0, _wt_security_src)
except Exception:
    pass  # Non-fatal; the sys.path insertion above is sufficient in most cases

# After updating parrot.__path__, invalidate cached parrot.human / parrot.handlers
# so they are re-found from the updated path.
for _key in list(sys.modules.keys()):
    if (
        _key == "parrot.human"
        or _key.startswith("parrot.human.")
        or _key == "parrot.handlers.web_hitl"
        or _key == "parrot.handlers.agent"
    ):
        del sys.modules[_key]

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
        {
            "get": staticmethod(lambda *a, **kw: _LocalFileManager()),
            "create": staticmethod(lambda *a, **kw: _LocalFileManager()),
        },
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

    # parrot.interfaces.file.abstract sub-module stub (required by overflow.py)
    _parrot_interfaces_file_abstract = types.ModuleType("parrot.interfaces.file.abstract")
    _parrot_interfaces_file_abstract.FileManagerInterface = _FileManagerInterface
    _parrot_interfaces_file_abstract.FileMetadata = _FileMetadata
    sys.modules.setdefault("parrot.interfaces.file.abstract", _parrot_interfaces_file_abstract)

    # parrot.interfaces.file.s3 sub-module stub (required by s3_overflow.py)
    _parrot_interfaces_file_s3 = types.ModuleType("parrot.interfaces.file.s3")
    _parrot_interfaces_file_s3.S3FileManager = _parrot_interfaces_file.S3FileManager
    sys.modules.setdefault("parrot.interfaces.file.s3", _parrot_interfaces_file_s3)

    # parrot.interfaces.file.local sub-module stub (required by various modules)
    _parrot_interfaces_file_local = types.ModuleType("parrot.interfaces.file.local")
    _parrot_interfaces_file_local.LocalFileManager = _LocalFileManager
    sys.modules.setdefault("parrot.interfaces.file.local", _parrot_interfaces_file_local)

    # parrot.interfaces.file.gcs sub-module stub
    _parrot_interfaces_file_gcs = types.ModuleType("parrot.interfaces.file.gcs")
    _parrot_interfaces_file_gcs.GCSFileManager = _parrot_interfaces_file.GCSFileManager
    sys.modules.setdefault("parrot.interfaces.file.gcs", _parrot_interfaces_file_gcs)

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

# ── Cython extension stubs (compiled .so files absent in git worktrees) ─────
# Worktrees contain only the .pyx sources, not the compiled .so modules.
# Inject minimal pure-Python stubs so that package __init__ files can import
# from Cython extensions without needing the compiled extensions present.

# parrot.utils.types (SafeDict)
if "parrot.utils.types" not in sys.modules:
    _utils_types_mod = types.ModuleType("parrot.utils.types")

    class _SafeDict(dict):
        """Pure-Python stand-in for the Cython SafeDict."""

        def __missing__(self, key):
            return None

    _utils_types_mod.SafeDict = _SafeDict
    sys.modules["parrot.utils.types"] = _utils_types_mod

# parrot.utils.parsers.toml (TOMLParser)
if "parrot.utils.parsers.toml" not in sys.modules:
    _parsers_toml_mod = types.ModuleType("parrot.utils.parsers.toml")

    class _TOMLParser:
        """Pure-Python stand-in for the Cython TOMLParser."""

        def __init__(self, *args, **kwargs):
            pass

        def parse(self, content: str) -> dict:
            import tomllib as _tomllib  # type: ignore[import]
            return _tomllib.loads(content)

    _parsers_toml_mod.TOMLParser = _TOMLParser
    sys.modules["parrot.utils.parsers.toml"] = _parsers_toml_mod
    # Ensure the parsers package is visible too
    if "parrot.utils.parsers" not in sys.modules:
        _parsers_pkg = types.ModuleType("parrot.utils.parsers")
        _parsers_pkg.TOMLParser = _TOMLParser
        sys.modules["parrot.utils.parsers"] = _parsers_pkg

for _mod_name in (
    "parrot.models.responses",
    "parrot.clients.base",
    # FEAT-176: ensure the real parrot.bots.abstract (with EventEmitterMixin)
    # is loaded before the test conftest installs its lightweight stub.
    "parrot.bots.abstract",
):
    if _mod_name not in sys.modules:
        try:
            _importlib.import_module(_mod_name)
        except ImportError:
            pass  # noqa: S110 — some deps may not be available in all envs
