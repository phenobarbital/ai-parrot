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
