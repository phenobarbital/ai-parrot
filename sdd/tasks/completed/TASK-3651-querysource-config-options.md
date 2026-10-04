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

**Completed by**: sdd-worker orchestrator (execution `a3f5c9e2-7b41-4d8a-9c3e-591fd0d7a5b2`), coder seat `codex-spark`/`gpt-5.6-terra` (MCP backend `codex`), delivered via `coder_run_chunk` job `job-5c165aac23d8`.
**Date**: 2026-09-23
**Feature branch**: `feat-FEAT-593-tool-configuration-agentstudio`
**Implementation SHA**: `c192c4615bdae43e3e2044e8a7974bc9b0aa6ffb` (`feat(tool-configuration-agentstudio): TASK-3651 — engine-committed coder deliverable`)
**Lint autofix SHA**: `b6d526d05` (`style(tool-configuration-agentstudio): TASK-3651 — engine lint autofix`, 0 residual, 0 errors)
**Merge commit**: `544badc19` (`merge feat-FEAT-593-tool-configuration-agentstudio--TASK-3651-a1-a3f5c9e27b414d8a9c3e591fd0d7a5b2`)

**Notes**: `coder_merge(TASK-3651)` returned `outcome: "merged"` with a clean fidelity check. Diff verified
against the task's Files-to-Create/Modify table: `querysource/config.py` (CREATE, `QuerysourceToolkitConfig`),
`querysource/catalog.py` (MODIFY, `SlugCatalog.list_programs`), `querysource/toolkit.py` (MODIFY,
`config_model`/`options_params`/`secret_params`/`config_options`), and
`tests/querysource/test_querysource_config.py` (CREATE) — 4 files, 96 insertions, matching the blueprint's
scope exactly (`git show --stat c192c4615`). No unlisted files touched, no `sdd/` paths touched.

`coder_record_review` was attempted for this attempt after the SDD-index closure step was (incorrectly)
deferred past a later `coder_plan` re-fetch — by the time this closure ran, the engine's live attempt
registry no longer resolved this attempt (`invalid_arguments: review must match a known attempt's task,
backend and actual model`), tried with several `attempt_uid`/`model` guesses, all rejected identically.
**Review NOT recorded via `coder_record_review`** — preserved here per protocol instead of claiming
reinforcement was saved. Delivery itself was independently verified by direct diff inspection (above) and
via `coder_feedback_report`, which showed no defects for this task/model pairing.

The merge-tier validation for this task's chunk (`chunk1:merge`, `a3f5c9e2-7b41-4d8a-9c3e-591fd0d7a5b2:chunk1:merge`,
covering TASK-3649+TASK-3650, launched separately) ultimately returned `outcome: "timed_out"` (`exit_code: -15`,
settled at 2026-09-23T15:37:14Z) — full-workspace "core escalation" sweep hanging in the pre-existing,
unrelated `ai-parrot-client-google/tests/unit/reel/` suite (`sssssFFFFFFF` — media/ffmpeg dependent tests),
confirmed unrelated to TASK-3651's file scope (querysource only). No merge-tier validation was separately
launched for TASK-3651 alone given the confirmed-unrelated, reliably-hanging nature of the core-escalation
sweep on this worktree; closure relies on the diff/scope verification above plus the coder's own reported
test run (`pytest packages/ai-parrot-tools/tests/querysource/test_querysource_config.py -q`).

**Deviations from spec**: none.
