"""FEAT-601 M13 — operator guide structure (TASK-3729)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
DOC = REPO_ROOT / "docs" / "knowledge" / "manuals.md"

HEADINGS = (
    "## 1. Installation",
    "## 2. Tenancy and authorization",
    "## 3. Storage",
    "## 4. Ingestion",
    "## 5. Curation",
    "## 6. Answering and channels",
    "## 7. Offline export",
    "## 8. Spike gate",
    "## 9. v1 limitations",
    "## 10. Command reference",
)
COMMANDS = ("add", "add-video", "refresh", "verify", "queue", "relink-tips", "export", "spike")


def test_manuals_doc_has_all_sections() -> None:
    """All ten fixed headings are present."""
    text = DOC.read_text(encoding="utf-8")
    for heading in HEADINGS:
        assert heading in text, heading


def test_manuals_doc_documents_every_command() -> None:
    """Each `parrot manuals <cmd>` appears in the command reference."""
    text = DOC.read_text(encoding="utf-8")
    for command in COMMANDS:
        assert f"parrot manuals {command}" in text, command


def test_manuals_doc_names_v1_limitations() -> None:
    """OCR / callouts / serials / offline are documented in §9 (AC18)."""
    text = DOC.read_text(encoding="utf-8")
    # OCR
    assert "OCR" in text, "OCR should be mentioned in §9"
    # Callouts
    assert "callouts" in text, "callouts should be mentioned in §9"
    # Serial applicability
    assert "serial" in text, "serial applicability should be mentioned in §9"
    # Offline viewer
    assert "offline viewer" in text, "offline viewer should be mentioned in §9"
