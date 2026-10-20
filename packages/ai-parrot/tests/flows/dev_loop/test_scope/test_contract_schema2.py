"""Schema-2 validation contract, schema-1 lift, and tier admission tests."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.contract import (
    contract_from_index_header,
    contract_to_header,
    load_index_header,
    parse_spec_contract,
)
from parrot.flows.dev_loop.test_scope.runners.registry import RunnerRegistry


class _DiagnosticAdapter:
    """Minimal registry adapter that reports a settings admission diagnostic."""

    default_tiers = frozenset({"task", "merge", "feature"})

    def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]:
        """Return a deterministic diagnostic for contract validation."""
        return ["custom: required setting is missing"]


def _runner_spec(kind: str, body: str = "") -> str:
    return f"### Validation Contract\nrunners:\n- kind: {kind}\n{body}"


def test_contract_schema1_lift_has_stable_schema2_digest():
    """A valid FEAT-699 payload lifts to one pytest runner and writes deterministic v2."""
    legacy = {
        "schema": 1,
        "tests": ["tests/test_x.py"],
        "markers": ["unit"],
        "digest": "sha256:a0aaa23d7ea8dc2c0e83309217e8b2b8173293d1a78c0449183bea7d618d3867",
    }
    first = contract_from_index_header({"test_contract": legacy})
    second = contract_from_index_header({"test_contract": legacy})

    assert first is not None
    assert first == second
    assert first.schema == 2
    assert first.pytest is not None
    assert first.pytest.targets == ("tests/test_x.py",)
    assert first.pytest.settings["markers"] == "unit"
    assert contract_to_header(first) == contract_to_header(second)


def test_unknown_kind_and_forbidden_tier_fail_closed():
    """Invalid runner admission never produces an empty green contract."""
    with pytest.raises(ValueError, match="unknown runner kind"):
        parse_spec_contract(_runner_spec("unknown"))
    with pytest.raises(ValueError, match="does not support tiers"):
        parse_spec_contract(_runner_spec("parrot-e2e", "  plan: plan.md\n  tiers: [task, merge]\n"))


def test_registry_settings_diagnostics_fail_closed():
    """Adapter settings diagnostics become contract admission errors."""
    registry = RunnerRegistry({"custom": _DiagnosticAdapter()}, {})

    with pytest.raises(ValueError, match="required setting is missing"):
        parse_spec_contract(_runner_spec("custom"), registry=registry)


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "pytest", "targets": [], "settings": {}, "tiers": "task"},
        {"kind": "pytest", "targets": [], "settings": {}, "tiers": []},
        {"kind": "pytest", "targets": [], "settings": {}, "tiers": ["unknown"]},
        {"kind": "pytest", "targets": [], "settings": {}, "tiers": ["task"], "extra": True},
    ],
)
def test_malformed_runner_blocks_fail_closed(payload):
    """Malformed schema-2 blocks are rejected before their digest is trusted."""
    with pytest.raises(ValueError):
        contract_from_index_header({"test_contract": {"schema": 2, "runners": [payload], "digest": "x"}})


def test_legacy_schema1_index_unchanged():
    """Reading the live FEAT-699 index lifts in memory without rewriting its bytes."""
    root = Path(__file__).resolve().parents[6]
    index_path = root / "sdd/tasks/index/tests-optimization-sdd-flow.json"
    before = index_path.read_bytes()
    legacy_payload = json.loads(before)["test_contract"]

    contract = contract_from_index_header(load_index_header(index_path))

    assert contract is not None
    assert contract.pytest is not None
    assert list(contract.pytest.targets) == legacy_payload["tests"]
    assert contract.pytest.settings["markers"] == ",".join(legacy_payload["markers"])
    assert index_path.read_bytes() == before
