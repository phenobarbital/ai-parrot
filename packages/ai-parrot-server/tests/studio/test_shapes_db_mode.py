"""FEAT-621 W4 — §2.9 response shapes in both modes (AC16).

The same scenarios run against a filesystem-mode app (``PARROT_STUDIO_STORAGE=filesystem``) and a
database-mode app (real Postgres pool); every key of the filesystem response must survive in database mode and
the keys database mode adds must be exactly the §2.9 "added" set for that route. Real aiohttp app, real Studio
routes and a real ``SessionData``; ``AbstractBot.configure`` is replaced so no LLM is started.

Run the pre-existing filesystem-mode suite with::

    PARROT_STUDIO_STORAGE=filesystem pytest packages/ai-parrot-server/tests/studio -q
"""
from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web

from parrot.handlers.studio import drafts as drafts_module
from parrot.handlers.studio import files as files_module
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio import skills_catalog as skills_module
from parrot.handlers.studio import tooling_store as store_module
from parrot.handlers.studio import toolkits as toolkits_module
from parrot.manager.manager import BotManager
from parrot.registry import agent_registry

from .test_agents_db_mode import BASE, _app, _offline, _session, pool  # noqa: F401  (fixtures)
from .test_tooling_db_mode import JIRA, vault  # noqa: F401  (fixtures)

PY_SOURCE = (
    "from parrot.bots.basic import BasicBot\n"
    "from parrot.registry import register_agent\n\n\n"
    "@register_agent(name='shapedraft', replace=True)\n"
    "class ShapeDraft(BasicBot):\n    pass\n"
)
# A Studio agent is a NEW item kind (§2.9): it is not a registry class, so the registry-introspection keys of a
# registry item have no value for it. Only these keys, only on the two GET routes, may be absent.
REGISTRY_ONLY_KEYS = {"at_startup", "class_name", "file_path", "module", "priority", "tags"}
REGISTRY_KIND_ROUTES = {"GET /agents item", "GET /agents/{name}"}

# route label -> keys database mode adds on top of the filesystem-mode response (spec §2.9)
ADDED: dict[str, set[str]] = {
    "POST /agents": {"agent_id", "version", "tenant"},
    "GET /agents item": {"agent_id", "tenant", "version", "updated_at", "visibility", "allowed_groups"},
    "GET /agents/{name}": {"agent_id", "tenant", "version", "updated_at", "visibility", "allowed_groups"},
    "DELETE /agents/{name}": set(),
    "PUT files": {"version", "sha256"},
    "GET files": {"version", "sha256"},
    "GET files list": set(),
    "POST /drafts (source)": set(),
    "GET /drafts/{name}": {"kind", "tenant", "visibility", "allowed_groups", "version"},
    "POST /drafts/{name}/activate": set(),
    "GET toolkit-config": set(),
    "PUT toolkits/{slug}": set(),
}


def _fs_app(pool) -> web.Application:
    """A filesystem-mode app: the pool is present (legacy draft state lives there) but the setting pins ``filesystem``."""
    app = web.Application(middlewares=[_session])
    app["database"] = pool
    manager = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                         enable_swagger_api=False)
    manager.setup_registry_only(app)
    setup_studio_routes(app)
    return app


async def _call(client, method: str, path: str, **kw) -> tuple[int, Any]:
    resp = await getattr(client, method)(f"{BASE}{path}", **kw)
    try:
        body = await resp.json()
    except Exception:  # noqa: BLE001 — a non-JSON body is itself a shape finding
        body = None
    return resp.status, body


async def _exercise(client) -> dict[str, tuple[int, Any]]:
    """Run every scenario once; returns ``label -> (status, json body)``."""
    out: dict[str, tuple[int, Any]] = {}
    out["POST /agents"] = await _call(client, "post", "/agents", json={"name": "alpha", "bot_class": "BasicBot",
                                                                     "persist": True})
    out["GET /agents"] = await _call(client, "get", "/agents")
    out["GET /agents/{name}"] = await _call(client, "get", "/agents/alpha")
    base = "/agents/alpha/files/kb"
    out["PUT files"] = await _call(client, "put", f"{base}/notes.md", json={"content": "hello"})
    out["GET files"] = await _call(client, "get", f"{base}/notes.md")
    out["GET files list"] = await _call(client, "get", base)
    out["POST /drafts (source)"] = await _call(client, "post", "/drafts", json={"name": "shapedraft",
                                                                              "source": PY_SOURCE})
    out["GET /drafts/{name}"] = await _call(client, "get", "/drafts/shapedraft")
    out["POST /drafts/{name}/activate"] = await _call(client, "post", "/drafts/shapedraft/activate", json={})
    out["GET toolkit-config"] = await _call(client, "get", "/agents/alpha/toolkit-config")
    out["PUT toolkits/{slug}"] = await _call(client, "put", "/agents/alpha/toolkits/jira", json=JIRA)
    out["DELETE /agents/{name}"] = await _call(client, "delete", "/agents/alpha")
    return out


def _keys(body: Any) -> set[str]:
    return set(body) if isinstance(body, dict) else set()


def _item_keys(label: str, body: Any) -> set[str]:
    """The keys of one response; for the list route, the keys of its first item."""
    if label == "GET /agents":
        return _keys((body or {}).get("agents", [{}])[0])
    return _keys(body)


def _forget_agents() -> None:
    """The agent registry is process-global: drop what the scenarios registered."""
    for name in ("alpha", "shapedraft"):
        agent_registry.unregister(name)


@pytest.fixture
async def snapshots(aiohttp_client, pool, monkeypatch, tmp_path, vault):  # noqa: F811 — imported fixtures
    """Both modes' responses, taken in the same test (filesystem first, then database)."""
    for module in (drafts_module, files_module, skills_module, store_module, toolkits_module):
        monkeypatch.setattr(module, "AGENTS_DIR", tmp_path / "agents")
    _forget_agents()
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "filesystem")
    fs_client = await aiohttp_client(_fs_app(pool))
    assert fs_client.app["studio_storage"].backend == "filesystem"
    fs = await _exercise(fs_client)
    _forget_agents()
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "database")
    db_client = await aiohttp_client(_app(pool))
    assert db_client.app["studio_storage"].backend == "database"
    db = await _exercise(db_client)
    yield fs, db
    _forget_agents()


def _labels(fs: dict) -> list[str]:
    return ["GET /agents item" if k == "GET /agents" else k for k in fs]


async def test_handlers_filesystem_mode_unchanged(snapshots):
    """Filesystem mode answers every scenario successfully and none of the database-only keys appear."""
    fs, _ = snapshots
    for label, (status, body) in fs.items():
        assert status in (200, 201), (label, status, body)
    assert fs["POST /agents"][1]["source"] == "registry"
    assert fs["POST /agents"][1]["file_path"] is not None
    for label in ("POST /agents", "PUT files", "GET files"):
        leaked = _keys(fs[label][1]) & ADDED[label]
        assert not leaked, (label, leaked)
    assert fs["PUT files"][1]["reload_required"] is True
    assert fs["POST /drafts (source)"][1]["file_path"] is not None


async def test_handlers_shapes_database_mode(snapshots):
    """Database mode is additive: nothing removed vs filesystem mode, exactly the §2.9 keys added."""
    fs, db = snapshots
    for label, (status, body) in db.items():
        assert status in (200, 201), (label, status, body)
        assert status == fs[label][0], (label, status, fs[label][0])
    for label in fs:
        key = "GET /agents item" if label == "GET /agents" else label
        fs_keys, db_keys = _item_keys(label, fs[label][1]), _item_keys(label, db[label][1])
        allowed_gap = REGISTRY_ONLY_KEYS if key in REGISTRY_KIND_ROUTES else set()
        assert fs_keys - allowed_gap <= db_keys, (label, "removed in database mode", fs_keys - db_keys)
        assert ADDED[key] <= db_keys, (label, "§2.9 key missing in database mode", ADDED[key] - db_keys)
        assert db_keys - fs_keys <= ADDED[key], (label, "key not listed in §2.9", db_keys - fs_keys - ADDED[key])
    assert db["POST /agents"][1]["source"] == "studio" and db["POST /agents"][1]["persisted"] is True
    assert db["POST /agents"][1]["file_path"] is None
    assert db["PUT files"][1]["reload_required"] is False


async def test_handlers_shapes_database_mode_bundle_drafts(aiohttp_client, pool, snapshots):  # noqa: F811
    """A declarative bundle draft keeps every key of the legacy draft response and adds ``kind``/``version``."""
    fs, _ = snapshots
    client = await aiohttp_client(_app(pool))
    bundle = {"name": "bundled", "definition": {"bot_class": "BasicBot", "description": "d"}}
    status, saved = await _call(client, "post", "/drafts", json={"name": "bundled", "bundle": bundle})
    assert status == 201
    assert _keys(fs["POST /drafts (source)"][1]) <= _keys(saved)
    assert _keys(saved) - _keys(fs["POST /drafts (source)"][1]) == {"kind", "version"}
    assert saved["file_path"] is None and saved["kind"] == "declarative"
    status, done = await _call(client, "post", "/drafts/bundled/activate", json={})
    assert status == 200
    assert _keys(fs["POST /drafts/{name}/activate"][1]) <= _keys(done)
    assert _keys(done) - _keys(fs["POST /drafts/{name}/activate"][1]) == {"agent_id", "version"}
    assert done["file_path"] is None and done["activated"] is True
