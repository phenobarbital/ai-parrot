"""Validate the database migration operator guide through the required CLI."""

from pathlib import Path
import subprocess


def test_database_migrations_techwiki() -> None:
    """Require the spec-scoped techwiki check to succeed in this checkout."""
    root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [
            "parrot",
            "sdd",
            "techwiki",
            "check",
            "--spec",
            "sdd/specs/db-upgrade.spec.md",
            "--root",
            ".",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
