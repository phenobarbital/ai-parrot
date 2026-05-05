"""Unit tests for ``scripts.sdd.sdd_meta`` — FEAT-145 / TASK-994."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.sdd.sdd_meta import FlowMeta, emit, parse


def test_parse_no_frontmatter_returns_defaults(tmp_path: Path) -> None:
    """A file without frontmatter must yield the documented defaults."""
    f = tmp_path / "doc.md"
    f.write_text("# Heading\nbody\n")
    meta = parse(f)
    assert meta.type == "feature"
    assert meta.base_branch == "dev"


def test_parse_feature_with_dev_base(tmp_path: Path) -> None:
    """Standard feature frontmatter parses cleanly."""
    f = tmp_path / "doc.md"
    f.write_text("---\ntype: feature\nbase_branch: dev\n---\n# body\n")
    meta = parse(f)
    assert meta.type == "feature"
    assert meta.base_branch == "dev"


def test_parse_hotfix_requires_main(tmp_path: Path) -> None:
    """``type: hotfix`` with anything other than ``main`` must fail validation."""
    f = tmp_path / "doc.md"
    f.write_text("---\ntype: hotfix\nbase_branch: dev\n---\n")
    with pytest.raises(ValidationError):
        parse(f)


def test_parse_unknown_type_rejected(tmp_path: Path) -> None:
    """Unknown ``type`` values are rejected by Pydantic ``Literal``."""
    f = tmp_path / "doc.md"
    f.write_text("---\ntype: bug\nbase_branch: dev\n---\n")
    with pytest.raises(ValidationError):
        parse(f)


def test_emit_round_trips(tmp_path: Path) -> None:
    """``emit`` then ``parse`` must yield the original ``FlowMeta``."""
    meta = FlowMeta(type="hotfix", base_branch="main")
    block = emit(meta)
    assert block.startswith("---\n")
    assert block.endswith("---\n")
    f = tmp_path / "doc.md"
    f.write_text(block + "# body\n")
    assert parse(f) == meta
