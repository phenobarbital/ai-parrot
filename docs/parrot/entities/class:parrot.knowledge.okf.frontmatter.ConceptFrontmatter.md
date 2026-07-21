---
type: Wiki Entity
title: ConceptFrontmatter
id: class:parrot.knowledge.okf.frontmatter.ConceptFrontmatter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic v2 model for the deterministic frontmatter projection.
---

# ConceptFrontmatter

Defined in [`parrot.knowledge.okf.frontmatter`](../summaries/mod:parrot.knowledge.okf.frontmatter.md).

```python
class ConceptFrontmatter(BaseModel)
```

Pydantic v2 model for the deterministic frontmatter projection.

Field order here determines YAML output order (dict insertion order,
Python 3.7+, preserved by ``model_dump()``).

Attributes:
    type: Ontological type (controlled vocabulary).
    title: Human-readable concept title.
    id: Stable concept_id (link target, filename stem).
    node_id: Structural position in the tree (volatile, for debugging only).
    resource: Canonical URI ``pageindex://<tree>/<concept_id>``.
    tags: Alphabetically sorted free-namespace tags.
    timestamp: ISO-8601 timestamp string from the node.
    summary: Embedding target text (reuses FEAT-199 value, D11).
    relates_to: Typed edge list.
    source: Optional per-node provenance.
