# TASK-3651: QuerysourceToolkitConfig + config_options(programs) + SlugCatalog.list_programs()

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3647
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10; original request "QuerySlugToolkit > ¿cuáles WS?" — the operator picks the
tenant `programs` scope from a list. `SlugCatalog.list_programs()` returns distinct
`program_slug` values (unfiltered by `TenantGuard`, since the operator is choosing the scope).

---

## Scope

- Create `querysource/config.py` with `QuerysourceToolkitConfig` mirroring the ctor
  (`dsn` is `x-secret`).
- `SlugCatalog.list_programs() -> list[str]`: distinct sorted `program_slug`. Reuse the same
  model/connection pattern as `list()`; prefer a `SELECT DISTINCT` if the model layer allows,
  else fetch all and dedupe.
- On `QuerysourceToolkit`: `config_model`, `options_params = frozenset({"programs"})`,
  `secret_params = frozenset({"dsn"})`; `config_options("programs")` → `await self._open()` then
  `[ConfigOption(value=p, label=p) for p in await self._catalog.list_programs()]`.

**NOT in scope**: HTTP endpoint (TASK-3660).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/config.py` | CREATE | QuerysourceToolkitConfig |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | ClassVars + config_options |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` | MODIFY | SlugCatalog.list_programs() |
| `packages/ai-parrot-tools/tests/querysource/test_querysource_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.tools.config_schema import ConfigOption  # created by TASK-3646
from pydantic import BaseModel, ConfigDict, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):  # :56
    def __init__(self, programs: list[str] | None = None, allow_write: bool = False, allow_raw_sql: bool = False,
                 allow_external_sources: bool = True, include_sql: bool = True, max_rows: int = 200,
                 forced_conditions: dict[str, Any] | None = None, dsn: str | None = None,
                 multiquery_timeout: float = 600.0, **kwargs: Any) -> None: ...  # :64-76
    # self._catalog = SlugCatalog(self._dsn or _qs.default_dsn(), self.guard)  # :107 (inside _open)
    async def list_slugs(self, search=None, program=None, limit=50) -> list[SlugSummary]:  # :138 — calls await self._open()
# packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py
class TenantGuard: __init__(self, programs: list[str] | None)  # :97
class SlugCatalog:  # :131
    async def open(self) -> None  # :139
    async def list(self, *, search: str | None, program: str | None, limit: int) -> list[SlugRecord]:  # :167
    #   rows via model.filter(program_slug=prog, _connection=conn) / model.all(...)  (:187)
```

### Does NOT Exist
- ~~`SlugCatalog.list_programs`~~ — this task creates it.
- ~~`parrot_tools.querysource.config`~~ — this task creates it.
- ~~a `programs` table~~ — programs are only the distinct `program_slug` values in the slug catalog.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/querysource/config.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/querysource/test_querysource_config.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py#SlugCatalog",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py#SlugCatalog.list"
  ]
}
```

---

## Implementation Notes

Read `SlugCatalog.list()` fully (catalog.py:167-192) and mirror its connection handling exactly.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read `SlugCatalog.list` and `_open` — *why*: reuse the exact connection pattern.
2. Add `list_programs` right after `list` — *why*: same model access.
3. Create the config model; add ClassVars + hook to the toolkit.
4. Tests with a stubbed catalog.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/config.py` (CREATE)
```python
"""QuerysourceToolkit configuration model (FEAT-593)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuerysourceToolkitConfig(BaseModel):
    """Operator-facing Querysource configuration; ``programs`` is the tenant scope."""

    model_config = ConfigDict(extra="forbid")
    programs: list[str] | None = Field(default=None, description="Allowed program slugs (tenants); empty = all")
    allow_write: bool = False
    allow_raw_sql: bool = False
    allow_external_sources: bool = True
    include_sql: bool = True
    max_rows: int = 200
    forced_conditions: dict[str, Any] | None = None
    dsn: str | None = Field(default=None, json_schema_extra={"x-secret": True})
    multiquery_timeout: float = 600.0
```

### `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def list(self, \*, search: str | None' catalog.py)
# FILL IN: insert after the end of `SlugCatalog.list` (verified: catalog.py:167-192)
    async def list_programs(self) -> list[str]:
        """Distinct ``program_slug`` values across the catalog, sorted (FEAT-593).

        Not filtered by ``TenantGuard``: the operator is choosing the scope itself.
        """
        # FILL IN: same model/connection pattern as list(); collect {row.program_slug}; return sorted
        raise NotImplementedError
```

### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class QuerysourceToolkit(AbstractToolkit):' toolkit.py)
# FILL IN: insert right after the class docstring (verified: toolkit.py:56)
    #: FEAT-593 — Agent Studio configuration surface.
    config_model = QuerysourceToolkitConfig
    options_params = frozenset({"programs"})
    secret_params = frozenset({"dsn"})

    async def config_options(self, param: str) -> list[ConfigOption]:
        """Dynamic choices for Agent Studio (FEAT-593): catalog program slugs for ``programs``."""
        if param != "programs":
            return await super().config_options(param)
        await self._open()
        return [ConfigOption(value=p, label=p) for p in await self._catalog.list_programs()]
```
Add `from .config import QuerysourceToolkitConfig` and `from parrot.tools.config_schema import ConfigOption` at the top.

### FILL IN checklist
- [ ] `SlugCatalog.list_programs` body; bounded by `SlugCatalog.list` connection pattern

---

## Acceptance Criteria

- [ ] `QuerysourceToolkit.config_schema("querysource")`: `programs` has `x-options`, `dsn` has `x-secret` (AC6, AC12).
- [ ] `config_options("programs")` returns sorted distinct programs from a stubbed catalog.
- [ ] Existing querysource tests still pass (run the file below).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-tools/tests/querysource/test_querysource_config.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/test_querysource_config.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot_tools.querysource.toolkit import QuerysourceToolkit


def test_schema():
    props = QuerysourceToolkit.config_schema("querysource")["schema"]["properties"]
    assert props["programs"]["x-options"] is True and props["dsn"]["x-secret"] is True


@pytest.mark.asyncio
async def test_config_options_programs(monkeypatch):
    kit = QuerysourceToolkit()
    monkeypatch.setattr(kit, "_open", AsyncMock())
    kit._catalog = SimpleNamespace(list_programs=AsyncMock(return_value=["a", "b"]))
    assert [o.value for o in await kit.config_options("programs")] == ["a", "b"]


@pytest.mark.asyncio
async def test_list_programs_distinct_sorted(monkeypatch):
    # FILL IN: build a SlugCatalog with a stubbed model/connection returning rows with
    #   program_slug in ["b", "a", "b"] and assert ["a", "b"]
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
