"""Unit tests for capability bindings, build_contract, and version rules."""

from datetime import date
import pytest
from pydantic import ValidationError

from parrot.interagent import ReturnsSpec, SquawkCapability
from parrot.squawk.contract.bindings import (
    CapabilityBinding,
    LLMBackedSpec,
    build_contract,
    check_version_rules,
)


def hr_capabilities() -> tuple[SquawkCapability, SquawkCapability, SquawkCapability]:
    """HR capability fixtures."""
    cap1 = SquawkCapability(
        cap_id="hr.employee.get",
        category="hr.employee",
        description="Fetch employee profile by ID",
        input_schema={
            "type": "object",
            "properties": {"emp_id": {"type": "string"}},
            "required": ["emp_id"],
        },
        returns=ReturnsSpec(
            kind="inline",
            schema={
                "type": "object",
                "properties": {
                    "emp_id": {"type": "string"},
                    "name": {"type": "string"},
                    "dept": {"type": "string"},
                },
            },
        ),
        backing="deterministic",
    )

    cap2 = SquawkCapability(
        cap_id="hr.reports.headcount",
        category="hr.reports",
        description="Compute headcount per department",
        input_schema={
            "type": "object",
            "properties": {"department": {"type": "string"}},
            "required": [],
        },
        returns=ReturnsSpec(
            kind="inline",
            schema={"type": "object", "properties": {"counts": {"type": "object"}}},
        ),
        backing="deterministic",
    )

    cap3 = SquawkCapability(
        cap_id="hr.reports.attrition_risk",
        category="hr.reports",
        description="Analyze attrition risk for a team using LLM evaluation",
        input_schema={
            "type": "object",
            "properties": {"team_id": {"type": "string"}},
            "required": ["team_id"],
        },
        returns=ReturnsSpec(
            kind="inline",
            schema={"type": "object", "properties": {"risk_level": {"type": "string"}}},
        ),
        backing="llm_backed",
    )

    return cap1, cap2, cap3


def test_llm_backed_spec_validation():
    # Valid allowlist
    spec = LLMBackedSpec(
        system_prompt="Analyze risk",
        output_schema={"type": "object"},
        tool_allowlist=("hr.employee.get",),
    )
    assert spec.tool_allowlist == ("hr.employee.get",)

    # Invalid tool_allowlist entry (not cap_id format)
    with pytest.raises(ValidationError, match="tool_allowlist must contain cap_ids"):
        LLMBackedSpec(
            system_prompt="Analyze risk",
            output_schema={"type": "object"},
            tool_allowlist=("invalid_tool_name",),
        )


def test_capability_binding_validation():
    cap1, _, cap3 = hr_capabilities()

    # Valid deterministic binding
    b1 = CapabilityBinding(capability=cap1, tool_name="get_emp_tool")
    assert b1.tool_name == "get_emp_tool"

    # Invalid deterministic binding (missing tool_name)
    with pytest.raises(ValidationError, match="deterministic capability requires tool_name set"):
        CapabilityBinding(capability=cap1)

    # Invalid deterministic binding (llm_backed also provided)
    spec = LLMBackedSpec(system_prompt="p", output_schema={})
    with pytest.raises(ValidationError, match="deterministic capability requires tool_name set"):
        CapabilityBinding(capability=cap1, tool_name="get_emp_tool", llm_backed=spec)

    # Valid llm_backed binding
    b3 = CapabilityBinding(capability=cap3, llm_backed=spec)
    assert b3.llm_backed == spec

    # Invalid llm_backed binding (missing llm_backed or having tool_name)
    with pytest.raises(ValidationError, match="llm_backed capability requires llm_backed set"):
        CapabilityBinding(capability=cap3, tool_name="some_tool")


def test_build_contract():
    cap1, cap2, cap3 = hr_capabilities()
    spec = LLMBackedSpec(system_prompt="p", output_schema={})

    b1 = CapabilityBinding(capability=cap1, tool_name="t1")
    b2 = CapabilityBinding(capability=cap2, tool_name="t2")
    b3 = CapabilityBinding(capability=cap3, llm_backed=spec)

    contract = build_contract([b1, b2, b3], agent_id="hr_agent", major=1)

    assert contract.agent_id == "hr_agent"
    assert contract.major == 1
    assert len(contract.categories) == 2
    cat_names = [c.name for c in contract.categories]
    assert cat_names == ["hr.employee", "hr.reports"]

    reports_cat = contract.categories[1]
    assert len(reports_cat.capabilities) == 2
    assert [cap.cap_id for cap in reports_cat.capabilities] == [
        "hr.reports.attrition_risk",
        "hr.reports.headcount",
    ]

    # Duplicate cap_id check
    with pytest.raises(ValueError, match="duplicate cap_id hr.employee.get"):
        build_contract([b1, b1], agent_id="hr_agent")


def test_check_version_rules_additions():
    cap1, cap2, cap3 = hr_capabilities()

    b1 = CapabilityBinding(capability=cap1, tool_name="t1")
    b2 = CapabilityBinding(capability=cap2, tool_name="t2")
    b3 = CapabilityBinding(capability=cap3, llm_backed=LLMBackedSpec(system_prompt="p", output_schema={}))

    prev_contract = build_contract([b1, b2], agent_id="hr_agent", major=1)
    cand_contract = build_contract([b1, b2, b3], agent_id="hr_agent", major=1)

    # Addition under same major version should have 0 violations
    violations = check_version_rules(prev_contract, cand_contract)
    assert violations == []


def test_check_version_rules_removals():
    cap1, cap2, cap3 = hr_capabilities()

    b1 = CapabilityBinding(capability=cap1, tool_name="t1")
    b2 = CapabilityBinding(capability=cap2, tool_name="t2")
    b3 = CapabilityBinding(capability=cap3, llm_backed=LLMBackedSpec(system_prompt="p", output_schema={}))

    prev_contract = build_contract([b1, b2, b3], agent_id="hr_agent", major=1)
    cand_contract = build_contract([b1, b2], agent_id="hr_agent", major=1)

    # Removal without major bump
    violations = check_version_rules(prev_contract, cand_contract)
    assert len(violations) == 1
    assert "Capabilities removed without major version bump" in violations[0]

    # Major bump, but removed cap lacked deprecated_until in previous contract
    cand_contract_v2 = build_contract([b1, b2], agent_id="hr_agent", major=2)
    violations = check_version_rules(prev_contract, cand_contract_v2)
    assert len(violations) == 1
    assert "Removed capabilities lacked deprecated_until" in violations[0]

    # Major bump with deprecation date set in previous contract
    cap3_dep = SquawkCapability(
        cap_id=cap3.cap_id,
        category=cap3.category,
        description=cap3.description,
        input_schema=cap3.input_schema,
        returns=cap3.returns,
        backing=cap3.backing,
        deprecated_until=date(2025, 12, 31),
    )
    b3_dep = CapabilityBinding(
        capability=cap3_dep,
        llm_backed=LLMBackedSpec(system_prompt="p", output_schema={}),
    )
    prev_contract_dep = build_contract([b1, b2, b3_dep], agent_id="hr_agent", major=1)
    violations = check_version_rules(prev_contract_dep, cand_contract_v2)
    assert violations == []


def test_check_version_rules_type_changes():
    cap1, cap2, _ = hr_capabilities()

    b1 = CapabilityBinding(capability=cap1, tool_name="t1")
    b2 = CapabilityBinding(capability=cap2, tool_name="t2")

    prev_contract = build_contract([b1, b2], agent_id="hr_agent", major=1)

    # Change input schema of cap1 without major bump
    cap1_modified = SquawkCapability(
        cap_id=cap1.cap_id,
        category=cap1.category,
        description=cap1.description,
        input_schema={"type": "object", "properties": {"emp_id": {"type": "integer"}}},
        returns=cap1.returns,
        backing=cap1.backing,
    )
    b1_mod = CapabilityBinding(capability=cap1_modified, tool_name="t1")
    cand_contract = build_contract([b1_mod, b2], agent_id="hr_agent", major=1)

    violations = check_version_rules(prev_contract, cand_contract)
    assert len(violations) == 1
    assert "schema or return type changed without major version bump" in violations[0]

    # Change with major bump is allowed
    cand_contract_v2 = build_contract([b1_mod, b2], agent_id="hr_agent", major=2)
    violations = check_version_rules(prev_contract, cand_contract_v2)
    assert violations == []
