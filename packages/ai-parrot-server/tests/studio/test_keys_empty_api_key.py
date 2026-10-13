"""POST /astudio/keys refuses an empty api_key with the 422 ``invalid_config`` per-field envelope (integration fix P3)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio.byok import StudioKeysHandler
from parrot.handlers.studio._base import StudioUser


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def _handler(body: dict) -> StudioKeysHandler:
    request = make_mocked_request("POST", "/keys", app=web.Application())
    request.json = AsyncMock(return_value=body)
    handler = StudioKeysHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="1"))
    handler._resolve_session = AsyncMock(return_value={})
    handler._pbac_gate = AsyncMock(return_value=None)
    return handler


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", ["", "   "])
async def test_empty_api_key_is_422_with_field_details(empty):
    response = await _unwrap(StudioKeysHandler.post)(_handler({"provider": "anthropic", "api_key": empty}))
    assert response.status == 422
    body = json.loads(response.body)
    assert body["code"] == "invalid_config"
    assert body["details"] == [
        {"field": "api_key", "constraint": "min_length", "limit": 1, "message": "api_key must not be empty."}
    ]
