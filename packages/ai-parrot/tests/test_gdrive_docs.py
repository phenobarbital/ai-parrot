"""FEAT-608 TASK-3819 — the Drive docs exist with the required sections (AC19)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FM_DOC = ROOT / "docs/interfaces/gdrive-filemanager.md"
AUTH_DOC = ROOT / "docs/integrations/google-oauth2.md"
SECTIONS = (
    "Install",
    "Quick start",
    "Authentication",
    "Paths",
    "Uploads and downloads",
    "Sharing links",
    "Batch operations",
    "Search",
    "Serving over HTTP",
    "Agents",
)


def test_filemanager_doc_sections():
    text = FM_DOC.read_text(encoding="utf-8")
    for section in SECTIONS:
        assert f"## {section}" in text, section
    assert "serving_max_bytes" in text
    # No Workspace export in v1
    assert "Workspace export" in text


def test_oauth_doc_mentions_credentials_and_shared_drives():
    text = AUTH_DOC.read_text(encoding="utf-8")
    for needle in ("GOOGLE_CREDENTIALS_FILE", "service account", "cached", "shared drive"):
        assert needle in text, needle
