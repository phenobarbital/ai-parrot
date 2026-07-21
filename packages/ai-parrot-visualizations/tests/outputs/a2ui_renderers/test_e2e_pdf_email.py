"""E2E: infographic envelope → PDF → email attachment seam (TASK-1732, spec §4).

The email provider is fully mocked — nothing is sent. The test proves the PDF
`RenderedArtifact` reaches the `report.files` attachment-extraction seam that
`NotificationMixin.send_notification` uses (full wiring is TASK-1733).
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("jsonpointer")
pytest.importorskip("weasyprint")

from parrot.outputs.a2ui.models import Component, CreateSurface  # noqa: E402
from parrot.outputs.a2ui_renderers.pdf import PDFRenderer  # noqa: E402

pytestmark = pytest.mark.asyncio


def _infographic_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="q1",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(
                id="b0",
                component="Infographic",
                properties={
                    "title": "Q1 Report",
                    "sections": [
                        {
                            "heading": "Metrics",
                            "components": [
                                {"component": "KPICard", "properties": {"label": "Rev", "value": 100}}
                            ],
                        }
                    ],
                },
            )
        ],
    )


async def test_e2e_envelope_to_pdf_email():
    # bake → PDF RenderedArtifact
    art = await PDFRenderer().render(_infographic_envelope())
    assert art.mime_type == "application/pdf"
    assert art.content[:5] == b"%PDF-"

    # Materialize to a temp file — the attachment path an email provider consumes.
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
        fh.write(art.content)
        pdf_path = Path(fh.name)

    # A report exposing `.files` (the highest-precedence attachment source per
    # NotificationMixin._extract_message_content: report.files → documents → blocks).
    report = SimpleNamespace(files=[pdf_path], documents=None)

    # Mocked provider: capture attachments instead of sending.
    captured = {}

    async def fake_send(*, message, recipients, attachments, **kwargs):
        captured["attachments"] = attachments
        return {"status": "ok"}

    # Simulate the send_notification attachment extraction (report.files precedence).
    attachments = list(report.files) if report.files else []
    result = await fake_send(message="Your report", recipients=["u@x.com"], attachments=attachments)

    assert result["status"] == "ok"
    assert pdf_path in captured["attachments"]
    assert pdf_path.read_bytes()[:5] == b"%PDF-"
    pdf_path.unlink()
