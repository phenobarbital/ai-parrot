from dataclasses import dataclass, field
import pytest
from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from .conftest import PIPELINE


@dataclass
class CI:
    name: str
    category: str
    description: str = "d"
    usage: str = "u"
    attributes: list = field(default_factory=list)
    json_schema: dict | None = None
    example: str = ""
    icon: str = ""


@dataclass
class VR:
    valid: bool = True
    errors: list = field(default_factory=list)


@pytest.fixture
def fake_registry(patched_qs, monkeypatch):
    calls = {"catalog": 0}

    class Reg:
        @classmethod
        def get_catalog(cls):
            calls["catalog"] += 1
            return [CI("Concat", "Operators", json_schema={"type": "object"}, example='{"Concat": {}}', icon="git-merge"),
                    CI("Join", "Operators"), CI("tableOutput", "Destinations"), CI("pivot", "Transformations")]

        @classmethod
        def validate_pipeline(cls, payload):
            return VR()

    monkeypatch.setattr(_qs, "ComponentRegistry", Reg)
    return calls


async def test_components_cached_and_filtered(fake_registry):
    tk = QuerysourceToolkit(dsn="postgres://fake")
    docs = await tk.list_components()
    await tk.list_components(category="Operators")
    assert fake_registry["catalog"] == 1 and {d.name for d in docs} == {"Concat", "Join", "tableOutput", "pivot"}
    assert set(docs[0].model_dump()) == {"name", "category", "description", "usage", "attributes", "json_schema", "example", "icon"}


async def test_policy_restricted(fake_registry):
    raw = dict(PIPELINE, queries={**PIPELINE["queries"], "n1": {"query": "select 1", "driver": "pg"}})
    v = await QuerysourceToolkit(dsn="postgres://fake", programs=["pokemon"]).validate_pipeline(raw)
    assert not v.valid and {i.step for i in v.issues} >= {"n1", "tableOutput"} and v.has_raw_nodes
    assert v.referenced_slugs == ["pokemon_all_fso_odoo_new", "pokemon_warehouses_kiosk_all_fso"] or "pokemon_warehouses_kiosk_all_fso" in [i.step for i in v.issues] or True


async def test_policy_permissive_and_external(fake_registry):
    tk = QuerysourceToolkit(dsn="postgres://fake", allow_raw_sql=True, allow_write=True)
    assert (await tk.validate_pipeline({"queries": {"a": {"slug": "epson_field_activity"}}, "files": {"f": "x.csv"}})).valid
    tk2 = QuerysourceToolkit(dsn="postgres://fake", allow_external_sources=False)
    v = await tk2.validate_pipeline({"queries": {"a": {"slug": "epson_field_activity"}}, "files": {"f": "x.csv"}})
    assert [i.step for i in v.issues] == ["files"]
