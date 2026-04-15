# TASK-619: Fix Critical Broken Imports (scraping, pricestool, sql)

**Feature**: refactor-tools-imports
**Spec**: `sdd/specs/refactor-tools-imports.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

During the monorepo migration, several tool files in `parrot_tools` retained imports
referencing `parrot.tools.<module>` for modules that only exist in `parrot_tools`.
These cause `ImportError` at runtime. This task fixes the most critical ones: the
scraping sub-package, `pricestool.py`, and `dataset_manager/sources/sql.py`.

Implements Spec Module 1.

---

## Scope

- Fix `pricestool.py:4` — change `parrot.tools.querytoolkit` to `parrot_tools.querytoolkit`
- Fix `dataset_manager/sources/sql.py:18` — change `parrot.tools.databasequery` to `parrot_tools.databasequery`
- Fix `scraping/drivers/selenium_driver.py:71` — change `parrot.tools.scraping.driver` to `parrot_tools.scraping.driver`
- Fix `scraping/driver_factory.py:16,84,87,110` — change all `parrot.tools.scraping.drivers.*` to `parrot_tools.scraping.drivers.*`
- Fix `scraping/toolkit.py:13` — evaluate if this should be `parrot_tools.toolkit` (bridge) instead of `parrot.tools.toolkit` (both work, but prefer consistency within parrot_tools)

**NOT in scope**: security submodule imports (TASK-620), docstring references (TASK-621), test suite (TASK-623).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/pricestool.py` | MODIFY | Fix line 4 import |
| `packages/ai-parrot-tools/src/parrot_tools/dataset_manager/sources/sql.py` | MODIFY | Fix line 18 import |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py` | MODIFY | Fix line 71 import |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py` | MODIFY | Fix lines 16, 84, 87, 110 imports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# These are CORRECT cross-package imports (base classes live in parrot.tools core):
from parrot.tools.abstract import AbstractTool, ToolResult       # packages/ai-parrot/src/parrot/tools/abstract.py
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool     # packages/ai-parrot/src/parrot/tools/toolkit.py
from parrot.tools.decorators import tool_schema, tool             # packages/ai-parrot/src/parrot/tools/decorators.py
from parrot.tools.manager import ToolManager                      # packages/ai-parrot/src/parrot/tools/manager.py:192

# These are ALSO correct (bridge re-exports):
from parrot_tools.abstract import AbstractTool, ToolResult        # packages/ai-parrot-tools/src/parrot_tools/abstract.py
from parrot_tools.toolkit import AbstractToolkit, ToolkitTool     # packages/ai-parrot-tools/src/parrot_tools/toolkit.py
from parrot_tools.decorators import tool_schema, tool             # packages/ai-parrot-tools/src/parrot_tools/decorators.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/querytoolkit.py
class QueryToolkit:  # ONLY exists in parrot_tools, NOT in parrot.tools

# packages/ai-parrot-tools/src/parrot_tools/databasequery.py:205
def get_default_credentials(driver: str) -> Optional[str]:  # ONLY exists in parrot_tools

# packages/ai-parrot-tools/src/parrot_tools/scraping/driver.py
class SeleniumSetup:  # ONLY in parrot_tools.scraping

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver:  # ONLY in parrot_tools.scraping.drivers

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py
class PlaywrightConfig:  # ONLY in parrot_tools.scraping.drivers

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
class PlaywrightDriver:  # ONLY in parrot_tools.scraping.drivers

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py
class SeleniumDriver:  # ONLY in parrot_tools.scraping.drivers
```

### Does NOT Exist

- ~~`parrot.tools.querytoolkit`~~ — does NOT exist; use `parrot_tools.querytoolkit`
- ~~`parrot.tools.databasequery`~~ — does NOT exist; use `parrot_tools.databasequery`
- ~~`parrot.tools.scraping`~~ — does NOT exist; use `parrot_tools.scraping`
- ~~`parrot.tools.scraping.driver`~~ — does NOT exist
- ~~`parrot.tools.scraping.drivers`~~ — does NOT exist

---

## Implementation Notes

### Pattern to Follow

For each broken import, the fix is mechanical:

```python
# BEFORE (broken):
from parrot.tools.querytoolkit import QueryToolkit

# AFTER (fixed):
from parrot_tools.querytoolkit import QueryToolkit
```

For scraping sub-package files, prefer relative imports where the file is within the same package:
```python
# driver_factory.py — relative imports within scraping/
from .drivers.abstract import AbstractDriver          # line 16
from .drivers.playwright_config import PlaywrightConfig   # line 84
from .drivers.playwright_driver import PlaywrightDriver   # line 87
from .drivers.selenium_driver import SeleniumDriver       # line 110

# selenium_driver.py — relative import within scraping/
from ..driver import SeleniumSetup                        # line 71
```

### Key Constraints
- Do NOT change imports of base classes (`AbstractTool`, `AbstractToolkit`, `ToolManager`, etc.) — those correctly point to `parrot.tools`
- Only change imports that reference modules exclusive to `parrot_tools`
- Preserve all other code unchanged

---

## Acceptance Criteria

- [ ] `from parrot_tools.pricestool import PricesTool` works without ImportError
- [ ] `from parrot_tools.dataset_manager.sources.sql import SQLSource` works without ImportError
- [ ] `from parrot_tools.scraping.driver_factory import DriverFactory` works without ImportError
- [ ] `from parrot_tools.scraping.drivers.selenium_driver import SeleniumDriver` works without ImportError
- [ ] No `from parrot.tools.scraping` or `from parrot.tools.querytoolkit` or `from parrot.tools.databasequery` remain in any runtime code

---

## Test Specification

```python
# Manual verification (no new test file for this task)
import importlib

modules = [
    "parrot_tools.pricestool",
    "parrot_tools.scraping.driver_factory",
    "parrot_tools.scraping.drivers.selenium_driver",
]
for mod in modules:
    try:
        importlib.import_module(mod)
        print(f"OK: {mod}")
    except ImportError as e:
        print(f"FAIL: {mod} — {e}")
```

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
7. **Move this file** to `tasks/completed/TASK-619-fix-critical-broken-imports.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
