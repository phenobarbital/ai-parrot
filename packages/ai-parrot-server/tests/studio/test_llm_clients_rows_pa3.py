"""PA-3: every ``/catalog/llm-clients`` row has the same keys, no raw exception text, ``default_model ∈ models``.

Real aiohttp app and Studio routes; the only seam is the loader table (a loader that raises is the fault injected).
"""
from __future__ import annotations

import logging

import pytest

from parrot.clients.factory import LLMFactory
from parrot.handlers.studio import catalog as catalog_module
from parrot.handlers.studio.catalog import _normalise_default_model

from .test_agents_db_mode import BASE, _app, _offline, pool  # noqa: F401  (pool/_offline are fixtures)

ROW_KEYS = {
    "provider", "class_name", "lazy", "available", "error", "default_model", "models", "deprecated_models",
    "credentials",
}
SECRET = "/srv/secret/path/boto3-missing"


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(catalog_module, "_LLM_CLIENTS_CACHE", None)


async def test_failed_import_row_has_the_full_key_set(aiohttp_client, pool, monkeypatch, caplog):  # noqa: F811
    def _boom():
        raise ImportError(f"cannot import {SECRET}")

    real = LLMFactory.supported_clients()
    monkeypatch.setattr(
        catalog_module.LLMFactory, "supported_clients", staticmethod(lambda: {"broken": _boom, "openai": real["openai"]})
    )
    client = await aiohttp_client(_app(pool))
    with caplog.at_level(logging.WARNING):
        resp = await client.get(f"{BASE}/catalog/llm-clients", params={"usable": "0"})
    rows = {r["provider"]: r for r in await resp.json()}
    assert resp.status == 200
    broken = rows["broken"]
    assert set(broken) == ROW_KEYS
    assert broken["available"] is False and broken["error"] == "import_failed" and broken["class_name"] is None
    assert broken["default_model"] is None and broken["models"] == [] and broken["deprecated_models"] == []
    assert broken["credentials"] == []
    assert SECRET not in str(rows)
    assert SECRET in caplog.text  # the detail is logged for operators, not echoed to tenants
    assert set(rows["openai"]) == ROW_KEYS


async def test_every_installed_provider_has_a_member_default_model(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp = await client.get(f"{BASE}/catalog/llm-clients", params={"usable": "0"})
    rows = await resp.json()
    providers = set(LLMFactory.supported_clients())
    assert {r["provider"] for r in rows} == providers and providers
    for row in rows:
        assert set(row) == ROW_KEYS, row["provider"]
        assert row["default_model"] is None or row["default_model"] in row["models"], row["provider"]
    anthropic = next(r for r in rows if r["provider"] == "anthropic")
    assert anthropic["default_model"].startswith("claude-sonnet-4-5") and anthropic["default_model"] in anthropic["models"]


@pytest.mark.parametrize(
    "default,models,expected",
    [
        ("m", ["m", "m-20250101"], "m"),
        ("claude-sonnet-4-5", ["x", "claude-sonnet-4-5-20250101", "claude-sonnet-4-5-20250929"], "claude-sonnet-4-5-20250929"),
        ("claude-sonnet-4-5-20250929", ["claude-sonnet-4-5"], "claude-sonnet-4-5"),
        ("gone", ["other"], None),
        ("m-2", ["m-20250101"], None),
        (None, ["a"], None),
        ("", ["a"], None),
    ],
)
def test_normalise_default_model(default, models, expected):
    assert _normalise_default_model(default, models) == expected
