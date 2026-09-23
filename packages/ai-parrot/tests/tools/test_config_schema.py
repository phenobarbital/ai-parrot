from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field
from parrot.tools.config_schema import build_schema_envelope, is_secret_name, secret_paths


class _Resolver: ...


class _Plain:
    secret_params = frozenset({"weird"})

    def __init__(self, server_url: str, token: Optional[str] = None, weird: str = "", max_rows: int = 5,
                 credential_resolver: _Resolver = None, **kwargs): ...


class _A(BaseModel):
    kind: Literal["a"]
    name: str
    dsn: Optional[str] = None


class _B(BaseModel):
    kind: Literal["b"]
    name: str
    api_key: Optional[str] = None


class _Cfg(BaseModel):
    datasources: list[Annotated[Union[_A, _B], Field(discriminator="kind")]] = []


class _Modeled:
    config_model = _Cfg


def test_introspection_envelope():
    env = build_schema_envelope("plain", _Plain)
    props = env.schema_["properties"]
    assert env.source == "introspection"
    assert env.schema_["required"] == ["server_url"]
    assert props["token"]["x-secret"] is True and props["weird"]["x-secret"] is True
    assert props["credential_resolver"]["x-server-managed"] is True
    assert props["max_rows"]["type"] == "integer"


def test_model_envelope():
    assert build_schema_envelope("m", _Modeled).source == "model"


def test_secret_paths_oneof():
    schema = build_schema_envelope("m", _Modeled).schema_
    params = {"datasources": [{"kind": "a", "name": "x", "dsn": "d"}, {"kind": "b", "name": "y", "api_key": "k"}]}
    assert sorted(secret_paths(schema, params)) == ["datasources.0.dsn", "datasources.1.api_key"]


def test_is_secret_name():
    assert is_secret_name("API_KEY") and not is_secret_name("server_url")
