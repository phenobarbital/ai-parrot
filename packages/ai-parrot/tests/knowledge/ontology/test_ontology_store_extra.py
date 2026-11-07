"""The ontology-store extra declares the vocabulary store's drivers (FEAT-824)."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


def test_ontology_store_extra() -> None:
    """Assert the ontology store extra has its exact runtime requirements."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    extra = data["project"]["optional-dependencies"]["ontology-store"]
    assert sorted(extra) == sorted(["asyncpg>=0.29", "pgvector>=0.2", "rdflib>=7.0", "pyshacl>=0.26", "numpy>=1.26"])
