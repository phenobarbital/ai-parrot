"""Tests for the AGENT exact-match index in CapabilityRegistry (FEAT-747 M3a)."""
import time

import pytest

from parrot.registry.capabilities.models import ResourceType
from parrot.registry.capabilities.registry import CapabilityRegistry


def test_agent_member():
    assert ResourceType.AGENT.value == "agent"
    assert {m.value for m in ResourceType} >= {"dataset", "tool", "graph_node", "pageindex", "vector_collection"}


def test_find_exact_capid_glob_keyword():
    reg = CapabilityRegistry()
    reg.register_agent_capability("hr-agent", "hr.people.salary", keywords=["salary", "pay"], category="hr.people")
    for q in ("hr.people.salary", "hr.people.*", "SALARY", "hr.people", "hr.*"):
        assert [e.metadata["agent_name"] for e in reg.find_exact(q)] == ["hr-agent"], q
    assert reg.find_exact("nope") == []
    assert reg.find_exact("hr.other.*") == []


def test_reregister_replaces_and_unregister():
    reg = CapabilityRegistry()
    reg.register_agent_capability("a", "x.y")
    reg.register_agent_capability("a", "x.y")
    assert len(reg.find_exact("x.y")) == 1 and len(reg._entries) == 1
    assert reg.unregister_agent("a") == 1 and reg.find_exact("x.y") == [] and reg._entries == []
    assert reg.unregister_agent("a") == 0


def test_resource_type_filter_and_limit():
    reg = CapabilityRegistry()
    for i in range(3):
        reg.register_agent_capability(f"a{i}", "x.y")
    assert len(reg.find_exact("x.y", limit=2)) == 2
    assert reg.find_exact("x.y", resource_types=[ResourceType.TOOL]) == []


@pytest.mark.asyncio
async def test_search_still_sees_agent_entries_dirty_flag():
    reg = CapabilityRegistry()
    reg.register_agent_capability("a", "x.y")
    assert reg._index_dirty is True
    assert reg._entries[0].resource_type == ResourceType.AGENT


def test_lookup_under_5ms():
    reg = CapabilityRegistry()
    for i in range(1000):
        reg.register_agent_capability(f"a{i}", f"cat{i % 50}.cap{i}", keywords=[f"kw{i}"])
    reg.register_agent_capability("hr-agent", "hr.people.salary", keywords=["salary"])
    t0 = time.perf_counter()
    assert reg.find_exact("salary")
    assert (time.perf_counter() - t0) < 0.005
