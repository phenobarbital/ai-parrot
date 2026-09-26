"""FEAT-598 AC12: ai-parrot-tools declares querysource>=5.1.1 (no runtime gate)."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_querysource_floor_is_5_1_1() -> None:
    """Pin the querysource floor declared by the db extra."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    db = data["project"]["optional-dependencies"]["db"]
    assert "querysource>=5.1.1" in db
