"""Validation of a blueprint against the live component catalog.

One test per issue code — these messages are fed verbatim back to the model
for repair, so both the detection and the code are part of the contract.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.bots.flows.authoring.blueprint import (
    BlueprintNode,
    BlueprintTransition,
    WorkflowBlueprint,
)
from parrot.bots.flows.authoring.validator import _cel_roots, validate_blueprint


def _blueprint(**overrides):
    payload = {
        "name": "wf",
        "engine": "crew",
        "nodes": [
            BlueprintNode(id="a", kind="agent", system_prompt="You are A."),
            BlueprintNode(id="b", kind="agent", system_prompt="You are B."),
        ],
        "transitions": [BlueprintTransition(source="a", target="b")],
    }
    payload.update(overrides)
    return WorkflowBlueprint(**payload)


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


# ── happy path ───────────────────────────────────────────────────────────────

def test_valid_blueprint_passes(crew_catalog):
    report = validate_blueprint(_blueprint(), crew_catalog)
    assert report.ok, str(report)


# ── catalog membership ───────────────────────────────────────────────────────

def test_unknown_tool_is_reported_with_a_suggestion(crew_catalog):
    blueprint = _blueprint(
        nodes=[
            BlueprintNode(
                id="a", kind="agent", system_prompt="x", tools=["google_serch"]
            )
        ],
        transitions=[],
    )
    report = validate_blueprint(blueprint, crew_catalog)
    assert not report.ok
    assert "tool_not_found" in _codes(report)
    # The near-miss must be named — that is what lets one repair round fix it.
    assert "google_search" in str(report)


def test_unknown_tool_becomes_a_capability_gap(crew_catalog):
    blueprint = _blueprint(
        nodes=[BlueprintNode(id="a", kind="tool", tool="wordpress_publish")],
        transitions=[],
    )
    report = validate_blueprint(blueprint, crew_catalog)
    gaps = [g for g in report.capability_gaps if g.requested == "wordpress_publish"]
    assert gaps and gaps[0].kind == "tool"
    assert gaps[0].node_id == "a"


def test_unknown_agent_ref_is_reported(catalog):
    blueprint = _blueprint(
        engine="flow",
        nodes=[BlueprintNode(id="a", kind="agent", agent_ref="no_such_agent")],
        transitions=[],
    )
    report = validate_blueprint(blueprint, catalog)
    assert "agent_not_found" in _codes(report)


def test_flow_agent_node_requires_agent_ref(catalog):
    blueprint = _blueprint(
        engine="flow",
        nodes=[BlueprintNode(id="a", kind="agent")],
        transitions=[],
    )
    report = validate_blueprint(blueprint, catalog)
    assert "agent_ref_required" in _codes(report)


def test_shared_tool_must_exist(crew_catalog):
    report = validate_blueprint(_blueprint(shared_tools=["nope"]), crew_catalog)
    assert "shared_tool_not_found" in _codes(report)


# ── engine compatibility ─────────────────────────────────────────────────────

def test_decision_node_is_rejected_for_a_crew(crew_catalog):
    blueprint = _blueprint(
        nodes=[
            BlueprintNode(
                id="a", kind="decision", config={"mode": "ballot", "decision_type": "binary"}
            )
        ],
        transitions=[],
    )
    report = validate_blueprint(blueprint, crew_catalog)
    assert "kind_unavailable" in _codes(report)


def test_conditional_edge_is_rejected_for_a_crew(crew_catalog):
    blueprint = _blueprint(
        transitions=[
            BlueprintTransition(
                source="a", target="b", condition="on_condition", predicate="result.ok"
            )
        ]
    )
    report = validate_blueprint(blueprint, crew_catalog)
    assert "condition_unsupported" in _codes(report)


def test_node_config_is_validated_against_its_type_schema(catalog):
    blueprint = _blueprint(
        engine="flow",
        nodes=[BlueprintNode(id="a", kind="decision", config={"mode": "ballot"})],
        transitions=[],
    )
    report = validate_blueprint(blueprint, catalog)
    # decision_type is required by the real DecisionConfigDef.
    assert "config_invalid" in _codes(report)


# ── graph shape ──────────────────────────────────────────────────────────────

def test_transition_to_unknown_node_is_reported(crew_catalog):
    blueprint = _blueprint(
        transitions=[BlueprintTransition(source="a", target="ghost")]
    )
    report = validate_blueprint(blueprint, crew_catalog)
    assert "transition_unknown_node" in _codes(report)


def test_cycle_is_detected(crew_catalog):
    blueprint = _blueprint(
        transitions=[
            BlueprintTransition(source="a", target="b"),
            BlueprintTransition(source="b", target="a"),
        ]
    )
    report = validate_blueprint(blueprint, crew_catalog)
    assert "cycle_detected" in _codes(report)
    assert "no_entry_point" in _codes(report)


def test_conditional_back_edge_is_allowed_in_a_flow(catalog):
    blueprint = _blueprint(
        engine="flow",
        nodes=[
            BlueprintNode(id="a", kind="agent", agent_ref="researcher_agent"),
            BlueprintNode(id="b", kind="agent", agent_ref="writer_agent"),
        ],
        transitions=[
            BlueprintTransition(source="a", target="b"),
            BlueprintTransition(
                source="b",
                target="a",
                condition="on_condition",
                predicate="result.retry == true",
            ),
        ],
    )
    report = validate_blueprint(blueprint, catalog)
    assert "cycle_detected" not in _codes(report)


def test_orphan_node_is_a_warning_not_an_error(crew_catalog):
    blueprint = _blueprint(
        nodes=[
            BlueprintNode(id="a", kind="agent", system_prompt="x"),
            BlueprintNode(id="b", kind="agent", system_prompt="y"),
            BlueprintNode(id="c", kind="agent", system_prompt="z"),
        ],
        transitions=[BlueprintTransition(source="a", target="b")],
    )
    report = validate_blueprint(blueprint, crew_catalog)
    assert report.ok
    assert "multiple_entry_points" in _codes(report)


# ── CEL predicates ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "expression,expected",
    [
        ('result.final_decision == "Pizza"', {"result"}),
        ("result.passed == false && result.attempt < 3", {"result"}),
        ('ctx.mode == "x" || error != ""', {"ctx", "error"}),
        ("size(result.items) > 0", {"result"}),
        # A quoted literal must not be read as a variable.
        ('result.name == "ctx"', {"result"}),
        # Comprehension macros bind their first argument; it is declared by
        # the expression itself, not a free variable.
        ('result.findings.exists(f, f.severity == "high")', {"result"}),
        ("result.filter(x, x > 3).size() > 0", {"result"}),
        ("result.items.all(i, i.ok)", {"result"}),
        ("result.map(v, v.id).size() > 0", {"result"}),
    ],
)
def test_cel_root_extraction(expression, expected):
    assert _cel_roots(expression) == expected


def test_a_valid_comprehension_predicate_is_accepted(catalog):
    """A macro-bound variable must not be flagged as unknown."""
    from parrot.bots.flows.authoring.blueprint import BlueprintNode, BlueprintTransition

    blueprint = _blueprint(
        engine="flow",
        nodes=[
            BlueprintNode(id="a", kind="agent", agent_ref="researcher_agent"),
            BlueprintNode(id="b", kind="agent", agent_ref="writer_agent"),
        ],
        transitions=[
            BlueprintTransition(
                source="a",
                target="b",
                condition="on_condition",
                predicate='result.findings.exists(f, f.severity == "high")',
            )
        ],
    )
    report = validate_blueprint(blueprint, catalog)
    assert "predicate_unknown_variable" not in _codes(report)


def test_predicate_reading_an_unknown_variable_is_rejected(catalog):
    """CEL is fail-safe, so this would otherwise be a silent mis-route."""
    blueprint = _blueprint(
        engine="flow",
        nodes=[
            BlueprintNode(id="a", kind="agent", agent_ref="researcher_agent"),
            BlueprintNode(id="b", kind="agent", agent_ref="writer_agent"),
        ],
        transitions=[
            BlueprintTransition(
                source="a",
                target="b",
                condition="on_condition",
                predicate='reslt.decision == "yes"',
            )
        ],
    )
    report = validate_blueprint(blueprint, catalog)
    assert "predicate_unknown_variable" in _codes(report)


def test_predicate_that_does_not_compile_is_rejected(catalog):
    blueprint = _blueprint(
        engine="flow",
        nodes=[
            BlueprintNode(id="a", kind="agent", agent_ref="researcher_agent"),
            BlueprintNode(id="b", kind="agent", agent_ref="writer_agent"),
        ],
        transitions=[
            BlueprintTransition(
                source="a", target="b", condition="on_condition", predicate="result.((("
            )
        ],
    )
    report = validate_blueprint(blueprint, catalog)
    assert _codes(report) & {"predicate_invalid", "cel_unavailable"}


# ── blueprint-level Pydantic invariants ──────────────────────────────────────

def test_dotted_node_id_is_rejected():
    with pytest.raises(ValidationError, match="lower_snake_case"):
        BlueprintNode(id="a.b", kind="agent")


def test_duplicate_node_ids_are_rejected():
    with pytest.raises(ValidationError, match="Duplicate node ids"):
        WorkflowBlueprint(
            name="wf",
            engine="crew",
            nodes=[
                BlueprintNode(id="a", kind="agent"),
                BlueprintNode(id="a", kind="agent"),
            ],
        )


def test_on_condition_without_predicate_is_rejected():
    with pytest.raises(ValidationError, match="predicate"):
        BlueprintTransition(source="a", target="b", condition="on_condition")


def test_predicate_without_on_condition_is_rejected():
    """A predicate on an unconditional edge would never be evaluated."""
    with pytest.raises(ValidationError, match="never be evaluated"):
        BlueprintTransition(
            source="a", target="b", condition="on_success", predicate="result.ok"
        )


def test_tool_kind_requires_a_tool():
    with pytest.raises(ValidationError, match="must set 'tool'"):
        BlueprintNode(id="a", kind="tool")


def test_agent_node_may_not_set_tool():
    with pytest.raises(ValidationError, match="must not set 'tool'"):
        BlueprintNode(id="a", kind="agent", tool="google_search")


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        BlueprintNode(id="a", kind="agent", hallucinated_field="x")
