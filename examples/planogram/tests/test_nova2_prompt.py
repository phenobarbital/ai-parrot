"""Unit tests for the closed-set vocabulary loader (FEAT-592, TASK-3641).

Pure-function tests: no AWS, no network, no planogram data committed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prompt import (
    NOVA_PROMPT_VERSION,
    NOVA_STAGE,
    PlanogramVocabulary,
    load_planogram_vocabulary,
)


@pytest.fixture
def planogram(tmp_path: Path) -> Path:
    """A minimal two-shelf planogram with a duplicate brand and a duplicate SKU."""
    payload = {
        "planogram": {"name": "synthetic"},
        "shelves": [
            {
                "shelf_number": 1,
                "products": {
                    "pos 1:1": {"product": "9C228AN", "brand": "HP", "display_name": "HP 31"},
                    "pos 1:2": {"product": "T502XL", "brand": "Epson", "family": "502"},
                },
            },
            {
                "shelf_number": 2,
                "products": {
                    "pos 2:1": {"product": "9C228AN", "brand": "HP", "aliases": ["HP 31 tri"]},
                    "pos 2:2": {"product": "PG-245", "brand": "Canon", "colors": ["black"]},
                },
            },
        ],
    }
    path = tmp_path / "planogram.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_vocabulary_reads_product_and_brand_only(planogram: Path) -> None:
    """Products and brands are collected; descriptor fields are ignored."""
    vocab = load_planogram_vocabulary(planogram)
    assert vocab.products == ["9C228AN", "PG-245", "T502XL"]
    assert vocab.brands == ["Canon", "Epson", "HP"]
    assert "HP 31" not in vocab.products + vocab.brands
    assert "502" not in vocab.products + vocab.brands
    assert "black" not in vocab.products + vocab.brands


def test_vocabulary_deduplicates_and_sorts(planogram: Path) -> None:
    """A SKU repeated across shelves appears once, and output order is stable."""
    vocab = load_planogram_vocabulary(planogram)
    assert len(set(vocab.products)) == len(vocab.products)
    assert len(set(vocab.brands)) == len(vocab.brands)
    assert vocab.products == sorted(vocab.products)
    assert vocab.brands == sorted(vocab.brands)


def test_vocabulary_rejects_non_planogram_json(tmp_path: Path) -> None:
    """A JSON file without a 'shelves' list is rejected, not silently empty."""
    path = tmp_path / "not_a_planogram.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(ValueError, match="shelves"):
        load_planogram_vocabulary(path)


def test_vocabulary_allows_empty_shelves(tmp_path: Path) -> None:
    """An empty but well-formed planogram yields empty lists, not an error."""
    path = tmp_path / "empty_planogram.json"
    path.write_text(json.dumps({"shelves": []}), encoding="utf-8")
    assert load_planogram_vocabulary(path) == PlanogramVocabulary(products=[], brands=[])


def test_prompt_versions_differ_from_pipeline() -> None:
    """The cache key constants must not collide with the shared open-set prompt."""
    assert NOVA_PROMPT_VERSION != "identify-v1"
    assert NOVA_STAGE != "identify"
