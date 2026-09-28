"""FEAT-611 M1: the environment runs querysource >= 5.1.2 (spec §4 test_querysource_version_gate)."""

from __future__ import annotations

import pytest
from packaging.version import Version

from parrot_tools.querysource._qs import installed_version

MIN_QUERYSOURCE = Version("5.1.2")


def test_querysource_version_gate() -> None:
    """installed_version() parses and is at least the workspace floor."""
    try:
        raw = installed_version()
    except ImportError:
        pytest.skip("querysource not installed ([db] extra absent)")
    assert Version(raw) >= MIN_QUERYSOURCE, f"querysource {raw} < {MIN_QUERYSOURCE}"
