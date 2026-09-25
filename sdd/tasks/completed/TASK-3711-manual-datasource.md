# TASK-3711: ManualCardDataSource (manualcard ExtractDataSource) (M8)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3702
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 8** (datasource half). `ManualCardDataSource` is the `manualcard`
`ExtractDataSource` that projects catalog cards into per-entity plain-dict records — the
`source: manualcard` declared by every owned entity in `procedures.ontology.yaml` (TASK-3701).
The graph loader (TASK-3712) calls `snapshot()` and derives edges from these records, so the
record shapes defined here are the loader's input contract. Copies
`contracts/datasource.py` (routing order, fail-loud extraction, import-time `register()`).

Parallelism: `config["catalog"]` is a ManualCatalogStore and tests use InMemoryManualCatalog
from TASK-3702 (manuals/catalog.py, tests/knowledge/_support/catalog.py).

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/manuals/datasource.py` with `SOURCE_NAME`,
  `ENTITY_FIELDS`, `ENTITY_ROUTING_ORDER`, `UnknownFieldRequest`, `ManualCardDataSource`,
  `register()` (called at import) per spec §3 M8.
- Entities: `Equipment`, `Manual`, `Procedure`, `Step`, `Part`, `Tool`, `Hazard`, `Media`
  (the eight owned vertex collections). **No `Tip`** — tips are technician-owned and never
  projected (U3).
- Routing order (most specific key first, fixed):
  `step_id → Step, media_id → Media, hazard_id → Hazard, part_id → Part, tool_id → Tool,
  procedure_id → Procedure, equipment_id → Equipment, manual_id → Manual`.
- Records carry the ontology properties (spec §3 M3 YAML) **plus** the relational fields the
  loader needs to build edges (fixed names below).
- Only the **current** `ManualVersion` / active procedures are projected unless
  `config["include_inactive"]` is true; bitemporal history stays in `versions` (list property).
- Write `packages/ai-parrot/tests/knowledge/manuals/test_datasource.py`
  (`test_datasource_routing_order` + projection tests).

**NOT in scope**: edge derivation (TASK-3712 `desired_edges`), graph writes, tips, catalog
implementation (TASK-3702/3703).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/datasource.py` | CREATE | `manualcard` ExtractDataSource |
| `packages/ai-parrot/tests/knowledge/manuals/test_datasource.py` | CREATE | routing, projection, registration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# optional satellite — same try/except as packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py:27-41
from parrot_loaders.extractors.base import ExtractDataSource, ExtractedRecord, ExtractionResult  # verified: packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py:18, 30, 50
from parrot_loaders.extractors.factory import DataSourceFactory  # verified: packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py:13 (register_api_source :35)
# Created by TASK-3702 (packages/ai-parrot/src/parrot/knowledge/manuals/catalog.py):
from parrot.knowledge.manuals.catalog import ManualCatalogStore
# Created by TASK-3699 (packages/ai-parrot/src/parrot/knowledge/manuals/models.py):
from parrot.knowledge.manuals.models import ManualCard
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py
class ExtractedRecord(BaseModel): data: dict[str, Any]; metadata: dict[str, Any]                   # :18
class ExtractionResult(BaseModel): records; total: int; errors; warnings; source_name: str; extracted_at: datetime  # :30
class ExtractDataSource(ABC):                                                                        # :50
    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None                     # :62 — sets self.name/self.config/self.logger
    @abstractmethod async def extract(self, fields=None, filters=None) -> ExtractionResult          # :70
    @abstractmethod async def list_fields(self) -> list[str]                                         # :91

# packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py:35
@classmethod def register_api_source(cls, name: str, source_cls: type[ExtractDataSource]) -> None

# Pattern to copy — packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py
SOURCE_NAME = "contractcard"                                   # :55
ENTITY_ROUTING_ORDER: tuple[tuple[str, str], ...]              # :58
class UnknownFieldRequest(ValueError)                          # :117
class ContractCardDataSource(ExtractDataSource):               # :130
    def __init__(self, name=SOURCE_NAME, config=None)          # :144 — RuntimeError without loaders; ValueError unless config["catalog"] isinstance store
    @staticmethod def infer_entity(fields) -> str              # :162
    async def records_for(self, entity, *, filters=None)       # :348
    async def snapshot(self, *, filters=None)                  # :380
    async def extract(self, fields=None, filters=None)         # :405 — failures propagate (never empty-on-error)
def register() -> None                                         # :447 — idempotent, no-op without loaders; called at import :455
```

### Does NOT Exist
- ~~`parrot.knowledge.manuals.datasource`~~ — this task creates it.
- ~~A `Tip` / `tech_tip` projection in any datasource~~ — technician collections have no `source:` (spec M3).
- ~~Importing `parrot.knowledge.contracts.datasource` from manuals~~ — copy the pattern, never import contracts.
- ~~`ExtractDataSource.snapshot`~~ — `snapshot()` is our own method, not on the ABC.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/datasource.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_datasource.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py#ExtractDataSource",
    "sym:packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py#ExtractedRecord",
    "sym:packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py#ExtractionResult",
    "sym:packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py#DataSourceFactory.register_api_source"
  ]
}
```

---

## Implementation Notes

### Record shapes (fixed — TASK-3712 consumes them)
| Entity | Ontology properties | Relational fields for edges |
|---|---|---|
| `Manual` | `manual_id, revision, source_sha256, active, versions` | `procedure_ids: list[str]` |
| `Equipment` | `equipment_id, model, family, revision, aliases` | — |
| `Procedure` | `procedure_id, kind, title, estimated_minutes, skill_level, active, verification, versions, manual_id` | `equipment_ids: list[str]`, `step_ids: list[{"step_id", "order"}]`, `overview_media_ids: list[str]`, `supersedes: str\|None` |
| `Step` | `step_id, order, source_identity, content_hash, text, torque, duration_minutes, applies_models, applies_serial_ranges, node_id, page, active, procedure_id` | `parts: list[{"part_id","quantity","context"}]`, `tool_ids`, `hazard_ids`, `media: list[{"media_id","role","confidence","origin"}]`, `precedes: list[{"step_id","kind"}]` |
| `Part` / `Tool` / `Hazard` | `part_id, part_number, name` / `tool_id, name, spec` / `hazard_id, severity, text` | — |
| `Media` | `media_id, kind, storage_key, uri, page, caption, label, t_start, t_end, origin` | `callouts: list[{"part_id","callout","confidence","origin"}]` |

`Extracted[...]` values are flattened to `.value`; `node_id`/`page` on Step come from
`step.text.evidence`. Dates/datetimes serialize ISO (`_iso` helper as contracts `:121`).
`precedes` holds the **next** step by order (`kind="order"`) plus evidence-backed
`cross_refs` resolved by `assemble_card` (`kind="explicit"`) — read what TASK-3708 stored; if
it only stores literal phrases, emit order edges only and note it.

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest …`.
- Ontology imports (if any) from submodules only (AC17); none are needed here.
- No new dependency. Google docstrings, type hints, Pydantic v2, `logger` — no `print`.
- Deterministic ordering: sort records by key so the loader's diff is stable.
- Shared `Part`/`Tool`/`Hazard` across procedures dedupe by id (FEAT-539 lesson: dedup by `_key`).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py:130-455` — the whole pattern.

---

## Implementation Blueprint

### Steps (in order)
1. Copy the optional-import block and `register()` from contracts — *why*: core must import without the loaders satellite (spec Integration Points).
2. Declare `ENTITY_FIELDS` from the table above and `ENTITY_ROUTING_ORDER` verbatim from the spec — *why*: `step_id` must win over `manual_id` since Step records carry `procedure_id` (and routing is by key marker).
3. Implement one `_<entity>_records(cards)` projector per entity — *why*: TASK-3712 reads these exact keys.
4. Implement `records_for`, `snapshot` (all eight entities), `extract`, `list_fields` — *why*: `snapshot` is the loader preflight; `extract` is the refresh-pipeline entry.
5. Write tests with `InMemoryManualCatalog` — *why*: AC19 runs without Postgres.

### `packages/ai-parrot/src/parrot/knowledge/manuals/datasource.py` (CREATE)
```python
"""``manualcard`` ontology datasource: catalog cards → per-entity records (FEAT-601 M8)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from .catalog import ManualCatalogStore
from .models import ManualCard

try:  # pragma: no cover - satellite package is an optional dependency
    from parrot_loaders.extractors.base import ExtractDataSource, ExtractedRecord, ExtractionResult
    from parrot_loaders.extractors.factory import DataSourceFactory

    _LOADERS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the satellite
    _LOADERS_AVAILABLE = False
    ExtractDataSource = object  # type: ignore[assignment,misc]
    ExtractedRecord = None  # type: ignore[assignment]
    ExtractionResult = None  # type: ignore[assignment]
    DataSourceFactory = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

SOURCE_NAME = "manualcard"
ENTITIES: tuple[str, ...] = ("Equipment", "Manual", "Procedure", "Step", "Part", "Tool", "Hazard", "Media")
ENTITY_ROUTING_ORDER: tuple[tuple[str, str], ...] = (
    ("step_id", "Step"), ("media_id", "Media"), ("hazard_id", "Hazard"), ("part_id", "Part"),
    ("tool_id", "Tool"), ("procedure_id", "Procedure"), ("equipment_id", "Equipment"), ("manual_id", "Manual"),
)
ENTITY_FIELDS: dict[str, frozenset[str]] = {
    # FILL IN: one frozenset per entity = ontology properties + relational fields (table in Implementation Notes)
}


class UnknownFieldRequest(ValueError):
    """A field request that no manuals entity owns, or an ambiguous mix of two."""


def _iso(value: Any) -> Any:
    """Serialize dates/datetimes to ISO strings; pass everything else through."""
    return value.isoformat() if isinstance(value, (date, datetime)) else value


class ManualCardDataSource(ExtractDataSource):  # type: ignore[misc]
    """Project the manual catalog into ontology entity records."""

    def __init__(self, name: str = SOURCE_NAME, config: Optional[dict[str, Any]] = None) -> None:
        if not _LOADERS_AVAILABLE:  # pragma: no cover - depends on install extras
            raise RuntimeError("The manuals ontology datasource requires ai-parrot-loaders (pip install ai-parrot-loaders).")
        super().__init__(name=name, config=config or {})
        catalog = self.config.get("catalog")
        if not isinstance(catalog, ManualCatalogStore):
            raise ValueError("ManualCardDataSource requires a tenant-bound ManualCatalogStore under config['catalog'].")
        self.catalog: ManualCatalogStore = catalog
        self.include_inactive: bool = bool(self.config.get("include_inactive", False))

    def infer_entity(self, fields: Optional[list[str]]) -> str:
        """Route a field request to an entity by the first key marker in ENTITY_ROUTING_ORDER."""
        # FILL IN: copy contracts/datasource.py:162-194 semantics; None/empty ⇒ "Manual"
        raise NotImplementedError

    async def _cards(self, filters: Optional[dict[str, Any]] = None) -> list[ManualCard]:
        """Active cards (all when include_inactive), filtered by manual_id when given."""
        # FILL IN: catalog.list_cards(active_only=not self.include_inactive); unknown filter keys ⇒ UnknownFieldRequest
        raise NotImplementedError

    # FILL IN: _manual_records / _equipment_records / _procedure_records / _step_records /
    #          _part_records / _tool_records / _hazard_records / _media_records — sorted, deduped by id

    async def records_for(self, entity: str, *, filters: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        """Project one entity's records; unknown entity ⇒ UnknownFieldRequest."""
        raise NotImplementedError

    async def snapshot(self, *, filters: Optional[dict[str, Any]] = None) -> dict[str, list[dict[str, Any]]]:
        """Complete snapshot of all eight entities (the loader preflights this before any write)."""
        return {entity: await self.records_for(entity, filters=filters) for entity in ENTITIES}

    async def extract(self, fields: list[str] | None = None, filters: dict[str, Any] | None = None) -> "ExtractionResult":
        """ExtractDataSource entry: failures propagate — an empty result must never mean 'catalog unreachable'."""
        entity = self.infer_entity(fields)
        records = await self.records_for(entity, filters=filters)
        requested = set(fields or [])
        payloads = [{k: v for k, v in r.items() if not requested or k in requested} for r in records]
        return ExtractionResult(
            records=[ExtractedRecord(data=p, metadata={"entity": entity, "source": self.name}) for p in payloads],
            total=len(payloads), source_name=self.name, extracted_at=datetime.now(tz=timezone.utc),
        )

    async def list_fields(self) -> list[str]:
        """Every field any manuals entity can supply."""
        return sorted({f for fields in ENTITY_FIELDS.values() for f in fields})


def register() -> None:
    """Register under ``manualcard``; idempotent, no-op without ai-parrot-loaders."""
    if not _LOADERS_AVAILABLE:  # pragma: no cover
        logger.debug("ai-parrot-loaders is not installed; manualcard not registered")
        return
    DataSourceFactory.register_api_source(SOURCE_NAME, ManualCardDataSource)


register()
```
**Why this shape**: the spec skeleton makes `infer_entity` an instance method (contracts has a
staticmethod) — keep the spec signature. Fail-loud `extract` is what stops the generic diff from
soft-deleting the whole graph on a catalog outage.

### `packages/ai-parrot/tests/knowledge/manuals/test_datasource.py` (CREATE)
```python
"""ManualCardDataSource routing and projection (FEAT-601 M8)."""
from __future__ import annotations

import pytest

pytest.importorskip("parrot_loaders")

from parrot.knowledge.manuals.datasource import (  # noqa: E402
    ENTITY_ROUTING_ORDER, SOURCE_NAME, ManualCardDataSource, UnknownFieldRequest,
)

from .._support.catalog import InMemoryManualCatalog  # created by TASK-3702  # noqa: E402


def test_datasource_routing_order() -> None:
    """step_id routes to Step before manual_id; unknown field ⇒ UnknownFieldRequest."""
    # FILL IN


@pytest.mark.asyncio
async def test_snapshot_projects_all_entities_without_tips() -> None:
    """Eight entities, deterministic order, no Tip key, Extracted flattened to .value."""


@pytest.mark.asyncio
async def test_step_records_carry_edge_fields() -> None:
    """parts/tool_ids/hazard_ids/media/precedes present with the fixed shapes."""


def test_requires_manual_catalog() -> None:
    """config without a ManualCatalogStore ⇒ ValueError."""


def test_registered_under_manualcard() -> None:
    """DataSourceFactory._api_registry[SOURCE_NAME] is ManualCardDataSource."""
```

### FILL IN checklist
- [ ] `ENTITY_FIELDS` — exactly the table; bounded by TASK-3701 YAML property names
- [ ] `infer_entity` — routing order + ambiguity refusal
- [ ] `_cards` — active/inactive + filter validation
- [ ] eight projectors — sorted, deduped, ISO dates, no Tip
- [ ] tests incl. a card fixture built from TASK-3699 models

---

## Acceptance Criteria

- [ ] `test_datasource_routing_order` passes (spec §4 M8).
- [ ] `snapshot()` returns the eight owned entities only; no tip data.
- [ ] Extraction errors propagate (never an empty success).
- [ ] `register()` runs at import and is a no-op without `parrot_loaders`.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/manuals/datasource.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_datasource.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_datasource.py
def test_datasource_routing_order(): ...                          # spec §4 M8
async def test_snapshot_projects_all_entities_without_tips(): ...
async def test_step_records_carry_edge_fields(): ...
def test_requires_manual_catalog(): ...
def test_registered_under_manualcard(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3711-manual-datasource.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note


- Task: TASK-3711
- Feature: training-agent
- Implementation SHA: 808ddbab234992cfec13bcd30488c0203aa9afac
- Closed at (UTC): 2026-09-25T13:54:47+00:00
- Fix commits: 3d40163dd675064cb993f04ff18691760d8cb7e9

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 250.6s · Tokens: n/a |
| supplementary_test_evidence | 127 passed, 1 skipped, 0 failed (scoped direct pytest over knowledge/manuals/ + contracts/test_ontology_domain.py, after fix commit 3d40163dd) |
