---
type: Wiki Overview
title: 'TASK-1360: Refactor core pyproject.toml dependencies'
id: doc:sdd-tasks-completed-task-1360-refactor-core-dependencies-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: '[project.optional-dependencies]'
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
---

# TASK-1360: Refactor core pyproject.toml dependencies

**Feature**: FEAT-200 — Extract outputs/formats to ai-parrot-visualizations
**Spec**: `sdd/proposals/ai-parrot-visualizations.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1357, TASK-1358
**Assigned-to**: unassigned

---

## Context

> With renderers moved to the satellite, the heavy visualization
> dependencies must be removed from the core package and restructured
> as granular extras pointing to the satellite. This is the highest-impact
> change for downstream users: `pip install ai-parrot` will no longer
> pull in matplotlib, seaborn, or any chart library.

---

## Scope

- Remove `matplotlib==3.10.0` (line 93) and `seaborn==0.13.2` (line 94) from BASE dependencies
- Remove visualization deps from `[agents]` extra (plotly, altair, bokeh, holoviews, folium, streamlit, pandas-bokeh)
- Remove viz deps from `[images]` extra
- Remove viz deps from `[charts]` extra (or redirect to satellite)
- Add new `[visualizations]` meta-extra: `ai-parrot-visualizations[charts]`
- Update `[all]` meta-extra to include `visualizations`
- Verify `uv pip install -e packages/ai-parrot` still works without viz deps
- Update any extras that referenced cairosvg/svglib/reportlab (infographic deps)

**NOT in scope**: Modifying the satellite's pyproject.toml (done in TASK-1355), changing code imports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Remove viz deps, add visualizations extra |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Not applicable — this task modifies pyproject.toml only
```

### Existing Signatures to Use
```toml
# packages/ai-parrot/pyproject.toml — current state:

# Line 93-94 (BASE deps — REMOVE):
# "matplotlib==3.10.0",
# "seaborn==0.13.2",

# Line 192-246 ([agents] extra — REMOVE viz deps):
# "streamlit==1.54.0",     # line 215
# "folium==0.20.0",        # line 223

# Line 248-253 ([charts] extra — REDIRECT to satellite):
# "matplotlib>=3.7",       # line 249
# "cairosvg",              # line 250
# "svglib",                # line 251
# "reportlab",             # line 252

# Line 323-345 ([images] extra — REMOVE viz deps):
# "holoviews==1.21.0",     # line 339
# "bokeh==3.8.2",          # line 340
# "pandas-bokeh==0.5.5",   # line 341
# "plotly==5.22.0",        # line 342
# "altair==5.5.0",         # line 344

# Reference: ai-parrot-embeddings pattern in root pyproject.toml
# Root pyproject.toml line 44-45: members = ["packages/*"]
# Satellite is auto-discovered as workspace member
```

### Does NOT Exist
- ~~`[visualizations]` extra in core~~ — does not exist yet; this task creates it
- ~~`ai-parrot-visualizations` in current dependencies~~ — not referenced yet

---

## Implementation Notes

### Key Constraints
- **Do NOT remove deps that are used by non-viz code**: e.g., if `folium` is used by something outside of `formats/`, it should stay in its relevant extra (but MOVE it out of `[agents]` into a dedicated extra or the satellite)
- **The `[agents]` extra will shrink significantly** — it currently bundles viz with scraping/finance. Only keep non-viz deps.
- **Check `[agents-lite]`, `[mcp]` extras** for folium references (lines 280, 314)
- **Version pinning**: the satellite uses relaxed versions (`>=3.7`); the core used pinned versions (`==3.10.0`). Verify the satellite's `pyproject.toml` pins are acceptable.

### Pattern to Follow
```toml
# New extra in core pyproject.toml:
[project.optional-dependencies]
visualizations = [
    "ai-parrot-visualizations[all]",
]

# Updated [all] extra:
all = [
    "ai-parrot[agents,images,mcp,visualizations]",  # add visualizations
]

# Updated [charts] extra (redirect):
charts = [
    "ai-parrot-visualizations[charts,infographic]",
]
```

### References in Codebase
- `packages/ai-parrot-embeddings/pyproject.toml` — reference for satellite dependency declaration
- `packages/ai-parrot/pyproject.toml` lines 90-100, 192-250, 248-253, 323-345

---

## Acceptance Criteria

- [ ] `matplotlib` and `seaborn` NOT in BASE dependencies
- [ ] `plotly`, `altair`, `bokeh`, `holoviews`, `streamlit`, `folium`, `pandas-bokeh` NOT in `[agents]` extra
- [ ] New `[visualizations]` extra exists pointing to `ai-parrot-visualizations`
- [ ] `[charts]` extra redirects to satellite
- [ ] `[all]` meta-extra includes `visualizations`
- [ ] `uv pip install -e packages/ai-parrot` succeeds without pulling matplotlib/seaborn
- [ ] `uv pip install -e "packages/ai-parrot[visualizations]"` pulls the satellite and its deps
- [ ] `python -c "import parrot"` works without matplotlib installed
- [ ] No toml syntax errors

---

## Test Specification

```bash
# Verify core installs without viz deps
source .venv/bin/activate
uv pip install -e packages/ai-parrot
python -c "import parrot; print('Core imports OK')"

# Verify matplotlib is NOT installed (should fail or not be in pip list)
python -c "import matplotlib" && echo "FAIL: matplotlib should not be installed" || echo "OK: matplotlib not in base"

# Verify visualizations extra works
uv pip install -e "packages/ai-parrot[visualizations]"
python -c "from parrot.outputs.formats import get_renderer; from parrot.models.outputs import OutputMode; print(get_renderer(OutputMode.MATPLOTLIB))"
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-1357 and TASK-1358 are complete** (renderers in satellite)
2. **Read** `packages/ai-parrot/pyproject.toml` in full — note all extras containing viz deps
3. **Carefully remove** viz deps from each extra, preserving non-viz deps
4. **Add** the `[visualizations]` meta-extra
5. **Test** installation with and without the extra
6. **Commit** with message: `sdd: refactor core deps, add visualizations meta-extra (TASK-1360)`

---

## Completion Note

Implemented by sdd-worker on 2026-05-28.

Changes to `packages/ai-parrot/pyproject.toml`:
- Removed `matplotlib==3.10.0` and `seaborn==0.13.2` from BASE dependencies ✅
- Removed from `[agents]`: streamlit, folium (duplicate), cairosvg ✅
- Removed from `[agents-lite]`: folium ✅
- Removed from `[mcp]`: folium ✅
- Removed from `[images]`: holoviews, bokeh, pandas-bokeh, plotly, altair ✅
- Redirected `[charts]` extra to `ai-parrot-visualizations[charts,infographic]` ✅
- Added `[visualizations]` meta-extra: `ai-parrot-visualizations[all]` ✅
- Updated `[all]` meta-extra to include `visualizations` ✅

Also modified root `pyproject.toml`:
- Added `ai-parrot-visualizations = { workspace = true }` to `[tool.uv.sources]`
  (required for uv workspace dependency resolution)

Installation verified:
- `uv pip install -e packages/ai-parrot` succeeds without viz deps ✅
- `uv pip install -e "packages/ai-parrot[visualizations]"` pulls satellite ✅
- `import parrot` works without matplotlib installed ✅
