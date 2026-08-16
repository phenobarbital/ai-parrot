"""XSS regression tests for QuickEdaTool and DfToHtmlTool HTML output.

Prevents regression of GitHub Issue #1159:
  security(quickeda): unescaped DataFrame values in _df_to_html_with_style()
"""
import pandas as pd
import pytest
from parrot_tools.dftohtml import DfToHtmlTool
from parrot_tools.quickeda import QuickEdaTool

# ── XSS payloads ──────────────────────────────────────────────

PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '"><svg/onload=alert(1)>',
    "</td><td><script>alert(1)</script>",
]

ESCAPED_MARKERS = [
    "&lt;script&gt;",
    "&lt;img",
    "&lt;svg",
    "&lt;/td&gt;",
]


@pytest.fixture
def tool():
    return QuickEdaTool()


@pytest.fixture
def xss_df():
    return pd.DataFrame({"category": PAYLOADS, "value": range(len(PAYLOADS))})


class TestDfToHtmlEscaping:
    """Verify _df_to_html_with_style() HTML-escapes cell values."""

    def test_script_tag_escaped(self, tool):
        df = pd.DataFrame({"col": ["<script>alert(1)</script>"]})
        html = tool._df_to_html_with_style(df)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_img_onerror_escaped(self, tool):
        df = pd.DataFrame({"col": ["<img src=x onerror=alert(1)>"]})
        html = tool._df_to_html_with_style(df)
        assert "<img " not in html
        assert "&lt;img" in html

    def test_all_payloads_escaped(self, tool, xss_df):
        html = tool._df_to_html_with_style(xss_df)
        for payload, marker in zip(PAYLOADS, ESCAPED_MARKERS):
            assert payload not in html, f"Raw payload found: {payload}"
            assert marker in html, f"Escaped marker missing: {marker}"

    def test_legitimate_data_preserved(self, tool):
        df = pd.DataFrame({"name": ["Alice", "Bob"], "score": [95, 87]})
        html = tool._df_to_html_with_style(df)
        assert "Alice" in html
        assert "Bob" in html

    def test_column_name_with_html_escaped(self, tool):
        df = pd.DataFrame({"<b>name</b>": ["Alice"]})
        html = tool._df_to_html_with_style(df)
        assert "<b>name</b>" not in html
        assert "&lt;b&gt;" in html

    def test_title_does_not_inject(self, tool):
        df = pd.DataFrame({"col": ["safe"]})
        html = tool._df_to_html_with_style(df, title="<script>bad</script>")
        # set_caption may or may not escape; verify no raw <script> tag
        assert "<script>bad</script>" not in html


class TestDfToHtmlDefaultEscape:
    """Verify DfToHtmlTool defaults to escape=True after TASK-2224."""

    @pytest.mark.asyncio
    async def test_default_escapes(self):
        tool = DfToHtmlTool()
        df = pd.DataFrame({"col": ["<script>alert(1)</script>"]})
        result = await tool._execute(dataframe=df)
        assert "<script>" not in result["html"]
        assert "&lt;script&gt;" in result["html"]

    @pytest.mark.asyncio
    async def test_escape_false_passes_through(self):
        tool = DfToHtmlTool()
        df = pd.DataFrame({"col": ["<b>bold</b>"]})
        result = await tool._execute(dataframe=df, escape=False)
        assert "<b>bold</b>" in result["html"]
