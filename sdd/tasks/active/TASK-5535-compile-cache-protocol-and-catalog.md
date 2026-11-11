# TASK-5535: Compile-cache protocol and `ModelCatalog`

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5529, TASK-5531
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (catalog + cache), U1. The shipped `CompileCache` is annotated for `CompiledQuery`; its
behaviour already works for any object with a canonical-JSON `cache_key` whose first element is the model digest.
This task widens the annotations to a `CacheableCompiled` protocol and writes `ModelCatalog`, which indexes every
`<models_dir>/<tenant>/<model>.yaml` spec without snapshots and loads selected models atomically.

---

## Scope

- `parrot/semantic/cache.py`: add `CacheableCompiled` Protocol; widen `_data`, `get`, `put` annotations only.
- `accounting/catalog.py`: `ModelCatalog` with `specs`, `load`, `reload`, `get`, `metrics`, `flags`, `set_flags`,
  and `SnapshotProvider` type alias, per spec §3 M8 Interface Skeleton.
  - `specs()` parses every `<tenant>/<model>.yaml` once at construction; the YAML's `tenant`/`model` must equal the
    directory/file names (else `ModelValidationError` naming the file).
  - `load(snapshots, columns)` loads only the supplied keys; unknown keys or identity mismatches raise; the whole
    batch validates before an atomic publish; other loaded models are preserved.
  - `reload(...)` same validation; returns nothing; the caller invalidates replaced hashes in the compile cache.
  - `flags`/`set_flags` hold `ModelLiveStatus` objects (type imported only under `TYPE_CHECKING` from `.live`,
    which TASK-5537 creates).
- `tests/accounting/test_catalog.py`: `test_compile_cache_holds_metric_queries`, `test_catalog_specs_without_snapshots`,
  `test_catalog_load_is_atomic`, `test_catalog_identity_mismatch`.

**NOT in scope**: snapshot providers / manifests wiring (TASK-5536); live flags semantics (TASK-5537).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/cache.py` | MODIFY | `CacheableCompiled` protocol |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/catalog.py` | CREATE | `ModelCatalog` |
| `packages/ai-parrot-semantic/tests/accounting/test_catalog.py` | CREATE | catalog + cache tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.semantic.cache import CompileCache                  # SL/cache.py:32
from parrot.semantic.accounting.loader import load_model, load_spec   # TASK-5529
from parrot.semantic.accounting.compiler import compile_metric        # TASK-5531 (tests only)
from parrot.semantic.accounting.errors import ModelValidationError    # TASK-5524
from parrot.semantic.accounting.models import AccountingModel, AccountingModelSpec, ChartSnapshot, MetricDef
```

### Existing Signatures to Use
```python
# SL/cache.py
from .models import CompiledQuery                                    # :9
def _model_digest_of(cache_key: str) -> str                          # :12 — list[0] or dict["model_digest"]
class CompileCache:                                                  # :32 (anchor occurrences: 1)
    def __init__(self, max_entries: int = 512) -> None               # :35
        self._data: OrderedDict[str, CompiledQuery] = OrderedDict()  # :37
        self._lock = threading.Lock()
    def get(self, key: str) -> CompiledQuery | None                  # :52
    def put(self, compiled: CompiledQuery) -> None                   # :59 — keyed by compiled.cache_key
    def invalidate_model(self, model_digest: str) -> int             # :73
```

### Does NOT Exist
- ~~a tenant level in `SemanticModelLoader`~~ — the shipped loader is flat; `ModelCatalog` is its own loader
  (owner decision U4: `<models_dir>/<tenant>/<model>.yaml`).
- ~~`parrot.semantic.accounting.live`~~ yet — TASK-5537; reference `ModelLiveStatus` only under `TYPE_CHECKING`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/cache.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/catalog.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_catalog.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot-semantic/src/parrot/semantic/cache.py#CompileCache"]
}
```

---

## Implementation Notes

### Key Constraints
- The `cache.py` change is annotations only; `packages/ai-parrot-semantic/tests/test_cache.py` must pass unchanged.
- Catalog publication is atomic: build a new dict, then swap under a `threading.Lock`.
- `catalog.py` imports only the compile path (stdlib, pydantic, yaml, accounting modules) — it stays importable
  without the governed stack.
- `metrics(tenant)` reads parsed specs only (no snapshot access), sorted by (model, metric).

---

## Implementation Blueprint

### Steps (in order)
1. Widen `cache.py`; run `tests/test_cache.py`.
2. Write `ModelCatalog`.
3. Tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/cache.py` (MODIFY)
```python
# BEFORE `class CompileCache:` (verified: SL/cache.py:32) — occurrences: 1
# Add `from typing import Protocol` to the imports.
class CacheableCompiled(Protocol):
    """A compiled artefact with a canonical-JSON cache key whose first element is the model digest."""

    @property
    def cache_key(self) -> str: ...

# REPLACE in CompileCache (each occurrence: 1):
#   :37  self._data: OrderedDict[str, CompiledQuery] = OrderedDict()   →  OrderedDict[str, CacheableCompiled]
#   :52  def get(self, key: str) -> CompiledQuery | None:              →  -> CacheableCompiled | None:
#   :59  def put(self, compiled: CompiledQuery) -> None:               →  def put(self, compiled: CacheableCompiled) -> None:
```

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/catalog.py` (CREATE)
```python
"""Tenant-scoped catalog of accounting models (FEAT-713 M8)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Mapping

from .errors import ModelValidationError
from .loader import load_model, load_spec
from .models import AccountingModel, AccountingModelSpec, ChartSnapshot, MetricDef

if TYPE_CHECKING:
    from .live import ModelLiveStatus

SnapshotProvider = Callable[[str, str, AccountingModelSpec], Awaitable[ChartSnapshot]]
Key = tuple[str, str]


class ModelCatalog:
    """Indexes ``<models_dir>/<tenant>/<model>.yaml`` specs; loads selected models atomically."""

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = Path(models_dir)
        self._lock = threading.Lock()
        self._paths: dict[Key, Path] = {}
        self._specs: dict[Key, AccountingModelSpec] = {}
        self._models: dict[Key, AccountingModel] = {}
        self._flags: dict[Key, "ModelLiveStatus"] = {}
        # FILL IN: scan <tenant>/<model>.yaml (and .yml); load_spec each; enforce tenant/model identity.

    def specs(self) -> dict[Key, AccountingModelSpec]:
        """Parsed YAML specs keyed (tenant, model) — available before snapshots exist."""
        return dict(self._specs)

    def load(self, snapshots: Mapping[Key, ChartSnapshot],
             columns: Mapping[Key, Mapping[str, str]] | None = None) -> None:
        """Load only supplied keys; validate the whole batch before atomic publication."""
        # FILL IN: unknown key ⇒ KeyError; load_model(self._paths[k], snap, columns=...) for all; then swap.
        raise NotImplementedError

    def reload(self, snapshots: Mapping[Key, ChartSnapshot],
               columns: Mapping[Key, Mapping[str, str]] | None = None) -> None:
        """Validate replacements before atomic publication; caller invalidates replaced model hashes."""
        self.load(snapshots, columns)

    def get(self, tenant: str, model: str) -> AccountingModel:
        """The loaded model; KeyError when not loaded."""
        return self._models[(tenant, model)]

    def is_loaded(self, tenant: str, model: str) -> bool:
        return (tenant, model) in self._models

    def metrics(self, tenant: str) -> list[tuple[str, str, MetricDef]]:
        """(model, metric name, definition) from parsed specs for one tenant; no snapshot access."""
        # FILL IN
        raise NotImplementedError

    def flags(self, tenant: str, model: str) -> "ModelLiveStatus | None":
        return self._flags.get((tenant, model))

    def set_flags(self, status: "ModelLiveStatus") -> None:
        with self._lock:
            self._flags[(status.tenant, status.model)] = status
```

### `packages/ai-parrot-semantic/tests/accounting/test_catalog.py` (CREATE)
```python
"""FEAT-713 M8 — catalog and compile cache."""

from __future__ import annotations


def test_compile_cache_holds_metric_queries(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: CompileCache put/get/invalidate_model with a CompiledMetricQuery (cache_key[0] == model_hash).


def test_catalog_specs_without_snapshots(troc_pnl_yaml) -> None:
    # FILL IN: ModelCatalog(troc_pnl_yaml.parent.parent).specs() has ("troc", "troc_pnl"); metrics("troc") listed.


def test_catalog_load_is_atomic(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: a batch with one invalid snapshot publishes nothing; previously loaded models preserved.


def test_catalog_identity_mismatch(tmp_path) -> None:
    # FILL IN: YAML tenant/model differing from its path ⇒ ModelValidationError naming the file.
```

### FILL IN checklist
- [ ] Spec scan + identity check, `load`, `metrics`.
- [ ] Four tests.

---

## Acceptance Criteria

- [ ] `CompileCache` accepts `CompiledMetricQuery`; `tests/test_cache.py` passes unchanged.
- [ ] Specs are listable with no snapshot; loads are atomic and preserve other models.
- [ ] `ruff check` passes on every touched file.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_catalog.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_cache.py -q`

---

## Test Specification

See blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with absolute `PYTHONPATH` for both `packages/ai-parrot-semantic/src` and `packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5535 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
