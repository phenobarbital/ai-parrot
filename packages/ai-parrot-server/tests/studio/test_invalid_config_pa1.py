"""PA-1: out-of-range / mistyped model params are ``422 invalid_config`` with per-field ``details``.

Real aiohttp app and Postgres through the Studio routes (create, PATCH, draft save, the model-params catalogue).
"""
from __future__ import annotations

import pytest

from .test_agents_db_mode import BASE, _app, _create, _offline, pool  # noqa: F401  (pool/_offline are fixtures)


def _detail(field, constraint, limit):
    return {"field": field, "constraint": constraint, "limit": limit}


def _pick(details):
    return [{k: d[k] for k in ("field", "constraint", "limit")} for d in details]


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"top_p": 2}, [_detail("top_p", "le", 1.0)]),
        ({"top_p": 0}, [_detail("top_p", "gt", 0.0)]),
        ({"temperature": -1}, [_detail("temperature", "ge", 0.0)]),
        ({"max_tokens": "x"}, [_detail("max_tokens", "type", None)]),
        ({"top_p": 2, "temperature": 3}, [_detail("top_p", "le", 1.0), _detail("temperature", "le", 2.0)]),
    ],
)
async def test_create_model_param_errors(aiohttp_client, pool, params, expected):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp, body = await _create(client, config=params)
    assert resp.status == 422 and body["code"] == "invalid_config"
    assert sorted(_pick(body["details"]), key=lambda d: d["field"]) == sorted(expected, key=lambda d: d["field"])
    assert all(d["message"] for d in body["details"])
    assert "Traceback" not in body["message"] and "pydantic" not in body["message"].lower()


async def test_create_other_refusals_keep_their_codes(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp, body = await _create(client, name="eps", config={"llm": "openai:gpt-4o"})
    assert resp.status == 422 and body["code"] == "unsupported_config_key"
    resp, body = await _create(client, name="zeta", config={"created_by": "someone"})
    assert resp.status == 400 and body["code"] == "reserved_config_key"
    resp, body = await _create(client, name="foo", config={"foo": 1})
    assert resp.status == 201  # free-form config keys stay accepted
    assert (await client.get(f"{BASE}/agents/foo")).status == 200


async def test_patch_model_param_errors(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    await _create(client)
    url = f"{BASE}/agents/alpha"
    resp = await client.patch(url, json={"model_params": {"top_p": 2, "temperature": -1}})
    body = await resp.json()
    assert resp.status == 422 and body["code"] == "invalid_config"
    assert {d["field"]: (d["constraint"], d["limit"]) for d in body["details"]} == {
        "top_p": ("le", 1.0),
        "temperature": ("ge", 0.0),
    }
    resp = await client.patch(url, json={"model_params": {"top_k": "x"}})
    body = await resp.json()
    assert resp.status == 422 and _pick(body["details"]) == [_detail("top_k", "type", None)]
    # an unknown model-param key and an unknown top-level key are NOT model-param range errors
    resp = await client.patch(url, json={"model_params": {"nope": 1}})
    assert resp.status == 422 and (await resp.json())["code"] == "invalid_request"
    resp = await client.patch(url, json={"bot_class": "Agent"})
    assert resp.status == 422 and (await resp.json())["code"] == "invalid_request"


async def test_draft_save_model_param_errors(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    bundle = {"name": "d1", "definition": {"bot_class": "BasicBot", "model_params": {"top_p": 2}}}
    resp = await client.post(f"{BASE}/drafts", json={"name": "d1", "bundle": bundle})
    body = await resp.json()
    assert resp.status == 422 and body["code"] == "invalid_config"
    assert _pick(body["details"]) == [_detail("top_p", "le", 1.0)]
    bundle["definition"]["model_params"] = {"temperature": "hot", "top_k": 0}
    resp = await client.post(f"{BASE}/drafts", json={"name": "d1", "bundle": bundle})
    body = await resp.json()
    assert resp.status == 422 and body["code"] == "invalid_config"
    assert {d["field"]: d["constraint"] for d in body["details"]} == {"temperature": "type", "top_k": "gt"}
    # a missing body is still the generic invalid_request
    resp = await client.post(f"{BASE}/drafts", json={"name": "d1"})
    assert resp.status == 422 and (await resp.json())["code"] == "invalid_request"


async def test_model_params_catalog_exposes_the_bounds(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp = await client.get(f"{BASE}/catalog/model-params")
    schema = await resp.json()
    assert resp.status == 200 and set(schema["properties"]) == {"temperature", "max_tokens", "top_k", "top_p"}
    top_p = schema["properties"]["top_p"]["anyOf"][0]
    assert top_p["maximum"] == 1.0 and top_p["exclusiveMinimum"] == 0.0
