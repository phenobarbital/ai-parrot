# Feature Specification: Runtime Dependency Reduction

**Feature ID**: FEAT-056
**Date**: 2026-03-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot has ~57 hard runtime dependencies in `pyproject.toml [project.dependencies]`, many of which are heavy, domain-specific packages that most users will never need. Installing `ai-parrot` as a library triggers installation of:

- **flowtask** (which pulls `asyncdb[all]` -> mysql driver -> `libmysqlclient-dev` system package)
- **torch** ecosystem (via sentence-transformers transitive deps)
- **pydub** (audio processing, needs ffmpeg)
- **markitdown** (document conversion)
- **pytesseract** (OCR, needs tesseract system package)
- **weasyprint** (PDF export, needs cairo/pango system libraries)
- **querysource** (DB query builder)
- **pandas-datareader**, **ta-lib** (financial analysis, ta-lib needs C library)
- **faiss-cpu** (vector search)
- **google-cloud-bigquery** (GCP-specific)
- **matplotlib**, **seaborn** (visualization)
- **python-arango-async** (ArangoDB-specific)
- **psycopg-binary** (PostgreSQL-specific)

This makes `pip install ai-parrot` extremely slow, fragile (system library requirements), and bloated for users who only need the core agent/chatbot framework.

### Goals

1. **Minimal core install**: `pip install ai-parrot` installs only the framework essentials (aiohttp, pydantic, LLM client deps, core bot/agent abstractions) — no ML, no DB drivers, no system library requirements.
2. **Extras-based opt-in**: Heavy dependencies move to optional extras groups (`ai-parrot[db]`, `ai-parrot[pdf]`, `ai-parrot[ocr]`, `ai-parrot[finance]`, `ai-parrot[audio]`, etc.).
3. **Lazy imports with clear errors**: All modules that use optional dependencies must import them lazily (at function/method call time) and raise a clear `ImportError` message telling the user which extra to install.
4. **Standardized lazy-import pattern**: Consolidate the 4-5 different lazy import patterns currently scattered across the codebase into one canonical utility.
5. **No breaking changes to public API**: All existing functionality remains available — users just need to install the right extras.
6. **flowtask isolation**: `flowtask` must NOT be a hard dependency. It should be an optional extra (`ai-parrot[flowtask]` or `ai-parrot[tasks]`), and its `asyncdb[all]` must be scoped down.
7. **Scheduler isolation**: `APScheduler` must NOT be a hard dependency. It should be an optional extra (`ai-parrot[scheduler]`).

### Non-Goals (explicitly out of scope)

- Removing any functionality — everything stays, just behind optional extras.
- Rewriting tools/toolkits — only import paths change, not logic.
- Changing the async architecture or client abstractions.
- Vendor-specific client removal (OpenAI, Anthropic SDKs stay as-is).
- Restructuring the `parrot/` package directory layout.

---

## 2. Architectural Design

### Overview

The solution has three layers:

1. **`pyproject.toml` restructuring** — Move ~30 dependencies from `[project.dependencies]` to new/existing `[project.optional-dependencies]` extras groups.
2. **Lazy import utility** — A single `parrot._imports` module providing a `lazy_import()` helper and `require_extra()` guard that raises clear error messages.
3. **Module-by-module refactoring** — Convert ~40+ files from top-level imports to lazy imports using the standardized utility.

```
pyproject.toml (restructured extras)
         │
         ▼
parrot/_imports.py  ◄── canonical lazy-import utility
         │
         ▼
parrot/tools/*.py ─────┐
parrot/clients/*.py ───┤  all use lazy_import() / require_extra()
parrot/loaders/*.py ───┤
parrot/memory/*.py ────┤
parrot/handlers/*.py ──┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `pyproject.toml` | modifies | Restructure `[project.dependencies]` and `[project.optional-dependencies]` |
| `parrot/tools/*` | modifies | Lazy-import heavy deps (asyncdb, querysource, markitdown, weasyprint, etc.) |
| `parrot/clients/base.py` | modifies | Lazy-import pandas, pydub |
| `parrot/clients/gpt.py` | modifies | Lazy-import pytesseract |
| `parrot/memory/core.py` | modifies | Lazy-import sentence-transformers |
| `parrot/handlers/*.py` | modifies | Lazy-import asyncdb |
| `parrot/loaders/*.py` | modifies | Already partially lazy; standardize pattern |
| `parrot/embeddings/*.py` | modifies | Lazy-import sentence-transformers, faiss |

### Data Models

```python
# No new data models — this is a packaging/import refactor
```

### New Public Interfaces

```python
# parrot/_imports.py — internal utility (not public API)

def lazy_import(
    module_path: str,
    package_name: str | None = None,
    extra: str | None = None,
) -> ModuleType:
    """Import a module lazily, raising a clear error if not installed.

    Args:
        module_path: Dotted import path (e.g., "asyncdb.drivers.pg")
        package_name: pip package name if different from module (e.g., "asyncdb[pg]")
        extra: ai-parrot extra group name (e.g., "db") for error message

    Raises:
        ImportError: with message like:
            "asyncdb is required for database tools.
             Install it with: pip install ai-parrot[db]"
    """
    ...

def require_extra(extra: str, *modules: str) -> None:
    """Check that all required modules for an extra are available.

    Use at class __init__ or function entry point to fail fast.
    """
    ...
```

---

## 3. Module Breakdown

### Module 1: Lazy Import Utility
- **Path**: `parrot/_imports.py`
- **Responsibility**: Provide `lazy_import()` and `require_extra()` functions. Single canonical pattern for the entire codebase.
- **Depends on**: nothing (stdlib only)

### Module 2: pyproject.toml Restructuring
- **Path**: `pyproject.toml`
- **Responsibility**: Move heavy dependencies to extras groups. Define new groups: `db`, `pdf`, `ocr`, `audio`, `finance`, `visualization`, `flowtask`, `arango`, `bigquery`. Keep a meta `all` extra.
- **Depends on**: Module 1 (design must align with extras naming)

### Module 3: Core Clients Lazy Imports
- **Path**: `parrot/clients/base.py`, `parrot/clients/gpt.py`
- **Responsibility**: Lazy-import pandas, pydub, pytesseract in client code.
- **Depends on**: Module 1

### Module 4: Database/Query Tools Lazy Imports
- **Path**: `parrot/tools/db.py`, `parrot/tools/querytoolkit.py`, `parrot/tools/qsource.py`, `parrot/tools/databasequery.py`, `parrot/tools/dataset_manager/`, `parrot/tools/nextstop/base.py`, `parrot/tools/products/__init__.py`
- **Responsibility**: Lazy-import asyncdb and querysource across all DB-related tools.
- **Depends on**: Module 1, Module 2

### Module 5: Handler/Interface Lazy Imports
- **Path**: `parrot/handlers/bots.py`, `parrot/handlers/agents/abstract.py`, `parrot/handlers/chat.py`, `parrot/interfaces/hierarchy.py`, `parrot/interfaces/database.py`, `parrot/interfaces/documentdb.py`, `parrot/stores/kb/user.py`, `parrot/stores/arango.py`
- **Responsibility**: Lazy-import asyncdb and querysource in handler/interface/store code.
- **Depends on**: Module 1, Module 2

### Module 6: Document/PDF/OCR Tools Lazy Imports
- **Path**: `parrot/tools/pdfprint.py`, `parrot/tools/file_reader.py`, `parrot/tools/sitesearch/tool.py`, `parrot/tools/google/tools.py`, `parrot/tools/ibisworld/tool.py`
- **Responsibility**: Lazy-import markitdown, weasyprint, pytesseract.
- **Depends on**: Module 1, Module 2

### Module 7: ML/Embeddings Lazy Imports
- **Path**: `parrot/memory/core.py`, `parrot/memory/skills/store.py`, `parrot/memory/episodic/embedding.py`, `parrot/embeddings/*.py`, `parrot/bots/flow/storage/mixin.py`
- **Responsibility**: Lazy-import sentence-transformers, faiss, torch.
- **Depends on**: Module 1, Module 2

### Module 8: Financial Tools Lazy Imports
- **Path**: `parrot/tools/technical_analysis.py` and related finance tools
- **Responsibility**: Lazy-import ta-lib, pandas-datareader, yfinance.
- **Depends on**: Module 1, Module 2

### Module 9: FlowtTask Isolation
- **Path**: `parrot/tools/flowtask/tool.py`, `parrot/tools/flowtask/__init__.py`
- **Responsibility**: Ensure flowtask is fully lazy (already partially done). Remove flowtask from hard deps. Scope down asyncdb extras when used with flowtask.
- **Depends on**: Module 1, Module 2

### Module 10: Audio/Voice Lazy Imports
- **Path**: `parrot/voice/transcriber/transcriber.py`, `parrot/loaders/basevideo.py`
- **Responsibility**: Lazy-import pydub, whisperx, moviepy.
- **Depends on**: Module 1, Module 2

### Module 11: Bot DB Modules Lazy Imports
- **Path**: `parrot/bots/db/cache.py`, `parrot/bots/database/sql.py`, `parrot/bots/product.py`, `parrot/bots/data.py`
- **Responsibility**: Lazy-import querysource in bot DB modules.
- **Depends on**: Module 1, Module 2

### Module 12: Tests & Validation
- **Path**: `tests/test_lazy_imports.py`, `tests/test_minimal_install.py`
- **Responsibility**: Test that core import works without optional deps. Test that lazy imports raise correct errors. Test that extras install correctly.
- **Depends on**: All previous modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_lazy_import_success` | Module 1 | `lazy_import("json")` works for installed packages |
| `test_lazy_import_missing` | Module 1 | `lazy_import("nonexistent", extra="foo")` raises clear `ImportError` |
| `test_require_extra_success` | Module 1 | `require_extra("db", "asyncdb")` passes when installed |
| `test_require_extra_missing` | Module 1 | `require_extra("db", "nonexistent")` raises clear error |
| `test_error_message_format` | Module 1 | Error message includes `pip install ai-parrot[extra]` |
| `test_core_import_no_optional` | Module 12 | `import parrot` succeeds without optional deps (mocked) |
| `test_tool_init_missing_dep` | Module 12 | Tool raises ImportError with install instruction when dep missing |

### Integration Tests

| Test | Description |
|---|---|
| `test_minimal_install` | Fresh venv with only `ai-parrot` — verify core imports work |
| `test_extras_install_db` | Install `ai-parrot[db]` — verify DB tools load |
| `test_extras_install_all` | Install `ai-parrot[all]` — verify everything loads |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_missing_module(monkeypatch):
    """Simulate a missing optional dependency."""
    import importlib
    original_import = __builtins__.__import__
    def mock_import(name, *args, **kwargs):
        if name == "asyncdb":
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr("builtins.__import__", mock_import)
```

---

## 5. Acceptance Criteria

- [ ] `pip install ai-parrot` (core only) completes in <60s with no system library requirements (no libmysqlclient-dev, no tesseract, no cairo/pango)
- [ ] `import parrot` succeeds without any optional dependencies installed
- [ ] `from parrot.bots import Chatbot, Agent` works without optional deps
- [ ] `from parrot.clients import OpenAIClient, AnthropicClient` works without optional deps
- [ ] Tools that need optional deps raise clear `ImportError` with install instructions when deps are missing
- [ ] `pip install ai-parrot[all]` installs everything and all existing functionality works
- [ ] All existing tests pass with `ai-parrot[all]` installed
- [ ] Core dependencies reduced from ~57 to ~25 or fewer
- [ ] No `mysql` / `libmysqlclient-dev` requirement in core install
- [ ] No `torch` / `sentence-transformers` in core install
- [ ] No system-level C library requirements (tesseract, cairo, pango, ta-lib) in core install
- [ ] pyproject.toml extras groups are documented with clear names

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

**Canonical lazy import pattern** (to be used everywhere):

```python
from parrot._imports import lazy_import

# At module level — deferred, no import happens yet
# In method body — import happens on first use

class PDFExporter:
    def export(self, html: str) -> bytes:
        weasyprint = lazy_import("weasyprint", extra="pdf")
        return weasyprint.HTML(string=html).write_pdf()
```

**For TYPE_CHECKING (type annotations only)**:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

class MyTool:
    def process(self) -> pd.DataFrame:
        pd = lazy_import("pandas", extra="visualization")
        return pd.DataFrame(...)
```

### Proposed Extras Groups

| Extra | Key Packages | Use Case |
|---|---|---|
| `db` | asyncdb[pg,mongodb,arangodb], querysource, psycopg-binary | Database tools/handlers |
| `bigquery` | google-cloud-bigquery, asyncdb[bigquery] | BigQuery integration |
| `pdf` | weasyprint, fpdf, markitdown | PDF export/reading |
| `ocr` | pytesseract | OCR/image text extraction |
| `audio` | pydub | Audio processing |
| `finance` | ta-lib, pandas-datareader, yfinance | Financial analysis tools |
| `visualization` | matplotlib, seaborn | Charting/plotting |
| `flowtask` | flowtask | Task orchestration via flowtask |
| `arango` | python-arango-async | ArangoDB graph store |
| `embeddings` | sentence-transformers, faiss-cpu | (already exists) ML embeddings |
| `all` | all of the above | Full install |

### Known Risks / Gotchas

- **Import order sensitivity**: Some modules may have circular import issues when switching to lazy imports. Must test each module individually.
- **asyncdb extras scoping**: `asyncdb[all]` pulls mysql. Need to scope to `asyncdb[pg,mongodb,arangodb,influxdb,boto3]` or similar.
- **flowtask transitive deps**: flowtask itself depends on asyncdb[all] — may need upstream fix or pinned asyncdb extras in flowtask's own pyproject.
- **Existing `agents-lite` group**: Already partially addresses this. Align new extras with existing groups to avoid confusion.
- **Performance**: Lazy imports add negligible overhead per call but first-call latency increases. Acceptable tradeoff.
- **CI/CD matrix**: Tests need to run with both minimal and full installs to catch regressions.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| No new dependencies | — | This feature removes/moves deps, doesn't add any |

---

## 7. Open Questions

- [ ] Should `asyncdb` remain a hard dependency with minimal extras (e.g., `asyncdb[default]` only), or should it move entirely to `[db]` extra? — *Owner: Jesus Lara*: asyncdb is used for some database connections, install `asyncdb[default]`
- [ ] Should `querysource` be in core (it's used by several bot classes) or in `[db]` extra? — *Owner: Jesus Lara*: move to `[db]` extra
- [ ] Does `flowtask` need an upstream change to stop requiring `asyncdb[all]`? — *Owner: Jesus Lara*: no, flowtask is a DAG tool, will always require asyncdb, so it will always be a hard dependency, move to `[flowtask]` extra.
- [ ] Should `pandas` stay in core (used in base client) or move to an extra? This would require lazy-importing in `parrot/clients/base.py`. — *Owner: Jesus Lara*: pandas is core, stay in core.
- [ ] What's the minimum set of core dependencies that allows `import parrot; bot = Chatbot(...)` to work? — *Owner: Jesus Lara*: `navconfig`, `pandas`, `navigator-api`, `asyncdb[default]`

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All tasks run in a single worktree since they share overlapping files (especially `pyproject.toml` and `parrot/_imports.py`).
- **Cross-feature dependencies**: None. This is a packaging refactor, independent of other features.
- **Recommended approach**: Work module-by-module, testing after each to avoid regression cascades.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-22 | Jesus Lara | Initial draft |
