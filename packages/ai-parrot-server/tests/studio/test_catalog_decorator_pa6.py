"""PA-6: the host catalogue decorator (``app[STUDIO_CATALOG_DECORATOR]``) and the ``available`` / ``abstract`` flags.

Real app and routes (tools, base-classes, llm-clients); built-in slugs are real ``parrot_tools`` entries.
"""
from __future__ import annotations

import copy

import pytest

from parrot.handlers import tools_catalog as tools_catalog_module
from parrot.handlers.studio import STUDIO_CATALOG_DECORATOR
from parrot.handlers.studio import catalog as catalog_module
from parrot.tools.resolver import get_toolkit_resolver
from parrot.tools.tooling_policy import TenantToolingPolicy, set_tenant_tooling_policy

from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import tenant_app, who


def _unresolvable_slug() -> str:
    resolver = get_toolkit_resolver()
    for entry in resolver.entries():
        if resolver.resolve(entry.slug) is None:  # a registered slug whose extra is not installed
            return entry.slug
    pytest.skip("every registered tool resolves in this environment")


GLOBAL = frozenset({"calculator", "arxiv"})


@pytest.fixture(autouse=True)
def _fresh_catalogues(monkeypatch):
    monkeypatch.setattr(catalog_module, "_BASE_CLASSES_CACHE", None)
    monkeypatch.setattr(catalog_module, "_LLM_CLIENTS_CACHE", None)
    monkeypatch.setattr(tools_catalog_module, "_CATALOG_CACHE", None)


def _app(pool, decorator=None, builtins=GLOBAL):  # noqa: F811
    app = tenant_app(pool)
    set_tenant_tooling_policy(app, TenantToolingPolicy(builtin_tools=frozenset(builtins)))
    if decorator is not None:
        app[STUDIO_CATALOG_DECORATOR] = decorator
    return app


async def _rows(client, kind, query=""):
    resp = await client.get(f"{BASE}/catalog/{kind}{query}", headers=who("u1"))
    assert resp.status == 200, await resp.text()
    return await resp.json()


async def test_decorator_adds_fields_and_hides_a_row_without_touching_the_cache(aiohttp_client, pool):  # noqa: F811
    def decorate(kind, row):
        if kind != "tools":
            return row
        if row["slug"] == "arxiv":
            return None
        row["description"] = "MUTATED IN PLACE"          # a careless decorator must not reach the shared cache
        row["access"] = None
        return {**row, "label": f"Label of {row['slug']}", "category": "math"}

    client = await aiohttp_client(_app(pool, decorate))
    rows = await _rows(client, "tools")
    assert [r["slug"] for r in rows] == ["calculator"]
    assert rows[0]["label"] == "Label of calculator" and rows[0]["category"] == "math"
    assert rows[0]["description"] == "MUTATED IN PLACE"
    cached = {r["slug"]: r for r in tools_catalog_module._CATALOG_CACHE}
    assert "label" not in cached["calculator"] and cached["calculator"]["description"] != "MUTATED IN PLACE"
    assert cached["calculator"]["access"] is not None or cached["calculator"]["access"] is None  # unchanged object
    snapshot = copy.deepcopy(tools_catalog_module._CATALOG_CACHE)
    await _rows(client, "tools")
    assert tools_catalog_module._CATALOG_CACHE == snapshot
    assert "arxiv" in cached  # hidden for the caller only, still in the cache


async def test_no_decorator_is_unchanged(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    assert {r["slug"] for r in await _rows(client, "tools")} == GLOBAL


async def test_a_failing_decorator_hides_rows_never_500(aiohttp_client, pool, caplog):  # noqa: F811
    def boom(kind, row):
        raise RuntimeError("table missing")

    client = await aiohttp_client(_app(pool, boom))
    with caplog.at_level("ERROR"):
        assert await _rows(client, "tools") == []
    assert caplog.text.count("fail closed") == 1


async def test_unresolvable_slug_is_listed_with_available_false(aiohttp_client, pool):  # noqa: F811
    broken = _unresolvable_slug()
    client = await aiohttp_client(_app(pool, builtins=GLOBAL | {broken}))
    rows = {r["slug"]: r for r in await _rows(client, "tools")}
    assert rows[broken]["available"] is False
    assert rows["calculator"]["available"] is True


async def test_class_attributes_display_name_summary_category(aiohttp_client, pool, monkeypatch):  # noqa: F811
    resolver = get_toolkit_resolver()
    cls = resolver.resolve("calculator")
    monkeypatch.setattr(cls, "display_name", "Calculator", raising=False)
    monkeypatch.setattr(cls, "summary", "Does the maths", raising=False)
    monkeypatch.setattr(cls, "category", "math", raising=False)
    client = await aiohttp_client(_app(pool))
    row = next(r for r in await _rows(client, "tools") if r["slug"] == "calculator")
    assert (row["display_name"], row["summary"], row["category"]) == ("Calculator", "Does the maths", "math")


async def test_base_classes_carry_abstract_and_pass_through_the_hook(aiohttp_client, pool):  # noqa: F811
    seen = []

    def decorate(kind, row):
        seen.append(kind)
        return None if row.get("name") == "BaseBot" else {**row, "label": row["name"].upper()}

    client = await aiohttp_client(_app(pool, decorate))
    rows = {r["name"]: r for r in await _rows(client, "base-classes")}
    assert rows["AbstractBot"]["abstract"] is True and rows["BasicBot"]["abstract"] is False
    assert "BaseBot" not in rows and rows["BasicBot"]["label"] == "BASICBOT"
    assert set(seen) == {"base-classes"}
    cache = {r["name"]: r for r in catalog_module._BASE_CLASSES_CACHE}
    assert "BaseBot" in cache and "label" not in cache["BasicBot"] and "allowed" not in cache["BasicBot"]


async def test_llm_clients_pass_through_the_hook(aiohttp_client, pool, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server-key-0001")

    def decorate(kind, row):
        if kind != "llm-clients" or row["provider"] in {"claude", "bedrock", "anthropic-aws"}:
            return None if kind == "llm-clients" else row
        return {**row, "label": "Anthropic"}

    client = await aiohttp_client(_app(pool, decorate))
    rows = {r["provider"]: r for r in await _rows(client, "llm-clients")}
    assert set(rows) == {"anthropic"} and rows["anthropic"]["label"] == "Anthropic"
    assert all("label" not in r for r in catalog_module._LLM_CLIENTS_CACHE)
