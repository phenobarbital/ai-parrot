"""FEAT-598 AC12 / FEAT-610 AC3 / FEAT-611 M1: ai-parrot-tools declares querysource>=5.1.2 (no runtime gate)."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_querysource_floor_is_5_1_2() -> None:
    """Pin the querysource floor declared by the db extra."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    db = data["project"]["optional-dependencies"]["db"]
    assert "querysource>=5.1.2" in db
