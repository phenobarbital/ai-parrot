# TASK-4847: MetricView + MetricRegistry (tenant overlay, list/describe/resolve)

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4844, TASK-4846
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (second half). `MetricRegistry` is the service the toolkit (TASK-4852),
the routing mixin (TASK-4853) and the HTTP lane consult. `MetricView` overlays a tenant
namespace on the global one with the `SkillView` collision rules (FEAT-707), re-implemented
for `MetricDefinition` (SkillView is typed over `SkillFileRegistry` and cannot be reused).

---

## Scope

- Implement `MetricView` (compose: C1 shadow by id, C2 alias collision → tenant wins and the
  global alias is dropped, C3 `global_only` global drops the tenant entry with a warning,
  C5/C6 single-namespace views), `get`, `list(program=)`, `terms()`.
- Implement `MetricRegistry` (`view` cached per tenant, `list`, `describe` raising
  `MetricNotFound`, `resolve` → `MetricMatch | None`, `invalidate`).
- `resolve` runs `MetricMatcher.match` under `asyncio.to_thread`, re-configures the matcher
  bank when the tenant view changes, and NEVER raises (log + return `None`).
- Write `test_registry_view.py`.

**NOT in scope**: the matcher itself, period/dimension parsing (TASK-4846 — just call its
static helpers), stores (TASK-4844), Postgres (TASK-4848), the bot hook (TASK-4853).
Do NOT edit `parrot/metrics/__init__.py` (TASK-4843 already lazily exports `MetricRegistry`, `MetricView`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/metrics/registry.py` | CREATE | `MetricView`, `MetricRegistry` |
| `packages/ai-parrot/tests/unit/metrics/test_registry_view.py` | CREATE | C1–C6 + registry tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.metrics.models import MetricDefinition, MetricMatch      # TASK-4843 (new)
from parrot.metrics.errors import MetricNotFound                       # TASK-4843 (new)
from parrot.metrics.store import MetricStore, InMemoryMetricStore      # TASK-4844 (new)
from parrot.metrics.matching import MetricMatcher                      # TASK-4846 (new)
```

### Existing Signatures to Use
```python
# TASK-4846 (new) — parrot/metrics/matching.py
class MetricMatcher:
    def __init__(self, *, embedding_model: str = "intfloat/multilingual-e5-small", threshold: float = 0.85,
                 margin: float = 0.05, enable_embeddings: bool = True) -> None
    def configure(self, bank: Mapping[str, Sequence[str]]) -> None
    def match(self, question: str) -> tuple[str, float, str, bool] | None   # (metric_id, score, lane, ambiguous); sync, CPU-bound
    @staticmethod
    def parse_period(question: str) -> PeriodPreset | None
    @staticmethod
    def parse_dimension(question: str, dimensions: Sequence[DimensionSpec]) -> str | None

# TASK-4844 (new) — parrot/metrics/store.py
class MetricStore(Protocol):
    async def get(self, metric_id: str, *, tenant: str | None) -> MetricDefinition | None
    async def list(self, *, tenant: str | None, program: str | None = None) -> list[MetricDefinition]

# TASK-4843 (new) — models.py
class MetricDefinition: id; aliases: list[str]; global_only: bool; program: str | None; dimensions
    def matching_terms(self) -> list[str]; def shadow_key(self) -> str
class MetricMatch: metric; score; lane: Literal["alias","embedding"]; ambiguous; tenant; requested_period; requested_dimension

# packages/ai-parrot/src/parrot/skills/tenancy.py — PATTERN ONLY, do not import SkillView
class SkillView:            # L146
    def compose(self)       # L172 — globals indexed by name/trigger; tenant None → globals only;
                            #   locked = global_only; tenant entries checked against locked first.
```

### Does NOT Exist
- ~~`SkillView` accepting `MetricDefinition`~~ — typed over `SkillFileRegistry`; re-implement, do not subclass.
- ~~`MetricStore.list_visible`~~ — only on the Postgres store (TASK-4848); the registry takes an optional `visibility_filter` callable instead.
- ~~`MetricMatcher.match_async`~~ — `match` is sync; wrap in `asyncio.to_thread`.
- ~~`TenantTreeReport` for metrics~~ — keep a simple `self.report: dict[str, list[str]]` (shadowed / dropped ids).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/metrics/registry.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/metrics/test_registry_view.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#SkillView"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `parrot.metrics` must not import `parrot.outputs.a2ui` or `parrot.tools` (spec §7).
- A registry must never break a turn: `resolve` catches `Exception`, logs at warning, returns `None`.
- View cache key = tenant (`None` for global); `invalidate(tenant)` drops one entry and forces the matcher bank to be rebuilt; `invalidate()` drops all.
- One `MetricMatcher` per registry; track which tenant's bank is loaded (`self._bank_tenant`) and call `configure(view.terms())` only when it differs.

---

## Implementation Blueprint

### Steps (in order)
1. Write `MetricView` — *why*: the overlay is pure and testable without a store.
2. Write `MetricRegistry.view/list/describe` over the store — *why*: resolve depends on a composed view.
3. Write `resolve` with to_thread + never-raise — *why*: spec R3/§7 (event loop, turn safety).
4. Write tests C1, C2, C3, C5, C6 + registry resolve/never-raises.

### `packages/ai-parrot/src/parrot/metrics/registry.py` (CREATE)
```python
"""Tenant-aware metric registry: MetricView overlay + MetricRegistry service (FEAT-756 M3)."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Sequence

from parrot.metrics.errors import MetricNotFound
from parrot.metrics.matching import MetricMatcher
from parrot.metrics.models import MetricDefinition, MetricMatch
from parrot.metrics.store import MetricStore

_LOGGER = logging.getLogger(__name__)


class MetricView:
    """Read-only overlay of a tenant namespace over the global one (SkillView twin, tenancy.py:146)."""

    def __init__(self, global_defs: Sequence[MetricDefinition], tenant_defs: Sequence[MetricDefinition] = (),
                 *, tenant: str | None = None, logger: logging.Logger | None = None) -> None:
        self._global = list(global_defs)
        self._tenant_defs = list(tenant_defs)
        self.tenant = tenant
        self.logger = logger or _LOGGER
        self._by_id: dict[str, MetricDefinition] = {}
        self._ordered: list[MetricDefinition] = []
        self.report: dict[str, list[str]] = {"shadowed": [], "dropped": [], "alias_dropped": []}

    def compose(self) -> "MetricView":
        """C1 tenant shadows global by id; C2 alias collision (tenant wins, global alias dropped);
        C3 ``global_only`` global drops the tenant entry with a warning; C5/C6 single-namespace views."""
        # FILL IN: C5/C6 — no tenant defs → globals only; no globals → tenant only.
        # FILL IN: C3 — tenant def whose id equals a global_only global id → drop, warn, report["dropped"].
        # FILL IN: C1 — tenant def with same id replaces global (report["shadowed"]).
        # FILL IN: C2 — alias (casefolded) owned by a tenant def is removed from any surviving global def's
        #   aliases via model_copy(update={"aliases": [...]}) (report["alias_dropped"]); never mutate inputs.
        # Order: surviving globals in input order, then tenant defs in input order.
        return self

    def get(self, metric_id: str) -> MetricDefinition | None:
        return self._by_id.get(metric_id)

    def list(self, *, program: str | None = None) -> list[MetricDefinition]:
        return [d for d in self._ordered if program is None or d.program == program]

    def terms(self) -> dict[str, list[str]]:
        """``{metric_id: matching_terms()}`` — the matcher's bank."""
        return {d.id: d.matching_terms() for d in self._ordered}


class MetricRegistry:
    """List / describe / resolve metrics for one agent, tenant-aware."""

    def __init__(self, store: MetricStore, *, matcher: MetricMatcher | None = None, default_tenant: str | None = None,
                 visibility_filter: Callable[[MetricDefinition], bool] | None = None,
                 logger: logging.Logger | None = None) -> None:
        self.store = store
        self._matcher = matcher
        self.default_tenant = default_tenant
        self._visibility_filter = visibility_filter
        self.logger = logger or _LOGGER
        self._views: dict[str | None, MetricView] = {}
        self._bank_tenant: object = object()  # sentinel: no bank loaded yet

    async def view(self, tenant: str | None) -> MetricView:
        """Compose (and cache per tenant until ``invalidate``) the view for ``tenant``."""
        # FILL IN: cache hit → return; else globals = await store.list(tenant=None),
        #   tenant_defs = await store.list(tenant=tenant) if tenant else []; apply visibility_filter to both;
        #   MetricView(...).compose(); cache.
        raise NotImplementedError

    async def list(self, *, tenant: str | None = None, program: str | None = None) -> list[MetricDefinition]:
        return (await self.view(tenant or self.default_tenant)).list(program=program)

    async def describe(self, metric_id: str, *, tenant: str | None = None) -> MetricDefinition:
        """Raises ``MetricNotFound``."""
        found = (await self.view(tenant or self.default_tenant)).get(metric_id)
        if found is None:
            raise MetricNotFound(metric_id)
        return found

    async def resolve(self, question: str, *, tenant: str | None = None) -> MetricMatch | None:
        """Alias fast path, then embeddings; ``None`` below threshold. Never raises."""
        try:
            # FILL IN: view → lazily build MetricMatcher() when None; configure(view.terms()) when
            #   self._bank_tenant != effective tenant; hit = await asyncio.to_thread(matcher.match, question);
            #   None → None; else MetricMatch(metric=view.get(id), score, lane, ambiguous, tenant,
            #   requested_period=MetricMatcher.parse_period(question),
            #   requested_dimension=MetricMatcher.parse_dimension(question, metric.dimensions)).
            raise NotImplementedError
        except Exception as exc:  # a registry must never break a turn (spec §7)
            self.logger.warning("metric resolve failed for %r: %s", question, exc)
            return None

    def invalidate(self, tenant: str | None = None) -> None:
        """Drop the cached view (and its route bank) for one tenant, or all."""
        # FILL IN: pop one / clear all; reset self._bank_tenant to a fresh sentinel.
```
**Why this shape**: signatures are fixed by spec §3 M3. `asyncio` import is used by `resolve`. Replace every `raise NotImplementedError` inside FILL IN regions.

### FILL IN checklist
- [ ] `MetricView.compose` — C1/C2/C3/C5/C6; bounded by AC-3 and SkillView semantics
- [ ] `MetricRegistry.view` — cache + visibility filter
- [ ] `MetricRegistry.resolve` — to_thread, bank switch, never raises
- [ ] `MetricRegistry.invalidate`

---

## Acceptance Criteria

- [ ] C1/C2/C3/C5/C6 behave as described; inputs are never mutated.
- [ ] `describe` raises `MetricNotFound` for an unknown id.
- [ ] `resolve` returns a `MetricMatch` with `requested_period`/`requested_dimension` parsed; returns `None` (and logs) when the matcher raises.
- [ ] `ruff check packages/ai-parrot/src/parrot/metrics/registry.py` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/metrics/test_registry_view.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/metrics/test_registry_view.py
import pytest
from parrot.metrics.registry import MetricRegistry, MetricView
from parrot.metrics.store import InMemoryMetricStore
from parrot.metrics.errors import MetricNotFound

def test_metric_view_c1_shadow_by_id(worked_hours_def): ...          # tenant copy replaces global
def test_metric_view_c2_alias_collision_tenant_wins(worked_hours_def): ...
def test_metric_view_c3_global_only_drops_tenant(worked_hours_def): ...
def test_metric_view_c5_c6_single_namespace(worked_hours_def): ...
async def test_registry_describe_not_found(): ...
async def test_registry_resolve_alias(worked_hours_def): ...         # "hours worked this month" → match, this_month
async def test_registry_resolve_never_raises(worked_hours_def, monkeypatch): ...  # matcher.match raises → None
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug metric-definition-registry --feature-id FEAT-756`).
2. Check TASK-4844 and TASK-4846 are `done` in `sdd/tasks/index/metric-definition-registry.json`; re-verify their signatures above.
3. Mark in-progress, implement from the blueprint, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4847 metric-definition-registry verified`.

## Completion Note

