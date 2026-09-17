import json

import pytest
from types import SimpleNamespace
from asyncdb.exceptions import NoDataFound
from parrot_tools.querysource import _qs

PIPELINE = {
    "queries": {"a": {"slug": "pokemon_all_fso_odoo_new"}, "b": {"slug": "pokemon_warehouses_kiosk_all_fso"}},
    "Join": [{"type": "left", "left": "a", "right": "b", "using": ["warehouse_alias"]}],
    "Output": [{"tableOutput": {"flavor": "postgresql", "tablename": "t", "schema": "pokemon"}}],
}


@pytest.fixture
def fake_rows():
    return {
        "epson_field_activity": SimpleNamespace(
            query_slug="epson_field_activity", program_slug="epson", description="Field activity",
            provider="db", is_cached=True, cache_timeout=3600,
            conditions={"firstdate": "2026-01-01", "lastdate": "2026-01-31"},
            cond_definition={"firstdate": "date", "lastdate": "date"}, filtering={}, fields=[], ordering=[],
            grouping=[],
            query_raw="SELECT * FROM epson.activity WHERE d BETWEEN {firstdate} AND {lastdate} {where_cond}",
        ),
        "pokemon_all_fso_odoo_new": SimpleNamespace(
            query_slug="pokemon_all_fso_odoo_new", program_slug="pokemon", description=None,
            provider="db", is_cached=False, cache_timeout=0, conditions={}, cond_definition={}, filtering={},
            fields=[], ordering=[], grouping=[], query_raw=json.dumps(PIPELINE),
        ),
    }


class FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeAsyncDB:
    def __init__(self, *a, **k):
        self.closed = False

    async def connection(self):
        return FakeConn()

    async def close(self):
        self.closed = True


@pytest.fixture
def patched_qs(monkeypatch, fake_rows):
    calls = {"get": [], "filter": [], "insert": [], "update": []}

    class FakeQueryModel:
        def __init__(self, **kw):
            self.__dict__.update(kw)

        @classmethod
        async def get(cls, *, _connection=None, **kw):
            calls["get"].append((kw, _connection))
            row = fake_rows.get(kw["query_slug"])
            if row is None:
                # Real "no such row" signal (asyncdb.exceptions.NoDataFound) — matches production behavior
                # so catalog.py's narrowed `except (NoDataFound, SlugNotFound)` clauses exercise real types.
                raise NoDataFound(kw["query_slug"])
            return row

        @classmethod
        async def filter(cls, *a, _connection=None, **kw):
            calls["filter"].append(kw)
            return [r for r in fake_rows.values() if r.program_slug == kw.get("program_slug")]

        @classmethod
        async def all(cls, *, _connection=None, **kw):
            return list(fake_rows.values())

        async def insert(self, *, _connection=None, **kw):
            calls["insert"].append(self.__dict__)
            return self

        async def update(self, *, _connection=None, **kw):
            calls["update"].append(self.__dict__)
            return self

    monkeypatch.setattr(_qs, "QueryModel", FakeQueryModel)
    monkeypatch.setattr("parrot_tools.querysource.catalog.AsyncDB", FakeAsyncDB)
    return calls
