"""MS Teams deep-link resume tests (TASK-1736).

Exercise the per-channel resume helper for Teams. The wrapper delegates to this helper
from the ``on_message_activity`` / ``activity.value`` seam (see the task Completion Note);
the wrapper is not importable in the worktree (botbuilder + Cython), so the resume logic
is validated here.
"""

import json

import pytest

from parrot.integrations.a2ui_resume import ChannelDeepLinkResume
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
    return DeepLinkService(FakeRedis(), base_url="https://teams.example")


class TestDeepLinkResumeTeams:
    async def test_token_activity_consumed_and_injected(self):
        service = _service()
        resume = ChannelDeepLinkResume(service, channel="msteams")
        dl = await service.mint(
            session_id="teams-sess", user_id="teams-user", agent_id="assistant",
            channel="msteams", action_payload={"action": "confirm"},
        )
        # The Teams wrapper extracts the token from activity.value and delegates.
        injected = {}

        async def inject(*, session_id, user_id, agent_id, query):
            injected.update(session_id=session_id, query=query)
            return {"ok": True}

        outcome = await resume.resume(dl.token_id, inject=inject)
        assert outcome["ok"] is True
        assert injected["session_id"] == "teams-sess"
        assert json.loads(injected["query"])["action"]["action"] == "confirm"

    async def test_invalid_token_friendly_reply(self):
        resume = ChannelDeepLinkResume(_service(), channel="msteams")

        async def _must_not_run(**kwargs):
            raise AssertionError("inject must not run for an invalid token")

        outcome = await resume.resume("bogus-token", inject=_must_not_run)
        assert outcome["ok"] is False
        assert "expired" in outcome["reply"].lower()
        # No session/action payload echoed in the friendly reply.
        assert "confirm" not in outcome["reply"]
