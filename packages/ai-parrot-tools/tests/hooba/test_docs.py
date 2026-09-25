"""FEAT-602 TASK-3746 — the operator page stays in sync with the toolkit."""
from pathlib import Path

DOC = Path(__file__).resolve().parents[4] / "docs" / "hooba-toolkit.md"
COMPOSITE = (
    "hooba_whoami",
    "hooba_find_contact",
    "hooba_list_drafts",
    "hooba_download_invoice_pdf",
    "hooba_recover_web_session",
    "hooba_run_web_action",
    "hooba_create_invoice_draft",
    "hooba_create_purchase_invoice_draft",
    "hooba_attach_document",
    "hooba_import_bbva_statement",
)


def test_docs_name_every_composite_tool():
    text = DOC.read_text(encoding="utf-8")
    missing = [name for name in COMPOSITE if name not in text]
    assert not missing, missing


def test_docs_state_drafts_only_and_spec_pin():
    text = DOC.read_text(encoding="utf-8")
    # The spec pin version must be present
    assert "2026.6.17" in text, "Spec pin version 2026.6.17 not found in docs"
    # The page must state that issue/confirm are impossible
    assert "never does" in text.lower(), "Missing 'never does' section"
    assert "never issues" in text.lower() or "never does" in text.lower(), "Missing 'never issues' statement"
    assert "never confirms" in text.lower() or "never does" in text.lower(), "Missing 'never confirms' statement"
