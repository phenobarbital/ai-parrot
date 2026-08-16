"""Tests for LocalVaultBackend: I/O, sandbox, skip patterns, search."""
import pytest

from parrot.interfaces.obsidian.local import LocalVaultBackend

pytestmark = pytest.mark.asyncio


@pytest.fixture
def backend(fixture_vault) -> LocalVaultBackend:
    return LocalVaultBackend(fixture_vault)


class TestListFiles:
    async def test_lists_notes_and_canvas(self, backend):
        infos = await backend.list_files()
        paths = {info.path for info in infos}
        assert "daily/2026-07-30.md" in paths
        assert "canvas/overview.canvas" in paths

    async def test_skip_patterns(self, backend):
        infos = await backend.list_files()
        assert all(not info.path.startswith(".obsidian") for info in infos)
        assert all(not info.path.startswith(".trash") for info in infos)

    async def test_suffix_filter(self, backend):
        infos = await backend.list_files(suffixes=frozenset({".canvas"}))
        assert [info.path for info in infos] == ["canvas/overview.canvas"]

    async def test_folder_scope(self, backend):
        infos = await backend.list_files(folder="daily")
        assert [info.path for info in infos] == ["daily/2026-07-30.md"]

    async def test_missing_folder_raises(self, backend):
        with pytest.raises(FileNotFoundError):
            await backend.list_files(folder="does-not-exist")


class TestReadWrite:
    async def test_read_note(self, backend):
        text = await backend.read_note("orphan.md")
        assert "lonely" in text

    async def test_read_without_suffix(self, backend):
        text = await backend.read_note("orphan")
        assert "lonely" in text

    async def test_read_missing_raises(self, backend):
        with pytest.raises(FileNotFoundError):
            await backend.read_note("missing-note")

    async def test_write_and_stat(self, backend):
        info = await backend.write_note("new/deep/note", "# New\n")
        assert info.path == "new/deep/note.md"
        stat = await backend.stat("new/deep/note.md")
        assert stat.size == len("# New\n")
        assert stat.mtime is not None

    async def test_write_no_overwrite(self, backend):
        with pytest.raises(FileExistsError):
            await backend.write_note("orphan", "clobber", overwrite=False)

    async def test_delete(self, backend):
        assert await backend.delete_note("orphan") is True
        assert await backend.note_exists("orphan") is False
        assert await backend.delete_note("orphan") is False

    async def test_non_utf8_read_raises(self, backend):
        with pytest.raises(UnicodeDecodeError):
            await backend.read_note("non-utf8.md")


class TestSandbox:
    async def test_escape_rejected(self, backend):
        with pytest.raises(ValueError):
            await backend.read_note("../outside.md")

    async def test_absolute_confined(self, backend, fixture_vault):
        # Leading slashes are stripped, so this resolves inside the vault.
        text = await backend.read_note("/orphan.md")
        assert "lonely" in text


class TestGetNoteAndIndex:
    async def test_get_note_parsed(self, backend):
        note = await backend.get_note("projects/ai-parrot")
        assert note.aliases == ["parrot", "AI Parrot"]
        assert "project" in note.tags
        assert any(link.is_embed for link in note.links)

    async def test_load_notes_skips_bad_files(self, backend):
        notes = await backend.load_notes()
        paths = {note.path.as_posix() for note in notes}
        assert "non-utf8.md" not in paths
        assert "daily/2026-07-30.md" in paths

    async def test_index_backlinks(self, backend):
        index = await backend.build_index()
        assert "daily/2026-07-30" in index.backlinks("projects/ai-parrot")

    async def test_index_cache_invalidated_on_write(self, backend):
        index_one = await backend.build_index()
        await backend.write_note("brand-new", "Links [[orphan]].")
        index_two = await backend.build_index()
        assert index_two is not index_one
        assert index_two.note("brand-new") is not None


class TestSearch:
    async def test_search_title_and_body(self, backend):
        hits = await backend.search("machine learning")
        assert hits
        assert hits[0].path == "concepts/machine-learning"

    async def test_search_by_alias(self, backend):
        hits = await backend.search("parrot")
        assert any(hit.path == "projects/ai-parrot" for hit in hits)

    async def test_empty_query(self, backend):
        assert await backend.search("   ") == []
