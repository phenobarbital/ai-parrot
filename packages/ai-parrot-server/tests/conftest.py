"""Shared fixtures for the ai-parrot-server test suite."""
import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# FEAT-204: Ensure the worktree's own ai-parrot-server src is on sys.path.
# The venv editable install (.pth) points to the MAIN repo's
# packages/ai-parrot-server/src, so new modules added only in a worktree
# are not visible via the installed path.  We insert the worktree-local src
# first so that worktree-specific modules (e.g. parrot.human.suspended_store)
# are found before the main-repo copy.
# ---------------------------------------------------------------------------
_THIS_PKG_SRC = (Path(__file__).parent.parent / "src").resolve()
if str(_THIS_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_THIS_PKG_SRC))


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
