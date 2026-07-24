"""Tests for the deterministic render route (FEAT-327, Module 3:
``InfographicTalk._render_infographic_deterministic`` + route registration).

Exercises the handler method directly (constructed via ``__new__``, same
pattern as ``test_infographic_recipes.py``) against real aiohttp JSON
requests (``make_mocked_request`` with a fed ``StreamReader``) — no live
server needed. Multipart WIRE decoding itself is covered by TASK-1889's
``test_infographic_render_models.py``; this module focuses on the render
flow (validation gate, rendering, persistence, URL rule, negotiation).

NOTE: this package's pytest.ini_options sets `asyncio_mode = "auto"`, so
async test functions are detected automatically — no blanket `pytestmark`
needed (this module mixes sync and async tests).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.base_protocol import BaseProtocol
from aiohttp.streams import StreamReader
from aiohttp.test_utils import make_mocked_request

from parrot.handlers.infographic import InfographicTalk
from parrot.models.infographic_templates import InfographicTemplate, infographic_registry
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec
from parrot.tools.infographic_toolkit import InfographicToolkit

# ---------------------------------------------------------------------------
# Template fixtures (mirrors test_infographic_data_splice.py's TINY_TEMPLATE)
# ---------------------------------------------------------------------------

TEMPLATE_NAME = "feat327_render_test_tpl"

TINY_TEMPLATE = (
    "<!doctype html><html><head><title>T</title></head><body>"
    "<h1>Report</h1>"
    '<script type="application/json" id="report-data">\n{}\n</script>'
    "<div>footer</div></body></html>"
)


@pytest.fixture(autouse=True)
def _register_test_template():
    """Register ``TEMPLATE_NAME`` in the GLOBAL block-spec registry (404 gate)."""
    infographic_registry.register(
        InfographicTemplate(name=TEMPLATE_NAME, description="FEAT-327 test template", block_specs=[])
    )
    yield
    infographic_registry._templates.pop(TEMPLATE_NAME, None)


@pytest.fixture
def fake_artifact_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    store.get_public_url = AsyncMock(return_value="https://signed.example/artifact")
    return store


@pytest.fixture
def render_toolkit(fake_artifact_store):
    return InfographicToolkit(
        artifact_store=fake_artifact_store, templates={TEMPLATE_NAME: TINY_TEMPLATE}
    )


@pytest.fixture
def app(fake_artifact_store, render_toolkit):
    application = web.Application()
    application["artifact_store"] = fake_artifact_store
    application["infographic_render_toolkit"] = render_toolkit
    return application


def _descriptor(mode: str = "data-splice") -> SectionDescriptor:
    return SectionDescriptor(
        template=TEMPLATE_NAME,
        mode=mode,
        sections=[
            SectionSpec(
                name="hero",
                target="/hero",
                datasets=["revenue"],
                columns={"revenue": ["amount"]},
                shape="records",
            )
        ],
    )


def _render_body(**overrides) -> dict:
    body = {
        "datasets": {"revenue": {"orient": "records", "data": [{"amount": 1}, {"amount": 2}]}},
        "template": TEMPLATE_NAME,
        "descriptor": _descriptor().model_dump(),
        "persist": True,
        "public": False,
    }
    body.update(overrides)
    return body


async def _json_request(app: web.Application, body: dict, *, headers: Optional[dict] = None):
    data = json.dumps(body).encode("utf-8")
    loop = asyncio.get_event_loop()
    protocol = BaseProtocol(loop=loop)
    stream = StreamReader(protocol, limit=2**20, loop=loop)
    stream.feed_data(data)
    stream.feed_eof()
    # Default Accept: application/json — _negotiate_accept()'s own default is
    # text/html (no ?format=, no matching Accept header), so tests that want
    # the JSON branch need it explicit; tests wanting HTML override it.
    all_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        all_headers.update(headers)
    return make_mocked_request(
        "POST", "/api/v1/agents/infographic/render",
        headers=all_headers, payload=stream, app=app,
    )


def _handler(request) -> InfographicTalk:
    h = InfographicTalk.__new__(InfographicTalk)
    h.logger = logging.getLogger("test.infographic_render_route")
    h._request = request
    return h


class _FixedAttributionInfographicTalk(InfographicTalk):
    """Test subclass returning fixed attribution (bypasses session plumbing)."""

    async def _resolve_render_attribution(self, parsed):
        return "user-42", parsed.agent_id or "_anon", parsed.session_id or "sess-1"


def _fixed_handler(request) -> _FixedAttributionInfographicTalk:
    h = _FixedAttributionInfographicTalk.__new__(_FixedAttributionInfographicTalk)
    h.logger = logging.getLogger("test.infographic_render_route")
    h._request = request
    return h


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRenderRoute:
    async def test_unknown_template_404(self, app):
        # BaseView.error() RAISES the HTTPException (aiohttp's dispatch layer
        # normally converts it to a response) — direct-call tests catch it.
        request = await _json_request(app, _render_body(template="does-not-exist"))
        with pytest.raises(web.HTTPNotFound):
            await _handler(request)._render_infographic_deterministic()

    async def test_null_dataset_without_multipart_part_400(self, app):
        """A ``None``-valued dataset with NO multipart part is a transport
        error (400) — distinct from the FEAT-326 gate's 422 (missing/short
        columns on an EXISTING dataset), covered below."""
        body = _render_body(datasets={"revenue": None})
        request = await _json_request(app, body)
        response = await _handler(request)._render_infographic_deterministic()
        assert response.status == 400

    async def test_deficits_aggregated_422_missing_column(self, app):
        descriptor = SectionDescriptor(
            template=TEMPLATE_NAME,
            mode="data-splice",
            sections=[
                SectionSpec(
                    name="hero", target="/hero", datasets=["revenue"],
                    columns={"revenue": ["amount", "missing_col"]}, shape="records",
                )
            ],
        )
        body = _render_body(descriptor=descriptor.model_dump())
        request = await _json_request(app, body)
        response = await _handler(request)._render_infographic_deterministic()
        assert response.status == 422
        payload = json.loads(response.body)
        assert payload["error"] == "sections_unmet"

    async def test_html_negotiation_and_json_default(self, app):
        request = await _json_request(app, _render_body(), headers={"Accept": "text/html"})
        response = await _handler(request)._render_infographic_deterministic()
        assert response.status == 200
        assert response.content_type == "text/html"
        assert "report-data" in response.body.decode("utf-8")
        assert response.headers["X-Artifact-Persisted"] == "true"

        request2 = await _json_request(app, _render_body())
        response2 = await _handler(request2)._render_infographic_deterministic()
        assert response2.content_type == "application/json"
        payload = json.loads(response2.body)
        assert payload["template"] == TEMPLATE_NAME
        assert payload["persisted"] is True
        assert payload["sections_validated"] == 1

    async def test_deterministic_repeat_call(self, app):
        request1 = await _json_request(app, _render_body(), headers={"Accept": "text/html"})
        response1 = await _handler(request1)._render_infographic_deterministic()
        request2 = await _json_request(app, _render_body(), headers={"Accept": "text/html"})
        response2 = await _handler(request2)._render_infographic_deterministic()
        assert response1.body == response2.body

    async def test_persist_awaited_with_attribution(self, app, fake_artifact_store):
        request = await _json_request(app, _render_body())
        response = await _fixed_handler(request)._render_infographic_deterministic()
        assert response.status == 200
        fake_artifact_store.save_artifact.assert_awaited_once()
        call_args = fake_artifact_store.save_artifact.call_args
        assert call_args.args[0] == "user-42"  # user_id from session (fixed)
        assert call_args.args[1] == "_anon"    # agent_id system default
        assert call_args.args[2] == "sess-1"   # session_id system default

    async def test_persist_false_skips_store(self, app, fake_artifact_store):
        request = await _json_request(app, _render_body(persist=False))
        response = await _handler(request)._render_infographic_deterministic()
        assert response.status == 200
        payload = json.loads(response.body)
        assert payload["persisted"] is False
        fake_artifact_store.save_artifact.assert_not_awaited()

    async def test_public_true_static_dir_url(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr("parrot.conf.STATIC_DIR", tmp_path)
        request = await _json_request(app, _render_body(public=True))
        response = await _handler(request)._render_infographic_deterministic()
        payload = json.loads(response.body)
        assert payload["url"].startswith("/static/")
        written = list(tmp_path.glob("infographic-*.html"))
        assert len(written) == 1
        assert "report-data" in written[0].read_text()

    async def test_local_nonpublic_url_presigned(self, app, fake_artifact_store):
        request = await _json_request(app, _render_body(public=False))
        response = await _handler(request)._render_infographic_deterministic()
        payload = json.loads(response.body)
        assert payload["url"] == "https://signed.example/artifact"
        fake_artifact_store.get_public_url.assert_awaited_once()

    async def test_local_nonpublic_url_null_when_not_persisted(self, app):
        request = await _json_request(app, _render_body(public=False, persist=False))
        response = await _handler(request)._render_infographic_deterministic()
        payload = json.loads(response.body)
        assert payload["url"] is None

    async def test_async_not_implemented_seam(self, app):
        body = _render_body()
        body["async"] = True
        request = await _json_request(app, body)
        response = await _handler(request)._render_infographic_deterministic()
        assert response.status == 501


class TestRenderRouteRegistration:
    def test_render_route_registered_before_agent_id(self):
        """The literal `render` resource route must be registered BEFORE the
        {agent_id} catch-all so aiohttp never swallows it (spec §7 Known Risks)."""
        import inspect

        from parrot.manager.manager import BotManager

        source = inspect.getsource(BotManager)
        render_idx = source.index("{resource:render}")
        agent_id_idx = source.index("/api/v1/agents/infographic/{agent_id}")
        assert render_idx < agent_id_idx
