"""Unit tests for ContractCache."""

import pytest

from parrot.interagent import contract_delta
from parrot.squawk.contract.bindings import (
    CapabilityBinding,
    LLMBackedSpec,
    build_contract,
)
from parrot.squawk.contract.cache import ContractCache
from .test_bindings import hr_capabilities


def test_contract_cache_basic_ops():
    cap1, cap2, cap3 = hr_capabilities()
    spec = LLMBackedSpec(system_prompt="p", output_schema={})
    b1 = CapabilityBinding(capability=cap1, tool_name="t1")
    b2 = CapabilityBinding(capability=cap2, tool_name="t2")
    b3 = CapabilityBinding(capability=cap3, llm_backed=spec)

    contract = build_contract([b1, b2, b3], agent_id="hr_agent", major=1)

    cache = ContractCache()
    assert cache.categories() == []
    assert cache.known_hashes == {}

    # Apply handshake delta from empty cache
    delta = contract_delta(cache.known_hashes, contract)
    cache.apply(delta)

    assert len(cache.categories()) == 2
    assert set(cache.known_hashes.keys()) == {"hr.employee", "hr.reports"}

    # Find cap
    cap = cache.find("hr.employee.get")
    assert cap is not None
    assert cap.cap_id == "hr.employee.get"

    assert cache.find("non.existent") is None

    # Replace category
    emp_cat = cache.category("hr.employee")
    assert emp_cat is not None
    cache.replace_category(emp_cat)
    assert cache.category("hr.employee") == emp_cat


def test_contract_cache_delta_updates():
    cap1, cap2, cap3 = hr_capabilities()
    spec = LLMBackedSpec(system_prompt="p", output_schema={})
    b1 = CapabilityBinding(capability=cap1, tool_name="t1")
    b2 = CapabilityBinding(capability=cap2, tool_name="t2")
    b3 = CapabilityBinding(capability=cap3, llm_backed=spec)

    c1 = build_contract([b1, b2, b3], agent_id="hr_agent", major=1)

    cache = ContractCache()
    cache.apply(contract_delta(cache.known_hashes, c1))
    assert len(cache.categories()) == 2

    # Now server drops hr.employee category
    c2 = build_contract([b2, b3], agent_id="hr_agent", major=2)
    delta2 = contract_delta(cache.known_hashes, c2)
    cache.apply(delta2)

    assert cache.category("hr.employee") is None
    assert len(cache.categories()) == 1
    assert cache.category("hr.reports") is not None


def test_contract_cache_search():
    cap1, cap2, cap3 = hr_capabilities()
    spec = LLMBackedSpec(system_prompt="p", output_schema={})
    b1 = CapabilityBinding(capability=cap1, tool_name="t1")
    b2 = CapabilityBinding(capability=cap2, tool_name="t2")
    b3 = CapabilityBinding(capability=cap3, llm_backed=spec)

    contract = build_contract([b1, b2, b3], agent_id="hr_agent", major=1)
    cache = ContractCache()
    cache.apply(contract_delta(cache.known_hashes, contract))

    # Search empty keywords -> returns all capabilities up to limit
    res_all = cache.search("")
    assert len(res_all) == 3

    # Search substring matching description/cap_id: "headcount"
    res_headcount = cache.search("headcount")
    assert len(res_headcount) == 1
    assert res_headcount[0].cap_id == "hr.reports.headcount"

    # Search substring matching description: "employee"
    res_emp = cache.search("employee")
    assert len(res_emp) >= 1
    assert any(c.cap_id == "hr.employee.get" for c in res_emp)

    # Fuzzy match / difflib fill-up for typos: e.g. "headcount" vs "headc" or close cap_id match
    res_fuzzy = cache.search("hr.report.headcount")
    assert len(res_fuzzy) >= 1
    assert res_fuzzy[0].cap_id == "hr.reports.headcount"

    # Limit constraint
    res_limit = cache.search("", limit=2)
    assert len(res_limit) == 2
