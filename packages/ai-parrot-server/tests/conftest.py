"""Shared fixtures for the ai-parrot-server test suite."""
import importlib.util
import shutil
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Cython extension stubs for ai-parrot-server tests
# (mirrors the root conftest — needed here because the server's pytest rootdir
# is packages/ai-parrot-server/, not the worktree root)
# ---------------------------------------------------------------------------

if "parrot.utils.types" not in sys.modules:
    _utils_types_mod = types.ModuleType("parrot.utils.types")

    class _SafeDict(dict):
        def __missing__(self, key):
            return None

    _utils_types_mod.SafeDict = _SafeDict
    sys.modules["parrot.utils.types"] = _utils_types_mod

if "parrot.utils.parsers.toml" not in sys.modules:
    _parsers_toml_mod = types.ModuleType("parrot.utils.parsers.toml")

    class _TOMLParser:
        def __init__(self, *args, **kwargs):
            pass

        def parse(self, content: str) -> dict:
            import tomllib as _tomllib  # type: ignore[import]
            return _tomllib.loads(content)

    _parsers_toml_mod.TOMLParser = _TOMLParser
    sys.modules["parrot.utils.parsers.toml"] = _parsers_toml_mod
    if "parrot.utils.parsers" not in sys.modules:
        _parsers_pkg = types.ModuleType("parrot.utils.parsers")
        _parsers_pkg.TOMLParser = _TOMLParser
        sys.modules["parrot.utils.parsers"] = _parsers_pkg


# ---------------------------------------------------------------------------
# FEAT-204: Ensure the worktree's own sources are first on sys.path AND that
# the parrot namespace package path is extended so sub-packages are found
# from the worktree.
#
# The venv editable installs (.pth files) point to the MAIN repo's package
# directories.  New modules added only in a worktree (e.g.
# parrot.human.suspended_store, WaitStrategy in parrot.human) are not visible
# via those installed paths.  We insert both worktree-local src dirs at the
# front of sys.path so worktree-specific modules shadow the main-repo copies
# for the duration of the test run.
#
# Additionally, we extend parrot.__path__ with the worktree's parrot src
# dirs so that Python's sub-package lookup finds the worktree modules even
# when 'parrot' itself was already loaded from the editable install.
# ---------------------------------------------------------------------------

_WORKTREE_ROOT = Path(__file__).parents[3].resolve()  # .../feat-204-hitl_web/

# ai-parrot-server worktree src
_THIS_PKG_SRC = (Path(__file__).parent.parent / "src").resolve()
if str(_THIS_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_THIS_PKG_SRC))

# ai-parrot (core) worktree src — exports WaitStrategy, updated HumanTool, etc.
_CORE_PKG_SRC = (_WORKTREE_ROOT / "packages" / "ai-parrot" / "src").resolve()
if str(_CORE_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_CORE_PKG_SRC))

# ai-parrot-integrations worktree src — exports new integrations (e.g. mcp/)
# added in FEAT-263 / TASK-1648 and not yet present in the installed editable
# package that points at the main-repo path.
_INTEGRATIONS_PKG_SRC = (
    _WORKTREE_ROOT / "packages" / "ai-parrot-integrations" / "src"
).resolve()
if str(_INTEGRATIONS_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_INTEGRATIONS_PKG_SRC))

# Extend parrot.__path__ to include the worktree's parrot sub-directories so
# that Python's sub-package resolution finds worktree-specific modules even
# after parrot has already been imported via the editable install.
try:
    import importlib
    import parrot as _parrot_pkg  # noqa: E402
    _wt_parrot_dir = str(_CORE_PKG_SRC / "parrot")
    _wt_server_dir = str(_THIS_PKG_SRC / "parrot")
    _wt_integrations_dir = str(_INTEGRATIONS_PKG_SRC / "parrot")
    for _wt_dir in [_wt_server_dir, _wt_parrot_dir, _wt_integrations_dir]:
        if _wt_dir not in _parrot_pkg.__path__:
            _parrot_pkg.__path__.insert(0, _wt_dir)
    # Also extend parrot.integrations.__path__ so worktree-local sub-packages
    # (e.g. parrot.integrations.mcp) are found even when parrot.integrations
    # was already loaded from the editable install's main-repo path.
    import parrot.integrations as _parrot_integrations_pkg  # noqa: E402
    _wt_integrations_subdir = str(_INTEGRATIONS_PKG_SRC / "parrot" / "integrations")
    if _wt_integrations_subdir not in _parrot_integrations_pkg.__path__:
        _parrot_integrations_pkg.__path__.insert(0, _wt_integrations_subdir)
    # Invalidate Python's path finder cache so it rediscovers sub-packages
    # from the updated parrot.__path__.
    importlib.invalidate_caches()
    # If parrot.human is already cached but is the main-repo version lacking
    # WaitStrategy, patch it by loading the WaitStrategy class directly from
    # the worktree source file and injecting it into the cached module.
    # This avoids a full module reload (which would trigger Cython stub deps).
    _ph_mod = sys.modules.get("parrot.human")
    if _ph_mod is not None and not hasattr(_ph_mod, "WaitStrategy"):
        _wt_models_file = _wt_parrot_dir + "/human/models.py"
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("_wt_parrot_human_models", _wt_models_file)
        if _spec and _spec.loader:
            _wt_models = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_wt_models)
            # Inject the missing exports into the cached parrot.human module.
            _ph_mod.WaitStrategy = _wt_models.WaitStrategy
            # Also update parrot.human.models to the worktree version.
            sys.modules["parrot.human.models"] = _wt_models
    # Invalidate cached parrot.handlers so they reload from the updated path.
    for _cached_key in list(sys.modules.keys()):
        if _cached_key in ("parrot.handlers.web_hitl", "parrot.handlers.agent"):
            del sys.modules[_cached_key]
except Exception as _exc:
    pass  # Non-fatal; tests may still work if modules are correctly loaded


def _package_available(name: str) -> bool:
    """Return True if the given package is importable."""
    return importlib.util.find_spec(name) is not None


def _uv_available() -> bool:
    """Return True if the ``uv`` CLI is available on PATH."""
    return shutil.which("uv") is not None


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "requires_apscheduler: requires the scheduler extra (apscheduler)",
    )
    config.addinivalue_line(
        "markers",
        "requires_aioquic: requires the mcp extra (aioquic)",
    )
    config.addinivalue_line(
        "markers",
        "wheel_build: requires building the wheel (slow, needs uv)",
    )


def pytest_runtest_setup(item):
    """Auto-skip tests that require unavailable extras."""
    markers = {m.name for m in item.iter_markers()}
    if "requires_apscheduler" in markers:
        if not _package_available("apscheduler"):
            pytest.skip("requires scheduler extra (apscheduler)")
    if "requires_aioquic" in markers:
        if not _package_available("aioquic"):
            pytest.skip("requires mcp extra (aioquic)")
    if "wheel_build" in markers:
        if not _uv_available():
            pytest.skip("wheel_build tests require uv on PATH")


@pytest.fixture(scope="session")
def satellite_pkg_root() -> Path:
    """Return the root of the satellite package directory."""
    # This file lives at packages/ai-parrot-server/tests/conftest.py
    return Path(__file__).parent.parent.resolve()


@pytest.fixture(scope="session")
def satellite_wheel_path(satellite_pkg_root, tmp_path_factory) -> Path:
    """Build the satellite wheel once per session and return its path."""
    out_dir = tmp_path_factory.mktemp("wheel")
    subprocess.check_call(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir), str(satellite_pkg_root)],
    )
    wheels = list(out_dir.glob("ai_parrot_server-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"
    return wheels[0]


@pytest.fixture(scope="session")
def satellite_wheel_namelist(satellite_wheel_path) -> list[str]:
    """All filenames inside the satellite wheel (slash-separated)."""
    with zipfile.ZipFile(satellite_wheel_path) as zf:
        return zf.namelist()


@pytest.fixture
def host_pyproject_text() -> str:
    """The host's current pyproject.toml text."""
    here = Path(__file__).parent.parent.parent  # packages/
    return (here / "ai-parrot" / "pyproject.toml").read_text(encoding="utf-8")
