"""FEAT-732 — the audit-trail page documents every check id and skip reason."""

from pathlib import Path

from parrot_formdesigner.api.handlers import READ_FORM_AUDIT
from parrot_formdesigner.core.audit_trail import CheckId, SkipReason

PAGE = Path(__file__).parents[4] / "docs" / "formdesigner-validation-audit-trail.md"


def test_page_exists() -> None:
    assert PAGE.is_file()


def test_every_check_id_documented() -> None:
    text = PAGE.read_text()
    missing = [c.value for c in CheckId if f"`{c.value}`" not in text]
    assert not missing, f"undocumented CheckId values: {missing}"


def test_every_skip_reason_documented() -> None:
    text = PAGE.read_text()
    missing = [s.value for s in SkipReason if f"`{s.value}`" not in text]
    assert not missing, f"undocumented SkipReason values: {missing}"


def test_permission_codename_documented() -> None:
    assert f"`{READ_FORM_AUDIT}`" in PAGE.read_text()
