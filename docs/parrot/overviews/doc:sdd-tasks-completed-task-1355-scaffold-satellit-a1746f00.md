---
type: Wiki Overview
title: 'TASK-1355: Scaffold ai-parrot-visualizations satellite package'
id: doc:sdd-tasks-completed-task-1355-scaffold-satellite-package-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: '[build-system]'
relates_to:
- concept: mod:parrot.embeddings.version
  rel: mentions
- concept: mod:parrot.outputs.formats.assets
  rel: mentions
- concept: mod:parrot.outputs.formats.version
  rel: mentions
---

# TASK-1355: Scaffold ai-parrot-visualizations satellite package

**Feature**: FEAT-200 — Extract outputs/formats to ai-parrot-visualizations
**Spec**: `sdd/proposals/ai-parrot-visualizations.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Foundation task for FEAT-200. Creates the satellite package directory
> structure, pyproject.toml, and version module — mirroring the proven
> `ai-parrot-embeddings` pattern for PEP 420 implicit namespace packages.
> All subsequent tasks depend on this scaffold existing.

---

## Scope

- Create `packages/ai-parrot-visualizations/` directory tree
- Create `pyproject.toml` with granular extras per renderer group
- Create `src/parrot/outputs/formats/version.py` for dynamic version discovery
- Place `.gitkeep` files at namespace boundaries (NO `__init__.py` at `parrot/`, `parrot/outputs/`, `parrot/outputs/formats/`)
- Create `README.md` (minimal)
- Verify the package is recognized by uv as a workspace member (root `pyproject.toml` has `members = ["packages/*"]` at line 44-45)

**NOT in scope**: Moving any renderer files (TASK-1357, TASK-1358), modifying core `__init__.py` files (TASK-1356), or updating core dependencies (TASK-1360).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/pyproject.toml` | CREATE | Package metadata, deps, granular extras |
| `packages/ai-parrot-visualizations/README.md` | CREATE | Minimal readme |
| `packages/ai-parrot-visualizations/src/parrot/.gitkeep` | CREATE | Namespace boundary marker |
| `packages/ai-parrot-visualizations/src/parrot/outputs/.gitkeep` | CREATE | Namespace boundary marker |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/.gitkeep` | CREATE | Namespace boundary marker |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/version.py` | CREATE | `__version__` for dynamic discovery |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/.gitkeep` | CREATE | Placeholder for echarts.min.js |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/generators/.gitkeep` | CREATE | Placeholder for generators subpackage |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/mixins/.gitkeep` | CREATE | Placeholder for mixins subpackage |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Not applicable — this task creates new files only
```

### Existing Signatures to Use
```python
# packages/ai-parrot-embeddings/pyproject.toml (reference pattern)
# Line 1-2: [build-system] requires = ["setuptools>=67.6.1", "wheel>=0.44.0"]
# Line 28-30: dependencies = ["ai-parrot"]
# Line 92-93: [tool.setuptools.dynamic] version = {attr = "parrot.embeddings.version.__version__"}
# Line 95-98: [tool.setuptools.packages.find] where=["src"], include=["parrot*"], namespaces=true
# Line 100-101: [tool.uv.sources] ai-parrot = { workspace = true }
```

### Does NOT Exist
- ~~`packages/ai-parrot-visualizations/`~~ — does not exist yet; this task creates it
- ~~`parrot.outputs.formats.version`~~ — does not exist yet; this task creates it
- ~~`__init__.py` at namespace boundaries~~ — must NOT be created (PEP 420)

---

## Implementation Notes

### Pattern to Follow
```toml
# Mirror ai-parrot-embeddings/pyproject.toml structure exactly:
[build-system]
requires = ["setuptools>=67.6.1", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-visualizations"
dynamic = ["version"]
description = "Visualization renderers for AI-Parrot outputs"
requires-python = ">=3.11"
license = "MIT"
dependencies = ["ai-parrot"]

[project.optional-dependencies]
matplotlib = ["matplotlib>=3.7"]
seaborn = ["seaborn>=0.13", "matplotlib>=3.7"]
plotly = ["plotly>=5.0"]
altair = ["altair>=5.0"]
bokeh = ["bokeh>=3.0", "pandas-bokeh>=0.5"]
holoviews = ["holoviews>=1.18"]
echarts = []
d3 = []
map = ["folium>=0.14"]
infographic = ["cairosvg", "svglib", "reportlab"]
jinja2 = ["jinja2>=3.0"]
streamlit = ["streamlit>=1.30"]
panel = ["panel>=1.0"]
messaging = []
charts = ["ai-parrot-visualizations[matplotlib,seaborn,plotly,altair,bokeh,holoviews,echarts,d3]"]
all = ["ai-parrot-visualizations[charts,map,infographic,jinja2,streamlit,panel,messaging]"]

[tool.setuptools.dynamic]
version = {attr = "parrot.outputs.formats.version.__version__"}

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true

[tool.setuptools.package-data]
"parrot.outputs.formats.assets" = ["*.js"]

[tool.uv.sources]
ai-parrot = { workspace = true }
```

### Key Constraints
- No `__init__.py` at `parrot/`, `parrot/outputs/`, or `parrot/outputs/formats/` — only `.gitkeep`
- `generators/` and `mixins/` are regular sub-packages (WILL have `__init__.py` once files are moved in TASK-1358)
- The `version.py` module pattern: `__version__ = "0.1.0"`

### References in Codebase
- `packages/ai-parrot-embeddings/` — the reference satellite package to mirror
- `packages/ai-parrot-embeddings/src/parrot/embeddings/version.py` — version module pattern

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-visualizations/pyproject.toml` exists with all granular extras
- [ ] `.gitkeep` files present at all three namespace levels (no `__init__.py`)
- [ ] `version.py` exists at `src/parrot/outputs/formats/version.py`
- [ ] `uv pip install -e packages/ai-parrot-visualizations` succeeds (after activating venv)
- [ ] No linting errors in any created files
- [ ] Directory structure mirrors `ai-parrot-embeddings` pattern

---

## Test Specification

```bash
# Verify package is installable
source .venv/bin/activate
uv pip install -e packages/ai-parrot-visualizations

# Verify version is discoverable
python -c "from parrot.outputs.formats.version import __version__; print(__version__)"

# Verify no __init__.py at namespace levels
test ! -f packages/ai-parrot-visualizations/src/parrot/__init__.py
test ! -f packages/ai-parrot-visualizations/src/parrot/outputs/__init__.py
test ! -f packages/ai-parrot-visualizations/src/parrot/outputs/formats/__init__.py
```

---

## Agent Instructions

When you pick up this task:

1. **Read the proposal** at `sdd/proposals/ai-parrot-visualizations.proposal.md`
2. **Study the reference** at `packages/ai-parrot-embeddings/` for the exact PEP 420 structure
3. **Create all directories and files** per the scope above
4. **Test installation** with `uv pip install -e packages/ai-parrot-visualizations`
5. **Commit** with message: `sdd: scaffold ai-parrot-visualizations satellite (TASK-1355)`

---

## Completion Note

Implemented by sdd-worker on 2026-05-28.

Created `packages/ai-parrot-visualizations/` with:
- `pyproject.toml` with all granular extras (matplotlib, seaborn, plotly, altair, bokeh,
  holoviews, echarts, d3, map, infographic, jinja2, streamlit, panel, messaging, charts, all)
- `README.md` with installation and usage docs
- `.gitkeep` files at all three PEP 420 namespace levels (no `__init__.py`)
- `src/parrot/outputs/formats/version.py` with `__version__ = "0.1.0"`
- Placeholder `.gitkeep` in `assets/`, `generators/`, `mixins/` directories

Package installs successfully: `uv pip install -e packages/ai-parrot-visualizations` ✅
Version module will be discoverable after TASK-1356 adds `extend_path()` to core.
