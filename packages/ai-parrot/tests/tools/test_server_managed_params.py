"""FEAT-622 M4: server-managed parameter declarations, schema marking and golden built-in schemas."""

import importlib
import json
from pathlib import Path

import pytest
from parrot.knowledge.wiki import LLMWikiToolkit
from parrot.tools.abstract import AbstractTool
from parrot.tools.config_schema import build_schema_envelope, introspect_config_schema, model_config_schema
from parrot.tools.infographic_toolkit import InfographicToolkit
from parrot.tools.server_params import (
    ServerParam,
    constructor_server_params,
    method_server_params,
)
from parrot.tools.toolkit import AbstractToolkit
from pydantic import BaseModel

from ._host_probe import host_plugins  # noqa: F401

GOLDEN = json.loads((Path(__file__).parent / "data" / "feat622_builtin_schemas_golden.json").read_text())


def test_server_param_app_requires_key():
    with pytest.raises(ValueError):
        ServerParam(source="app")
    assert ServerParam(source="app", key="k").key == "k"


def test_ctor_and_method_params_are_split(host_plugins):  # noqa: F811
    probe = importlib.import_module("plugins.tools.probe").ProbeToolkit
    assert constructor_server_params(probe) == frozenset({"app_store"})
    assert set(method_server_params(probe)) == {"tenant"}


def test_server_managed_ctor_param_marked_on_both_schema_paths(host_plugins):  # noqa: F811
    probe = importlib.import_module("plugins.tools.probe").ProbeToolkit
    assert introspect_config_schema(probe)["properties"]["app_store"] == {"x-server-managed": True}

    class _Config(BaseModel):
        app_store: str = "x"
        other: int = 1

    class _ModelKit(AbstractToolkit):
        config_model = _Config
        server_managed_params = {"app_store": ServerParam(source="app", key="s")}

        def __init__(self, app_store: str = "x", other: int = 1, **kwargs):
            super().__init__(**kwargs)

    schema = model_config_schema(_ModelKit)
    assert schema["properties"]["app_store"] == {"x-server-managed": True}
    assert schema["properties"]["other"].get("x-server-managed") is None


def test_json_typed_ctor_param_is_marked_by_the_classvar_alone():
    """A str-typed ctor param is only ``x-server-managed`` because the ClassVar declares it."""

    class _IntroKit(AbstractToolkit):
        server_managed_params = {"endpoint": ServerParam(source="app", key="endpoint")}

        def __init__(self, endpoint: str = "x", other: str = "y", **kwargs):
            super().__init__(**kwargs)

    props = introspect_config_schema(_IntroKit)["properties"]
    assert props["endpoint"] == {"x-server-managed": True} and props["other"]["type"] == "string"


def test_method_server_param_absent_from_generated_args_schema(host_plugins):  # noqa: F811
    probe = importlib.import_module("plugins.tools.probe").ProbeToolkit
    tools = {tool.name: tool for tool in probe().get_tools()}
    assert "tenant" not in tools["tp_whoami"].args_schema.model_json_schema().get("properties", {})


@pytest.mark.parametrize("source", ["tenant", "caller", "agent"])
def test_scope_source_on_ctor_param_is_typeerror(source):
    with pytest.raises(TypeError):

        class _Bad(AbstractToolkit):
            server_managed_params = {"conn": ServerParam(source=source)}

            def __init__(self, conn: object = None, **kwargs):
                super().__init__(**kwargs)

    with pytest.raises(TypeError):

        class _BadTool(AbstractTool):
            server_managed_params = {"conn": ServerParam(source=source)}

            def __init__(self, conn: object = None, **kwargs):
                super().__init__(**kwargs)


def test_scope_source_on_method_param_is_allowed():
    class _Good(AbstractToolkit):
        server_managed_params = {"tenant": ServerParam(source="tenant")}

        async def ask(self, tenant: str | None = None) -> str:
            """Ask."""
            return "ok"

    assert set(method_server_params(_Good)) == {"tenant"}


@pytest.mark.parametrize("slug,cls", [("wiki", LLMWikiToolkit), ("infographic", InfographicToolkit)])
def test_builtin_schemas_match_golden(slug, cls):
    """The ClassVar declaration alone reproduces the schema the server dicts produced before the change."""
    now = json.loads(json.dumps(build_schema_envelope(slug, cls).model_dump(by_alias=True), sort_keys=True, default=str))
    assert now == GOLDEN[slug]
