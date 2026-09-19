"""FEAT-576: every SDD authoring template declares the taxonomy keys."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sdd.sdd_meta import DocTaxonomy, parse_taxonomy

TEMPLATES = Path(__file__).resolve().parents[2] / "sdd" / "templates"


@pytest.mark.parametrize("name", ["spec.md", "brainstorm.md", "proposal.md"])
def test_templates_declare_taxonomy_keys(name: str) -> None:
    path = TEMPLATES / name
    text = path.read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    assert "\nprojects: []\n" in front
    assert "\ntags: []\n" in front
    assert parse_taxonomy(path) == DocTaxonomy()
