---
id: FC-006
query_id: Q006
type: grep
intent: "Is there any RDF / Turtle / SKOS / OWL / IRI notion or dependency already in the repository?"
executed_at: 2026-11-06T13:37:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-006 — No RDF, Turtle, SKOS, OWL or IRI anywhere in source or dependency declarations

## Summary

No matches found. `grep -rnilE "rdflib|pyshacl|turtle|skos|owl:|\biri\b" packages/*/src --include="*.py"` returned zero files, and `grep -nE "rdflib|pyshacl|owlready|oxigraph" pyproject.toml packages/*/pyproject.toml` returned zero lines. The draft's whole OntologyStore pipeline (Turtle in git → rdflib parse → pyshacl validate → IRI-keyed tables → Turtle export, `owl:deprecated` / `dcterms:isReplacedBy`, SKOS labels) is therefore **entirely greenfield**: there is no existing Turtle corpus to import, no IRI scheme, and two new third-party dependencies (`rdflib`, `pyshacl`).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/base.ontology.yaml`
  lines: 1-12
  symbol: `base` ontology header (the format that exists instead)
  excerpt: |
    name: base
    version: "1.0"
    entities:
      Employee:
        collection: employees
        key_field: employee_id

## Notes

- Commands run (both empty):
  - `grep -rnilE "rdflib|pyshacl|turtle|skos|owl:|\biri\b" packages/*/src --include="*.py"`
  - `grep -nE "rdflib|pyshacl|owlready|oxigraph" pyproject.toml packages/*/pyproject.toml`
- Consequence for migration §9.1 of the draft ("export Arango concept collections to Turtle, publish as v1"): the mapping YAML/Arango → Turtle has no precedent in the code, and the identifiers available today are `(tenant_id, slug)` / UUID for concepts (FC-008) and `collection/key` for instances (FC-001), not IRIs.
- [cross-lane: type=wiki_query, intent=did any prior spec (ontological-graph-rag, topic-authority-ontology, FEAT-159) consider and reject RDF/OWL/SKOS, and why]
