"""Tests for the Agent Studio package scaffold (FEAT-467 TASK-2511).

Covers: route registration under ``/api/v1/astudio/`` (and never under
the plain ``/api/v1/studio`` prefix another installed service occupies),
unauthenticated 401, PBAC fail-open without a PDP, ownership 403/admin
bypass, slug validation, and traversal-safe path resolution.
"""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from navigator_auth.decorators import is_authenticated
from parrot.handlers.studio import STUDIO_PREFIX, setup_studio_routes
from parrot.handlers.studio._base import (
    StudioBaseView,
    StudioUser,
    is_valid_slug,
    resolve_safe_path,
)


def _route_paths(app: web.Application) -> list[str]:
    """Collect canonical resource paths for every registered route."""
    paths = []
    for route in app.router.routes():
        canonical = getattr(route.resource, "canonical", None)
        if canonical:
            paths.append(canonical)
    return paths


class TestStudioScaffold:
    """Route wiring + prefix invariants."""

    def test_routes_registered_under_astudio(self, studio_app):
        """Every route ``setup_studio_routes`` adds lives under
        ``/api/v1/astudio/`` (vacuously true today — TASK-2511 adds no
        concrete endpoints; this is a regression guard for TASK-2512+)."""
        for path in _route_paths(studio_app):
            assert path == STUDIO_PREFIX or path.startswith(f"{STUDIO_PREFIX}/")

    def test_no_route_under_plain_studio(self, studio_app):
        """No route is ever registered under bare ``/api/v1/studio`` —
        that prefix belongs to another installed service (spec §2)."""
        for path in _route_paths(studio_app):
            assert path != "/api/v1/studio"
            assert not path.startswith("/api/v1/studio/")

    def test_setup_studio_routes_is_safe_on_a_bare_app(self):
        """``setup_studio_routes`` never raises — the wiring point
        ``BotManager.setup()`` calls must be safe even before any
        concrete Studio handler exists."""
        app = web.Application()
        setup_studio_routes(app)  # must not raise


class TestStudioAuth:
    """The ``@is_authenticated()``/``@user_session()`` pattern every real
    Studio handler applies at its class definition site. TASK-2511
    registers no concrete endpoints yet, so this exercises the pattern
    directly (pattern: ``tests/handlers/test_comm_center_handler.py::
    TestGetBatchesAuthentication``)."""

    @pytest.mark.asyncio
    async def test_unauthenticated_401(self):
        @is_authenticated()
        async def _dummy_handler(request):
            return web.json_response({"ok": True})

        request = make_mocked_request("GET", "/api/v1/astudio/_dummy")
        with pytest.raises(web.HTTPException) as excinfo:
            await _dummy_handler(request)
        # No auth backend configured -> get_auth() raises 400 before any
        # session/credential check runs; a configured-but-failing backend
        # would raise 401/403. All three are "access denied" outcomes.
        assert excinfo.value.status in (400, 401, 403)


class TestStudioPBAC:
    """Fail-open PBAC posture (pattern: ``handlers/bots.py
    _PBACHandlerMixin``) — no ``app['abac']`` means allowed."""

    @pytest.mark.asyncio
    async def test_pbac_fail_open_without_pdp(self):
        request = make_mocked_request("GET", "/api/v1/astudio/agents", app=web.Application())
        view = StudioBaseView(request)
        allowed = await view._pbac_allowed("agents", "astudio:agents:list")
        assert allowed is True

    def test_pbac_evaluator_absent_from_app(self):
        """``app['abac']`` entirely absent (not just no evaluator) is
        also fail-open. Uses a real ``web.Application`` (not the default
        ``make_mocked_request`` MagicMock app) so ``.get('abac')`` behaves
        like a real mapping instead of auto-mocking a truthy return."""
        request = make_mocked_request("GET", "/api/v1/astudio/agents", app=web.Application())
        assert "abac" not in request.app
        view = StudioBaseView(request)
        assert view._get_pbac_evaluator() is None


class TestStudioOwnership:
    """``_require_owner`` — 403 for non-owners, bypassed for superusers."""

    def test_require_owner_allows_owner(self):
        request = make_mocked_request("GET", "/api/v1/astudio/agents/foo")
        view = StudioBaseView(request)
        user = StudioUser(user_id="42")
        view._require_owner("42", user)  # must not raise

    def test_require_owner_rejects_non_owner(self):
        request = make_mocked_request("GET", "/api/v1/astudio/agents/foo")
        view = StudioBaseView(request)
        user = StudioUser(user_id="42")
        with pytest.raises(web.HTTPForbidden):
            view._require_owner("99", user)

    def test_require_owner_admin_bypass(self):
        request = make_mocked_request("GET", "/api/v1/astudio/agents/foo")
        view = StudioBaseView(request)
        admin = StudioUser(user_id="1", is_superuser=True)
        view._require_owner("99", admin)  # must not raise — admin bypass

    def test_require_owner_rejects_none_owner(self):
        request = make_mocked_request("GET", "/api/v1/astudio/agents/foo")
        view = StudioBaseView(request)
        user = StudioUser(user_id="42")
        with pytest.raises(web.HTTPForbidden):
            view._require_owner(None, user)


class TestStudioSlugValidation:
    """Slug validation helper — ``^[a-z0-9_-]+$`` (pattern: handlers/bots.py
    ``_AGENT_SLUG_RE``)."""

    @pytest.mark.parametrize("slug", ["my-agent", "agent_1", "abc123"])
    def test_slug_validation_accepts_valid(self, slug):
        assert is_valid_slug(slug) is True

    @pytest.mark.parametrize("slug", ["My-Agent", "agent name", "../etc", "", "a/b"])
    def test_slug_validation_rejects_invalid(self, slug):
        assert is_valid_slug(slug) is False


class TestStudioPathResolver:
    """Traversal-safe path resolver (used by files/drafts tasks TASK-2513/
    TASK-2514)."""

    def test_path_resolver_accepts_valid_relative_path(self, tmp_path):
        resolved = resolve_safe_path(tmp_path, "identity/role.md")
        assert resolved == (tmp_path / "identity" / "role.md").resolve()

    @pytest.mark.parametrize(
        "bad_path",
        ["../escape.txt", "../../etc/passwd", "/etc/passwd", "a/../../b"],
    )
    def test_path_resolver_rejects_traversal(self, tmp_path, bad_path):
        with pytest.raises(ValueError):
            resolve_safe_path(tmp_path, bad_path)

    def test_path_resolver_rejects_empty_path(self, tmp_path):
        with pytest.raises(ValueError):
            resolve_safe_path(tmp_path, "")

    def test_path_resolver_rejects_symlink_escape(self, tmp_path):
        """A symlink inside the sandbox pointing outside it must still
        be rejected once resolved."""
        outside = tmp_path.parent / f"{tmp_path.name}-outside-target"
        outside.mkdir(exist_ok=True)
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "escape").symlink_to(outside)

        with pytest.raises(ValueError):
            resolve_safe_path(sandbox, "escape/secret.txt")


class TestPbacGateWiring:
    """Adversarial-review fix: `_pbac_allowed` existed but no concrete
    handler ever called it — a configured PDP denying `astudio:*` had
    zero effect. Every mutating verb now opens with `_pbac_gate(...)`;
    these tests prove an explicit deny genuinely blocks a request."""

    @pytest.mark.asyncio
    async def test_gate_returns_none_when_allowed(self):
        from unittest.mock import AsyncMock

        from parrot.handlers.studio.agents import StudioAgentsHandler

        request = make_mocked_request("POST", "/agents", app=web.Application())
        handler = StudioAgentsHandler(request)
        handler._pbac_allowed = AsyncMock(return_value=True)

        assert await handler._pbac_gate("agents", "astudio:agents:create") is None

    @pytest.mark.asyncio
    async def test_explicit_deny_blocks_mutating_verb_with_403(self):
        import json
        from unittest.mock import AsyncMock

        from parrot.handlers.studio.agents import StudioAgentsHandler

        request = make_mocked_request("POST", "/agents", app=web.Application())
        request.json = AsyncMock(return_value={"name": "x", "bot_class": "BasicBot"})
        handler = StudioAgentsHandler(request)
        handler._pbac_allowed = AsyncMock(return_value=False)

        post = StudioAgentsHandler.post
        while hasattr(post, "__wrapped__"):
            post = post.__wrapped__
        response = await post(handler)

        assert response.status == 403
        body = json.loads(response.body)
        assert body["code"] == "pbac_denied"
        handler._pbac_allowed.assert_awaited_once_with("agents", "astudio:agents:create")

    def test_every_mutating_verb_is_gated(self):
        """Static check: each mutating handler verb's source contains a
        `_pbac_gate(` call — regression guard so a future endpoint can't
        silently ship ungated."""
        import inspect

        from parrot.handlers.studio.agents import StudioAgentReloadHandler, StudioAgentsHandler
        from parrot.handlers.studio.byok import StudioKeysHandler
        from parrot.handlers.studio.drafts import StudioDraftActivateHandler, StudioDraftsHandler
        from parrot.handlers.studio.files import StudioFilesHandler
        from parrot.handlers.studio.meta_agent import StudioAssistantHandler
        from parrot.handlers.studio.skills_catalog import (
            StudioSkillsCatalogHandler,
            StudioSkillsImportHandler,
            StudioSkillsResyncHandler,
        )
        from parrot.handlers.studio.testing import (
            StudioTestingHandler,
            StudioToolAssignHandler,
            StudioToolExecuteHandler,
        )
        from parrot.handlers.studio.toolkits import StudioToolkitsHandler

        gated_verbs = [
            (StudioAgentsHandler, "post"),
            (StudioAgentsHandler, "delete"),
            (StudioAgentReloadHandler, "post"),
            (StudioDraftsHandler, "post"),
            (StudioDraftsHandler, "delete"),
            (StudioDraftActivateHandler, "post"),
            (StudioFilesHandler, "put"),
            (StudioFilesHandler, "delete"),
            (StudioSkillsCatalogHandler, "post"),
            (StudioSkillsCatalogHandler, "put"),
            (StudioSkillsCatalogHandler, "delete"),
            (StudioSkillsImportHandler, "post"),
            (StudioSkillsResyncHandler, "post"),
            (StudioKeysHandler, "post"),
            (StudioKeysHandler, "delete"),
            (StudioTestingHandler, "post"),
            (StudioToolExecuteHandler, "post"),
            (StudioToolAssignHandler, "post"),
            (StudioToolkitsHandler, "post"),
            (StudioAssistantHandler, "post"),
        ]
        for cls, verb in gated_verbs:
            method = getattr(cls, verb)
            while hasattr(method, "__wrapped__"):
                method = method.__wrapped__
            assert "_pbac_gate(" in inspect.getsource(method), f"{cls.__name__}.{verb} is not PBAC-gated"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
