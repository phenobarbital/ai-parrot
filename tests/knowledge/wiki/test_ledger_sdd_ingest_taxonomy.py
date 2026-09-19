"""FEAT-576: projects/tags in the SDD spec page summary."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from parrot.knowledge.wiki.ledger.sdd_ingest import SDDGraphIngest


def _spec(root: Path, front: str) -> Path:
    p = root / "sdd" / "specs" / "demo.spec.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntype: feature\nbase_branch: dev\n{front}---\n# Demo\n", encoding="utf-8")
    return p


def test_ingest_summary_with_taxonomy(tmp_path: Path) -> None:
    page, _ = SDDGraphIngest(MagicMock(), tmp_path)._process_spec_file(
        _spec(tmp_path, "projects: [ai-parrot]\ntags: [x]\n")
    )
    assert page.summary == "SDD specification for demo.spec (type: feature, base: dev; projects: ai-parrot; tags: x)"


def test_ingest_summary_untagged_unchanged(tmp_path: Path) -> None:
    page, _ = SDDGraphIngest(MagicMock(), tmp_path)._process_spec_file(_spec(tmp_path, ""))
    assert page.summary == "SDD specification for demo.spec (type: feature, base: dev)"


def test_ingest_invalid_taxonomy_still_ingests(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = SDDGraphIngest(MagicMock(), tmp_path)._process_spec_file(_spec(tmp_path, "tags: ['!!']\n"))
    assert result is not None
    assert "Invalid projects/tags" in caplog.text
