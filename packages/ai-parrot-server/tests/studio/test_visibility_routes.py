"""FEAT-605 M11 — visibility routes (mounted ONLY by ``setup_studio_routes``) and request models."""
from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from pydantic import ValidationError

from parrot.handlers.studio import STUDIO_PREFIX, setup_studio_routes
from parrot.handlers.studio.drafts._models import SaveDraftRequest
from parrot.handlers.studio.models import CreateAgentRequest, SkillPublishRequest, VisibilityUpdateRequest

from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import create, tenant_app, who
from .test_drafts_tenant import _drafts_dir, save  # noqa: F401  (fixtures)
from .test_skills_catalog_db_mode import PAYLOAD
from .test_skills_visibility import _registry, publish  # noqa: F401  (fixtures)

TENANT_PREFIX = "/api/v1/{tenant}/astudio"


def _paths(app: web.Application, method: str | None = None) -> list[str]:
    return [
        r.resource.canonical for r in app.router.routes()
        if r.resource is not None and (method is None or r.method == method)
    ]


def test_visibility_routes_mounted_by_setup():
    app = web.Application()
    setup_studio_routes(app)
    patches = _paths(app)
    for tail in ("/agents/{name}/visibility", "/drafts/{name}/visibility", "/skills/{id}/visibility"):
        assert f"{STUDIO_PREFIX}{tail}" in patches, tail


def test_visibility_routes_under_prefix():
    app = web.Application()
    setup_studio_routes(app, prefix=TENANT_PREFIX)
    patches = _paths(app)
    for tail in ("/agents/{name}/visibility", "/drafts/{name}/visibility", "/skills/{id}/visibility"):
        assert f"{TENANT_PREFIX}{tail}" in patches, tail


def test_skill_route_order():
    app = web.Application()
    setup_studio_routes(app)
    paths = _paths(app)
    generic = paths.index(f"{STUDIO_PREFIX}/skills/{{id}}")
    assert paths.index(f"{STUDIO_PREFIX}/skills/resync") < generic
    assert paths.index(f"{STUDIO_PREFIX}/skills/{{id}}/visibility") < generic


async def test_skill_visibility_resolves_to_visibility_handler():
    app = web.Application()
    setup_studio_routes(app)
    match = await app.router.resolve(make_mocked_request("PATCH", f"{STUDIO_PREFIX}/skills/abc/visibility", app=app))
    assert match.http_exception is None
    assert match.handler.__name__ == "StudioSkillVisibilityHandler"
    assert match["id"] == "abc"


def test_visibility_update_request_validation():
    assert VisibilityUpdateRequest(visibility="tenant").allowed_groups == []
    with pytest.raises(ValidationError):
        VisibilityUpdateRequest(visibility="public")
    with pytest.raises(ValidationError):
        VisibilityUpdateRequest()


def test_create_models_default_private():
    assert CreateAgentRequest(name="a").visibility == "private"
    assert CreateAgentRequest(name="a").allowed_groups == []
    assert SkillPublishRequest(**PAYLOAD).visibility == "private"
    assert SaveDraftRequest(name="d", source="x").visibility == "private"
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="a", visibility="public")


async def test_patch_routes_work_through_setup_routes_only(aiohttp_client, pool):  # noqa: F811
    """Agents, drafts and skills: owner PATCH 200; visible-not-manageable 403 ``not_manageable`` (C1); invisible 404."""
    client = await aiohttp_client(tenant_app(pool))
    owner, peer, outsider = who("u1"), who("u2"), who("u9", "globex")
    assert (await create(client, "r-agent", owner, visibility="tenant"))[0].status == 201
    assert (await save(client, "r-draft", owner, visibility="tenant"))[0].status == 201
    resp, body = await publish(client, "r-skill", owner, visibility="tenant")
    assert resp.status == 201, body
    urls = {
        "agent": f"{BASE}/agents/r-agent/visibility",
        "draft": f"{BASE}/drafts/r-draft/visibility",
        "skill": f"{BASE}/skills/{body['skill_id']}/visibility",
    }
    for kind, url in urls.items():
        resp = await client.patch(url, json={"visibility": "private"}, headers=peer)
        assert resp.status == 403 and (await resp.json())["code"] == "not_manageable", kind
        resp = await client.patch(url, json={"visibility": "private"}, headers=outsider)
        assert resp.status == 404, kind
        resp = await client.patch(url, json={"visibility": "tenant"}, headers=owner)
        assert resp.status == 200 and (await resp.json())["visibility"] == "tenant", kind
