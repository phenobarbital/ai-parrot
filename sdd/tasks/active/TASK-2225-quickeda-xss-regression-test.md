# TASK-2225: Add XSS regression tests for QuickEdaTool HTML output

**Feature**: quickeda-html-escape-xss (FEAT-424)
**Spec**: n/a — bug fix from [GitHub Issue #1159](https://github.com/phenobarbital/ai-parrot/issues/1159)
**Status**: [ ] pending
**Priority**: critical
**Depends-on**: TASK-2224
**Assigned-to**: unassigned

## Context

TASK-2224 applies `.format(escape="html")` to the pandas Styler in
`_df_to_html_with_style()` and hardens `DfToHtmlTool` defaults. This
task adds regression tests to lock that behaviour down — mirroring the
pattern from the sibling `_altair_chart_to_html()` fix (PR #1158) and
the formdesigner XSS tests in TASK-558.

## Scope

Create a new test module
`packages/ai-parrot-tools/tests/test_quickeda_xss.py` with tests
covering:

1. **`_df_to_html_with_style` escapes `<script>` tags** — a DataFrame
   cell containing `<script>alert(1)</script>` must appear as
   `&lt;script&gt;` in the output.
2. **`_df_to_html_with_style` escapes `<img onerror>` payloads** — a
   DataFrame cell containing `<img src=x onerror=alert(1)>` must
   appear as `&lt;img` in the output.
3. **`_df_to_html_with_style` preserves legitimate data** — normal
   string/numeric values survive unchanged (no double-escaping of `&`
   that was already plain text).
4. **Column names with HTML are escaped** — a column name like
   `<b>name</b>` must be escaped in the rendered header.
5. **`DfToHtmlTool._execute()` escapes by default** — with default
   args, HTML payloads in cells are escaped.
6. **`DfToHtmlTool._execute(escape=False)` passes through** — when
   explicitly opting out, raw HTML is preserved (for pre-sanitized
   content).

## Files to Create/Modify

- `packages/ai-parrot-tools/tests/test_quickeda_xss.py` — **new**

## Implementation Notes

### Test pattern

```python
"""XSS regression tests for QuickEdaTool and DfToHtmlTool HTML output.

Prevents regression of GitHub Issue #1159:
  security(quickeda): unescaped DataFrame values in _df_to_html_with_style()
"""
import pytest
import pandas as pd
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
```

### DfToHtmlTool tests (same file or separate — implementer's choice)

```python
class TestDfToHtmlDefaultEscape:
    """Verify DfToHtmlTool defaults to escape=True after TASK-2224."""

    @pytest.mark.asyncio
    async def test_default_escapes(self):
        from parrot_tools.dftohtml import DfToHtmlTool
        tool = DfToHtmlTool()
        df = pd.DataFrame({"col": ["<script>alert(1)</script>"]})
        result = await tool._execute(dataframe=df)
        assert "<script>" not in result["html"]
        assert "&lt;script&gt;" in result["html"]

    @pytest.mark.asyncio
    async def test_escape_false_passes_through(self):
        from parrot_tools.dftohtml import DfToHtmlTool
        tool = DfToHtmlTool()
        df = pd.DataFrame({"col": ["<b>bold</b>"]})
        result = await tool._execute(dataframe=df, escape=False)
        assert "<b>bold</b>" in result["html"]
```

### Running

```bash
cd packages/ai-parrot-tools
source ../../.venv/bin/activate
pytest tests/test_quickeda_xss.py -v
```

## Reference Code

- `sdd/tasks/completed/TASK-558-fix-xss-vulnerabilities.md` — XSS test pattern
- `packages/ai-parrot-tools/tests/` — existing test conventions

## Acceptance Criteria

- [ ] `test_quickeda_xss.py` exists and imports cleanly
- [ ] All 7+ tests pass with the TASK-2224 fix applied
- [ ] Tests **fail** if `.format(escape="html")` is removed from `_df_to_html_with_style()` (verified by the implementer)
- [ ] `DfToHtmlTool` default-escape tests pass

## Output

When complete, the agent must:
1. Update this file's Status to `[x] done`
2. Update `sdd/tasks/index/quickeda-html-escape-xss.json` status to `"done"`
3. Add a brief completion note below

### Completion Note
(Agent fills this in when done)
