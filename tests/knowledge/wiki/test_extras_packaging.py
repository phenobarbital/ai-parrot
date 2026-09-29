"""FEAT-609 Q1: the `wiki-languages` extra must bring the structural tier."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[3] / "packages" / "ai-parrot" / "pyproject.toml"


def _extras() -> dict[str, list[str]]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


def test_wiki_languages_extra_pulls_astgrep() -> None:
    """Installing the language plugins alone must yield symbols (spec G7)."""
    names = [spec.split(">")[0].split("=")[0].strip() for spec in _extras()["wiki-languages"]]
    assert "ast-grep-py" in names


def test_wiki_structural_extra_kept() -> None:
    """The old extra name keeps working for existing install lines."""
    assert any(spec.startswith("ast-grep-py") for spec in _extras()["wiki-structural"])
