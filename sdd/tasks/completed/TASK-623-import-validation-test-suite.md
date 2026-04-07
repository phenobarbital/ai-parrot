# TASK-623: Import Validation Test Suite

**Feature**: refactor-tools-imports
**Spec**: `sdd/specs/refactor-tools-imports.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-619, TASK-620, TASK-622
**Assigned-to**: unassigned

---

## Context

After fixing all broken imports (TASK-619 through TASK-622), we need a permanent
test suite that prevents future import regressions. This is especially important
because the monorepo structure makes it easy to accidentally create cross-package
import errors when adding new tools.

The user confirmed (spec open question) that a CI check should be added.

Implements Spec Module 4.

---

## Scope

1. Create `packages/ai-parrot-tools/tests/test_imports_integrity.py` with:
   - `test_import_all_registered_tools` — iterate TOOL_REGISTRY and import each entry
   - `test_bridge_reexports_complete` — verify bridge files export same symbols as core
   - `test_no_stale_cross_package_imports` — grep-based test ensuring no `from parrot.tools.<X>` for parrot_tools-only modules
2. Ensure the test runs in CI (standard pytest discovery)

**NOT in scope**: fixing any remaining broken imports (should all be done by TASK-622).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/test_imports_integrity.py` | CREATE | Import validation test suite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# TOOL_REGISTRY is defined in parrot_tools/__init__.py
from parrot_tools import TOOL_REGISTRY  # packages/ai-parrot-tools/src/parrot_tools/__init__.py

# Bridge files to verify:
import parrot_tools.abstract    # packages/ai-parrot-tools/src/parrot_tools/abstract.py
import parrot_tools.toolkit     # packages/ai-parrot-tools/src/parrot_tools/toolkit.py
import parrot_tools.decorators  # packages/ai-parrot-tools/src/parrot_tools/decorators.py

# Core counterparts:
import parrot.tools.abstract    # packages/ai-parrot/src/parrot/tools/abstract.py
import parrot.tools.toolkit     # packages/ai-parrot/src/parrot/tools/toolkit.py
import parrot.tools.decorators  # packages/ai-parrot/src/parrot/tools/decorators.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py
TOOL_REGISTRY: dict  # Maps tool names to dotted module paths (e.g., "jira" -> "parrot_tools.jiratoolkit.JiraToolkit")
```

### Does NOT Exist

- ~~`parrot_tools.models`~~ — no root-level models.py in parrot_tools
- ~~`parrot.tools.TOOL_REGISTRY`~~ — TOOL_REGISTRY is in parrot_tools, not parrot.tools

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot-tools/tests/test_imports_integrity.py
import importlib
import subprocess
import sys
from pathlib import Path

import pytest


class TestToolRegistryImports:
    """Verify every tool in TOOL_REGISTRY is importable."""

    def test_import_all_registered_tools(self):
        from parrot_tools import TOOL_REGISTRY

        failures = []
        for name, dotted_path in TOOL_REGISTRY.items():
            module_path = dotted_path.rsplit(".", 1)[0]
            try:
                importlib.import_module(module_path)
            except ImportError as e:
                failures.append(f"{name} ({module_path}): {e}")

        assert not failures, (
            f"{len(failures)} tool(s) failed to import:\n"
            + "\n".join(failures)
        )


class TestBridgeReexports:
    """Verify bridge files in parrot_tools re-export core symbols."""

    @pytest.mark.parametrize("symbol", [
        "AbstractTool", "ToolResult", "AbstractToolArgsSchema",
    ])
    def test_abstract_bridge(self, symbol):
        import parrot_tools.abstract as bridge
        import parrot.tools.abstract as core
        assert hasattr(bridge, symbol), f"parrot_tools.abstract missing {symbol}"
        assert getattr(bridge, symbol) is getattr(core, symbol)

    @pytest.mark.parametrize("symbol", ["AbstractToolkit", "ToolkitTool"])
    def test_toolkit_bridge(self, symbol):
        import parrot_tools.toolkit as bridge
        import parrot.tools.toolkit as core
        assert hasattr(bridge, symbol), f"parrot_tools.toolkit missing {symbol}"
        assert getattr(bridge, symbol) is getattr(core, symbol)

    @pytest.mark.parametrize("symbol", ["tool_schema", "tool", "requires_permission"])
    def test_decorators_bridge(self, symbol):
        import parrot_tools.decorators as bridge
        import parrot.tools.decorators as core
        assert hasattr(bridge, symbol), f"parrot_tools.decorators missing {symbol}"
        assert getattr(bridge, symbol) is getattr(core, symbol)


class TestNoStaleCrossPackageImports:
    """Grep-based test: no parrot.tools.<X> for X that only exists in parrot_tools."""

    PARROT_TOOLS_ONLY = [
        "security", "scraping", "docker", "pulumi", "ibkr", "quant",
        "o365", "navigator", "massive", "flowtask", "company_info",
        "google", "retail", "workday", "sassie", "troc", "messaging",
        "epson", "shell_tool", "sitesearch", "cloudsploit",
        "codeinterpreter", "system_health", "calculator", "ibisworld",
        "file", "querytoolkit", "databasequery", "pricestool", "chart",
    ]

    def test_no_stale_imports_in_runtime_code(self):
        """Ensure no .py files import from parrot.tools.<module> for
        modules that only exist in parrot_tools."""
        parrot_tools_dir = Path(__file__).resolve().parent.parent / "src" / "parrot_tools"
        pattern = "|".join(rf"from parrot\.tools\.{m}" for m in self.PARROT_TOOLS_ONLY)

        result = subprocess.run(
            ["grep", "-rn", "-E", pattern, str(parrot_tools_dir),
             "--include=*.py"],
            capture_output=True, text=True,
        )
        stale = [
            line for line in result.stdout.strip().split("\n")
            if line and "__pycache__" not in line
        ]
        assert not stale, (
            f"Found {len(stale)} stale cross-package import(s):\n"
            + "\n".join(stale)
        )
```

### Key Constraints
- Use `pytest` and `pytest-asyncio` (project standards)
- The TOOL_REGISTRY import test should use `pytest.mark.parametrize` if feasible, but a loop with collected failures is also acceptable for clearer error output
- The grep test must exclude `__pycache__` directories
- Keep the `PARROT_TOOLS_ONLY` list maintainable — add a comment explaining how to update it

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-tools/tests/test_imports_integrity.py -v` passes all tests
- [ ] Test catches a simulated regression (manually add a bad import, verify test fails, then revert)
- [ ] `PARROT_TOOLS_ONLY` list covers all current parrot_tools-only modules
- [ ] Tests run in standard pytest discovery (no special configuration needed)

---

## Test Specification

The test file IS the deliverable for this task. See Implementation Notes above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-623-import-validation-test-suite.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
