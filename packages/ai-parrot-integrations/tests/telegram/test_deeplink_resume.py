"""Telegram deep-link resume tests (TASK-1736, spec §4).

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
            action_payload={"action": "approve", "row": 4},
        )

        # The telegram wrapper's inject closure overrides the session and resumes.
        injected = {}

        async def inject(*, session_id, user_id, agent_id, query):
            injected.update(
                session_id=session_id, user_id=user_id, agent_id=agent_id, query=query
            )
            return {"resumed": True}

        outcome = await resume.resume(dl.token_id, inject=inject)

        assert outcome["ok"] is True
        assert outcome["session_id"] == "tg-sess-1"
        assert injected["session_id"] == "tg-sess-1"  # original session restored
        assert injected["user_id"] == "tg-user-1"
        decoded = json.loads(injected["query"])
        assert decoded["type"] == "a2ui_action_resume"
        assert decoded["action"]["action"] == "approve"

    async def test_expired_token_friendly_message(self):
        service = _service()
        resume = ChannelDeepLinkResume(service, channel="telegram")
        dl = await service.mint(
            session_id="s", user_id="u", agent_id="a", channel="telegram",
            action_payload={"action": "x"},
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

    async def test_build_structured_message_shape(self):
        msg = build_structured_message({"action": "go"})
        assert json.loads(msg) == {"type": "a2ui_action_resume", "action": {"action": "go"}}


async def _noop_inject(**kwargs):
    return {"ok": True}


async def _must_not_run(**kwargs):
    raise AssertionError("inject must not run for an invalid/expired token")
