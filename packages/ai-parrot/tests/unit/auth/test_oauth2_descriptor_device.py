"""Descriptor device field + StandardOAuth2Manager device grant (FEAT-774 M8)."""

from __future__ import annotations

import json
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2 import descriptor as descriptor_module
from parrot.auth.oauth2.descriptor import OAuth2ProviderDescriptor, StandardOAuth2Manager
from parrot.auth.oauth2.device_code import DeviceAuthorization, DeviceCodeError
from parrot.auth.principal import Principal

from ._oauth2_fakes import MemRedis


class DeviceRedis(MemRedis):
    """Memory Redis that records pending-grant expiration semantics."""

    def __init__(self) -> None:
        super().__init__()
        self.set_calls: list[tuple[str, str, Optional[int]]] = []
        self.remaining_ttl = 73

    async def set(self, key: str, value: str, *, ex: Optional[int] = None) -> bool:
        """Store a value and retain its requested expiration for assertions."""
        self.set_calls.append((key, value, ex))
        return await super().set(key, value, ex=ex)

    async def ttl(self, key: str) -> int:
        """Return the scripted remaining expiration for an existing value."""
        return self.remaining_ttl if key in self.rows else -2


def _descriptor(**overrides: Any) -> OAuth2ProviderDescriptor:
    """Build a minimal descriptor suitable for device-grant tests."""
    values = {
        "provider_id": "dummy",
        "display_name": "Dummy",
        "authorization_url": "https://idp.example/authorize",
        "token_url": "https://idp.example/token",
        "default_scopes": ["read"],
        "client_type": "public",
        "device_authorization_url": "https://idp.example/device",
    }
    values.update(overrides)
    return OAuth2ProviderDescriptor.model_validate(values)


def _manager(descriptor: OAuth2ProviderDescriptor, redis: DeviceRedis) -> StandardOAuth2Manager:
    """Build a manager with only in-memory dependencies."""
    return StandardOAuth2Manager(
        descriptor,
        client_id="client-id",
        client_secret=None,
        redirect_uri="https://client.example/callback",
        redis_client=redis,
    )


def test_descriptor_device_url_optional() -> None:
    """Device authorization is opt-in for descriptor-backed providers."""
    descriptor = _descriptor(device_authorization_url=None)

    assert descriptor.device_authorization_url is None


@pytest.mark.asyncio
async def test_start_device_without_url_raises() -> None:
    """Providers without a device endpoint reject server-side device grants."""
    manager = _manager(_descriptor(device_authorization_url=None), DeviceRedis())
    principal = Principal(user_id="user-1", channel="cli", channel_user_id="cli-1")

    with pytest.raises(ValueError, match="does not support the device authorization grant"):
        await manager.start_device_authorization(principal)


@pytest.mark.asyncio
async def test_server_device_start_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """One poll handles pending, slow-down, approval, failed, and expired device grants."""
    redis = DeviceRedis()
    manager = _manager(_descriptor(), redis)
    principal = Principal(user_id="user-1", channel="cli", channel_user_id="cli-1")
    authorization = DeviceAuthorization(
        device_code="provider-device-code",
        user_code="ABCD-EFGH",
        verification_uri="https://idp.example/verify",
        expires_in=90,
        interval=3,
    )
    token_outcomes: list[object] = [
        ("authorization_pending", {}),
        ("slow_down", {}),
        ("approved", {"access_token": "access-token", "expires_in": 3600, "scope": "read"}),
        DeviceCodeError("expired_token"),
        DeviceCodeError("invalid_client"),
    ]

    async def request_authorization(*args: Any, **kwargs: Any) -> DeviceAuthorization:
        """Return the scripted authorization without contacting a provider."""
        assert kwargs["scopes"] == ["read"]
        return authorization

    async def request_token(*args: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        """Return the next scripted RFC 8628 polling outcome."""
        assert kwargs["device_code"] == "provider-device-code"
        outcome = token_outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[return-value]

    monkeypatch.setattr(descriptor_module, "request_device_authorization", request_authorization)
    monkeypatch.setattr(descriptor_module, "request_device_token", request_token)
    manager._get_session = AsyncMock(return_value=object())
    manager._discover_identity = AsyncMock(return_value={"account_id": "account-1"})
    manager._persist_token = AsyncMock()
    manager._publish = AsyncMock()

    handle, returned_authorization = await manager.start_device_authorization(principal)
    key = manager._device_key(handle)
    assert returned_authorization == authorization
    assert redis.set_calls[-1][0] == key
    assert redis.set_calls[-1][2] == authorization.expires_in
    assert json.loads(redis.rows[key])["device_code"] == "provider-device-code"

    assert await manager.complete_device_authorization(handle) == {"status": "pending", "interval": 3}
    assert await manager.complete_device_authorization(handle) == {"status": "pending", "interval": 8}
    assert redis.set_calls[-1][2] == redis.remaining_ttl

    completed = await manager.complete_device_authorization(handle)
    assert completed["status"] == "completed"
    assert completed["account_id"] == "account-1"
    assert key not in redis.rows
    manager._persist_token.assert_awaited_once_with(
        principal,
        completed["token_set"],
        minted=True,
        state_payload={"channel": "cli"},
    )
    manager._publish.assert_awaited_once()

    expired_handle, _ = await manager.start_device_authorization(principal)
    assert await manager.complete_device_authorization(expired_handle) == {"status": "expired", "reason": "expired_token"}
    assert manager._device_key(expired_handle) not in redis.rows

    failed_handle, _ = await manager.start_device_authorization(principal)
    assert await manager.complete_device_authorization(failed_handle) == {"status": "failed", "reason": "invalid_client"}
    assert manager._device_key(failed_handle) not in redis.rows
