"""Pytest guard: no test leaves a ``MagicMock/`` directory behind.

``unittest.mock.MagicMock`` implements ``__fspath__``, and its default return
value is the string ``"MagicMock/<mock name>/<id>"``.  So any code that does
``Path(value).mkdir(parents=True)`` on a value that turned out to be a mock
materialises that tree under the process CWD.  This is not hypothetical: a
mocked ``parrot.conf`` made ``DevLoopGraphMemory.from_config()`` ->
``SQLitePersistence`` write a whole SQLite graph plane into the repo root
(``MagicMock/mock.DEV_LOOP_GRAPH_MEMORY_PATH.strip()/<id>/default.db``).

Policy: an artifact a test creates is cleaned up by that test — it is not
something to .gitignore and forget.  Two layers implement it:

* :func:`_cleanup_mock_fspath_artifacts` — autouse, function-scoped, so the
  removal happens in the teardown of the very test that leaked, and a warning
  names it in the run summary.
* :func:`pytest_sessionfinish` — the counterpart for a mock that reaches a
  path while modules are being *imported* (conftest import / collection),
  which predates every test and therefore every fixture.

This module is imported by both the repo-root ``conftest.py`` and
``packages/ai-parrot/conftest.py``: several packages declare their own
``[tool.pytest.ini_options]``, so pytest's ``confcutdir`` excludes the
repo-root conftest from runs rooted inside those packages, and each pytest
rootdir needs its own registration.  To adopt it in another package, copy the
``_load_fspath_guard()`` helper from either of those conftests and add::

    _guard = _load_fspath_guard(_REPO_ROOT)
    _cleanup_mock_fspath_artifacts = _guard._cleanup_mock_fspath_artifacts
    pytest_sessionfinish = _guard.pytest_sessionfinish

to that package's root ``conftest.py``.  Load it by PATH, never as
``tests.mock_fspath_guard``: nine directories in this workspace are ``tests``
packages, so that name resolves differently depending on pytest's rootdir.
"""

from __future__ import annotations

import shutil
import warnings
from collections.abc import Iterable
from pathlib import Path

import pytest

#: Name of the directory ``MagicMock.__fspath__()`` produces.
MOCK_FSPATH_DIRNAME = "MagicMock"

#: Repo root — the directory containing this module.
_REPO_ROOT = Path(__file__).resolve().parent


def _mock_fspath_roots() -> set[Path]:
    """Return the directories a leaked ``MagicMock/`` tree can appear in.

    ``Path(<mock>).mkdir()`` is relative, so the process CWD is the real
    target; the repo root is included for runs launched from elsewhere.

    Returns:
        The candidate root directories.
    """
    return {Path.cwd(), _REPO_ROOT}


def _sweep_mock_fspath_artifacts(roots: Iterable[Path]) -> list[Path]:
    """Delete ``MagicMock/`` trees under ``roots`` and report what was removed.

    Args:
        roots: Directories to sweep.

    Returns:
        The paths that were removed, in sweep order.
    """
    removed: list[Path] = []
    for root in roots:
        stray = root / MOCK_FSPATH_DIRNAME
        # Guard the recursive delete: exact name, real directory, no symlink.
        if stray.name != MOCK_FSPATH_DIRNAME or stray.is_symlink():
            continue
        if not stray.is_dir():
            continue
        shutil.rmtree(stray, ignore_errors=True)
        removed.append(stray)
    return removed


#: ``MagicMock/`` trees that already existed when this module was imported.
#: Snapshotted at import time rather than in ``pytest_configure`` because
#: importing the conftests themselves can put a mock on a filesystem path,
#: which happens before any pytest hook runs.
_PRE_EXISTING: set[Path] = {
    root for root in _mock_fspath_roots()
    if (root / MOCK_FSPATH_DIRNAME).exists()
}


@pytest.fixture(autouse=True)
def _cleanup_mock_fspath_artifacts(request):
    """Delete any ``MagicMock/`` tree the test under execution leaves on disk.

    Autouse and function-scoped, so the cleanup runs in the teardown of the
    very test that created the artifact.  The leak is reported as a warning
    rather than silently swallowed, so the offending test stays identifiable
    in the run summary.

    Args:
        request: pytest request, used to name the offending test.

    Yields:
        Control to the test.
    """
    roots = _mock_fspath_roots()
    pre_existing = {
        root for root in roots if (root / MOCK_FSPATH_DIRNAME).exists()
    }

    yield

    for stray in _sweep_mock_fspath_artifacts(roots - pre_existing):
        warnings.warn(
            f"{request.node.nodeid} leaked a {MOCK_FSPATH_DIRNAME}/ directory "
            f"into {stray.parent} (a MagicMock reached a filesystem path); it "
            "has been removed. Fix the test, or the code path that accepted "
            "the mock as a path.",
            stacklevel=1,
        )


def pytest_sessionfinish(session, exitstatus) -> None:
    """Sweep ``MagicMock/`` trees created at import/collection time.

    The autouse fixture covers artifacts a *test* creates; a mock that reaches
    a path while a module is being imported predates every test, so it needs
    this session-scoped counterpart.

    Args:
        session: The finished pytest session.
        exitstatus: The session exit status (unused).
    """
    for stray in _sweep_mock_fspath_artifacts(_mock_fspath_roots() - _PRE_EXISTING):
        print(  # sessionfinish has no logging surface
            f"\n[conftest] removed leaked {stray} — a MagicMock reached a "
            "filesystem path during collection/import."
        )
