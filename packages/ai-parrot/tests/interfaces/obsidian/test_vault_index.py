"""Unit tests for VaultIndex resolution, backlinks, orphans (FEAT-392)."""
from parrot.interfaces.obsidian.index import VaultIndex
from parrot.interfaces.obsidian.parser import ObsidianNoteParser


def _build_index() -> VaultIndex:
    parser = ObsidianNoteParser()
    notes = [
        parser.parse(
            "---\naliases: [ML, ml-notes]\n---\nBody #ml", "concepts/machine-learning.md"
        ),
        parser.parse("Links to [[machine-learning]] and [[ML]].", "daily/today.md"),
        parser.parse("Path link [[concepts/machine-learning]].", "projects/proj.md"),
        parser.parse("Broken [[nowhere-to-be-found]].", "broken.md"),
        parser.parse("Nothing here.", "orphan.md"),
        parser.parse("Root duplicate.", "notes.md"),
        parser.parse("Deep duplicate.", "deep/nested/notes.md"),
        parser.parse("Ambiguous [[notes]] link.", "ambig.md"),
    ]
    return VaultIndex.build(notes)


class TestResolve:
    def test_resolve_by_name(self):
        index = _build_index()
        assert index.resolve("machine-learning") == "concepts/machine-learning"

    def test_resolve_by_path(self):
        index = _build_index()
        assert (
            index.resolve("concepts/machine-learning")
            == "concepts/machine-learning"
        )

    def test_resolve_by_alias(self):
        index = _build_index()
        assert index.resolve("ML") == "concepts/machine-learning"
        assert index.resolve("ml-notes") == "concepts/machine-learning"

    def test_resolve_with_md_suffix(self):
        index = _build_index()
        assert index.resolve("machine-learning.md") == "concepts/machine-learning"

    def test_shortest_path_wins_on_duplicates(self):
        index = _build_index()
        assert index.resolve("notes") == "notes"

    def test_unresolvable_returns_none(self):
        index = _build_index()
        assert index.resolve("nowhere-to-be-found") is None
        assert index.resolve("") is None


class TestBacklinks:
    def test_backlinks(self):
        index = _build_index()
        backlinks = index.backlinks("concepts/machine-learning")
        assert backlinks == ["daily/today", "projects/proj"]

    def test_outlinks(self):
        index = _build_index()
        targets = [link.target for link in index.outlinks("daily/today")]
        assert targets == ["machine-learning", "ML"]

    def test_unresolved_recorded(self):
        index = _build_index()
        assert ("broken", "nowhere-to-be-found") in index.unresolved()


class TestTagsAndOrphans:
    def test_notes_by_tag(self):
        index = _build_index()
        assert index.notes_by_tag("ml") == ["concepts/machine-learning"]
        assert index.notes_by_tag("#ml") == ["concepts/machine-learning"]

    def test_nested_tag_prefix_match(self):
        parser = ObsidianNoteParser()
        index = VaultIndex.build(
            [parser.parse("Tagged #project/status here.", "a.md")]
        )
        assert index.notes_by_tag("project") == ["a"]
        assert index.notes_by_tag("project/status") == ["a"]

    def test_orphans(self):
        index = _build_index()
        assert "orphan" in index.orphans()
        assert "daily/today" not in index.orphans()

    def test_tag_counts(self):
        index = _build_index()
        assert index.tags().get("ml") == 1
