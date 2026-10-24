# TASK-4679: `_clone_agent_dm` must not share `DataSource` objects across user managers

**Feature**: FEAT-738 — Request-scoped RLS injection and non-shared dataset sources
**Spec**: `sdd/specs/handlers-datasets-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-4678
**Assigned-to**: unassigned
**Discovered-from**: `issue:90cf04ce8edd`

---

## Context

`_clone_agent_dm()` builds a per-user `DatasetManager` from the agent's catalog. It is
careful with the data — `entry.df.copy(deep=True)`, `dict(entry.metadata or {})`,
`dict(entry.column_types)` — but it passes `source=entry.source`, i.e. **the same
`DataSource` instance** into every user's manager.

On its own that is latent. Combined with TASK-4678's in-place RLS rewrite it is the
cross-subject half of `issue:90cf04ce8edd`: subject A's RLS predicates land on the object
subject B's manager also points at.

TASK-4678 fixes the mutation and ships the `request_scoped_copy()` helper this task
consumes. Both halves are needed — fixing only one leaves the leak reachable.

## Scope

- Give each cloned `DatasetEntry` its own source via `request_scoped_copy`.
- Add the first test coverage `_clone_agent_dm` has ever had.

### NOT in scope

- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/*` — that is TASK-4678.
- The other fields `_clone_agent_dm` drops (`description`, `computed_columns`,
  `usage_guidance`, `protected`, `no_cache`) — untidy, but not a security defect, and
  changing them here would widen the blast radius of a vulnerability fix.
- Any change to the HTTP routes or the handler classes.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/datasets.py` | MODIFY |
| `packages/ai-parrot-server/tests/handlers/test_datasets_clone.py` | CREATE |

## Codebase Contract

### Verified Imports

```python
from parrot.tools.dataset_manager import DatasetEntry, DatasetManager
from parrot.tools.dataset_manager.sources import request_scoped_copy   # added by TASK-4678
from parrot.tools.dataset_manager.sources.memory import InMemorySource
```

### Existing Signatures (verified on dev 2026-10-24)

- `handlers/datasets.py:47` `def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None`
  — sole caller is `handlers/datasets.py:130` (`dm = _clone_agent_dm(agent, logger) or DatasetManager()`)
- `handlers/datasets.py:23` existing import line `from ..tools.dataset_manager import DatasetEntry, DatasetManager`
- `tool.py:129` `class DatasetEntry`; `__init__(self, name, description=None, source=None, metadata=None, is_active=True, auto_detect_types=True, cache_ttl=3600, no_cache=False, df=None, query_slug=None, computed_columns=None, usage_guidance=None, protected=False)`
- `DatasetEntry` attributes used by the current clone loop: `.source`, `.metadata`,
  `.is_active`, `.auto_detect_types`, `.cache_ttl`, `.loaded`, `.df`, `._df`,
  `.column_types`, `._column_types`
- `DatasetManager()` takes no required arguments; `._datasets` is a `dict[str, DatasetEntry]`
- `sources/scoped_copy.py` `def request_scoped_copy(source: DataSource) -> DataSource` — **created by TASK-4678**

### Does NOT Exist (Anti-Hallucination)

- No test file `packages/ai-parrot-server/tests/handlers/test_datasets_clone.py`.
- `_clone_agent_dm` has **no** test coverage anywhere in the repo today
  (verified: `grep -rl _clone_agent_dm packages/*/tests` → no hits).
- `DatasetManager` has **no** `clone()`, `copy()` or `for_user()` method.
- `DatasetEntry` has **no** `clone()` method.
- There is no `handlers/datasets.py` import of anything under `sources/` today — the
  import added by this task is the first.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/datasets.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_datasets_clone.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/datasets.py#_clone_agent_dm",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetEntry"
  ]
}
```

## Implementation Blueprint

### `handlers/datasets.py` — MODIFY

```python
# AFTER — insert below `from ..tools.dataset_manager import DatasetEntry, DatasetManager`
# occurrences: 1 (verified: grep -c 'from ..tools.dataset_manager import DatasetEntry, DatasetManager')
from ..tools.dataset_manager.sources import request_scoped_copy
```

```python
# REPLACE — the source argument of the cloned entry
# anchor: `                source=entry.source,`
# occurrences: 1 (verified: grep -c 'source=entry.source,')
                source=request_scoped_copy(entry.source) if entry.source else None,
```

**Why**: `entry.source` is `Optional[DataSource]`, and `DatasetEntry.__init__` accepts
`source=None` (falling back to the legacy `df`/`query_slug` kwargs), so the guard keeps a
sourceless entry working instead of calling `copy.copy(None)`. The existing
`try/except Exception` around the loop already logs and skips an entry whose construction
raises, so an uncopyable source is skipped — never silently shared.

### `tests/handlers/test_datasets_clone.py` — CREATE

```python
"""Tests for _clone_agent_dm's source isolation (issue:90cf04ce8edd)."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from parrot.handlers.datasets import _clone_agent_dm
from parrot.tools.dataset_manager import DatasetEntry, DatasetManager


class _Agent:
    """Minimal stand-in for the agent object _clone_agent_dm reads."""

    def __init__(self, dm: DatasetManager) -> None:
        self._dataset_manager = dm
```

`# FILL IN: three tests, bounded by AC4 and the spec's Test Specification:`
`#   test_clone_agent_dm_does_not_share_source  — cloned.source is not agent_entry.source`
`#   test_clone_agent_dm_isolates_mutation      — mutate the clone's source, assert the`
`#       agent's source is untouched (use a source with _permanent_filter so the dict`
`#       isolation from TASK-4678 is exercised, not just the shallow copy)`
`#   test_clone_agent_dm_skips_uncopyable_source — a source whose copy raises is skipped`
`#       with the existing logger.warning, and does NOT appear in the returned manager`
`# Build the agent's DatasetManager by assigning into dm._datasets directly — that is how`
`# the function reads it, and it avoids needing a live backend.`

### Steps (in order)

1. Confirm TASK-4678 landed: `request_scoped_copy` must be importable from
   `parrot.tools.dataset_manager.sources` — this task cannot run before it.
2. Add the import, then change the one `source=` argument — because the helper must exist
   before the call site references it.
3. Write the three tests; run the Validation Commands.

### FILL IN checklist

- [ ] three tests written, including the uncopyable-source skip path
- [ ] the mutation test uses a source type that has `_permanent_filter`
- [ ] no other `DatasetEntry` field changed in the clone loop

## Acceptance Criteria

- AC4. `_clone_agent_dm` yields entries whose `source` is not the agent's source object,
  and mutating the clone's source does not affect the agent's.
- AC5. Existing server handler tests still pass.
- AC6. `ruff check` clean on the touched file.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_datasets_clone.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_agent_uploads.py -q`

## Test Specification

Pure unit tests — no aiohttp app, no live database. `_clone_agent_dm` takes
`(agent, logger)` and only reads `agent._dataset_manager`, so a tiny stand-in class is
enough. Assert object identity (`is not`), not equality.

## Agent Instructions

Run with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`. Change exactly
one argument in the clone loop plus one import — no refactor of `_clone_agent_dm`, no
touching the handler classes or routes.

## Completion Note

**Completed 2026-10-24.** Exactly the two lines the blueprint specified: one import of
`request_scoped_copy` from `..tools.dataset_manager.sources`, and
`source=request_scoped_copy(entry.source) if entry.source else None` in the clone loop.
No other `DatasetEntry` field touched, no refactor of `_clone_agent_dm`.

Five tests added in the new `tests/handlers/test_datasets_clone.py` — the first coverage
this function has ever had. Beyond the three the task listed, two more earn their place:
`test_clone_agent_dm_two_users_do_not_see_each_other` (two clones of one agent catalog,
the actual cross-subject shape) and `test_clone_agent_dm_copies_dataframe_without_source`
(a df-backed entry gets an `InMemorySource`, which must be isolated too — the `if
entry.source` guard would otherwise be easy to over-trust).

**Regression value verified**: with `datasets.py` reverted to HEAD all five fail; with the
fix all five pass.

**Validation**: `test_datasets_clone.py` + `test_agent_uploads.py` → 9 passed. Whole
`packages/ai-parrot-server/tests/handlers/` suite → 2 failed / 759 passed / 4 skipped; the
two failures are `test_agent_a2ui_stream.py::TestA2UIStreamContract::{test_chunked_wire_contract_unchanged,
test_a2ui_envelope_added_to_final_stream_dict}`, which fail identically on `dev` baseline
and are unrelated to this change. `ruff check` clean on both touched files.
