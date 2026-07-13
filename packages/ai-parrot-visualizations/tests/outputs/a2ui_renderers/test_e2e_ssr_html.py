"""E2E: tool envelope → validate → SSR-HTML render (TASK-1729, spec §4)."""

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope  # noqa: E402
from parrot.outputs.a2ui.models import Component, CreateSurface  # noqa: E402
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer  # noqa: E402

pytestmark = pytest.mark.asyncio


async def test_e2e_tool_envelope_to_html():
    """Tool builder → catalog validate → SSR-HTML render → self-contained, safe doc."""
    # A tool builder emits a deterministic envelope (here constructed directly).
    envelope = CreateSurface(
        surfaceId="report",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(
                id="blk-000",
                component="DataTable",
                properties={
                    "title": "<b>Sales</b>",  # hostile-ish data value
                    "columns": [{"name": "region"}, {"name": "total"}],
                    "data": {"$bind": "/rows"},
                },
            )
        ],
        dataModel={"rows": [{"region": "EU", "total": 5}]},
    )
    # Tool-produced → validation passes (allowlist).
    validate_envelope(envelope, origin=ProducerOrigin.TOOL)

    art = await SSRHTMLRenderer().render(envelope)
    doc = art.content.decode()

    assert art.mime_type == "text/html"
    assert doc.startswith("<!DOCTYPE html>")
    # No script injection from data; the hostile title is escaped.
    assert "<b>Sales</b>" not in doc
    assert "&lt;b&gt;Sales&lt;/b&gt;" in doc
    # Baked: no live bindings remain.
    assert "$bind" not in doc
