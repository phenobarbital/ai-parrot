"""PA-9 (core): the host toolkit-parameter hook — contract, ToolManager choke point, write-time enforcement."""
from __future__ import annotations

import pytest

from parrot.tools.host_hooks import (
    FEATURES,
    STUDIO_TOOLKIT_PARAM_HOOK,
    apply_exclude_tools,
    check_toolkit_params,
    run_toolkit_param_hook,
    split_exclude_tools,
)
from parrot.tools.manager import ToolManager, get_toolkit_owner
from parrot.tools.spec import NormalizedTooling, ToolkitSpec
from parrot.tools.tooling_policy import (
    TenantToolingPolicy,
    TenantToolingRefused,
    ToolingSubject,
    ToolParamRefused,
    enforce_tenant_tooling,
    set_tenant_tooling_policy,
)
from parrot.tools.toolkit import AbstractToolkit


class HookedToolkit(AbstractToolkit):
    """A toolkit with an explicit constructor (no ``**kwargs`` forwarding of ``exclude_tools``)."""

    def __init__(self, storage_dir: str = "", **kwargs):
        super().__init__(**kwargs)
        self.storage_dir = storage_dir

    async def read_thing(self) -> str:
        """Read."""
        return "r"

    async def write_thing(self) -> str:
        """Write."""
        return "w"


def _subject(phase="attach", tenant="acme", held=frozenset()):
    return ToolingSubject(tenant=tenant, agent_id=None, actor="u1", phase=phase, held=held)


def _force(slug, params, subject):
    return {**params, "storage_dir": "/forced", "exclude_tools": ("write_thing",)}


def test_feature_probe_and_key():
    assert "toolkit_param_hook" in FEATURES and STUDIO_TOOLKIT_PARAM_HOOK == "studio_toolkit_param_hook"


def test_the_hook_gets_a_copy_and_returns_a_new_dict():
    original = {"a": 1}

    def hook(slug, params, subject):
        params["a"] = 2
        return params

    final = run_toolkit_param_hook(hook, "x", original, _subject())
    assert final == {"a": 2} and original == {"a": 1}


@pytest.mark.parametrize(
    "hook",
    [lambda s, p, subj: 1 / 0, lambda s, p, subj: None, lambda s, p, subj: [("a", 1)],
     lambda s, p, subj: {"exclude_tools": "write_thing"}, lambda s, p, subj: {"exclude_tools": [1]}],
    ids=["raises", "none", "not-mapping", "str-exclude", "non-str-exclude"],
)
def test_a_broken_hook_refuses(hook):
    with pytest.raises(ToolParamRefused) as err:
        run_toolkit_param_hook(hook, "x", {}, _subject())
    assert err.value.reason == "tool_params_not_permitted" and err.value.item == "x"


def test_an_async_hook_refuses():
    async def hook(slug, params, subject):
        return params

    with pytest.raises(ToolParamRefused):
        run_toolkit_param_hook(hook, "x", {}, _subject())


def test_a_refusal_carries_the_params_and_defaults_the_item_to_the_slug():
    def hook(slug, params, subject):
        raise ToolParamRefused(["b", "a", "a"])

    with pytest.raises(ToolParamRefused) as err:
        run_toolkit_param_hook(hook, "tp", {}, _subject())
    assert err.value.params == ["a", "b"] and err.value.item == "tp" and isinstance(err.value, TenantToolingRefused)


def test_exclude_tools_is_instance_level_and_additive():
    params, exclude = split_exclude_tools({"a": 1, "exclude_tools": ["write_thing"]})
    assert params == {"a": 1} and exclude == ("write_thing",)
    first, second = HookedToolkit(), HookedToolkit()
    apply_exclude_tools(first, exclude)
    assert first.exclude_tools == ("write_thing",) and second.exclude_tools == () and HookedToolkit.exclude_tools == ()


def test_build_toolkit_forces_values_whatever_the_constructor_accepts():
    manager = ToolManager()
    manager.set_toolkit_param_hook(_force, _subject())
    toolkit = manager.build_toolkit(HookedToolkit, "hooked", {"storage_dir": "/client"})
    assert toolkit.storage_dir == "/forced" and toolkit.exclude_tools == ("write_thing",)
    names = {tool.name for tool in toolkit.get_tools_sync()}
    assert "read_thing" in names and "write_thing" not in names


def test_without_a_hook_it_is_cls_of_params():
    toolkit = ToolManager().build_toolkit(HookedToolkit, "hooked", {"storage_dir": "/client"})
    assert toolkit.storage_dir == "/client" and toolkit.exclude_tools == ()


def test_phase_override_and_register_toolkit_and_clone():
    seen = []

    def hook(slug, params, subject):
        seen.append((slug, subject.phase))
        return params

    manager = ToolManager()
    manager.set_toolkit_param_hook(hook, _subject(phase="build"))
    manager.build_toolkit(HookedToolkit, "hooked", {}, phase="attach")
    manager.register_toolkit(HookedToolkit, storage_dir="/x")          # by class: the hook sees it as well
    clone = manager.clone()
    clone.build_toolkit(HookedToolkit, "hooked", {})                    # a per-session clone keeps the hook
    assert seen[0] == ("hooked", "attach") and seen[1][1] == "build" and seen[2] == ("hooked", "build")
    tools = manager.register_toolkit(HookedToolkit, storage_dir="/y")
    assert {t.name for t in tools} >= {"read_thing", "write_thing"} and get_toolkit_owner(tools[0]) is not None


def test_register_toolkit_by_class_is_refused_by_the_hook():
    def hook(slug, params, subject):
        raise ToolParamRefused(["storage_dir"])

    manager = ToolManager()
    manager.set_toolkit_param_hook(hook, _subject())
    with pytest.raises(ToolParamRefused):
        manager.register_toolkit(HookedToolkit, storage_dir="/x")
    assert manager.list_tools() == []


def _tooling(*slugs):
    return NormalizedTooling(toolkits=[ToolkitSpec(slug=slug, params={"storage_dir": "/x"}) for slug in slugs])


def test_write_time_enforcement_runs_the_hook_on_every_partition_and_skips_held_specs():
    def refuse(slug, params, subject):
        raise ToolParamRefused(["storage_dir"])

    app: dict = {STUDIO_TOOLKIT_PARAM_HOOK: refuse}
    set_tenant_tooling_policy(app, TenantToolingPolicy(builtin_tools=frozenset({"wiki"}), apply_to_global=True))
    for tenant in ("acme", None):                                    # the global partition is checked too
        with pytest.raises(ToolParamRefused):
            enforce_tenant_tooling(app, _tooling("wiki"), subject=_subject(phase="write", tenant=tenant))
    enforce_tenant_tooling(  # stored and unchanged: not re-checked on an unrelated write (the build re-checks it)
        app, _tooling("wiki"), subject=_subject(phase="write", held=frozenset({"wiki"}))
    )
    check_toolkit_params({}, _tooling("wiki"), subject=_subject())   # no hook: a no-op
    enforce_tenant_tooling({}, _tooling("wiki"), subject=_subject(tenant=None))  # nothing registered at all


# -- PA-V2 review fix 6: the hook is keyed by the CANONICAL slug, whatever spelling reached the manager ------------------


@pytest.mark.parametrize("spelling", ["calculator", "Calculator", "CALCULATOR", "CalculatorTool"])
def test_the_hook_receives_the_canonical_slug_for_every_spelling(spelling):
    seen: list[str] = []

    def hook(slug, params, subject):
        seen.append(slug)
        return params

    manager = ToolManager()
    manager.set_toolkit_param_hook(hook, _subject(phase="build"))
    assert manager.load_tool(spelling) is True
    assert seen == ["calculator"]


def test_a_pass_through_policy_keyed_by_slug_cannot_be_dodged_by_case():
    refused = {"calculator"}

    def hook(slug, params, subject):
        if slug in refused:
            raise ToolParamRefused(["expression"])
        return params

    manager = ToolManager()
    manager.set_toolkit_param_hook(hook, _subject(phase="build"))
    for spelling in ("Calculator", "CALCULATOR"):
        with pytest.raises(ToolParamRefused):
            manager.load_tool(spelling)


def test_a_hook_mutating_a_nested_value_cannot_reach_the_callers_spec():
    """P3: the hook gets a DEEP copy, so mutating a nested header dict / list never alters the stored spec."""
    original = {"headers": {"X-A": "1"}, "paths": ["a"]}

    def hook(slug, params, subject):
        params["headers"]["X-Evil"] = "1"
        params["paths"].append("/etc")
        return params

    run_toolkit_param_hook(hook, "x", original, _subject())
    assert original == {"headers": {"X-A": "1"}, "paths": ["a"]}


def test_a_server_managed_object_in_the_params_is_shared_not_copied():
    class Store:
        def __deepcopy__(self, memo):
            raise RuntimeError("a store must never be copied")

    store = Store()
    seen = {}

    def hook(slug, params, subject):
        seen["store"] = params["artifact_store"]
        return params

    run_toolkit_param_hook(hook, "x", {"artifact_store": store}, _subject())
    assert seen["store"] is store
