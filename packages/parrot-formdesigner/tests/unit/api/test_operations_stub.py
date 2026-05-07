"""Unit test for the Wave 1 ``/operations`` 501 stub."""

from __future__ import annotations

from aiohttp import web

from parrot_formdesigner.api.operations import handle_operations


async def test_operations_returns_501(aiohttp_client):
    app = web.Application()
    app.router.add_patch(
        "/api/v1/forms/{form_id}/operations", handle_operations
    )
    client = await aiohttp_client(app)
    resp = await client.patch(
        "/api/v1/forms/test-form/operations", json={"operations": []}
    )
    assert resp.status == 501
    body = await resp.json()
    assert body == {"detail": "not implemented"}
