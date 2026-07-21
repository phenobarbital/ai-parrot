---
type: Wiki Overview
title: 'Feature Specification: Topic-Authority Ontology Curation'
id: doc:sdd-specs-topic-authority-ontology-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The three sibling brainstorms in the topic-authority trilogy leave a deliberate
  gap:'
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.knowledge.ontology.cache
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.http
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.reconcile
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.seed
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.service
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.worker
  rel: mentions
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.refresh
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.http
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.service
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.validator
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.worker
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
- concept: mod:parrot.knowledge.ontology.validators
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Topic-Authority Ontology Curation

**Feature ID**: FEAT-159
**Date**: 2026-05-11
**Author**: Jesús Lara
**Status**: approved
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

…(truncated)…
