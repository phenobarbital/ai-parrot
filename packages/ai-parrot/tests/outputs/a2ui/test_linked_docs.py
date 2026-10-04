"""FEAT-598 (TASK-3796): AC13 — the linked-surface docs exist and state the required facts."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
DOCS = REPO_ROOT / "docs"


def _read(rel: str) -> str:
    """Return a docs file's text, failing clearly when it is missing."""
    path = DOCS / rel
    assert path.is_file(), f"missing doc: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "phrase",
    [
        "`locked` is not security",
        "trusted service behind a mandatory guard",
        "CSP is the host page's responsibility",
        "parrot_data_sources",
    ],
)
def test_linked_surfaces_doc_states(phrase: str) -> None:
    """The wire doc carries the AC13 trust-model statements."""
    assert phrase in _read("outputs/a2ui-linked-surfaces.md")


def test_a2ui_v1_extension_table() -> None:
    """a2ui-v1.md lists both new extension keys."""
    text = _read("outputs/a2ui-v1.md")
    assert "| `parrot_data_sources` |" in text
    assert "| `parrot_param` |" in text


def test_agentdashboard_reference_has_linked_section() -> None:
    """agentdashboard reference has the new §6.5."""
    text = _read("frontend/agentdashboard-a2ui-reference.md")
    assert "### 6.5 Linked surfaces (FEAT-598)" in text


def test_agentdashboard_reference_has_reload_item() -> None:
    """agentdashboard reference has the §7.4 Reload item."""
    text = _read("frontend/agentdashboard-a2ui-reference.md")
    assert "9. **Filter vs Refresh vs Reload (FEAT-598)**" in text


def test_querysource_toolkit_mentions_new_tool() -> None:
    """querysource-toolkit.md mentions `qs_build_linked_surface` and `tenant`."""
    text = _read("tools/querysource-toolkit.md")
    assert "qs_build_linked_surface" in text
    assert "Optional `tenant` argument" in text
