"""PA-5: ``TenantToolingPolicy.tenant_builtin_tools`` — the per-tenant allow-list of BUILT-IN slugs (pure policy)."""
from __future__ import annotations

import pytest

from parrot.tools.tooling_policy import TenantToolingPolicy, TenantToolingRefused, ToolingSubject

BUILTINS = frozenset({"calculator", "arxiv"})


def _subject(tenant="acme", phase="attach", held=frozenset()):
    return ToolingSubject(tenant=tenant, agent_id=None, actor=None, phase=phase, held=held)


def _policy(callback):
    return TenantToolingPolicy(builtin_tools=BUILTINS, tenant_builtin_tools=callback)


def test_none_callback_changes_nothing():
    policy = TenantToolingPolicy(builtin_tools=BUILTINS)
    policy.check_tool("arxiv", subject=_subject())
    with pytest.raises(TenantToolingRefused) as err:
        policy.check_tool("excel", subject=_subject())
    assert err.value.reason == "builtin_not_permitted"


def test_allow_list_narrows_the_global_set():
    policy = _policy(lambda tenant: {"calculator"})
    policy.check_tool("calculator", subject=_subject())
    with pytest.raises(TenantToolingRefused) as err:
        policy.check_tool("arxiv", subject=_subject())
    assert err.value.reason == "toolkit_unavailable"
    with pytest.raises(TenantToolingRefused) as err:  # never WIDENS the global set
        _policy(lambda tenant: {"calculator", "excel"}).check_tool("excel", subject=_subject())
    assert err.value.reason == "builtin_not_permitted"


def test_none_for_a_tenant_is_unrestricted_and_case_is_ignored():
    _policy(lambda tenant: None).check_tool("arxiv", subject=_subject())
    _policy(lambda tenant: {"CALCULATOR"}).check_tool("calculator", subject=_subject())
    _policy(lambda tenant: "arxiv").check_tool("arxiv", subject=_subject())  # one slug, not a substring pool
    with pytest.raises(TenantToolingRefused):
        _policy(lambda tenant: "arxiv").check_tool("calculator", subject=_subject())


async def _async_callback(tenant):
    return {"arxiv"}


@pytest.mark.parametrize("callback", [_async_callback, lambda t: 5, lambda t: True, lambda t: 1 / 0],
                         ids=["async", "int", "bool", "raises"])
def test_malformed_or_failing_callback_fails_closed(callback):
    with pytest.raises(TenantToolingRefused):
        _policy(callback).check_tool("arxiv", subject=_subject())


def test_held_build_global_and_execute_rules():
    policy = _policy(lambda tenant: set())
    policy.check_tool("arxiv", subject=_subject(held=frozenset({"arxiv"})))      # held: write leaves it untouched
    policy.check_tool("arxiv", subject=_subject(phase="build"))                    # a stored agent still builds
    policy.check_tool("arxiv", subject=_subject(tenant=None))                      # the global partition
    with pytest.raises(TenantToolingRefused):
        policy.check_tool("arxiv", subject=_subject(phase="execute"))  # refused at call time


def test_pinned_for_resolves_both_allow_lists_once():
    calls = {"toolkits": 0, "builtins": 0}

    def toolkits(tenant):
        calls["toolkits"] += 1
        return None

    def builtins(tenant):
        calls["builtins"] += 1
        return {"calculator"}

    policy = TenantToolingPolicy(builtin_tools=BUILTINS, tenant_toolkits=toolkits, tenant_builtin_tools=builtins)
    pinned = policy.pinned_for(_subject())
    for _ in range(5):
        pinned.check_tool("calculator", subject=_subject())
    assert calls == {"toolkits": 1, "builtins": 1}
    assert policy.pinned_for(_subject(phase="build")) is policy and policy.pinned_for(_subject(tenant=None)) is policy
