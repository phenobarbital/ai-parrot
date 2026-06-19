"""Mode A end-to-end integration test (TASK-1610 — FEAT-249).

Tests the LITE avatar + text/voice flow against the real LiveAvatar API:
  1. Start a LITE session  (POST /api/v1/agents/avatar/{agent_id}/start)
  2. Run a chat turn       (POST /api/v1/agents/chat/{agent_id}, stream)
  3. Stop the session      (POST /api/v1/agents/avatar/{agent_id}/stop)

Required environment variables (all must be set for the tests to run):
    LIVEAVATAR_API_KEY      API key for the LiveAvatar service
    LIVEAVATAR_AVATAR_ID    Avatar ID (use 5761a14c — production-only avatar)
    LIVEAVATAR_BASE_URL     Base URL (default: https://api.heygen.com)
    LIVEAVATAR_SANDBOX      Must be "false" for the production avatar (5761a14c
                            returns 400 under sandbox mode)
    LIVEKIT_URL             LiveKit server WebSocket URL
    LIVEKIT_API_KEY         LiveKit API key (for room token minting)
    LIVEKIT_API_SECRET      LiveKit API secret

If any of the above is missing the entire module is skipped with pytest.skip().

Note on the "mouth" path:
  AvatarTurnSpeaker is created per-turn by _maybe_start_avatar_speaker().
  It feeds PCM audio (resampled 44100 → 24000 Hz by AvatarVoiceProvider) to
  the LiveAvatar data channel.  The integration test confirms the avatar session
  is active and the speaker is wired but does NOT make assertions about raw PCM
  bytes — that is unit-tested in test_speaker.py and test_voice_provider.py.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, Optional

import pytest

# ---------------------------------------------------------------------------
# Environment gate — skip the entire module when credentials are absent
# ---------------------------------------------------------------------------

_REQUIRED_ENV = (
    "LIVEAVATAR_API_KEY",
    "LIVEAVATAR_AVATAR_ID",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)

_missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
if _missing:
    pytest.skip(
        f"Mode A e2e tests require: {', '.join(_missing)}. Skipping.",
        allow_module_level=True,
    )

# Confirm production avatar is not accidentally run in sandbox mode
if os.environ.get("LIVEAVATAR_SANDBOX", "true").lower() != "false":
    pytest.skip(
        "LIVEAVATAR_SANDBOX must be 'false' for the production avatar (5761a14c). "
        "Set LIVEAVATAR_SANDBOX=false to run Mode A e2e tests.",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _start_session(
    client,
    agent_id: str,
    session_id: str,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /api/v1/agents/avatar/{agent_id}/start and return the response dict."""
    body: Dict[str, Any] = {"session_id": session_id}
    if tenant_id:
        body["tenant_id"] = tenant_id

    async with client.post(
        f"/api/v1/agents/avatar/{agent_id}/start",
        json=body,
    ) as resp:
        assert resp.status == 200, f"start returned {resp.status}: {await resp.text()}"
        return await resp.json()


async def _stop_session(client, agent_id: str, session_id: str) -> None:
    """POST /api/v1/agents/avatar/{agent_id}/stop."""
    async with client.post(
        f"/api/v1/agents/avatar/{agent_id}/stop",
        json={"session_id": session_id},
    ) as resp:
        # 204 (success) or 200 are both acceptable; idempotent on 404
        assert resp.status in (200, 204), f"stop returned {resp.status}"


# ---------------------------------------------------------------------------
# Integration test — start → chat → stop
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mode_a_start_chat_stop():
    """Mode A e2e: start LITE session, run chat turn (mouth path active), stop.

    This test requires live LiveAvatar + LiveKit credentials. CI skips it when
    any of the required env vars is absent (see module-level guard above).
    """
    import aiohttp

    agent_id = os.environ.get("TEST_AGENT_ID", "default-agent")
    session_id = f"e2e-{uuid.uuid4().hex[:8]}"
    base_url = os.environ.get("SERVER_BASE_URL", "http://localhost:8080")

    async with aiohttp.ClientSession(base_url=base_url) as client:
        # ── Step 1: start the LITE avatar session ────────────────────────────
        creds = await _start_session(client, agent_id, session_id)

        assert "livekit_url" in creds, "livekit_url missing from start response"
        assert "client_token" in creds, "client_token missing from start response"
        assert creds["session_id"] == session_id
        # Security: agent_token must never be in the response
        assert "agent_token" not in creds

        # ── Step 2: drive a chat turn ─────────────────────────────────────────
        # We POST to the streaming endpoint and consume the response body.
        # The avatar "mouth" path is exercised server-side when AvatarTurnSpeaker
        # is wired (app['avatar_voice_provider'] is set and the session is live).
        try:
            async with client.post(
                f"/api/v1/agents/chat/{agent_id}",
                json={
                    "query": "Hello, just testing. Please say a single word.",
                    "session_id": session_id,
                    "avatar": True,
                    "output_format": "text",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as chat_resp:
                assert chat_resp.status == 200, (
                    f"chat returned {chat_resp.status}: {await chat_resp.text()}"
                )
                # Consume the streamed body so the server completes the turn
                _ = await chat_resp.read()
        finally:
            # ── Step 3: stop the session ──────────────────────────────────────
            await _stop_session(client, agent_id, session_id)
