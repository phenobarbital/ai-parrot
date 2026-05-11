---
type: feature
base_branch: dev
---

# Feature Specification: Topic-Authority Ontology Curation

**Feature ID**: FEAT-159
**Date**: 2026-05-11
**Author**: Jesús Lara
**Status**: draft
**Target version**: ai-parrot 4.x (TBD)
**Brainstorm**: `sdd/proposals/FEAT-topic-authority-ontology-brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The three sibling brainstorms in the topic-authority trilogy leave a deliberate gap:

- **FEAT-concept-document-authority** defines `Document` / `Concept` as YAML entities and the `covers_topic` / `is_a` relations — but treats `Concept` lifecycle as out of scope.
- **FEAT-topic-authority-operational** delivers a Postgres-backed state machine for the `covers_topic` edges — but explicitly punts on `Concept` management ("out of scope; concepts assumed managed via YAML for now").
- **FEAT-ontology-entity-extraction** consumes the merged ontology but does not curate it.

Today `TenantOntologyManager` (`packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:18`) resolves the merged ontology from a three-layer YAML chain (`base → domain → client`). The only way to add a `Concept`, change a synonym, introduce a new `is_a` parent, register a new entity type, or extend the merged ontology is a PR against the relevant YAML in `ontologies/clients/<tenant>.ontology.yaml`.

This works at framework scale but breaks at tenant scale (50+ clients):

- **No approval workflow.** Concept proposals from extraction pipelines (LLM/NER) have nowhere to live in `pending_review`.
- **No audit trail.** *"Why did the bot start treating `commissions` as a synonym of `sales_compensation`?"* needs `(actor, timestamp, before, after)`; `git blame` on nested YAML keys is the wrong granularity.
- **No hot reload.** YAML changes require merge + deploy + restart; curators expect changes to land in seconds.
- **No role separation.** A tenant admin who needs to add a synonym should NOT need the ability to introduce a new entity type — these changes have very different blast radii.

Without a curated catalog layer, FEAT-topic-authority-operational has a state machine for the **edges** but a free-text vocabulary for the **endpoints** — undermining the authority signal it set out to protect.

### Goals

- Postgres-backed operational truth for `Concept` entities, `is_a` taxonomy, AND per-tenant schema overlays (new entity types / relations / traversal patterns).
- **Two isolated services** sharing infrastructure but not tables: `ConceptCatalogService` (concept data) and `SchemaOverlayService` (schema overlays).
- Same five-state machine as FEAT-topic-authority-operational: `proposed → pending_review → approved → deprecated/rejected`.
- Framework concepts (those in `defaults/base.ontology.yaml` / `defaults/domains/*.yaml`) are **immutable at runtime**; no UI path can mutate them.
- `is_a` is a DAG with cross-tier links allowed (tenant concept may `is_a` a framework concept). Cycle detection mandatory at every transition.
- Role separation: reuse `topic_curator` / `topic_reviewer` / `topic_admin` for concept data; introduce `ontology_schema_admin` for schema overlays. Schema-side enforces a mandatory **sandboxed dry-run** before `approved`.
- Hot reload via Redis pub/sub on approve → `TenantOntologyManager.invalidate(tenant_id)` + `OntologyCache.invalidate_tenant(tenant_id)`. Sub-second propagation across all agent processes.
- Per-tenant isolation enforced at the API layer (no cross-tenant reads/writes).
- Existing YAML layering preserved: PG overlay is composed as an additional layer in the merger; tenants without PG overlays behave exactly as today.
- Cascade discipline on `Concept` deprecation: the cascade notifies the operational service's review queue (does not mutate it).

### Non-Goals (explicitly out of scope)

- **Generic `curated_ontology_*` shared-table abstraction with a `kind` discriminator** — rejected in brainstorm Option A. See `sdd/proposals/FEAT-topic-authority-ontology-brainstorm.md` (Option A) for the reasoning; same anti-pattern explicitly avoided in FEAT-topic-authority-operational.
- **Materialized-YAML export** as a backup/DR artifact (brainstorm Option C) — deferred; flagged as open question for a possible follow-up FEAT.
- **Mutating framework concepts via the UI** — explicitly forbidden by design. Framework concepts ship via bundled YAML + release only.
- **Cross-tenant concept/overlay sharing.** Each tenant's catalog and overlay are isolated.
- **WebSocket / SSE for nav-admin curators.** Polling refresh (10s) initially; reuses the operational decision.
- **Materialized smoke-test battery in dry-run.** v1 dry-run stops at AQL validation + cycle/parser checks; richer smoke testing is a follow-up.
- **Replacing `OntologyRefreshPipeline`.** The existing refresh pipeline (`refresh.py:61`) continues to operate on data-driven entity sync; this feature is curation-driven and runs alongside.

---

## 2. Architectural Design

### Overview

Two new Python sub-packages (`parrot.knowledge.ontology.concept_catalog` and `parrot.knowledge.ontology.schema_overlay`), each shaped exactly like the `TopicAuthorityService` family in FEAT-topic-authority-operational: a service (sole SQL writer), a qworker sync task, a YAML seed command, an aiohttp HTTP module, and a nightly reconciliation job. They share:

- The same five-state machine and audit/outbox conventions.
- The same `pg_<thing>_id` Arango-bridge attribute pattern.
- The same `SELECT … FOR UPDATE SKIP LOCKED` outbox-drain idiom.
- The same DLQ-after-N-retries posture with alerts.

They differ in:

- **Tables**: concept-side has 4 tables (state + audit + outbox + is_a edges); schema-side has 3 (state + audit + outbox).
- **Materialization target**: concept worker upserts to ArangoDB (`concepts` vertex collection, `concept_isa` edge collection); schema worker publishes to a Redis pub/sub channel and updates a `tenant_ontology_version` column.
- **Transition gate**: schema-side runs a mandatory `dry_run()` between `pending_review` and `approved` (sandboxed YAML+overlay merge + AQL validation); concept-side runs cycle detection on `is_a` proposals only.
- **Roles**: concept-side reuses `topic_*` from FEAT-topic-authority-operational; schema-side requires `ontology_schema_admin`.

`TenantOntologyManager.resolve()` is extended to compose the YAML chain + PG overlay layer in a single merge:

```
base.ontology.yaml
  ↓
domains/<domain>.ontology.yaml          [optional]
  ↓
clients/<tenant>.ontology.yaml          [optional]
  ↓
pg_overlay_concepts (from ontology_concept rows where state='approved')   [NEW]
  ↓
pg_overlay_schema   (from ontology_schema_overlay rows where state='approved')   [NEW]
  ↓
OntologyMerger.merge_with_overlay(yaml_paths, [pg_overlay_concepts, pg_overlay_schema])
  ↓
MergedOntology  →  TenantContext  →  cached in _cache
```

Cache invalidation: `SchemaOverlaySyncWorker` and `ConceptCatalogSyncWorker` both publish `ontology:invalidate:<tenant_id>` on approve/deprecate. Every agent process subscribes via a wildcard pattern; the subscriber calls `TenantOntologyManager.invalidate(tenant_id)` + `OntologyCache.invalidate_tenant(tenant_id)`.

### Component Diagram

```
   nav-admin (SvelteKit)
   ├── Concept Catalog Queue   ─┐
   ├── Concept Browser          │
   ├── Schema Overlay (admin)   │
   └── Audit Log                │
                                ▼
   aiohttp routes (/api/ontology/concepts/*, /api/ontology/schema/*)
        │                                          │
        ▼                                          ▼
   ConceptCatalogService                  SchemaOverlayService
   (sole SQL writer)                      (sole SQL writer + dry_run gate)
        │                                          │
        ▼                                          ▼
   Postgres: ontology_concept,            Postgres: ontology_schema_overlay,
             ontology_concept_isa,                  ontology_schema_audit,
             ontology_concept_audit,                ontology_schema_outbox
             ontology_concept_outbox
        │                                          │
        ▼ (qworker drain, SKIP LOCKED)             ▼ (qworker drain, SKIP LOCKED)
   ConceptCatalogSyncWorker               SchemaOverlaySyncWorker
        │                                          │
        ▼                                          ▼
   ArangoDB: concepts (vertex)            Redis pub/sub:
             concept_isa (edge)           ontology:invalidate:<tenant_id>
   via OntologyGraphStore                       │
                                                ▼
                              All agent processes:
                              OntologyCache.invalidate_tenant() +
                              TenantOntologyManager.invalidate()

                                                ↑
                              (Same channel — concept worker also
                               publishes after Arango materialization)

   TenantOntologyManager.resolve():
     YAML chain + ontology_concept(approved) + ontology_schema_overlay(approved)
     → OntologyMerger.merge_with_overlay()
     → MergedOntology
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.knowledge.ontology.tenant.TenantOntologyManager` | extends | `.resolve()` composes PG overlay; subscribes to pub/sub for cross-process invalidation. |
| `parrot.knowledge.ontology.merger.OntologyMerger` | extends | New `merge_with_overlay(yaml_paths, overlay_defs)`; framework-override guard at merge time. |
| `parrot.knowledge.ontology.cache.OntologyCache` | extends | Pub/sub subscriber added; existing `invalidate_tenant()` is the handler. |
| `parrot.knowledge.ontology.graph_store.OntologyGraphStore` | depends on | `upsert_nodes`, `create_edges`, `soft_delete_nodes` used by concept worker. No changes to graph_store itself. |
| `parrot.knowledge.ontology.validators.validate_aql` | depends on | Used by `SchemaOverlayService.dry_run()` for traversal patterns. No changes. |
| `parrot.knowledge.ontology.exceptions` | extends | New: `FrameworkOverrideError`, `CycleError`, `SynonymConflictError`, `DryRunFailedError`. |
| `navigator-auth` | depends on | Adds `ontology_schema_admin` role; reuses `topic_curator`/`topic_reviewer`/`topic_admin`. |
| `qworker` | depends on | Two new task classes (`ConceptCatalogSyncWorker`, `SchemaOverlaySyncWorker`); shared retry/DLQ policy. |
| `asyncdb` (Postgres) | depends on | New schema, ~7 tables + indexes. |
| ArangoDB | extends | New per-tenant collections `concepts` and `concept_isa` initialized via `OntologyGraphStore.initialize_tenant()`. |
| FEAT-topic-authority-operational | hard dependency | Audit/outbox/role patterns reused; cascade-on-deprecate notifies its review queue. |
| FEAT-concept-document-authority | provides | `Concept` entity definition (this feature curates instances). |
| nav-admin (SvelteKit) | extends | New panels; shared components `<CurationQueue>` / `<TransitionDialog>` extracted from operational panels. |

### Data Models

#### Postgres schema

```sql
-- ── Concept catalog ──

CREATE TABLE ontology_concept (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(64)  NOT NULL,
    slug            VARCHAR(128) NOT NULL,                  -- tenant-local slug (e.g. "sales_commissions")
    label           VARCHAR(256) NOT NULL,
    synonyms        TEXT[]       NOT NULL DEFAULT '{}',
    description     TEXT,
    domain          VARCHAR(64),

    state           VARCHAR(16)  NOT NULL DEFAULT 'proposed'
                    CHECK (state IN ('proposed','pending_review','approved','rejected','deprecated')),

    asserted_by     VARCHAR(96)  NOT NULL,
    reviewed_by     VARCHAR(96),
    reviewed_at     TIMESTAMPTZ,
    rationale       TEXT,

    effective_from  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    effective_to    TIMESTAMPTZ,

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Only one "live" concept per (tenant, slug). Historical versions coexist deprecated/rejected.
CREATE UNIQUE INDEX uq_ontology_concept_live
    ON ontology_concept (tenant_id, slug)
    WHERE state IN ('approved','pending_review','proposed');

CREATE INDEX idx_ontology_concept_review_queue
    ON ontology_concept (tenant_id, state, created_at)
    WHERE state IN ('proposed','pending_review');

CREATE INDEX idx_ontology_concept_approved_lookup
    ON ontology_concept (tenant_id, slug)
    WHERE state = 'approved';

-- Synonym collision detection (within tenant, approved state).
-- Enforced at service layer via SynonymConflictError; this is a fast lookup helper.
CREATE INDEX idx_ontology_concept_synonyms
    ON ontology_concept USING gin (tenant_id, synonyms)
    WHERE state = 'approved';


CREATE TABLE ontology_concept_isa (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(64)  NOT NULL,
    child_id        UUID         NOT NULL REFERENCES ontology_concept(id),
    parent_tier     VARCHAR(16)  NOT NULL CHECK (parent_tier IN ('framework','tenant')),
    parent_ref      VARCHAR(256) NOT NULL,    -- framework concept name OR tenant ontology_concept.id (as text)

    state           VARCHAR(16)  NOT NULL DEFAULT 'proposed'
                    CHECK (state IN ('proposed','pending_review','approved','rejected','deprecated')),

    asserted_by     VARCHAR(96)  NOT NULL,
    reviewed_by     VARCHAR(96),
    reviewed_at     TIMESTAMPTZ,
    rationale       TEXT,

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_ontology_concept_isa_child
    ON ontology_concept_isa (tenant_id, child_id)
    WHERE state = 'approved';


CREATE TABLE ontology_concept_audit (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_id   UUID         NOT NULL,                     -- ontology_concept.id or ontology_concept_isa.id
    target_kind VARCHAR(16)  NOT NULL CHECK (target_kind IN ('concept','isa_edge')),
    action      VARCHAR(32)  NOT NULL,
    actor       VARCHAR(96)  NOT NULL,
    diff        JSONB        NOT NULL,
    reason      TEXT,
    occurred_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_ontology_concept_audit_target
    ON ontology_concept_audit (target_id, occurred_at DESC);


CREATE TABLE ontology_concept_outbox (
    id           BIGSERIAL PRIMARY KEY,
    target_id    UUID         NOT NULL,
    target_kind  VARCHAR(16)  NOT NULL,                    -- 'concept' | 'isa_edge'
    operation    VARCHAR(32)  NOT NULL,                    -- 'publish_to_graph' | 'deprecate_in_graph' | 'invalidate_cache'
    payload      JSONB        NOT NULL,
    enqueued_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    attempts     INT          NOT NULL DEFAULT 0,
    last_error   TEXT
);

CREATE INDEX idx_ontology_concept_outbox_unprocessed
    ON ontology_concept_outbox (enqueued_at)
    WHERE processed_at IS NULL;


-- ── Schema overlay (entity types, relation types, traversal patterns) ──

CREATE TABLE ontology_schema_overlay (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(64)  NOT NULL,
    overlay_kind    VARCHAR(32)  NOT NULL
                    CHECK (overlay_kind IN ('entity_type','relation_type','traversal_pattern')),
    name            VARCHAR(128) NOT NULL,                -- e.g. "Project" or "manages" or "team_status"
    definition      JSONB        NOT NULL,                -- serialized EntityDef / RelationDef / TraversalPattern

    state           VARCHAR(16)  NOT NULL DEFAULT 'proposed'
                    CHECK (state IN ('proposed','pending_review','approved','rejected','deprecated')),

    asserted_by     VARCHAR(96)  NOT NULL,
    reviewed_by     VARCHAR(96),
    reviewed_at     TIMESTAMPTZ,
    rationale       TEXT,
    dry_run_report  JSONB,                                -- last dry_run outcome (success or failure + trace)

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_ontology_schema_overlay_live
    ON ontology_schema_overlay (tenant_id, overlay_kind, name)
    WHERE state IN ('approved','pending_review','proposed');

CREATE INDEX idx_ontology_schema_overlay_review_queue
    ON ontology_schema_overlay (tenant_id, state, created_at)
    WHERE state IN ('proposed','pending_review');


CREATE TABLE ontology_schema_audit (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    overlay_id  UUID         NOT NULL REFERENCES ontology_schema_overlay(id),
    action      VARCHAR(32)  NOT NULL,
    actor       VARCHAR(96)  NOT NULL,
    diff        JSONB        NOT NULL,
    reason      TEXT,
    occurred_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_ontology_schema_audit_overlay
    ON ontology_schema_audit (overlay_id, occurred_at DESC);


CREATE TABLE ontology_schema_outbox (
    id           BIGSERIAL PRIMARY KEY,
    overlay_id   UUID         NOT NULL,
    operation    VARCHAR(32)  NOT NULL,                   -- 'invalidate_cache' | 'deprecate_invalidate'
    payload      JSONB        NOT NULL,
    enqueued_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    attempts     INT          NOT NULL DEFAULT 0,
    last_error   TEXT
);

CREATE INDEX idx_ontology_schema_outbox_unprocessed
    ON ontology_schema_outbox (enqueued_at)
    WHERE processed_at IS NULL;
```

#### Pydantic / domain types

```python
# parrot/knowledge/ontology/concept_catalog/models.py

class ConceptRow(BaseModel):
    id: UUID
    tenant_id: str
    slug: str
    label: str
    synonyms: list[str] = Field(default_factory=list)
    description: str | None = None
    domain: str | None = None
    state: Literal["proposed","pending_review","approved","rejected","deprecated"]
    asserted_by: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    rationale: str | None = None
    effective_from: datetime
    effective_to: datetime | None = None

class IsaEdgeRow(BaseModel):
    id: UUID
    tenant_id: str
    child_id: UUID
    parent_tier: Literal["framework","tenant"]
    parent_ref: str                                 # framework name or tenant ID-as-string
    state: Literal["proposed","pending_review","approved","rejected","deprecated"]
    asserted_by: str
    reviewed_by: str | None = None
    rationale: str | None = None

class CascadeAlert(BaseModel):
    """Emitted to the operational service's queue when a Concept is deprecated."""
    tenant_id: str
    concept_id: UUID
    concept_slug: str
    affected_edge_ids: list[UUID]                  # operational topic_authority.id values
    notified_at: datetime
```

```python
# parrot/knowledge/ontology/schema_overlay/models.py

class SchemaOverlayRow(BaseModel):
    id: UUID
    tenant_id: str
    overlay_kind: Literal["entity_type","relation_type","traversal_pattern"]
    name: str
    definition: dict[str, Any]                     # serialized EntityDef / RelationDef / TraversalPattern
    state: Literal["proposed","pending_review","approved","rejected","deprecated"]
    asserted_by: str
    reviewed_by: str | None = None
    rationale: str | None = None
    dry_run_report: dict[str, Any] | None = None

class DryRunReport(BaseModel):
    ok: bool
    checks: list[dict[str, Any]]                  # list of {check_name, passed, details}
    error: str | None = None
    duration_ms: int
```

### New Public Interfaces

```python
# parrot/knowledge/ontology/concept_catalog/service.py

class ConceptCatalogService:
    """Operational truth for per-tenant Concept entities and is_a edges.

    All state-changing calls follow the FEAT-topic-authority-operational shape:
      1. FOR UPDATE row lock.
      2. Validate transition (state machine + invariants).
      3. UPDATE row.
      4. INSERT audit row.
      5. INSERT outbox row.
    All within a single transaction.
    """

    async def propose_concept(
        self,
        tenant_id: str,
        slug: str,
        label: str,
        asserted_by: str,
        synonyms: list[str] | None = None,
        description: str | None = None,
        domain: str | None = None,
        rationale: str | None = None,
    ) -> UUID: ...

    async def propose_isa_edge(
        self,
        tenant_id: str,
        child_id: UUID,
        parent_tier: Literal["framework","tenant"],
        parent_ref: str,
        asserted_by: str,
        rationale: str | None = None,
    ) -> UUID: ...

    async def submit_for_review(self, target_id: UUID, target_kind: str, actor: str) -> None: ...
    async def approve(self, target_id: UUID, target_kind: str, actor: str, reason: str | None = None) -> None: ...
    async def reject(self, target_id: UUID, target_kind: str, actor: str, reason: str | None = None) -> None: ...
    async def deprecate(self, target_id: UUID, target_kind: str, actor: str, reason: str | None = None) -> CascadeAlert | None: ...
    async def restore(self, target_id: UUID, target_kind: str, actor: str, reason: str | None = None) -> None: ...
    async def modify_metadata(
        self, concept_id: UUID, actor: str,
        synonyms: list[str] | None = None,
        description: str | None = None,
        domain: str | None = None,
    ) -> None: ...

    async def get_live_concepts(self, tenant_id: str, domain: str | None = None) -> list[ConceptRow]: ...
    async def get_isa_subgraph(self, tenant_id: str, concept_id: UUID) -> dict[str, Any]: ...
    async def get_history(self, target_id: UUID, target_kind: str) -> list[dict[str, Any]]: ...
```

```python
# parrot/knowledge/ontology/schema_overlay/service.py

class SchemaOverlayService:
    """Operational truth for per-tenant schema overlays.

    Transition to 'approved' MUST pass dry_run() (sandboxed merge + AQL validation).
    Failures keep the row in 'pending_review' with dry_run_report populated.
    """

    async def propose(
        self,
        tenant_id: str,
        overlay_kind: Literal["entity_type","relation_type","traversal_pattern"],
        name: str,
        definition: dict[str, Any],
        asserted_by: str,
        rationale: str | None = None,
    ) -> UUID: ...

    async def submit_for_review(self, overlay_id: UUID, actor: str) -> None: ...
    async def approve(self, overlay_id: UUID, actor: str, reason: str | None = None) -> None: ...  # invokes dry_run() first
    async def reject(self, overlay_id: UUID, actor: str, reason: str | None = None) -> None: ...
    async def deprecate(self, overlay_id: UUID, actor: str, reason: str | None = None) -> None: ...

    async def dry_run(self, tenant_id: str, candidate: SchemaOverlayRow) -> DryRunReport: ...

    async def get_pending(self, tenant_id: str) -> list[SchemaOverlayRow]: ...
    async def get_history(self, overlay_id: UUID) -> list[dict[str, Any]]: ...
```

```python
# parrot/knowledge/ontology/concept_catalog/worker.py

class ConceptCatalogSyncWorker:
    OPERATIONS: dict[str, str] = {
        "publish_to_graph":   "_op_publish",
        "deprecate_in_graph": "_op_deprecate",
        "invalidate_cache":   "_op_invalidate",
    }
    GRAPH_NODE_COLLECTION = "concepts"
    GRAPH_EDGE_COLLECTION = "concept_isa"

    async def run_once(self, batch_size: int = 50) -> int: ...
```

```python
# parrot/knowledge/ontology/schema_overlay/worker.py

class SchemaOverlaySyncWorker:
    OPERATIONS: dict[str, str] = {
        "invalidate_cache":     "_op_invalidate",
        "deprecate_invalidate": "_op_invalidate",
    }
    INVALIDATE_CHANNEL_TEMPLATE = "ontology:invalidate:{tenant_id}"

    async def run_once(self, batch_size: int = 50) -> int: ...
```

```python
# parrot/knowledge/ontology/merger.py (extension)

class OntologyMerger:
    def merge(self, yaml_paths: list[Path]) -> MergedOntology: ...                # existing
    def merge_with_overlay(                                                       # NEW
        self,
        yaml_paths: list[Path],
        overlay_defs: list[OntologyDefinition],
    ) -> MergedOntology:
        """Merge YAML layers + in-memory PG-sourced overlay definitions.

        Raises:
            FrameworkOverrideError: an overlay attempts to mutate a framework
                entity/relation/pattern.
        """
        ...
```

```python
# parrot/knowledge/ontology/exceptions.py (new exception types)

class FrameworkOverrideError(OntologyError): ...
class CycleError(OntologyError): ...
class SynonymConflictError(OntologyError): ...
class DryRunFailedError(OntologyError):
    def __init__(self, report: DryRunReport): ...
```

#### HTTP routes

| Method | Path | Role required |
|---|---|---|
| GET | `/api/ontology/concepts?tenant=&state=&domain=&limit=&offset=` | `topic_curator`+ |
| GET | `/api/ontology/concepts/{id}` | `topic_curator`+ |
| GET | `/api/ontology/concepts/{id}/history` | `topic_curator`+ |
| GET | `/api/ontology/concepts/{id}/isa` | `topic_curator`+ |
| POST | `/api/ontology/concepts` | `topic_curator`+ |
| POST | `/api/ontology/concepts/{id}/transitions/submit` | `topic_curator`+ |
| POST | `/api/ontology/concepts/{id}/transitions/approve` | `topic_reviewer`+ |
| POST | `/api/ontology/concepts/{id}/transitions/reject` | `topic_reviewer`+ |
| POST | `/api/ontology/concepts/{id}/transitions/deprecate` | `topic_admin` |
| POST | `/api/ontology/concepts/{id}/transitions/restore` | `topic_admin` |
| PATCH | `/api/ontology/concepts/{id}` (metadata only) | `topic_reviewer`+ |
| POST | `/api/ontology/concepts/isa` (propose new is_a edge) | `topic_curator`+ |
| POST | `/api/ontology/concepts/isa/{id}/transitions/{action}` | per state-machine action |
| GET | `/api/ontology/schema?tenant=&state=&kind=` | `ontology_schema_admin` |
| GET | `/api/ontology/schema/{id}` | `ontology_schema_admin` |
| GET | `/api/ontology/schema/{id}/dry-run` | `ontology_schema_admin` |
| POST | `/api/ontology/schema` (propose) | `ontology_schema_admin` |
| POST | `/api/ontology/schema/{id}/transitions/{action}` | `ontology_schema_admin` |
| GET | `/api/ontology/reconciliation/report` | `topic_admin` |

All routes scoped by `tenant_id` from the auth session; cross-tenant access denied at the auth layer.

---

## 3. Module Breakdown

### Module 1: Postgres migration
- **Path**: `packages/ai-parrot/migrations/<timestamp>_ontology_curation.sql` (or whatever migration runner ai-parrot uses; verify in §6).
- **Responsibility**: All seven tables + indexes + role grants. Rollback script included.
- **Depends on**: nothing — this lands first.

### Module 2: `parrot.knowledge.ontology.exceptions` (extension)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py`
- **Responsibility**: Add `FrameworkOverrideError`, `CycleError`, `SynonymConflictError`, `DryRunFailedError`. All inherit from the existing `OntologyError` (verify base class name in §6).
- **Depends on**: existing exceptions module.

### Module 3: `parrot.knowledge.ontology.concept_catalog.models`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/models.py`
- **Responsibility**: Pydantic v2 row models (`ConceptRow`, `IsaEdgeRow`, `CascadeAlert`).
- **Depends on**: Pydantic v2 (already a dependency).

### Module 4: `parrot.knowledge.ontology.concept_catalog.service`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/service.py`
- **Responsibility**: `ConceptCatalogService` — sole writer to `ontology_concept*` tables. State machine, audit, outbox in one transaction. Cycle detection on `propose_isa_edge` / approve. Synonym collision check. Cascade alert emission on Concept deprecation.
- **Depends on**: Module 1, 2, 3; `asyncdb` for PG; `networkx` (optional, for cycle detection) or hand-rolled DFS.

### Module 5: `parrot.knowledge.ontology.concept_catalog.worker`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py`
- **Responsibility**: `ConceptCatalogSyncWorker` — drains `ontology_concept_outbox` with `SELECT ... FOR UPDATE SKIP LOCKED`; upserts concepts/edges to ArangoDB via `OntologyGraphStore`; publishes `ontology:invalidate:<tenant_id>` after each successful sync.
- **Depends on**: Modules 3, 4; `qworker`; `OntologyGraphStore`.

### Module 6: `parrot.knowledge.ontology.concept_catalog.seed`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/seed.py`
- **Responsibility**: `seed_concepts_from_yaml(tenant_id, yaml_path, service)` — idempotent; existing rows (any state) skipped. Calls `propose` + `approve` (admin path) with `asserted_by="seed:yaml@<hash>"`.
- **Depends on**: Module 4; existing `OntologyParser`.

### Module 7: `parrot.knowledge.ontology.concept_catalog.reconcile`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/reconcile.py`
- **Responsibility**: Nightly job. For each tenant: scan approved rows; verify matching ArangoDB documents/edges with correct `pg_concept_id` / `pg_isa_edge_id`. Reverse scan. Log discrepancies, **do not auto-repair**.
- **Depends on**: Modules 4, 5; `qworker` scheduler; `OntologyGraphStore`.

### Module 8: `parrot.knowledge.ontology.concept_catalog.http`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/http.py`
- **Responsibility**: aiohttp routes under `/api/ontology/concepts/*`. Role enforcement via `navigator-auth`. Tenant scoping from session.
- **Depends on**: Module 4; navigator-auth.

### Module 9: `parrot.knowledge.ontology.schema_overlay.models`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/models.py`
- **Responsibility**: `SchemaOverlayRow`, `DryRunReport`.
- **Depends on**: Pydantic v2.

### Module 10: `parrot.knowledge.ontology.schema_overlay.validator`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/validator.py`
- **Responsibility**: `dry_run_overlay(tenant_id, overlay)` — sandboxed merge using `OntologyMerger.merge_with_overlay()` against an ephemeral copy of the tenant's current state; runs `validate_aql` for any traversal patterns; checks for framework override attempts; emits a `DryRunReport`.
- **Depends on**: existing `OntologyMerger`, `validate_aql`, `TenantOntologyManager.resolve()`.

### Module 11: `parrot.knowledge.ontology.schema_overlay.service`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/service.py`
- **Responsibility**: `SchemaOverlayService` — sole writer to `ontology_schema_overlay*` tables. State machine. Mandatory `dry_run()` gate between `pending_review` and `approved`.
- **Depends on**: Modules 1, 2, 9, 10.

### Module 12: `parrot.knowledge.ontology.schema_overlay.worker`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/worker.py`
- **Responsibility**: `SchemaOverlaySyncWorker` — drains `ontology_schema_outbox`; publishes `ontology:invalidate:<tenant_id>`.
- **Depends on**: Modules 9, 11; `qworker`; `redis.asyncio`.

### Module 13: `parrot.knowledge.ontology.schema_overlay.http`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/http.py`
- **Responsibility**: aiohttp routes under `/api/ontology/schema/*`. `ontology_schema_admin` role required.
- **Depends on**: Module 11; navigator-auth.

### Module 14: `OntologyMerger.merge_with_overlay` (extension)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py`
- **Responsibility**: New method that accepts in-memory `OntologyDefinition` overlay layers in addition to YAML paths. Enforces framework-override guard: any overlay attempting to mutate an entity/relation/pattern present in `base.ontology.yaml` raises `FrameworkOverrideError`.
- **Depends on**: Module 2.

### Module 15: `TenantOntologyManager` extension
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py`
- **Responsibility**: `.resolve()` fetches approved concept rows + approved schema overlays for the tenant and synthesizes two `OntologyDefinition` instances (`pg_overlay_concepts`, `pg_overlay_schema`) passed to `merge_with_overlay`. Constructor accepts a `concept_catalog_service` and `schema_overlay_service` (or thin reader interfaces) for testability.
- **Depends on**: Modules 4, 11, 14.

### Module 16: `OntologyCache` pub/sub subscriber
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/cache.py`
- **Responsibility**: New `async def subscribe_invalidation(self, manager: TenantOntologyManager) -> None` that subscribes to the wildcard `ontology:invalidate:*` channel; on message, calls `manager.invalidate(tenant_id)` + `self.invalidate_tenant(tenant_id)`. Started by the application bootstrap.
- **Depends on**: existing `OntologyCache`; `redis.asyncio`.

### Module 17: nav-admin Concept Catalog Queue panel
- **Path**: nav-admin SvelteKit routes — `src/routes/ontology/concepts/queue/+page.svelte` (path to be verified per nav-admin conventions).
- **Responsibility**: Review queue for proposed/pending_review concept rows. Same UX patterns as the operational Review Queue (extract shared `<CurationQueue>` Svelte component if not already extracted).
- **Depends on**: Module 8 (HTTP API).

### Module 18: nav-admin Concept Browser panel
- **Path**: `src/routes/ontology/concepts/+page.svelte`
- **Responsibility**: Approved-concepts browser with is_a ancestor/descendant view, synonym editor, deprecate action (with cascade preview).
- **Depends on**: Module 8.

### Module 19: nav-admin Schema Overlay panel
- **Path**: `src/routes/ontology/schema/+page.svelte`
- **Responsibility**: Schema-admin-only panel. Diff view of proposed overlays vs current merged ontology. Dry-run report visible. Route guarded by role.
- **Depends on**: Module 13.

### Module 20: navigator-auth role addition
- **Path**: navigator-auth role catalog (location varies; verify before implementation).
- **Responsibility**: Register `ontology_schema_admin` role.
- **Depends on**: navigator-auth (external repo or in-tree config).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_propose_concept_creates_proposed_row` | 4 | Service inserts row with state='proposed' and writes audit + outbox in same transaction. |
| `test_approve_concept_state_machine` | 4 | Approves only from proposed/pending_review; rejected → approve raises `InvalidTransitionError`. |
| `test_synonym_collision_rejected` | 4 | Proposing a synonym already in another approved concept raises `SynonymConflictError`. |
| `test_concept_uniqueness_partial_index` | 4 | Two concurrent proposes for same (tenant, slug) yield exactly one success. |
| `test_propose_isa_edge_cycle_detection` | 4 | A→B, then B→A approve attempt raises `CycleError`. |
| `test_propose_isa_edge_cross_tier_allowed` | 4 | tenant concept is_a framework concept succeeds; framework is_a tenant raises `InvalidTransitionError`. |
| `test_deprecate_concept_emits_cascade_alert` | 4 | Deprecating a concept referenced by operational `topic_authority` edges returns `CascadeAlert` with the edge IDs. |
| `test_modify_metadata_concept_only` | 4 | `modify_metadata` cannot change slug/label after approve. |
| `test_concept_outbox_drain_skip_locked` | 5 | Two parallel workers process disjoint outbox rows; no double-processing. |
| `test_concept_arango_upsert_carries_pg_concept_id` | 5 | Each upserted Arango doc has `pg_concept_id` set. |
| `test_concept_worker_publishes_invalidation` | 5 | After successful sync, Redis channel `ontology:invalidate:<tenant>` receives a message. |
| `test_seed_idempotency` | 6 | Running `seed_concepts_from_yaml` twice on a fresh tenant yields the same final state. |
| `test_concept_reconciliation_detects_drift` | 7 | Artificial PG↔Arango discrepancy → discrepancy logged, no auto-repair. |
| `test_concept_http_role_enforcement` | 8 | `topic_curator` cannot call `/transitions/approve`; receives 403. |
| `test_schema_overlay_propose` | 11 | Service inserts row with state='proposed'; audit + outbox in same transaction. |
| `test_schema_overlay_approve_runs_dry_run` | 11 | Approve call invokes `dry_run`; failure keeps state at `pending_review` with `dry_run_report` populated and raises `DryRunFailedError`. |
| `test_schema_overlay_dry_run_aql_validation` | 10 | Traversal pattern with invalid AQL fails dry_run; valid AQL passes. |
| `test_schema_overlay_dry_run_framework_override_blocked` | 10 | Overlay redefining `Employee` (framework entity) fails dry_run with `FrameworkOverrideError`. |
| `test_schema_overlay_worker_publishes_invalidation` | 12 | After sync, Redis channel receives invalidation message. |
| `test_schema_overlay_http_role_enforcement` | 13 | `topic_admin` cannot call schema endpoints; receives 403. |
| `test_merger_merge_with_overlay` | 14 | YAML chain + overlay layers produce identical `MergedOntology` as the equivalent all-YAML chain. |
| `test_merger_framework_override_guard` | 14 | Overlay mutating a `base` entity raises `FrameworkOverrideError`. |
| `test_tenant_manager_composes_pg_overlay` | 15 | `resolve()` includes approved concepts + approved schema overlays in `MergedOntology`. |
| `test_cache_pubsub_subscriber` | 16 | Subscriber calls `invalidate(tenant_id)` + `invalidate_tenant(tenant_id)` on message. |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_concept_lifecycle` | Propose concept → submit_for_review → approve → ArangoDB has the document with pg_concept_id → all agent processes see it after invalidation. |
| `test_end_to_end_isa_curation` | Propose A→B is_a; approve; query `get_isa_subgraph` returns the edge; ArangoDB `concept_isa` has the edge. |
| `test_end_to_end_schema_overlay` | Propose new entity_type → submit → approve (dry_run passes) → `TenantOntologyManager.resolve()` returns merged ontology with the new entity. |
| `test_end_to_end_hot_reload` | Tenant T running ontology version 1. Approve a concept synonym. Within ≤5s, every running agent process resolving T sees the new synonym. |
| `test_yaml_seed_to_full_pipeline` | Seed a new tenant from YAML; verify approved rows in PG; verify ArangoDB materialized; verify a query against the new tenant resolves the concept. |
| `test_cross_tenant_isolation` | Tenant A's approved concepts NOT visible to tenant B via `resolve()`. |
| `test_cascade_alert_on_concept_deprecate` | Deprecate a concept referenced by operational edges; alert emitted; operational queue receives notification. |
| `test_dry_run_failure_blocks_approve` | Propose a traversal pattern with broken AQL; approve fails; state stays pending_review with dry_run_report. |

### Test Data / Fixtures

```python
@pytest.fixture
async def empty_tenant(pg_pool, arango_client) -> str:
    """Returns a fresh tenant_id with empty Postgres + Arango state."""
    ...

@pytest.fixture
async def concept_catalog_service(pg_pool) -> ConceptCatalogService:
    ...

@pytest.fixture
async def schema_overlay_service(pg_pool, tenant_manager) -> SchemaOverlayService:
    ...

@pytest.fixture
def synthetic_framework_concepts() -> list[str]:
    """List of concept names from base.ontology.yaml; used to test framework-override guard."""
    ...

@pytest.fixture
async def seeded_tenant_with_isa(concept_catalog_service, empty_tenant) -> str:
    """Tenant with concepts A, B, C and approved is_a edges A→B, B→C."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true.

- [ ] All unit tests in §4 pass (`pytest packages/ai-parrot/tests/knowledge/concept_catalog/ packages/ai-parrot/tests/knowledge/schema_overlay/ -v`).
- [ ] All integration tests in §4 pass.
- [ ] Postgres migration applies cleanly; rollback script verified.
- [ ] Two concurrent `propose_concept` calls for the same `(tenant_id, slug)`: exactly one succeeds; the other raises `ConflictError`.
- [ ] Two parallel `ConceptCatalogSyncWorker` instances drain disjoint outbox rows under SKIP LOCKED; no message processed twice.
- [ ] After `approve()`, the corresponding ArangoDB document/edge appears within outbox drain interval (default ≤5s).
- [ ] After `approve()`, every running agent process resolving the tenant sees the updated ontology within ≤5s (pub/sub propagation + 60s polling fallback).
- [ ] `topic_curator` calling `/api/ontology/concepts/{id}/transitions/approve` receives 403.
- [ ] `topic_admin` calling `/api/ontology/schema` (any method) receives 403.
- [ ] `ontology_schema_admin` proposing an overlay that mutates a framework entity: dry_run fails with `FrameworkOverrideError`; row stays at `pending_review` with `dry_run_report` populated.
- [ ] Proposing an is_a edge that would create a cycle in the approved DAG raises `CycleError` at propose time (never reaches outbox).
- [ ] Cross-tier: tenant concept → framework concept succeeds; framework → tenant rejected with `InvalidTransitionError`.
- [ ] Deprecating a concept referenced by approved operational `topic_authority` edges: succeeds; emits `CascadeAlert`; operational service's review queue receives notification.
- [ ] YAML seed run twice on a fresh tenant produces identical final state.
- [ ] Nightly reconciliation job detects an artificially-injected PG↔Arango discrepancy; emits alert; does NOT auto-repair.
- [ ] `MergedOntology` produced by `merge_with_overlay()` is identical to the equivalent all-YAML chain when overlay is empty (regression safety).
- [ ] No breaking changes to existing public API of `TenantOntologyManager.resolve()`, `OntologyMerger.merge()`, `OntologyCache.invalidate_tenant()`. New surfaces are additive.
- [ ] Existing ontology test suite (`packages/ai-parrot/tests/knowledge/test_ontology_*.py`) continues to pass.
- [ ] nav-admin Concept Catalog Queue panel renders proposed rows within one polling cycle (10s).
- [ ] DLQ growth on either worker triggers an alert (reuses FEAT-topic-authority-operational alerting hookup).
- [ ] Documentation updated in `docs/ontology/curation.md` (or equivalent location verified in §6).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Implementation agents MUST NOT reference imports, attributes, or methods not listed here without first verifying via `grep`/`read`.

### Verified Imports

```python
# These imports were re-verified during spec drafting (2026-05-11):
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.schema import (
    OntologyDefinition,        # schema.py:155
    MergedOntology,            # schema.py:185
    EntityDef,                 # schema.py:39
    RelationDef,               # schema.py:106
    TraversalPattern,          # schema.py:131
    TenantContext,             # schema.py:261
    ResolvedIntent,            # schema.py:279
    EnrichedContext,           # schema.py:303
    PropertyDef,               # schema.py:17
)
from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.graph_store import (
    OntologyGraphStore,        # graph_store.py:33
    UpsertResult,              # graph_store.py:19
)
from parrot.knowledge.ontology.validators import validate_aql       # validators.py:36
from parrot.knowledge.ontology.refresh import (
    OntologyRefreshPipeline,   # refresh.py:61
    RefreshReport,             # refresh.py:41
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py
class TenantOntologyManager:                                                    # line 18
    def __init__(
        self,
        ontology_dir: Path | str | None = None,
        base_file: str | None = None,
        domains_dir: str | None = None,
        clients_dir: str | None = None,
        db_template: str | None = None,
        pgvector_schema_template: str | None = None,
    ) -> None: ...                                                              # line 37
    def resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext: ...   # line 74
    def invalidate(self, tenant_id: str | None = None) -> None: ...             # line 165
    def list_tenants(self) -> list[str]: ...                                    # line 180
    # Attributes:
    self._cache: dict[str, TenantContext]                                       # line 72
    self._merger: OntologyMerger                                                # line 71
    self._ontology_dir: Path                                                    # line 64

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py
class EntityDef(BaseModel):                                                     # line 39
    collection: str | None = None                                               # line 55
    source: str | None = None                                                   # line 56
    key_field: str | None = None                                                # line 57
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)      # line 58
    vectorize: list[str] = Field(default_factory=list)                          # line 59
    extend: bool = False                                                        # line 60   ← KEY: enables layered merging
    model_config = ConfigDict(extra="forbid")                                   # line 62
    def get_property_names(self) -> set[str]: ...                               # line 64

class RelationDef(BaseModel):                                                   # line 106
    from_entity: str = Field(alias="from")                                      # line 119
    to_entity: str = Field(alias="to")                                          # line 120
    edge_collection: str                                                        # line 121

class TraversalPattern(BaseModel):                                              # line 131
    description: str
    trigger_intents: list[str] = Field(default_factory=list)
    query_template: str
    post_action: Literal["vector_search","tool_call","none"] = "none"
    post_query: str | None = None

class OntologyDefinition(BaseModel):                                            # line 155
    name: str
    version: str = "1.0"
    extends: str | None = None
    description: str | None = None
    entities: dict[str, EntityDef] = Field(default_factory=dict)
    relations: dict[str, RelationDef] = Field(default_factory=dict)
    traversal_patterns: dict[str, TraversalPattern] = Field(default_factory=dict)

class MergedOntology(BaseModel):                                                # line 185
    name: str
    version: str
    entities: dict[str, EntityDef]
    relations: dict[str, RelationDef]
    traversal_patterns: dict[str, TraversalPattern]
    layers: list[str]                                                           # list of YAML file paths merged
    merge_timestamp: datetime
    def get_entity_collections(self) -> list[str]: ...                          # line 209
    def get_edge_collections(self) -> list[str]: ...                            # line 213
    def get_vectorizable_fields(self, entity_name: str) -> list[str]: ...       # line 217
    def build_schema_prompt(self) -> str: ...                                   # line 229

class TenantContext(BaseModel):                                                 # line 261
    tenant_id: str
    arango_db: str
    pgvector_schema: str
    ontology: MergedOntology

# packages/ai-parrot/src/parrot/knowledge/ontology/merger.py
class OntologyMerger:                                                           # line 26
    def merge(self, yaml_paths: list[Path]) -> MergedOntology: ...              # line 51
    def merge_definitions(...) -> MergedOntology: ...                           # line 99   ← reuse for in-memory overlay
    def _merge_entities(...) -> dict[str, EntityDef]: ...                       # line 144
    def _extend_entity(...) -> EntityDef: ...                                   # line 162
    def _merge_relations(...) -> dict[str, RelationDef]: ...                    # line 204
    def _validate_relation_endpoints(...) -> None: ...                          # line 233
    def _merge_patterns(...) -> dict[str, TraversalPattern]: ...                # line 253
    def _validate_integrity(self, merged: MergedOntology) -> None: ...          # line 278

# packages/ai-parrot/src/parrot/knowledge/ontology/cache.py
class OntologyCache:                                                            # line 30
    def __init__(self, redis_client: Any = None) -> None: ...                   # line 39
    @staticmethod
    def build_key(tenant_id: str, user_id: str, pattern: str) -> str: ...       # line 43
    async def get(self, key: str) -> EnrichedContext | None: ...                # line 57
    async def set(self, key, value, ttl) -> None: ...                           # line 79
    async def invalidate_tenant(self, tenant_id: str) -> None: ...              # line 99   ← KEY: subscriber calls this
    async def invalidate_all(self) -> None: ...                                 # line 125

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
class OntologyGraphStore:                                                       # line 33
    def __init__(self, arango_client: Any = None) -> None: ...                  # line 49
    async def _get_db(self, ctx: TenantContext) -> Any: ...                     # line 53
    async def initialize_tenant(self, ctx: TenantContext) -> None: ...          # line 71
    async def execute_traversal(...) -> Any: ...                                # line 185
    async def upsert_nodes(...) -> UpsertResult: ...                            # line 225   ← KEY: concept worker calls
    async def create_edges(...) -> UpsertResult: ...                            # line 312   ← KEY: is_a worker call
    async def get_all_nodes(...) -> list[dict[str, Any]]: ...                   # line 386   ← reconcile reverse-scan
    async def soft_delete_nodes(...) -> int: ...                                # line 413   ← deprecation path

# packages/ai-parrot/src/parrot/knowledge/ontology/validators.py
async def validate_aql(...) -> None: ...                                        # line 36   ← used by dry_run

# packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py
class OntologyRefreshPipeline:                                                  # line 61
    def __init__(
        self,
        tenant_manager: TenantOntologyManager,
        graph_store: OntologyGraphStore,
        discovery: RelationDiscovery,
        datasource_factory: Any,
        cache: OntologyCache,
        vector_store: Any = None,
        source_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None: ...                                                              # line 76
    async def run(self, tenant_id: str, domain: str | None = None) -> RefreshReport: ...   # line 94
```

### Configuration References

The following config keys exist (or are expected) in `parrot.conf`:

```python
# packages/ai-parrot/src/parrot/conf.py (verified used in tenant.py:48-54)
ONTOLOGY_DIR                          # base directory for ontology YAML files
ONTOLOGY_BASE_FILE                    # default "base.ontology.yaml"
ONTOLOGY_DOMAINS_DIR                  # default "domains"
ONTOLOGY_CLIENTS_DIR                  # default "clients"
ONTOLOGY_DB_TEMPLATE                  # default "{tenant}_ontology"
ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE     # default "{tenant}"
```

This feature adds (verify exact location in `parrot.conf` before use):

```python
ONTOLOGY_CURATION_PG_DSN                       # asyncdb DSN for curation tables
ONTOLOGY_CURATION_REDIS_URL                    # Redis URL for pub/sub
ONTOLOGY_INVALIDATE_CHANNEL = "ontology:invalidate"   # base channel; per-tenant uses :<tenant_id>
ONTOLOGY_CURATION_OUTBOX_BATCH_SIZE = 50
ONTOLOGY_CURATION_POLL_INTERVAL_S = 60         # fallback polling cadence; primary path is pub/sub
ONTOLOGY_DRY_RUN_TIMEOUT_S = 10
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ConceptCatalogSyncWorker` | `OntologyGraphStore.upsert_nodes()` | direct call | `graph_store.py:225` |
| `ConceptCatalogSyncWorker` | `OntologyGraphStore.create_edges()` | direct call | `graph_store.py:312` |
| `ConceptCatalogSyncWorker` | `OntologyGraphStore.soft_delete_nodes()` | direct call | `graph_store.py:413` |
| `ConceptCatalogSyncWorker` | Redis pub/sub | publish on `ontology:invalidate:<tenant>` | new |
| `SchemaOverlaySyncWorker` | Redis pub/sub | publish on `ontology:invalidate:<tenant>` | new |
| `OntologyCache.subscribe_invalidation` (new) | `TenantOntologyManager.invalidate()` | direct call | `tenant.py:165` |
| `OntologyCache.subscribe_invalidation` (new) | `OntologyCache.invalidate_tenant()` | direct call | `cache.py:99` |
| `TenantOntologyManager.resolve` (extended) | `ConceptCatalogService.get_live_concepts()` | direct call | new |
| `TenantOntologyManager.resolve` (extended) | `SchemaOverlayService` reader (list approved) | direct call | new |
| `TenantOntologyManager.resolve` (extended) | `OntologyMerger.merge_with_overlay()` | direct call | new |
| `SchemaOverlayService.dry_run` | `OntologyMerger.merge_with_overlay()` | direct call | new (sandbox copy) |
| `SchemaOverlayService.dry_run` | `validate_aql()` | direct call | `validators.py:36` |
| `ConceptCatalogService.deprecate` | operational `topic_authority` table read | direct SQL via shared PG pool | will exist after FEAT-topic-authority-operational lands |

### Does NOT Exist (Anti-Hallucination)

- ~~`OntologyMerger.merge_with_overlay`~~ — does not exist; this feature adds it (Module 14).
- ~~`OntologyCache.subscribe_invalidation`~~ — does not exist; this feature adds it (Module 16).
- ~~`TopicAuthorityService`~~ — exists only in FEAT-topic-authority-operational brainstorm; not yet implemented. This feature has a HARD dependency on it landing first for the cascade-on-deprecate notification path.
- ~~`topic_authority` Postgres table~~ — same; brainstorm only. Cascade notification reads from it once FEAT-topic-authority-operational ships.
- ~~`doc_covers_concept` ArangoDB edge collection~~ — defined in FEAT-concept-document-authority brainstorm; not yet created.
- ~~`Concept` entity in `defaults/base.ontology.yaml`~~ — verified absent. The base YAML defines `Employee`, `Department`, `Role`. `Concept` lives only in FEAT-concept-document-authority brainstorm; this feature assumes that feature has landed.
- ~~`FrameworkOverrideError`, `CycleError`, `SynonymConflictError`, `DryRunFailedError`~~ — new exception types this feature adds.
- ~~`OntologyError`~~ — verify base exception class name in `parrot/knowledge/ontology/exceptions.py` before subclassing. The completed task TASK-356-ontology-exceptions confirms this module exists; exact base class to be verified by the implementer.
- ~~`ontology_schema_admin` role~~ — must be added to navigator-auth role catalog by Module 20.
- ~~A `tenant_ontology_version` column~~ — not present today; if a polling-fallback path is implemented (per open question), this column would be added in the migration.
- ~~Existing Redis pub/sub usage inside `OntologyCache`~~ — `OntologyCache` accepts a redis client but uses it for key/value caching only. The subscriber loop is new code.
- ~~`networkx` as an ai-parrot dependency~~ — not present in `pyproject.toml` today; if Module 4 uses it, must be added (otherwise hand-roll DFS for cycle detection).
- ~~A pre-existing `<CurationQueue>` Svelte component~~ — assumed to be extracted from FEAT-topic-authority-operational; if that extraction did not happen, Module 17 either extracts it or duplicates.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Service is the sole SQL writer** (mirrors Seam #1 from FEAT-topic-authority-operational): no raw `INSERT`/`UPDATE` against `ontology_concept*` or `ontology_schema_overlay*` from anywhere else. Enforced by code review.
- **Worker dispatch by operation map + graph identity attributes** (Seam #2): the `OPERATIONS` dict and `GRAPH_*` class attributes are the entire surface that would change for a different curated kind.
- **Audit `diff` and Outbox `payload` are JSONB** (Seam #3): no kind-specific columns in the auxiliary tables.
- **Transactional discipline**: row lock → validate → UPDATE → audit INSERT → outbox INSERT, all in one transaction.
- **`pg_<thing>_id` bridge attribute** on every Arango doc/edge so reconciliation has a reliable Arango↔PG mapping.
- **No auto-repair in reconciliation** — alerts only; humans decide.
- **Pydantic v2 throughout**, `ConfigDict(extra="forbid")`.
- **Async-first**: every external call (`asyncpg`, `python-arango` async client, `redis.asyncio`) is awaited; no blocking in async paths.
- **Google-style docstrings + strict type hints** on every public class/method (per `CLAUDE.md` non-negotiables).
- **`self.logger`** (Python `logging.getLogger("Parrot.Ontology.<sub>")`) — NEVER print statements.

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| **Outbox stall on either worker** blocks visibility of subsequent rows. | Per-message error handling; DLQ after N retries; alert on DLQ growth (same as operational). |
| **is_a cycle introduction**. | Cycle detection on every `propose_isa_edge` AND `approve` (full DAG scan, including framework-tier concept names). Worker never sees a cyclic edge. |
| **Synonym collision races**: two curators propose same synonym for different concepts simultaneously. | `SynonymConflictError` at propose time using `SELECT ... FOR UPDATE` on the synonyms GIN index probe (acceptable contention; synonyms are low-write). |
| **Hot-reload pub/sub miss**: a process briefly disconnected misses the invalidation. | Polling fallback: every `ONTOLOGY_CURATION_POLL_INTERVAL_S` seconds, processes compare `MergedOntology.merge_timestamp` against a per-tenant `latest_approval` timestamp queried from PG. Mismatch triggers local invalidate. Belt-and-braces. |
| **Framework concept override slipping through.** | Defense in depth: (1) UI hides framework rows from edit actions; (2) HTTP layer rejects payloads referencing framework names; (3) `merge_with_overlay()` raises `FrameworkOverrideError` if invariant is violated. Tests cover all three layers. |
| **Cascade alert flood** when deprecating a heavily-used concept. | Single `CascadeAlert` per deprecation operation (one alert object, list of affected edges). Receiver throttles. |
| **PG↔Arango reconciliation false positives** during in-flight outbox processing. | Only flag rows whose `updated_at` is older than `outbox_drain_interval × 10`; in-flight rows ignored. Same posture as operational. |
| **`OntologyMerger.merge_with_overlay` semantic divergence from `merge()`** for empty overlays. | Acceptance criterion: identical output when overlay is empty (regression test). |
| **`networkx` not yet a dep**. | Either add to `pyproject.toml` (preferred for clarity) or implement DFS-based cycle detection inline (saves dep but reinvents wheel; acceptable for small graphs). |
| **Schema overlay dry-run side effects**. | The dry-run uses an ephemeral merger; under no circumstances may it mutate the tenant's real `_cache`. Verified by test (call dry_run; assert `manager.list_tenants()` unchanged). |
| **Concept ID generation strategy unresolved**. | Default: UUID primary key + unique `(tenant_id, slug)` index, where slug is curator-supplied (`sales_commissions`). The Arango `_key` uses the UUID. Confirm in §8. |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncpg` (via `asyncdb`) | already pinned | Postgres access for new curation tables. |
| `python-arango` (async) | already pinned | ArangoDB upserts via `OntologyGraphStore`. |
| `redis` / `redis.asyncio` | already pinned | Pub/sub for cache invalidation. |
| `pydantic` v2 | already pinned | Row + report models. |
| `networkx` | `>=3.0` | OPTIONAL — cycle detection in `is_a` DAG. Hand-rolled DFS is acceptable if we want to avoid the dep. Decide before Module 4 starts. |
| `qworker` | already pinned | Worker scheduling + retry/DLQ. |
| `navigator-auth` | already pinned | Role enforcement on HTTP routes. |
| `aiohttp` | already pinned | HTTP routes. |

---

## 8. Open Questions

> Carried forward from the brainstorm. All eight remain `[ ]` unresolved; each carries a tentative recommendation that is treated as the design baseline in the spec body. Confirm or override during implementation.

- [ ] **Cascade-on-Concept-deprecate semantics.** Block deprecation until dependent edges are handled (a), or succeed and route dependent edges into the operational queue with a `cascade:concept_deprecated` tag (b), or auto-deprecate dependent edges atomically (c)? Spec assumes (b). — *Owner: TBD*
- [ ] **Concept ID generation strategy.** Spec assumes UUID PK + `(tenant_id, slug)` unique index. Confirm slug source (curator-supplied vs derived from label). — *Owner: TBD*
- [ ] **Dry-run depth.** v1 stops at: YAML parse + `merge_with_overlay` + cycle check + `validate_aql` for traversal patterns + framework-override check. Smoke battery of synthetic queries deferred. Confirm. — *Owner: TBD*
- [ ] **nav-admin layout.** Single "Ontology Curation" top-level panel with tabs (Edges / Concepts / Schema), three separate top-level panels, or two (Curation: Edges+Concepts, Admin: Schema)? — *Owner: TBD*
- [ ] **is_a re-parenting.** Spec assumes the same temporal-boundary rule as the operational service: forbidden via modify; must `deprecate` + `propose` new edge. Confirm. — *Owner: TBD*
- [ ] **Materialized YAML export as DR.** Spec defers. Decide whether to schedule a follow-up FEAT. — *Owner: TBD*
- [ ] **Bulk operations on the Concept side.** Bulk-approve a batch of LLM-proposed concepts. Reuse the operational bulk-approve guardrails (sample size, progress bar). Confirm in scope for v1. — *Owner: TBD*
- [ ] **Pub/sub fanout reliability.** Spec includes a polling fallback at `ONTOLOGY_CURATION_POLL_INTERVAL_S` (default 60s). Confirm the interval and confirm that a missed pub/sub message is acceptable for that window. — *Owner: TBD*

---

## Worktree Strategy

- **Default isolation unit**: `mixed`.
- **Sequential foundation** (one worktree, in order): Module 1 (PG migration) → Module 2 (exceptions) → Module 14 (`merge_with_overlay`) → Module 15 (`TenantOntologyManager` extension) → Module 16 (cache pub/sub subscriber).
- **Parallelizable after foundation** (independent worktrees):
  - **Concept-side bundle**: Modules 3, 4, 5, 6, 7, 8.
  - **Schema-side bundle**: Modules 9, 10, 11, 12, 13.
  - **nav-admin bundle**: Modules 17, 18, 19 (depends on HTTP APIs from concept-side and schema-side being stable — coordinate by freezing API contracts before kickoff).
  - **navigator-auth role addition**: Module 20 (trivial, can run any time after Module 1).
- **Cross-feature dependencies**:
  - **HARD**: FEAT-topic-authority-operational must merge first (this feature reuses its outbox/audit conventions, role definitions, and cascade-target tables).
  - **HARD**: FEAT-concept-document-authority must merge first (defines the `Concept` entity that this feature curates).
  - **COORDINATE**: FEAT-ontology-entity-extraction touches `mixin.py` and `tenant.py`; sequence with care or rebase before merge.

- **Rationale**: One shared base must land sequentially because every subsequent module depends on the migration + the extended merger/manager. After that, the two service stacks are completely independent (different tables, different services, different roles) and can build in parallel. UI is gated on stable HTTP contracts but otherwise independent.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-11 | Jesús Lara | Initial draft from `FEAT-topic-authority-ontology` brainstorm (Option B). |
