---
type: Wiki Summary
title: parrot.knowledge.ontology.exceptions
id: mod:parrot.knowledge.ontology.exceptions
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Custom exceptions for the Ontological Graph RAG system.
relates_to:
- concept: class:parrot.knowledge.ontology.exceptions.AQLValidationError
  rel: defines
- concept: class:parrot.knowledge.ontology.exceptions.CycleError
  rel: defines
- concept: class:parrot.knowledge.ontology.exceptions.DataSourceValidationError
  rel: defines
- concept: class:parrot.knowledge.ontology.exceptions.DryRunFailedError
  rel: defines
- concept: class:parrot.knowledge.ontology.exceptions.FrameworkOverrideError
  rel: defines
- concept: class:parrot.knowledge.ontology.exceptions.InvalidTransitionError
  rel: defines
- concept: class:parrot.knowledge.ontology.exceptions.OntologyError
  rel: defines
- concept: class:parrot.knowledge.ontology.exceptions.OntologyIntegrityError
  rel: defines
- concept: class:parrot.knowledge.ontology.exceptions.OntologyMergeError
  rel: defines
- concept: class:parrot.knowledge.ontology.exceptions.SynonymConflictError
  rel: defines
- concept: class:parrot.knowledge.ontology.exceptions.UnknownDataSourceError
  rel: defines
---

# `parrot.knowledge.ontology.exceptions`

Custom exceptions for the Ontological Graph RAG system.

## Classes

- **`OntologyError(Exception)`** — Base exception for all ontology-related errors.
- **`OntologyMergeError(OntologyError)`** — Raised during YAML merge when rules are violated.
- **`OntologyIntegrityError(OntologyError)`** — Raised during post-merge integrity validation.
- **`AQLValidationError(OntologyError)`** — Raised when LLM-generated AQL fails safety validation.
- **`UnknownDataSourceError(OntologyError)`** — Raised by DataSourceFactory when a source name cannot be resolved.
- **`DataSourceValidationError(OntologyError)`** — Raised by ExtractDataSource.validate() when the source schema doesn't match.
- **`FrameworkOverrideError(OntologyError)`** — Raised when an overlay attempts to mutate a framework entity, relation, or pattern.
- **`CycleError(OntologyError)`** — Raised when an is_a edge would create a cycle in the concept DAG.
- **`SynonymConflictError(OntologyError)`** — Raised when a synonym conflicts with an existing approved concept synonym.
- **`DryRunFailedError(OntologyError)`** — Raised when a schema overlay dry-run fails validation.
- **`InvalidTransitionError(OntologyError)`** — Raised when a state-machine transition is not permitted.
