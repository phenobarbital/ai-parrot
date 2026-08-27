"""Tests for the shared skills catalog (FEAT-467 TASK-2515).

Covers PG-first dual-write (publish succeeds even when the registry is
down, flagging ``search_index_stale``), category/owner-ordered listing
and filtering, invalid-category 400, per-agent import + collision
handling, and admin-only resync (both the on-demand endpoint and the
startup reconciliation routine).

DB access is faked via an in-memory store monkeypatched onto the
mixin's `_get_entry_by_id`/`_get_entry_by_name`/`_list_entries`/
`_insert_entry`/`_update_entry`/`_delete_entry` methods (pattern:
``tests/studio/test_drafts.py``'s ``_FakeDraftStore``) — this avoids
simulating asyncdb's Model/SQL layer while still exercising every real
`SkillCatalogEntry` object end to end. The shared `SkillRegistry` is
faked via `_get_shared_skill_registry` (a module-level function,
designed to be monkeypatchable) so tests never load a real embedding
model.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.models.skills_catalog import SkillCatalogEntry
from parrot.handlers.studio import skills_catalog as skills_catalog_module
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.skills_catalog import (
    StudioSkillsCatalogHandler,
    StudioSkillsImportHandler,
    StudioSkillsResyncHandler,
    reconcile_skills_catalog,
)


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCatalogStore:
    """In-memory stand-in for ``navigator.ai_skills_catalog`` — holds
    REAL ``SkillCatalogEntry`` model instances, only faking persistence."""

    def __init__(self):
        self.entries: dict = {}

    async def get_by_id(self, skill_id):
        return self.entries.get(str(skill_id))

    async def get_by_name(self, name):
        for entry in self.entries.values():
            if entry.name == name:
                return entry
        return None

    async def list_entries(self, **filters):
        result = list(self.entries.values())
        for key, value in filters.items():
            result = [e for e in result if getattr(e, key) == value]
        return result

    async def insert_entry(self, entry):
        self.entries[str(entry.skill_id)] = entry

    async def update_entry(self, entry):
        self.entries[str(entry.skill_id)] = entry

    async def delete_entry(self, entry):
        self.entries.pop(str(entry.skill_id), None)


class _FakeSkillRegistry:
    """Stand-in for a shared-namespace ``SkillRegistry``."""

    def __init__(self, *, fail_upload: bool = False):
        self.fail_upload = fail_upload
        self.uploads = []
        self.revocations = []

    async def upload_skill(self, **kwargs):
        if self.fail_upload:
            raise RuntimeError("registry unavailable (simulated outage)")
        self.uploads.append(kwargs)

    async def revoke_skill(self, skill_id, reason=""):
        self.revocations.append((skill_id, reason))

    async def get_skill_versions(self, skill_id):
        return [{"version_number": 0}]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> _FakeCatalogStore:
    return _FakeCatalogStore()


@pytest.fixture
def fake_registry() -> _FakeSkillRegistry:
    return _FakeSkillRegistry()


@pytest.fixture(autouse=True)
def patch_registry_lookup(monkeypatch, fake_registry):
    """Route every `_get_shared_skill_registry(app, org_id)` call to the
    per-test fake — avoids loading a real embedding model."""
    def _fake_get_registry(_app, _org_id):
        return fake_registry

    monkeypatch.setattr(
        skills_catalog_module, "_get_shared_skill_registry", _fake_get_registry
    )
    return fake_registry


@pytest.fixture(autouse=True)
def patch_agents_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(skills_catalog_module, "AGENTS_DIR", tmp_path)
    return tmp_path


class _FakeAsyncConnCtx:
    """A minimal async context manager standing in for an acquired
    connection — its ``conn`` value is never actually used since every
    test bypasses real DB access via the monkeypatched store methods
    (except the standalone ``reconcile_skills_catalog`` startup hook,
    which is a plain function and genuinely calls ``db.acquire()``)."""

    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *_args):
        return False


class _FakeDB:
    """Non-None ``app['database']`` sentinel that also supports a real
    ``await db.acquire()`` (needed by ``reconcile_skills_catalog``)."""

    async def acquire(self):
        return _FakeAsyncConnCtx()


@pytest.fixture
def app() -> web.Application:
    application = web.Application()
    application["database"] = _FakeDB()
    return application


def _make_handler(handler_cls, app, store, *, method="GET", path="/x",
                   match_info=None, json_body=None, owner="1", superuser=False):
    request = make_mocked_request(method, path, match_info=match_info or {}, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    handler = handler_cls(request)
    handler._get_user = AsyncMock(
        return_value=StudioUser(user_id=owner, is_superuser=superuser)
    )
    handler._get_entry_by_id = store.get_by_id
    handler._get_entry_by_name = store.get_by_name
    handler._list_entries = store.list_entries
    handler._insert_entry = store.insert_entry
    handler._update_entry = store.update_entry
    handler._delete_entry = store.delete_entry
    return handler


async def _publish(app, store, *, name, category="general", owner="1", triggers=None):
    handler = _make_handler(
        StudioSkillsCatalogHandler, app, store, method="POST", path="/skills",
        json_body={
            "name": name, "description": f"{name} description",
            "category": category, "triggers": triggers or [f"/{name}"],
            "body": f"# {name}\n\nSkill body.",
        },
        owner=owner,
    )
    response = await _unwrap(StudioSkillsCatalogHandler.post)(handler)
    return response


# ---------------------------------------------------------------------------
# Publish / dual-write
# ---------------------------------------------------------------------------


class TestSkillsPublish:
    async def test_publish_dual_write(self, app, store, fake_registry):
        response = await _publish(app, store, name="my-skill", owner="7")
        assert response.status == 201
        body = await _decode(response)
        assert body["name"] == "my-skill"
        assert body["owner"] == "7"
        assert body["search_index_stale"] is False
        assert len(fake_registry.uploads) == 1
        assert fake_registry.uploads[0]["skill_id"] == body["skill_id"]
        assert fake_registry.uploads[0]["owner_user_id"] == "7"

    async def test_publish_registry_down_sets_stale(self, app, store, monkeypatch):
        broken_registry = _FakeSkillRegistry(fail_upload=True)
        monkeypatch.setattr(
            skills_catalog_module,
            "_get_shared_skill_registry",
            lambda _app, _org: broken_registry,
        )
        response = await _publish(app, store, name="stale-skill")

        assert response.status == 201  # publish still succeeds
        body = await _decode(response)
        assert body["search_index_stale"] is True

    async def test_publish_duplicate_name_409(self, app, store):
        await _publish(app, store, name="dup-skill")
        response = await _publish(app, store, name="dup-skill")
        assert response.status == 409
        assert (await _decode(response))["code"] == "duplicate"

    async def test_publish_invalid_category_rejected_by_model(self, app, store):
        handler = _make_handler(
            StudioSkillsCatalogHandler, app, store, method="POST", path="/skills",
            json_body={
                "name": "bad-cat-skill", "description": "desc",
                "category": "not-a-real-category", "triggers": [],
                "body": "content",
            },
        )
        response = await _unwrap(StudioSkillsCatalogHandler.post)(handler)
        assert response.status == 400


# ---------------------------------------------------------------------------
# Listing / filtering
# ---------------------------------------------------------------------------


class TestSkillsListing:
    async def test_list_grouped_by_category_ordered(self, app, store):
        await _publish(app, store, name="b-tool", category="tool_usage")
        await _publish(app, store, name="a-tool", category="tool_usage")
        await _publish(app, store, name="a-workflow", category="workflow")

        handler = _make_handler(StudioSkillsCatalogHandler, app, store, method="GET", path="/skills")
        response = await _unwrap(StudioSkillsCatalogHandler.get)(handler)
        assert response.status == 200
        body = await _decode(response)

        assert set(body["skills"].keys()) == {"tool_usage", "workflow"}
        tool_names = [s["name"] for s in body["skills"]["tool_usage"]]
        assert tool_names == ["a-tool", "b-tool"]  # name-ordered within category
        assert body["count"] == 3

    async def test_owner_and_category_filters(self, app, store):
        await _publish(app, store, name="mine", owner="1", category="tool_usage")
        await _publish(app, store, name="theirs", owner="2", category="workflow")

        handler = _make_handler(
            StudioSkillsCatalogHandler, app, store, method="GET",
            path="/skills?owner=1",
        )
        response = await _unwrap(StudioSkillsCatalogHandler.get)(handler)
        body = await _decode(response)
        all_names = [s["name"] for cat in body["skills"].values() for s in cat]
        assert all_names == ["mine"]

    async def test_invalid_category_400(self, app, store):
        handler = _make_handler(
            StudioSkillsCatalogHandler, app, store, method="GET",
            path="/skills?category=not-real",
        )
        response = await _unwrap(StudioSkillsCatalogHandler.get)(handler)
        assert response.status == 400
        body = await _decode(response)
        assert body["code"] == "invalid_category"
        assert "general" in body["message"]

    async def test_get_one_includes_versions(self, app, store, fake_registry):
        publish_response = await _publish(app, store, name="versioned-skill")
        skill_id = (await _decode(publish_response))["skill_id"]

        handler = _make_handler(
            StudioSkillsCatalogHandler, app, store, method="GET",
            path="/skills/x", match_info={"id": skill_id},
        )
        response = await _unwrap(StudioSkillsCatalogHandler.get)(handler)
        body = await _decode(response)
        assert body["versions"] == [{"version_number": 0}]


# ---------------------------------------------------------------------------
# PUT / DELETE — owner-or-admin
# ---------------------------------------------------------------------------


class TestSkillsUpdateDelete:
    async def test_put_non_owner_403(self, app, store):
        publish_response = await _publish(app, store, name="owned-skill", owner="1")
        skill_id = (await _decode(publish_response))["skill_id"]

        handler = _make_handler(
            StudioSkillsCatalogHandler, app, store, method="PUT",
            path="/skills/x", match_info={"id": skill_id},
            json_body={"name": "owned-skill", "description": "hijack", "category": "general", "triggers": [], "body": "x"},
            owner="99",
        )
        with pytest.raises(web.HTTPForbidden):
            await _unwrap(StudioSkillsCatalogHandler.put)(handler)

    async def test_put_owner_succeeds_and_bumps_version(self, app, store):
        publish_response = await _publish(app, store, name="editable-skill", owner="1")
        skill_id = (await _decode(publish_response))["skill_id"]

        handler = _make_handler(
            StudioSkillsCatalogHandler, app, store, method="PUT",
            path="/skills/x", match_info={"id": skill_id},
            json_body={
                "name": "editable-skill", "description": "updated desc",
                "category": "workflow", "triggers": ["/new"], "body": "new body",
            },
            owner="1",
        )
        response = await _unwrap(StudioSkillsCatalogHandler.put)(handler)
        assert response.status == 200
        body = await _decode(response)
        assert body["version"] == 2
        assert body["category"] == "workflow"

    async def test_delete_owner_succeeds(self, app, store, fake_registry):
        publish_response = await _publish(app, store, name="deletable-skill", owner="1")
        skill_id = (await _decode(publish_response))["skill_id"]

        handler = _make_handler(
            StudioSkillsCatalogHandler, app, store, method="DELETE",
            path="/skills/x", match_info={"id": skill_id}, owner="1",
        )
        response = await _unwrap(StudioSkillsCatalogHandler.delete)(handler)
        assert response.status == 200
        assert skill_id not in store.entries
        assert fake_registry.revocations == [(skill_id, "deleted via Studio catalog")]

    async def test_delete_admin_bypass(self, app, store):
        publish_response = await _publish(app, store, name="admin-deletable", owner="1")
        skill_id = (await _decode(publish_response))["skill_id"]

        handler = _make_handler(
            StudioSkillsCatalogHandler, app, store, method="DELETE",
            path="/skills/x", match_info={"id": skill_id}, owner="99", superuser=True,
        )
        response = await _unwrap(StudioSkillsCatalogHandler.delete)(handler)
        assert response.status == 200


# ---------------------------------------------------------------------------
# Import into agent
# ---------------------------------------------------------------------------


class TestSkillsImport:
    async def test_import_into_agent_and_collision(self, app, store, tmp_path):
        publish_response = await _publish(app, store, name="importable-skill")
        skill_id = (await _decode(publish_response))["skill_id"]

        handler = _make_handler(
            StudioSkillsImportHandler, app, store, method="POST",
            path="/x", match_info={"name": "my-agent", "id": skill_id},
        )
        response = await _unwrap(StudioSkillsImportHandler.post)(handler)
        assert response.status == 201, await _decode(response)
        body = await _decode(response)
        assert body["reload_required"] is True

        target = Path(body["file_path"])
        assert target.exists()
        assert target == tmp_path / "my-agent" / "skills" / "importable-skill.md"
        assert "name: importable-skill" in target.read_text()

        # Second import without overwrite -> 409 collision.
        handler2 = _make_handler(
            StudioSkillsImportHandler, app, store, method="POST",
            path="/x", match_info={"name": "my-agent", "id": skill_id},
        )
        response2 = await _unwrap(StudioSkillsImportHandler.post)(handler2)
        assert response2.status == 409
        assert (await _decode(response2))["code"] == "collision"

        # With overwrite=true -> succeeds.
        handler3 = _make_handler(
            StudioSkillsImportHandler, app, store, method="POST",
            path="/x", match_info={"name": "my-agent", "id": skill_id},
            json_body={"overwrite": True},
        )
        response3 = await _unwrap(StudioSkillsImportHandler.post)(handler3)
        assert response3.status == 201

    async def test_import_unknown_skill_404(self, app, store):
        handler = _make_handler(
            StudioSkillsImportHandler, app, store, method="POST",
            path="/x", match_info={"name": "my-agent", "id": "no-such-id"},
        )
        response = await _unwrap(StudioSkillsImportHandler.post)(handler)
        assert response.status == 404


# ---------------------------------------------------------------------------
# Resync — admin-only, clears stale
# ---------------------------------------------------------------------------


class TestSkillsResync:
    async def test_resync_non_admin_403(self, app, store):
        handler = _make_handler(
            StudioSkillsResyncHandler, app, store, method="POST", path="/x",
            superuser=False,
        )
        response = await _unwrap(StudioSkillsResyncHandler.post)(handler)
        assert response.status == 403

    async def test_resync_admin_only_and_clears_stale(
        self, app, store, fake_registry, monkeypatch
    ):
        # Publish while the registry is failing to produce a stale entry.
        broken_registry = _FakeSkillRegistry(fail_upload=True)
        monkeypatch.setattr(
            skills_catalog_module,
            "_get_shared_skill_registry",
            lambda _app, _org: broken_registry,
        )
        publish_response = await _publish(app, store, name="needs-resync")
        # Restore the healthy fake_registry for the resync call below —
        # monkeypatch reverts automatically at test teardown, but we need
        # the healthy registry active NOW, mid-test.
        monkeypatch.setattr(
            skills_catalog_module,
            "_get_shared_skill_registry",
            lambda _app, _org: fake_registry,
        )
        skill_id = (await _decode(publish_response))["skill_id"]
        assert store.entries[skill_id].search_index_stale is True

        # Resync as admin, with a HEALTHY registry this time.
        handler = _make_handler(
            StudioSkillsResyncHandler, app, store, method="POST", path="/x",
            superuser=True,
        )
        response = await _unwrap(StudioSkillsResyncHandler.post)(handler)
        assert response.status == 200
        body = await _decode(response)
        assert body["resynced"] == 1
        assert body["failed"] == 0
        assert store.entries[skill_id].search_index_stale is False
        assert len(fake_registry.uploads) == 1


class TestReconcileSkillsCatalogStartupHook:
    async def test_reconcile_repairs_stale_entries(self, app, store, fake_registry, monkeypatch):
        entry = SkillCatalogEntry(
            name="startup-stale-skill", description="desc", category="general",
            owner="1", triggers=[], body="content", version=1,
            search_index_stale=True,
        )
        store.entries[str(entry.skill_id)] = entry

        # reconcile_skills_catalog uses the module-level DB-touching
        # helpers directly (it's a plain function, not a handler
        # method) — patch AsyncDB Model.filter/instance.update via the
        # store's list/update instead by monkeypatching the module
        # functions it calls through app['database'].acquire(); simplest
        # here is to monkeypatch SkillCatalogEntry.filter directly.
        async def _fake_filter(**kwargs):
            return await store.list_entries(**kwargs)

        async def _fake_update(self):
            await store.update_entry(self)

        monkeypatch.setattr(SkillCatalogEntry, "filter", staticmethod(_fake_filter))
        monkeypatch.setattr(SkillCatalogEntry, "update", _fake_update)

        await reconcile_skills_catalog(app)

        assert store.entries[str(entry.skill_id)].search_index_stale is False
        assert len(fake_registry.uploads) == 1

    async def test_reconcile_noop_without_database(self):
        app = web.Application()  # no 'database' key
        await reconcile_skills_catalog(app)  # must not raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
