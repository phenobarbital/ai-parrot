# TASK-4843: Metric definition models, errors and lazy package exports

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Data Models" and §3 Module 1. Every other FEAT-756 task (store, loader,
importer, matcher, registry, toolkit, Postgres store, HTTP handler, routing mixin)
consumes the `MetricDefinition` family defined here. This task also creates the
`parrot.metrics` package `__init__.py` as a **lazy export map** covering every public
name of the package, so no later task ever edits `__init__.py` (avoids file-overlap
between parallel tasks).

---

## Scope

- Create `parrot/metrics/errors.py` with `MetricRegistryError`, `MetricNotFound`, `MetricSourceUnavailable`.
- Create `parrot/metrics/models.py` with every model of spec §2 Data Models: `MetricId`, `Visibility`,
  `Grain`, `PeriodPreset`, `DimensionSpec`, `PeriodBinding`, `TimeSpec`, `ComparisonPolicy`,
  `KPICardShape`, `ChartShape`, `DataTableShape`, `MapShape`, `ShapeSpec`, `QuerySlugSource`,
  `TransformerSource`, `RecipeSource`, `SemanticMetricSource`, `MetricSource`, `MetricDefinition`,
  `MetricMatch`, `ResolvedPeriod`, plus the four `MetricDefinition` methods of §3 M1.
- Create `parrot/metrics/__init__.py` as a lazy `__getattr__` map (name → (submodule, attr)).
- Create test `conftest.py` (fixtures `worked_hours_def`, `frozen_today`, `stub_encoder`) and `test_models.py`.

**NOT in scope**: stores, loaders, importers, matcher, registry, context ContextVars (TASK-4844..4847);
anything under `parrot_tools` or `ai-parrot-server`; executing a source.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/metrics/__init__.py` | CREATE | Lazy export map for the whole package |
| `packages/ai-parrot/src/parrot/metrics/errors.py` | CREATE | Three exceptions |
| `packages/ai-parrot/src/parrot/metrics/models.py` | CREATE | Pydantic v2 definition family |
| `packages/ai-parrot/tests/unit/metrics/conftest.py` | CREATE | Shared fixtures for parrot.metrics tests |
| `packages/ai-parrot/tests/unit/metrics/test_models.py` | CREATE | M1 unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.tenancy import validate_tenant_id   # verified: packages/ai-parrot/src/parrot/skills/tenancy.py:42
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator  # pydantic v2 (core dep)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/tenancy.py:42
def validate_tenant_id(value: str) -> str:   # raises ValueError on invalid / reserved (RESERVED_TENANT_NAMES L23)

# packages/ai-parrot/src/parrot/registry/routing/embedding_router.py:70-77 (used by the stub_encoder fixture only)
class EmbeddingIntentRouter:
    def __init__(self, model: str = "intfloat/multilingual-e5-small", threshold: float = 0.85,
                 margin: float = 0.05, *, encoder: Any | None = None) -> None
    # add_route (L116) calls enc.encode(texts, normalize_embeddings=True) (L131);
    # route_label_scores (L134) calls enc.encode([f"query: {query}"], normalize_embeddings=True) (L150)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py:15 — KPICARD_SCHEMA:
#   higherIsBetter accepts bool | null (tri-state); format ∈ {percent, currency, number}
```

### Does NOT Exist
- ~~`parrot.metrics` package~~ — net-new here. (`parrot/observability/` metrics are telemetry, unrelated.)
- ~~`MetricStore`, `InMemoryMetricStore`, `MetricRegistry`, `MetricView`, `MetricMatcher`, `load_metrics_yaml`, `import_kpi_table`, `resolve_metric_tenant`, `current_metric_match`~~ — created by TASK-4844..4847; only referenced lazily by `__init__.py` here.
- ~~Any import of `parrot.outputs.a2ui` or `parrot.tools` from `parrot.metrics`~~ — forbidden (spec §7: the registry must stay import-light for the router hook).
- ~~`RequestContext.tenant`~~ — tenant travels in `ctx.kwargs["tenant"]`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/metrics/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/metrics/errors.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/metrics/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/metrics/conftest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/metrics/test_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#validate_tenant_id",
    "sym:packages/ai-parrot/src/parrot/registry/routing/embedding_router.py#EmbeddingIntentRouter"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2, `ConfigDict(extra="forbid")` on every model — a YAML typo must fail loudly.
- `MetricDefinition.tenant` is the auth/namespace tenant; `QuerySlugSource.tenant` is the QuerySource store (routing). Say so in field descriptions (spec R6).
- `higher_is_better: bool | None = True` — tri-state preserved (`None` must survive `model_dump`).
- `SemanticMetricSource` parses and round-trips; execution is not this task's concern.
- Google-style docstrings, type hints everywhere, no `print`.

### References in Codebase
- `packages/ai-parrot/src/parrot/skills/tenancy.py` — tenant validation pattern.
- `packages/ai-parrot/src/parrot/bots/mixins/__init__.py:28-45` — `_LAZY_IMPORTS` + `__getattr__` idiom to copy.

---

## Implementation Blueprint

### Steps (in order)
1. Write `errors.py` — *why*: models do not need it, but `__init__` exports it and every later task raises these.
2. Write `models.py` from spec §2 verbatim, adding the validators listed below — *why*: the spec fixes every field; only validator bodies are judgement.
3. Write `__init__.py` lazy map — *why*: later tasks add modules without touching this file.
4. Write `conftest.py` and `test_models.py`; run the validation command.

### `packages/ai-parrot/src/parrot/metrics/errors.py` (CREATE)
```python
"""Errors raised by the metric definition registry (FEAT-756)."""
from __future__ import annotations


class MetricRegistryError(Exception):
    """Base error of the metric registry."""


class MetricNotFound(MetricRegistryError):
    """No definition with that id is visible to the caller."""


class MetricSourceUnavailable(MetricRegistryError):
    """The source kind is declared but cannot run here (e.g. ``semantic_metric``, FEAT-704)."""
```

### `packages/ai-parrot/src/parrot/metrics/models.py` (CREATE)
```python
"""Metric definition models (FEAT-756 §2). Pure Pydantic — no a2ui / tools imports."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.skills.tenancy import validate_tenant_id  # verified: skills/tenancy.py:42

MetricId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")]
Visibility = Literal["private", "tenant", "public"]
Grain = Literal["day", "week", "month", "quarter", "year"]
PeriodPreset = Literal["today", "yesterday", "this_week", "last_week", "this_month", "last_month", "mtd",
                       "qtd", "ytd", "last_7d", "last_30d", "last_90d", "this_year", "last_year"]
_STRICT = ConfigDict(extra="forbid")


class DimensionSpec(BaseModel):
    """A breakdown axis ("by cost center")."""
    model_config = _STRICT
    name: str
    column: str
    label: str | None = None
    aliases: list[str] = Field(default_factory=list)


class PeriodBinding(BaseModel):
    """How a resolved period reaches the source: two placeholders, or one date column for post-filtering."""
    model_config = _STRICT
    start_placeholder: str | None = None
    end_placeholder: str | None = None
    date_column: str | None = None

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> "PeriodBinding":
        # FILL IN: valid iff (start_placeholder AND end_placeholder set, date_column None)
        #          XOR (date_column set, both placeholders None); else raise ValueError — bounded by test_period_binding_exactly_one_mode
        return self

# FILL IN: TimeSpec, ComparisonPolicy, KPICardShape, ChartShape, DataTableShape, MapShape, ShapeSpec,
#          QuerySlugSource, TransformerSource, RecipeSource, SemanticMetricSource, MetricSource,
#          MetricMatch, ResolvedPeriod — copy field-for-field from spec §2 Data Models (lines 315-446);
#          every model gets model_config = _STRICT and a one-line docstring.


class MetricDefinition(BaseModel):
    """A tenant-scoped metric: vocabulary, semantics, default shape and executable source."""
    model_config = _STRICT
    # FILL IN: fields exactly as spec §2 (id … updated_at); tenant/QuerySlugSource.tenant descriptions per R6.

    @model_validator(mode="after")
    def _check(self) -> "MetricDefinition":
        # FILL IN: (a) tenant is not None → self.tenant = validate_tenant_id(self.tenant)
        #          (b) visibility == "public" and tenant is not None → ValueError
        #          (c) if source has non-empty `fields` (QuerySlugSource, or TransformerSource.input),
        #              KPICardShape.value_column / ChartShape.x+y must be in it → ValueError otherwise
        return self

    def matching_terms(self) -> list[str]:
        """Return ``[name] + aliases + example_phrases`` de-duplicated, lower-cased, order-preserving."""
        # FILL IN: strip + lower each term, skip empties, keep first occurrence order
        raise NotImplementedError

    def dimension(self, name_or_alias: str) -> DimensionSpec | None:
        """Return the dimension whose name or alias equals ``name_or_alias`` (case-insensitive), else ``None``."""
        # FILL IN: casefold comparison over d.name and d.aliases
        raise NotImplementedError

    def shadow_key(self) -> str:
        """Return ``self.id`` — the key a tenant definition shadows a global one by (``SkillView`` C1)."""
        return self.id

    @classmethod
    def json_schema_v1(cls) -> dict[str, Any]:
        """Return the JSON Schema served by ``GET /api/v1/metrics/schema`` and written to docs."""
        return cls.model_json_schema()
```
**Why this shape**: spec §2 fixes every field and discriminator (`source.kind`, `default_shape.component`);
the validators are the only logic. `date`/`datetime` are needed by `ResolvedPeriod` / timestamps. Do not
import anything from `parrot.outputs` or `parrot.tools`.

### `packages/ai-parrot/src/parrot/metrics/__init__.py` (CREATE)
```python
"""Metric definition registry (FEAT-756): tenant-scoped KPIs with a declared default shape.

Exports are lazy so importing ``parrot.metrics`` stays cheap and so sibling modules can be added
without editing this file.
"""
from __future__ import annotations

import importlib
from typing import Any

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "MetricRegistryError": (".errors", "MetricRegistryError"),
    "MetricNotFound": (".errors", "MetricNotFound"),
    "MetricSourceUnavailable": (".errors", "MetricSourceUnavailable"),
    "MetricDefinition": (".models", "MetricDefinition"),
    "MetricMatch": (".models", "MetricMatch"),
    "MetricSource": (".models", "MetricSource"),
    "ShapeSpec": (".models", "ShapeSpec"),
    "ResolvedPeriod": (".models", "ResolvedPeriod"),
    "MetricStore": (".store", "MetricStore"),
    "InMemoryMetricStore": (".store", "InMemoryMetricStore"),
    "MetricsYamlReport": (".loader", "MetricsYamlReport"),
    "load_metrics_yaml": (".loader", "load_metrics_yaml"),
    "load_agent_metrics": (".loader", "load_agent_metrics"),
    "seed_store": (".loader", "seed_store"),
    "KpiTableRow": (".importers", "KpiTableRow"),
    "parse_kpi_table": (".importers", "parse_kpi_table"),
    "import_kpi_table": (".importers", "import_kpi_table"),
    "MetricMatcher": (".matching", "MetricMatcher"),
    "MetricRegistry": (".registry", "MetricRegistry"),
    "MetricView": (".registry", "MetricView"),
    "resolve_metric_tenant": (".context", "resolve_metric_tenant"),
    "current_metric_match": (".context", "current_metric_match"),
    "bind_metric_match": (".context", "bind_metric_match"),
    "reset_metric_match": (".context", "reset_metric_match"),
}

__all__ = sorted(_LAZY_IMPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr = _LAZY_IMPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(importlib.import_module(module_name, __name__), attr)
    globals()[name] = value
    return value
```
**Why**: later tasks (TASK-4844..4847) create `store`, `loader`, `importers`, `matching`, `registry`,
`context`; names resolve on first access. `MetricSuggestionProvider` is NOT exported here (spec: imported
from `parrot.metrics.suggestions`).

### `packages/ai-parrot/tests/unit/metrics/conftest.py` (CREATE)
```python
"""Shared fixtures for parrot.metrics tests (FEAT-756)."""
from __future__ import annotations

import re
from datetime import date

import numpy as np
import pytest

from parrot.metrics.models import MetricDefinition


@pytest.fixture
def frozen_today() -> date:
    return date(2026, 10, 27)


@pytest.fixture
def worked_hours_def() -> MetricDefinition:
    """query_slug KPI: slug 'flex_hours', placeholders firstdate/lastdate, dimensions cost_center/pay_code,
    higher_is_better=None, default_shape KPICardShape(value_column='hours', aggregate='sum')."""
    return MetricDefinition.model_validate({
        "id": "worked_hours", "name": "Worked Hours",
        "aliases": ["hours worked", "horas trabajadas", "worked hrs"],
        "example_phrases": ["show me worked hours this month", "cuántas horas trabajamos este mes"],
        "unit": "h", "format": "number", "higher_is_better": None, "program": "flex",
        "dimensions": [{"name": "cost center", "column": "cost_center", "aliases": ["cc"]},
                       {"name": "pay code", "column": "pay_code"}],
        "time": {"grain": "month", "default_period": "this_month", "series_grain": "day",
                 "binding": {"start_placeholder": "firstdate", "end_placeholder": "lastdate"}},
        "comparison": {"mode": "previous_period"},
        "default_shape": {"component": "KPICard", "value_column": "hours", "aggregate": "sum"},
        "source": {"kind": "query_slug", "slug": "flex_hours"},
    })


class _BagOfWordsEncoder:
    """Deterministic encoder: hashed bag of words, L2-normalised. Strips e5 'query: '/'passage: ' prefixes."""

    dim = 256

    def encode(self, texts, normalize_embeddings: bool = True):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            text = re.sub(r"^(query|passage):\s*", "", text.lower())
            for tok in re.findall(r"\w+", text):
                out[i, hash(tok) % self.dim] += 1.0
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


@pytest.fixture
def stub_encoder() -> _BagOfWordsEncoder:
    """Pass as ``EmbeddingIntentRouter(..., encoder=stub_encoder)`` — no model download."""
    return _BagOfWordsEncoder()
```
**Why**: `EmbeddingIntentRouter` accepts `encoder=` (embedding_router.py:70-77), so no monkeypatching is
needed. `hash()` of str is salted per process but stable within one run — fine for a fixture.

### `packages/ai-parrot/tests/unit/metrics/test_models.py` (CREATE)
See Test Specification below.

### FILL IN checklist
- [ ] `models.py` — remaining 14 models copied from spec §2 field-for-field
- [ ] `PeriodBinding._exactly_one_mode` — XOR rule
- [ ] `MetricDefinition._check` — tenant validation, public-with-tenant rejection, fields membership
- [ ] `MetricDefinition.matching_terms` / `.dimension` bodies
- [ ] `test_models.py` bodies

---

## Acceptance Criteria

- [ ] `MetricDefinition` round-trips JSON/YAML dict → model → `model_dump(mode="json")` → model, with discriminated `source` and `default_shape`.
- [ ] `visibility="public"` + tenant → `ValidationError`; invalid tenant id → `ValidationError`.
- [ ] `higher_is_better` tri-state preserved; default `True`.
- [ ] `SemanticMetricSource` parses and round-trips.
- [ ] `PeriodBinding` enforces placeholders-pair XOR `date_column`.
- [ ] `import parrot.metrics` does not import `parrot.outputs` or `parrot.tools` (assert via `sys.modules` in a subprocess-free check: names absent after importing `parrot.metrics.models` in a fresh interpreter is optional; at minimum grep-clean).
- [ ] `parrot.metrics.MetricDefinition` resolves through the lazy map; unknown attr → `AttributeError`.
- [ ] `ruff check packages/ai-parrot/src/parrot/metrics` clean.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/metrics/test_models.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/metrics/test_models.py
import pytest
from pydantic import ValidationError

import parrot.metrics as pm
from parrot.metrics.models import KPICardShape, MetricDefinition, PeriodBinding, SemanticMetricSource


def test_metric_definition_roundtrip(worked_hours_def):
    dumped = worked_hours_def.model_dump(mode="json")
    again = MetricDefinition.model_validate(dumped)
    assert again == worked_hours_def
    assert isinstance(again.default_shape, KPICardShape)
    assert again.source.kind == "query_slug"


def test_metric_definition_rejects_public_tenant(worked_hours_def):
    data = worked_hours_def.model_dump(mode="json") | {"tenant": "acme", "visibility": "public"}
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(data)


def test_higher_is_better_tristate(worked_hours_def): ...          # FILL IN: True default, False, None preserved

def test_semantic_metric_parses(worked_hours_def): ...             # FILL IN: source={"kind":"semantic_metric",...}

def test_period_binding_exactly_one_mode(): ...                    # FILL IN: both / neither / half-pair → ValidationError

def test_extra_field_forbidden(worked_hours_def): ...              # FILL IN: unknown key → ValidationError

def test_matching_terms_and_dimension(worked_hours_def): ...       # FILL IN: lower/dedupe; dimension("CC") → cost center

def test_lazy_exports():
    assert pm.MetricDefinition is MetricDefinition
    with pytest.raises(AttributeError):
        pm.DoesNotExist  # noqa: B018
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug metric-definition-registry --feature-id FEAT-756`).
2. Read the spec (§2 Data Models, §3 M1, §7).
3. Verify the Codebase Contract; update it first if anything moved.
4. Mark `in-progress` in `sdd/tasks/index/metric-definition-registry.json`, commit only the index.
5. Implement from the blueprint; complete every `FILL IN`.
6. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. Commit only the files listed; close with `scripts/sdd/close_task.sh TASK-4843 metric-definition-registry verified`.

---

## Completion Note

*(Agent fills this in when done)*
