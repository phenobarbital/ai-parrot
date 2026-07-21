"""Unit tests for the markdown-to-sections parser."""
import pytest


class TestMarkdownToSections:
    def test_plain_text(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import TextSection
        result = markdown_to_sections("Hello world")
        assert len(result) == 1
        assert isinstance(result[0], TextSection)
        assert result[0].text == "Hello world"

    def test_pipe_table(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import TableSection
        md = "| Name | Age |\n| --- | --- |\n| Alice | 30 |\n| Bob | 25 |"
        result = markdown_to_sections(md)
        tables = [s for s in result if isinstance(s, TableSection)]
        assert len(tables) == 1
        assert tables[0].columns == ["Name", "Age"]
        assert len(tables[0].rows) == 2
        assert tables[0].rows[0] == ["Alice", "30"]

    def test_text_then_table_then_text(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import TableSection, TextSection
        md = "Intro text\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\nConclusion"
        result = markdown_to_sections(md)
        assert isinstance(result[0], TextSection)
        assert isinstance(result[1], TableSection)
        assert isinstance(result[2], TextSection)

    def test_fenced_code_block(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import CodeSection
        md = "Before\n```python\nprint('hi')\n```\nAfter"
        result = markdown_to_sections(md)
        codes = [s for s in result if isinstance(s, CodeSection)]
        assert len(codes) == 1
        assert codes[0].code == "print('hi')"
        assert codes[0].language == "python"

    def test_image_reference(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import ImageSection
        md = "Text\n![Chart](https://example.com/chart.png)\nMore text"
        result = markdown_to_sections(md)
        images = [s for s in result if isinstance(s, ImageSection)]
        assert len(images) == 1
        assert images[0].images[0].url == "https://example.com/chart.png"
        assert images[0].images[0].alt_text == "Chart"

    def test_empty_string(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        result = markdown_to_sections("")
        assert result == []

    def test_inline_markdown_preserved(self):
        from parrot.outputs.cards.markdown import markdown_to_sections
        from parrot.outputs.cards.sections import TextSection
        md = "This has **bold** and *italic* text"
        result = markdown_to_sections(md)
        assert len(result) == 1
        assert isinstance(result[0], TextSection)
        assert "**bold**" in result[0].text
