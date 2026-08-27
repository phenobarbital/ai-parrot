"""Tests for the Studio draft pipeline (FEAT-467 TASK-2513).

``TestDraftValidation`` exercises ``validation.validate_draft`` as pure
functions (no handler/DB involved). ``TestDraftLifecycle`` exercises the
HTTP handlers against an in-memory fake draft-row store (avoids
simulating asyncdb's Model/SQL layer — pattern:
``tests/studio/test_agents_lifecycle.py``) plus a REAL, isolated
``AgentRegistry`` for the activate-imports-and-registers path.
"""

from __future__ import annotations

import json
import textwrap
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import parrot.registry as registry_pkg
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import drafts as drafts_module
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.drafts import (
    StudioDraftActivateHandler,
    StudioDraftsHandler,
)
from parrot.handlers.studio.validation import detect_base_class, validate_draft
from parrot.manager.manager import BotManager
from parrot.registry.registry import AgentRegistry


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# TestDraftValidation — pure static analysis, no handler/DB
# ---------------------------------------------------------------------------


VALID_DRAFT_SOURCE = textwrap.dedent("""
    from parrot.bots.basic import BasicBot


    class MyDraftAgent(BasicBot):
        \"\"\"A generated draft agent.\"\"\"
        pass
    """)


class TestDraftValidation:
    def test_syntax_error_reported_with_line(self):
        report = validate_draft("def broken(:\n    pass\n")
        assert report.passed is False
        assert any(e["code"] == "syntax-error" for e in report.errors)
        assert report.errors[0]["line"] >= 1

    def test_forbidden_import_flagged(self):
        source = "import requests\n\nfrom parrot.bots.basic import BasicBot\n\n\nclass X(BasicBot):\n    pass\n"
        report = validate_draft(source)
        assert report.passed is False
        codes = {e["code"] for e in report.errors}
        assert "forbidden-import" in codes

    def test_relative_import_flagged(self):
        source = "from . import something\n\nfrom parrot.bots.basic import BasicBot\n\n\nclass X(BasicBot):\n    pass\n"
        report = validate_draft(source)
        assert report.passed is False
        assert any(e["code"] == "forbidden-import" for e in report.errors)

    def test_exec_eval_flagged(self):
        source = (
            "from parrot.bots.basic import BasicBot\n\n\n"
            "class X(BasicBot):\n"
            "    def boom(self):\n"
            "        exec('print(1)')\n"
        )
        report = validate_draft(source)
        assert report.passed is False
        assert any(e["code"] == "forbidden-call" for e in report.errors)

    def test_no_bot_subclass_flagged(self):
        report = validate_draft("x = 1\n")
        assert report.passed is False
        assert any(e["code"] == "no-bot-subclass" for e in report.errors)

    def test_multiple_bot_subclasses_flagged(self):
        source = (
            "from parrot.bots.basic import BasicBot\n\n\n"
            "class A(BasicBot):\n    pass\n\n\n"
            "class B(BasicBot):\n    pass\n"
        )
        report = validate_draft(source)
        assert report.passed is False
        assert any(e["code"] == "multiple-bot-subclasses" for e in report.errors)

    def test_valid_draft_passes(self):
        report = validate_draft(VALID_DRAFT_SOURCE)
        assert report.passed is True
        assert report.errors == []

    def test_detect_base_class(self):
        assert detect_base_class(VALID_DRAFT_SOURCE) == "BasicBot"

    def test_detect_base_class_none_on_syntax_error(self):
        assert detect_base_class("def broken(:\n") is None


# ---------------------------------------------------------------------------
# Fixtures — TestDraftLifecycle
# ---------------------------------------------------------------------------


class _FakeDraftRow:
    """Stand-in for a StudioDraft asyncdb row (no real DB involved)."""

    def __init__(self, **fields):
        self.draft_id = fields.pop("draft_id", uuid.uuid4())
        for key, value in fields.items():
            setattr(self, key, value)

    def set(self, key, value):
        setattr(self, key, value)

    async def update(self):
        return None

    async def delete(self):
        return None


class _FakeDraftStore:
    """In-memory stand-in for the ``navigator.studio_drafts`` table."""

    def __init__(self):
        self.rows: dict = {}

    async def get_draft_row(self, name):
        return self.rows.get(name)

    async def get_all_draft_rows(self):
        return list(self.rows.values())

    async def upsert_draft_row(self, **fields):
        name = fields["name"]
        existing = self.rows.get(name)
        if existing is not None:
            for key, value in fields.items():
                setattr(existing, key, value)
            return existing
        row = _FakeDraftRow(**fields)
        self.rows[name] = row
        return row

    async def delete_draft_row(self, row):
        self.rows.pop(row.name, None)


@pytest.fixture
def store() -> _FakeDraftStore:
    return _FakeDraftStore()


@pytest.fixture
def registry(tmp_path) -> AgentRegistry:
    return AgentRegistry(agents_dir=tmp_path)


@pytest.fixture(autouse=True)
def patch_agents_dir(monkeypatch, tmp_path):
    """Redirect the module-level AGENTS_DIR the drafts handler relies on
    into tmp_path (same footgun documented in TASK-2512's fixtures)."""
    monkeypatch.setattr(drafts_module, "AGENTS_DIR", tmp_path)
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


def _make_handler(handler_cls, app, store, *, method="GET", path="/x", match_info=None, json_body=None, owner="1"):
    request = make_mocked_request(method, path, match_info=match_info or {}, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    handler = handler_cls(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id=owner))
    handler._get_draft_row = store.get_draft_row
    handler._get_all_draft_rows = store.get_all_draft_rows
    handler._upsert_draft_row = store.upsert_draft_row
    handler._delete_draft_row = store.delete_draft_row
    return handler


async def _save_draft(app, store, *, name, source, owner="1"):
    handler = _make_handler(
        StudioDraftsHandler,
        app,
        store,
        method="POST",
        path="/drafts",
        json_body={"name": name, "source": source},
        owner=owner,
    )
    response = await _unwrap(StudioDraftsHandler.post)(handler)
    assert response.status == 201, await _decode(response)
    return await _decode(response)


# ---------------------------------------------------------------------------
# TestDraftLifecycle
# ---------------------------------------------------------------------------


class TestDraftLifecycle:
    async def test_save_persists_file_and_row(self, app, store, tmp_path):
        body = await _save_draft(app, store, name="ok-draft", source=VALID_DRAFT_SOURCE)
        assert body["status"] == "validated"
        file_path = Path(body["file_path"])
        assert file_path.exists()
        assert file_path.read_text() == VALID_DRAFT_SOURCE
        assert file_path.parent == tmp_path / "_drafts"

        row = store.rows["ok-draft"]
        assert row.status == "validated"
        assert row.base_class == "BasicBot"
        assert row.owner_user_id == "1"

    async def test_save_failed_validation_still_persists_file(self, app, store):
        body = await _save_draft(app, store, name="bad-draft", source="x = 1\n")
        assert body["status"] == "failed"
        assert Path(body["file_path"]).exists()
        row = store.rows["bad-draft"]
        assert row.status == "failed"
        assert any(e["code"] == "no-bot-subclass" for e in row.validation_report["errors"])

    async def test_get_one_includes_source(self, app, store):
        await _save_draft(app, store, name="readable-draft", source=VALID_DRAFT_SOURCE)
        handler = _make_handler(
            StudioDraftsHandler,
            app,
            store,
            method="GET",
            path="/drafts/readable-draft",
            match_info={"name": "readable-draft"},
        )
        response = await _unwrap(StudioDraftsHandler.get)(handler)
        assert response.status == 200
        body = await _decode(response)
        assert body["source"] == VALID_DRAFT_SOURCE

    async def test_get_one_not_found_404(self, app, store):
        handler = _make_handler(
            StudioDraftsHandler,
            app,
            store,
            method="GET",
            path="/drafts/nope",
            match_info={"name": "nope"},
        )
        response = await _unwrap(StudioDraftsHandler.get)(handler)
        assert response.status == 404

    async def test_activate_gate_blocks_failed(self, app, store):
        await _save_draft(app, store, name="bad-activate", source="x = 1\n")
        handler = _make_handler(
            StudioDraftActivateHandler,
            app,
            store,
            method="POST",
            path="/drafts/bad-activate/activate",
            match_info={"name": "bad-activate"},
        )
        response = await _unwrap(StudioDraftActivateHandler.post)(handler)
        assert response.status == 409
        assert (await _decode(response))["code"] == "validation_failed"
        assert store.rows["bad-activate"].status == "failed"

    async def test_activate_imports_and_registers(self, app, store, registry, monkeypatch):
        # The draft self-registers via `agent_registry.register_bot_decorator`
        # resolved FRESH at exec time (`from parrot.registry import
        # agent_registry` inside the draft) — point the module-level
        # singleton at this test's isolated registry for the duration of
        # the activation so it lands there, not the real global registry.
        monkeypatch.setattr(registry_pkg, "agent_registry", registry)

        draft_source = textwrap.dedent("""
            from parrot.registry import agent_registry
            from parrot.bots.basic import BasicBot


            @agent_registry.register_bot_decorator(name="live-draft-agent", replace=True)
            class LiveDraftAgent(BasicBot):
                \"\"\"Activated draft agent.\"\"\"
                pass
            """)
        await _save_draft(app, store, name="live-draft-agent", source=draft_source, owner="7")

        handler = _make_handler(
            StudioDraftActivateHandler,
            app,
            store,
            method="POST",
            path="/drafts/live-draft-agent/activate",
            match_info={"name": "live-draft-agent"},
            owner="7",
        )
        response = await _unwrap(StudioDraftActivateHandler.post)(handler)
        assert response.status == 200, await _decode(response)
        body = await _decode(response)
        assert body["activated"] is True

        assert registry.has("live-draft-agent")
        target_path = Path(body["file_path"])
        assert target_path.exists()
        # Activation moves the file into AGENTS_DIR/ (patched to tmp_path,
        # matching this test's registry.agents_dir) so the startup loader
        # also finds it on next boot (spec §7).
        assert target_path.parent == registry.agents_dir

        row = store.rows["live-draft-agent"]
        assert row.status == "activated"
        assert row.activated_at is not None

    async def test_activate_not_found_404(self, app, store):
        handler = _make_handler(
            StudioDraftActivateHandler,
            app,
            store,
            method="POST",
            path="/drafts/nope/activate",
            match_info={"name": "nope"},
        )
        response = await _unwrap(StudioDraftActivateHandler.post)(handler)
        assert response.status == 404

    async def test_activate_non_owner_403(self, app, store):
        await _save_draft(app, store, name="owned-draft", source=VALID_DRAFT_SOURCE, owner="1")
        handler = _make_handler(
            StudioDraftActivateHandler,
            app,
            store,
            method="POST",
            path="/drafts/owned-draft/activate",
            match_info={"name": "owned-draft"},
            owner="99",
        )
        with pytest.raises(web.HTTPForbidden):
            await _unwrap(StudioDraftActivateHandler.post)(handler)

    async def test_drafts_dir_invisible_to_startup_loader(self, app, store, registry, tmp_path):
        await _save_draft(app, store, name="hidden-draft", source=VALID_DRAFT_SOURCE)
        assert (tmp_path / "_drafts" / "hidden-draft.py").exists()

        imported = await registry.load_modules()
        assert imported == 0
        assert not registry.has("hidden-draft")
        assert not registry.has("HiddenDraftAgent")

    async def test_delete_removes_file_and_row(self, app, store):
        body = await _save_draft(app, store, name="deletable-draft", source=VALID_DRAFT_SOURCE)
        file_path = Path(body["file_path"])
        assert file_path.exists()

        handler = _make_handler(
            StudioDraftsHandler,
            app,
            store,
            method="DELETE",
            path="/drafts/deletable-draft",
            match_info={"name": "deletable-draft"},
        )
        response = await _unwrap(StudioDraftsHandler.delete)(handler)
        assert response.status == 200
        assert not file_path.exists()
        assert "deletable-draft" not in store.rows

    async def test_delete_non_owner_403(self, app, store):
        await _save_draft(app, store, name="protected-draft", source=VALID_DRAFT_SOURCE, owner="1")
        handler = _make_handler(
            StudioDraftsHandler,
            app,
            store,
            method="DELETE",
            path="/drafts/protected-draft",
            match_info={"name": "protected-draft"},
            owner="99",
        )
        with pytest.raises(web.HTTPForbidden):
            await _unwrap(StudioDraftsHandler.delete)(handler)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
