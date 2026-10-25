"""Unit tests for the FEAT-421 version bump and migration guide (TASK-2207)."""

from importlib.metadata import version as dist_version
from pathlib import Path

from packaging.version import Version

import parrot_formdesigner.version as v

GUIDE = Path(__file__).parents[4] / "docs" / "migration" / "feat-421-forms-tenant-in-url.md"


def test_version_bumped() -> None:
    """The module version matches distribution metadata and is valid PEP 440."""
    assert v.__version__ == dist_version("parrot-formdesigner")
    assert str(Version(v.__version__)) == v.__version__


def test_migration_guide_exists():
    assert GUIDE.is_file()


def test_guide_documents_org_exemption():
    text = GUIDE.read_text()
    assert "/org/" in text
    assert "unchanged" in text.lower()


def test_guide_documents_error_slugs():
    text = GUIDE.read_text()
    for slug in ("tenant_not_declared", "tenant_forbidden", "tenant_conflict"):
        assert slug in text
