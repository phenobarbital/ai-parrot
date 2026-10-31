"""Real-Redis tests for ChannelLinkIssuer (FEAT-777 M2). Skips when Redis db 15 is unreachable."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
import redis.asyncio as aioredis

from parrot.auth.channel_link import ChannelLinkClaim, ChannelLinkIssuer


@pytest.fixture
async def redis_client():
    client = aioredis.from_url("redis://localhost:6379/15", decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        await client.aclose()
        pytest.skip(f"Redis unreachable: {exc}")
    yield client
    await client.aclose()


def _nonce(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


@pytest.mark.asyncio
async def test_channel_link_issue_consume_single_use(redis_client) -> None:
    """Consume once returns a claim; a second consume and an expired nonce return ``None``."""
    issuer = ChannelLinkIssuer(redis_client, base_url="https://admin.example", ttl_seconds=1)
    link = await issuer.issue(
        "slack",
        "T01:U02",
        {"team_id": "T01", "slack_user_id": "U02"},
    )

    claim = await issuer.consume(_nonce(link))
    assert isinstance(claim, ChannelLinkClaim)
    assert claim.channel == "slack"
    assert claim.channel_user_id == "T01:U02"
    assert claim.extra == {"team_id": "T01", "slack_user_id": "U02"}
    assert await issuer.consume(_nonce(link)) is None

    expired_link = await issuer.issue("slack", "T01:U03")
    await asyncio.sleep(1.2)
    assert await issuer.consume(_nonce(expired_link)) is None


@pytest.mark.asyncio
async def test_peek_does_not_consume_or_extend(redis_client, caplog) -> None:
    """Peek preserves the claim and TTL; malformed stored values are ignored and logged."""
    issuer = ChannelLinkIssuer(redis_client, base_url="https://admin.example", ttl_seconds=30)
    link = await issuer.issue("slack", "T01:U02")
    nonce = _nonce(link)
    key = f"channel_link:{nonce}"

    first_claim = await issuer.peek(nonce)
    first_ttl = await redis_client.ttl(key)
    await asyncio.sleep(0.01)
    second_claim = await issuer.peek(nonce)
    second_ttl = await redis_client.ttl(key)

    assert first_claim == second_claim
    assert second_ttl <= first_ttl
    assert await issuer.consume(nonce) == first_claim
    assert await issuer.peek(nonce) is None
    assert await issuer.peek("") is None
    assert await issuer.consume("") is None

    malformed_nonce = "malformed-channel-link-test"
    await redis_client.set(f"channel_link:{malformed_nonce}", "not-json", ex=30)
    assert await issuer.peek(malformed_nonce) is None
    assert "Ignoring malformed channel-link claim" in caplog.text
    assert malformed_nonce not in caplog.text
    await redis_client.set(f"channel_link:{malformed_nonce}", "{}", ex=30)
    assert await issuer.consume(malformed_nonce) is None

    bytes_claim = ChannelLinkClaim(channel="slack", channel_user_id="T01:U04", issued_at=1.0)
    assert issuer._parse(bytes_claim.model_dump_json().encode("utf-8")) == bytes_claim


@pytest.mark.asyncio
async def test_issue_validation(redis_client) -> None:
    """Invalid claims are rejected and normalized base URLs produce the specified link shape."""
    issuer = ChannelLinkIssuer(redis_client, base_url="https://admin.example/", ttl_seconds=30)

    with pytest.raises(ValueError):
        await issuer.issue("", "T01:U02")
    with pytest.raises(ValueError):
        await issuer.issue("slack", "")
    with pytest.raises(ValueError):
        await ChannelLinkIssuer(redis_client, base_url="").issue("slack", "T01:U02")
    with pytest.raises(ValueError):
        await issuer.issue("slack", "T01:U02", {"token": "x"})

    link = await issuer.issue("slack", "T01:U02")
    assert link == f"https://admin.example/account/link?token={_nonce(link)}"
    assert await issuer.consume(_nonce(link)) is not None
