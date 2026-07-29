---
type: Wiki Overview
title: FEAT-topic-authority-operational — Brainstorm
id: doc:sdd-proposals-feat-topic-authority-operational-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `covers_topic` relation introduced in FEAT-concept-document-authority
  is too operational to live in YAML. This feature implements a Postgres-backed **operational
  truth** with a five-state machine (`proposed → pending_review → approved → deprecated/rejected`),
  a **transactiona
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.knowledge.ontology
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
---

# FEAT-topic-authority-operational — Brainstorm

**Status:** brainstorm
**Type:** operational / data plane
**Dependencies:** FEAT-concept-document-authority, navigator-auth (RBAC), qworker (background tasks + DLQ), asyncdb (Postgres + ArangoDB), nav-admin SvelteKit app shell
**Drives:** future curated-edge feature work (intentionally specific, not generic — see "Three seams" below)
**Owner:** TBD

---

## Summary

The `covers_topic` relation introduced in FEAT-concept-document-authority is too operational to live in YAML. This feature implements a Postgres-backed **operational truth** with a five-state machine (`proposed → pending_review → approved → deprecated/rejected`), a **transactional outbox** syncing approved edges to ArangoDB via a `qworker` task, complete auditability, and curation panels in `nav-admin`.

YAML's role is reduced to three responsibilities: **seeding** new tenants, **defining schema** (entities/relations/patterns at the framework level), and **cross-tenant migrations**.

The design is **deliberately specific** to `topic_authority` rather than introducing a generic `curated_edge` abstraction. Three implementation seams are documented so the future generalization, when a second curated edge type appears, is a straightforward refactor rather than a rewrite.

---

## Motivation

YAML works for static, version-controlled configuration. It does not work for:

- **Per-tenant curation at scale.** 50+ clients each maintaining their own `covers_topic` mappings via PR-to-YAML is impractical.
- **Workflow with approval.** Edges proposed by automated pipelines (LLM/NER batch jobs) need human review before going live. YAML has no notion of state.
- **Audit and rollback.** *"Why did the bot answer with X?"* requires `(actor, timestamp, before, after)` per edge change. Git history is the wrong granularity.
- **Time-bounded validity.** A policy effective from `2025-01-01` cannot be expressed cleanly in YAML.
- **Hot edits.** Curators changing edges should see results in production within seconds, not after a deploy.

---

## Goals

- Postgres tables: `topic_authority` (state), `topic_authority_audit` (history), `topic_authority_outbox` (sync queue).
- Five-state machine with explicit transitions, all audited.
- `TopicAuthorityService` Python API encapsulating all transitions. **No direct SQL** outside the service.
- `TopicAuthoritySyncWorker` (qworker task) draining the outbox into ArangoDB with `SELECT ... FOR UPDATE SKIP LOCKED` and retry/DLQ.
- YAML seeding: `seed_tenant_from_yaml(tenant_id, yaml_path)` — idempotent, marks `asserted_by='seed:yaml@<hash>'`.
- nav-admin panels: review queue, concept browser, document browser, audit log, LLM-proposed batch workflow.
- Nightly reconciliation job: Postgres ↔ ArangoDB consistency check with discrepancy alerts (**no auto-repair**).
- Role-based authorization integrated with navigator-auth: `topic_curator`, `topic_reviewer`, `topic_admin`.

## Non-goals

- **Generic `curated_edge_*` abstraction.** Deliberately specific. Generalization deferred to when a second curated edge type concretely appears.
- **`Concept` lifecycle management UI.** Out of scope; concepts assumed managed via YAML for now.
- **Real-time WebSocket updates to curators.** Polling refresh on a 10s interval is sufficient initially.
- **Cross-tenant edge sharing.** Each tenant's edges are isolated.

---

## Codebase contract

### What exists today

- `asyncdb` for async Postgres + ArangoDB access.
- `qworker` task runtime with retry policy + DLQ infrastructure.
- `navigator-auth` for role-based authorization on aiohttp routes.
- nav-admin SvelteKit 5 + Tailwind 4 + daisyUI app shell with plugin slots.
- ArangoDB `doc_covers_concept` edge collection (after FEAT-concept-document-authority).
- `parrot.knowledge.ontology.tenant.TenantOntologyManager` for tenant resolution.

### What this feature builds

- Postgres migration: three tables + indexes.
- `parrot.knowledge.ontology.topic_authority.service.TopicAuthorityService` — state machine + transactional API.
- `parrot.knowledge.ontology.topic_authority.worker.TopicAuthoritySyncWorker` — qworker sync task.
- `parrot.knowledge.ontology.topic_authority.seed` — YAML seeding command.
- `parrot.knowledge.ontology.topic_authority.reconcile` — nightly reconciliation job.
- HTTP API routes in `parrot.web` (aiohttp) exposing the service to nav-admin.
- nav-admin Svelte routes + components for the four+one panels.

---

## Proposed design

### Schema

```sql
CREATE TABLE topic_authority (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(64)  NOT NULL,
    document_id     VARCHAR(128) NOT NULL,
    concept_id      VARCHAR(128) NOT NULL,

    authority       VARCHAR(16)  NOT NULL
                    CHECK (authority IN ('primary', 'secondary', 'mentions')),
    confidence      REAL         NOT NULL DEFAULT 1.0,
    rationale       TEXT,

    state           VARCHAR(16)  NOT NULL DEFAULT 'proposed'
                    CHECK (state IN ('proposed', 'pending_review',
                                     'approved', 'rejected', 'deprecated')),

    asserted_by     VARCHAR(96)  NOT NULL,
    reviewed_by     VARCHAR(96),
    reviewed_at     TIMESTAMPTZ,

    effective_from  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    effective_to    TIMESTAMPTZ,

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Only one "live" edge per (tenant, doc, concept). Historical versions
-- coexist as deprecated/rejected.
CREATE UNIQUE INDEX uq_topic_authority_live
    ON topic_authority (tenant_id, document_id, concept_id)
    WHERE state IN ('approved', 'pending_review', 'proposed');

CREATE INDEX idx_topic_authority_review_queue
    ON topic_authority (tenant_id, state, created_at)
    WHERE state IN ('proposed', 'pending_review');

CREATE INDEX idx_topic_authority_concept_lookup
    ON topic_authority (tenant_id, concept_id, authority)
    WHERE state = 'approved';


CREATE TABLE topic_authority_audit (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    edge_id     UUID NOT NULL REFERENCES topic_authority(id),
    action      VARCHAR(32) NOT NULL,
    actor       VARCHAR(96) NOT NULL,
    diff        JSONB       NOT NULL,
    reason      TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_edge ON topic_authority_audit (edge_id, occurred_at DESC);


CREATE TABLE topic_authority_outbox (
    id           BIGSERIAL PRIMARY KEY,
    edge_id      UUID NOT NULL,
    operation    VARCHAR(32) NOT NULL,
    payload      JSONB NOT NULL,
    enqueued_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    attempts     INT NOT NULL DEFAULT 0,
    last_error   TEXT
);

CREATE INDEX idx_outbox_unprocessed
    ON topic_authority_outbox (enqueued_at)
    WHERE processed_at IS NULL;
```

### State machine

```
proposed       → pending_review | approved (skip-review by admin) | rejected
pending_review → approved | rejected
approved       → deprecated | approved (metadata-only modify)
rejected       → (terminal)
deprecated     → approved (restore on error)
```

**Hard rules:**

- Changing `authority`, `document_id`, or `concept_id` on an approved edge is **forbidden**. Required path is `deprecate` + new `propose`. The reason: we want to know *when* a document became the authority for something. UPDATE would lose that temporal boundary.
- `rejected` and `deprecated` are immutable as historical records (deprecated can be `restore`d, which creates a new audit entry and re-enters `approved`; the original is preserved).
- All transitions write to `topic_authority_audit` in the **same transaction** as the state update.

### TopicAuthorityService API

```python
class TopicAuthorityService:
    """Operational truth for topic→document authority.

    All state-changing calls follow the same shape:
      1. Acquire row lock (FOR UPDATE).
      2. Validate transition.
      3. UPDATE topic_authority.
      4. INSERT topic_authority_audit.
      5. INSERT topic_authority_outbox.
    All within a single transaction.
    """

    async def propose(
        self,
        tenant_id: str,
        document_id: str,
        concept_id: str,
        authority: str,
        asserted_by: str,
        confidence: float = 1.0,
        rationale: str | None = None,
    ) -> UUID: ...

    async def submit_for_review(self, edge_id: UUID, actor: str) -> None: ...
    async def approve(self, edge_id: UUID, actor: str, reason: str | None = None) -> None: ...
    async def reject(self, edge_id: UUID, actor: str, reason: str | None = None) -> None: ...
    async def deprecate(self, edge_id: UUID, actor: str, reason: str | None = None) -> None: ...
    async def restore(self, edge_id: UUID, actor: str, reason: str | None = None) -> None: ...
    async def modify_metadata(
        self, edge_id: UUID, actor: str,
        confidence: float | None = None, rationale: str | None = None,
    ) -> None: ...

    async def get_live_edges(
        self, tenant_id: str, concept_id: str | None = None,
        authority: str | None = None,
    ) -> list[Edge]: ...

    async def get_history(self, edge_id: UUID) -> list[AuditEntry]: ...
```

Typed exceptions:

- `ConflictError` — live edge already exists for `(tenant, doc, concept)`.
- `InvalidTransitionError` — current state doesn't permit the requested action.
- `EdgeNotFoundError` — edge_id missing.

### TopicAuthoritySyncWorker

```python
class TopicAuthoritySyncWorker:
    OPERATIONS: dict[str, str] = {
        "publish_to_graph":   "_op_publish",
        "deprecate_in_graph": "_op_deprecate",
        "upsert_proposed":    "_op_noop",
    }
    GRAPH_EDGE_COLLECTION = "doc_covers_concept"
    GRAPH_FROM_PREFIX     = "documents"
    GRAPH_TO_PREFIX       = "concepts"

    async def run_once(self, batch_size: int = 50) -> int:
        """Drain a batch of outbox messages with SKIP LOCKED."""
        async with self._pg.transaction():
            rows = await self._pg.fetch(f"""
                SELECT id, edge_id, operation, payload
                FROM topic_authority_outbox
                WHERE processed_at IS NULL
                ORDER BY enqueued_at
                LIMIT {batch_size}
                FOR UPDATE SKIP LOCKED
            """)
            for row in rows:
                try:
                    handler = getattr(self, self.OPERATIONS[row["operation"]])
                    await handler(row)
                    await self._pg.execute(
                        "UPDATE topic_authority_outbox SET processed_at=now() WHERE id=$1",
                        row["id"],
                    )
                except Exception as e:
                    await self._pg.execute("""
                        UPDATE topic_authority_outbox
                        SET attempts = attempts + 1, last_error = $1
                        WHERE id = $2
                    """, str(e), row["id"])
                    raise   # qworker retry policy kicks in
            return len(rows)
```

After `max_attempts`, qworker DLQs to `topic_authority_outbox_dlq`. DLQ growth triggers alert.

**`pg_edge_id` bridge:** every graph edge upserted carries an attribute `pg_edge_id = str(edge.id)`. This is the only reliable way to map Arango ↔ Postgres during debugging and reconciliation.

### Nightly reconciliation

Separate qworker job, runs daily:

1. Scan `topic_authority` rows with `state='approved'` for the tenant.
2. For each, verify a matching edge exists in ArangoDB with the right `pg_edge_id`.
3. Reverse scan: list `doc_covers_concept` edges with `pg_edge_id`; verify each maps to a row in state `approved`.
4. Log all discrepancies. **Do not auto-repair** — alerts go to ops; humans decide.

### YAML seeding

```python
async def seed_tenant_from_yaml(
    tenant_id: str,
    yaml_path: Path,
    service: TopicAuthorityService,
) -> SeedReport:
    """Idempotent: existing edges (any state) are skipped, not modified."""
```

Calls `service.propose()` + `service.approve()` (skip-review path, requires `topic_admin` privileges in the service auth check) with `asserted_by=f"seed:yaml@{yaml_hash}"`. Emits a `SeedReport` of created / skipped / errored.

### HTTP API for nav-admin

aiohttp routes under `/api/topic-authority/`:

| Method | Path | Role required |
|---|---|---|
| GET | `/edges?tenant=&concept=&state=&limit=&offset=` | `topic_curator`+ |
| GET | `/edges/{id}` | `topic_curator`+ |
| GET | `/edges/{id}/history` | `topic_curator`+ |
| POST | `/edges` (propose) | `topic_curator`+ |
| POST | `/edges/{id}/transitions/submit` | `topic_curator`+ |
| POST | `/edges/{id}/transitions/approve` | `topic_reviewer`+ |
| POST | `/edges/{id}/transitions/reject` | `topic_reviewer`+ |
| POST | `/edges/{id}/transitions/deprecate` | `topic_admin` |
| POST | `/edges/{id}/transitions/restore` | `topic_admin` |
| PATCH | `/edges/{id}` (metadata only) | `topic_reviewer`+ |
| POST | `/batch/llm-propose` | `topic_admin` |
| GET | `/reconciliation/report` | `topic_admin` |

All routes scoped by `tenant_id` from the auth session; cross-tenant access denied at the auth layer.

### nav-admin panels

1. **Review Queue** (`/topic-authority/queue`). Highest-traffic page. Lists `proposed` + `pending_review`, grouped by concept. Per-row: doc, concept, authority, `asserted_by`, confidence, rationale. Actions: approve / reject / edit-then-approve / bulk-approve. Filter by `asserted_by` to revisar lotes from a specific pipeline.
2. **Concept Browser** (`/topic-authority/concepts`). Per-concept view, all linked documents with state + authority, full history. Actions: promote secondary→primary (= deprecate old + propose new), deprecate.
3. **Document Browser** (`/topic-authority/documents`). Per-document view, all covered concepts. Assistant: "copy authorities from previous version" when handling a new doc version.
4. **Audit Log** (`/topic-authority/audit`). Filterable read-only. Tenant, edge, actor, action, date range.
5. **LLM Propose Batch** (`/topic-authority/batch`). Kick off a background job: scan unmatched concepts, run extraction pipeline against the tenant's documents, produce a batch of `proposed` edges with `asserted_by='auto:ner_v1'`. Review in the standard Queue.

---

## Three seams for future generalization

These are the **only** intentional preparations for a possible future `CuratedEdgeService` refactor. No abstraction is introduced today; these are disciplined boundaries that cost nothing now and convert the refactor from a week to a day if/when needed.

**Seam #1 — Service is the sole SQL writer.** All transitions go through `TopicAuthorityService`. No `INSERT` / `UPDATE` to `topic_authority*` from elsewhere in the codebase. Enforced by code review + (optionally) a lint check that flags raw SQL against these tables outside the service module. The day generalization arrives, this class becomes a thin subclass of a base; today it's just a class.

**Seam #2 — Worker dispatches by operation map + graph identity attributes.** The `OPERATIONS` dict and `GRAPH_*` class attributes on `TopicAuthoritySyncWorker` are the **entire** surface that would change for a different edge type. Today they're concrete strings; when generalizing, they become abstract attributes on a base class. Zero refactor pain.

**Seam #3 — Audit `diff` and Outbox `payload` are JSONB.** No edge-type-specific columns in these auxiliary tables. Free schema cost today, gratis for the future. Any edge-type-specific fields live in the main `topic_authority` table; the audit/outbox tables stay generic by virtue of JSONB.

**Anti-pattern explicitly avoided:** a generic `edge_type` discriminator column on a shared table. Each curated edge type gets its own table. When the second type appears, it gets `responsible_for` (or whatever it is) as a fresh table with its own state machine variant.

---

## Implementation plan

1. **Postgres migration** — three tables + indexes; migration script + rollback.
2. **`TopicAuthorityService`** with full unit tests covering state machine invariants (cannot approve from `rejected`, cannot modify forbidden fields, uniqueness collisions, etc.).
3. **`TopicAuthoritySyncWorker`** with mock ArangoDB; concurrency tests (two workers running in parallel never double-process).
4. **YAML seeding command** + idempotency tests (run twice → same final state).
5. **HTTP API + navigator-auth integration** — role enforcement tests, tenant scoping tests.
6. **nav-admin Review Queue** — highest user value first.
7. **nav-admin Concept Browser + Document Browser**.
8. **nav-admin Audit Log** (read-only).
9. **Reconciliation job** + alerting integration.
10. **LLM Propose Batch** workflow — depends on FEAT-concept-document-authority's extraction pipeline being ready.

---

## Open questions

- **Document version handoff strategy.** When `Sales_Policy_v3.2` is superseded by `v3.3`, auto-clone approved edges to the new version (with deprecate of old) vs. UI-assisted manual workflow? **Recommendation:** UI-assisted first ("copy authorities" button on Document Browser); revisit auto-propagation when enough data exists to model the heuristic safely.
- **Soft delete vs hard delete of rejected proposals.** Lean toward keeping everything: rejected is a learning signal for the LLM proposal pipeline. Add a retention policy (purge `rejected` after 2 years) if storage becomes an issue.
- **Outbox archiving.** Processed outbox rows are not deleted, archived to `topic_authority_outbox_archive` for replay capability. Confirm operational acceptability with infra; document the storage growth profile (~N edges × ~3 transitions × ~1KB payload).
- **Polling vs SSE/WebSocket for nav-admin.** Polling refresh (10s) initially; consider SSE if curators report stale views. WebSocket is overkill.
- **Bulk-approve UX guardrails.** Should bulk-approve be limited to a sample size (e.g. 50) per request, with progress shown? **Recommendation:** yes, with progress bar — prevents accidental approval of a 10k-edge batch without review.

---

## Acceptance criteria

- A curator proposes an edge; it appears in the Review Queue within one polling cycle.
- A reviewer approves; the corresponding ArangoDB edge appears within outbox drain interval (default 5s).
- A reviewer rejects; no ArangoDB edge is created; audit shows the rejection.
- Two curators concurrently submitting proposals for the same `(tenant, doc, concept)` triple: exactly one succeeds, the other gets `ConflictError`.
- Worker SKIP LOCKED concurrency test: two parallel workers process disjoint subsets of outbox; no message is processed twice.
- Reconciliation job detects an artificially-introduced Arango↔PG discrepancy and emits an alert (does not auto-repair).
- YAML seed run twice on a fresh tenant produces the same final state as run once.
- An LLM-proposed batch of 100 edges lands as `proposed` rows tagged `asserted_by='auto:ner_v1'`; each appears in the Review Queue.
- navigator-auth: a `topic_curator` cannot call the approve endpoint; receives 403.
- Changing `authority` on an approved edge via PATCH is rejected; only `confidence` and `rationale` are modifiable.

---

## Risks

- **Outbox stall.** A bug in `_apply_to_graph` blocks all subsequent edges. **Mitigation:** per-message error handling, DLQ after N retries, alerting on DLQ growth.
- **Race condition on uniqueness.** Two concurrent `propose` calls slip past the uniqueness check before the index catches it. **Mitigation:** transaction isolation + retry on `unique_violation` SQLSTATE 23505.
- **navigator-auth role mismatch.** A curator accidentally gets `topic_admin` privileges. **Mitigation:** principle of least privilege at role creation; UI buttons hidden by role AND double-checked server-side (defense in depth).
- **Outbox table unbounded growth.** Even archived, the table grows. **Mitigation:** monthly archive job; document storage growth profile up front; archive to cold storage after 1 year.
- **Reconciliation false positives.** Brief drift during in-flight outbox processing flagged as discrepancy. **Mitigation:** only flag rows where `effective_from` is more than (outbox_drain_interval × 10) ago; ignore in-flight.

---

## References

- FEAT-ontology-entity-extraction — infrastructure that consumes these edges at query time.
- FEAT-concept-document-authority — defines `Document`, `Concept`, and the `doc_covers_concept` edge collection that this feature populates.
- Outbox pattern: standard transactional outbox for eventual consistency; well-known in distributed systems literature.
