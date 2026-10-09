"""PA-V2 review fix 1: ``POST /tools/{slug}/execute`` is built through the host hook and the app-managed params.

Real app, real handler, real ``DocumentConverterTool`` / ``CSVExportTool``; the hook is host code (test-owned).
"""
from __future__ import annotations

import pytest

from parrot.handlers.studio import STUDIO_TOOLKIT_PARAM_HOOK
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.overflow import OverflowStore
from parrot.tools.tooling_policy import TenantToolingPolicy, ToolParamRefused, set_tenant_tooling_policy
from navigator.utils.file import LocalFileManager

from .test_agents_db_mode import BASE, pool  # noqa: F401  (fixture)
from .test_agents_visibility import tenant_app, who


def _app(pool, hook=None, store=None):  # noqa: F811
    app = tenant_app(pool)
    set_tenant_tooling_policy(app, TenantToolingPolicy(builtin_tools=frozenset({"doc_converter", "csv_export"})))
    if hook is not None:
        app[STUDIO_TOOLKIT_PARAM_HOOK] = hook
    if store is not None:
        app["artifact_store"] = store
    return app


async def _execute(client, slug, args):
    resp = await client.post(f"{BASE}/tools/{slug}/execute", json={"args": args}, headers=who("u1"))
    return resp, await resp.json()


async def test_the_hook_forces_a_confinement_switch_on_the_direct_route(aiohttp_client, pool, tmp_path):  # noqa: F811
    seen = []

    def hook(slug, params, subject):
        seen.append((slug, subject.phase, subject.tenant))
        return {**params, "url_only": True}

    secret = tmp_path / "secret.txt"
    secret.write_text("do not read")
    client = await aiohttp_client(_app(pool, hook))
    resp, body = await _execute(client, "doc_converter", {"source": str(secret)})
    assert resp.status == 200 and "http(s) URL" in str(body), body          # url_only reached the tool
    assert seen == [("doc_converter", "execute", "acme")]                  # the slug the hook is keyed by


async def test_without_a_hook_the_route_is_unchanged(aiohttp_client, pool, tmp_path):  # noqa: F811
    note = tmp_path / "note.txt"
    note.write_text("hello")
    client = await aiohttp_client(_app(pool))
    resp, body = await _execute(client, "doc_converter", {"source": str(note)})
    assert resp.status == 200 and "http(s) URL" not in str(body), body


@pytest.mark.parametrize("failure", [ToolParamRefused(["url_only"]), RuntimeError("boom")], ids=["refuses", "raises"])
async def test_a_refusing_or_broken_hook_fails_closed(aiohttp_client, pool, failure):  # noqa: F811
    def hook(slug, params, subject):
        raise failure

    client = await aiohttp_client(_app(pool, hook))
    resp, body = await _execute(client, "doc_converter", {"source": "/etc/hostname"})
    assert resp.status == 422 and body["details"]["reason"] == "tool_params_not_permitted", body


async def test_the_artifact_store_is_injected_even_though_the_constructor_defaults_it(  # noqa: F811
    aiohttp_client, pool, tmp_path
):
    store = ArtifactStore(
        dynamodb=ConversationSQLiteBackend(str(tmp_path / "c.db")),
        s3_overflow=OverflowStore(LocalFileManager(base_path=tmp_path / "files")),
    )
    client = await aiohttp_client(_app(pool, store=store))
    resp, body = await _execute(client, "csv_export", {"content": [{"a": 1, "b": 2}]})
    assert resp.status == 200, body
    assert "/exports/acme/" in str(body), body                               # published to the tenant's store
