# TASK-371: Default Ontology YAML Files

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2h)
**Depends-on**: TASK-360, TASK-362
**Assigned-to**: —

---

## Context

> Create base ontology YAML and example domain ontology that ship as package resources.
> Implements spec Module 17.

---

## Scope

### Create `parrot/knowledge/ontology/defaults/base.ontology.yaml`

Base ontology with universal entities and relations:

**Entities:**
- `Employee` — collection: `employees`, key_field: `employee_id`, properties: employee_id, name, email, job_title, department, location. Vectorize: `job_title`.
- `Department` — collection: `departments`, key_field: `department_id`, properties: department_id, name, description.
- `Role` — collection: `roles`, key_field: `role_id`, properties: role_id, name, description.

**Relations:**
- `reports_to` — Employee → Employee, edge: `reports_to`, discovery: exact match on `manager_id` → `employee_id`.
- `belongs_to` — Employee → Department, edge: `belongs_to_dept`, discovery: exact match on `department` → `department_id`.
- `has_role` — Employee → Role, edge: `has_role`, discovery: fuzzy match on `job_title` → `name` (threshold: 0.80).

**Traversal Patterns:**
- `find_manager` — triggers: `["my manager", "who is my manager", "reports to"]`, AQL: traverse reports_to from employee.
- `find_department` — triggers: `["my department", "which department"]`, AQL: traverse belongs_to from employee.

### Create `parrot/knowledge/ontology/defaults/domains/field_services.ontology.yaml`

Domain extension for field services:

**Entities (extend Employee):**
- Add `project_code` property to Employee.

**New Entities:**
- `Project` — collection: `projects`, key_field: `project_id`, properties: project_id, name, client, portal_url. Vectorize: `name`.
- `Portal` — collection: `portals`, key_field: `portal_id`, properties: portal_id, name, url, description. Vectorize: `description`.

**Relations:**
- `assigned_to` — Employee → Project, discovery: exact match on `project_code` → `project_id`.
- `has_portal` — Project → Portal, discovery: exact match on `portal_id` field.

**Traversal Patterns:**
- `find_portal` — triggers: `["my portal", "what is my portal", "how to access portal"]`, AQL: Employee → assigned_to → Project → has_portal → Portal, post_action: `vector_search`, post_query: `portal_url`.

---

## Acceptance Criteria

- [ ] `base.ontology.yaml` parses and validates against `OntologyDefinition` schema.
- [ ] `field_services.ontology.yaml` uses `extend: true` for Employee and parses correctly.
- [ ] Merging base + field_services produces a valid `MergedOntology`.
- [ ] All traversal patterns have valid trigger_intents and AQL templates.
- [ ] Unit test: load defaults → merge → validate integrity.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/defaults/base.ontology.yaml` | **Create** |
| `parrot/knowledge/ontology/defaults/domains/field_services.ontology.yaml` | **Create** |
