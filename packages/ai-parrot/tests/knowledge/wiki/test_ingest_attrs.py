"""Regression cases for FEAT-627."""

from pathlib import Path

import pytest

import parrot.knowledge.wiki.repo_scan as subject


def _write(root: Path, rel_path: str, content: str) -> None:
    """Write one test document beneath the temporary root."""
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _slice(root: Path, rel_path: str) -> subject.FileSlice:
    """Build one file slice and require that the fixture is readable."""
    result = subject.build_file_slice(root, rel_path)
    assert result is not None
    return result


def test_markdown_and_jira_attrs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify markdown and Jira-shaped document attrs retain their bodies."""
    monkeypatch.chdir(tmp_path)
    markdown = (
        "---\n"
        "type: Project\n"
        "status: ACTIVE\n"
        "primary_project: Wiki\n"
        "---\n\n"
        "# Wiki plan\n\n"
        "Body text.\n"
    )
    jira = (
        "---\n"
        "type: Issue\n"
        "status: In-Progress\n"
        "project: NAV\n"
        "assignee: Ada Lovelace\n"
        "assignee_id: jira-account-1\n"
        "---\n\n"
        "# NAV-1\n\n"
        "Rendered issue body.\n"
    )
    _write(tmp_path, "plan.md", markdown)
    _write(tmp_path, "issues/NAV-1.md", jira)

    markdown_record = _slice(tmp_path, "plan.md").record
    jira_record = _slice(tmp_path, "issues/NAV-1.md").record

    assert markdown_record.attrs == {
        "type": "project",
        "status": "active",
        "status_raw": "ACTIVE",
        "project": "Wiki",
        "source": "markdown",
    }
    assert markdown_record.concept_id == "file:plan.md"
    assert markdown_record.summary == "Wiki plan"
    assert markdown_record.body == "# plan.md\n\n## Content\n" + markdown
    assert jira_record.attrs == {
        "type": "ticket",
        "status": "in-progress",
        "status_raw": "In-Progress",
        "project": "NAV",
        "source": "markdown",
        "x_assignee": "Ada Lovelace",
        "x_assignee_id": "jira-account-1",
    }
    assert jira_record.body == "# issues/NAV-1.md\n\n## Content\n" + jira
    assert not any("email" in key.casefold() for key in jira_record.attrs)


def test_vault_aliases_and_body_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify vault key aliases preserve existing note body and edges."""
    from parrot.knowledge.wiki.vault_scan import scan_vault

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".obsidian").mkdir()
    _write(
        tmp_path,
        "daily/standup.md",
        "---\n"
        "type: meeting-source\n"
        "meeting_date: 2026-10-03T09:30:00+00:00\n"
        "primary_project: Wiki\n"
        "status: HELD\n"
        "aliases: [Morning standup]\n"
        "---\n\n"
        "# Standup\n\n"
        "See [[reference]]. #daily\n",
    )
    _write(tmp_path, "reference.md", "# Reference\n")

    scan, _ = scan_vault(tmp_path)
    records = {file_slice.rel_path: file_slice.record for file_slice in scan.files}
    record = records["daily/standup.md"]

    assert record.attrs == {
        "type": "meeting",
        "status": "held",
        "status_raw": "HELD",
        "project": "Wiki",
        "date": "2026-10-03",
        "source": "vault",
    }
    assert record.summary == "Standup"
    assert record.body == "# standup\nTags: #daily\nAliases: Morning standup\n\n# Standup\n\nSee [[reference]]. #daily"
    assert ("file:daily/standup.md", "file:reference.md", "references") in scan.import_edges


def test_no_frontmatter_build_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify absent, malformed, and non-document input leaves attrs empty."""
    monkeypatch.chdir(tmp_path)
    plain = "# Plain document\n\nBody.\n"
    malformed = "---\ntitle: [unclosed\n---\n\n# Broken metadata\n"
    source = "---\ntype: project\n---\nprint('code')\n"
    _write(tmp_path, "plain.rst", plain)
    _write(tmp_path, "malformed.md", malformed)
    _write(tmp_path, "module.py", source)

    plain_record = _slice(tmp_path, "plain.rst").record
    malformed_record = _slice(tmp_path, "malformed.md").record
    source_record = _slice(tmp_path, "module.py").record

    assert plain_record.attrs == {}
    assert plain_record.body == "# plain.rst\n\n## Content\n" + plain
    assert malformed_record.attrs == {}
    assert malformed_record.body == "# malformed.md\n\n## Content\n" + malformed
    assert source_record.attrs == {}
    assert source_record.category == "module"
