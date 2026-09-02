"""Root conftest for the packages/ai-parrot test suite.

Ensures that the src layout is importable without a ``pip install -e .``
by prepending ``packages/ai-parrot/src`` to ``sys.path`` at collection time.
This lets pytest discover and import ``parrot.*`` modules regardless of
whether the package is installed in the active virtual environment.
"""
import importlib.util
import sys
from pathlib import Path

# Ensure the src layout is importable without pip install -e
sys.path.insert(0, str(Path(__file__).parent / "src"))

# This package declares its own [tool.pytest.ini_options], so runs rooted here
# never load the repo-root conftest (pytest's confcutdir stops at the rootdir).
# Register the leaked-``MagicMock/``-directory guard for them too: a test owns
# every artifact it creates, whichever rootdir it runs under.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_fspath_guard(repo_root: Path):
    """Import ``tests/mock_fspath_guard.py`` by path, not by module name.

    ``tests.mock_fspath_guard`` would be ambiguous: nine directories in
    this workspace are ``tests`` packages — including this package's own
    ``packages/ai-parrot/tests`` — so which one the name resolves to
    depends on pytest's rootdir. Loading by absolute path removes the
    question, and the fixed ``sys.modules`` key is shared with the
    repo-root conftest so the guard is loaded once, not twice.

    Args:
        repo_root: Absolute path of the repository/worktree root.

    Returns:
        The loaded guard module.
    """
    name = "parrot_mock_fspath_guard"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = repo_root / "tests" / "mock_fspath_guard.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load the MagicMock/ guard from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_guard = _load_fspath_guard(_REPO_ROOT)
_cleanup_mock_fspath_artifacts = _guard._cleanup_mock_fspath_artifacts  # noqa: F401
pytest_sessionfinish = _guard.pytest_sessionfinish  # noqa: F401
