"""MS Teams deep-link resume tests (TASK-1736; FEAT-470 TASK-2546 v1.0).

Exercise the per-channel resume helper for Teams. The wrapper delegates to this helper
from the ``on_message_activity`` / ``activity.value`` seam (see the task Completion Note);
the wrapper is not importable in the worktree (botbuilder + Cython), so the resume logic
is validated here. This covers the ``a2ui_token`` deep-link resume path only — the
``a2ui_action`` native-input Adaptive Cards submit path is TASK-2545's
``test_a2ui_submit.py``.
"""

import json

import pytest

from parrot.integrations.a2ui_resume import ChannelDeepLinkResume
from parrot.outputs.a2ui.deeplink import DeepLinkService

pytestmark = pytest.mark.asyncio


def _action_envelope(name: str = "confirm", **context) -> dict:
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
    return DeepLinkService(FakeRedis(), base_url="https://teams.example")


class TestDeepLinkResumeTeams:
    async def test_token_activity_consumed_and_injected(self):
        service = _service()
        resume = ChannelDeepLinkResume(service, channel="msteams")
        dl = await service.mint(
            session_id="teams-sess", user_id="teams-user", agent_id="assistant",
            channel="msteams", action_payload=_action_envelope("confirm"),
        )
        # The Teams wrapper extracts the token from activity.value and delegates.
        injected = {}

        async def inject(*, session_id, user_id, agent_id, query):
            injected.update(session_id=session_id, query=query)
            return {"ok": True}

        outcome = await resume.resume(dl.token_id, inject=inject)
        assert outcome["ok"] is True
        assert injected["session_id"] == "teams-sess"
        decoded = json.loads(injected["query"])
        assert decoded["type"] == "a2ui_action"
        assert decoded["action"]["action"]["name"] == "confirm"

    async def test_invalid_token_friendly_reply(self):
        resume = ChannelDeepLinkResume(_service(), channel="msteams")

        async def _must_not_run(**kwargs):
            raise AssertionError("inject must not run for an invalid token")

        outcome = await resume.resume("bogus-token", inject=_must_not_run)
        assert outcome["ok"] is False
        assert "expired" in outcome["reply"].lower()
        # No session/action payload echoed in the friendly reply.
        assert "confirm" not in outcome["reply"]
