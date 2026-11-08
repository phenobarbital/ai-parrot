"""Static checks for the G1 check catalogue; no server or SDK is imported."""

from __future__ import annotations

import sys
from pathlib import Path

SPIKE = Path(__file__).resolve().parents[2] / "scripts" / "spikes" / "surrealdb_g1"
BLOCKING = {
    "G1-01",
    "G1-02",
    "G1-03",
    "G1-04",
    "G1-05",
    "G1-07",
    "G1-08",
    "G1-09",
    "G1-10",
    "G1-11",
    "G1-12",
}


def test_all_checks_complete_and_flagged() -> None:
    """All checks are ordered and carry their specification blocking flags."""
    sys.path.insert(0, str(SPIKE))
    try:
        from checks import ALL_CHECKS

        ids = [check.check_id for check in ALL_CHECKS]
        assert ids == [f"G1-{number:02d}" for number in range(1, 14)]
        assert {check.check_id for check in ALL_CHECKS if check.blocking} == BLOCKING
    finally:
        sys.path.remove(str(SPIKE))


def test_import_does_not_load_surrealdb() -> None:
    """Static check discovery remains runnable without the optional SDK."""
    before = set(sys.modules)
    sys.path.insert(0, str(SPIKE))
    try:
        import checks  # noqa: F401
    finally:
        sys.path.remove(str(SPIKE))
    assert "surrealdb" not in set(sys.modules) - before
