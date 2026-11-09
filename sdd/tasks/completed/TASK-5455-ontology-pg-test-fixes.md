# TASK-5455: Fix vocabulary PG test failures against live PostgreSQL

- **Feature**: ontology-pg-live-validation
- **Feature ID**: FEAT-864
- **Spec**: sdd/specs/ontology-pg-live-validation.spec.md
- **Status**: pending
- **Priority**: high
- **Estimated effort**: small
- **Depends-on**: []

## Context

Running the vocabulary test suite against PostgreSQL 17 + pgvector + pg_trgm
exposes 4 failures that were invisible when the tests were always SKIPPED.

**Discovered-from**: `issue:a985902092e3`

## Scope

Fix 4 test/fixture files so all vocabulary PG tests pass against a live server.

### NOT in scope
- Changes to production code (`postgres_store.py`, `publisher.py`)
- New test cases

## Files to Modify

- `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_reads.py`
- `packages/ai-parrot/tests/knowledge/ontology/vocabulary/store_conformance.py`
- `packages/ai-parrot/tests/knowledge/ontology/vocabulary/fixtures/legal_es.v2.ttl`

## Codebase Contract

### Verified Imports
- `from parrot.knowledge.ontology.vocabulary.contracts import OntologyStore` — exists
- `from parrot.knowledge.ontology.vocabulary.exceptions import OntologyVersionNotFound` — exists

### Existing Signatures
- `PostgresOntologyStore.get(self, ontology_id, iri, *, as_of=None) -> ConceptRef | None` — verified
- `PostgresOntologyStore.resolve(self, ontology_id, term, *, lang=None, k=10, kinds=None, embedding=None) -> list[Resolution]` — verified
- `PostgresOntologyStore.expand(self, ontology_id, iris, *, family="subclass", direction="down", max_depth=None, include_deprecated=False, as_of=None) -> set[str]` — verified

## Implementation Notes

### test_get (line 66-88)
Replace `"https://ontology.parrot.dev/legal_es/Normativa"` with
`"https://ontology.parrot.dev/legal_es/LegalEntity"` (a class IRI that exists
in the golden v1 fixture).

### test_resolve_exact_then_trgm (line 92-110)
Replace `"Normativa"` with `"Entidad jurídica"` (an exact pref label in v1,
lang=es). Replace the trigram misspelling `"Normtiva"` with `"Entiad jurídica"`.

### case_expand_multiple_inheritance (store_conformance.py:95-103)
The v2 fixture removed the `PublicAuthority rdfs:subClassOf PublicBody` triple.
Restore it in `legal_es.v2.ttl` so the dual-parent DAG persists through v2.

### case_export_checksum_roundtrip (store_conformance.py:117-127)
rdflib's `json-ld` serializer produces expanded JSON-LD (a flat list of `@id`
objects, no `@context`/`@graph`). Update the assertion to also accept `@id`:
```python
assert b'"@context"' in jsonld_data or b"@graph" in jsonld_data or b'"@id"' in jsonld_data
```

## Acceptance Criteria

1. `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_store.py test_postgres_reads.py test_publisher.py test_temporal_fidelity.py test_pg_schema.py` — all pass against a live PG.
2. No production code changed.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_store.py packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_reads.py packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_publisher.py packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_temporal_fidelity.py packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_pg_schema.py -v --timeout=60
```

## Completion Note

_To be filled on completion._
