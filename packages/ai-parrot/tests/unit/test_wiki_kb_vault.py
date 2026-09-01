"""Unit tests for the vault access layer (FEAT-481, spec Module 4 /
TASK-2662): naming, §8.1 link-fixup, §11 init, §25 mirror.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from parrot.flows.wiki_ingest import vault
from parrot.flows.wiki_ingest.models import UNSAFE_FILENAME_CHARS
from parrot.flows.wiki_ingest.naming import (
    daily_note_filename,
    meeting_source_filename,
    sanitize_filename,
    short_source_id,
    title_case_name,
)
from parrot.tools.obsidian import ObsidianToolkit

# ---------------------------------------------------------------------------
# Naming (§8.2)
# ---------------------------------------------------------------------------


def test_sanitize_filename_strips_unsafe_punctuation() -> None:
    assert sanitize_filename('Q3: Review / Plan? "Draft"') == "Q3 Review Plan Draft"


def test_title_case_name() -> None:
    assert title_case_name("gigsmart integration") == "Gigsmart Integration"


def test_daily_note_filename() -> None:
    assert daily_note_filename(date(2026, 8, 31)) == "2026-08-31.md"


def test_short_source_id() -> None:
    assert short_source_id("fireflies:abcdef0123456789") == "abcdef01"


def test_filename_sanitization_and_meeting_tz() -> None:
    """§8.2 — the meeting filename uses the meeting's original-tz date,
    never the ingestion date, and strips unsafe punctuation from the
    title."""
    filename = meeting_source_filename(
        meeting_date_local=date(2026, 8, 30),  # e.g. meeting ran late in a UTC-X tz
        title='Q3 Sync: "Roadmap"',
        source_id="fireflies:abcdef0123456789",
    )
    assert filename == "2026-08-30 - Q3 Sync Roadmap - abcdef01.md"
    assert not UNSAFE_FILENAME_CHARS.intersection(filename)


# ---------------------------------------------------------------------------
# §8.1 link-fixup
# ---------------------------------------------------------------------------


async def test_move_note_link_fixup(tmp_path: Path) -> None:
    """After move_note(), fixup_links() rewrites both full-path and
    basename-style wikilinks in every backlinking note."""
    (tmp_path / "Wiki" / "Entities" / "People").mkdir(parents=True)
    old_path = "Wiki/Entities/People/Old Name.md"
    (tmp_path / old_path).write_text("# Old Name\n", encoding="utf-8")

    backlink_path = "note-with-backlink.md"
    (tmp_path / backlink_path).write_text(
        "See [[Wiki/Entities/People/Old Name|Old Name]] and also [[Old Name]].\n",
        encoding="utf-8",
    )

    toolkit = ObsidianToolkit(
        vault_path=str(tmp_path),
        allowed_operations={"read", "list", "search", "create", "update", "move", "delete"},
    )

    new_path = "Wiki/Entities/People/New Name.md"
    result = await toolkit.move_note(old_path, new_path)
    assert result["affected_backlinks"] == [backlink_path[: -len(".md")]]

    rewritten = await vault.fixup_links(
        toolkit,
        old_path=old_path,
        new_path=new_path,
        affected_backlinks=result["affected_backlinks"],
    )
    assert rewritten == [backlink_path[: -len(".md")]]

    new_text = await toolkit.vault.read_note(backlink_path)
    assert "[[Wiki/Entities/People/New Name|Old Name]]" in new_text
    assert "[[Wiki/Entities/People/New Name]]" in new_text
    assert "Old Name.md" not in new_text
    assert "[[Old Name]]" not in new_text


# ---------------------------------------------------------------------------
# §11 init / §25 mirror
# ---------------------------------------------------------------------------


async def test_init_idempotent(tmp_path: Path) -> None:
    """§11 — initialize_vault() creates missing control files once, and
    a second call is a no-op (never overwrites)."""
    toolkit = ObsidianToolkit(
        vault_path=str(tmp_path),
        allowed_operations={"read", "list", "search", "create", "update", "move", "delete"},
    )

    created = await vault.initialize_vault(toolkit)
    assert "Wiki/index.md" in created
    assert "Wiki/Registry/processed-sources.md" in created

    # Hand-edit one control file — a second init call must not clobber it.
    await toolkit.update_note("Wiki/index.md", "# Custom content\n", preserve_frontmatter=False)

    created_again = await vault.initialize_vault(toolkit)
    assert created_again == []

    note = await toolkit.read_note("Wiki/index.md")
    assert note["content"].strip() == "# Custom content"


async def test_registry_dir_for_vault() -> None:
    assert vault.registry_dir_for_vault("/tmp/my-vault") == Path("/tmp/my-vault/Wiki/Registry")


async def test_regenerate_mirror_matches_db(tmp_path: Path) -> None:
    """§25 — the mirror is regenerated from the registry's records."""

    class _FakeRecord:
        def __init__(self) -> None:
            self.external_id = "fireflies:abc123"
            self.meeting_date = "2026-08-31"
            self.summary_fingerprint = "sum-hash"
            self.fingerprint = "txt-hash"
            self.note_path = "Wiki/Sources/Meetings/2026-08-31 - Sync - abc12345.md"
            self.synced_at = "2026-08-31T12:00:00+00:00"

    class _FakeRegistry:
        async def all_records(self):
            return [_FakeRecord()]

    toolkit = ObsidianToolkit(
        vault_path=str(tmp_path),
        allowed_operations={"read", "list", "search", "create", "update", "move", "delete"},
    )

    body = await vault.regenerate_registry_mirror(toolkit, _FakeRegistry())
    assert "`fireflies:abc123`" in body
    assert "meeting `2026-08-31`" in body
    assert "[[Wiki/Sources/Meetings/2026-08-31 - Sync - abc12345|Source Page]]" in body

    note = await toolkit.read_note("Wiki/Registry/processed-sources.md")
    assert note["content"].strip() == body.strip()
