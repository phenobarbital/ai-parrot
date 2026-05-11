-- ============================================================
-- FEAT-159: Topic-Authority Ontology Curation
-- Forward migration: all 7 ontology curation tables + indexes
-- ============================================================

-- ── Concept catalog ──

CREATE TABLE ontology_concept (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(64)  NOT NULL,
    slug            VARCHAR(128) NOT NULL,
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
CREATE INDEX idx_ontology_concept_synonyms
    ON ontology_concept USING gin (synonyms)
    WHERE state = 'approved';


CREATE TABLE ontology_concept_isa (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(64)  NOT NULL,
    child_id        UUID         NOT NULL REFERENCES ontology_concept(id),
    parent_tier     VARCHAR(16)  NOT NULL CHECK (parent_tier IN ('framework','tenant')),
    parent_ref      VARCHAR(256) NOT NULL,

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
    target_id   UUID         NOT NULL,
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
    target_kind  VARCHAR(16)  NOT NULL,
    operation    VARCHAR(32)  NOT NULL,
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
    name            VARCHAR(128) NOT NULL,
    definition      JSONB        NOT NULL,

    state           VARCHAR(16)  NOT NULL DEFAULT 'proposed'
                    CHECK (state IN ('proposed','pending_review','approved','rejected','deprecated')),

    asserted_by     VARCHAR(96)  NOT NULL,
    reviewed_by     VARCHAR(96),
    reviewed_at     TIMESTAMPTZ,
    rationale       TEXT,
    dry_run_report  JSONB,

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
    operation    VARCHAR(32)  NOT NULL,
    payload      JSONB        NOT NULL,
    enqueued_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    attempts     INT          NOT NULL DEFAULT 0,
    last_error   TEXT
);

CREATE INDEX idx_ontology_schema_outbox_unprocessed
    ON ontology_schema_outbox (enqueued_at)
    WHERE processed_at IS NULL;
