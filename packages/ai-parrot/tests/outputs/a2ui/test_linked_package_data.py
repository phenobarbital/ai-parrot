"""FEAT-598 S7: the linked contract ships as package data."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


def test_linked_contract_is_package_data() -> None:
    """Pin the linked contract package-data globs."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    globs = data["tool"]["setuptools"]["package-data"]["parrot.outputs.a2ui.linked"]
    assert "contract/*.json" in globs
    assert "contract/fixtures/*/*.json" in globs
