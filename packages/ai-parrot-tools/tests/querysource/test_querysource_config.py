from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot_tools.querysource import _qs
from parrot_tools.querysource.catalog import SlugCatalog, TenantGuard
from parrot_tools.querysource.toolkit import QuerysourceToolkit


def test_schema():
    props = QuerysourceToolkit.config_schema("querysource")["schema"]["properties"]
    assert props["programs"]["x-options"] is True and props["dsn"]["x-secret"] is True


@pytest.mark.asyncio
async def test_config_options_programs(monkeypatch):
    kit = QuerysourceToolkit()
    monkeypatch.setattr(kit, "_open", AsyncMock())
    kit._catalog = SimpleNamespace(list_programs=AsyncMock(return_value=["a", "b"]))
    assert [option.value for option in await kit.config_options("programs")] == ["a", "b"]


@pytest.mark.asyncio
async def test_list_programs_distinct_sorted(monkeypatch):
    class FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class FakeDatabase:
        async def connection(self):
            return FakeConnection()

    class FakeQueryModel:
        @classmethod
        async def all(cls, *, _connection):
            return [
                SimpleNamespace(program_slug="b"),
                SimpleNamespace(program_slug="a"),
                SimpleNamespace(program_slug="b"),
            ]

    catalog = SlugCatalog("postgres://fake", TenantGuard(["restricted"]))
    catalog._db = FakeDatabase()
    monkeypatch.setattr(_qs, "QueryModel", FakeQueryModel)

    assert await catalog.list_programs() == ["a", "b"]
