"""FormDesigner CLI behavioral tests — FEAT-650 TASK-4204."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest
from click.testing import CliRunner

from parrot_formdesigner.cli import formdesigner
from parrot_formdesigner.services.a2ui_export import ExportedSurface


def test_help_without_services() -> None:
    """The group help does not need service imports."""
    result = CliRunner().invoke(formdesigner, ["--help"])
    assert result.exit_code == 0
    assert all(command in result.output for command in ("export", "import", "translate"))


def test_export_requires_dsn(tmp_path) -> None:
    """A storage-backed command reports missing DSN as configuration error."""
    result = CliRunner().invoke(
        formdesigner,
        ["export", "--tenant", "t", "--out", str(tmp_path)],
        env={"FORMDESIGNER_DSN": ""},
    )
    assert result.exit_code == 2


def test_export_writes_files_and_report(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful rows write envelopes while error rows produce a failing report."""
    import parrot_formdesigner.cli as cli_module

    class Storage:
        """Minimal storage lifecycle double."""

        async def close(self) -> None:
            """Record no action on close."""

    class Service:
        """Export service yielding one good and one failed row."""

        def __init__(self, registry, *, dialect: str, locale: str) -> None:
            """Accept the production constructor shape."""

        async def export_tenant(self, *args, **kwargs) -> AsyncIterator[ExportedSurface]:
            """Yield deterministic rows for CLI report behavior."""
            yield ExportedSurface(
                form_uid="good-uid",
                form_id="good",
                version="1.0",
                dialect="a2ui",
                envelope={"createSurface": {"surfaceId": "good"}},
                warnings=["notice"],
            )
            yield ExportedSurface(
                form_uid="bad-uid", form_id="bad", version="1.0", dialect="a2ui", error="render failed"
            )

    async def registry(dsn: str | None, tenant: str) -> tuple[object, Storage]:
        """Return a fake registry and closable storage."""
        return object(), Storage()

    monkeypatch.setattr(cli_module, "_registry", registry)
    monkeypatch.setattr("parrot_formdesigner.services.a2ui_export.A2UIExportService", Service)
    result = CliRunner().invoke(formdesigner, ["export", "--tenant", "t", "--out", str(tmp_path), "--dsn", "dsn"])

    report = json.loads((tmp_path / "export-report.json").read_text())
    assert result.exit_code == 1
    assert json.loads((tmp_path / "good-good-uid.a2ui.json").read_text())["createSurface"]["surfaceId"] == "good"
    assert report == {"exported": 1, "failed": 1, "warnings": {"good-uid": ["notice"], "bad-uid": ["render failed"]}}


def test_import_dry_run_prints_report(tmp_path) -> None:
    """Dry imports report their extraction result without requiring storage."""
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
    from parrot_formdesigner.core.types import FieldType
    from parrot_formdesigner.renderers import A2UIFormRenderer

    form = FormSchema(
        form_id="example",
        title={"en": "Example"},
        sections=[FormSection(section_id="main", fields=[FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"})])],
    )
    surface = asyncio.run(A2UIFormRenderer().render(form))
    path = tmp_path / "surface.json"
    path.write_text(json.dumps(surface.content))

    result = CliRunner().invoke(formdesigner, ["import", str(path), "--tenant", "t", "--dry-run"])
    assert result.exit_code == 0
    assert '"mode"' in result.output


def test_translate_writes_envelope(tmp_path) -> None:
    """Translation produces an A2UI envelope without a storage DSN."""
    pytest.importorskip("parrot.outputs.a2ui")
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps({"type": "object", "title": "T", "properties": {"a": {"type": "string"}}}))

    result = CliRunner().invoke(formdesigner, ["translate", str(schema_path), "--tenant", "t"])
    assert result.exit_code == 0
    assert "createSurface" in result.output


def test_python_m_entry() -> None:
    """The module remains independently invokable."""
    import subprocess
    import sys

    result = subprocess.run([sys.executable, "-m", "parrot_formdesigner.cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "formdesigner" in result.stdout.lower()
