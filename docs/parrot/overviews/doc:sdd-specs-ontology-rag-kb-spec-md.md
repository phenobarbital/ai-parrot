---
type: Wiki Overview
title: 'Feature Specification: Ontology RAG + Employee Knowledge Base'
id: doc:sdd-specs-ontology-rag-kb-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'NAV-8350 asks whether two capabilities exist in the parrot framework:'
relates_to:
- concept: mod:parrot.knowledge
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.mixin
  rel: mentions
- concept: mod:parrot.knowledge.ontology.parser
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Ontology RAG + Employee Knowledge Base

**Feature ID**: FEAT-255
**Date**: 2026-06-24
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Jira**: NAV-8350

---

## 1. Motivation & Business Requirements

> This spec confirms that the `parrot/knowledge` module already implements both
> requested capabilities and documents the current state for traceability.

### Problem Statement

NAV-8350 asks whether two capabilities exist in the parrot framework:

1. **Ontology RAG** — Graph-first retrieval-augmented generation that traverses
   entity relationships before vector search.
2. **Employee Knowledge Base** — Injecting per-user employee data (teams, roles,
   project assignments) into the agent's user context.

### Findings

Both capabilities are **already implemented** in `parrot/knowledge/`:

| Capability | Implementation | FEAT |
|---|---|---|
| Ontology RAG core (schema, merger, graph store, intent, mixin) | `parrot/knowledge/ontology/` | FEAT-053 |
| Entity extraction & tool-call dispatch for employee queries | `parrot/knowledge/ontology/entity_resolver.py`, `tool_dispatcher.py` | FEAT-158 |
| Ontology graph RAG advisor agent example (Gorilla Sheds) | `examples/shoply/` | FEAT-071 |
| Knowledge ontology YAML (base + domain overlays) | `parrot/knowledge/ontology/defaults/` | FEAT-053 |
| OKF knowledge layer (lint, bundle, concept catalog) | `parrot/knowledge/ontology/concept_catalog/` | FEAT-216 |

The `parrot/knowledge/ontology/defaults/knowledge.ontology.yaml` ships a built-in
ontology that can model Employee entities and their relationships.

### Goals

Since both features exist, this spec drives **gap analysis and integration hardening**:

1. **Verify** `OntologyRAGMixin` can answer employee-centric queries (e.g. "What
   is my team working on?") end-to-end without silent failures.
2. **Document** how to configure the employee KB via `knowledge.ontology.yaml`
   and inject employee data from an HR data source.
3. **Add an integration smoke test** that exercises the employee ontology path.
4. **Update Jira NAV-8350** with triage findings.

### Non-Goals (explicitly out of scope)

- Implementing a new Ontology RAG engine (already done in FEAT-053/158).
- Building a UI for the KB.
- Real-time HR data sync (CRON refresh pipeline already exists in FEAT-053).

---

## 2. Architectural Design

### Overview

The existing `parrot/knowledge` module tree is:

```
parrot/knowledge/
├── __init__.py
├── graphindex/          # Graph-index extraction + community signals
├── ontology/
│   ├── schema.py        # Pydantic models (EntityDef, RelationDef, …)
│   ├── parser.py        # YAML → OntologyDefinition
│   ├── merger.py        # Multi-layer YAML merge (base → domain → client)
│   ├── graph_store.py   # ArangoDB operations
│   ├── intent.py        # Dual-path intent resolver
│   ├── mixin.py         # OntologyRAGMixin — hooks into ask()
│   ├── tenant.py        # TenantOntologyManager
│   ├── refresh.py       # CRON delta sync
│   ├── cache.py         # Redis cache helpers
│   ├── validators.py    # AQL safety validation
│   ├── entity_resolver.py   # Named-entity → graph node (FEAT-158)
│   ├── tool_dispatcher.py   # post_action: tool_call dispatch (FEAT-158)
│   └── defaults/
│       ├── base.ontology.yaml
│       ├── knowledge.ontology.yaml   # Employee KB ontology
│       └── domains/field_services.ontology.yaml
└── pageindex/           # Page-index RAG
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OntologyRAGMixin` | consumed | Agent inherits to get graph-first RAG |
| `TenantOntologyManager` | consumed | Resolves merged ontology per tenant |
| `OntologyRefreshPipeline` | consumed | CRON delta sync from HR data source |
| `knowledge.ontology.yaml` | extended | Employee entity definitions live here |
| `parrot/loaders/extractors/` | consumed | CSVDataSource / SQLDataSource for HR data |

### Data Models (already exist — FEAT-053)

```python
# parrot/knowledge/ontology/schema.py
class EntityDef(BaseModel): ...     # Employee, Team, Project, …
class RelationDef(BaseModel): ...   # reports_to, member_of, assigned_to, …
class OntologyDefinition(BaseModel): ...
class MergedOntology(BaseModel): ...
```

---

## 3. Module Breakdown

### Module 1: Employee Ontology YAML Hardening

- **Path**: `parrot/knowledge/ontology/defaults/knowledge.ontology.yaml`
- **Responsibility**: Verify Employee entity definition includes `name`, `email`,
  `department`, `team` properties and `reports_to` / `member_of` relations. Add
  missing properties if any.
- **Depends on**: FEAT-053 (schema already validated)

### Module 2: Integration Smoke Test

- **Path**: `tests/knowledge/test_employee_ontology_smoke.py`
- **Responsibility**: Load `knowledge.ontology.yaml`, merge with `base.ontology.yaml`,
  verify Employee entity is present with required properties. No ArangoDB required
  (schema-only test).
- **Depends on**: Module 1

### Module 3: NAV-8350 Jira Comment

- **Path**: Jira issue NAV-8350
- **Responsibility**: Post a comment on NAV-8350 documenting that both Ontology RAG
  (FEAT-053/158) and Employee KB (knowledge.ontology.yaml) already exist, with
  pointers to the relevant specs and module paths.
- **Depends on**: None

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_knowledge_yaml_loads` | Module 1 | `knowledge.ontology.yaml` parses without error |
| `test_employee_entity_present` | Module 1 | `Employee` entity in merged ontology |
| `test_employee_required_properties` | Module 2 | `name`, `email` properties present |
| `test_reports_to_relation` | Module 2 | `reports_to` relation references Employee |

### Integration Tests

| Test | Description |
|---|---|
| `test_merge_base_plus_knowledge` | Merge base + knowledge ontologies; assert no integrity errors |

### Test Data / Fixtures

```python
@pytest.fixture
def knowledge_ontology():
    from parrot.knowledge.ontology.parser import OntologyParser
    return OntologyParser.load_default("knowledge")
```

---

## 5. Acceptance Criteria

- [x] `parrot/knowledge` module exists at `packages/ai-parrot/src/parrot/knowledge/`
- [x] `OntologyRAGMixin` exists in `parrot/knowledge/ontology/mixin.py`
- [x] `knowledge.ontology.yaml` exists in `parrot/knowledge/ontology/defaults/`
- [ ] `knowledge.ontology.yaml` includes Employee entity with `name`, `email`, `department`, `team`
- [ ] Integration smoke test passes: `pytest tests/knowledge/test_employee_ontology_smoke.py -v`
- [ ] NAV-8350 updated with triage findings and pointers to FEAT-053/FEAT-158

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.knowledge.ontology.schema import OntologyDefinition, EntityDef, MergedOntology
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.mixin import OntologyRAGMixin
```

### Existing Class Signatures

```python
# parrot/knowledge/ontology/mixin.py
class OntologyRAGMixin:
    async def ontology_process(self, query: str, user_context: dict, tenant_id: str) -> dict: ...
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.employee_kb`~~ — does not exist as a separate module; Employee KB is part of `knowledge.ontology.yaml`
- ~~`EmployeeKBToolkit`~~ — not a real class; use `OntologyRAGMixin` instead

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- YAML ontology files must validate against `OntologyDefinition` Pydantic schema.
- Merge via `OntologyMerger.merge([base, knowledge])` — use `extend: true` on Employee if extending base entities.
- Async-first throughout.

### Known Risks / Gotchas

- `OntologyRAGMixin.ontology_process` previously required positional args `(query, user_context, tenant_id)` — FEAT-158 fixed the silent-failure bug in `IntentRouterMixin._run_graph_pageindex`.
- ArangoDB not required for schema-level tests.

---

## 8. Open Questions

- [ ] Does the current `knowledge.ontology.yaml` already define Employee? — *Owner: Jesus Lara*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-24 | Claude (SDD research agent) | Initial draft — triage spec for NAV-8350 |
