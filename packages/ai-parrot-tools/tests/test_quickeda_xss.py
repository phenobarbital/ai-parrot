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
        assert "<script>bad</script>" not in html
        assert "&lt;script&gt;bad&lt;/script&gt;" in html

    def test_row_index_label_escaped(self, tool):
        """Row index labels are attacker-controlled too (e.g. value_counts()
        results, transposed describe()) — `.format()` alone does not cover
        them, only `.format_index(axis=0)` does."""
        df = pd.DataFrame(
            {"Count": [1]},
            index=pd.Index(["<script>alert(1)</script>"]),
        )
        html = tool._df_to_html_with_style(df)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_index_name_escaped(self, tool):
        """`df.index.name` is rendered as a separate `index_name` header
        cell that neither `.format()` nor `.format_index()` touches — it
        must be escaped independently. This is exactly the shape produced
        by `value_counts().to_frame()`, which inherits the source column's
        (attacker-controlled) name as the index name."""
        df = pd.DataFrame({"Count": [1]})
        df.index.name = "<script>alert(1)</script>"
        html = tool._df_to_html_with_style(df)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_columns_name_escaped(self, tool):
        """`df.columns.name` has the same gap as `df.index.name`."""
        df = pd.DataFrame({"col": [1]})
        df.columns.name = "<script>alert(1)</script>"
        html = tool._df_to_html_with_style(df)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    @pytest.mark.asyncio
    async def test_execute_categorical_section_value_counts_escaped(self, tool):
        """End-to-end regression: a malicious column name AND a malicious
        categorical value must both come out escaped in the full report,
        via the real `_generate_categorical_section` -> `value_counts()`
        -> `_df_to_html_with_style()` path (not just the private helper in
        isolation)."""
        malicious_col = "<script>alert(1)</script>"
        malicious_val = "<img src=x onerror=alert(2)>"
        df = pd.DataFrame({malicious_col: [malicious_val, malicious_val, "safe"]})
        result = await tool._execute(dataframe=df)
        html = result["html"]
        assert malicious_col not in html
        assert malicious_val not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&lt;img src=x onerror=alert(2)&gt;" in html


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
    async def test_column_header_escaped_by_default(self):
        """Column names are just as attacker-controlled as cell values
        (e.g. CSV headers) — the default `escape=True` must cover them."""
        tool = DfToHtmlTool()
        df = pd.DataFrame({"<script>alert(1)</script>": ["safe"]})
        result = await tool._execute(dataframe=df)
        assert "<script>alert(1)</script>" not in result["html"]
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result["html"]

    @pytest.mark.asyncio
    async def test_escape_false_passes_through(self):
        tool = DfToHtmlTool()
        df = pd.DataFrame({"col": ["<b>bold</b>"]})
        result = await tool._execute(dataframe=df, escape=False)
        assert "<b>bold</b>" in result["html"]

    @pytest.mark.asyncio
    async def test_escape_false_column_header_passes_through(self):
        tool = DfToHtmlTool()
        df = pd.DataFrame({"<b>bold</b>": ["safe"]})
        result = await tool._execute(dataframe=df, escape=False)
        assert "<b>bold</b>" in result["html"]
