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
                id="root",
                component="DataTable",
                title="<b>Sales</b>",  # hostile-ish data value
                columns=[{"name": "region"}, {"name": "total"}],
                data={"path": "/rows"},
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
    assert '"path"' not in doc
    # ...and the bound rows actually reach the document. Absence of "$bind" alone
    # was never proof of that: before row materialisation the resolved rows sat in
    # an inert property on a childless node and every table rendered empty.
    assert "EU" in doc
    assert ">5<" in doc


async def test_e2e_bound_rows_render_as_escaped_cells():
    """Every bound row reaches the document, in declared column order, escaped."""
    envelope = CreateSurface(
        surfaceId="report",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(
                id="root",
                component="DataTable",
                columns=[{"name": "region"}, {"name": "total"}],
                data={"path": "/rows"},
            )
        ],
        dataModel={
            "rows": [
                {"region": "EU", "total": 5},
                {"region": "APAC", "total": 7},
                {"region": "<script>alert(1)</script>", "total": None},
            ]
        },
    )
    doc = (await SSRHTMLRenderer().render(envelope)).content.decode()

    # One cell per column per row.
    assert doc.count('class="a2ui-text a2ui-cell"') == 6
    for value in ("EU", "APAC", ">5<", ">7<"):
        assert value in doc
    # Cell data is data, never markup.
    assert "<script>alert(1)</script>" not in doc
    assert "&lt;script&gt;" in doc
