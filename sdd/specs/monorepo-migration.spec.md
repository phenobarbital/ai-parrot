# Feature Specification: Monorepo Workspace Migration

**Feature ID**: FEAT-057
**Date**: 2026-03-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x (next major restructure)
**Proposal**: `sdd/proposals/monorepo-migration.proposal.md`
**Brainstorm**: `sdd/proposals/monorepo-migration.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot has grown to 100+ tools/toolkits and heavy document loaders. All of this code lives in a single package, forcing every user to install everything — even if they only need the core agent framework. Splitting into multiple repositories introduces cross-repo PR friction, versioning headaches, and painful local development. We need physical package separation without multi-repo overhead.

This feature builds on FEAT-056 (runtime-dependency-reduction), which introduced lazy imports and extras groups within the single package. FEAT-057 takes the next step: physically splitting tools and loaders into independently distributable packages within a `uv`-workspace monorepo.

### Goals

1. **Three distributable packages**: `ai-parrot` (core), `ai-parrot-tools` (all tools/toolkits), `ai-parrot-loaders` (all document loaders) — each with its own `pyproject.toml` and per-tool optional extras.
2. **`uv` workspace**: Single `uv.lock`, `uv sync --all-packages` for dev, workspace-aware dependency resolution.
3. **Backward-compatible imports**: `from parrot.tools.jira import JiraToolkit` keeps working via `__getattr__` proxy modules in core.
4. **Lazy declarative discovery**: `TOOL_REGISTRY` / `LOADER_REGISTRY` dicts enable tool discovery without importing any tool code at startup.
5. **Clean core install**: `pip install ai-parrot` installs only the framework — no tool or loader dependencies.
6. **Single repo, single CI**: All development stays in one git repository.

### Non-Goals (explicitly out of scope)

- Moving external dependencies (asyncdb, querysource, flowtask, navconfig) into the monorepo — those remain separate packages.
- Changing tool/loader internal logic — only import paths and package structure change.
- Namespace packages — we use proxy modules (`__getattr__`), not PEP 420 namespace packages.
- Splitting further (e.g., `ai-parrot-clients`, `ai-parrot-memory`) — only tools and loaders for now.
- Changing the async architecture, client abstractions, or bot/agent APIs.

---

## 2. Architectural Design

### Overview

```
ai-parrot/                              # repo root
├── pyproject.toml                      # workspace root (NOT a package)
├── uv.lock
├── packages/
│   ├── ai-parrot/                      # core package
│   │   ├── pyproject.toml              # name = "ai-parrot"
│   │   └── src/
│   │       └── parrot/
│   │           ├── __init__.py
│   │           ├── _imports.py         # lazy import utility (from FEAT-056)
│   │           ├── clients/
│   │           ├── bots/
│   │           ├── memory/
│   │           ├── handlers/
│   │           ├── stores/
│   │           ├── integrations/
│   │           ├── embeddings/
│   │           ├── tools/
│   │           │   ├── __init__.py     # PROXY module (__getattr__)
│   │           │   ├── abstract.py     # AbstractTool (stays in core)
│   │           │   ├── toolkit.py      # AbstractToolkit (stays in core)
│   │           │   ├── manager.py      # ToolManager (stays in core)
│   │           │   ├── discovery.py    # Multi-source discovery (NEW)
│   │           │   ├── python_repl.py  # PythonREPLTool (stays in core)
│   │           │   ├── vectorstore_search.py  # VectorStoreSearchTool (core)
│   │           │   ├── multi_store_search.py  # MultiStoreSearchTool (core)
│   │           │   ├── openapi/        # OpenAPIToolkit (core — dynamic)
│   │           │   ├── rest.py         # RESTTool (core — generic HTTP)
│   │           │   ├── mcp_manager.py  # MCPToolManagerMixin (core — MCP)
│   │           │   ├── to_json.py      # ToJsonTool (core — utility)
│   │           │   └── agent_tool.py   # AgentTool (core — agent delegation)
│   │           └── loaders/
│   │               ├── __init__.py     # PROXY module (__getattr__)
│   │               └── abstract.py     # BaseLoader (stays in core)
│   │
│   ├── ai-parrot-tools/                # tools package
│   │   ├── pyproject.toml              # name = "ai-parrot-tools"
│   │   └── src/
│   │       └── parrot_tools/
│   │           ├── __init__.py         # TOOL_REGISTRY dict
│   │           ├── jira/
│   │           ├── slack/
│   │           ├── aws/
│   │           ├── docker/
│   │           ├── openapi/
│   │           ├── sitesearch/
│   │           └── ...                 # 100+ tools
│   │
│   └── ai-parrot-loaders/              # loaders package
│       ├── pyproject.toml              # name = "ai-parrot-loaders"
│       └── src/
│           └── parrot_loaders/
│               ├── __init__.py         # LOADER_REGISTRY dict
│               ├── youtube/
│               ├── pdf/
│               ├── audio/
│               └── ...
│
├── scripts/
│   └── generate_tool_registry.py       # registry auto-generation
├── plugins/                            # user/deploy-time plugins (existing)
├── tests/
└── sdd/
```

### Key Design Decisions

1. **`packages/` directory** (not `src/`): Avoids confusion with inner `src/` layout. Clearly signals "multiple distributable packages."

2. **Inner `src/` layout** per package: Prevents accidental imports from the working directory without installing. PEP 517/518 standard.

3. **Import proxy via `__getattr__`** (not namespace packages): Module-level `__getattr__` (PEP 562) lets us intercept `from parrot.tools.X import Y` and resolve X from `parrot_tools.X`. Cached after first access — zero overhead on subsequent imports.

4. **Declarative `TOOL_REGISTRY`** (not `pkgutil.walk_packages`): A dict mapping tool names to dotted import paths avoids importing all tool modules at discovery time. Walk is reserved for `plugins/` directory only.

5. **`parrot_tools` / `parrot_loaders`** package names (underscore, not dot): These are separate top-level packages, not sub-packages of `parrot`. The proxy in `parrot.tools` bridges the gap.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/tools/__init__.py` | replaces | Becomes `__getattr__` proxy; base classes + core tools stay |
| `parrot/tools/abstract.py` | stays in core | `AbstractTool`, `@tool` decorator |
| `parrot/tools/toolkit.py` | stays in core | `AbstractToolkit` |
| `parrot/tools/manager.py` | modifies | Add multi-source discovery |
| `parrot/tools/python_repl.py` | stays in core | `PythonREPLTool` — fundamental agent capability |
| `parrot/tools/vectorstore_search.py` | stays in core | `VectorStoreSearchTool` — core RAG primitive |
| `parrot/tools/multi_store_search.py` | stays in core | `MultiStoreSearchTool` — core RAG primitive |
| `parrot/tools/openapi/` | stays in core | `OpenAPIToolkit` — dynamic tool generation from specs |
| `parrot/tools/rest.py` | stays in core | `RESTTool` — generic HTTP tool |
| `parrot/tools/mcp_manager.py` | stays in core | `MCPToolManagerMixin` — MCP integration |
| `parrot/tools/to_json.py` | stays in core | `ToJsonTool` — utility tool |
| `parrot/tools/agent_tool.py` | stays in core | `AgentTool` — agent-to-agent delegation |
| `parrot/loaders/__init__.py` | replaces | Becomes `__getattr__` proxy; `BaseLoader` stays |
| `parrot/loaders/abstract.py` | stays in core | `BaseLoader` class |
| `parrot/tools/registry.py` | deprecates | Replace with `ToolManager` discovery |
| `pyproject.toml` | replaces | Becomes workspace root |
| `parrot/handlers/chat.py` | modifies | Loader resolution uses proxy transparently |

### Data Models

```python
# TOOL_REGISTRY format (in parrot_tools/__init__.py)
TOOL_REGISTRY: dict[str, str] = {
    "jira": "parrot_tools.jira.toolkit.JiraToolkit",
    "google_search": "parrot_tools.google.GoogleSearchTool",
    # ... auto-generated entries
}

# LOADER_REGISTRY format (in parrot_loaders/__init__.py)
LOADER_REGISTRY: dict[str, str] = {
    "youtube": "parrot_loaders.youtube.YoutubeLoader",
    "pdf": "parrot_loaders.pdf.PDFLoader",
    # ...
}
```

### New Public Interfaces

```python
# parrot/tools/discovery.py (NEW)
def discover_from_registry(sources: list[str] | None = None) -> dict[str, str]:
    """Fast discovery: read TOOL_REGISTRY dicts from installed packages."""
    ...

def discover_from_walk(sources: list[str] | None = None) -> dict[str, type]:
    """Full discovery: walk_packages for plugins/ directory."""
    ...

def discover_all(sources: list[str] | None = None) -> dict[str, str | type]:
    """Combined: fast registry + walk for plugins."""
    ...
```

---

## 3. Module Breakdown

### Module 1: Workspace Scaffolding
- **Path**: Root `pyproject.toml`, `packages/` directory structure
- **Responsibility**: Create the `uv` workspace configuration. Transform root `pyproject.toml` into workspace root (not a package). Create per-package `pyproject.toml` files with `src/` layout. Move `parrot/` to `packages/ai-parrot/src/parrot/`. Create empty `packages/ai-parrot-tools/` and `packages/ai-parrot-loaders/` structures. Verify `uv sync` works.
- **Depends on**: FEAT-056 must be merged (lazy imports in place)

### Module 2: Import Proxy — Tools
- **Path**: `packages/ai-parrot/src/parrot/tools/__init__.py`
- **Responsibility**: Replace current `__init__.py` with `__getattr__`-based proxy that resolves imports from `parrot_tools` package, then `plugins.tools`, then `TOOL_REGISTRY`. Keep re-exports of `AbstractTool`, `AbstractToolkit`, `ToolManager`.
- **Depends on**: Module 1

### Module 3: Import Proxy — Loaders
- **Path**: `packages/ai-parrot/src/parrot/loaders/__init__.py`
- **Responsibility**: Same `__getattr__` proxy pattern for loaders. Resolves from `parrot_loaders`, then `plugins.loaders`, then `LOADER_REGISTRY`. Keep re-export of `BaseLoader`.
- **Depends on**: Module 1

### Module 4: Tool Discovery System
- **Path**: `packages/ai-parrot/src/parrot/tools/discovery.py`, updates to `manager.py`
- **Responsibility**: Create multi-source discovery module with `discover_from_registry()` (fast, declarative) and `discover_from_walk()` (full, for plugins). Update `ToolManager` to use discovery. Deprecate `ToolkitRegistry` in `registry.py`.
- **Depends on**: Module 2

### Module 5: Tools Package Setup
- **Path**: `packages/ai-parrot-tools/pyproject.toml`, `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
- **Responsibility**: Create the `ai-parrot-tools` package with `pyproject.toml` (depends on `ai-parrot`, per-tool optional extras groups), empty `TOOL_REGISTRY`, and workspace source config.
- **Depends on**: Module 1

### Module 6: Tools Migration (Batch 1 — Simple Tools)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/...`
- **Responsibility**: Move a first batch of simple tools (low dependency, self-contained) from `parrot/tools/` to `parrot_tools/`. Update internal imports. Run `generate_tool_registry.py`. Verify backward-compat imports via proxy. Candidates: zipcode, wikipedia, weather, calculator, file_reader.
- **EXCLUDED from migration (stays in core)**: `PythonREPLTool`, `VectorStoreSearchTool`, `MultiStoreSearchTool`, `OpenAPIToolkit`, `RESTTool`, `MCPToolManagerMixin`, `ToJsonTool`, `AgentTool` — these are fundamental agent primitives that must work without `ai-parrot-tools`.
- **Depends on**: Module 2, Module 5

### Module 7: Tools Migration (Batch 2 — Toolkit-Based Tools)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/...`
- **Responsibility**: Move toolkit-based tools (JiraToolkit, DockerToolkit, GitToolkit, SlackToolkit, etc.) — these extend `AbstractToolkit` from core. Verify toolkit registration and discovery. Note: `OpenAPIToolkit` stays in core (it's a generic dynamic tool generator, not a service-specific toolkit).
- **Depends on**: Module 6

### Module 8: Tools Migration (Batch 3 — Complex/Heavy Tools)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/...`
- **Responsibility**: Move remaining heavy tools (DB tools, financial tools, analysis, sitesearch, flowtask wrapper, scraping, code interpreter, sandbox, etc.). These have the most external deps and cross-imports. Per-tool extras groups in `pyproject.toml`.
- **Depends on**: Module 7

### Module 9: Loaders Package Setup & Migration
- **Path**: `packages/ai-parrot-loaders/pyproject.toml`, `packages/ai-parrot-loaders/src/parrot_loaders/...`
- **Responsibility**: Create the `ai-parrot-loaders` package. Move all loaders from `parrot/loaders/` to `parrot_loaders/`. Update internal imports. Create `LOADER_REGISTRY`. Per-loader extras groups (youtube, audio, pdf, web, ebook).
- **Depends on**: Module 3

### Module 10: Registry Generation Script
- **Path**: `scripts/generate_tool_registry.py`
- **Responsibility**: Create script that scans `parrot_tools/` and `parrot_loaders/` for `AbstractTool`/`AbstractToolkit`/`BaseLoader` subclasses and generates/updates the `TOOL_REGISTRY` and `LOADER_REGISTRY` dicts. Supports `--dry-run`, `--verbose`, `--check` (CI mode).
- **Depends on**: Module 6 (needs at least some tools migrated)

### Module 11: Cleanup & CI
- **Path**: Root config, CI, old directories
- **Responsibility**: Remove empty tool/loader directories from core. Update CI to run `generate_tool_registry.py --check`. Update `.gitignore`. Verify `uv sync --all-packages` in CI. Version synchronization across packages.
- **Depends on**: All previous modules

### Module 12: Tests & Validation
- **Path**: `tests/`
- **Responsibility**: Verify backward-compatible imports work. Verify proxy resolution chain. Verify tool discovery (registry + walk). Verify `pip install ai-parrot` without tools/loaders. Verify `pip install ai-parrot ai-parrot-tools[all]` restores everything. Test error messages for missing packages.
- **Depends on**: All previous modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_proxy_resolves_installed_tool` | Module 2 | `from parrot.tools.jira import JiraToolkit` works when `ai-parrot-tools` installed |
| `test_proxy_error_missing_tool` | Module 2 | Clear `ImportError` with install instructions when tool not installed |
| `test_proxy_caches_result` | Module 2 | Second `__getattr__` call hits cache (no re-import) |
| `test_proxy_base_classes_always_available` | Module 2 | `AbstractTool`, `AbstractToolkit`, `ToolManager` importable without `ai-parrot-tools` |
| `test_core_tools_always_available` | Module 2 | Core tools (PythonREPLTool, VectorStoreSearchTool, OpenAPIToolkit, etc.) importable without `ai-parrot-tools` |
| `test_loader_proxy_resolves` | Module 3 | Same tests for loader proxy |
| `test_discover_from_registry` | Module 4 | Reads `TOOL_REGISTRY` dict from installed package |
| `test_discover_from_walk` | Module 4 | Finds tools in plugins/ via walk_packages |
| `test_discover_all_combined` | Module 4 | Registry + walk results merged correctly |
| `test_tool_manager_lazy` | Module 4 | `ToolManager(lazy=True)` doesn't trigger discovery until `.get_tool()` |
| `test_registry_generation` | Module 10 | Script finds all tool classes and generates correct dict |
| `test_registry_check_mode` | Module 10 | `--check` exits 1 when registry is stale |

### Integration Tests

| Test | Description |
|---|---|
| `test_core_import_without_tools` | `import parrot` and basic bot creation works without `ai-parrot-tools` |
| `test_backward_compat_imports` | All existing `from parrot.tools.X import Y` patterns still work |
| `test_direct_parrot_tools_import` | `from parrot_tools.jira.toolkit import JiraToolkit` works |
| `test_uv_sync_all_packages` | `uv sync --all-packages` installs everything editable |
| `test_full_test_suite` | All existing tests pass after migration |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_parrot_tools_missing(monkeypatch):
    """Simulate ai-parrot-tools not installed."""
    import sys
    monkeypatch.setitem(sys.modules, "parrot_tools", None)

@pytest.fixture
def mock_parrot_tools_installed():
    """Verify ai-parrot-tools is installed and TOOL_REGISTRY is populated."""
    from parrot_tools import TOOL_REGISTRY
    assert len(TOOL_REGISTRY) > 0
```

---

## 5. Acceptance Criteria

- [ ] Repository has `packages/` directory with 3 sub-packages, each with `src/` layout
- [ ] Root `pyproject.toml` is a workspace root with `[tool.uv.workspace] members = ["packages/*"]`
- [ ] `uv sync --all-packages` installs all 3 packages in editable mode
- [ ] `pip install ai-parrot` (core only) works without tools/loaders dependencies
- [ ] `pip install ai-parrot-tools` installs tools with core as dependency
- [ ] `pip install ai-parrot-loaders` installs loaders with core as dependency
- [ ] `from parrot.tools.jira import JiraToolkit` works (backward compat via proxy)
- [ ] `from parrot_tools.jira.toolkit import JiraToolkit` works (direct import)
- [ ] `from parrot.tools import AbstractTool, AbstractToolkit, ToolManager` works without `ai-parrot-tools`
- [ ] Core tools available without `ai-parrot-tools`: `PythonREPLTool`, `VectorStoreSearchTool`, `MultiStoreSearchTool`, `OpenAPIToolkit`, `RESTTool`, `MCPToolManagerMixin`, `ToJsonTool`, `AgentTool`
- [ ] `from parrot.loaders import BaseLoader` works without `ai-parrot-loaders`
- [ ] Missing tool/loader raises `ImportError` with clear install instructions
- [ ] `ToolManager.available_tools()` discovers tools from registry without importing them
- [ ] `scripts/generate_tool_registry.py --check` passes in CI
- [ ] All existing tests pass with all packages installed
- [ ] Version numbers synchronized across all 3 packages
- [ ] No tool or loader code remains in `packages/ai-parrot/src/parrot/tools/` except proxy, base classes, and core tools (PythonREPLTool, VectorStoreSearchTool, MultiStoreSearchTool, OpenAPIToolkit, RESTTool, MCPToolManagerMixin, ToJsonTool, AgentTool)

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

**Proxy module pattern** (for `parrot/tools/__init__.py` and `parrot/loaders/__init__.py`):

```python
import importlib
import sys

SOURCES = ["parrot_tools", "plugins.tools"]

def __getattr__(name: str):
    if name.startswith("_"):
        raise AttributeError(name)
    for source in SOURCES:
        try:
            mod = importlib.import_module(f"{source}.{name}")
            setattr(sys.modules[__name__], name, mod)  # cache
            return mod
        except ImportError:
            continue
    raise ImportError(
        f"Tool '{name}' not found. "
        f"Install with: uv pip install ai-parrot-tools[{name}]"
    )

# Base classes stay in core
from parrot.tools.abstract import AbstractTool   # noqa
from parrot.tools.toolkit import AbstractToolkit  # noqa
from parrot.tools.manager import ToolManager      # noqa
```

**Tool internal imports** (inside `parrot_tools/`):

```python
# Tools import base classes from core — this is a normal dependency
from parrot.tools.abstract import AbstractTool
from parrot.tools.toolkit import AbstractToolkit

class JiraToolkit(AbstractToolkit):
    ...
```

### Migration Order

1. Workspace scaffolding (no code moves)
2. Proxy modules + discovery (core changes)
3. Tool package setup (empty package)
4. Tools migration in 3 batches (simple → toolkit-based → complex)
5. Loaders migration (single batch — fewer loaders than tools)
6. Registry generation script
7. Cleanup + CI

### Known Risks / Gotchas

- **Circular imports**: `parrot_tools` depends on `parrot` (core) for base classes. Core's proxy resolves from `parrot_tools`. This is safe because proxy uses `importlib.import_module` (lazy), but must never have core import tool implementations at module level.
- **Cython extensions**: If any tools have `.pyx` files, the build system per-package must handle them. Check before migration.
- **Maturin/Rust**: `yaml_rs` stays in core — no impact.
- **`setup.py` / `setup.cfg`**: Must be removed or converted to per-package `pyproject.toml`. All build config moves to `pyproject.toml`.
- **Editable installs**: `uv sync` handles `src/` layout natively. `pip install -e .` from workspace root won't work — must use `uv sync --all-packages`.
- **PyPI publishing**: Each package published independently. `tool.uv.sources` ignored during publish — normal PyPI resolution kicks in.
- **Git history**: File moves show as delete+create. Use `git log --follow` for history tracking.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `uv` | `>=0.5` | Workspace support required (available since 0.4+) |
| No new Python packages | — | This is a structural refactor |

---

## 7. Open Questions

- [x] Maturin/Rust extension stays in core — *Resolved: yes*
- [x] Version synchronization across packages — *Resolved: yes, same version for all 3*
- [x] ToolkitRegistry deprecation — *Resolved: deprecate in favor of ToolManager discovery*
- [x] Shared test fixtures: root `tests/` with conditional imports, or per-package `tests/`? — *Owner: Jesus Lara*: shared test fixtures
- [x] Migration batch size: How many tools per batch? Move all simple tools at once or in smaller groups? — *Owner: Jesus Lara*: all simple tools at once
- [x] FEAT-056 dependency: Must it be fully complete, or can workspace scaffolding start in parallel with FEAT-056 tail tasks? — *Owner: Jesus Lara*: already completed.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All tasks touch the same directory structure (`packages/`, `pyproject.toml`, proxy modules). Running in parallel would cause constant merge conflicts.
- **Cross-feature dependencies**: FEAT-056 (runtime-dependency-reduction) should be merged to `dev` before starting this feature. The lazy-import utility and restructured `pyproject.toml` from FEAT-056 are prerequisites.
- **Recommended approach**: Work phase-by-phase. After workspace scaffolding, verify `uv sync` before proceeding. After each tools batch, run full test suite.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-23 | Jesus Lara | Initial draft from brainstorm + proposal |
