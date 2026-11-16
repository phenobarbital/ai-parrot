"""Studio BYOK handler and key source on the default Redis backend (FEAT-878 TASK-5502).

Uses the real local Redis (db 15, unique prefix); skipped when unreachable.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import parrot.auth.broker as broker_module
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import byok as byok_module
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.byok import StudioKeysHandler, active_byok_store, resolve_user_api_key
from parrot.handlers.studio.key_source import user_byok_providers
from parrot.userstore.testing import redis_test_settings

MASTER_KEY_ID = 1
MASTER_KEY = b"1" * 32


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def _handler(app, *, method="GET", path="/keys", match_info=None, json_body=None, user_id="u-redis"):
    request = make_mocked_request(method, path, match_info=match_info or {}, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    handler = StudioKeysHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id=user_id))
    handler._resolve_session = AsyncMock(return_value={})
    handler._pbac_gate = AsyncMock(return_value=None)
    return handler


@pytest.fixture
async def redis_byok(monkeypatch):
    try:
        from navigator_session.vault import KeyRing
    except ImportError:
        pytest.skip("navigator_session.vault not installed")
    import parrot.security.vault_utils as vault_utils_module

    keyring = KeyRing({MASTER_KEY_ID: MASTER_KEY}, MASTER_KEY_ID)
    monkeypatch.setattr(vault_utils_module, "get_vault_keyring", lambda: keyring)
    monkeypatch.setattr(byok_module, "get_vault_keyring", lambda: keyring)
    monkeypatch.delenv("BYOK_STORE", raising=False)
    monkeypatch.setattr(broker_module, "_REDIS_STORE", None)
    async with redis_test_settings(monkeypatch):
        yield web.Application()
    monkeypatch.setattr(broker_module, "_REDIS_STORE", None)


async def test_active_store_is_redis_by_default(redis_byok):
    assert active_byok_store(redis_byok) is broker_module.get_user_llm_key_store()
    assert active_byok_store(redis_byok) is not None


async def test_studio_keys_redis(redis_byok):
    secret = "sk-ant-abcdef1234"
    post = _handler(redis_byok, method="POST", json_body={"provider": "anthropic", "api_key": secret})
    response = await _unwrap(StudioKeysHandler.post)(post)
    assert response.status == 201
    assert json.loads(response.body)["masked"] == "sk-…1234"

    listed = await _unwrap(StudioKeysHandler.get)(_handler(redis_byok))
    body = json.loads(listed.body)
    assert body["count"] == 1
    assert body["keys"][0]["provider"] == "anthropic"
    assert body["keys"][0]["masked"] == "sk-…1234"
    assert secret not in json.dumps(body)

    assert await resolve_user_api_key(redis_byok, "u-redis", "anthropic") == secret

    delete = _handler(redis_byok, method="DELETE", match_info={"provider": "anthropic"})
    deleted = await _unwrap(StudioKeysHandler.delete)(delete)
    assert deleted.status in (200, 204)

    after = await _unwrap(StudioKeysHandler.get)(_handler(redis_byok))
    assert json.loads(after.body)["count"] == 0


async def test_user_byok_providers_redis(redis_byok):
    assert await user_byok_providers(redis_byok, "u-redis") == frozenset()
    post = _handler(redis_byok, method="POST", json_body={"provider": "openai", "api_key": "sk-openai-secret-9999"})
    assert (await _unwrap(StudioKeysHandler.post)(post)).status == 201
    assert await user_byok_providers(redis_byok, "u-redis") == frozenset({"openai"})
