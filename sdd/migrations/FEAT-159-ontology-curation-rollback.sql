-- ============================================================
-- FEAT-159: Topic-Authority Ontology Curation
-- Rollback migration: drops all 7 tables in reverse dependency order
-- ============================================================

-- Schema side (no FK deps on concept side)
DROP INDEX IF EXISTS idx_ontology_schema_outbox_unprocessed;
DROP TABLE IF EXISTS ontology_schema_outbox;

DROP INDEX IF EXISTS idx_ontology_schema_audit_overlay;
DROP TABLE IF EXISTS ontology_schema_audit;

DROP INDEX IF EXISTS idx_ontology_schema_overlay_review_queue;
DROP INDEX IF EXISTS uq_ontology_schema_overlay_live;
DROP TABLE IF EXISTS ontology_schema_overlay;

-- Concept side (outbox/audit first, then isa, then concept)
DROP INDEX IF EXISTS idx_ontology_concept_outbox_unprocessed;
DROP TABLE IF EXISTS ontology_concept_outbox;

DROP INDEX IF EXISTS idx_ontology_concept_audit_target;
DROP TABLE IF EXISTS ontology_concept_audit;

DROP INDEX IF EXISTS idx_ontology_concept_isa_child;
DROP TABLE IF EXISTS ontology_concept_isa;

DROP INDEX IF EXISTS idx_ontology_concept_synonyms;
DROP INDEX IF EXISTS idx_ontology_concept_approved_lookup;
DROP INDEX IF EXISTS idx_ontology_concept_review_queue;
DROP INDEX IF EXISTS uq_ontology_concept_live;
DROP TABLE IF EXISTS ontology_concept;
