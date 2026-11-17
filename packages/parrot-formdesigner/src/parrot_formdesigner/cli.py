"""``parrot formdesigner`` export, import, and translate commands (FEAT-650)."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import click

dsn_option = click.option("--dsn", envvar="FORMDESIGNER_DSN", default=None, help="Postgres DSN (env FORMDESIGNER_DSN).")
tenant_option = click.option("--tenant", "tenants", multiple=True, required=True, help="Tenant slug (repeatable).")


@click.group(name="formdesigner")
def formdesigner() -> None:
    """FormDesigner dialect tools (FEAT-650)."""


def _config_error(message: str) -> None:
    """Write a configuration error and end the command with status 2.

    Args:
        message: Description of the missing configuration or optional extra.
    """
    click.echo(f"Error: {message}", err=True)
    raise click.exceptions.Exit(2)


async def _registry(dsn: str | None, tenant: str) -> tuple[Any, Any]:
    """Build the registry and storage for one tenant.

    Args:
        dsn: PostgreSQL connection string.
        tenant: Tenant slug to initialise.

    Returns:
        The tenant-scoped registry and its open storage backend.
    """
    if not dsn:
        _config_error("a Postgres DSN is required (--dsn or FORMDESIGNER_DSN)")
    from .services.registry import FormRegistry
    from .services.storage import PostgresFormStorage

    storage = PostgresFormStorage(dsn=dsn, tenant=tenant)
    await storage.initialize(tenant=tenant)
    return FormRegistry(storage=storage, default_tenant=tenant), storage


@formdesigner.command("export")
@click.option("--dialect", type=click.Choice(["a2ui", "json_schema"]), default="a2ui", show_default=True)
@tenant_option
@click.option("--form-uid", "form_uids", multiple=True, help="Restrict to these form_uids (repeatable).")
@click.option("--published-only", is_flag=True, default=False)
@click.option("--locale", default="en", show_default=True)
@click.option("--out", "out_dir", type=click.Path(file_okay=False, path_type=Path), required=True)
@dsn_option
def export(
    dialect: str,
    tenants: tuple[str, ...],
    form_uids: tuple[str, ...],
    published_only: bool,
    locale: str,
    out_dir: Path,
    dsn: str | None,
) -> None:
    """Write one form file plus ``export-report.json`` for each requested form."""
    report = asyncio.run(_export(dialect, tenants, form_uids, published_only, locale, out_dir, dsn))
    (out_dir / "export-report.json").write_text(json.dumps(report, indent=2))
    click.echo(f"exported={report['exported']} failed={report['failed']} → {out_dir}")
    sys.exit(1 if report["failed"] else 0)


async def _export(
    dialect: str,
    tenants: tuple[str, ...],
    form_uids: tuple[str, ...],
    published_only: bool,
    locale: str,
    out_dir: Path,
    dsn: str | None,
) -> dict[str, Any]:
    """Export selected forms and return their aggregate report.

    Args:
        dialect: Requested output dialect.
        tenants: Tenant slugs to export.
        form_uids: Optional form UID allowlist.
        published_only: Whether unpublished forms are excluded.
        locale: Output locale.
        out_dir: Destination directory for envelopes.
        dsn: PostgreSQL connection string.

    Returns:
        Counts and per-form warnings for the export operation.
    """
    from .services.a2ui_export import A2UIExportService

    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    report: dict[str, Any] = {"exported": 0, "failed": 0, "warnings": {}}
    uids = [uuid.UUID(value) for value in form_uids] or None
    for tenant in tenants:
        registry, storage = await _registry(dsn, tenant)
        try:
            service = A2UIExportService(registry, dialect=dialect, locale=locale)
            async for row in service.export_tenant(tenant, form_uids=uids, published_only=published_only):
                if row.error:
                    report["failed"] += 1
                    report["warnings"][row.form_uid] = [row.error]
                    continue
                output = out_dir / f"{row.form_id}-{row.form_uid}.{dialect}.json"
                output.write_text(json.dumps(row.envelope, indent=2))
                report["exported"] += 1
                if row.warnings:
                    report["warnings"][row.form_uid] = row.warnings
        finally:
            await storage.close()
    return report


@formdesigner.command("import")
@click.argument("surface", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--tenant", required=True)
@click.option("--form-id", default=None)
@click.option("--overwrite", is_flag=True, default=False)
@click.option("--dry-run", is_flag=True, default=False)
@dsn_option
def import_surface(
    surface: Path, tenant: str, form_id: str | None, overwrite: bool, dry_run: bool, dsn: str | None
) -> None:
    """Extract an A2UI surface and persist it unless ``--dry-run`` is supplied."""
    sys.exit(asyncio.run(_import(surface, tenant, form_id, overwrite, dry_run, dsn)))


async def _import(
    surface: Path, tenant: str, form_id: str | None, overwrite: bool, dry_run: bool, dsn: str | None
) -> int:
    """Extract and optionally persist an A2UI surface.

    Args:
        surface: Source A2UI envelope path.
        tenant: Destination tenant.
        form_id: Optional form slug override.
        overwrite: Whether a same-UID form may be replaced.
        dry_run: Whether persistence is skipped.
        dsn: PostgreSQL connection string.

    Returns:
        Process exit code, with 3 representing a conflict.
    """
    from .extractors import A2UIExtractor

    try:
        result = A2UIExtractor().extract(await asyncio.to_thread(surface.read_text), form_id=form_id, tenant=tenant)
    except RuntimeError as exc:
        _config_error(str(exc))
    click.echo(
        json.dumps(
            {
                "mode": result.mode.value,
                "warnings": result.warnings,
                "dropped": [dropped.model_dump() for dropped in result.dropped],
            },
            indent=2,
        )
    )
    if dry_run:
        click.echo(result.form.model_dump_json(indent=2))
        return 0

    registry, storage = await _registry(dsn, tenant)
    try:
        existing = await registry.get(result.form.form_uid, tenant=tenant)
        if existing is not None and not overwrite:
            click.echo(f"conflict: form UID {result.form.form_uid} already exists", err=True)
            return 3
        form = result.form
        if existing is not None:
            from .api._utils import _bump_version

            form = form.model_copy(update={"version": _bump_version(existing.version)})
        await registry.register(form, persist=True, overwrite=True, tenant=tenant)
    finally:
        await storage.close()
    return 0


@formdesigner.command("translate")
@click.argument("schema_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--from", "source", type=click.Choice(["json_schema"]), default="json_schema", show_default=True)
@click.option("--to", "target", type=click.Choice(["a2ui"]), default="a2ui", show_default=True)
@click.option("--form-id", default=None)
@click.option("--tenant", default=None)
@click.option("--locale", default="en", show_default=True)
@click.option("--out", "out_file", type=click.Path(dir_okay=False, path_type=Path), default=None)
def translate(
    schema_file: Path,
    source: str,
    target: str,
    form_id: str | None,
    tenant: str | None,
    locale: str,
    out_file: Path | None,
) -> None:
    """Translate JSON Schema to an A2UI ``createSurface`` envelope."""
    del source, target
    from .renderers import A2UIFormRenderer
    from .services.a2ui_translate import translate_jsonschema_to_a2ui

    schema = json.loads(schema_file.read_text())
    try:
        rendered = asyncio.run(
            translate_jsonschema_to_a2ui(
                schema,
                form_id=form_id,
                tenant=tenant,
                locale=locale,
                renderer=A2UIFormRenderer(),
            )
        )
    except RuntimeError as exc:
        _config_error(str(exc))
    for warning in rendered.warnings:
        click.echo(f"warning: {warning.reason}", err=True)
    text = json.dumps(rendered.content, indent=2)
    if out_file:
        out_file.write_text(text)
    else:
        click.echo(text)


def main() -> None:
    """Run the standalone module entry point."""
    formdesigner(standalone_mode=True)


if __name__ == "__main__":
    main()
