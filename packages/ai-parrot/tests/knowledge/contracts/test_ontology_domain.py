"""Contracts ontology domain tests (TASK-3036).

Validates the installed ``contracts.ontology.yaml`` through the real
parser/merger, pins the corrected pattern semantics (active guards, bind
sets, family de-duplication) and records the ``same_department`` spike
result with a Contract fixture.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from parrot.knowledge.contracts.standards import STANDARD_IDS
from parrot.knowledge.ontology.authorization import AuthorizationChecker
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import AuthorizationRule, AuthorizationSpec

import parrot.knowledge.ontology as ontology_package

#: Resolved from the installed package so the test follows the source tree
#: it is actually running against (worktree or site-packages).
DEFAULTS = Path(ontology_package.__file__).resolve().parent / "defaults"
BASE_YAML = DEFAULTS / "base.ontology.yaml"
CONTRACTS_YAML = DEFAULTS / "domains" / "contracts.ontology.yaml"

PATTERN_NAMES = (
    "contracts_requiring_standard",
    "expiring_within",
    "notice_deadlines_within",
    "contracts_with_party",
    "contract_family",
    "signatories_of",
    "obligations_of_contract",
    "contract_in_force",
    "my_contracts",
    "search_contracts",
)

_BIND_RE = re.compile(r"@@?[A-Za-z_][A-Za-z0-9_]*")


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return yaml.safe_load(CONTRACTS_YAML.read_text())


@pytest.fixture(scope="module")
def definition():
    return OntologyParser().load(CONTRACTS_YAML)


@pytest.fixture(scope="module")
def merged():
    return OntologyMerger().merge([BASE_YAML, CONTRACTS_YAML])


# --------------------------------------------------------------------------
# 1. Structure, counts and the merge contract
# --------------------------------------------------------------------------


def test_the_domain_yaml_is_installed_in_defaults():
    assert CONTRACTS_YAML.is_file()


def test_parser_accepts_the_domain(definition):
    assert definition.name == "contracts"
    assert definition.extends == "base"


def test_domain_declares_five_entities_thirteen_relations_ten_patterns(definition):
    assert set(definition.entities) == {
        "Contract",
        "Party",
        "Person",
        "Obligation",
        "ComplianceStandard",
    }
    assert len(definition.relations) == 13
    assert set(definition.traversal_patterns) == set(PATTERN_NAMES)


def test_base_merge_yields_eight_sixteen_thirteen(merged):
    assert len(merged.entities) == 8
    assert len(merged.relations) == 16
    assert len(merged.traversal_patterns) == 13
    assert {"Employee", "Department", "Role"} <= set(merged.entities)


def test_the_two_judged_relations_are_declared_without_discovery(definition):
    for name, source, target in (
        ("conflicts_with", "Contract", "Contract"),
        ("references_obligation", "Obligation", "Obligation"),
    ):
        relation = definition.relations[name]
        assert relation.from_entity == source
        assert relation.to_entity == target
        assert relation.discovery.rules == [], f"{name} must never be auto-discovered"
        properties = {key for entry in relation.properties for key in entry}
        assert "origin" in properties
        origin = next(entry["origin"] for entry in relation.properties if "origin" in entry)
        assert origin.enum == ["llm", "manual"]
        assert origin.default == "llm"


def test_original_eleven_relations_are_preserved(definition):
    assert {
        "party_to",
        "signed_by",
        "represents",
        "is_employee",
        "governed_by",
        "amends",
        "supersedes",
        "imposed_by",
        "requires",
        "owned_by",
        "managed_by",
    } <= set(definition.relations)


def test_contract_versions_is_a_plain_list_property(definition):
    contract = definition.entities["Contract"]
    versions = next(entry["versions"] for entry in contract.properties if "versions" in entry)
    assert versions.type == "list"


def test_contract_and_obligation_carry_an_active_flag(definition):
    for entity in ("Contract", "Obligation"):
        names = definition.entities[entity].get_property_names()
        assert "active" in names, entity
    assert "card_revision" in definition.entities["Contract"].get_property_names()


def test_english_search_view_links_the_searchable_entities(definition):
    view = definition.search_views["contracts_view"]
    linked = {link.entity for link in view.links}
    assert linked == {"Contract", "Obligation", "Party"}
    analyzers = {analyzer for link in view.links for field in link.fields for analyzer in field.analyzers}
    assert analyzers <= {"text_en", "identity"}, "the pilot is English-only"


def test_every_seeded_standard_is_representable(definition):
    standard = definition.entities["ComplianceStandard"]
    assert standard.key_field == "standard_id"
    described = " ".join(
        entry["standard_id"].description or "" for entry in standard.properties if "standard_id" in entry
    )
    assert "soc2" in described
    assert {"soc2", "soc1", "iso27001", "gdpr", "uk_gdpr"} <= set(STANDARD_IDS)


# --------------------------------------------------------------------------
# 2. Pattern semantics: guards, binds, de-duplication
# --------------------------------------------------------------------------


def test_every_pattern_filters_inactive_endpoints(definition):
    for name, pattern in definition.traversal_patterns.items():
        query = pattern.query_template
        if name == "search_contracts":
            assert "d.active != false" in query
            continue
        assert "active != false" in query, name


def test_obligation_patterns_filter_inactive_obligations(definition):
    for name in ("contracts_requiring_standard", "obligations_of_contract"):
        assert "ob.active != false" in definition.traversal_patterns[name].query_template


def test_every_bind_used_is_documented_in_the_pattern_description(definition):
    for name, pattern in definition.traversal_patterns.items():
        used = set(_BIND_RE.findall(pattern.query_template))
        documented = set(_BIND_RE.findall(pattern.description))
        assert used <= documented, (name, sorted(used - documented))
        assert "Binds:" in pattern.description, name


def test_pattern_bind_sets_match_the_spec_table(definition):
    expected = {
        "contracts_requiring_standard": {"@standard_id", "@statuses"},
        "expiring_within": {"@today", "@until"},
        "notice_deadlines_within": {"@today", "@until"},
        "contracts_with_party": {"@party_id"},
        "contract_family": {"@contract_id"},
        "signatories_of": {"@contract_id"},
        "obligations_of_contract": {"@contract_id", "@kind"},
        "contract_in_force": {"@contract_id", "@as_of"},
        "my_contracts": {"@user_id"},
        "search_contracts": {"@query", "@top_k"},
    }
    for name, values in expected.items():
        used = {
            bind
            for bind in _BIND_RE.findall(definition.traversal_patterns[name].query_template)
            if not bind.startswith("@@")
        }
        assert used == values, name


def test_nullable_kind_is_always_bound(definition):
    query = definition.traversal_patterns["obligations_of_contract"].query_template
    assert "@kind == null OR ob.kind == @kind" in query
    assert "ALWAYS bound" in definition.traversal_patterns["obligations_of_contract"].description


def test_my_contracts_uses_a_full_employee_graph_id(definition):
    pattern = definition.traversal_patterns["my_contracts"]
    assert "INBOUND @user_id" in pattern.query_template
    assert "employees/" in pattern.description
    assert "never from the question" in pattern.description


def test_contract_family_deduplicates_by_contract_identity(definition):
    query = definition.traversal_patterns["contract_family"].query_template
    assert "UNIQUE(" in query
    assert "RETURN v._key" in query
    assert "RETURN DISTINCT { contract" not in query


def test_search_pattern_maps_hits_back_to_contracts(definition):
    pattern = definition.traversal_patterns["search_contracts"]
    assert "PARSE_IDENTIFIER(d._id).collection" in pattern.query_template
    assert "mapped back" in pattern.description
    assert "@top_k" in pattern.query_template


def test_contract_in_force_is_effective_time_not_recorded_time(definition):
    pattern = definition.traversal_patterns["contract_in_force"]
    assert "v.valid_from <= @as_of" in pattern.query_template
    assert "v.valid_to == null OR v.valid_to > @as_of" in pattern.query_template
    assert "GraphIndex temporal plane" in pattern.description


def test_contracts_layer_resolves_entities_itself(definition):
    resolvers = {
        rule.resolver
        for pattern in definition.traversal_patterns.values()
        for rule in pattern.entity_extraction.values()
    }
    assert resolvers <= {"exact_id_match"}, (
        "the contracts adapter resolves ids against the authorized catalog; "
        "hybrid_concept_match is Concept-oriented and may call an LLM"
    )


# --------------------------------------------------------------------------
# 3. Authorization policy
# --------------------------------------------------------------------------


def test_every_pattern_is_default_deny(definition):
    for name, pattern in definition.traversal_patterns.items():
        assert pattern.authorization is not None, name
        assert pattern.authorization.default_deny is True, name


def test_read_patterns_accept_either_reader_or_owner(definition):
    for name in PATTERN_NAMES:
        if name == "my_contracts":
            continue
        rules = definition.traversal_patterns[name].authorization.rules
        assert [rule.role for rule in rules] == ["contract_reader", "contract_owner"], name
        assert all(rule.rule == "has_role" for rule in rules)


def test_my_contracts_is_self_service_and_still_default_deny(definition):
    spec = definition.traversal_patterns["my_contracts"].authorization
    assert [rule.rule for rule in spec.rules] == ["always"]
    assert spec.default_deny is True


def test_v1_yaml_declares_no_same_department_rule(definition):
    rules = {rule.rule for pattern in definition.traversal_patterns.values() for rule in pattern.authorization.rules}
    assert "same_department" not in rules, "v1 stays role-based plus my_contracts"


# --------------------------------------------------------------------------
# The same_department spike (open question in spec §8)
# --------------------------------------------------------------------------


class _RecordingGraphStore:
    """Captures what ``AuthorizationChecker`` would execute."""

    def __init__(self, department: Any = "legal") -> None:
        self.department = department
        self.calls: list[dict[str, Any]] = []

    async def execute_traversal(self, ctx, aql, bind_vars=None, collection_binds=None):
        self.calls.append(
            {
                "tenant_id": ctx.tenant_id,
                "arango_db": ctx.arango_db,
                "aql": aql,
                "bind_vars": dict(bind_vars or {}),
            }
        )
        return [self.department]


@pytest.mark.asyncio
async def test_spike_same_department_reads_a_contract_department_generically():
    """Spike (spec §8): ``_check_same_department`` on a Contract target.

    Verified behaviour against a Contract fixture:

    * it reads ``DOCUMENT(@target_id).department`` — a generic field read,
      so a Contract supplies ``department`` exactly like an Employee;
    * it builds the conventional ``<tenant>_ontology`` database name;
    * it matches ANY resolved entity, not a specific one.

    The rule stays **unused** in v1 YAML: enabling it would widen access
    beyond the role-based policy this spec froze.
    """
    store = _RecordingGraphStore(department="legal")
    checker = AuthorizationChecker(graph_store=store)
    spec = AuthorizationSpec(rules=[AuthorizationRule(rule="same_department")], default_deny=True)

    allowed, reason = await checker.check(
        spec,
        {"user_id": "employees/emp-1", "department": "legal"},
        {"contract": "contract/acme-msa"},
        "troc",
    )

    assert allowed is True and reason is None
    assert store.calls[0]["aql"] == "RETURN DOCUMENT(@target_id).department"
    assert store.calls[0]["bind_vars"] == {"target_id": "contract/acme-msa"}
    assert store.calls[0]["arango_db"] == "troc_ontology"


@pytest.mark.asyncio
async def test_spike_same_department_matches_any_resolved_target():
    store = _RecordingGraphStore(department="legal")
    checker = AuthorizationChecker(graph_store=store)
    spec = AuthorizationSpec(rules=[AuthorizationRule(rule="same_department")])

    allowed, _ = await checker.check(
        spec,
        {"user_id": "employees/emp-1", "department": "legal"},
        {"contract": "contract/acme-msa", "other": "contract/zeta-nda"},
        "troc",
    )
    assert allowed is True
    assert len(store.calls) == 1, "ANY-target semantics: it stops at the first match"


@pytest.mark.asyncio
async def test_spike_same_department_denies_without_a_department():
    store = _RecordingGraphStore(department="finance")
    checker = AuthorizationChecker(graph_store=store)
    spec = AuthorizationSpec(rules=[AuthorizationRule(rule="same_department")])

    allowed, reason = await checker.check(
        spec,
        {"user_id": "employees/emp-1", "department": "legal"},
        {"contract": "contract/acme-msa"},
        "troc",
    )
    assert allowed is False
    assert reason


def test_real_aql_execution_remains_an_integration_gate(raw):
    """Parsing YAML is not evidence that its AQL runs.

    The ten patterns must be executed against a real ArangoDB with real
    bind values by the integration task (TASK-3054); this module only
    validates structure and semantics.
    """
    assert len(raw["traversal_patterns"]) == 10
