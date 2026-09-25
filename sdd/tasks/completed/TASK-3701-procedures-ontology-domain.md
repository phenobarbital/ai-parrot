# TASK-3701: procedures.ontology.yaml + manuals/domain.py tenant manager (M3)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3699
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3** (U5, R4, Q1, F011). The procedure graph needs its own ontology domain (`extends: base`):
vertex collections the loader owns (equipment → step → media …), the **technician-owned** tip collections the loader
must never reconcile (U3), typed edge properties, the base-layer `Employee` link via `field_match`, and one traversal
pattern per read shape — each with `has_role` authorization and `default_deny: true` (AC10). `domain.py` provides the
**dedicated** `TenantOntologyManager` over the packaged defaults dir (the only way the YAML resolves — F011, AC11) and the
owned/technician collection tuples that TASK-3710/3712 key off.

Parallelism: `domain.py` lives in the `parrot.knowledge.manuals` package whose `__init__.py` TASK-3699 creates; YAML
property names are checked against TASK-3699 model fields in `test_domain.py`.

---

## Scope

- Create `procedures.ontology.yaml` with the entities, relations and traversal patterns in spec §3 M3.
- Create `manuals/domain.py`: `PROCEDURES_DOMAIN`, `OWNED_VERTEX_COLLECTIONS`, `OWNED_EDGE_COLLECTIONS`,
  `TECHNICIAN_COLLECTIONS`, `TECHNICIAN_ROLE`, `CURATOR_ROLE`, `REQUIRED_ENTITIES`, `ProceduresDomainNotLoaded`,
  `default_tenant_manager`, `resolve_context`.
- Write `tests/knowledge/manuals/test_domain.py`.

**NOT in scope**: AQL execution (TASK-3720); graph writes (TASK-3712); any `certified_for` relation or custom rule kind
(R4 — forbidden); changing `OntologyRefreshPipeline` or `ontology/__init__.py` (FEAT-540 in flight).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/procedures.ontology.yaml` | CREATE | Procedures vocabulary, relations, patterns |
| `packages/ai-parrot/src/parrot/knowledge/manuals/domain.py` | CREATE | Domain constants, dedicated tenant manager, domain check |
| `packages/ai-parrot/tests/knowledge/manuals/test_domain.py` | CREATE | YAML validity, authorization, collection disjointness |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.parser import OntologyParser        # ontology/parser.py:29 (load, static :29-35), get_defaults_dir :93-99
from parrot.knowledge.ontology.tenant import TenantOntologyManager # ontology/tenant.py:29 (class), __init__ :48-60, resolve :92-131
from parrot.knowledge.ontology.merger import OntologyMerger        # ontology/merger.py:29; merge(yaml_paths: list[Path]) -> MergedOntology :54
from parrot.knowledge.ontology.schema import TenantContext, OntologyDefinition, AuthorizationRule, AuthorizationSpec  # schema.py:529, 419, 176, 212
import yaml                                                         # used the same way by tests/knowledge/contracts/test_ontology_domain.py:16
```

### Existing Signatures to Use
```python
# ontology/schema.py
class PropertyDef(BaseModel):   # :18  type Literal["string","int","float","boolean","date","list","dict"]; required; unique; default; enum; description; extra="forbid" (:37)
class EntityDef(BaseModel):     # :40-63 collection, source, key_field, properties: list[dict[str, PropertyDef]], vectorize, extend; extra="forbid"
class RelationDef(BaseModel):   # :114-140 from (alias) / to (alias) / edge_collection / properties / discovery; extra="forbid"
class DiscoveryRule(BaseModel): # :80-97 source_field, target_field, match_type Literal["exact","fuzzy","ai_assisted","composite"]
class AuthorizationRule(BaseModel):  # :176-210 rule Literal["target_is_self","target_in_management_chain","has_role","same_department","always"]; role required for has_role (:198-208)
class AuthorizationSpec(BaseModel):  # :212-226 rules: list[AuthorizationRule]; default_deny: bool = True — OR semantics
class TraversalPattern(BaseModel):   # :261-295 description (required), trigger_intents, query_template (required), post_action, entity_extraction, authorization, tool_call
class OntologyDefinition(BaseModel): # :419-446 name, version, extends, description, entities, relations, traversal_patterns, search_views; extra="forbid"
class MergedOntology(BaseModel):     # :452+ entities / relations / traversal_patterns dicts
class TenantContext(BaseModel):      # :529-545 tenant_id, arango_db, pgvector_schema, ontology: MergedOntology
# ontology/tenant.py
TenantOntologyManager.resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext   # :92-131 — cache keyed by tenant_id ONLY (:104-106);
    # domain file looked up at ontology_dir / domains_dir / f"{domain}.ontology.yaml"; missing file ⇒ debug log, base-only ontology (silent!)
# ontology/defaults/base.ontology.yaml
Employee: collection employees, key_field employee_id   # :9-13
# knowledge/contracts/graph_loader.py  (pattern to copy — do not import)
class ContractsDomainNotLoaded(RuntimeError)                        # :102
def _default_tenant_manager(ontology_dir) -> TenantOntologyManager(ontology_dir=Path(ontology_dir) if ontology_dir else OntologyParser.get_defaults_dir())   # :215-222
async def context(self): missing = {…} - set(ctx.ontology.entities) → raise ContractsDomainNotLoaded   # :226-245
# ontology/defaults/domains/contracts.ontology.yaml  (YAML shapes to copy)
header name/version/extends :1-3; entity Party :141-167; relations with properties :266-298; field_match is_employee :300-310;
pattern with active guards + authorization :467-509 (FILTER x.active != false AND x._active != false)
```

### Does NOT Exist
- ~~Domain YAML auto-discovery from `defaults/domains/`~~ — only through `ontology_dir=OntologyParser.get_defaults_dir()` (F011).
- ~~A `certified_for` rule kind / relation, or AND composition in `AuthorizationChecker`~~ — five fixed OR-evaluated kinds (R4, AC10).
- ~~`from parrot.knowledge.ontology import …` (package root)~~ — forbidden, import submodules (AC17, FEAT-540).
- ~~A `Tip` entity with `source:`~~ — technician collections have **no** `source:` so the refresh pipeline skips them (contracts precedent: `ComplianceStandard` :248-263 has none).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/procedures.ontology.yaml", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/domain.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_domain.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/parser.py#OntologyParser",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py#TenantOntologyManager",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/merger.py#OntologyMerger",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py#TenantContext",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py#OntologyDefinition",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py#ContractsDomainNotLoaded"
  ]
}
```

---

## Implementation Notes

### Vocabulary (fixed by spec §3 M3 — property names MUST equal the TASK-3699 model fields)
| Entity | collection | key_field | source | properties (beyond key) |
|---|---|---|---|---|
| Equipment | equipment | equipment_id | manualcard | model, family, revision, aliases(list); vectorize [model] |
| Manual | manual | manual_id | manualcard | revision, source_sha256, active(boolean), versions(list) |
| Procedure | procedure | procedure_id | manualcard | manual_id, slug, kind(enum ProcedureKind), title, estimated_minutes(int), skill_level, active(boolean), verification(enum), versions(list); vectorize [title] |
| Step | step | step_id | manualcard | procedure_id, order(int), source_identity, content_hash, text, torque, duration_minutes(int), applies_models(list), applies_serial_ranges(list), node_id, page(int), active(boolean) |
| Part | part | part_id | manualcard | part_number, name |
| Tool | tool | tool_id | manualcard | name, spec |
| Hazard | hazard | hazard_id | manualcard | severity(enum), text |
| Media | media | media_id | manualcard | kind(enum), storage_key, uri, page(int), caption, label, t_start(float), t_end(float), origin, unresolved_callouts(list); vectorize [caption] |
| Tip | tech_tip | tip_id | — (none) | text, origin, author_employee_id, created_at(date), active(boolean), orphaned(boolean), source_revision, attached_step_id, history(list) |

Relations (edge_collection = relation name): `documents` Manual→Procedure; `assembles` Procedure→Equipment; `has_step`
Procedure→Step [order(int)]; `precedes` Step→Step [kind(string)]; `requires_part` Step→Part [quantity(int), contexts(list)];
`requires_tool` Step→Tool; `warns` Step→Hazard; `illustrated_by` Step→Media [roles(list), confidence(float), origin(string)];
`overview_media` Procedure→Media; `depicts` Media→Part [callouts(list), confidence(float), origin(string)]; `shares_module`
Equipment→Equipment [module(string)]; `supersedes` Procedure→Procedure; `tech_tip_on` Tip→Step [linked_by(string),
linked_at(date)]; `tech_tip_by` Tip→Employee with `discovery: {strategy: field_match, rules: [{source_field: author_employee_id,
target_field: employee_id, match_type: exact}]}`.

Patterns: `procedure_steps`, `procedure_prerequisites`, `procedures_for_equipment`, `step_detail`, `equipment_sharing_module`,
`procedure_in_force`, `tips_for_procedure`, `part_for_callout`, `verification_queue_procedures`. Every `query_template`
filters `x.active != false AND x._active != false` on every vertex it returns, uses `@@collection` binds (never literal
collection names) and returns plain projections. Read patterns authorize `has_role technician` OR `has_role manual_curator`;
`verification_queue_procedures` authorizes **only** `manual_curator`; all `default_deny: true`. `tips_for_procedure` also filters
`tip.orphaned != true`.

- `default_tenant_manager()` must create a **new** manager each call — never shared with another domain, because the resolve
  cache is keyed by tenant only (`tenant.py:104-106`). `resolve_context` raises `ProceduresDomainNotLoaded` when
  `REQUIRED_ENTITIES = {"Procedure", "Step", "Media", "Tip"}` is not ⊆ `ctx.ontology.entities`.
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`. The YAML
  is resolved from the *installed source tree* — locate it via `Path(domain.__file__)`-relative or
  `OntologyParser.get_defaults_dir()` exactly like `tests/knowledge/contracts/test_ontology_domain.py:24-28`.

---

## Implementation Blueprint

### Steps (in order)
1. Write `domain.py` — *why*: the tuples are the single source of truth for owned vs technician collections (AC5).
2. Write the YAML following the tables above and the example block — *why*: property names must match models so the datasource snapshot projects cleanly.
3. Write tests: parse + merge with base, every pattern authorized, owned ∩ technician = ∅, YAML collections == tuples.

### `packages/ai-parrot/src/parrot/knowledge/manuals/domain.py` (CREATE)
```python
"""Procedures ontology domain wiring (FEAT-601 M3).

The packaged ``procedures.ontology.yaml`` only resolves through a
``TenantOntologyManager`` built on the package defaults dir (F011). Never
share that manager with another domain: its resolve cache is keyed by
tenant id only.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.ontology.tenant import TenantOntologyManager

logger = logging.getLogger(__name__)

PROCEDURES_DOMAIN = "procedures"
OWNED_VERTEX_COLLECTIONS: tuple[str, ...] = ("equipment", "manual", "procedure", "step", "part", "tool", "hazard", "media")
OWNED_EDGE_COLLECTIONS: tuple[str, ...] = (
    "documents", "assembles", "has_step", "precedes", "requires_part", "requires_tool", "warns",
    "illustrated_by", "overview_media", "depicts", "shares_module", "supersedes",
)
TECHNICIAN_COLLECTIONS: tuple[str, ...] = ("tech_tip", "tech_tip_on", "tech_tip_by")   # never reconciled by the loader
TECHNICIAN_ROLE = "technician"
CURATOR_ROLE = "manual_curator"
REQUIRED_ENTITIES: frozenset[str] = frozenset({"Procedure", "Step", "Media", "Tip"})


class ProceduresDomainNotLoaded(RuntimeError):
    """The resolved tenant ontology does not contain the procedures domain."""


def default_tenant_manager(ontology_dir: str | Path | None = None) -> TenantOntologyManager:
    """Build a procedures-only tenant manager over the packaged defaults (or ``ontology_dir``).

    Args:
        ontology_dir: Override directory holding ``base.ontology.yaml`` and ``domains/``.

    Returns:
        A new, unshared :class:`TenantOntologyManager`.
    """
    return TenantOntologyManager(ontology_dir=Path(ontology_dir) if ontology_dir else OntologyParser.get_defaults_dir())


def resolve_context(manager: TenantOntologyManager, tenant_id: str) -> TenantContext:
    """Resolve the procedures context for ``tenant_id``.

    Raises:
        ProceduresDomainNotLoaded: When the merged ontology lacks :data:`REQUIRED_ENTITIES`
            (misconfigured ontology_dir or a manager shared with another domain).
    """
    ctx = manager.resolve(tenant_id, domain=PROCEDURES_DOMAIN)
    # FILL IN: missing = REQUIRED_ENTITIES - set(ctx.ontology.entities); raise with an actionable message
    #   (copy the wording of contracts/graph_loader.py:236-243); log debug on success
    return ctx
```
**Why**: identical failure mode to contracts (`graph_loader.py:215-245`) so a silent base-only ontology fails loudly (AC11).

### `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/procedures.ontology.yaml` (CREATE)
```yaml
name: procedures
version: "1.0"
extends: base
description: >
  Equipment procedure graph (FEAT-601). Vocabulary the ManualCard is projected
  into by the ManualGraphLoader. Technician-owned collections (tech_tip,
  tech_tip_on, tech_tip_by) are declared so initialize_tenant creates them,
  but they carry no `source:` and are never reconciled by the loader.
  Authorization is tenant-wide has_role technician / manual_curator (Q1).

entities:
  Step:
    collection: step
    source: manualcard
    key_field: step_id
    properties:
      - step_id: {type: string, required: true, unique: true, description: Minted immutable step identity (R1)}
      - procedure_id: {type: string, required: true}
      - order: {type: int, required: true}
      - source_identity: {type: string}
      - content_hash: {type: string, required: true, description: Exact-equality hash (never similarity)}
      - text: {type: string, required: true}
      - torque: {type: string}
      - duration_minutes: {type: int}
      - applies_models: {type: list}
      - applies_serial_ranges: {type: list}
      - node_id: {type: string}
      - page: {type: int}
      - active: {type: boolean, default: true}
  # FILL IN: Equipment, Manual, Procedure, Part, Tool, Hazard, Media, Tip per the vocabulary table — bounded by AC10 (extra="forbid")

relations:
  has_step:
    from: Procedure
    to: Step
    edge_collection: has_step
    properties:
      - order: {type: int}
  tech_tip_by:
    from: Tip
    to: Employee
    edge_collection: tech_tip_by
    discovery:
      strategy: field_match
      rules:
        - {source_field: author_employee_id, target_field: employee_id, match_type: exact}
  # FILL IN: the remaining 12 relations per the relations list — bounded by "no certified_for" (R4)

traversal_patterns:
  procedure_steps:
    description: Ordered steps of one active procedure with their evidence anchors.
    trigger_intents: [how do i assemble, cómo ensamblo, steps for, pasos para]
    query_template: >
      FOR p IN @@procedure
        FILTER p._key == @procedure_id AND p.active != false AND p._active != false
        FOR s, e IN 1..1 OUTBOUND p @@has_step
          FILTER s.active != false AND s._active != false
          SORT e.order
          RETURN { procedure: p, step: s, order: e.order }
    post_action: none
    authorization:
      rules:
        - {rule: has_role, role: technician}
        - {rule: has_role, role: manual_curator}
      default_deny: true
  # FILL IN: procedure_prerequisites, procedures_for_equipment, step_detail, equipment_sharing_module, procedure_in_force,
  #   tips_for_procedure (orphaned != true), part_for_callout, verification_queue_procedures (curator only)
```
**Why**: the example rows fix the exact YAML shapes (inline mappings are valid for `list[dict[str, PropertyDef]]`);
the rest follows the tables so the executor never invents a property or a rule kind.

### FILL IN checklist
- [ ] `resolve_context` — missing-entity check + message
- [ ] YAML — 8 remaining entities, 12 remaining relations, 8 remaining patterns; active guards; `@@` binds
- [ ] tests below

---

## Acceptance Criteria

- [ ] `OntologyParser.load(procedures.ontology.yaml)` validates under `extra="forbid"`; merges with base via `OntologyMerger().merge([...])` (AC10)
- [ ] Every traversal pattern has `authorization.default_deny: true` and a `has_role` rule; curator-only patterns exclude `technician` (AC10)
- [ ] No relation or rule named `certified_for` (AC10)
- [ ] YAML vertex/edge collections == `OWNED_* ∪ TECHNICIAN_COLLECTIONS`; `OWNED_* ∩ TECHNICIAN_COLLECTIONS == ∅` (AC5)
- [ ] `default_tenant_manager()` resolves `procedures`; a manager on a foreign dir makes `resolve_context` raise `ProceduresDomainNotLoaded` (AC11)
- [ ] Ontology imports use submodules only (AC17)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_domain.py -q`
- `pytest packages/ai-parrot/tests/knowledge/contracts/test_ontology_domain.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_domain.py
from pathlib import Path

import pytest
import yaml

from parrot.knowledge.manuals import domain
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.parser import OntologyParser

DEFAULTS = OntologyParser.get_defaults_dir()
YAML_PATH = DEFAULTS / "domains" / "procedures.ontology.yaml"


def test_procedures_yaml_parses_extra_forbid():
    definition = OntologyParser.load(YAML_PATH)
    assert definition.name == "procedures"
    merged = OntologyMerger().merge([DEFAULTS / "base.ontology.yaml", YAML_PATH])
    assert {"Procedure", "Step", "Media", "Tip", "Employee"} <= set(merged.entities)


def test_collections_match_domain_tuples_and_are_disjoint():
    ...


def test_patterns_authorization_has_role():
    """Every pattern default_deny + has_role; verification_queue_procedures excludes technician."""


def test_no_certified_for_anywhere():
    assert "certified_for" not in YAML_PATH.read_text()


def test_every_pattern_guards_active():
    ...


def test_domain_resolves_only_with_defaults_dir(tmp_path):
    ctx = domain.resolve_context(domain.default_tenant_manager(), "t1")
    assert "Step" in ctx.ontology.entities
    with pytest.raises(domain.ProceduresDomainNotLoaded):
        domain.resolve_context(domain.default_tenant_manager(tmp_path), "t1")


def test_property_names_match_models():
    """Step/Media/Tip YAML properties are fields (or documented projections) of the TASK-3699 models."""
```

---

## Agent Instructions

1. Read spec §3 Module 3 and §5 AC5/AC10/AC11/AC17.
2. Confirm TASK-3699 is done; re-verify the schema/tenant anchors.
3. Update the per-spec index status → `in-progress`.
4. Implement from the blueprint; complete every `# FILL IN:`.
5. Run the Validation Commands with the worktree `PYTHONPATH`.
6. Move this file to `sdd/tasks/completed/`, update the index → `done`, fill the Completion Note.

---

## Completion Note


- Task: TASK-3701
- Feature: training-agent
- Implementation SHA: d30ff0a9e5aee11dd2a796fd8994194655668acf
- Closed at (UTC): 2026-09-25T00:04:13+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
| supplementary_test_evidence | 84 passed, 0 failed (scoped direct pytest over manuals+contracts/test_ontology_domain) |
