"""Procedures ontology domain tests (TASK-3701).

Validates the installed ``procedures.ontology.yaml`` through the real
parser/merger, pins the owned/technician collection tuples ``domain.py``
exposes, and checks the dedicated ``TenantOntologyManager`` fails loudly
when it does not resolve the procedures domain.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import parrot.knowledge.ontology as ontology_package
from parrot.knowledge.manuals import domain
from parrot.knowledge.manuals.models import MediaRef, Step, StepIdentity, Tip
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.parser import OntologyParser

#: Resolved from the installed package so the test follows the source tree
#: it is actually running against (worktree or site-packages).
DEFAULTS = Path(ontology_package.__file__).resolve().parent / "defaults"
BASE_YAML = DEFAULTS / "base.ontology.yaml"
YAML_PATH = DEFAULTS / "domains" / "procedures.ontology.yaml"

PATTERN_NAMES = (
    "procedure_steps",
    "procedure_prerequisites",
    "procedures_for_equipment",
    "step_detail",
    "equipment_sharing_module",
    "procedure_in_force",
    "tips_for_procedure",
    "part_for_callout",
    "verification_queue_procedures",
)


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(YAML_PATH.read_text())


@pytest.fixture(scope="module")
def definition():
    return OntologyParser.load(YAML_PATH)


@pytest.fixture(scope="module")
def merged():
    return OntologyMerger().merge([BASE_YAML, YAML_PATH])


# --------------------------------------------------------------------------
# 1. Structure and the merge contract (AC10)
# --------------------------------------------------------------------------


def test_procedures_yaml_is_installed_in_defaults():
    assert YAML_PATH.is_file()


def test_procedures_yaml_parses_extra_forbid(definition):
    assert definition.name == "procedures"
    assert definition.extends == "base"


def test_domain_declares_nine_entities_fourteen_relations_nine_patterns(definition):
    assert set(definition.entities) == {
        "Equipment",
        "Manual",
        "Procedure",
        "Step",
        "Part",
        "Tool",
        "Hazard",
        "Media",
        "Tip",
    }
    assert len(definition.relations) == 14
    assert set(definition.traversal_patterns) == set(PATTERN_NAMES)


def test_base_merge_includes_procedures_and_employee(merged):
    assert {"Procedure", "Step", "Media", "Tip", "Employee"} <= set(merged.entities)


# --------------------------------------------------------------------------
# 2. Owned vs technician collections (AC5)
# --------------------------------------------------------------------------


def test_collections_match_domain_tuples_and_are_disjoint(definition):
    yaml_vertex_collections = {entity.collection for entity in definition.entities.values()}
    yaml_edge_collections = {relation.edge_collection for relation in definition.relations.values()}

    owned_vertex = set(domain.OWNED_VERTEX_COLLECTIONS)
    owned_edge = set(domain.OWNED_EDGE_COLLECTIONS)
    technician = set(domain.TECHNICIAN_COLLECTIONS)

    assert yaml_vertex_collections == owned_vertex | {"tech_tip"}
    assert yaml_edge_collections == owned_edge | {"tech_tip_on", "tech_tip_by"}
    assert owned_vertex.isdisjoint(technician)
    assert owned_edge.isdisjoint(technician)


def test_technician_entities_have_no_source(definition):
    tip = definition.entities["Tip"]
    assert tip.collection == "tech_tip"
    assert tip.source is None


def test_owned_entities_have_a_source(definition):
    for name, entity in definition.entities.items():
        if name == "Tip":
            continue
        assert entity.source == "manualcard", name


# --------------------------------------------------------------------------
# 3. Authorization policy (AC10)
# --------------------------------------------------------------------------


def test_every_pattern_is_default_deny(definition):
    for name, pattern in definition.traversal_patterns.items():
        assert pattern.authorization is not None, name
        assert pattern.authorization.default_deny is True, name


def test_read_patterns_accept_technician_or_curator(definition):
    for name in PATTERN_NAMES:
        if name == "verification_queue_procedures":
            continue
        rules = definition.traversal_patterns[name].authorization.rules
        assert [rule.role for rule in rules] == [domain.TECHNICIAN_ROLE, domain.CURATOR_ROLE], name
        assert all(rule.rule == "has_role" for rule in rules)


def test_verification_queue_excludes_technician(definition):
    rules = definition.traversal_patterns["verification_queue_procedures"].authorization.rules
    assert [rule.role for rule in rules] == [domain.CURATOR_ROLE]
    assert domain.TECHNICIAN_ROLE not in [rule.role for rule in rules]


def test_no_certified_for_anywhere():
    text = YAML_PATH.read_text()
    assert "certified_for" not in text


def test_no_forbidden_authorization_rule_kind(definition):
    allowed = {"target_is_self", "target_in_management_chain", "has_role", "same_department", "always"}
    for pattern in definition.traversal_patterns.values():
        for rule in pattern.authorization.rules:
            assert rule.rule in allowed


# --------------------------------------------------------------------------
# 4. Pattern semantics: active guards, binds
# --------------------------------------------------------------------------


def test_every_pattern_guards_active(definition):
    for name, pattern in definition.traversal_patterns.items():
        query = pattern.query_template
        assert "active != false" in query, name
        assert "_active != false" in query, name


def test_tips_for_procedure_filters_orphaned(definition):
    query = definition.traversal_patterns["tips_for_procedure"].query_template
    assert "tip.orphaned != true" in query


def test_patterns_use_collection_binds_not_literal_names(definition):
    for name, pattern in definition.traversal_patterns.items():
        for collection in domain.OWNED_VERTEX_COLLECTIONS + domain.TECHNICIAN_COLLECTIONS:
            # A bare collection name (not prefixed with @@) should never appear
            # as an AQL FOR-source; only bind-parameter forms are allowed.
            assert f"FOR {collection} " not in pattern.query_template.replace("\n", " "), name


# --------------------------------------------------------------------------
# 5. domain.py resolution (AC11)
# --------------------------------------------------------------------------


def test_domain_resolves_with_defaults_dir():
    ctx = domain.resolve_context(domain.default_tenant_manager(), "t1")
    assert "Step" in ctx.ontology.entities
    assert "Tip" in ctx.ontology.entities


def test_domain_raises_when_manager_points_elsewhere(tmp_path):
    with pytest.raises(domain.ProceduresDomainNotLoaded):
        domain.resolve_context(domain.default_tenant_manager(tmp_path), "t1")


def test_default_tenant_manager_returns_a_new_instance_each_call():
    first = domain.default_tenant_manager()
    second = domain.default_tenant_manager()
    assert first is not second


# --------------------------------------------------------------------------
# 6. Property names match the TASK-3699 models (or documented projections)
# --------------------------------------------------------------------------


def test_media_property_names_match_media_ref_fields(definition):
    media = definition.entities["Media"]
    model_fields = set(MediaRef.model_fields)
    yaml_fields = media.get_property_names()
    assert yaml_fields <= model_fields, yaml_fields - model_fields


def test_tip_property_names_match_tip_model_fields(definition):
    tip = definition.entities["Tip"]
    model_fields = set(Tip.model_fields)
    yaml_fields = tip.get_property_names()
    assert yaml_fields == model_fields, yaml_fields ^ model_fields


def test_step_identity_fields_are_projected_from_step_and_step_identity(definition):
    step = definition.entities["Step"]
    yaml_fields = step.get_property_names()
    identity_fields = set(StepIdentity.model_fields)
    step_fields = set(Step.model_fields)
    # step_id/source_identity/content_hash come from StepIdentity; order/text/
    # torque/duration_minutes come from Step itself. The remainder
    # (procedure_id, applies_models, applies_serial_ranges, node_id, page,
    # active) are documented graph-loader projections, not direct fields.
    assert {"step_id", "source_identity", "content_hash"} <= identity_fields
    assert {"order", "text", "torque", "duration_minutes"} <= step_fields
    assert yaml_fields >= {"step_id", "source_identity", "content_hash", "order", "text"}


# --------------------------------------------------------------------------
# 7. Imports discipline (AC17)
# --------------------------------------------------------------------------


def test_domain_module_imports_only_submodules():
    source = Path(domain.__file__).read_text()
    assert "from parrot.knowledge.ontology import " not in source
    assert "from parrot.knowledge.ontology.parser import" in source
    assert "from parrot.knowledge.ontology.tenant import" in source
    assert "from parrot.knowledge.ontology.schema import" in source


def test_real_aql_execution_remains_an_integration_gate(raw):
    """Parsing YAML is not evidence that its AQL runs against ArangoDB.

    The nine patterns must be executed by the integration task (TASK-3720);
    this module only validates structure and semantics.
    """
    assert len(raw["traversal_patterns"]) == 9
