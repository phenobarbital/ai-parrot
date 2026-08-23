# TASK-2374: DataSourceFactory registration and sync_boe() entrypoint

**Feature**: FEAT-449 — Legal Norms Graph (BOE consolidated legislation with temporal validity)
**Spec**: `sdd/specs/legal-norms-graph-boe.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2373
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. This is the seam that connects the new datasource to the existing pipeline
without editing either. `DataSourceFactory.register_api_source` is a **classmethod** designed
exactly for this — no factory modification required.

Per spec decision **D5**, ai-parrot-server is in the deployment, so `@schedule` is available.
But the entrypoint must stay callable from an external cron too, so the deployment shape is
not baked into the code.

---

## Scope

- Register the source: `DataSourceFactory.register_api_source("boe", BOEDataSource)` at
  package import time in `parrot_tools/legal/boe/__init__.py`.
- Implement `async def sync_boe(tenant_id: str, since: date | None = None) -> RefreshReport`
  that constructs the `OntologyRefreshPipeline` collaborators and calls
  `run(tenant_id, domain="legal")`.
- Keep `sync_boe` free of any scheduler import — it must be callable from `@schedule`,
  from an external cron, or directly from a test.
- Document (in the docstring) how to wire it to `@schedule(ScheduleType.DAILY, ...)` without
  importing the scheduler here.
- Write tests asserting the factory resolves `"boe"` to a `BOEDataSource`.

**NOT in scope**: defining the schedule itself (deployment concern); modifying
`DataSourceFactory`, `OntologyRefreshPipeline`, or any ontology module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/__init__.py` | MODIFY | Register the source; export `sync_boe` |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/sync.py` | CREATE | `sync_boe()` entrypoint |
| `packages/ai-parrot-tools/tests/legal/test_boe_registration.py` | CREATE | Registration + resolution tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from datetime import date
from parrot_loaders.extractors.factory import DataSourceFactory     # factory.py:13
from parrot.knowledge.ontology.refresh import (
    OntologyRefreshPipeline,   # refresh.py:61
    RefreshReport,             # refresh.py:41
)
from parrot.knowledge.ontology.tenant import TenantOntologyManager   # tenant.py:29
from parrot.knowledge.ontology.graph_store import OntologyGraphStore # graph_store.py:33
from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.discovery import RelationDiscovery

from parrot_tools.legal.boe.datasource import BOEDataSource          # TASK-2373
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py:13
class DataSourceFactory:
    _builtin_types: dict[str, type[ExtractDataSource]] = {
        "csv": CSVDataSource, "json": JSONDataSource,
        "sql": SQLDataSource, "records": RecordsDataSource,
    }                                                    # "boe" is NOT here — must register
    _api_registry: dict[str, type[ExtractDataSource]] = {}

    @classmethod
    def register_api_source(                             # line 35 — CLASSMETHOD
        cls, name: str, source_cls: type[ExtractDataSource]
    ) -> None: ...

    def get(                                             # line 46 — INSTANCE method
        self, source_name: str, source_config: dict[str, Any] | None = None,
    ) -> ExtractDataSource: ...

# packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:61
class OntologyRefreshPipeline:
    def __init__(                                        # line 76
        self,
        tenant_manager: TenantOntologyManager,
        graph_store: OntologyGraphStore,
        discovery: RelationDiscovery,
        datasource_factory: Any,          # duck-typed: needs .get(name, config)
        cache: OntologyCache,
        vector_store: Any = None,         # None is fine — v1 does no embedding
        source_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None: ...

    async def run(                                       # line 94
        self, tenant_id: str, domain: str | None = None,
    ) -> RefreshReport: ...

# packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:29
class TenantOntologyManager:
    def resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext: ...  # line 92

# packages/ai-parrot-server/src/parrot/scheduler/manager.py:64 — REFERENCE ONLY, do not import here
def schedule(
    schedule_type: ScheduleType = ScheduleType.DAILY, *,
    success_callback=None, send_result=None, callbacks=None, **schedule_config,
): ...
class ScheduleType(Enum):    # line 52
    ONCE="once"; DAILY="daily"; WEEKLY="weekly"; MONTHLY="monthly"
    INTERVAL="interval"; CRON="cron"; CRONTAB="crontab"
```

### Does NOT Exist

- ~~`parrot.scheduler.manager` in the **core** package~~ — `parrot/scheduler/__init__.py` is a
  38-line lazy shim resolving via `__getattr__` into **ai-parrot-server[scheduler]**. Do NOT
  import the scheduler in `parrot_tools` — it would make the legal toolkit depend on the
  server satellite. Document the wiring instead.
- ~~`"boe"` as a builtin factory type~~ — builtins are exactly `csv`, `json`, `sql`, `records`.
- ~~`DataSourceFactory.register(...)`~~ — the method is `register_api_source(name, source_cls)`
  and it is a **classmethod**, called on the class, not an instance.
- ~~`OntologyRefreshPipeline(sources=...)` or similar~~ — the constructor takes exactly the
  seven parameters listed above. `vector_store` and `source_configs` are the only optional ones.
- ~~A `domain="legal"` default~~ — `run()`'s `domain` defaults to `None`. You must pass
  `domain="legal"` explicitly or the legal ontology layer will not be resolved.

---

## Implementation Notes

### Pattern to Follow

Registration at import time, in `parrot_tools/legal/boe/__init__.py`:

```python
from parrot_loaders.extractors.factory import DataSourceFactory
from .datasource import BOEDataSource
from .sync import sync_boe

DataSourceFactory.register_api_source("boe", BOEDataSource)

__all__ = ["BOEDataSource", "sync_boe"]
```

Scheduler wiring documented but **not imported** (belongs to the deploying agent):

```python
async def sync_boe(tenant_id: str, since: date | None = None) -> RefreshReport:
    """Run the BOE delta sync for one tenant.

    Deployment note: under ai-parrot-server this can be wired to the daily
    scheduler by the *consuming agent*, e.g.::

        from parrot.scheduler import schedule, ScheduleType

        @schedule(ScheduleType.DAILY, hour=4, minute=0)
        async def nightly_boe(self):
            await sync_boe(tenant_id="legal_civil")

    It is equally callable from an external cron, so the deployment shape is
    not baked in here.
    """
```

### Key Constraints

- Async throughout.
- Do **not** import anything from `parrot.scheduler` in this package.
- Pass `domain="legal"` explicitly to `run()`.
- `vector_store=None` — v1 does no embedding.
- Thread `since` through as `source_configs={"boe": {"since": since}}` (or the equivalent
  the datasource expects) — confirm against TASK-2373's filter handling.
- Google-style docstrings and strict type hints.

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py:35` — registration API
- `packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:76-145` — pipeline construction and `run`
- `packages/ai-parrot/src/parrot/scheduler/__init__.py` — proof the scheduler is a satellite shim

---

## Acceptance Criteria

- [ ] `import parrot_tools.legal.boe` registers `"boe"` with `DataSourceFactory`
- [ ] `DataSourceFactory().get("boe", {})` returns a `BOEDataSource` instance
- [ ] `sync_boe(tenant_id, since=None)` is async and returns a `RefreshReport`
- [ ] `sync_boe` passes `domain="legal"` to `OntologyRefreshPipeline.run`
- [ ] **No import of `parrot.scheduler`** anywhere in `parrot_tools/legal/` (asserted by grep in review)
- [ ] Scheduler wiring is documented in the `sync_boe` docstring
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/legal/test_boe_registration.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/legal/`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_boe_registration.py
import inspect
import pytest
from parrot_loaders.extractors.factory import DataSourceFactory


class TestBOERegistration:
    def test_import_registers_source(self):
        import parrot_tools.legal.boe  # noqa: F401
        src = DataSourceFactory().get("boe", {})
        assert type(src).__name__ == "BOEDataSource"

    def test_sync_boe_is_async(self):
        from parrot_tools.legal.boe import sync_boe
        assert inspect.iscoroutinefunction(sync_boe)

    def test_no_scheduler_dependency(self):
        """The legal toolkit must not depend on the ai-parrot-server satellite."""
        import parrot_tools.legal.boe.sync as m
        src = inspect.getsource(m)
        assert "from parrot.scheduler" not in src
        assert "import parrot.scheduler" not in src
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/legal-norms-graph-boe.spec.md` (§3 Module 5, D5 in §8).
2. **Check dependencies** — TASK-2373 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing code.
4. **Update status** in `sdd/tasks/index/legal-norms-graph-boe.json` → `"in-progress"`.
5. **Implement** registration, `sync_boe`, and tests.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-2374-registration-and-sync-entrypoint.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-23
**Notes**: `DataSourceFactory.register_api_source("boe", BOEDataSource)` runs
at import time in `boe/__init__.py`, which now also exports `BOEDataSource`
and `sync_boe`. `sync_boe(tenant_id, since=None)` constructs the pipeline
collaborators with zero-arg constructors (`TenantOntologyManager()`,
`OntologyGraphStore()`, `RelationDiscovery()`, `OntologyCache()`,
`DataSourceFactory()`), `vector_store=None`, and calls
`pipeline.run(tenant_id, domain="legal")`. The scheduler wiring recipe is
documented in the docstring using prose (`parrot.scheduler` as a dotted
reference) rather than a literal `from parrot.scheduler import ...`
statement, because the task's own Test Specification greps the module
source text for that exact substring — a literal import-statement example
in the docstring (as shown in the task's "Pattern to Follow") would have
tripped its own `test_no_scheduler_dependency` check. 5 unit tests pass
(`pytest -c pytest.ini packages/ai-parrot-tools/tests/legal/test_boe_registration.py -v`),
plus the full `tests/legal/` suite (29/29) still passes together.
`ruff check` clean.

**Known integration gap surfaced (not fixed here, out of this task's file
list):** per the task's own instruction to "confirm against TASK-2373's
filter handling," `since` is threaded into `source_configs={"boe":
{"since": since}}` as instructed, but `OntologyRefreshPipeline._refresh_entity`
only ever calls `source.extract(fields=property_names)` — it never
forwards `filters` — and `BOEDataSource._parse_since` (TASK-2373) only
reads `since` from `extract()`'s `filters` argument, not from
`self.config`. So today, `since` threaded via `source_configs` sits inert
through a real `sync_boe()` → `pipeline.run()` call; the `since` filter is
only reachable when a caller invokes `BOEDataSource.extract(filters=...)`
directly (as TASK-2373's own unit tests do). Functionally, `sync_boe`
still does everything ITS acceptance criteria require (async, returns
`RefreshReport`, passes `domain="legal"`, threads `since` into
`source_configs` exactly as instructed) — this gap only matters for
end-to-end incremental-sync behavior, which is TASK-2376's concern. Noting
it here so it isn't silently lost.

**Deviations from spec**: none.
