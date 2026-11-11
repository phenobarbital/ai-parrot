# TASK-5515: DataSource self_governed flag and current_owner hook (M1)

**Feature**: FEAT-880 — DatasetManager semantic source — add_semantic()
**Spec**: `sdd/specs/datasetmanager-semantic-source.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. DatasetManager needs a generic, source-declared way to know that a source enforces its own authorization and returns subject-scoped rows, plus a hook naming the calling subject. Every later task (M2, M3, M4, M7) reads these two members.

---

## Scope

- Add the `self_governed` property (default `False`) to `DataSource`, next to `has_builtin_cache`.
- Add the `current_owner()` method (default `None`).
- Create `packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py` with the shared `_GovernedSource` test double and the M1 tests. Later tasks (TASK-5516, 5517, 5518, 5521) append to this file and reuse the double.

**NOT in scope**: any DatasetManager behavior change (TASK-5516/5517/5518); the semantic source (TASK-5520).

---

## Files to Create / Modify

| File | Action | Purpose |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py` | MODIFY | add `self_governed` and `current_owner` |
| `packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py` | CREATE | shared test double + M1 tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `254caceeb8` on `dev`. Re-verify before writing code.

### Verified Imports
```python
from parrot.tools.dataset_manager.sources.base import DataSource  # verified: sources/base.py:23
from parrot.tools.dataset_manager.sources import (  # verified: sources/__init__.py:23-31
    InMemorySource, QuerySlugSource, SQLQuerySource, TableSource, CompositeDataSource)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py
from typing import Dict                                   # line 18 (no Optional imported)
class DataSource(ABC):                                    # line 23
    def __init__(self, routing_meta: Dict | None = None)   # line 46
    @property
    def has_builtin_cache(self) -> bool:                   # line 102, returns False (line 113)
    @property
    @abstractmethod
    def cache_key(self) -> str:                            # line 117
```

### Does NOT Exist
- ~~`DataSource.self_governed`~~, ~~`DataSource.current_owner`~~ — created here.
- ~~`typing.Optional` in `base.py`~~ — not imported; use `str | None`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py#DataSource",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py#DataSource.has_builtin_cache"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Both members are concrete with safe defaults: every existing subclass must keep working unchanged.
- `current_owner` is a plain method, not a property — it reads request context at call time.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py:101-113` — `has_builtin_cache`, the pattern to copy.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Insert both members after the `has_builtin_cache` property — *why*: keeps the optional hooks together.
2. Create the test file with `_GovernedSource` exactly as given — *why*: four later tasks reuse it.
3. Run the validation command.

### `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def has_builtin_cache(self) -> bool:' sources/base.py)
# AFTER — insert below the `return False` that ends has_builtin_cache (verified: sources/base.py:113)

    @property
    def self_governed(self) -> bool:
        """Whether this source enforces its own authorization and returns subject-scoped rows.

        When True, DatasetManager does not wrap the source in AuthorizingDataSource, always
        re-fetches, never uses its Redis cache, keeps its DataFrame per calling subject
        (see ``current_owner``) and never copies it to another manager.

        Returns:
            False by default.
        """
        return False

    def current_owner(self) -> str | None:
        """Opaque, stable identifier of the subject calling right now, or None.

        Only consulted for ``self_governed`` sources: DatasetEntry keys the loaded
        DataFrame by it.

        Returns:
            None by default, and None whenever no subject can be resolved.
        """
        return None
```
**Why**: spec §3 M1 fixes both names and defaults; later tasks attach behavior to them.

### `packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py` (CREATE)
```python
"""FEAT-880: DatasetManager support for self-governed data sources."""
from __future__ import annotations

import pandas as pd
import pytest

from parrot.tools.dataset_manager.sources.base import DataSource
from parrot.tools.dataset_manager.sources import InMemorySource


class _GovernedSource(DataSource):
    """Minimal self-governed source: records fetch params, one frame per call."""

    def __init__(self, owner: str | None = "subject-a") -> None:
        super().__init__()
        self.name = "governed"
        self.owner = owner
        self.calls: list[dict] = []

    @property
    def self_governed(self) -> bool:
        return True

    @property
    def has_builtin_cache(self) -> bool:
        return True

    @property
    def cache_key(self) -> str:
        return "governed:test"

    def current_owner(self) -> str | None:
        return self.owner

    def describe(self) -> str:
        return "governed test source"

    async def fetch(self, **params) -> pd.DataFrame:
        self.calls.append(dict(params))
        return pd.DataFrame({"n": [len(self.calls)]})


def test_datasource_self_governed_default_false() -> None:
    """Every existing source reports self_governed == False."""
    source = InMemorySource(df=pd.DataFrame({"a": [1]}), name="mem")
    assert source.self_governed is False
    # FILL IN: also instantiate QuerySlugSource / SQLQuerySource / TableSource with minimal valid args
    #   (or assert on the class attribute) — bounded by: no network, no credentials.


def test_datasource_current_owner_default_none() -> None:
    """Every existing source returns None from current_owner()."""
    assert InMemorySource(df=pd.DataFrame({"a": [1]}), name="mem").current_owner() is None


def test_governed_double_contract() -> None:
    """The shared double declares both hooks."""
    source = _GovernedSource()
    assert source.self_governed is True
    assert source.current_owner() == "subject-a"
```
**Why**: later tasks import nothing from this file; they append tests to it and reuse `_GovernedSource`.

### FILL IN checklist
- [ ] `test_datasource_self_governed_default_false` — cover the other source classes; bounded by no network/credentials.

---

## Acceptance Criteria

- [ ] `DataSource.self_governed` returns False and `DataSource.current_owner()` returns None for every existing source
- [ ] Validation command passes; `ruff check` clean on both files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py -q`

---

## Test Specification

See the CREATE block above; it is the full scaffold.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug datasetmanager-semantic-source --feature-id FEAT-880`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/datasetmanager-semantic-source.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/datasetmanager-semantic-source.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH` set to the absolute `src` dirs of every changed package (worktree rule)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5515 datasetmanager-semantic-source verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
