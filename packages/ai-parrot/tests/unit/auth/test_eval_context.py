"""Unit tests for the canonical PBAC EvalContext builder (FEAT-446).

Covers ``parrot.auth.eval_context.build_eval_context``, the single
consolidated implementation replacing the three former per-module copies
in ``agent_guard.py`` / ``handlers/bots.py`` / ``handlers/agent.py``.
"""
from __future__ import annotations

from aiohttp.test_utils import make_mocked_request
from navigator_auth.conf import AUTH_SESSION_OBJECT
from parrot.auth.eval_context import build_eval_context


class _FakeSession(dict):
    """Minimal session stand-in: dict-like ``.get()``; ``.decode()`` for
    the navigator_session-style ``session.decode('user')`` access pattern.
    """

    def decode(self, key):
        return self.get(f"__decoded_{key}__")


def _make_request(session=None):
    req = make_mocked_request("GET", "/api/v1/crew")
    if session is not None:
        req.session = session
    return req


_USERINFO = {
    "username": "acme-user",
    "groups": ["engineering"],
    "roles": ["agent:operator"],
    "programs": ["acme"],
}


class TestBuildEvalContext:
    async def test_builds_from_request_session(self):
        session = _FakeSession({AUTH_SESSION_OBJECT: _USERINFO})
        request = _make_request(session=session)

        ctx = await build_eval_context(request)

        assert ctx is not None
        assert ctx.userinfo == _USERINFO
        assert ctx.session is session
        assert ctx.request is request

    async def test_falls_back_to_navigator_session(self, monkeypatch):
        session = _FakeSession({AUTH_SESSION_OBJECT: _USERINFO})
        request = _make_request(session=None)

        async def _fake_get_session(req):
            return session

        monkeypatch.setattr(
            "navigator_session.get_session", _fake_get_session
        )

        ctx = await build_eval_context(request)

        assert ctx is not None
        assert ctx.userinfo == _USERINFO

    async def test_returns_none_without_session(self, monkeypatch):
        request = _make_request(session=None)

        async def _fake_get_session(req):
            return None

        monkeypatch.setattr(
            "navigator_session.get_session", _fake_get_session
        )

        ctx = await build_eval_context(request)

        assert ctx is None

    async def test_returns_none_when_navigator_session_raises(self, monkeypatch):
        request = _make_request(session=None)

        async def _raising_get_session(req):
            raise RuntimeError("session backend unavailable")

        monkeypatch.setattr(
            "navigator_session.get_session", _raising_get_session
        )

        ctx = await build_eval_context(request)

        assert ctx is None

    async def test_matches_legacy_field_population(self):
        """Equivalence check against the pre-FEAT-446 `handlers/agent.py`
        implementation (the only one of the three legacy copies that
        actually matched navigator-auth's real ``EvalContext.__init__``
        signature — see Completion Note for TASK-2321).
        """
        from navigator_auth.abac.context import EvalContext

        session = _FakeSession({AUTH_SESSION_OBJECT: _USERINFO})
        request = _make_request(session=session)

        # Legacy `handlers/agent.py::_build_eval_context` body, inlined.
        userinfo = session.get(AUTH_SESSION_OBJECT, {}) if hasattr(session, "get") else {}
        user = session.decode("user") if hasattr(session, "decode") else None
        if user is None and isinstance(userinfo, dict) and userinfo:
            user = userinfo
        legacy_ctx = EvalContext(
            request=request, user=user, userinfo=userinfo, session=session
        )

        consolidated_ctx = await build_eval_context(request)

        assert consolidated_ctx is not None
        assert consolidated_ctx.userinfo == legacy_ctx.userinfo
        assert consolidated_ctx.user == legacy_ctx.user
        assert consolidated_ctx.session is legacy_ctx.session
        assert consolidated_ctx.org_id == legacy_ctx.org_id
        assert consolidated_ctx.client_id == legacy_ctx.client_id
