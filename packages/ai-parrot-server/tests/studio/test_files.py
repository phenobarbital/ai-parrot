"""Tests for Studio per-agent asset file management (FEAT-467 TASK-2514).

Covers identity's canonical-name restriction, skill frontmatter
validation (422), KB extension rules, traversal rejection, the
``reload_required`` flag on every mutation, and that deleting a file the
live agent uses is never blocked.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.bots.prompts.identity import IDENTITY_FILES, load_identity
from parrot.handlers.studio import files as files_module
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.files import StudioFilesHandler
from parrot.manager.manager import BotManager
from parrot.registry.registry import AgentRegistry, BotConfig


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path) -> AgentRegistry:
    return AgentRegistry(agents_dir=tmp_path)


@pytest.fixture(autouse=True)
def patch_agents_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(files_module, "AGENTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def manager(registry) -> BotManager:
    bm = BotManager.__new__(BotManager)
    bm.app = None
    bm._bots = {}
    bm._botdef = {}
    bm._bot_expiration = {}
    bm._cleaned_up = set()
    bm.logger = MagicMock()
    bm.registry = registry
    return bm


@pytest.fixture
def app(manager) -> web.Application:
    application = web.Application()
    application["bot_manager"] = manager
    return application


def _register_agent(registry, name="my-agent", owner="1"):
    from parrot.bots.basic import BasicBot

    registry.register(
        name,
        BasicBot,
        bot_config=BotConfig(
            name=name,
            class_name="BasicBot",
            module="parrot.bots.basic",
            origin="factory",
            config={"created_by": owner},
        ),
    )


def _make_handler(app, *, method="GET", path="/x", match_info=None, json_body=None, owner="1"):
    request = make_mocked_request(method, path, match_info=match_info or {}, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    handler = StudioFilesHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id=owner))
    return handler


def _mi(name="my-agent", kind="identity", filename=None):
    m = {"name": name, "kind": kind}
    if filename is not None:
        m["filename"] = filename
    return m


VALID_SKILL_CONTENT = (
    "---\n"
    "name: my-skill\n"
    "description: A useful skill.\n"
    "triggers:\n"
    "  - /myskill\n"
    "---\n\n"
    "Skill body instructions.\n"
)


class TestStudioFiles:
    # -- identity ------------------------------------------------------

    async def test_identity_canonical_names_only(self, app, registry):
        _register_agent(registry)
        handler = _make_handler(
            app,
            method="PUT",
            path="/x",
            match_info=_mi(filename="identity.md"),
            json_body={"content": "not a canonical name"},
        )
        response = await _unwrap(StudioFilesHandler.put)(handler)
        assert response.status == 400
        assert (await _decode(response))["code"] == "invalid_filename"

    async def test_identity_write_and_load_identity_roundtrip(self, app, registry, tmp_path):
        _register_agent(registry)
        handler = _make_handler(
            app,
            method="PUT",
            path="/x",
            match_info=_mi(filename="role.md"),
            json_body={"content": "You are a helpful assistant."},
        )
        response = await _unwrap(StudioFilesHandler.put)(handler)
        assert response.status == 200
        body = await _decode(response)
        assert body["reload_required"] is True

        identity_dir = tmp_path / "my-agent" / "identity"
        assert (identity_dir / "role.md").read_text() == "You are a helpful assistant."

        fields = load_identity(identity_dir)
        assert fields.role == "You are a helpful assistant."
        assert fields.goal is None  # never written

    async def test_identity_all_five_canonical_names_accepted(self, app, registry):
        _register_agent(registry)
        for name in IDENTITY_FILES:
            handler = _make_handler(
                app,
                method="PUT",
                path="/x",
                match_info=_mi(filename=f"{name}.md"),
                json_body={"content": f"{name} content"},
            )
            response = await _unwrap(StudioFilesHandler.put)(handler)
            assert response.status == 200, (name, await _decode(response))

    # -- kb --------------------------------------------------------------

    async def test_kb_extension_rules(self, app, registry):
        _register_agent(registry)
        for filename, expect_ok in [
            ("notes.md", True),
            ("notes.txt", True),
            ("notes.pdf", False),
            ("subdir/notes.md", False),
        ]:
            handler = _make_handler(
                app,
                method="PUT",
                path="/x",
                match_info=_mi(kind="kb", filename=filename),
                json_body={"content": "kb content"},
            )
            response = await _unwrap(StudioFilesHandler.put)(handler)
            if expect_ok:
                assert response.status == 200, (filename, await _decode(response))
            else:
                assert response.status in (400,), (filename, await _decode(response))

    # -- skills ------------------------------------------------------------

    async def test_skill_frontmatter_validation_422(self, app, registry):
        _register_agent(registry)
        handler = _make_handler(
            app,
            method="PUT",
            path="/x",
            match_info=_mi(kind="skills", filename="bad-skill.md"),
            json_body={"content": "no frontmatter here\n"},
        )
        response = await _unwrap(StudioFilesHandler.put)(handler)
        assert response.status == 422
        assert (await _decode(response))["code"] == "invalid_frontmatter"

    async def test_skill_valid_frontmatter_accepted(self, app, registry, tmp_path):
        _register_agent(registry)
        handler = _make_handler(
            app,
            method="PUT",
            path="/x",
            match_info=_mi(kind="skills", filename="my-skill.md"),
            json_body={"content": VALID_SKILL_CONTENT},
        )
        response = await _unwrap(StudioFilesHandler.put)(handler)
        assert response.status == 200
        assert (tmp_path / "my-agent" / "skills" / "my-skill.md").read_text() == VALID_SKILL_CONTENT

    async def test_composite_skill_layout(self, app, registry, tmp_path):
        _register_agent(registry)
        # SKILL.md entry point — validated.
        handler = _make_handler(
            app,
            method="PUT",
            path="/x",
            match_info=_mi(kind="skills", filename="composite-skill/SKILL.md"),
            json_body={"content": VALID_SKILL_CONTENT},
        )
        response = await _unwrap(StudioFilesHandler.put)(handler)
        assert response.status == 200, await _decode(response)

        # Adjacent asset file — NOT validated (arbitrary content OK).
        handler = _make_handler(
            app,
            method="PUT",
            path="/x",
            match_info=_mi(kind="skills", filename="composite-skill/template.txt"),
            json_body={"content": "not frontmatter at all"},
        )
        response = await _unwrap(StudioFilesHandler.put)(handler)
        assert response.status == 200, await _decode(response)

        skill_dir = tmp_path / "my-agent" / "skills" / "composite-skill"
        assert (skill_dir / "SKILL.md").exists()
        assert (skill_dir / "template.txt").read_text() == "not frontmatter at all"

    async def test_skill_bad_composite_asset_bad_frontmatter_but_not_validated(self, app, registry):
        """A composite SKILL.md with bad frontmatter IS validated (422);
        confirms the composite entry-point path is not silently skipped."""
        _register_agent(registry)
        handler = _make_handler(
            app,
            method="PUT",
            path="/x",
            match_info=_mi(kind="skills", filename="broken-skill/SKILL.md"),
            json_body={"content": "no frontmatter\n"},
        )
        response = await _unwrap(StudioFilesHandler.put)(handler)
        assert response.status == 422

    # -- traversal / kind / agent validation --------------------------------

    @pytest.mark.parametrize("filename", ["../escape.md", "/etc/passwd", "../../etc/passwd"])
    async def test_traversal_rejected(self, app, registry, filename):
        _register_agent(registry)
        handler = _make_handler(
            app,
            method="GET",
            path="/x",
            match_info=_mi(filename=filename),
        )
        response = await _unwrap(StudioFilesHandler.get)(handler)
        assert response.status == 400
        assert (await _decode(response))["code"] == "invalid_path"

    async def test_unknown_agent_404(self, app, registry):
        handler = _make_handler(
            app,
            method="GET",
            path="/x",
            match_info=_mi(name="no-such-agent", filename="role.md"),
        )
        response = await _unwrap(StudioFilesHandler.get)(handler)
        assert response.status == 404

    async def test_unknown_kind_400(self, app, registry):
        _register_agent(registry)
        handler = _make_handler(
            app,
            method="GET",
            path="/x",
            match_info=_mi(kind="bogus"),
        )
        response = await _unwrap(StudioFilesHandler.get)(handler)
        assert response.status == 400
        assert (await _decode(response))["code"] == "invalid_kind"

    # -- reload_required + delete-always-allowed ----------------------------

    async def test_reload_required_flag_on_mutations(self, app, registry):
        _register_agent(registry)
        put_handler = _make_handler(
            app,
            method="PUT",
            path="/x",
            match_info=_mi(filename="goal.md"),
            json_body={"content": "Help the user."},
        )
        put_response = await _unwrap(StudioFilesHandler.put)(put_handler)
        assert (await _decode(put_response))["reload_required"] is True

        delete_handler = _make_handler(
            app,
            method="DELETE",
            path="/x",
            match_info=_mi(filename="goal.md"),
        )
        delete_response = await _unwrap(StudioFilesHandler.delete)(delete_handler)
        assert (await _decode(delete_response))["reload_required"] is True

    async def test_delete_allowed_even_for_in_use_file(self, app, registry, tmp_path):
        """Deleting a file the live agent uses is allowed, never blocked
        (resolved decision — no "in use" check exists at all)."""
        _register_agent(registry)
        identity_dir = tmp_path / "my-agent" / "identity"
        identity_dir.mkdir(parents=True)
        (identity_dir / "role.md").write_text("Currently live.")

        handler = _make_handler(
            app,
            method="DELETE",
            path="/x",
            match_info=_mi(filename="role.md"),
        )
        response = await _unwrap(StudioFilesHandler.delete)(handler)
        assert response.status == 200
        assert not (identity_dir / "role.md").exists()

    # -- ownership -----------------------------------------------------------

    async def test_put_non_owner_403(self, app, registry):
        _register_agent(registry, owner="1")
        handler = _make_handler(
            app,
            method="PUT",
            path="/x",
            match_info=_mi(filename="role.md"),
            json_body={"content": "hijacked"},
            owner="99",
        )
        with pytest.raises(web.HTTPForbidden):
            await _unwrap(StudioFilesHandler.put)(handler)

    async def test_get_does_not_require_ownership(self, app, registry, tmp_path):
        _register_agent(registry, owner="1")
        identity_dir = tmp_path / "my-agent" / "identity"
        identity_dir.mkdir(parents=True)
        (identity_dir / "role.md").write_text("Readable by anyone authenticated.")

        handler = _make_handler(
            app,
            method="GET",
            path="/x",
            match_info=_mi(filename="role.md"),
            owner="99",
        )
        response = await _unwrap(StudioFilesHandler.get)(handler)
        assert response.status == 200

    # -- listing -----------------------------------------------------------

    async def test_list_files_empty_when_dir_missing(self, app, registry):
        _register_agent(registry)
        handler = _make_handler(app, method="GET", path="/x", match_info=_mi())
        response = await _unwrap(StudioFilesHandler.get)(handler)
        assert response.status == 200
        assert (await _decode(response))["files"] == []

    async def test_list_files_after_writes(self, app, registry):
        _register_agent(registry)
        for name in ("role", "goal"):
            handler = _make_handler(
                app,
                method="PUT",
                path="/x",
                match_info=_mi(filename=f"{name}.md"),
                json_body={"content": f"{name}"},
            )
            await _unwrap(StudioFilesHandler.put)(handler)

        handler = _make_handler(app, method="GET", path="/x", match_info=_mi())
        response = await _unwrap(StudioFilesHandler.get)(handler)
        body = await _decode(response)
        assert set(body["files"]) == {"role.md", "goal.md"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
