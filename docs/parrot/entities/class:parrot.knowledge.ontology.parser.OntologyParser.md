---
type: Wiki Entity
title: OntologyParser
id: class:parrot.knowledge.ontology.parser.OntologyParser
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Load and validate ontology YAML files against Pydantic schema models.
---

# OntologyParser

Defined in [`parrot.knowledge.ontology.parser`](../summaries/mod:parrot.knowledge.ontology.parser.md).

```python
class OntologyParser
```

Load and validate ontology YAML files against Pydantic schema models.

Usage::

    parser = OntologyParser()
    definition = parser.load(Path("ontologies/base.ontology.yaml"))

## Methods

- `def load(path: Path) -> OntologyDefinition` — Load a YAML file and parse it into an OntologyDefinition.
- `def load_from_dict(data: dict[str, Any]) -> OntologyDefinition` — Parse an OntologyDefinition from an already-loaded dict.
- `def load_default_base() -> OntologyDefinition` — Load the base ontology from package-bundled defaults.
- `def get_defaults_dir() -> Path` — Return the path to the package-bundled defaults directory.
