"""Telegram deep-link resume tests (TASK-1736, spec §4; FEAT-470 TASK-2546 v1.0).

Exercise the per-channel resume helper (`ChannelDeepLinkResume`) with a real
`DeepLinkService` over a fake Redis. The Telegram wrapper delegates to this helper via a
thin `/start <token>` detection hook (see the task Completion Note for the exact seam);
the wrapper itself is not importable in the worktree (aiogram + Cython), so the resume
logic — the substantive deliverable — is validated here.
"""

import json

import pytest

from parrot.integrations.a2ui_resume import ChannelDeepLinkResume, build_structured_message
from parrot.outputs.a2ui.deeplink import DeepLinkService

pytestmark = pytest.mark.asyncio


def _action_envelope(name: str = "approve", **context) -> dict:
    """Build a valid v1.0 ``A2UIRendererMessage`` 'action' envelope."""
    return {
        "version": "v1.0",
        "action": {
            "name": name,
            "surfaceId": "main",
            "sourceComponentId": "btn1",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "context": context,
        },
    }


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


def _service():
    return DeepLinkService(FakeRedis(), base_url="https://t.me/mybot")


class TestDeepLinkResumeTelegram:
    async def test_e2e_deeplink_resume_telegram(self):
        service = _service()
        resume = ChannelDeepLinkResume(service, channel="telegram")

        # Mint a deep link for a degraded action on a baked surface.
        dl = await service.mint(
            session_id="tg-sess-1",
            user_id="tg-user-1",
            agent_id="assistant",
            channel="telegram",
            action_payload=_action_envelope("approve", row=4),
        )

        # The telegram wrapper's inject closure overrides the session and resumes.
        injected = {}

        async def inject(*, session_id, user_id, agent_id, query):
            injected.update(session_id=session_id, user_id=user_id, agent_id=agent_id, query=query)
            return {"resumed": True}

        outcome = await resume.resume(dl.token_id, inject=inject)

        assert outcome["ok"] is True
        assert outcome["session_id"] == "tg-sess-1"
        assert injected["session_id"] == "tg-sess-1"  # original session restored
        assert injected["user_id"] == "tg-user-1"
        decoded = json.loads(injected["query"])
        assert decoded["type"] == "a2ui_action"
        assert decoded["action"]["action"]["name"] == "approve"

    async def test_expired_token_friendly_message(self):
        service = _service()
        resume = ChannelDeepLinkResume(service, channel="telegram")
        dl = await service.mint(
            session_id="s",
            user_id="u",
            agent_id="a",
            channel="telegram",
            action_payload=_action_envelope("x"),
        )
        # Consume once (success), then replay → friendly message, session untouched.
        await resume.resume(dl.token_id, inject=_noop_inject)
        outcome = await resume.resume(dl.token_id, inject=_must_not_run)
        assert outcome["ok"] is False
        assert "expired" in outcome["reply"].lower()

    async def test_empty_token_friendly_message(self):
        resume = ChannelDeepLinkResume(_service(), channel="telegram")
        outcome = await resume.resume("", inject=_must_not_run)
        assert outcome["ok"] is False

    async def test_resume_message_format(self):
        # FEAT-470 TASK-2546 spec §4: build_structured_message emits
        # {"type": "a2ui_action", "action": <v1.0 sobre>} — same tag/shape the
        # Teams Adaptive Cards a2ui_action submit branch (TASK-2545) expects.
        envelope = _action_envelope("go")
        msg = build_structured_message(envelope)
        assert json.loads(msg) == {"type": "a2ui_action", "action": envelope}


async def _noop_inject(**kwargs):
    return {"ok": True}


async def _must_not_run(**kwargs):
    raise AssertionError("inject must not run for an invalid/expired token")
