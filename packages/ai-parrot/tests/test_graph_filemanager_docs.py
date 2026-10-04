"""FEAT-603 TASK-3766 — the Graph file-manager guide keeps its required sections."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUIDE = ROOT / "docs" / "interfaces" / "graph-filemanager.md"
O365 = ROOT / "docs" / "integrations" / "office365-oauth2.md"
HEADINGS = [
    "## Install",
    "## Quick start",
    "## Authentication",
    "## Paths",
    "## Uploads and downloads",
    "## Sharing links",
    "## Batch operations",
    "## Search",
    "## Serving over HTTP",
    "## Agents (FileManagerToolkit)",
    "## Permissions",
    "## Live tests",
]


def test_guide_has_required_sections():
    text = GUIDE.read_text(encoding="utf-8")
    missing = [h for h in HEADINGS if f"\n{h}\n" not in f"\n{text}\n"]
    assert not missing, missing


def test_guide_documents_serving_limit_and_extra():
    text = GUIDE.read_text(encoding="utf-8")
    assert "413" in text and "64 MiB" in text and "ai-parrot[msgraph]" in text
    serving = text.split("## Serving over HTTP", 1)[1].split("\n## ", 1)[0].lower()
    assert "buffer" in serving  # the section must say the extension buffers whole files (S7)


def test_o365_doc_lists_manager_permissions():
    text = O365.read_text(encoding="utf-8")
    assert "## File managers (SharePoint / OneDrive)" in text and "Files.ReadWrite.All" in text
