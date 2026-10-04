---
id: F008
query_id: Q008
type: read
intent: Line anchors in contracts.ontology.yaml (header, entity block, relation with properties, field_match relation, traversal pattern with query_template+entity_extraction+authorization, top-level authorization/search_views) plus the Employee link form in base/field_services
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F008 — contracts domain YAML anchors and the base-layer Employee link form

## Summary
`contracts.ontology.yaml` (827 lines) starts with `name/version/extends: base/description`, then has four top-level sections: `entities` (L39), `relations` (L265), `search_views` (L444) and `traversal_patterns` (L466). There is no top-level `authorization` block. Authorization is declared per pattern with OR'ed `has_role` rules and `default_deny: true`. Edge properties are written as a list of single-key maps, the same shape as entity properties. A domain entity links to the base-layer `Employee` with a plain `to: Employee` plus a `field_match` rule on `employee_id` (`is_employee`). `field_services` shows the other form: extending `Employee` itself with `extend: true`.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml`
  lines: 1-4
  symbol: `header`
  excerpt: |
    name: contracts
    version: "1.0"
    extends: base
    description: >
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml`
  lines: 141-167
  symbol: `entities.Party`
  excerpt: |
    Party:
      collection: party
      source: contractcard
      key_field: party_id
      properties:
        - party_id: {type: string, required: true, unique: true}
        - aliases:
            type: list
      vectorize:
        - name
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml`
  lines: 276-286
  symbol: `relations.signed_by`
  excerpt: |
    signed_by:
      from: Contract
      to: Person
      edge_collection: signed_by
      properties:
        - signed_on:
            type: date
        - on_behalf_of:
            type: string
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml`
  lines: 300-310
  symbol: `relations.is_employee`
  excerpt: |
    is_employee:
      from: Person
      to: Employee
      edge_collection: is_employee
      discovery:
        strategy: field_match
        rules:
          - source_field: employee_id
            target_field: employee_id
            match_type: exact
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml`
  lines: 444-464
  symbol: `search_views.contracts_view`
  excerpt: |
    search_views:
      contracts_view:
        links:
          - entity: Contract
            fields:
              - path: "title"
                analyzers: ["text_en"]
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml`
  lines: 466-508
  symbol: `traversal_patterns.contracts_requiring_standard`
  excerpt: |
    query_template: >
      FOR std IN @@compliance_standard
        FILTER std._key == @standard_id
        FOR ob IN 1..1 INBOUND std @@requires
          FILTER ob.active != false AND ob._active != false
    entity_extraction:
      standard: {type: ComplianceStandard, resolver: exact_id_match, scope: same_tenant, ambiguity_strategy: ask_user}
    authorization:
      rules: [{rule: has_role, role: contract_reader}, {rule: has_role, role: contract_owner}]
      default_deny: true
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/base.ontology.yaml`
  lines: 8-38
  symbol: `entities.Employee`
  excerpt: |
    Employee:
      collection: employees
      key_field: employee_id
      properties:
        - employee_id: {type: string, required: true, unique: true}
        - name: ...
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/field_services.ontology.yaml`
  lines: 9-15
  symbol: `entities.Employee (extend)`
  excerpt: |
    Employee:
      extend: true
      properties:
        - project_code:
            type: string
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/field_services.ontology.yaml`
  lines: 93-94
  symbol: `traversal_patterns.find_project`
  excerpt: |
    query_template: >
      FOR v IN 1..1 OUTBOUND @user_id @@assigned_to RETURN v

## Notes
- `Tip→authored_by→Employee` can copy `is_employee` (L300-310): `to: Employee`, edge collection `authored_by`, plus a `field_match` rule `author_employee_id → employee_id`. The `employees` collection comes from the base layer.
- `ComplianceStandard` (L248-250) has no `source:`, so `OntologyRefreshPipeline.run` skips it. Entities that should not be extracted can do the same.
- Patterns read `_active != false` as well as the domain-level `active` flag. Procedures patterns should apply the same filter.

