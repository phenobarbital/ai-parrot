"""Unit tests for the FEAT-421 version bump and migration guide (TASK-2207)."""

from pathlib import Path

import parrot_formdesigner.version as v

GUIDE = Path(__file__).parents[4] / "docs" / "migration" / "feat-421-forms-tenant-in-url.md"


def test_version_bumped():
    assert v.__version__ == "0.9.0"


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
