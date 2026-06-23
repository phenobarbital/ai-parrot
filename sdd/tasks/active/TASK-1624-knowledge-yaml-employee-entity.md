# TASK-1624: Verify and Harden Employee Entity in knowledge.ontology.yaml

**Feature**: FEAT-255 — Ontology RAG + Employee Knowledge Base
**Spec**: `sdd/specs/ontology-rag-kb.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

NAV-8350 requests an Employee Knowledge Base that injects employee data into
agent user context. The `parrot/knowledge/ontology/defaults/knowledge.ontology.yaml`
currently defines Document and Concept entities but does NOT define Employee.

This task adds an Employee entity (with team, department, role, manager fields)
and a `reports_to` relation to `knowledge.ontology.yaml` so that ontology-aware
agents can traverse employee graphs.

---

## Scope

- Inspect current `knowledge.ontology.yaml` (done: Document + Concept only)
- Add `Employee` entity with fields: `employee_id` (key), `name`, `email`,
  `department`, `team`, `role`, `manager_id`
- Add `reports_to` relation: Employee → Employee (edge_collection: `emp_reports_to`)
- Add `member_of` relation: Employee → Team if Team entity exists or add Team entity
- Add a traversal pattern `employee_team_workload` that answers
  "What is my team working on?" queries
- Verify the YAML still validates against `OntologyDefinition` (use existing parser tests)

**NOT in scope**: ArangoDB population, HR data extractor, production deployment.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/knowledge.ontology.yaml` | MODIFY | Add Employee entity, Team entity, reports_to / member_of relations |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.parser import OntologyParser  # verified: parrot/knowledge/ontology/parser.py
from parrot.knowledge.ontology.schema import OntologyDefinition, EntityDef  # verified: parrot/knowledge/ontology/schema.py
```

### Existing Signatures to Use

```python
# parrot/knowledge/ontology/schema.py
class EntityDef(BaseModel):
    collection: str | None = None
    source: str | None = None
    key_field: str | None = None
    properties: list[dict[str, PropertyDef]] = []
    vectorize: list[str] = []
    extend: bool = False

class RelationDef(BaseModel):
    from_entity: str = Field(alias="from")
    to_entity: str = Field(alias="to")
    edge_collection: str
```

### Does NOT Exist

- ~~`EmployeeKBToolkit`~~ — not a real class
- ~~`parrot.knowledge.employee`~~ — no such module

---

## Implementation Notes

The YAML must match the schema defined in `parrot/knowledge/ontology/schema.py`.
Employee `key_field` should be `employee_id`. Use `extend: false` since Employee
is a new entity not overriding a base entity.

---

## Acceptance Criteria

- [ ] `knowledge.ontology.yaml` contains `Employee` entity with `employee_id`, `name`, `email`, `department`, `team`, `role`
- [ ] `reports_to` relation exists: Employee → Employee
- [ ] YAML parses without error via `OntologyParser`
- [ ] Merged ontology (base + knowledge) passes integrity validation

---

## Completion Note

*(Agent fills this in when done)*
