# TASK-3702: ManualCatalogStore ABC + in-memory double (M4)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3699
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4**. Postgres is the authoritative store for manual cards (the graph is a projection, as in contracts).
This task defines the **cut-down** tenant-bound protocol — cards, versions, search, equipment resolution, verification
queue, answer audit, publication outbox; no parties, deltas or relations — plus a complete deterministic in-memory double
that every later suite (datasource, graph loader, library, retrieval) runs on. `PostgresManualCatalog` (TASK-3703)
implements the same ABC.

Parallelism: ABC signatures take `ManualCard`/`ManualVersion`/`VerificationState` from TASK-3699 (manuals/models.py).

---

## Scope

- Create `parrot/knowledge/manuals/catalog.py`: errors, `validate_identifier`, `VerificationReason`, `SearchHit`,
  `PublicationRecord`, `UpsertResult`, `VerificationQueueEntry`, `AnswerRecord`, pure `queue_entries_for(card)`,
  concrete shared `rank_equipment(...)`, and `ManualCatalogStore(ABC)`.
- Create `tests/knowledge/_support/catalog.py`: `InMemoryManualCatalog(ManualCatalogStore)`.
- Write `tests/knowledge/manuals/test_catalog_contract.py` (ABC contract suite run on the double).

**NOT in scope**: Postgres DDL/SQL (TASK-3703); graph publication (TASK-3712); typed `ProcedureCitation` in
`AnswerRecord` (would need TASK-3700 — citations are stored as JSON dicts here). Do not edit `manuals/__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/catalog.py` | CREATE | Protocol, result models, queue derivation, equipment ranking |
| `packages/ai-parrot/tests/knowledge/_support/catalog.py` | CREATE | `InMemoryManualCatalog` double |
| `packages/ai-parrot/tests/knowledge/manuals/test_catalog_contract.py` | CREATE | ABC contract suite over the double |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from abc import ABC, abstractmethod
import re, logging
from datetime import datetime
from typing import Any, Literal, Optional, Sequence
from pydantic import BaseModel, Field
from parrot.knowledge.manuals.models import (ManualCard, ManualVersion, EquipmentRef, ProcedureAnswerKind,
                                             manual_snapshot_payload)          # TASK-3699
from parrot.knowledge.common.provenance import VerificationState               # TASK-3697
# rapidfuzz is imported lazily inside rank_equipment (declared only in the graphindex extra — do not import at module top)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py  (shape to copy — never import contracts from manuals)
class CatalogError(RuntimeError) :91; class CatalogConflictError(CatalogError) :95 (contract_id, expected, actual);
class DuplicateSourceError(CatalogError) :111 (source_sha256/source_uri kwargs)
VerificationReason = Literal[...]  :181;  _QUEUE_ORDER: dict[str, int] :185
class SearchHit(BaseModel): card; rank: float = 0.0                         # :188-192
class UpsertResult(BaseModel): contract_id; revision ge=1; created; version_n ge=1; queued: list[PublicationRecord]   # :195-210
class VerificationQueueEntry(BaseModel): card; reason; fields; @property priority   # :213-223
SQL_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$") :263; def validate_sql_identifier(value, *, what="identifier") -> str :266-284
class ContractCatalogStore(ABC):  # :292; __init__(*, tenant_id, schema="contracts", principal=None) :308-319 (rejects empty tenant, validates schema);
    # properties tenant_id/schema/principal :321-334; upsert(card, *, expected_revision=None, version=None, targets=…) :339-363;
    # get :366; find_by_sha :370; find_by_source_uri :375; list_cards :379; search(query, top_k=8) :398; verification_queue(*, limit=50) :430;
    # record_answer :528; get_answer :537; enqueue_publication :631; pending_publications :635; claim_publication :644;
    # complete_publication :657; fail_publication :666; setup :677; close :681
# packages/ai-parrot/src/parrot/knowledge/contracts/models.py
class AnswerRecord(BaseModel)       # :830-858 (answer_id, asked_at, user, question, answer_kind, pattern, answer, citations, authorization, retired_*)
class PublicationRecord(BaseModel)  # :861-893 (tenant_id, contract_id, version_n, revision, target, run_id, payload, state, receipt, attempts, last_error, created_at, updated_at; @property key)
# packages/ai-parrot/src/parrot/knowledge/contracts/carding.py
def similarity(left: str, right: str) -> float   # :868-892 rapidfuzz.fuzz.token_sort_ratio / 100; RuntimeError with install hint
# packages/ai-parrot/tests/knowledge/contracts/test_catalog_contract.py
class InMemoryContractCatalog(ContractCatalogStore)   # :66-… double to mirror (optimistic revisions, immutable history, outbox); suite tests :654+
```

### Does NOT Exist
- ~~Parties, source deltas, relation judgements, obligations windows~~ in the manuals catalog — deliberately cut (spec M4).
- ~~`ManualCatalogStore.resolve_equipment` backed by SQL~~ — it is a concrete, deterministic method over `list_cards()` using `rank_equipment` (both backends share it).
- ~~A `"callout"` verification reason~~ — unresolved callouts are reported under `"unpaired_figure"` with item `"<media_id>#<label>"`.
- ~~Importing `parrot.knowledge.contracts.*`~~ from manuals — copy shapes instead.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/catalog.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/_support/catalog.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_catalog_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py#ContractCatalogStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py#validate_sql_identifier",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#AnswerRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#PublicationRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/carding.py#similarity"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Tenant-bound**: `tenant_id` fixed at construction, never an argument (copy contracts :308-319). `schema` and
  `search_regconfig` are both validated with `validate_identifier` (`^[a-z_][a-z0-9_]{0,62}$`) because TASK-3703 interpolates them into DDL.
- **Optimistic revisions**: `upsert(expected_revision=n)` raises `CatalogConflictError` when stale; a different manual owning the same
  `source_sha256` or `source_uri` raises `DuplicateSourceError`. Every upsert appends a `ManualVersion` (given or derived:
  `n = len(versions)+1`, `revision=card.revision`, `card_snapshot=manual_snapshot_payload(card)`) and enqueues one `ontology`
  `PublicationRecord` in the same logical write.
- **Queue** (`queue_entries_for`, pure, priority order): `missing_evidence` (a `field_provenance` entry with blank quote and
  `origin=="llm"`) → `low_confidence_step` (step `text.confidence < 0.6`) → `unpaired_figure` (step `figure_refs` label with no
  `card.figures` media of that label, plus media `unresolved_callouts`) → `orphaned_tip` (never derived from the card; produced by
  relink reports — keep the literal for TASK-3713) → `stale` (`card.verification == "stale"`). Ties break on `manual_id`.
- **Search** (double): case-insensitive token match over manual id, procedure titles, equipment models/aliases and figure captions;
  `matched` says which field won. The Postgres backend does real FTS.
- `rank_equipment(query, equipment, *, limit)` — exact alias/model match scores 1.0; otherwise lazily-imported
  `rapidfuzz.fuzz.token_sort_ratio/100`; `RuntimeError("…pip install 'ai-parrot[graphindex]'")` when rapidfuzz is missing (copy
  contracts `similarity` :868-892 wording). Deterministic ordering: score desc, then `equipment_id`.
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`.

---

## Implementation Blueprint

### Steps (in order)
1. Write errors, identifier validation and result models — *why*: both backends and the library raise/return them.
2. Write `queue_entries_for` and `rank_equipment` as pure functions — *why*: one implementation shared by both backends (no drift).
3. Write the ABC — *why*: TASK-3703 and the double implement it; later tasks type against it.
4. Write the in-memory double and the contract suite.

### `packages/ai-parrot/src/parrot/knowledge/manuals/catalog.py` (CREATE)
```python
"""Authoritative, tenant-bound manual catalog protocol (FEAT-601 M4)."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.common.provenance import VerificationState
from parrot.knowledge.manuals.models import EquipmentRef, ManualCard, ManualVersion, ProcedureAnswerKind

logger = logging.getLogger(__name__)

IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
VerificationReason = Literal["missing_evidence", "low_confidence_step", "unpaired_figure", "orphaned_tip", "stale"]
_QUEUE_ORDER: dict[str, int] = {"missing_evidence": 0, "low_confidence_step": 1, "unpaired_figure": 2, "orphaned_tip": 3, "stale": 4}
LOW_CONFIDENCE_STEP = 0.6
PublicationTarget = Literal["ontology"]
PublicationState = Literal["pending", "in_flight", "published", "failed"]


class CatalogError(RuntimeError):
    """Base error of the manual catalog."""


class CatalogConflictError(CatalogError):
    """``expected_revision`` did not match the stored revision."""
    # FILL IN: __init__(manual_id, expected, actual) storing attrs + message (contracts :102-108)


class DuplicateSourceError(CatalogError):
    """The source sha256 or URI already belongs to another manual."""


class UnknownManualError(CatalogError):
    """No card with this manual_id."""


def validate_identifier(value: str, *, what: str = "identifier") -> str:
    """Validate a configured SQL identifier (schema / regconfig) before interpolation."""
    # FILL IN: copy contracts validate_sql_identifier :266-284 semantics against IDENTIFIER_RE


class PublicationRecord(BaseModel):
    tenant_id: str = Field(..., min_length=1); manual_id: str = Field(..., min_length=1)
    version_n: int = Field(default=1, ge=1); revision: int = Field(default=1, ge=1); target: PublicationTarget = "ontology"
    run_id: str = Field(..., min_length=1); payload: dict[str, Any] = Field(default_factory=dict)
    state: PublicationState = "pending"; receipt: Optional[str] = None; attempts: int = Field(default=0, ge=0)
    last_error: Optional[str] = None; created_at: Optional[datetime] = None; updated_at: Optional[datetime] = None

    @property
    def key(self) -> tuple[str, str, int, int, str]:
        return (self.tenant_id, self.manual_id, self.version_n, self.revision, self.target)


class SearchHit(BaseModel):
    card: ManualCard; rank: float = 0.0; matched: Literal["manual", "procedure", "equipment", "caption"] = "manual"


class UpsertResult(BaseModel):
    manual_id: str; revision: int = Field(..., ge=1); created: bool = False; version_n: int = Field(default=1, ge=1)
    queued: list[PublicationRecord] = Field(default_factory=list)


class VerificationQueueEntry(BaseModel):
    card: ManualCard; reason: VerificationReason; items: list[str] = Field(default_factory=list)

    @property
    def priority(self) -> int:
        return _QUEUE_ORDER[self.reason]


class AnswerRecord(BaseModel):
    """One audited answer, written BEFORE release (blocked answers too)."""
    answer_id: str = Field(..., min_length=1); asked_at: datetime; user: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1); answer_kind: ProcedureAnswerKind; pattern: Optional[str] = None
    manual_id: Optional[str] = None; manual_revision: Optional[str] = None
    citations: list[dict[str, Any]] = Field(default_factory=list)   # ProcedureCitation.model_dump(mode="json")
    allowed: bool = True; reason: Optional[str] = None; blocked_reason: Optional[str] = None


def queue_entries_for(card: ManualCard) -> list[VerificationQueueEntry]:
    """Derive this card's verification-queue entries (pure; see Implementation Notes for the rules)."""
    # FILL IN: rules in priority order; one entry per reason with its items (field paths / step_ids / media#label)


def rank_equipment(query: str, equipment: Sequence[EquipmentRef], *, limit: int = 5) -> list[tuple[EquipmentRef, float]]:
    """Deterministic equipment resolution over models + aliases (rapidfuzz imported lazily)."""
    # FILL IN: exact casefold match ⇒ 1.0; else token_sort_ratio/100; sort (-score, equipment_id); cut to limit


class ManualCatalogStore(ABC):
    """Async, tenant-bound authoritative store for manual cards."""

    def __init__(self, *, tenant_id: str, schema: str = "manuals", principal: Optional[str] = None,
                 search_regconfig: str = "english") -> None:
        if not (tenant_id or "").strip():
            raise ValueError("a manual catalog must be bound to a tenant_id")
        self._tenant_id = tenant_id
        self._schema = validate_identifier(schema, what="catalog schema")
        self._search_regconfig = validate_identifier(search_regconfig, what="search regconfig")
        self._principal = principal

    # FILL IN: read-only properties tenant_id / schema / search_regconfig / principal

    @abstractmethod
    async def upsert(self, card: ManualCard, *, expected_revision: Optional[int] = None,
                     version: Optional[ManualVersion] = None) -> UpsertResult:
        """Atomically write card + history + outbox row; CatalogConflictError / DuplicateSourceError."""

    # FILL IN: abstract get / find_by_sha / find_by_source_uri / list_cards(*, verification=None, active_only=True) /
    #   versions(manual_id) / search(query, top_k=8) / verification_queue(*, limit=50) / record_answer / get_answer /
    #   enqueue_publication / pending_publications(*, limit=50) / claim_publication(*, limit=1) /
    #   complete_publication(record, *, receipt) / fail_publication(record, *, error) / setup / close — signatures per spec §3 M4

    async def resolve_equipment(self, query: str, *, limit: int = 5) -> list[EquipmentRef]:
        """Deterministic resolution over every active card's equipment (shared by all backends)."""
        cards = await self.list_cards(active_only=True)
        pool = {ref.equipment_id: ref for card in cards for ref in card.equipment}
        return [ref for ref, _score in rank_equipment(query, list(pool.values()), limit=limit)]
```
**Why**: pure queue/ranking helpers keep the two backends observably identical; `AnswerRecord` stores citation dicts so this task
does not wait on TASK-3700.

### `packages/ai-parrot/tests/knowledge/_support/catalog.py` (CREATE)
```python
"""Deterministic in-memory ManualCatalogStore (FEAT-601). Mirrors the Postgres backend's observable preconditions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from parrot.knowledge.manuals.catalog import (AnswerRecord, CatalogConflictError, DuplicateSourceError, ManualCatalogStore,
                                              PublicationRecord, SearchHit, UpsertResult, VerificationQueueEntry,
                                              queue_entries_for)
from parrot.knowledge.manuals.models import ManualCard, ManualVersion, manual_snapshot_payload


class InMemoryManualCatalog(ManualCatalogStore):
    """Optimistic revisions, immutable history, durable outbox — no database."""

    def __init__(self, *, tenant_id: str = "t1", schema: str = "manuals", principal: Optional[str] = None,
                 search_regconfig: str = "english",
                 now: Callable[[], datetime] = lambda: datetime(2026, 9, 25, 12, tzinfo=timezone.utc)) -> None:
        super().__init__(tenant_id=tenant_id, schema=schema, principal=principal, search_regconfig=search_regconfig)
        self._now = now
        self.cards: dict[str, ManualCard] = {}
        self.revisions: dict[str, int] = {}
        self.history: dict[str, list[ManualVersion]] = {}
        self.answers: dict[str, AnswerRecord] = {}
        self.outbox: dict[tuple, PublicationRecord] = {}
        self.fail_record_answer = False

    # FILL IN: every abstract method; upsert enforces revision + sha/uri clash; record_answer raises when fail_record_answer
```

### FILL IN checklist
- [ ] errors + `validate_identifier`
- [ ] `queue_entries_for` — five reasons, priority, items
- [ ] `rank_equipment` — lazy rapidfuzz, deterministic sort
- [ ] ABC abstract methods + properties
- [ ] `InMemoryManualCatalog` — all methods
- [ ] contract suite below

---

## Acceptance Criteria

- [ ] `ManualCatalogStore` cannot be instantiated; the double implements every abstract method
- [ ] Empty tenant and invalid `schema`/`search_regconfig` identifiers are rejected
- [ ] Stale `expected_revision` ⇒ `CatalogConflictError`; sha/URI owned by another manual ⇒ `DuplicateSourceError`
- [ ] Every upsert appends a version and queues one publication row
- [ ] `verification_queue` orders by reason priority then `manual_id`
- [ ] `resolve_equipment("model x")` returns the matching `EquipmentRef` deterministically

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_catalog_contract.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_catalog_contract.py
import inspect

import pytest

from parrot.knowledge.manuals.catalog import CatalogConflictError, ManualCatalogStore, queue_entries_for

from .._support.catalog import InMemoryManualCatalog


@pytest.fixture()
def catalog() -> InMemoryManualCatalog:
    return InMemoryManualCatalog(tenant_id="t1")


def test_protocol_is_fully_implemented_and_async():
    ...


def test_cannot_instantiate_the_protocol_directly():
    with pytest.raises(TypeError):
        ManualCatalogStore(tenant_id="t1")


@pytest.mark.parametrize("value", ["Bad-Name", "1abc", "drop table;"])
def test_invalid_identifiers_rejected(value):
    ...


async def test_catalog_contract_inmemory(catalog):
    """upsert → get / find_by_sha / search / versions / outbox; conflict on stale revision."""


async def test_queue_ordering(catalog):
    ...


async def test_resolve_equipment_deterministic(catalog):
    ...


async def test_record_answer_failure_propagates(catalog):
    ...
```

---

## Agent Instructions

1. Read spec §3 Module 4.
2. Confirm TASK-3699 is done; re-verify the contracts catalog anchors.
3. Update the per-spec index status → `in-progress`.
4. Implement from the blueprint; complete every `# FILL IN:`.
5. Run the Validation Commands with the worktree `PYTHONPATH`.
6. Move this file to `sdd/tasks/completed/`, update the index → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
