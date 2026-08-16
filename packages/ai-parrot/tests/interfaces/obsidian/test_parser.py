"""Unit tests for ObsidianNoteParser and parse_canvas (FEAT-392 Module 1)."""
import json

import pytest

from parrot.interfaces.obsidian.parser import ObsidianNoteParser, parse_canvas


@pytest.fixture(scope="module")
def parser() -> ObsidianNoteParser:
    return ObsidianNoteParser()


class TestParseWikilink:
    def test_basic(self, parser):
        note = parser.parse("See [[target]].", "a.md")
        assert len(note.links) == 1
        link = note.links[0]
        assert link.target == "target"
        assert link.alias is None
        assert link.heading is None
        assert link.is_embed is False

    def test_alias(self, parser):
        note = parser.parse("See [[target|display text]].", "a.md")
        assert note.links[0].target == "target"
        assert note.links[0].alias == "display text"

    def test_heading(self, parser):
        note = parser.parse("See [[target#Some Heading]].", "a.md")
        assert note.links[0].target == "target"
        assert note.links[0].heading == "Some Heading"

    def test_heading_and_alias(self, parser):
        note = parser.parse("See [[target#head|shown]].", "a.md")
        link = note.links[0]
        assert (link.target, link.heading, link.alias) == ("target", "head", "shown")

    def test_path_qualified(self, parser):
        note = parser.parse("See [[folder/note]].", "a.md")
        assert note.links[0].target == "folder/note"

    def test_multiple_links(self, parser):
        note = parser.parse("[[one]] then [[two|2]] and ![[three]]", "a.md")
        assert [link.target for link in note.links] == ["one", "two", "three"]


class TestParseEmbed:
    def test_note_embed(self, parser):
        note = parser.parse("Body ![[note]] end.", "a.md")
        assert note.links[0].is_embed is True
        assert note.links[0].target == "note"

    def test_image_embed(self, parser):
        note = parser.parse("![[image.png]]", "a.md")
        assert note.links[0].is_embed is True
        assert note.links[0].target == "image.png"

    def test_embed_with_heading(self, parser):
        note = parser.parse("![[note#section]]", "a.md")
        assert note.links[0].is_embed is True
        assert note.links[0].heading == "section"


class TestParseFrontmatter:
    def test_frontmatter_extracted(self, parser):
        raw = "---\ntitle: My Note\ntags: [a, b]\naliases: [x]\n---\nBody.\n"
        note = parser.parse(raw, "a.md")
        assert note.title == "My Note"
        assert note.frontmatter["title"] == "My Note"
        assert note.tags == {"a", "b"}
        assert note.aliases == ["x"]
        assert note.content.strip() == "Body."

    def test_tags_as_string(self, parser):
        raw = "---\ntags: one, two\n---\nBody\n"
        note = parser.parse(raw, "a.md")
        assert note.tags == {"one", "two"}

    def test_invalid_yaml_treated_as_body(self, parser):
        raw = "---\n: bad: [unclosed\n---\nBody text.\n"
        note = parser.parse(raw, "a.md")
        assert note.frontmatter == {}
        assert "Body text." in note.content

    def test_title_falls_back_to_stem(self, parser):
        note = parser.parse("No frontmatter here.", "folder/some-note.md")
        assert note.title == "some-note"


class TestParseTags:
    def test_inline_tag(self, parser):
        note = parser.parse("Hello #tag world", "a.md")
        assert "tag" in note.tags

    def test_nested_tag(self, parser):
        note = parser.parse("Hello #nested/tag world", "a.md")
        assert "nested/tag" in note.tags

    def test_heading_is_not_tag(self, parser):
        note = parser.parse("# Heading\n\nBody #real one", "a.md")
        assert note.tags == {"real"}

    def test_code_block_tags_ignored(self, parser):
        raw = "```python\n# not-a-tag\nx = '#alsonot'\n```\n\n#yes\n"
        note = parser.parse(raw, "a.md")
        assert note.tags == {"yes"}

    def test_pure_number_not_tag(self, parser):
        note = parser.parse("Issue #123 but #v2 counts", "a.md")
        assert "123" not in note.tags
        assert "v2" in note.tags


class TestParseCallouts:
    def test_callout_preserved(self, parser):
        raw = "> [!note] Title\n> Callout body.\n"
        note = parser.parse(raw, "a.md")
        assert "[!note] Title" in note.content
        assert "Callout body." in note.content


class TestParseDataview:
    def test_dataview_block_captured(self, parser):
        raw = "Before\n\n```dataview\nLIST FROM #tag\n```\n\nAfter\n"
        note = parser.parse(raw, "a.md")
        assert note.dataview_queries == ["LIST FROM #tag"]

    def test_dataview_not_tag_source(self, parser):
        raw = "```dataview\nLIST FROM #hidden\n```\n"
        note = parser.parse(raw, "a.md")
        assert "hidden" not in note.tags

    def test_dataviewjs_captured(self, parser):
        raw = "```dataviewjs\ndv.list()\n```\n"
        note = parser.parse(raw, "a.md")
        assert note.dataview_queries == ["dv.list()"]


class TestParseCanvas:
    def test_parse_canvas(self):
        payload = {
            "nodes": [
                {"id": "a", "type": "file", "file": "x.md"},
                {"id": "b", "type": "text", "text": "hello"},
            ],
            "edges": [{"fromNode": "a", "toNode": "b"}],
        }
        canvas = parse_canvas(json.dumps(payload), "canvas/overview.canvas")
        assert canvas.title == "overview"
        assert len(canvas.cards) == 2
        assert canvas.cards[0].file_path == "x.md"
        assert canvas.connections == [("a", "b")]

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            parse_canvas("{not json", "c.canvas")
