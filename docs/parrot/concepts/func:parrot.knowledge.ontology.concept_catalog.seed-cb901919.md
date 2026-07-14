---
type: Concept
title: seed_concepts_from_yaml()
id: func:parrot.knowledge.ontology.concept_catalog.seed.seed_concepts_from_yaml
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Seed concept rows from a YAML ontology file.
---

# seed_concepts_from_yaml

```python
async def seed_concepts_from_yaml(tenant_id: str, yaml_path: Path, service: ConceptCatalogService) -> int
```

Seed concept rows from a YAML ontology file.

Reads each ``entity`` defined in the YAML and proposes + approves it as a
concept in the catalog.  The seed is idempotent: if a concept with the same
``(tenant_id, slug)`` already exists (in any state), it is skipped.

``asserted_by`` is set to ``"seed:yaml@<sha256[:12]>"`` so audit logs can
trace every row back to the source file and its content hash.

is_a edges are seeded *after* all concepts, so parent IDs are available.
YAML hierarchy is encoded as ``parent_entity`` or ``parent`` keys on each
entity block (non-standard extension; falls back to no edge if absent).

Args:
    tenant_id: Tenant to seed concepts into.
    yaml_path: Path to the ontology YAML file.
    service: ``ConceptCatalogService`` instance (already connected to pool).

Returns:
    Number of new concepts actually seeded (skipped rows not counted).

Raises:
    FileNotFoundError: If ``yaml_path`` does not exist.
    yaml.YAMLError: If the file cannot be parsed.
