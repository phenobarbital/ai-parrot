# TASK-4844: MetricStore protocol, InMemoryMetricStore and metrics.yaml loader

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4843
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (store + YAML seed lane) and §7 "`metrics.yaml` format". The registry (TASK-4847)
composes views over a `MetricStore`; the Postgres store (TASK-4848) implements the same protocol.
`load_agent_metrics` reads the agent-level file and every FEAT-707 tenant tree.

---

## Scope

- Implement `MetricStore` (Protocol) and `InMemoryMetricStore` in `parrot/metrics/store.py`.
- Implement `MetricsYamlReport`, `load_metrics_yaml`, `load_agent_metrics`, `seed_store` in `parrot/metrics/loader.py`.
- Write `test_store_and_loader.py`.

**NOT in scope**: `importers.py` (TASK-4845), Postgres store (TASK-4848), registry/view (TASK-4847),
editing `parrot/metrics/__init__.py` (its lazy map already names these symbols — TASK-4843).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/metrics/store.py` | CREATE | Protocol + dict-backed store |
| `packages/ai-parrot/src/parrot/metrics/loader.py` | CREATE | YAML loaders + seeding |
| `packages/ai-parrot/tests/unit/metrics/test_store_and_loader.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.metrics.models import MetricDefinition          # created by TASK-4843
from parrot.skills.tenancy import validate_tenant_id, TENANTS_DIRNAME   # verified: skills/tenancy.py:42, :38
from parrot.utils.paths import secure_path                  # verified: utils/paths.py:52
import yaml                                                  # core dep (a2ui/recipes/store.py uses it)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/utils/paths.py:52
def secure_path(base: Union[str, Path], *segments: str, name: str = "path segment") -> Path
    # each segment validated with validate_path_segment; raises ValueError when the result escapes base

# packages/ai-parrot/src/parrot/skills/tenancy.py
TENANTS_DIRNAME: Final[str] = "tenants"            # L38
def validate_tenant_id(value: str) -> str          # L42 — ValueError on invalid/reserved
class TenantTreeReport                              # L135 — shape to mirror for MetricsYamlReport (dataclass there; ours is Pydantic)
```

### Does NOT Exist
- ~~Reusing `discover_tenant_dirs` (tenancy.py:63) for metrics~~ — it only returns tenants that have a
  `skills/` directory and warns otherwise; a tenant with only `metrics.yaml` would be skipped. Iterate
  `agent_root / TENANTS_DIRNAME` yourself.
- ~~`tenant_metrics_dir()` helper in tenancy.py~~ — does not exist; build the path with `secure_path`.
- ~~An async YAML reader~~ — loading is configure-time, sync (`yaml.safe_load`).
- ~~`MetricStore.list_visible`~~ — only on the Postgres store (TASK-4848).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/metrics/store.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/metrics/loader.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/metrics/test_store_and_loader.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/utils/paths.py#secure_path",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#validate_tenant_id",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#TENANTS_DIRNAME"
  ]
}
```

---

## Implementation Notes

- A bad YAML row must **never** raise — drop it and record the reason in the report (agent must not crash).
- A tenant file forces `tenant` onto every entry, strips `global_only` (set False, record a note), and
  rejects `visibility: public` (drop + report). An entry declaring a *different* tenant is dropped.
- Agent-level file entries get `tenant=None`; an entry there declaring a tenant is dropped.
- `InMemoryMetricStore` keys on `(tenant, id)`; must return copies (`model_copy(deep=True)`) so callers can't mutate stored state.

---

## Implementation Blueprint

### Steps (in order)
1. Write `store.py` — *why*: loader's `seed_store` and the registry type against the protocol.
2. Write `loader.py` — *why*: depends on the protocol only for `seed_store`.
3. Write tests using `tmp_path` agent trees; run validation.

### `packages/ai-parrot/src/parrot/metrics/store.py` (CREATE)
```python
"""MetricStore protocol and the in-memory backend (FEAT-756 M2)."""
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from parrot.metrics.models import MetricDefinition


@runtime_checkable
class MetricStore(Protocol):
    """Persistence boundary. Tenancy is explicit on every call; ``tenant=None`` means the global namespace."""

    async def get(self, metric_id: str, *, tenant: str | None) -> MetricDefinition | None:
        """Return one definition in exactly that namespace, or ``None``."""

    async def list(self, *, tenant: str | None, program: str | None = None) -> list[MetricDefinition]:
        """Return every definition of one namespace (no visibility filtering — that is the registry's job)."""

    async def save(self, definition: MetricDefinition, *, overwrite: bool = False) -> str:
        """Insert (or upsert when ``overwrite``) and return ``definition.id``; raises ``ValueError`` on a duplicate."""

    async def delete(self, metric_id: str, *, tenant: str | None) -> bool:
        """Remove one definition; ``True`` when a row was removed."""


class InMemoryMetricStore:
    """Dict-backed ``MetricStore`` for tests, notebooks and agents without Postgres."""

    def __init__(self, definitions: Iterable[MetricDefinition] = ()) -> None:
        """Pre-load ``definitions`` (duplicates raise ``ValueError``)."""
        self._rows: dict[tuple[str | None, str], MetricDefinition] = {}
        for d in definitions:
            self._put(d, overwrite=False)

    def _put(self, definition: MetricDefinition, *, overwrite: bool) -> str:
        key = (definition.tenant, definition.id)
        # FILL IN: duplicate and not overwrite → ValueError(f"metric {definition.id!r} already exists ...");
        #          store definition.model_copy(deep=True); return definition.id
        raise NotImplementedError

    async def get(self, metric_id: str, *, tenant: str | None) -> MetricDefinition | None:
        # FILL IN: return deep copy or None
        raise NotImplementedError

    async def list(self, *, tenant: str | None, program: str | None = None) -> list[MetricDefinition]:
        # FILL IN: filter by tenant (exact, None = global) and program; sort by id; deep copies
        raise NotImplementedError

    async def save(self, definition: MetricDefinition, *, overwrite: bool = False) -> str:
        return self._put(definition, overwrite=overwrite)

    async def delete(self, metric_id: str, *, tenant: str | None) -> bool:
        return self._rows.pop((tenant, metric_id), None) is not None
```

### `packages/ai-parrot/src/parrot/metrics/loader.py` (CREATE)
```python
"""metrics.yaml seed lane: agent-level + FEAT-707 tenant trees (FEAT-756 M2)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Mapping

import yaml
from pydantic import BaseModel, Field, ValidationError

from parrot.metrics.models import MetricDefinition
from parrot.metrics.store import MetricStore
from parrot.skills.tenancy import TENANTS_DIRNAME, validate_tenant_id  # verified: tenancy.py:38, :42
from parrot.utils.paths import secure_path  # verified: utils/paths.py:52

METRICS_FILENAME = "metrics.yaml"
_LOGGER = logging.getLogger(__name__)


class MetricsYamlReport(BaseModel):
    """Configure-time audit of one YAML file (loaded ids, dropped entries with reasons) — ``TenantTreeReport`` twin."""
    path: str
    tenant: str | None = None
    loaded: list[str] = Field(default_factory=list)
    dropped: list[dict[str, str]] = Field(default_factory=list)   # {"entry": <id or index>, "reason": ...}
    notes: list[str] = Field(default_factory=list)


def load_metrics_yaml(path: Path, *, tenant: str | None = None, logger: logging.Logger | None = None,
                      ) -> tuple[list[MetricDefinition], MetricsYamlReport]:
    """Parse ``metrics.yaml`` (top-level ``metrics: [ … ]``). ``tenant`` is FORCED onto every entry
    (a tenant file cannot declare another tenant, nor ``global_only``); invalid entries are dropped and
    reported, never raised — a bad row must not take the agent down."""
    log = logger or _LOGGER
    report = MetricsYamlReport(path=str(path), tenant=tenant)
    # FILL IN: missing file → ([], report); unreadable / non-mapping / no list under "metrics" → report.dropped
    #          with entry="<file>" and return ([], report) (log.warning).
    # FILL IN: per entry (index i): must be a dict; entry tenant present and != tenant → drop;
    #          tenant file: drop visibility=="public"; global_only true → set False + note;
    #          set entry["tenant"] = tenant; MetricDefinition.model_validate → ValidationError → drop with str(exc)[:300];
    #          duplicate id within the file → drop the later one.
    raise NotImplementedError


def load_agent_metrics(agent_root: Path, *, logger: logging.Logger | None = None,
                       ) -> dict[str | None, list[MetricDefinition]]:
    """Return ``{None: global defs, "<tenant>": tenant defs, …}`` from ``agent_root/metrics.yaml`` and every
    ``agent_root/tenants/<t>/metrics.yaml``."""
    log = logger or _LOGGER
    result: dict[str | None, list[MetricDefinition]] = {}
    # FILL IN: global = load_metrics_yaml(agent_root / METRICS_FILENAME, tenant=None)
    # FILL IN: tenants_root = agent_root / TENANTS_DIRNAME; if dir: for entry in sorted(iterdir()) dirs only:
    #          try validate_tenant_id(entry.name); path = secure_path(agent_root, TENANTS_DIRNAME, entry.name,
    #          METRICS_FILENAME, name="tenant id") except ValueError → log.warning + skip;
    #          skip silently when the file does not exist; include tenant key only when ≥1 def loaded.
    #          Do NOT use discover_tenant_dirs (it requires a skills/ dir).
    return result


async def seed_store(store: MetricStore, definitions: Mapping[str | None, Iterable[MetricDefinition]],
                     *, overwrite: bool = False) -> int:
    """Persist loaded definitions; returns the number written. Idempotent with ``overwrite=True``."""
    written = 0
    # FILL IN: for each def: await store.save(d, overwrite=overwrite); ValueError (duplicate, overwrite False)
    #          → skip without counting; return written
    return written
```
**Why this shape**: spec §3 M2 skeleton fixes the signatures; `secure_path` gives the FEAT-707
containment guarantee (symlink/`..` escape refused).

### FILL IN checklist
- [ ] `InMemoryMetricStore._put/get/list` bodies
- [ ] `load_metrics_yaml` drop/force rules (spec §7)
- [ ] `load_agent_metrics` tenant iteration without `discover_tenant_dirs`
- [ ] `seed_store` duplicate handling
- [ ] tests

---

## Acceptance Criteria

- [ ] In-memory CRUD: get/list/save/delete; duplicate save → `ValueError`; `overwrite=True` upserts.
- [ ] `load_metrics_yaml` forces the tenant, strips `global_only`, rejects `public` in tenant files, drops+reports invalid rows without raising.
- [ ] `load_agent_metrics(tmp_path/"agents/x")` with `metrics.yaml` + `tenants/acme/metrics.yaml` (no `skills/` dir) → `{None: [...], "acme": [...]}`.
- [ ] Invalid tenant dir name (e.g. `tenants/Bad Name/`) skipped with a warning.
- [ ] `seed_store` idempotent with `overwrite=True`.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/metrics/test_store_and_loader.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/metrics/test_store_and_loader.py
import pytest
import yaml

from parrot.metrics.loader import load_agent_metrics, load_metrics_yaml, seed_store
from parrot.metrics.store import InMemoryMetricStore


@pytest.mark.asyncio
async def test_inmemory_store_crud(worked_hours_def): ...           # FILL IN

def _write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"metrics": entries}))

def test_load_metrics_yaml_forces_tenant_and_drops_invalid(tmp_path, worked_hours_def): ...  # FILL IN

def test_load_agent_metrics_discovers_tenant_trees(tmp_path, worked_hours_def): ...         # FILL IN (no skills/ dir)

def test_load_metrics_yaml_missing_file_is_empty(tmp_path): ...                             # FILL IN

@pytest.mark.asyncio
async def test_seed_store_idempotent(worked_hours_def): ...                                 # FILL IN
```

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4843 is `done` in `sdd/tasks/index/metric-definition-registry.json`.
2. Verify the contract; mark in-progress; implement; run validation with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only listed files; `scripts/sdd/close_task.sh TASK-4844 metric-definition-registry verified`.

---

## Completion Note

*(Agent fills this in when done)*
