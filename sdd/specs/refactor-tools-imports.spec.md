# Feature Specification: Refactor Tools Imports (Monorepo Migration Fix)

**Feature ID**: FEAT-089
**Date**: 2026-04-07
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.25.x

---

## 1. Motivation & Business Requirements

### Problem Statement

During the migration to a monorepo structure (`ai-parrot` core + `ai-parrot-tools` sub-package), dozens of tool files retained stale import paths. Files inside `parrot_tools` (the `ai-parrot-tools` package) reference modules via `parrot.tools.*` that **no longer exist** in the core package — they were moved to `parrot_tools`. This causes `ImportError` at runtime when those tools are loaded.

The inverse also occurs: some tool files still use `from parrot.tools.<toolkit>` when the toolkit was moved to `parrot_tools` and only the base classes (`AbstractTool`, `AbstractToolkit`, `ToolManager`, `ToolResult`, decorators) remain in `parrot.tools`.

Yesterday's JiraToolkit incident is one symptom of a systemic problem affecting ~12-15 files with critical or high-severity broken imports.

### Goals
- Fix all broken imports in `packages/ai-parrot-tools/src/parrot_tools/` that reference `parrot.tools.*` for modules that only exist in `parrot_tools`
- Fix all imports that use `parrot_tools.*` for base classes that live in `parrot.tools`
- Verify bridge/re-export files (`parrot_tools/abstract.py`, `toolkit.py`, `decorators.py`) are complete and correct
- Update docstring examples that reference old `parrot.tools.*` paths
- Add a validation script or test that catches future import regressions

### Non-Goals (explicitly out of scope)
- Restructuring the monorepo layout itself
- Moving tools between packages
- Changing the bridge/re-export pattern (it's working correctly)
- Modifying any tool logic or behavior — only imports and references

---

## 2. Architectural Design

### Overview

This is a corrective refactoring, not a new feature. The fix follows a simple rule:

| What you're importing | Correct source | Example |
|---|---|---|
| Base classes (`AbstractTool`, `AbstractToolkit`, `ToolResult`) | `parrot.tools.*` or `parrot_tools.*` bridge | `from parrot.tools.abstract import AbstractTool` |
| Core manager/registry (`ToolManager`, `ToolkitRegistry`) | `parrot.tools.*` | `from parrot.tools.manager import ToolManager` |
| Decorators (`tool`, `tool_schema`) | `parrot.tools.decorators` or `parrot_tools.decorators` | `from parrot.tools.decorators import tool` |
| Toolkit implementations (security, scraping, docker, etc.) | `parrot_tools.*` or relative | `from parrot_tools.security.models import SecurityFinding` |
| Sibling modules within same sub-package | Relative imports | `from ..models import ScanResult` |

### Component Diagram
```
parrot.tools (ai-parrot core)
├── abstract.py       → AbstractTool, ToolResult
├── toolkit.py        → AbstractToolkit, ToolkitTool
├── decorators.py     → tool, tool_schema
├── manager.py        → ToolManager
├── registry.py       → ToolkitRegistry
└── (core tools: vectorstore, pandas, openapi, etc.)

parrot_tools (ai-parrot-tools)
├── abstract.py       → RE-EXPORT from parrot.tools.abstract  ✓
├── toolkit.py        → RE-EXPORT from parrot.tools.toolkit    ✓
├── decorators.py     → RE-EXPORT from parrot.tools.decorators ✓
├── security/         → ONLY in parrot_tools
├── scraping/         → ONLY in parrot_tools
├── docker/           → ONLY in parrot_tools
├── pulumi/           → ONLY in parrot_tools
├── dataset_manager/  → sources ONLY in parrot_tools
└── (100+ tool files)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.abstract` | re-export bridge | `parrot_tools/abstract.py` re-exports base classes |
| `parrot.tools.toolkit` | re-export bridge | `parrot_tools/toolkit.py` re-exports toolkit classes |
| `parrot.tools.decorators` | re-export bridge | `parrot_tools/decorators.py` re-exports decorators |
| `parrot.tools.manager` | cross-package import | Tools that need ToolManager import it directly from core |

### Data Models

No new models. Existing models stay where they are.

### New Public Interfaces

No new interfaces. This is a fix-only refactoring.

---

## 3. Module Breakdown

### Module 1: Fix Critical Broken Imports (scraping, database)
- **Path**: Multiple files in `parrot_tools/scraping/` and `parrot_tools/`
- **Responsibility**: Fix 5 critical imports that cause `ImportError`
- **Files**:
  - `parrot_tools/pricestool.py:4` — `parrot.tools.querytoolkit` → `parrot_tools.querytoolkit`
  - `parrot_tools/dataset_manager/sources/sql.py:18` — `parrot.tools.databasequery` → `parrot_tools.databasequery`
  - `parrot_tools/scraping/drivers/selenium_driver.py:71` — `parrot.tools.scraping.driver` → `parrot_tools.scraping.driver`
  - `parrot_tools/scraping/driver_factory.py:16,84,87,110` — `parrot.tools.scraping.drivers.*` → `parrot_tools.scraping.drivers.*`

### Module 2: Fix Security Submodule Imports
- **Path**: Multiple files in `parrot_tools/security/`
- **Responsibility**: Fix 7 security-related import issues
- **Files**:
  - `parrot_tools/security/__init__.py:8,25-27` — docstring examples and lazy imports
  - `parrot_tools/security/checkov/__init__.py:8`
  - `parrot_tools/security/trivy/__init__.py:7`
  - `parrot_tools/security/prowler/__init__.py:7`
  - `parrot_tools/security/reports/__init__.py:7`
  - `parrot_tools/docker/config.py:12` — `parrot.tools.security.base_executor` → `parrot_tools.security.base_executor`
  - `parrot_tools/docker/executor.py:15` — same
  - `parrot_tools/pulumi/config.py:13` — same
  - `parrot_tools/pulumi/executor.py:13` — same

### Module 3: Fix Docstring / Example References
- **Path**: Multiple `__init__.py` files
- **Responsibility**: Update docstring examples that reference old paths
- **Files**:
  - `parrot_tools/docker/__init__.py` — references `parrot.tools.docker`
  - `parrot_tools/pulumi/__init__.py` — references `parrot.tools.pulumi`
  - `parrot_tools/ibkr/__init__.py` — references `parrot.tools.ibkr`
  - `parrot_tools/system_health/tool.py` — references `parrot.tools.system_health`

### Module 4: Import Validation Test
- **Path**: `packages/ai-parrot-tools/tests/test_imports_integrity.py`
- **Responsibility**: Automated test that imports every registered tool and verifies no `ImportError`
- **Depends on**: Modules 1-3

### Module 5: Full Sweep — Automated Grep Audit
- **Path**: N/A (manual/scripted audit)
- **Responsibility**: Run a final automated sweep across ALL `.py` files in `parrot_tools/` to catch any remaining `from parrot.tools.<module>` where `<module>` only exists in `parrot_tools`. This catches edge cases the initial audit may have missed.
- **Depends on**: Modules 1-3

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_import_all_registered_tools` | Module 4 | Iterate TOOL_REGISTRY and import each entry, assert no ImportError |
| `test_bridge_reexports_complete` | Module 4 | Verify `parrot_tools.abstract`, `.toolkit`, `.decorators` export the same symbols as `parrot.tools.*` |
| `test_no_stale_parrot_tools_imports` | Module 4 | Grep-based test: no `from parrot.tools.<X>` where X is a parrot_tools-only module |

### Integration Tests
| Test | Description |
|---|---|
| `test_security_toolkit_instantiation` | Import and instantiate security toolkit classes |
| `test_scraping_toolkit_instantiation` | Import and instantiate scraping toolkit classes |
| `test_docker_toolkit_instantiation` | Import and instantiate docker toolkit classes |

### Test Data / Fixtures
```python
import importlib
from parrot_tools import TOOL_REGISTRY

PARROT_TOOLS_ONLY_MODULES = [
    "security", "scraping", "docker", "pulumi", "ibkr",
    "quant", "o365", "navigator", "massive", "flowtask",
    "company_info", "google", "retail", "workday", "sassie",
    "troc", "messaging", "epson", "shell_tool", "sitesearch",
    "cloudsploit", "codeinterpreter", "system_health",
    "calculator", "ibisworld", "file",
]
```

---

## 5. Acceptance Criteria

- [ ] All 5 critical broken imports fixed (no `ImportError` on import)
- [ ] All 7 high-severity security/executor imports fixed
- [ ] All docstring examples updated to use correct `parrot_tools.*` paths
- [ ] `test_import_all_registered_tools` passes — every tool in TOOL_REGISTRY is importable
- [ ] `test_no_stale_parrot_tools_imports` passes — no `from parrot.tools.<X>` for parrot_tools-only modules
- [ ] No breaking changes to any existing tool behavior
- [ ] Automated grep audit finds zero remaining stale cross-package imports

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Bridge files in parrot_tools — re-export from parrot.tools (CORRECT, DO NOT CHANGE)
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult  # parrot_tools/abstract.py
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool                       # parrot_tools/toolkit.py
from parrot.tools.decorators import tool_schema, tool, requires_permission          # parrot_tools/decorators.py

# Core imports from parrot.tools that ARE correct (ToolManager lives in core)
from parrot.tools.manager import ToolManager   # packages/ai-parrot/src/parrot/tools/manager.py:192

# Core imports that ARE correct (these modules live in ai-parrot core)
from parrot.tools.abstract import AbstractTool, ToolResult   # packages/ai-parrot/src/parrot/tools/abstract.py
from parrot.tools.toolkit import AbstractToolkit              # packages/ai-parrot/src/parrot/tools/toolkit.py
from parrot.tools.decorators import tool_schema, tool         # packages/ai-parrot/src/parrot/tools/decorators.py
from parrot.tools.registry import ToolkitRegistry             # packages/ai-parrot/src/parrot/tools/registry.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:          # base class for all tools
class ToolResult(BaseModel): # success, status, result, error, metadata, timestamp, files, images, voice_text, display_data

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:       # base class for toolkit collections
class ToolkitTool:           # individual tool within a toolkit

# packages/ai-parrot/src/parrot/tools/manager.py:192
class ToolManager(MCPToolManagerMixin):  # main tool orchestrator

# packages/ai-parrot-tools/src/parrot_tools/security/base_executor.py
class BaseExecutor:          # base for security tool executors
class BaseExecutorConfig:    # configuration for executors

# packages/ai-parrot-tools/src/parrot_tools/security/models.py
class SecurityFinding:       # security scan finding model
class ScanResult:            # aggregated scan result

# packages/ai-parrot-tools/src/parrot_tools/querytoolkit.py
class QueryToolkit:          # query-based toolkit (ONLY in parrot_tools)

# packages/ai-parrot-tools/src/parrot_tools/databasequery.py
def get_default_credentials:  # database credential helper (ONLY in parrot_tools)
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.tools.security`~~ — security module does NOT exist in ai-parrot core; it's in `parrot_tools.security`
- ~~`parrot.tools.scraping`~~ — scraping module does NOT exist in ai-parrot core; it's in `parrot_tools.scraping`
- ~~`parrot.tools.docker`~~ — docker module does NOT exist in ai-parrot core; it's in `parrot_tools.docker`
- ~~`parrot.tools.pulumi`~~ — pulumi module does NOT exist in ai-parrot core; it's in `parrot_tools.pulumi`
- ~~`parrot.tools.querytoolkit`~~ — does NOT exist in core; it's `parrot_tools.querytoolkit`
- ~~`parrot.tools.databasequery`~~ — does NOT exist in core; it's `parrot_tools.databasequery`
- ~~`parrot.tools.ibkr`~~ — does NOT exist in core; it's `parrot_tools.ibkr`
- ~~`parrot.tools.quant`~~ — does NOT exist in core; it's `parrot_tools.quant`
- ~~`parrot.tools.system_health`~~ — does NOT exist in core; it's `parrot_tools.system_health`
- ~~`parrot_tools.models`~~ — there is NO `models.py` at the parrot_tools root level; models are per-subpackage (e.g., `parrot_tools.security.models`)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

**Import correction rules (in priority order):**
1. If importing a base class (`AbstractTool`, `AbstractToolkit`, `ToolResult`, `ToolManager`, decorators) → keep `parrot.tools.*` or use `parrot_tools.*` bridge — both are valid
2. If importing a toolkit-specific module that only exists in `parrot_tools` → change to `parrot_tools.*` absolute or relative import
3. Within a sub-package (e.g., `security/checkov/`) → prefer relative imports for sibling modules
4. In `__init__.py` docstring examples → use `parrot_tools.*` paths

**Search command for audit:**
```bash
# Find all imports in parrot_tools that reference parrot.tools
grep -rn "from parrot\.tools\." packages/ai-parrot-tools/src/parrot_tools/ --include="*.py" | grep -v "__pycache__"

# Cross-reference: which of those modules DON'T exist in parrot.tools?
# Modules that ONLY exist in parrot_tools:
# security, scraping, docker, pulumi, ibkr, quant, o365, navigator, massive,
# flowtask, company_info, google, retail, workday, sassie, troc, messaging,
# epson, shell_tool, sitesearch, cloudsploit, codeinterpreter, system_health,
# calculator, ibisworld, file, querytoolkit, databasequery, pricestool, etc.
```

### Known Risks / Gotchas
- Some `from parrot.tools.*` imports in parrot_tools are CORRECT (for base classes that DO live in core) — don't blindly replace all of them
- The bridge re-export files mean `from parrot_tools.abstract import AbstractTool` and `from parrot.tools.abstract import AbstractTool` are both valid — don't "fix" correct bridge usage
- Some imports are inside docstrings/comments — these won't cause runtime errors but should be updated for developer clarity
- `dataset_manager/` exists in BOTH packages — the core has the base DatasetManager, the tools package has data sources. Imports must be checked carefully.

### External Dependencies

None — this is a pure refactoring of import paths.

---

## 8. Open Questions

- [x] Are there tools in `TOOL_REGISTRY` that aren't importable today? — Yes, at least pricestool, scraping drivers, and security submodules will fail.
- [x] Should we add a CI check (e.g., pre-commit hook or pytest marker) that validates imports on every PR? — *Owner: Jesus Lara*: Yes.

---

## Worktree Strategy

- **Isolation**: `per-spec` (sequential tasks)
- **Rationale**: All changes are import-path corrections in the same package (`parrot_tools`). No parallelism benefit since later tasks depend on the full audit from earlier tasks.
- **Cross-feature dependencies**: None. This spec is self-contained.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-07 | Jesus Lara | Initial draft |
