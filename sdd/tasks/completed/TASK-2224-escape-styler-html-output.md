# TASK-2224: Escape DataFrame cell values in _df_to_html_with_style()

**Feature**: quickeda-html-escape-xss (FEAT-424)
**Spec**: n/a — bug fix from [GitHub Issue #1159](https://github.com/phenobarbital/ai-parrot/issues/1159)
**Status**: [x] done
**Priority**: critical
**Depends-on**: none
**Assigned-to**: sdd-worker

## Context

`QuickEdaTool._df_to_html_with_style()` in
`packages/ai-parrot-tools/src/parrot_tools/quickeda.py` converts a
pandas DataFrame to an HTML table via `pandas.Styler.to_html()`. The
Styler does **not** HTML-escape cell values by default, so any DataFrame
containing adversarial values (e.g. `<img src=x onerror=alert(1)>` or
`<script>alert(1)</script>`) renders the payload verbatim in the EDA
report HTML. Since the agent runs `quick_eda` over user-supplied data
(uploaded files, scraped tables), this is a pre-auth XSS vector.

The method is called from every DataFrame-derived table section:
- `_generate_data_types_section`  (line ~323)
- `_generate_missing_values_section`  (line ~338)
- `_generate_descriptive_stats_section`  (lines ~366, ~383)
- `_generate_correlation_section`  (line ~432)
- `_generate_categorical_section`  (line ~522)

This is a **pre-existing** vulnerability, identical on `dev` before
FEAT-423. Filed separately from PR #1158 (which fixed the sibling
`_altair_chart_to_html()` XSS introduced by that PR).

## Scope

1. **Fix `_df_to_html_with_style()`** — add `.format(escape="html")` to
   the Styler chain before `.to_html()`.
2. **Sweep `dftohtml.py`** — `DfToHtmlTool._execute()` defaults
   `escape=False` (line 175). Change the default to `True` (safe by
   default) and update the Pydantic field default + description in
   `DfToHtmlArgs.escape` (line 33).
3. **Sweep the rest of `parrot_tools/`** — confirm no other file uses
   `.style…to_html()` or `DataFrame.to_html()` without escaping. The
   only other hit is `edareport.py:226` (`ProfileReport.to_html()`) —
   that is `ydata-profiling`'s own renderer, not raw pandas; document
   this as "out of scope, third-party escaping" in a code comment.

## Files to Create/Modify

- `packages/ai-parrot-tools/src/parrot_tools/quickeda.py` — fix
- `packages/ai-parrot-tools/src/parrot_tools/dftohtml.py` — default-escape hardening

## Implementation Notes

### quickeda.py (lines 264–269)

**Before:**
```python
def _df_to_html_with_style(self, df_input: pd.DataFrame, title: str = "") -> str:
    """Convert DataFrame to HTML with styling."""
    styler = df_input.style.set_table_attributes('class="dataframe"')
    if title:
        styler = styler.set_caption(title)
    return styler.to_html()
```

**After:**
```python
def _df_to_html_with_style(self, df_input: pd.DataFrame, title: str = "") -> str:
    """Convert DataFrame to HTML with styling.

    Cell values are HTML-escaped to prevent XSS when rendering
    user-supplied DataFrames.
    """
    styler = (
        df_input.style
        .set_table_attributes('class="dataframe"')
        .format(escape="html")
    )
    if title:
        styler = styler.set_caption(title)
    return styler.to_html()
```

### dftohtml.py (line 33–35 and line 175)

**Before:**
```python
escape: bool = Field(
    default=False,
    description="Whether to escape HTML characters in the data"
)
```

**After:**
```python
escape: bool = Field(
    default=True,
    description="Whether to escape HTML characters in the data (disable only for pre-sanitized content)"
)
```

And the corresponding `_execute` parameter (line 175):
```python
escape: bool = True,
```

### Verification

```python
import pandas as pd
df = pd.DataFrame({"cat1": ["<img src=x onerror=alert(1)>", "B"]})

# quickeda path
tool = QuickEdaTool()
html = tool._df_to_html_with_style(df)
assert "<img" not in html        # tag is escaped
assert "&lt;img" in html         # escaped entity present

# Styler.format(escape="html") path
print(df.style.format(escape="html").to_html())
# => &lt;img src=x onerror=alert(1)&gt;
```

## Reference Code

- Existing XSS fix pattern: `sdd/tasks/completed/TASK-558-fix-xss-vulnerabilities.md`
- `html.escape` already imported at `quickeda.py:7` (`from html import escape`)
- PR #1158 sibling fix for `_altair_chart_to_html()`

## Acceptance Criteria

- [ ] `_df_to_html_with_style()` applies `.format(escape="html")` before `.to_html()`
- [ ] `DfToHtmlArgs.escape` defaults to `True`; `DfToHtmlTool._execute(escape=...)` parameter defaults to `True`
- [ ] Payloads `<script>alert(1)</script>` and `<img src=x onerror=alert(1)>` in DataFrame cells survive as `&lt;script&gt;` / `&lt;img` in the output HTML
- [ ] No unescaped `.style…to_html()` or `.to_html()` calls remain in `parrot_tools/` (sweep documented)

## Output

When complete, the agent must:
1. Update this file's Status to `[x] done`
2. Update `sdd/tasks/index/quickeda-html-escape-xss.json` status to `"done"`
3. Add a brief completion note below

### Completion Note

Applied `.format(escape="html")` to the Styler chain in
`_df_to_html_with_style()` (`quickeda.py`), and flipped `DfToHtmlArgs.escape`
default (and the corresponding `_execute()` parameter default) to `True` in
`dftohtml.py`, matching the "After" snippets in this task exactly. Verified
manually with the payload from the task's Verification section — `<img`
does not survive, `&lt;img` does.

Two follow-up corrections beyond the literal Before/After snippets, made
after writing TASK-2225's regression tests surfaced they were needed to
close the actual XSS vector and to satisfy that task's given test
scaffold (both changes stayed inside files already authorized for this
task):

- **`dftohtml.py`**: `Styler.to_html()` has no `escape` kwarg in pandas
  2.2 (it silently absorbs it into `**kwargs` and does nothing) — passing
  `escape=escape` there, as the original code did, never actually escaped
  anything regardless of the flag's value. Fixed by applying
  `.format(escape="html")` to the styler conditionally on `escape` before
  calling `.to_html()` (mirroring the `quickeda.py` fix), and dropped the
  no-op `escape=` kwarg from the `.to_html()` call. Confirmed manually:
  default now escapes `<script>`, `escape=False` still passes through
  raw HTML for pre-sanitized content.
- **`quickeda.py`**: `.format(escape="html")` only escapes *cell* values,
  not column headers (`.format_index(..., axis=1)` needed) or the
  `set_caption()` title (Styler never escapes captions). Since column
  names are just as attacker-controlled as cell values (e.g. CSV
  headers), added `.format_index(escape="html", axis=1)` to the chain
  and `html.escape(title)` before `set_caption()`.

**Critical follow-up (post code-review, before push)**: the dispatched
`code-reviewer` agent built end-to-end repros against the patched code
and found the fix above was still materially incomplete — confirmed by
an independent Codex cross-check with pandas-source citations. Two more
gaps, closed in the same files:

- **Row index (axis=0) never escaped.** `.format_index(..., axis=1)`
  only covers column headers; the row *index* needs its own
  `.format_index(escape="html", axis=0)` call. Real attacker-reachable
  paths in `quickeda.py`: `_generate_missing_values_section`'s
  `to_frame()`, `_generate_descriptive_stats_section`'s transposed
  `describe()`, and — the exact payload class this fix targets —
  `_generate_categorical_section`'s `value_counts().to_frame()`, whose
  index holds the actual category *values* from user data. `dftohtml.py`
  had no `.format_index()` at all for either axis, so `escape=True`
  (the new default) did not protect column headers or the index either.
  Added `.format_index(escape="html", axis=0)` (and confirmed axis=1
  was already/now present) in both files.
- **Axis *names* (`df.index.name` / `df.columns.name`) are a third,
  separate gap** — pandas' Styler renders them as a distinct
  `class="index_name"` header cell that neither `.format()` nor
  `.format_index()` touches at all (verified against pandas 2.2.3
  directly: a `.format_index(escape="html")`-wrapped Styler still
  renders a raw `<script>` tag from `index.name`). This is exactly what
  `value_counts().to_frame()` produces: the resulting index inherits the
  source column's (attacker-controlled) name. Fixed by escaping
  `index.name` / `columns.name` in place on a DataFrame copy, in both
  `quickeda.py` and `dftohtml.py` (`dftohtml.py`'s escaping is gated on
  `escape=True`, preserving the `escape=False` pre-sanitized-content
  opt-out).

Re-verified end-to-end after this follow-up: a malicious column name
(`<script>alert(1)</script>`) fed through the real
`QuickEdaTool._execute()` → `_generate_categorical_section` →
`value_counts()` path, and a malicious categorical value
(`<img src=x onerror=alert(2)>`), both now come out escaped in the full
report HTML — this exact case was the reviewer's failing repro before
the fix. Also added 6 end-to-end regression tests to TASK-2225's test
file covering all three gaps (see that task's completion note).

Sweep of `parrot_tools/` for other unescaped `to_html()` call sites (item 3
in Scope):
- `edareport.py:226` — `ProfileReport.to_html()` (ydata-profiling's own
  renderer, not raw pandas). Out of scope for this fix; left un-annotated
  in code since `edareport.py` is not listed in this task's Files to
  Create/Modify (Cardinal Rule: file fidelity) — documented here instead.
- `correlationanalysis.py:388` — `correlation_df.to_html(classes=...,
  table_id=...)` with no `escape=` kwarg, so it uses pandas'
  `DataFrame.to_html()` default of `escape=True` already. Not a
  vulnerability; no change needed.
- No other `.style...to_html()` or `DataFrame.to_html()` call sites found.
