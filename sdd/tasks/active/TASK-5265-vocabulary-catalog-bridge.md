# TASK-5265: Concept-catalog bridge — publish a tenant's reviewed catalog as `tenant.<tenant_id>`

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5260
**Assigned-to**: unassigned

---

## Context

Spec Module 10 (bridge half) and spec §2 "Concept catalog publishes to the store" (user decision
2026-11-06). The reviewed, tenant-scoped catalog (`ontology_concept*` tables, five-state machine)
stays the authoring workflow; this bridge projects one tenant's **approved** rows into an
`OntologyContent` and publishes it with `carry_forward_missing=True`, so a concept that stops being
approved stays in the store as deprecated. Read-only on the catalog tables. The worker hook is TASK-5266.

---

## Scope

- `vocabulary/catalog_bridge.py` with `tenant_ontology_id`, `tenant_base_iri`,
  `content_from_catalog`, `CatalogVocabularyPublisher` (spec lines 939–953).
- Mapping (spec §2 table):

  | Catalog | Vocabulary |
  |---|---|
  | `ConceptRow` (approved) | concept kind `skos_concept`, IRI `urn:parrot:tenant:<tenant_id>:<slug>` |
  | `label` / `synonyms` / `description` | `pref` label / `alt` labels (in `default_lang`) / `definition` |
  | `domain` | statement predicate `urn:parrot:core:domain`, object `{"value": domain}` |
  | `IsaEdgeRow` approved, `parent_tier="tenant"` | relation `skos:broader` → parent concept's IRI (look up its slug by `parent_ref` = concept id str; skip when the parent is not among the approved concepts) |
  | `IsaEdgeRow` approved, `parent_tier="framework"` | relation `skos:broader` → `urn:parrot:framework:<parent_ref>` |
  | published concept no longer approved | kept, deprecated (via `carry_forward_missing=True`) |

- `CatalogVocabularyPublisher.publish_tenant(tenant_id)`: `ConceptCatalogService(pg_pool).get_live_concepts(tenant_id)`;
  approved edges with `SELECT id, tenant_id, child_id, parent_tier, parent_ref, state, asserted_by, reviewed_by, rationale
  FROM ontology_concept_isa WHERE tenant_id = $1 AND state = 'approved'`; `publisher.ensure_ontology(…, base_iri=tenant_base_iri(tid), title=f"Tenant {tid} concepts")`;
  `publisher.publish_content(…, carry_forward_missing=True, notes="concept catalog")`.
- `test_catalog_bridge.py` — unit mapping tests + one integration test.

**NOT in scope**: the worker change (TASK-5266); writing to any catalog table; framework ontology
publication (spec §8 open question).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/catalog_bridge.py` | CREATE | projection + publisher |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_catalog_bridge.py` | CREATE | unit + integration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.concept_catalog.models import ConceptRow, IsaEdgeRow    # verified: concept_catalog/models.py:17, :55
from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService    # verified: concept_catalog/service.py:100
from parrot.knowledge.ontology.vocabulary.contracts import (                           # TASK-5253
    OntologyContent, OntologyPublisher, ParsedConcept, ParsedLabel, ParsedRelation, ParsedStatement, PublishResult)
from parrot.knowledge.ontology.vocabulary.closure import PARROT_NS, SKOS               # TASK-5257
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings    # TASK-5254
```

### Existing Signatures to Use
```python
# concept_catalog/models.py:17   (ConfigDict(extra="forbid"))
class ConceptRow(BaseModel):
    id: UUID; tenant_id: str; slug: str; label: str; synonyms: list[str]; description: str | None
    domain: str | None; state: Literal["proposed","pending_review","approved","rejected","deprecated"]
    asserted_by: str; reviewed_by: str | None; reviewed_at: datetime | None; rationale: str | None
    effective_from: datetime; effective_to: datetime | None
# concept_catalog/models.py:55   (ConfigDict(extra="forbid"))
class IsaEdgeRow(BaseModel):
    id: UUID; tenant_id: str; child_id: UUID; parent_tier: Literal["framework","tenant"]
    parent_ref: str; state: ...; asserted_by: str; reviewed_by: str | None; rationale: str | None
# concept_catalog/service.py:115, :457
class ConceptCatalogService:
    def __init__(self, pg_pool: Any) -> None
    async def get_live_concepts(self, tenant_id: str, domain: str | None = None) -> list[ConceptRow]  # approved only
# service.py:539-546 — SELECT id, child_id, parent_ref, parent_tier FROM ontology_concept_isa WHERE tenant_id = $1 AND state = 'approved'
# TASK-5260: PostgresOntologyPublisher.ensure_ontology(...), .publish_content(..., carry_forward_missing=True)
```

### Does NOT Exist
- ~~`ConceptCatalogService.list_isa_edges()`~~ or any "all approved edges" method — query the table directly (read-only).
- ~~DDL for `ontology_concept*` in the repository~~ — the integration test creates the tables from
  the DDL text in `sdd/specs/topic-authority-ontology.spec.md:169-264` inside its own unique schema
  (catalog pool opened with `server_settings={"search_path": "<schema>"}` because the service SQL is unqualified).
- ~~`ontology_concept_outbox.tenant_id`~~ — no such column.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/catalog_bridge.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_catalog_bridge.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/models.py#ConceptRow",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/models.py#IsaEdgeRow",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/service.py#ConceptCatalogService"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. The two IRI helpers and `content_from_catalog` (pure) — *why*: unit-testable mapping table.
2. `CatalogVocabularyPublisher` — *why*: the worker (TASK-5266) calls `publish_tenant`.
3. Tests.

### `.../vocabulary/catalog_bridge.py` (CREATE)
```python
"""Publish a tenant's reviewed concept catalog into the vocabulary store (FEAT-824)."""
from __future__ import annotations

import logging
import re
from typing import Any, Sequence

from parrot.knowledge.ontology.concept_catalog.models import ConceptRow, IsaEdgeRow  # verified: models.py:17, :55
from parrot.knowledge.ontology.vocabulary.closure import PARROT_NS, SKOS
from parrot.knowledge.ontology.vocabulary.contracts import OntologyContent, OntologyPublisher, PublishResult
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings

_TENANT_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
FRAMEWORK_NS = "urn:parrot:framework:"


def tenant_ontology_id(tenant_id: str) -> str:
    """'tenant.<tenant_id>'. Raises ValueError unless tenant_id matches [A-Za-z0-9_.-]+."""
    if not _TENANT_ID.match(tenant_id):
        raise ValueError(f"Invalid tenant id {tenant_id!r}")
    return f"tenant.{tenant_id}"


def tenant_base_iri(tenant_id: str) -> str:
    """'urn:parrot:tenant:<tenant_id>:'"""
    tenant_ontology_id(tenant_id)  # validates
    return f"urn:parrot:tenant:{tenant_id}:"


def content_from_catalog(tenant_id: str, concepts: Sequence[ConceptRow], edges: Sequence[IsaEdgeRow], *,
                         default_lang: str) -> OntologyContent:
    """Pure projection of approved rows. An edge whose tenant parent is not among ``concepts`` is skipped."""
    # FILL IN: mapping table of TASK-5265 Scope; ignore non-approved rows defensively; sorted lists.
    raise NotImplementedError


class CatalogVocabularyPublisher:
    """Publishes a tenant's reviewed concept catalog as the ontology 'tenant.<tenant_id>'."""

    def __init__(self, pg_pool: Any, publisher: OntologyPublisher, *, default_lang: str | None = None) -> None:
        self._pool, self._publisher = pg_pool, publisher
        self._lang = default_lang or resolve_ontology_settings().default_lang
        self.logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.catalog_bridge")

    async def publish_tenant(self, tenant_id: str) -> PublishResult:
        """Read approved concepts and approved is_a edges, ensure the ontology exists, publish. Read-only on the catalog."""
        from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService  # verified: service.py:100

        # FILL IN: per Scope; log version/changed.
        raise NotImplementedError
```

### `.../vocabulary/test_catalog_bridge.py` (CREATE) — required cases
```python
def test_tenant_ids_validated(): ...                    # "a b" → ValueError
def test_content_from_catalog_mapping(): ...            # every row of the mapping table
def test_edge_to_missing_tenant_parent_skipped(): ...
async def test_catalog_publish_tenant(pg_pool, pg_schema_name): ...
    # integration: create catalog tables in a second unique schema; insert 2 approved concepts + 1 edge;
    # publish_tenant → version 1; set one concept to 'deprecated' in the catalog; publish_tenant → version 2
    # and that IRI is in result.diff.deprecated and its current concept row has deprecated = true
    # (direct SQL on <schema>.concept WHERE until_version IS NULL) — not removed. Do not use
    # PostgresOntologyStore here (TASK-5261 is not a dependency of this task).
```

### FILL IN checklist
- [ ] `content_from_catalog`, `publish_tenant` bodies.
- [ ] tests (integration creates and drops its catalog schema).

---

## Acceptance Criteria

- [ ] `publish_tenant` publishes approved catalog concepts as `tenant.<tenant_id>`.
- [ ] A concept that stops being approved stays in the store as deprecated.
- [ ] The bridge never writes to a catalog table.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_catalog_bridge.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/concept_catalog/test_models.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5260 is `done`.
2. Mark `in-progress`; implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the listed files; close with `parrot sdd task close TASK-5265 ontology-backend verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
