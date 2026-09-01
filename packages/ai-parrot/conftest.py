"""Root conftest for the packages/ai-parrot test suite.

Ensures that the src layout is importable without a ``pip install -e .``
by prepending ``packages/ai-parrot/src`` to ``sys.path`` at collection time.
This lets pytest discover and import ``parrot.*`` modules regardless of
whether the package is installed in the active virtual environment.
"""
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

from mock_fspath_guard import (  # noqa: F401 - registers fixture + hook
    _cleanup_mock_fspath_artifacts,
    pytest_sessionfinish,
)
