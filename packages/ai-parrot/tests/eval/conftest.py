"""Local conftest for parrot.eval tests.

Provides shared fixtures for the evaluation harness test suite.
This conftest is intentionally minimal to avoid importing broken
optional dependencies from the parent conftest.
"""
import sys
from pathlib import Path

import pytest

# Ensure the parrot source tree is importable when running tests directly.
SRC = Path(__file__).resolve().parents[3] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
