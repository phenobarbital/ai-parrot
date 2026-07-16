---
type: Wiki Overview
title: FEAT-topic-authority-ontology — Brainstorm
id: doc:sdd-proposals-feat-topic-authority-ontology-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The three sibling brainstorms each leave a deliberate gap:'
relates_to:
- concept: mod:parrot.knowledge.ontology.cache
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog
  rel: mentions
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.mixin
  rel: mentions
- concept: mod:parrot.knowledge.ontology.parser
  rel: mentions
- concept: mod:parrot.knowledge.ontology.refresh
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
- concept: mod:parrot.knowledge.ontology.validators
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# FEAT-topic-authority-ontology — Brainstorm

**Date**: 2026-05-11
**Author**: Jesús Lara
**Status**: exploration
**Type**: ontology curation / data plane
**Dependencies**: FEAT-topic-authority-operational (outbox/audit conventions, navigator-auth roles), FEAT-concept-document-authority (defines `Concept` as a first-class entity), FEAT-ontology-entity-extraction (resolver/dispatcher infra), existing `TenantOntologyManager`, `OntologyMerger`, `OntologyGraphStore`, `OntologyCache`, qworker, asyncdb
**Drives**: completion of the topic-authority trilogy (edges / entities / schema) and unblocks per-tenant ontology evolution at scale
**Recommended Option**: B

---

## Problem Statement

The three sibling brainstorms each leave a deliberate gap:

- **FEAT-concept-document-authority** defines `Document` and `Concept` as YAML entities and the `covers_topic` / `is_a` relations — but treats `Concept` lifecycle as out of scope ("deferred").
- **FEAT-topic-authority-operational** delivers a Postgres-backed state machine for the `covers_topic` edges — but explicitly punts on `Concept` management: *"out of scope; concepts assumed managed via YAML for now."*
- **FEAT-ontology-entity-extraction** consumes the resulting ontology but does not curate it.

Today's `TenantOntologyManager` (`packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:18`) resolves the merged ontology from a three-layer YAML chain (`base → domain → client`). The **only** way to add a `Concept`, change a synonym, introduce a new `is_a` parent, register a new entity type, or extend the merged ontology in any way is a PR against the relevant YAML in `ontologies/clients/<tenant>.ontology.yaml`.

This works at framework scale (a handful of `base` / `domain` YAMLs maintained by core engineers) but breaks at tenant scale:

- **50+ clients each maintaining their own concept catalogs** via PR-to-YAML is the same impracticality the operational brainstorm cites for edges.
- **No approval workflow.** Concept proposals from extraction pipelines (LLM/NER) have nowhere to live in `pending_review` state — YAML has no notion of state.
- **No audit trail.** *"Why did the bot start treating `commissions` as a synonym of `sales_compensation`?"* requires `(actor, timestamp, before, after)` granularity; `git blame` on a deeply nested YAML key is the wrong tool.
- **No hot reload.** A YAML change requires merging the PR, deploying, and restarting agent processes. Curators expect changes to land in seconds.
- **No role separation.** A tenant administrator who needs to add a synonym to `commissions` should not also need the ability to introduce a new entity type — those changes have very different blast radii.

Without a curated catalog layer, FEAT-topic-authority-operational ends up with a state machine for the *edges* but a free-text vocabulary for the *endpoints* — undermining the whole authority signal it set out to protect.

This feature delivers the missing third leg: **Postgres-backed operational truth for `Concept` entities, the `is_a` taxonomy, and per-tenant schema overlays**, with the same five-state machine, audit, outbox, and hot-reload guarantees as the operational brainstorm — but with two **distinct services** (concept data vs schema overlays) reflecting their different change cadences and reviewer profiles.

---

## Constraints & Requirements

- **Framework concepts are immutable at runtime.** Framework concepts ship bundled in `defaults/base.ontology.yaml` and `defaults/domains/*.ontology.yaml`; no UI path can mutate them. Updates ship via PR + release only. Tenant extensions sit on top in PG.
- **Same five-state machine** as FEAT-topic-authority-operational: `proposed → pending_review → approved → deprecated/rejected`. Curators learn one mental model across the trilogy.
- **Two services, two state machines, one infrastructure.** Concept data (`ConceptCatalogService`) and schema overlays (`SchemaOverlayService`) get isolated tables and services but reuse the audit/outbox/qworker patterns introduced by FEAT-topic-authority-operational.
- **Role separation**: `topic_curator` / `topic_reviewer` / `topic_admin` for concept data (reuse from FEAT-topic-authority-operational); `ontology_schema_admin` for schema overlays. Schema-side enforces a **dry-run validation gate** before any `approved` transition.
- **`is_a` is a DAG, cross-tier links allowed.** A tenant concept may `is_a` a framework concept (e.g. `acme:sales_commissions is_a commissions`). Multiple parents allowed. Cycle detection mandatory at every transition.
- **Hot reload on approve**: `OntologyCache.invalidate_tenant(tenant_id)` (`packages/ai-parrot/src/parrot/knowledge/ontology/cache.py:99`) plus a Redis pub/sub signal so all agent processes drop their `TenantOntologyManager._cache` entry for the tenant. Next request re-resolves with the new overlay merged in.
- **Per-tenant isolation.** A tenant cannot read or mutate another tenant's overlays. Cross-tenant denied at the auth layer.
- **YAML layering survives.** The existing `base → domain → client` YAML chain continues to work; PG overlay is added as a **fourth layer** composed after YAML. Existing tenants without PG overlays behave exactly as today.
- **Cascade discipline on Concept deprecation.** A Concept referenced by approved `covers_topic` edges (from FEAT-topic-authority-operational) cannot be hard-deleted; deprecation produces an alert and a worklist of dependent edges that need review.
- **Reuse, do not duplicate, the audit/outbox conventions** introduced by FEAT-topic-authority-operational — including the `pg_edge_id` bridge attribute pattern, the SKIP LOCKED outbox drain, and the DLQ + alert flow.

---

## Options Explored

### Option A: Unified PG store, one schema, kind discriminator

A single Postgres schema with three tables (`ontology_curation`, `ontology_curation_audit`, `ontology_curation_outbox`). Each `ontology_curation` row carries a `kind` discriminator column (`concept_extension | concept_isa_edge | entity_type | relation_type | traversal_pattern`). One state machine handles all kinds; transitions branch on `kind` to validate the right invariants. `TenantOntologyManager.resolve()` composes the YAML chain + a single PG query before passing to `OntologyMerger.merge()`.

✅ **Pros:**
- Smallest table count (~3 vs ~7 for Option B). Lowest migration cost.
- One nav-admin panel covers everything — single mental model for curators.
- Reuses FEAT-topic-authority-operational's `outbox` and `audit` patterns most literally; the JSONB seam (Seam #3) already exists.
- Single audit log queryable across both concept and schema changes — useful for compliance.

❌ **Cons:**
- **Violates the explicit anti-pattern** from FEAT-topic-authority-operational: *"a generic `edge_type` discriminator column on a shared table"* (the operational brainstorm's "Anti-pattern explicitly avoided" section). Repeating the same anti-pattern here would be a directly contradictory architectural choice.
- Concept data churns daily (curators adding synonyms, deprecating concepts, etc.). Schema overlays churn monthly. Forcing them into one table couples their change cadence.
- Different reviewer profiles: a `topic_reviewer` should not be a `ontology_schema_admin`. Sharing one table makes per-kind authorization harder (more conditional checks, no row-level guarantees).
- Cannot enforce per-kind constraints at the database level (e.g., uniqueness, FK to Concept for is_a edges) cleanly with a discriminator.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncpg` via `asyncdb` | PG access | Already in use; standard pool + transaction. |
| `qworker` | Outbox draining | Reuse the same retry/DLQ pattern as FEAT-topic-authority-operational. |
| `navigator-auth` | RBAC | Single role check per request; harder to enforce per-kind. |

🔗 **Existing Code to Reuse:**
- `parrot.knowledge.ontology.tenant.TenantOntologyManager.resolve()` — extend to merge PG overlay.
- `parrot.knowledge.ontology.merger.OntologyMerger.merge()` — accept an in-memory `OntologyDefinition` alongside file paths.

---

### Option B: Two isolated services, two state machines, shared patterns (**recommended**)

Two Postgres schemas / service modules. Each is the sole writer to its own tables, mirroring Seam #1 from the operational brainstorm:

```
parrot/knowledge/ontology/concept_catalog/
  service.py            # ConceptCatalogService
  worker.py             # ConceptCatalogSyncWorker (Postgres → Arango)
  seed.py               # YAML → PG seeding for new tenants
  reconcile.py          # nightly PG↔Arango consistency check
  http.py               # aiohttp routes under /api/ontology/concepts/

parrot/knowledge/ontology/schema_overlay/
  service.py            # SchemaOverlayService
  worker.py             # SchemaOverlaySyncWorker (PG approve → cache invalidate)
  validator.py          # sandboxed dry-run merge + cycle/AQL checks
  http.py               # aiohttp routes under /api/ontology/schema/
```

Tables (~7):

```
ontology_concept                  -- per-tenant Concept rows; framework concepts NEVER appear here
ontology_concept_isa              -- per-tenant is_a edges (DAG; cross-tier allowed)
ontology_concept_audit            -- audit log for both above
ontology_concept_outbox           -- sync queue → Arango `concepts`, `concept_isa`

ontology_schema_overlay           -- per-tenant overlay entries (new entity types, relations, traversal patterns)
ontology_schema_audit             -- audit log
ontology_schema_outbox            -- sync queue → cache invalidation signal
```

Two service classes with the same shape as `TopicAuthorityService` from FEAT-topic-authority-operational:

- `ConceptCatalogService` — `propose / submit_for_review / approve / reject / deprecate / restore / modify_metadata` plus is_a-specific `propose_isa_edge / deprecate_isa_edge`. Approve runs cycle detection across the full per-tenant DAG (framework + tenant nodes).
- `SchemaOverlayService` — same transitions, plus a `dry_run(overlay)` method invoked **automatically** between `pending_review` and `approved`. The dry-run sandboxes a `TenantOntologyManager.resolve()` against an ephemeral merger, runs `validate_aql` on every traversal pattern, and rejects the transition if anything fails.

`TenantOntologyManager.resolve()` is extended to compose the YAML chain + PG overlay layer into the `OntologyMerger.merge()` call. Cache invalidation publishes on a Redis pub/sub channel (`ontology:invalidate:<tenant_id>`) and every process subscribes via `OntologyCache.invalidate_tenant()`.

✅ **Pros:**
- **Honors the operational brainstorm's anti-pattern guidance**: each curated kind gets its own table. Consistent architecture across the trilogy.
- Different change cadences live in different services — schema can enforce its dry-run gate without polluting the concept-data path.
- Role separation is enforced both at the API layer (different aiohttp prefixes) and at the table level (no shared rows, no risk of a misconfigured admin clobbering Concept data while editing schema).
- Per-table constraints are first-class: unique `(tenant_id, label)` on concepts, FK from `ontology_concept_isa.child_id` to `ontology_concept.id`, partial indexes per state — none of which is clean with a discriminator.
- Easy to evolve independently: if schema overlays need a stricter approval (e.g., two-reviewer rule) later, that lives entirely in `SchemaOverlayService`.

❌ **Cons:**
- More tables (7 vs 3). More boilerplate in migrations.
- UI duplication risk: two review-queue pages, two audit views. Mitigation: extract shared Svelte components (`<CurationQueue>`, `<AuditTable>`, `<TransitionDialog>`) and parameterize by service.
- Two outbox workers running on the same qworker fleet — operational complexity slightly higher (two metrics dashboards instead of one).

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncpg` via `asyncdb` | PG access | Two pools? No — single pool, two schemas. |
| `qworker` | Outbox draining (×2 workers) | Same retry/DLQ policy as operational; one DLQ per worker. |
| `navigator-auth` | RBAC | Two role groups — `topic_*` for concept side, `ontology_schema_admin` for schema side. |
| `redis.asyncio` | Pub/sub for cache invalidation | Already a dependency for `OntologyCache`. |
| `networkx` | Cycle detection in is_a DAG | Pure-Python, MIT, very mature. Optional — a hand-rolled DFS is also fine; networkx is convenience. |

🔗 **Existing Code to Reuse:**
- `parrot.knowledge.ontology.tenant.TenantOntologyManager` (`tenant.py:18`) — extend `.resolve()` to compose PG overlay; `.invalidate(tenant_id)` already exists.
- `parrot.knowledge.ontology.merger.OntologyMerger.merge()` (`merger.py:51`) — new `merge_with_overlay(yaml_paths, overlay_def)` variant.
- `parrot.knowledge.ontology.cache.OntologyCache.invalidate_tenant()` (`cache.py:99`) — already supports per-tenant invalidation; this feature subscribes it to pub/sub.
- `parrot.knowledge.ontology.graph_store.OntologyGraphStore.upsert_nodes / create_edges` (`graph_store.py:225, 312`) — used by `ConceptCatalogSyncWorker` to materialize approved concepts/edges in Arango.
- `parrot.knowledge.ontology.validators.validate_aql` (`validators.py:36`) — used by `SchemaOverlayService.dry_run()` for traversal patterns.
- All `topic_authority_*` patterns from FEAT-topic-authority-operational: outbox, audit, SKIP LOCKED drain, `pg_edge_id` bridge attribute, DLQ alerting.

---

### Option C: PG-light + materialized YAML

Live curation goes through PG state machines like Option B, **but** on approve a worker materializes the merged result as a frozen YAML file on disk (`ontologies/clients/<tenant>.materialized.yaml`). YAML remains the runtime source of truth; PG is the curation surface only. `TenantOntologyManager` is unchanged — it just keeps reading YAML files.

✅ **Pros:**
- `TenantOntologyManager` resolution logic is **literally unchanged**. Lowest blast radius against existing code.
- Materialized YAML doubles as cold backup, disaster-recovery artifact, and rollback target (just check out an older revision).
- Curators with read access to the filesystem can `diff` between tenant versions trivially.
- "What is currently live?" question answered by `cat`, not a join.

❌ **Cons:**
- Two sources of truth (PG + materialized YAML) bridged by a worker. The worker IS the source of bugs the operational brainstorm warns about (outbox stalls block visibility).
- Materialization lag is a real consistency window — operator approves at 14:00, file lands at 14:00:05, agent reads stale ontology at 14:00:02. Acceptable, but documentation burden.
- Where does the materialized YAML live? In-repo (commits churn massively) or a separate volume (one more piece of infra to operate, monitor, back up)?
- Doubles the storage cost of "the current state of the ontology" — once in PG, once on disk.
- Schema overlay dry-run still needs PG; the materialization adds nothing for that side.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pyyaml` | YAML emit | Already a dependency for ontology parsing. |
| `asyncpg` / `qworker` | Same as Option B. | — |

🔗 **Existing Code to Reuse:**
- `parrot.knowledge.ontology.parser.OntologyParser` — could grow an `emit()` companion for materialization.

---

### Option D (unconventional): Ontology-of-the-ontology in ArangoDB

Store concept entries, is_a edges, and schema overlay records **as graph nodes in ArangoDB itself** (`ConceptDef`, `EntityTypeDef`, `RelationTypeDef`). State machine implemented as Arango document fields; audit log lives in a separate Arango collection. `TenantOntologyManager` reads the graph at resolution time instead of (or alongside) YAML.

✅ **Pros:**
- Conceptually elegant — the ontology of the ontology IS the graph itself. Eat your own dog food.
- Removes the PG↔Arango outbox bridge for these specific entities (they live where they need to be queried).
- Cycle detection on is_a is "free" — Arango AQL handles it via `K_SHORTEST_PATHS`-style queries on the meta-graph.

❌ **Cons:**
- Arango's transactional guarantees are coarser than PG for state-machine workloads. Multi-document transactions require either a single-shard topology or stream transactions, both of which add operational complexity.
- No equivalent of `SELECT ... FOR UPDATE SKIP LOCKED` — implementing a contention-safe outbox is hard.
- Loses PG features that the operational brainstorm relies on: partial indexes (`WHERE state IN ('approved', 'pending_review', 'proposed')`), unique constraints with partial conditions, native JSONB, row-level role enforcement via row-security policies.
- Diverges from FEAT-topic-authority-operational's PG-first pattern — fragments the mental model and the on-call playbook.
- Audit log compliance: PG's `WAL` + `INSERT-only audit table` is the well-understood compliance baseline; Arango audit story is custom-built.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-arango` | Arango access | Already in use via `OntologyGraphStore`. |

🔗 **Existing Code to Reuse:**
- `parrot.knowledge.ontology.graph_store.OntologyGraphStore` — would need extensive extension for the meta-graph + audit collection.

---

## Recommendation

**Option B** — two isolated services with their own tables and state machines, sharing patterns (audit/outbox/qworker/navigator-auth) but not data.

The decisive arguments:

1. **Architectural consistency with FEAT-topic-authority-operational.** The operational brainstorm explicitly rejects a generic discriminator column as an anti-pattern. Option A would directly contradict that decision. The trilogy should land coherent; Option B is the only choice that does.
2. **Change cadence honesty.** Concept data churns daily; schema overlays churn monthly. Forcing one workflow onto both either over-engineers the concept side (heavy dry-run gates on every synonym change) or under-secures the schema side (no dry-run before merging a new entity type that the LLM will start reasoning about). Two services let each enforce its appropriate gates.
3. **Role separation as a first-class concern.** `topic_reviewer` and `ontology_schema_admin` are very different roles. Two services with two role groups mirror that organizational reality; one service with a single role group would push permission checks into conditional code, where mistakes hide.
4. **Database-level constraints.** Per-table uniqueness, partial indexes per state, FK from is_a to Concept — all clean with Option B, all gymnastic with Option A.
5. **Independent evolution.** When schema overlays inevitably need a stricter workflow (two-reviewer, mandatory dry-run, change-windows), that change lives entirely in `SchemaOverlayService`. Option A would require carving out a separate path inside a shared service.

What we're trading off: ~4 extra tables, two outbox workers instead of one, two nav-admin queue pages instead of one. Mitigation: shared Svelte components and a shared abstract base for the two worker classes (purely an internal refactor — externally still two distinct workers). Both costs are bounded and one-time.

Option C (materialized YAML) is the second-best choice. We pass on it because (a) the schema-side dry-run still needs PG, so Option C doesn't eliminate the PG dependency it appears to; and (b) the operational brainstorm already commits to PG-first for the trilogy — adding YAML materialization for one feature out of three fragments the model.

Option D is interesting but pays heavy operational complexity for a conceptual win that doesn't surface to curators or developers.

---

## Feature Description

### User-Facing Behavior

Three new nav-admin panels live alongside the operational panels:

1. **Concept Catalog Queue** (`/ontology/concepts/queue`). Lists `proposed` + `pending_review` concept entries grouped by tenant. Per-row: label, synonyms, description, domain, `asserted_by`, rationale. Same actions as the operational Review Queue: approve / reject / edit-then-approve / bulk-approve. Filter by `asserted_by` to triage batch-proposed concepts from extraction pipelines.
2. **Concept Browser** (`/ontology/concepts`). Per-tenant view of all approved concepts. Shows `is_a` ancestors and descendants, linked documents (cross-link to the operational `covers_topic` data), synonyms, and history. Actions: propose synonym, propose new is_a parent, deprecate (with cascade warning), restore.
3. **Schema Overlay** (`/ontology/schema`). Schema-admin-only panel listing proposed and approved overlay entries (new entity types, relations, traversal patterns). Diff view against the current merged ontology. Dry-run results visible before approving — if the dry-run fails, the entry stays in `pending_review` with the failure message attached.

A `topic_curator` can never see the Schema Overlay panel (navigator-auth route guard + UI hidden by role).

Hot-reload visible: a curator approves a Concept synonym change; within 1–2 seconds, agents reasoning over `acme`'s ontology see the new synonym (via `OntologyCache.invalidate_tenant` + Redis pub/sub propagation). No deploy, no restart.

### Internal Behavior

**Resolution path** (`TenantOntologyManager.resolve(tenant_id, domain)`):

1. Build YAML chain `base → domain → client` (unchanged).
2. Parse each file via existing `OntologyParser`.
3. **New:** fetch the tenant's approved PG overlay — concepts, is_a edges, schema overlay entries — and convert them into in-memory `OntologyDefinition` instances (one per layer: `pg_overlay_concepts`, `pg_overlay_schema`).
4. Pass the full chain to `OntologyMerger.merge_with_overlay(yaml_paths, [pg_overlay_concepts, pg_overlay_schema])`.
5. Merger composes layers in order; tenant PG layer wins last-write-wins on tenant-extensible fields, but **cannot mutate framework entities** (validation enforced at merge time — attempting to override `base.Concept.label` raises `FrameworkOverrideError`).
6. Return `TenantContext(tenant_id, arango_db, pgvector_schema, ontology=merged)`.
7. Cache the result in `_cache` (already there).

**State transitions** (mirrors operational service):

1. Acquire row lock (`FOR UPDATE`).
2. Validate transition (state machine).
3. **Concept-side only:** if changing `is_a` parentage, run cycle detection on the candidate DAG (existing approved is_a edges + this candidate).
4. **Schema-side only:** if transitioning to `approved`, run `dry_run()` — sandboxed merge + `validate_aql` for every traversal pattern in the overlay. Roll back if dry-run fails.
5. `UPDATE` the row.
6. `INSERT` audit row.
7. `INSERT` outbox row.
All within a single transaction.

**Outbox draining**:

- `ConceptCatalogSyncWorker` materializes approved concept rows into Arango `concepts` collection via `OntologyGraphStore.upsert_nodes`, approved is_a edges into `concept_isa` via `create_edges`, deprecations via `soft_delete_nodes`. Each materialized doc carries `pg_concept_id` / `pg_isa_edge_id` for the same Arango↔PG bridge convention the operational worker uses.
- `SchemaOverlaySyncWorker` publishes a Redis pub/sub message (`ontology:invalidate:<tenant_id>`) and writes to `ontology_schema_outbox` with `processed_at`. Every running agent process subscribes; the subscriber calls `TenantOntologyManager.invalidate(tenant_id)` + `OntologyCache.invalidate_tenant(tenant_id)`. Next request rebuilds from the new state.

…(truncated)…
