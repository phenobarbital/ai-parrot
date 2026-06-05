"""Shared fixtures for the agent-browser driver tests.

The driver lives at ``../scripts/agent_browser.py`` (a skill asset, not an
installed package), so we add that directory to ``sys.path`` for the unit
tests that import it directly. Integration tests invoke it as a subprocess.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import agent_browser as ab  # noqa: E402  (path set above)


@pytest.fixture
def ab_mod():
    """The imported driver module."""
    return ab


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point the module's state root at a throwaway dir for every test."""
    monkeypatch.setattr(ab, "STATE_ROOT", tmp_path / "ab-home")
    yield
