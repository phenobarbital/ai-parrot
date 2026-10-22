"""Tests for parsing FEAT-699 spec-declared validation contracts."""

import pytest

from parrot.flows.dev_loop.test_scope.contract import (
    contract_from_index_header,
    contract_to_header,
    parse_spec_contract,
)
from parrot.flows.dev_loop.test_scope.datatypes import ScopePlan

SPEC = """## 4. Test Specification
### Validation Contract

> note
tests:
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py
- tests/sdd_scripts/test_check_task_graph.py::test_x
markers: none

### Next
"""

RUNNERS_SPEC = """## 4. Test Specification
### Validation Contract
runners:
- kind: pytest
  tests:
  - packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py
  markers: [unit, integration]
- kind: vitest
  cwd: packages/ai-parrot-server/ui
  tests:
  - src/lib/components/FormRenderer.test.ts
  tiers: [task, merge]

### Next
"""


def test_parse_spec_contract_roundtrip():
    """A normal contract preserves test order and round-trips through an index header."""
    contract = parse_spec_contract(SPEC)
    assert contract is not None
    assert contract.pytest is not None
    assert contract.pytest.targets[1].endswith("::test_x")
    assert contract.pytest.settings["markers"] == ""
    assert contract_from_index_header({"test_contract": contract_to_header(contract)}) == contract


def test_parse_runner_contract_roundtrip():
    """The multi-runner form normalizes settings and survives the schema-2 header."""
    contract = parse_spec_contract(RUNNERS_SPEC)
    assert contract is not None
    assert [runner.kind for runner in contract.runners] == ["pytest", "vitest"]
    assert contract.pytest is not None
    assert contract.pytest.settings["markers"] == "integration,unit"
    assert contract.runners[1].tiers == ("task", "merge")
    assert contract_from_index_header({"test_contract": contract_to_header(contract)}) == contract


def test_none_fallback_and_missing_heading():
    """Fallback is explicit, while a missing contract fails closed."""
    assert parse_spec_contract("### Validation Contract\nnone — fallback\n") is None
    with pytest.raises(ValueError):
        parse_spec_contract("## Validation Commands\n")


@pytest.mark.parametrize("bad", ["packages/ai-parrot/tests", "../x.py", "tests/*.py"])
def test_bad_operands_fail_closed(bad):
    """Unsafe and over-broad pytest operands are rejected."""
    with pytest.raises(ValueError):
        parse_spec_contract(SPEC.replace("tests/sdd_scripts/test_check_task_graph.py::test_x", bad))


def test_real_llm_marker_fails_closed():
    """Live-LLM tests cannot be declared by a validation contract."""
    with pytest.raises(ValueError):
        parse_spec_contract(SPEC.replace("markers: none", "markers:\n- real_llm"))


def test_absent_and_unknown_schema_header():
    """Legacy headers fall back, but unknown cached schemas fail closed."""
    assert contract_from_index_header({}) is None
    with pytest.raises(ValueError):
        contract_from_index_header({"test_contract": {"schema": 99}})


def test_tampered_digest_fails_closed():
    """A cached contract must match its integrity digest."""
    contract = parse_spec_contract(SPEC)
    assert contract is not None
    header = contract_to_header(contract)
    header["digest"] = "sha256:tampered"
    with pytest.raises(ValueError):
        contract_from_index_header({"test_contract": header})


def test_scope_plan_new_fields_are_optional():
    """Existing ScopePlan construction retains fallback-mode defaults."""
    plan = ScopePlan("task", (), (), (), (), ())
    assert plan.mode == "fallback"
    assert plan.cached == ()
