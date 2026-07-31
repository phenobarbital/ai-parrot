"""Tests for OutputMode.TEXT — plain-text renderer and markdown_to_plain."""
import pytest

from parrot.models.outputs import OutputMode
from parrot.outputs.formats.text import (
    PLAIN_TEXT_SYSTEM_PROMPT,
    PlainTextRenderer,
    markdown_to_plain,
)


class MockAIMessage:
    """Minimal AIMessage stand-in (same shape as test_formatter_retry's mock)."""

    def __init__(self, output: str):
        self.output = output
        self.response = None


class TestMarkdownToPlain:
    def test_bold_italic_inline_code_stripped(self):
        text = "This is **bold**, *italic*, and `code`."
        assert markdown_to_plain(text) == "This is bold, italic, and code."

    def test_headings_flattened(self):
        text = "# Title\n## Section\nBody text"
        assert markdown_to_plain(text) == "Title\nSection\nBody text"

    def test_links_become_text_url(self):
        text = "See [the docs](https://example.com/docs) for details."
        assert markdown_to_plain(text) == (
            "See the docs (https://example.com/docs) for details."
        )

    def test_fenced_code_content_kept(self):
        text = "Run:\n```bash\necho hi\n```\ndone"
        result = markdown_to_plain(text)
        assert "```" not in result
        assert "echo hi" in result

    def test_two_column_pipe_table_becomes_label_value(self):
        # The Copilot-screenshot shape: header + alignment row + data rows.
        text = (
            "| Metric | Count |\n"
            "| :--- | :--- |\n"
            "| Total FSO Daily Summary Records | 122,132 |\n"
            "| Distinct Completed FSOs | 133,883 |"
        )
        result = markdown_to_plain(text)
        assert "|" not in result
        assert "Total FSO Daily Summary Records: 122,132" in result
        assert "Distinct Completed FSOs: 133,883" in result

    def test_wide_pipe_table_pairs_headers_with_cells(self):
        text = (
            "| id | customer | total |\n"
            "| --- | --- | --- |\n"
            "| 1001 | Acme | $42 |"
        )
        result = markdown_to_plain(text)
        assert "|" not in result
        assert "id: 1001" in result
        assert "customer: Acme" in result
        assert "total: $42" in result

    def test_blockquote_and_hr_removed(self):
        text = "> quoted line\n\n---\n\nafter"
        result = markdown_to_plain(text)
        assert result == "quoted line\n\nafter"

    def test_bullet_markers_normalized(self):
        text = "* one\n+ two\n- three"
        assert markdown_to_plain(text) == "- one\n- two\n- three"

    def test_plain_text_unchanged(self):
        text = "Just a simple sentence with numbers 1, 2 and 3."
        assert markdown_to_plain(text) == text

    def test_empty_and_none_safe(self):
        assert markdown_to_plain("") == ""
        assert markdown_to_plain(None) == ""

    def test_never_raises_on_odd_input(self):
        odd = "| broken \n``` unclosed\n**dangling | :--- |"
        assert isinstance(markdown_to_plain(odd), str)


class TestPlainTextRenderer:
    def test_registered_with_system_prompt(self):
        from parrot.outputs.formats import get_output_prompt, get_renderer

        assert get_renderer(OutputMode.TEXT) is PlainTextRenderer
        prompt = get_output_prompt(OutputMode.TEXT)
        assert prompt == PLAIN_TEXT_SYSTEM_PROMPT
        assert "plain" in prompt.lower()

    @pytest.mark.asyncio
    async def test_render_strips_markdown(self):
        renderer = PlainTextRenderer()
        response = MockAIMessage("**Total**: `122,132` orders\n# Done")
        content, wrapped = await renderer.render(response)
        assert content == "Total: 122,132 orders\nDone"
        assert wrapped == content

    @pytest.mark.asyncio
    async def test_render_non_string_output(self):
        renderer = PlainTextRenderer()
        content, _ = await renderer.render(MockAIMessage({"a": 1}))
        assert isinstance(content, str)


def test_output_mode_text_enum_value():
    assert OutputMode.TEXT == OutputMode("text")
    assert OutputMode.TEXT != OutputMode.DEFAULT
