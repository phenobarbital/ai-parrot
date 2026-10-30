---
id: F023
query_id: Q043
type: glob
intent: "Ontology default domains — an existing 'domain' notion that experts might reuse or collide with."
executed_at: 2026-10-30T16:46:28Z
duration_ms: 200
parent_id: null
depth: 0
merged_from: [FC-024-ontology-domains]
---

# F023 — Four bundled ontology "domains" ship as YAML: contracts, field_services, legal, procedures (`knowledge/ontology/defaults/domains/`)

## Summary

4 files: `contracts.ontology.yaml` (28K), `procedures.ontology.yaml` (20K), `legal.ontology.yaml` (7K, FEAT-449 BOE legislation vocabulary: norma/articulo/materia), `field_services.ontology.yaml` (3K). Each has `name`, `version`, `description` and declares entities/relations. This is an existing, bundled, versioned Tier-1 "domain knowledge" artifact the expert bundle can reference (`knowledge: - source: ontology`) and a naming collision risk for the word *domain*.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml`
  lines: 1-6
  symbol: `legal ontology header`
  excerpt: |
    name: legal
    version: "1.1"
    description: >
      Legal Norms Graph domain (FEAT-449, Sprints 1 + 1.5/2). Declares the BOE
      (Boletin Oficial del Estado) consolidated-legislation vocabulary:

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml`
  lines: 1
  symbol: `contracts ontology`
  excerpt: |
    (28.1K — contracts domain)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/procedures.ontology.yaml`
  lines: 1
  symbol: `procedures ontology`
  excerpt: |
    (20.0K)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/field_services.ontology.yaml`
  lines: 1
  symbol: `field_services ontology`
  excerpt: |
    (2.8K)

## Notes

Contracts + legal already have both an ontology and a hand-built agent (FC-029) — strongest migration candidates.
