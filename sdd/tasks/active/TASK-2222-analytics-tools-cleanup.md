# TASK-2222: Analytics Tools — Replace matplotlib with altair

**Feature**: FEAT-423 — Purge Matplotlib & Heavy Renderer Libraries
**Spec**: `sdd/specs/purge-matplotlib-renderer-libs.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2221
**Assigned-to**: unassigned

---

## Context

Several analytics tools in `ai-parrot-tools` hard-import matplotlib for chart
generation. These must be migrated to altair. The sandboxtool also lists
matplotlib in its default packages — this must be removed.

Implements spec §Module 5.

---

## Scope

- **Rewrite** `quickeda.py`: replace `import matplotlib` / `import matplotlib.pyplot
  as plt` with altair. Rewrite figure generation to produce Vega-Lite specs or
  static images via `vl-convert-python`.
- **Rewrite** `correlationanalysis.py`: replace matplotlib heatmap rendering with
  altair's `mark_rect()` + color encoding.
- **Rewrite** `seasonaldetection.py`: replace matplotlib time-series plots with
  altair `mark_line()`.
- **Update** `sandboxtool.py`: remove `"matplotlib"` from `DEFAULT_PACKAGES` list
  (line 35) and from init code templates (lines 250–252, 595, 635, 656).

**NOT in scope**:
- PythonREPLTool changes (TASK-2218)
- ChartTool backend migration (TASK-2221)
- Documentation updates (TASK-2223)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/quickeda.py` | MODIFY | matplotlib → altair |
| `packages/ai-parrot-tools/src/parrot_tools/correlationanalysis.py` | MODIFY | matplotlib → altair |
| `packages/ai-parrot-tools/src/parrot_tools/seasonaldetection.py` | MODIFY | matplotlib → altair |
| `packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py` | MODIFY | Remove matplotlib from defaults |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot-tools/src/parrot_tools/quickeda.py (lines 10-11):
import matplotlib                     # REPLACE with: import altair as alt
import matplotlib.pyplot as plt       # DELETE
# Line 19: matplotlib.use('Agg')      # DELETE

# packages/ai-parrot-tools/src/parrot_tools/correlationanalysis.py (lines 10-11):
import matplotlib                     # REPLACE with: import altair as alt
import matplotlib.pyplot as plt       # DELETE
# Line 19: matplotlib.use('Agg')      # DELETE

# packages/ai-parrot-tools/src/parrot_tools/seasonaldetection.py (line 9):
import matplotlib.pyplot as plt       # REPLACE with: import altair as alt

# packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py (line 35):
# "pandas", "numpy", "matplotlib", "seaborn", "scikit-learn",  # REMOVE matplotlib, seaborn
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/quickeda.py:
# Has a method that converts matplotlib figure to base64 (line 255):
# """Convert matplotlib figure to base64 encoded string."""  # REWRITE for altair

# packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py:
# DEFAULT_PACKAGES list (line 35):
# "pandas", "numpy", "matplotlib", "seaborn", "scikit-learn",
# → CHANGE TO: "pandas", "numpy", "altair", "scikit-learn",

# Init code templates (lines 250-252):
# import matplotlib
# matplotlib.use('Agg')  # Non-interactive backend
# import matplotlib.pyplot as plt
# → DELETE these lines from the template strings

# More init code templates (line 595):
# "pandas", "numpy", "matplotlib", "seaborn",
# → REMOVE matplotlib, seaborn

# Template code blocks (lines 635, 656):
# import matplotlib.pyplot as plt
# → DELETE or replace with altair
```

### Does NOT Exist

- ~~`quickeda.AltairEDAReport`~~ — does not exist; must adapt existing class
- ~~`correlationanalysis.AltairCorrelation`~~ — does not exist
- ~~`sandboxtool.ALTAIR_PACKAGES`~~ — does not exist; modify existing list

---

## Implementation Notes

### altair Equivalents for matplotlib Patterns

| matplotlib pattern | altair equivalent |
|---|---|
| `plt.figure()` / `plt.subplots()` | `alt.Chart(df)` |
| `plt.bar(x, y)` | `chart.mark_bar().encode(x=..., y=...)` |
| `plt.plot(x, y)` | `chart.mark_line().encode(x=..., y=...)` |
| `plt.scatter(x, y)` | `chart.mark_circle().encode(x=..., y=...)` |
| `plt.imshow(matrix)` (heatmap) | `chart.mark_rect().encode(x=..., y=..., color=...)` |
| `plt.hist(values)` | `chart.mark_bar().encode(alt.X(..., bin=True), y='count()')` |
| `plt.savefig(path)` | `chart.save(path)` |
| `fig.to_base64()` | `chart.to_dict()` → JSON (or `chart.save()` → PNG if vl-convert available) |
| `sns.heatmap(corr)` | `alt.Chart(corr_long).mark_rect().encode(...)` |
| `sns.set_palette(p)` | `alt.Scale(range=[...])` |

### Correlation Matrix (altair)

The correlation heatmap in `correlationanalysis.py` currently uses
`sns.heatmap()`. The altair equivalent requires melting the correlation
matrix into long format:

```python
import altair as alt
import pandas as pd

corr = df.corr()
# Melt to long format: var1, var2, correlation
corr_long = corr.reset_index().melt(id_vars="index")
corr_long.columns = ["var1", "var2", "correlation"]

chart = alt.Chart(corr_long).mark_rect().encode(
    x="var1:N",
    y="var2:N",
    color=alt.Color("correlation:Q", scale=alt.Scale(scheme="redblue", domain=[-1, 1])),
    tooltip=["var1", "var2", "correlation"],
).properties(title="Correlation Matrix")
```

### Key Constraints

- Each tool must continue to return a file path (for inline image delivery
  via messaging integrations) OR a dict/JSON spec (for frontend rendering).
- The `sandboxtool.py` init code templates are f-strings embedded in the
  source — edit carefully to preserve string escaping.
- `seaborn` must be removed alongside `matplotlib` from sandboxtool defaults.

---

## Acceptance Criteria

- [ ] `quickeda.py` does not import matplotlib or seaborn
- [ ] `correlationanalysis.py` does not import matplotlib or seaborn
- [ ] `seasonaldetection.py` does not import matplotlib
- [ ] `sandboxtool.py` does not list matplotlib or seaborn in DEFAULT_PACKAGES
- [ ] `sandboxtool.py` init code templates do not import matplotlib
- [ ] All replacement charts produce valid output (file path or Vega-Lite JSON)
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/`
- [ ] `grep -rn "import matplotlib" packages/ai-parrot-tools/src/` returns zero matches

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_analytics_no_matplotlib.py
import ast
from pathlib import Path

TOOLS_SRC = Path("packages/ai-parrot-tools/src/parrot_tools")


def _imports_matplotlib(filepath: Path) -> bool:
    """Check if a Python file imports matplotlib."""
    tree = ast.parse(filepath.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("matplotlib"):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("matplotlib"):
                return True
    return False


def test_quickeda_no_matplotlib():
    assert not _imports_matplotlib(TOOLS_SRC / "quickeda.py")


def test_correlationanalysis_no_matplotlib():
    assert not _imports_matplotlib(TOOLS_SRC / "correlationanalysis.py")


def test_seasonaldetection_no_matplotlib():
    assert not _imports_matplotlib(TOOLS_SRC / "seasonaldetection.py")


def test_sandboxtool_no_matplotlib_default():
    content = (TOOLS_SRC / "sandboxtool.py").read_text()
    # Check DEFAULT_PACKAGES does not contain matplotlib
    assert '"matplotlib"' not in content.split("DEFAULT_PACKAGES")[1].split("]")[0]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/purge-matplotlib-renderer-libs.spec.md`
2. **Check dependencies** — TASK-2221 must be completed first (altair backend pattern)
3. **Read each tool file fully** before modifying — understand the chart generation flow
4. **Update status** in `sdd/tasks/index/purge-matplotlib-renderer-libs.json` → `"in-progress"`
5. **Implement** — migrate one tool at a time, verify each before moving to the next
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
