"""FEAT-734 M1 — FormDesignerClient against a fake aiohttp server."""

import uuid

import pytest
from aiohttp import web

from parrot.integrations.msteams.formdesigner_client import (
    MAX_RESPONSE_BYTES,
    FormDesignerClient,
    FormDesignerError,
    parse_form_ref,
)

UID = uuid.UUID("f0000000-0000-0000-0000-000000000001")


@pytest.fixture
def seen() -> list[dict[str, object]]:
    """Collect each received fake-server request."""
    return []


async def _server(aiohttp_server, seen, handler):
    """Start a request-recording aiohttp test server."""
    app = web.Application()

    async def _record(request):
        seen.append({"path": request.path, "query": dict(request.query), "auth": request.headers.get("Authorization")})
        return await handler(request)

    app.router.add_get("/{tail:.*}", _record)
    return await aiohttp_server(app)


def _descriptor() -> dict[str, str]:
    """Return a stable list-form descriptor fixture."""
    return {"form_uid": str(UID), "form_id": "store-visit", "title": "Store visit", "description": "Survey"}


async def test_client_list_forms_parses_descriptors(aiohttp_server, seen):
    """``{"forms": [...]}`` produces descriptors and supports an empty result."""
    response_count = 0

    async def handler(_request):
        nonlocal response_count
        response_count += 1
        if response_count == 1:
            descriptor = _descriptor()
            descriptor["title"] = {"en": "Store visit"}
            return web.json_response({"forms": [descriptor]})
        return web.json_response({"forms": []})

    server = await _server(aiohttp_server, seen, handler)
    client = FormDesignerClient(str(server.make_url("/")))
    try:
        forms = await client.list_forms(tenant="acme", bearer_token=None)
        assert forms[0].form_uid == UID
        assert forms[0].form_id == "store-visit"
        assert forms[0].title == "Store visit"
        assert await client.list_forms(tenant="acme", bearer_token=None) == []
    finally:
        await client.close()


async def test_client_list_forms_sends_bearer(aiohttp_server, seen):
    """Authorization is sent only for a non-empty bearer token."""

    async def handler(_request):
        return web.json_response({"forms": []})

    server = await _server(aiohttp_server, seen, handler)
    client = FormDesignerClient(str(server.make_url("/")))
    try:
        await client.list_forms(tenant="acme", bearer_token="token-123")
        await client.list_forms(tenant="acme", bearer_token=None)
        assert [request["auth"] for request in seen] == ["Bearer token-123", None]
    finally:
        await client.close()


async def test_client_render_teams_with_meta(aiohttp_server, seen):
    """A ``with_meta`` render envelope produces a complete ``RenderedCard``."""

    async def handler(_request):
        return web.json_response(
            {
                "content": {"type": "AdaptiveCard"},
                "content_type": "application/vnd.microsoft.card.adaptive",
                "warnings": [],
                "metadata": {"envelope": {"form_uid": str(UID)}},
            }
        )

    server = await _server(aiohttp_server, seen, handler)
    client = FormDesignerClient(str(server.make_url("/")))
    try:
        card = await client.render_teams(tenant="acme", form_uid=UID, bearer_token=None)
        assert card.metadata["envelope"]["form_uid"] == str(UID)
        assert seen[0]["query"] == {"with_meta": "true"}
    finally:
        await client.close()


async def test_client_render_teams_415_raises(aiohttp_server, seen):
    """An unsupported teams renderer surfaces its HTTP 415 status."""

    async def handler(_request):
        return web.json_response({"supported": ["html"]}, status=415)

    server = await _server(aiohttp_server, seen, handler)
    client = FormDesignerClient(str(server.make_url("/")))
    try:
        with pytest.raises(FormDesignerError, match="415") as exc_info:
            await client.render_teams(tenant="acme", form_uid=UID, bearer_token=None)
        assert exc_info.value.status == 415
    finally:
        await client.close()


async def test_client_no_redirects_and_bounded_body(aiohttp_server, seen):
    """A redirect is not followed and oversized bodies are refused."""

    async def redirect_handler(request):
        if request.path.endswith("redirect"):
            raise web.HTTPFound("/api/v1/acme/forms")
        return web.Response(body=b"x" * (MAX_RESPONSE_BYTES + 1), content_type="application/json")

    server = await _server(aiohttp_server, seen, redirect_handler)
    client = FormDesignerClient(str(server.make_url("/")))
    try:
        with pytest.raises(FormDesignerError) as redirect_error:
            await client._request_json(str(server.make_url("/redirect")), bearer_token=None)
        assert redirect_error.value.status == 302
        with pytest.raises(FormDesignerError, match="response too large") as oversize_error:
            await client.list_forms(tenant="acme", bearer_token=None)
        assert oversize_error.value.status == 200
        assert len(seen) == 2
    finally:
        await client.close()


async def test_client_section_render_requires_matching_metadata(aiohttp_server, seen):
    """A server that ignores required section metadata is rejected as old."""

    async def handler(_request):
        return web.json_response(
            {
                "content": {"type": "AdaptiveCard"},
                "content_type": "application/vnd.microsoft.card.adaptive",
                "metadata": {"section_index": 1, "total_sections": "2", "form_version": "1.0"},
            }
        )

    server = await _server(aiohttp_server, seen, handler)
    client = FormDesignerClient(str(server.make_url("/")))
    try:
        with pytest.raises(FormDesignerError, match="section rendering"):
            await client.render_teams(tenant="acme", form_uid=UID, bearer_token=None, section_index=1)
        assert seen[0]["query"] == {"with_meta": "true", "section_index": "1"}
    finally:
        await client.close()


def test_parse_form_ref_uuid_vs_slug():
    """UUID-shaped references resolve to UUIDs and slugs remain strings."""
    assert parse_form_ref(str(UID)) == UID
    assert parse_form_ref("store-visit") == "store-visit"
