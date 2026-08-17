# TASK-2223: Documentation & Rules — Update for matplotlib removal

**Feature**: FEAT-423 — Purge Matplotlib & Heavy Renderer Libraries
**Spec**: `sdd/specs/purge-matplotlib-renderer-libs.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2218, TASK-2219, TASK-2220, TASK-2221, TASK-2222
**Assigned-to**: unassigned

---

## Context

All code changes are complete (TASK-2218 through TASK-2222). This final task
updates documentation and rules files to reflect the new visualization policy:
altair replaces matplotlib, and the primary path is structured-chart / A2UI.

Implements spec §Module 6.

---

## Scope

- **Update** `docs/outputs.md`: remove "Matplotlib" row from Supported Output
  Types table (line 45), remove matplotlib from install command (line 64),
  remove matplotlib usage example (lines 448–452).
- **Update** `docs/sandbox_tool.md`: remove matplotlib from pip install lists
  (lines 173, 255).
- **Update** `docs/jupyter_mode.md`: replace matplotlib example (lines 306–315)
  with altair equivalent.
- **Update** `docs/repl-worker-sandbox.md`: remove matplotlib from calibration
  references (lines 61, 126, 132, 145).
- **Update** `.agent/rules/python-development.md`: replace line 38
  ("Use matplotlib/seaborn for visualization") with A2UI/altair guidance.
- **Update** `.claude/rules/python-development.md`: same change as above.
- **Update** `.agent/skills/data-storytelling/SKILL.md`: replace matplotlib
  code example (line 243) with altair.

**NOT in scope**:
- Any code changes (all done in prior tasks)
- A2UI documentation (already up to date from FEAT-273)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/outputs.md` | MODIFY | Remove matplotlib from supported types, install, examples |
| `docs/sandbox_tool.md` | MODIFY | Remove matplotlib from pip install lists |
| `docs/jupyter_mode.md` | MODIFY | Replace matplotlib example with altair |
| `docs/repl-worker-sandbox.md` | MODIFY | Remove matplotlib calibration refs |
| `.agent/rules/python-development.md` | MODIFY | Replace viz recommendation |
| `.claude/rules/python-development.md` | MODIFY | Replace viz recommendation |
| `.agent/skills/data-storytelling/SKILL.md` | MODIFY | Replace matplotlib code example |

---

## Codebase Contract (Anti-Hallucination)

### Verified References

```markdown
# docs/outputs.md:
# Line 45: | **Matplotlib** | matplotlib | Description | ✅ Image | ✅ Native |
# Line 64: pip install folium plotly matplotlib pandas altair bokeh
# Lines 448-452: matplotlib usage example

# docs/sandbox_tool.md:
# Line 173: pip install pandas numpy matplotlib seaborn plotly scipy scikit-learn
# Line 255: pandas numpy matplotlib seaborn \

# docs/jupyter_mode.md:
# Line 306: import matplotlib.pyplot as plt
# Line 315: # If response contains matplotlib figures, they display inline

# docs/repl-worker-sandbox.md:
# Line 61: matplotlib, connection pools, and the parent's
# Line 126: pandas/numpy/matplotlib/pyarrow version bump
# Line 132: pandas/numpy/matplotlib already imported
# Line 145: pandas/numpy/matplotlib versions

# .agent/rules/python-development.md:
# Line 38: - Use matplotlib/seaborn for visualization

# .claude/rules/python-development.md:
# Line 38: - Use matplotlib/seaborn for visualization

# .agent/skills/data-storytelling/SKILL.md:
# Line 243: import matplotlib.pyplot as plt
```

### Does NOT Exist

- ~~`docs/visualization.md`~~ — no dedicated visualization docs file
- ~~`docs/altair.md`~~ — no altair-specific docs; guidance goes in existing files
- ~~`.agent/rules/visualization.md`~~ — does not exist; keep guidance in python-development.md

---

## Implementation Notes

### Replacement Patterns

**docs/outputs.md** — Supported Output Types table:
```markdown
# REMOVE this row:
| **Matplotlib** | matplotlib | Description | ✅ Image | ✅ Native |

# The table should still include:
| **Altair Chart** | altair | Description | ✅ Vega-Lite | ✅ Native |
| **Plotly Chart** | plotly | Description | ✅ Embeddable | ✅ Native |
```

**docs/outputs.md** — Install command:
```bash
# BEFORE:
pip install folium plotly matplotlib pandas altair bokeh
# AFTER:
pip install folium plotly pandas altair
```

**Rules files** — Visualization recommendation:
```markdown
# BEFORE:
- Use matplotlib/seaborn for visualization
# AFTER:
- Return data for visualization via structured-chart / A2UI; use altair for complex viz only
```

**jupyter_mode.md** — Example replacement:
```python
# BEFORE:
import matplotlib.pyplot as plt
plt.figure(figsize=(10, 6))
plt.plot(data['x'], data['y'])
plt.title('Analysis')
plt.savefig('chart.png')

# AFTER:
import altair as alt
chart = alt.Chart(df).mark_line().encode(
    x='x:Q',
    y='y:Q',
).properties(title='Analysis')
chart.save('chart.json')  # Vega-Lite JSON
```

### Key Constraints

- Do not remove references to plotly or folium — they stay.
- Do not change any A2UI documentation — it's already current.
- The repl-worker-sandbox.md calibration references should mention the reduced
  memory footprint (no matplotlib overhead).

---

## Acceptance Criteria

- [ ] `grep -rn "matplotlib" docs/outputs.md` returns zero matches (or only
  historical/changelog references)
- [ ] `grep -rn "matplotlib" docs/sandbox_tool.md` returns zero matches
- [ ] `grep -rn "matplotlib" docs/jupyter_mode.md` returns zero matches
- [ ] `grep -rn "matplotlib" docs/repl-worker-sandbox.md` returns zero matches
- [ ] `.agent/rules/python-development.md` references altair/A2UI, not matplotlib
- [ ] `.claude/rules/python-development.md` references altair/A2UI, not matplotlib
- [ ] `.agent/skills/data-storytelling/SKILL.md` uses altair, not matplotlib
- [ ] All documentation files are valid markdown

---

## Test Specification

No automated tests — this is a documentation-only task. Verification is via
grep (see Acceptance Criteria).

```bash
# Verification commands:
grep -rn "matplotlib" docs/outputs.md docs/sandbox_tool.md docs/jupyter_mode.md docs/repl-worker-sandbox.md
# Expected: zero matches (or only in historical/migration notes)

grep -n "matplotlib\|seaborn" .agent/rules/python-development.md .claude/rules/python-development.md
# Expected: zero matches
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/purge-matplotlib-renderer-libs.spec.md`
2. **Check dependencies** — ALL prior tasks (2218-2222) must be completed
3. **Read each doc file** before modifying — verify line numbers are still accurate
4. **Update status** in `sdd/tasks/index/purge-matplotlib-renderer-libs.json` → `"in-progress"`
5. **Implement** — update one file at a time
6. **Verify** all acceptance criteria via grep
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-16
**Notes**: All 7 files updated as scoped. Found and fixed one un-itemized
issue while editing `docs/outputs.md`'s architecture ASCII diagram: removing
"Matplotlib" from the Renderer Registry box left a pre-existing duplicated
"HTML Widget" line exposed (the diagram had listed it twice) — fixed for a
clean, non-redundant diagram (same file already in scope).

Resolved one direct conflict between the task's own instructions: the
literal AC for `docs/repl-worker-sandbox.md` demands zero `matplotlib`
grep matches, while the Key Constraint explicitly directs "should mention
the reduced memory footprint (no matplotlib overhead)". Resolved by keeping
the reduced-footprint notes (satisfying the Key Constraint's intent) while
rephrasing to avoid the literal word "matplotlib" (satisfying the strict
AC) — e.g. "predates FEAT-423's reduction of the REPL bootstrap import
surface" instead of naming the library. Verified: zero matches.

Verified the two altair code examples (jupyter_mode.md's inline
visualization snippet, SKILL.md's Annotation-and-Highlight technique) are
not just plausible-looking but actually EXECUTE and produce valid Vega-Lite
specs — ran both against real/synthetic data with the installed altair
5.5.0.

All 7 files: zero `matplotlib`/`seaborn` matches (verified via grep, per
AC), balanced ``` code fences (valid markdown, verified via fence-count
parity check). Confirmed 2 remaining repo-wide matplotlib mentions
(`docs/migration/feat-223-*.md`, `docs/migration/feat-273-*.md`) are
historical migration docs from OTHER features, correctly out of this
task's scope — left untouched.

**Deviations from spec**: See Notes above (ASCII diagram fix,
repl-worker-sandbox.md AC/Key-Constraint conflict resolution) — both
minor, same-file, no functional/code impact (documentation-only task).
