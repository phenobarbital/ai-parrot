---
feature_id: FEAT-864
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [ontology, testing, ci]
---

# FEAT-864: Ontology vocabulary PostgreSQL live validation

## Problem

The ontology vocabulary PostgreSQL backend (FEAT-824) was never executed
against a live PostgreSQL instance during its implementation. All PG-backed
tests were SKIPPED in the worker sandbox. Commit 88d2269061 fixed five SQL
placeholder-numbering defects discovered via a fake-connection arity test, but
the actual read paths (types, pgvector casts, trigram similarity, FOR UPDATE
publish loop) remain unexecuted against a real server.

Running the tests against PostgreSQL 17 with pgvector + pg_trgm now surfaces
4 failures: test data assumptions that only appear when data actually round-trips
through PG.

**Discovered-from**: `issue:a985902092e3`

## Goal

1. Fix the 4 test failures that surface against a live PostgreSQL.
2. Add a CI job that runs the vocabulary PG tests against a PostgreSQL 17
   service with pgvector + pg_trgm extensions.

## Scope

### In scope
- Fix `test_postgres_reads.py::test_get` — references non-existent `Normativa` IRI
- Fix `test_postgres_reads.py::test_resolve_exact_then_trgm` — references non-existent `Normativa` label
- Fix `store_conformance.py::case_expand_multiple_inheritance` — v2 fixture removed the dual-parent relation the test asserts at current version
- Fix `store_conformance.py::case_export_checksum_roundtrip` — rdflib JSON-LD produces expanded form (flat list without `@context`/`@graph`)
- Add `test-ontology-pg` CI job to `.github/workflows/ci.yml`

### NOT in scope
- Changes to production code (`postgres_store.py`, `publisher.py`) — those work correctly
- New test cases beyond fixing existing ones
- Changes to the snapshot or CLI test suites

## Design

### Test fixes (TASK-5455)

| Test | Fix |
|------|-----|
| `test_get` | Use `LegalEntity` IRI (exists in golden v1) instead of `Normativa` |
| `test_resolve_exact_then_trgm` | Use `"Entidad jurídica"` (exact pref label in v1) and a close misspelling for trigram |
| `case_expand_multiple_inheritance` | The v2 fixture removes the `PublicAuthority → PublicBody` subclass relation. Restore it in `legal_es.v2.ttl` so the dual-parent DAG persists across versions. |
| `case_export_checksum_roundtrip` | rdflib's `json-ld` format produces expanded JSON-LD (a flat list of `@id` objects). Accept `@id` as valid alongside `@context`/`@graph`. |

### CI job (TASK-5456)

New `test-ontology-pg` job in `.github/workflows/ci.yml`:
- PostgreSQL 17 service container with pgvector + pg_trgm
- `ONTOLOGY_PG_DSN` env var pointing at the service
- `uv sync` with `ontology` extra (includes `rdflib`, `pyshacl`)
- Runs `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/ -q`

## Acceptance criteria

1. All vocabulary PG tests pass against a live PostgreSQL 17 with pgvector + pg_trgm.
2. CI job `test-ontology-pg` exists and would run on push/PR to `main`/`dev`.
3. No changes to production code files.
