"""Tests for inter-agent capability contract validation and hashing."""

import pytest

from parrot.interagent import (
    CapabilityCategory,
    PolicyAnnotations,
    ReturnsSpec,
    SquawkCapability,
    SquawkContract,
    contract_delta,
)


def _cap(cid: str = "hr.reports.manager_of", desc: str = "Manager of an employee") -> SquawkCapability:
    """Build a valid inline capability used by contract tests."""
    return SquawkCapability(
        cap_id=cid,
        category="hr.reports",
        description=desc,
        input_schema={"type": "object", "properties": {}},
        returns=ReturnsSpec(kind="inline", schema={"type": "object"}),
        backing="deterministic",
        policy=PolicyAnnotations(data_class="hr"),
    )


def test_hash_changes_with_capability() -> None:
    """Canonical category hashes are stable and reflect capability content."""
    first = CapabilityCategory(name="hr.reports", capabilities=(_cap(),))
    changed = CapabilityCategory(name="hr.reports", capabilities=(_cap(desc="Manager of employee"),))

    assert first.hash.startswith("sha256:")
    assert first.hash != changed.hash
    assert CapabilityCategory(name="hr.reports", capabilities=(_cap(),)).hash == first.hash
    assert first.model_copy().hash == first.hash


def test_delta_partition() -> None:
    """Deltas include differing definitions, equal names, and missing names."""
    category = CapabilityCategory(name="hr.reports", capabilities=(_cap(),))
    contract = SquawkContract(agent_id="hr", major=1, categories=(category,))

    delta = contract_delta(
        {"hr.reports": "sha256:" + "0" * 64, "hr.people": "sha256:" + "1" * 64},
        contract,
    )

    assert [item.name for item in delta.changed] == ["hr.reports"]
    assert delta.unchanged == ()
    assert delta.removed == ("hr.people",)
    assert contract_delta(contract.hashes, contract).unchanged == ("hr.reports",)


def test_capability_return_requirements_and_category_are_validated() -> None:
    """Only coherent category and return specifications are accepted."""
    with pytest.raises(ValueError, match="category"):
        SquawkCapability(
            cap_id="hr.reports.manager_of",
            category="hr.people",
            description="Manager of an employee",
            input_schema={"type": "object"},
            returns=ReturnsSpec(kind="inline", schema={"type": "object"}),
            backing="deterministic",
        )

    with pytest.raises(ValueError, match="media_type"):
        SquawkCapability(
            cap_id="hr.reports.export",
            category="hr.reports",
            description="Export report",
            input_schema={},
            returns=ReturnsSpec(kind="artifact"),
            backing="deterministic",
        )
