# TASK-2219: System Prompt Rewrite — Direct LLM to structured-chart / A2UI

**Feature**: FEAT-423 — Purge Matplotlib & Heavy Renderer Libraries
**Spec**: `sdd/specs/purge-matplotlib-renderer-libs.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2218
**Assigned-to**: unassigned

---

## Context

With matplotlib/seaborn removed from PythonREPLTool's namespace (TASK-2218), the
system prompts must be rewritten to guide the LLM toward the correct visualization
path: return structured data and let the frontend render it via A2UI /
structured-chart, or use altair for complex edge cases.

Implements spec §Module 2.

---

## Scope

- **Rewrite** `REACT_PROMPT_PREFIX` in `data.py`:
  - Replace line 25 ("You can create visualizations using matplotlib, seaborn or
    altair") with A2UI-directed guidance.
  - Replace line 28 (library listing) — remove matplotlib, matplotlib-inline,
    seaborn from available libraries.
  - Replace line 116 ("use seaborn or altair for charts and matplotlib for plots
    as embedded images") — remove matplotlib/seaborn references.
- **Rewrite** `TOOL_CALLING_PROMPT_PREFIX` in `data.py`:
  - Replace line 201 (Available Libraries) — remove matplotlib and seaborn.
  - Add a `## Visualization Policy` section.
- **Update** `DataBot._build_system_prompt()` in `bots/data.py`:
  - Replace capabilities text at line 870 ("Create visualizations (matplotlib,
    seaborn, plotly)") with structured output guidance.

**NOT in scope**:
- PythonREPLTool code changes (TASK-2218)
- ChartTool migration (TASK-2221)
- Documentation updates (TASK-2223)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/data.py` | MODIFY | Rewrite all 3 prompt templates |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | Update capabilities text |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/bots/prompts/data.py — no imports, pure string constants
# REACT_PROMPT_PREFIX starts at line 1
# TOOL_CALLING_PROMPT_PREFIX starts at line 162
# TOOL_CALLING_PROMPT_SUFFIX starts at line 214
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/prompts/data.py

# Lines to modify in REACT_PROMPT_PREFIX:
# Line 25: "- You can create visualizations using matplotlib, seaborn or altair through the Python tool."
# Line 28: "- You have access to several python libraries installed as scipy, numpy, matplotlib, matplotlib-inline, seaborn, altair, plotly, ..."
# Line 116: "    - use seaborn or altair for charts and matplotlib for plots as embedded images"

# Lines to modify in TOOL_CALLING_PROMPT_PREFIX:
# Line 201: "You can use: pandas, numpy, matplotlib, seaborn, plotly, scipy, ..."

# packages/ai-parrot/src/parrot/bots/data.py
# Line 870: "- Create visualizations (matplotlib, seaborn, plotly)"
# This is inside DataBot._build_system_prompt() capabilities default text
```

### Does NOT Exist

- ~~`parrot.bots.prompts.visualization`~~ — no separate visualization prompt module
- ~~`DataBot.visualization_prompt`~~ — not a real attribute
- ~~`VISUALIZATION_POLICY_PROMPT`~~ — does not exist yet; create inline in the templates

---

## Implementation Notes

### New Visualization Policy Text

Insert this section in both `REACT_PROMPT_PREFIX` and `TOOL_CALLING_PROMPT_PREFIX`:

```
## Visualization Policy
- DO NOT use matplotlib or seaborn — they are not available in this environment.
- For standard charts (bar, line, pie, scatter, histogram): return the data as a
  Python dict, e.g. {"chart_type": "bar", "title": "Revenue", "data": {"categories": [...], "values": [...]}}.
  The system renders charts automatically.
- For complex visualizations only (heatmaps, correlation matrices, network
  graphs): use altair. Return the chart's .to_dict() output.
- For geographic maps: use folium (if available).
- NEVER attempt to import matplotlib, seaborn, or bokeh — these are blocked
  and will raise an error.
```

### Library Listing Replacement

Replace matplotlib/seaborn in available library lists with:
```
pandas, numpy, altair, plotly, scipy, statsmodels, scikit-learn, pmdarima,
prophet, geopandas, sentence-transformers, nltk, spacy, and others if needed.
```

### Key Constraints

- Keep all non-visualization prompt content unchanged (DataFrame handling,
  EDA instructions, PDF generation, etc.)
- The PDF generation section currently says "use seaborn or altair for charts
  and matplotlib for plots" — update to "use altair for charts" only.
- Preserve `$variable` template substitutions exactly as-is.

---

## Acceptance Criteria

- [ ] Zero mentions of `matplotlib` or `seaborn` as available libraries in any prompt
- [ ] Both prompt templates include a `## Visualization Policy` section
- [ ] Capabilities text in `bots/data.py` references structured output, not matplotlib
- [ ] All `$variable` template substitutions preserved correctly
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/prompts/data.py`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/data.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_data_prompts_no_matplotlib.py
from parrot.bots.prompts.data import (
    REACT_PROMPT_PREFIX,
    TOOL_CALLING_PROMPT_PREFIX,
)


def test_no_matplotlib_in_react_prompt():
    """REACT prompt must not mention matplotlib as available."""
    assert "matplotlib" not in REACT_PROMPT_PREFIX.lower() or \
           "do not use matplotlib" in REACT_PROMPT_PREFIX.lower()


def test_no_seaborn_in_react_prompt():
    """REACT prompt must not mention seaborn as available."""
    assert "seaborn" not in REACT_PROMPT_PREFIX.lower() or \
           "do not use seaborn" in REACT_PROMPT_PREFIX.lower()


def test_visualization_policy_in_react():
    """REACT prompt must include visualization policy section."""
    assert "Visualization Policy" in REACT_PROMPT_PREFIX


def test_no_matplotlib_in_tool_calling_prompt():
    """Tool-calling prompt must not list matplotlib as available."""
    assert "matplotlib" not in TOOL_CALLING_PROMPT_PREFIX.lower() or \
           "do not use matplotlib" in TOOL_CALLING_PROMPT_PREFIX.lower()


def test_visualization_policy_in_tool_calling():
    """Tool-calling prompt must include visualization policy section."""
    assert "Visualization Policy" in TOOL_CALLING_PROMPT_PREFIX


def test_altair_mentioned():
    """Both prompts should mention altair as the viz fallback."""
    assert "altair" in REACT_PROMPT_PREFIX.lower()
    assert "altair" in TOOL_CALLING_PROMPT_PREFIX.lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/purge-matplotlib-renderer-libs.spec.md`
2. **Check dependencies** — TASK-2218 must be completed first
3. **Verify the Codebase Contract** — confirm line numbers in `data.py` and `bots/data.py`
4. **Update status** in `sdd/tasks/index/purge-matplotlib-renderer-libs.json` → `"in-progress"`
5. **Implement** — modify the three string constants, preserving all `$variable` placeholders
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-16
**Notes**: Rewrote all 3 areas as scoped. Also found and fixed the module
appears to be currently unwired into the live `DataBot` prompt-building path
(`DataBot` uses `PromptBuilder`/`domain_layers`, not these legacy string
constants) — confirmed via a repo-wide grep that `REACT_PROMPT_PREFIX`/
`TOOL_CALLING_PROMPT_PREFIX` are not imported anywhere else. Updated them
anyway per the task/spec's explicit instruction and because the task's own
Test Specification imports and asserts on them directly. Also fixed one
additional stale reference not itemized in the task's line list but in the
same file/scope: a `plt.savefig()` example under `TOOL_CALLING_PROMPT_PREFIX`'s
"PYTHON CODE GUIDELINES" section (Saving Files bullet).

Verified all `$variable` template placeholders preserved in both prompts.
`ruff check` on the two modified source files: pre-existing debt only (177
errors, all present before this task's edits per line-number correlation
with `dev`); the new test file is clean. New test suite
(`tests/bots/test_data_prompts_no_matplotlib.py`): 7/7 pass.

Found and confirmed PRE-EXISTING (unrelated) test failures in
`tests/unit/bots/test_pandasagent_stale_data_variables.py` (3 tests,
`AttributeError: 'types.SimpleNamespace' object has no attribute
'_assignment_target_names'`) — reproduced identically via `git stash` back
to the TASK-2218 commit, confirming they are not a regression from this
task or TASK-2218. Left untouched (out of scope).

**Deviations from spec**: Fixed the un-itemized `plt.savefig()` reference
noted above (same file already in scope, not a new file/class).
