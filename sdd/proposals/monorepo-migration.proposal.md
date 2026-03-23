# Feature Proposal: Monorepo Workspace Migration

**Date**: 2026-03-23
**Author**: Jesus Lara
**Status**: accepted
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Brainstorm**: `sdd/proposals/monorepo-migration.brainstorm.md`

---

## Why

AI-Parrot has grown to 100+ tools/toolkits and heavy loaders (PDF, audio, video, OCR). A regular user who only needs the core agent framework is forced to install everything. Splitting into separate repos introduces friction (cross-repo PRs, versioning headaches, local dev requires `uv sources` hacks). We need modularization without multi-repo pain.

This complements FEAT-056 (runtime-dependency-reduction) — where FEAT-056 makes heavy deps lazy/optional within a single package, this feature physically separates tools and loaders into independently installable packages while keeping everything in one repo for developer convenience.

**Why now**: The dependency problem is acute (users can't install ai-parrot without system libraries like libmysqlclient-dev), and `uv` workspaces are now stable enough to support this pattern cleanly.

---

## What Changes

### From the user's perspective

**Install experience changes** — users choose what they need:
```bash
# Before: pip install ai-parrot  (installs everything, slow, fragile)
# After:
uv pip install ai-parrot                          # core only (fast, clean)
uv pip install ai-parrot ai-parrot-tools[jira]     # core + jira tool
uv pip install ai-parrot ai-parrot-loaders[audio]  # core + audio loader
uv pip install ai-parrot ai-parrot-tools[all] ai-parrot-loaders[all]  # everything
```

**Import experience does NOT change** — backward-compatible proxy modules:
```python
# All existing imports keep working:
from parrot.tools.jira import JiraToolkit     # still works (proxy resolves)
from parrot.loaders.youtube import YoutubeLoader  # still works

# New direct imports also available:
from parrot_tools.jira.toolkit import JiraToolkit
from parrot_loaders.youtube import YoutubeLoader
```

**Error experience improves** — clear messages when a tool/loader isn't installed:
```python
>>> from parrot.tools.jira import JiraToolkit
ImportError: Tool 'jira' not found. Install with: uv pip install ai-parrot-tools[jira]
```

### From the developer's perspective

- Repository structure changes: `packages/` directory with 3 sub-packages
- `uv sync --all-packages` installs everything in editable mode for local dev
- Single monorepo, single PR, single CI pipeline
- Tools depend on `ai-parrot` (core) — never the reverse

---

## Capabilities

### New Capabilities

- `workspace-setup`: Root `pyproject.toml` with `[tool.uv.workspace]`, `packages/` directory structure, per-package `pyproject.toml` with `src/` layout
- `import-proxy`: `__getattr__`-based proxy modules in `parrot/tools/__init__.py` and `parrot/loaders/__init__.py` that resolve imports from `parrot_tools` / `parrot_loaders` packages transparently
- `tool-discovery`: Multi-source `ToolManager` discovery via `TOOL_REGISTRY` dicts (fast, declarative) + `pkgutil.walk_packages` (full, for plugins)
- `registry-generation`: `scripts/generate_tool_registry.py` to auto-generate `TOOL_REGISTRY` from package scan, with `--check` mode for CI
- `tools-migration`: Physical move of all tool/toolkit code from `parrot/tools/` to `packages/ai-parrot-tools/src/parrot_tools/`
- `loaders-migration`: Physical move of all loader code from `parrot/loaders/` to `packages/ai-parrot-loaders/src/parrot_loaders/`

### Modified Capabilities

- `parrot/tools/__init__.py`: Changes from direct exports to `__getattr__` proxy. Base classes (`AbstractTool`, `AbstractToolkit`, `ToolManager`) stay in core.
- `parrot/loaders/__init__.py`: Same proxy pattern. `BaseLoader` stays in core.
- `parrot/tools/registry.py` (ToolkitRegistry): Deprecated in favor of `ToolManager` + `discover_from_registry()`
- `pyproject.toml`: Transforms from single-package config to workspace root (not a package itself)

---

## Impact

### End users
- **No breaking changes** to import paths (proxy modules ensure backward compat)
- **Better install experience** — smaller, faster, no system library requirements for core
- Users must install `ai-parrot-tools` / `ai-parrot-loaders` separately if they need tools/loaders

### APIs
- No API changes — tools/loaders expose the same classes and methods
- New `parrot_tools.*` and `parrot_loaders.*` import paths available (optional)

### Dependencies
- Core package (`ai-parrot`) has drastically fewer dependencies
- Tool-specific deps move to `ai-parrot-tools[<extra>]` optional groups
- Loader-specific deps move to `ai-parrot-loaders[<extra>]` optional groups

### Development workflow
- `uv sync --all-packages` replaces `uv pip install -e .`
- Tests run from workspace root: `uv run pytest tests/`
- CI needs `--check` step for tool registry staleness

### Relationship to FEAT-056
- FEAT-056 (lazy imports) should land FIRST — it makes the lazy-import utility (`parrot/_imports.py`) that tools/loaders will continue to use after migration
- The monorepo migration builds on top of the cleaned-up dependency structure

---

## Open Questions

1. **Maturin/Rust extension** (`parrot/yaml_rs`): stays in core? **Recommendation**: yes, it's a core YAML performance optimization.

2. **Shared test fixtures**: Separate test directories per package, or shared root `tests/` with conditional imports? **Recommendation**: keep root `tests/` with `conftest.py` that conditionally imports packages.

3. **Version synchronization**: Should all 3 packages share the same version number? **Recommendation**: yes, simplest approach. A script can enforce this.

4. **ToolkitRegistry deprecation**: The existing `parrot/tools/registry.py` has hardcoded imports. Deprecate in favor of `ToolManager` discovery? **Recommendation**: yes.

5. **Ordering with FEAT-056**: Must FEAT-056 (runtime-dependency-reduction) be fully complete before starting this? **Recommendation**: yes — the lazy import infrastructure and pyproject.toml restructuring from FEAT-056 are prerequisites.

6. **Migration granularity**: Move all tools at once or incrementally (tool-by-tool)? The brainstorm suggests incremental. What batch size is practical?

---

## Parallelism Potential

- **workspace-setup** and **import-proxy** are sequential prerequisites
- **tools-migration** and **loaders-migration** can run in parallel (different files)
- **registry-generation** depends on tools-migration completing
- **Cross-feature dependency**: FEAT-056 (runtime-dependency-reduction) should be merged to `dev` first
