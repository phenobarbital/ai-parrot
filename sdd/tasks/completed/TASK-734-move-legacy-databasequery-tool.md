# TASK-734: Move legacy `DatabaseQueryTool` into the new subpackage

**Feature**: databasetoolkit-clash
**Spec**: `sdd/specs/databasetoolkit-clash.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-733
**Assigned-to**: unassigned

---

## Context

After TASK-733 renames the toolkit package, both
`parrot.tools.databasequery/` (new home) and the standalone
`parrot_tools/databasequery.py` (1064-line legacy tool) coexist. This
task collapses the legacy tool into the new subpackage as `tool.py`,
keeps a thin compat shim at the original `parrot_tools` location, and
re-exports the moved symbols from `parrot.tools.databasequery.__init__`.

Implements **Module 2** of the spec.

---

## Scope

- `git mv packages/ai-parrot-tools/src/parrot_tools/databasequery.py packages/ai-parrot/src/parrot/tools/databasequery/tool.py`.
- Inside the moved `tool.py`, fix any imports that broke from the move:
  - The file currently imports `from .abstract import AbstractTool` (at line 22) — the old `.abstract` was `parrot_tools.abstract`. After the move, the equivalent is `from parrot.tools.abstract import AbstractTool`. **Verify with `read` first** — there may be other relative imports.
  - Imports from `parrot.security`, `parrot._imports`, `navconfig`, `asyncdb`, `pandas`, `pydantic` are absolute and unaffected by the move.
- Replace `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` with a compat shim (NEW file at the same path):
  ```python
  """Compat shim — use parrot.tools.databasequery instead."""
  from __future__ import annotations
  from parrot.tools.databasequery.tool import (
      DatabaseQueryTool, DriverInfo, DatabaseQueryArgs,
  )
  from parrot.security import QueryLanguage, QueryValidator
  __all__ = [
      "DatabaseQueryTool", "DriverInfo", "DatabaseQueryArgs",
      "QueryLanguage", "QueryValidator",
  ]
  ```
- Update `parrot/tools/databasequery/__init__.py` (renamed by TASK-733) to
  re-export `DatabaseQueryTool`:
  ```python
  from parrot.tools.databasequery.tool import DatabaseQueryTool
  __all__ = [..., "DatabaseQueryTool"]
  ```

**NOT in scope**:
- Refactoring `DatabaseQueryTool` internals (1064 LOC moved verbatim).
- Updating `TOOL_REGISTRY` to point to the new path (TASK-737).
- Refactoring the `DatabaseQueryToolkit` class (TASK-735).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` | DELETE → REPLACE | After `git mv`, recreate at the original path as a 10-line compat shim |
| `packages/ai-parrot/src/parrot/tools/databasequery/tool.py` | CREATE (via mv) | The moved 1064-line legacy tool |
| `packages/ai-parrot/src/parrot/tools/databasequery/__init__.py` | MODIFY | Add `DatabaseQueryTool` re-export |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-tools/src/parrot_tools/databasequery.py — current head
import re, json, os, asyncio
from typing import Dict, Optional, Any, Tuple, Union, Literal, List, TYPE_CHECKING
from datetime import datetime
from pathlib import Path
import pandas as pd
from pydantic import BaseModel, Field, field_validator
from asyncdb import AsyncDB                                                     # line 14
from navconfig import config, BASE_DIR                                          # line 15
from parrot._imports import lazy_import                                         # line 16
from parrot.security import QueryLanguage, QueryValidator                       # line 20
from .abstract import AbstractTool                                              # line 22  ← MUST CHANGE

# After move, line 22 must become:
from parrot.tools.abstract import AbstractTool
# verified: packages/ai-parrot/src/parrot/tools/abstract.py defines AbstractTool

# Compat shim (new file at packages/ai-parrot-tools/src/parrot_tools/databasequery.py):
from parrot.tools.databasequery.tool import (
    DatabaseQueryTool, DriverInfo, DatabaseQueryArgs,
)
from parrot.security import QueryLanguage, QueryValidator
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/databasequery.py:25
class DriverInfo:
    DRIVER_MAP: dict[str, dict] = ...                                           # line 28
    @classmethod
    def normalize_driver(cls, driver: str) -> str: ...
    @classmethod
    def get_query_language(cls, driver: str) -> QueryLanguage: ...
    # additional classmethods at lines 137-186

# packages/ai-parrot-tools/src/parrot_tools/databasequery.py:207
class DatabaseQueryArgs(BaseModel):
    driver: str
    query: Union[str, Dict[str, Any]]
    credentials: Optional[Dict[str, Any]] = None
    dsn: Optional[str] = None
    output_format: Literal["pandas", "json", "native", "arrow"] = "pandas"
    query_timeout: int = 300
    max_rows: int = 10000

# packages/ai-parrot-tools/src/parrot_tools/databasequery.py:308
class DatabaseQueryTool(AbstractTool):
    name = "database_query"
    args_schema = DatabaseQueryArgs
    def __init__(self, **kwargs): ...
    def _validate_query_safety(self, query: str, driver: str) -> Dict[str, Any]: ...   # line 386 — uses QueryValidator
```

```python
# packages/ai-parrot/src/parrot/tools/abstract.py — verify before move
class AbstractTool: ...   # base class — same surface used by current DatabaseQueryTool
```

### Does NOT Exist
- ~~`from .abstract import AbstractTool` works after the move~~ — it does
  NOT. Inside `parrot/tools/databasequery/tool.py` the relative import
  `.abstract` would resolve to `parrot.tools.databasequery.abstract`,
  which is not a module. Use the absolute path
  `from parrot.tools.abstract import AbstractTool`.
- ~~`parrot_tools.abstract` accessible from inside `parrot.tools.*`~~ — the
  `parrot_tools.*` namespace must NOT be imported back from `parrot.*`
  files; cross-package back-references are anti-pattern.
- ~~`parrot.tools.databasequery.tool.DatabaseQueryToolkit`~~ — `tool.py`
  contains only the legacy `DatabaseQueryTool` (single class hierarchy).
  The `DatabaseQueryToolkit` lives in `toolkit.py` (the file renamed in
  TASK-733).

---

## Implementation Notes

### Pattern to Follow

```bash
# 1. Move
git mv packages/ai-parrot-tools/src/parrot_tools/databasequery.py \
       packages/ai-parrot/src/parrot/tools/databasequery/tool.py

# 2. Fix the .abstract import inside the moved file
sed -i 's|^from .abstract import AbstractTool|from parrot.tools.abstract import AbstractTool|' \
    packages/ai-parrot/src/parrot/tools/databasequery/tool.py

# 3. Recreate the compat shim at the original path
cat > packages/ai-parrot-tools/src/parrot_tools/databasequery.py <<'EOF'
"""Compat shim — use parrot.tools.databasequery instead."""
from __future__ import annotations
from parrot.tools.databasequery.tool import (
    DatabaseQueryTool, DriverInfo, DatabaseQueryArgs,
)
from parrot.security import QueryLanguage, QueryValidator
__all__ = [
    "DatabaseQueryTool", "DriverInfo", "DatabaseQueryArgs",
    "QueryLanguage", "QueryValidator",
]
EOF

# 4. Re-export from the new package
# Add to parrot/tools/databasequery/__init__.py:
#   from parrot.tools.databasequery.tool import DatabaseQueryTool
#   __all__ = [..., "DatabaseQueryTool"]
```

### Key Constraints

- The compat shim MUST re-export the same five names that callers
  currently import from `parrot_tools.databasequery`: `DatabaseQueryTool`,
  `DriverInfo`, `DatabaseQueryArgs`, `QueryLanguage`, `QueryValidator`
  (verified by grepping callers, none external in this repo, but the
  registry shim is public surface).
- DO NOT delete `parrot_tools/databasequery.py` outright — replace it
  with the shim. Tests, the `TOOL_REGISTRY` lazy import, and any user
  code still pointing at the old path must keep working.
- DO NOT add new logic to `tool.py` during the move — verbatim relocation
  only (apart from the one `from .abstract` fix).

### References in Codebase

- Spec Section 3 Module 2.
- `packages/ai-parrot-tools/src/parrot_tools/__init__.py:112` — the
  `TOOL_REGISTRY` entry that TASK-737 will repoint.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/tools/databasequery/tool.py` exists and is the moved 1064-LOC file (line count within ±5 of original).
- [ ] `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` exists and is a ~12-line compat shim.
- [ ] `python -c "from parrot.tools.databasequery import DatabaseQueryTool; print(DatabaseQueryTool.name)"` prints `database_query`.
- [ ] `python -c "from parrot_tools.databasequery import DatabaseQueryTool, DriverInfo, DatabaseQueryArgs, QueryLanguage, QueryValidator"` succeeds.
- [ ] `grep -n "from .abstract" packages/ai-parrot/src/parrot/tools/databasequery/tool.py` returns zero matches.
- [ ] `git log --follow packages/ai-parrot/src/parrot/tools/databasequery/tool.py` shows pre-move history (confirms `git mv`).

---

## Test Specification

No new tests in this task; TASK-738 adds the shim coverage.

---

## Agent Instructions

1. Confirm TASK-733 is complete (the target folder `databasequery/` exists).
2. Read `packages/ai-parrot/src/parrot/tools/abstract.py` to confirm `AbstractTool` is importable from there.
3. Perform the `git mv`, fix the `.abstract` import, write the shim, update `__init__.py`.
4. Run the four smoke imports listed in acceptance criteria.
5. Move file to `sdd/tasks/completed/`.

---

## Completion Note

## Completion Note

TASK-734 completed successfully.

- git mv parrot_tools/databasequery.py → parrot/tools/databasequery/tool.py (history preserved)
- Fixed relative import: from .abstract → from parrot.tools.abstract import AbstractTool
- Created compat shim at parrot_tools/databasequery.py re-exporting: DatabaseQueryTool, DriverInfo, DatabaseQueryArgs, QueryLanguage, QueryValidator
- Updated databasequery/__init__.py to add DatabaseQueryTool re-export
- Smoke tests passed: all acceptance criteria verified
