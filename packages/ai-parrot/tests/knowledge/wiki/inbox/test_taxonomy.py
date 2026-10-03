"""Focused FEAT-626 regression and failure-path tests."""

import hashlib
from pathlib import Path

import pytest
from parrot.knowledge.wiki.charter import Charter, Taxonomy, TaxonomyKind, default_taxonomy, load_charter
from pydantic import ValidationError


_CHARTER_YAML = """\
version: "1"
scope:
  include: []
  exclude: []
weights:
  density: 0.4
  novelty: 0.35
  durability: 0.25
thresholds:
  admit: 0.75
  reject: 0.35
calibration: {}
"""


def test_default_taxonomy_six_kinds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify exact mappings and independent mutable defaults."""
    del tmp_path, monkeypatch
    taxonomy = default_taxonomy()

    assert taxonomy.default_kind == "note"
    assert taxonomy.max_tags == 8
    assert {kind.id: kind.category for kind in taxonomy.kinds} == {
        "meeting": "summary",
        "briefing": "overview",
        "decision": "concept",
        "report": "synthesis",
        "memo": "summary",
        "note": "concept",
    }

    taxonomy.kinds[0].tag_hints.append("mutated")
    assert "mutated" not in default_taxonomy().kinds[0].tag_hints


def test_charter_without_taxonomy_block_still_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the raw-byte fingerprint unchanged for an old charter."""
    del monkeypatch
    charter_path = tmp_path / "charter.yaml"
    original_yaml_bytes = _CHARTER_YAML.encode()
    charter_path.write_bytes(original_yaml_bytes)

    charter = load_charter(charter_path)

    assert charter.taxonomy == default_taxonomy()
    assert charter.fingerprint == hashlib.sha256(original_yaml_bytes).hexdigest()

    other_charter = Charter.model_validate(
        {
            "version": "1",
            "scope": {"include": [], "exclude": []},
            "weights": {"density": 0.4, "novelty": 0.35, "durability": 0.25},
            "thresholds": {"admit": 0.75, "reject": 0.35},
            "calibration": {},
        }
    )
    charter.taxonomy.kinds[0].tag_hints.append("local")
    assert "local" not in other_charter.taxonomy.kinds[0].tag_hints


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (
            lambda: TaxonomyKind(id="", description="bad", category="summary"),
            "kebab-case",
        ),
        (
            lambda: TaxonomyKind(id="not_kebab", description="bad", category="summary"),
            "kebab-case",
        ),
        (
            lambda: TaxonomyKind(id="note", description="bad", category="unknown"),
            "unknown wiki page category",
        ),
        (
            lambda: Taxonomy(
                kinds=[
                    TaxonomyKind(id="note", description="note", category="concept"),
                    TaxonomyKind(id="note", description="another", category="summary"),
                ]
            ),
            "unique",
        ),
        (
            lambda: Taxonomy(
                default_kind="missing",
                kinds=[TaxonomyKind(id="note", description="note", category="concept")],
            ),
            "default_kind",
        ),
        (lambda: Taxonomy(kinds=[]), "at least one kind"),
        (
            lambda: Taxonomy(max_tags=0, kinds=[TaxonomyKind(id="note", description="note", category="concept")]),
            "greater than or equal",
        ),
        (
            lambda: Taxonomy(max_tags=33, kinds=[TaxonomyKind(id="note", description="note", category="concept")]),
            "less than or equal",
        ),
    ],
)
def test_taxonomy_validators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory: object,
    match: str,
) -> None:
    """Reject duplicates, invalid ids/categories/default kinds and invalid tag limits."""
    del tmp_path, monkeypatch
    with pytest.raises(ValidationError, match=match):
        factory()
