"""`parrot ontology` — publish, export and snapshot ontology vocabularies (FEAT-824)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import click


def _database_options(command: Any) -> Any:
    """Add the common ontology PostgreSQL options to a Click command."""
    command = click.option(
        "--schema", default=None, help="Schema name (default: ONTOLOGY_PG_SCHEMA or ontology_store)."
    )(command)
    return click.option("--dsn", default=None, help="asyncpg DSN (default: ONTOLOGY_PG_DSN).")(command)


@click.group()
def ontology() -> None:
    """Ontology vocabulary store: publish, export and snapshot."""


@ontology.command("init-schema")
@_database_options
def init_schema(dsn: str | None, schema: str | None) -> None:
    """Create the vocabulary schema if missing."""

    async def _run() -> None:
        from parrot.knowledge.ontology.vocabulary.pg_schema import create_ontology_pg_pool, ensure_schema

        pool = await create_ontology_pg_pool(dsn, schema=schema)
        try:
            await ensure_schema(pool, schema)
        finally:
            await pool.close()

    asyncio.run(_run())
    click.echo("ontology schema ready")


@ontology.command("register")
@click.argument("ontology_id")
@click.option("--base-iri", required=True, help="Immutable base IRI for the ontology.")
@click.option("--title", default=None, help="Human-readable ontology title.")
@_database_options
def register(ontology_id: str, base_iri: str, title: str | None, dsn: str | None, schema: str | None) -> None:
    """Register an ontology before its first publication."""

    async def _run() -> None:
        from parrot.knowledge.ontology.vocabulary.pg_schema import create_ontology_pg_pool
        from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher

        pool = await create_ontology_pg_pool(dsn, schema=schema)
        publisher = PostgresOntologyPublisher(pool, schema=schema)
        try:
            await publisher.ensure_ontology(ontology_id, base_iri=base_iri, title=title)
        finally:
            await publisher.close()
            await pool.close()

    asyncio.run(_run())
    click.echo(f"registered {ontology_id}")


@ontology.command("publish")
@click.argument("ontology_id")
@click.argument("turtle_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--shapes", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option("--notes", default=None, help="Release notes stored with the published version.")
@_database_options
def publish(
    ontology_id: str,
    turtle_file: Path,
    shapes: Path | None,
    notes: str | None,
    dsn: str | None,
    schema: str | None,
) -> None:
    """Publish a Turtle document as the next ontology version."""

    async def _run() -> Any:
        from parrot.knowledge.ontology.vocabulary.pg_schema import create_ontology_pg_pool
        from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher

        pool = await create_ontology_pg_pool(dsn, schema=schema)
        publisher = PostgresOntologyPublisher(pool, schema=schema)
        try:
            return await publisher.publish(
                ontology_id,
                turtle_file.read_bytes(),
                notes=notes or "",
                shapes=shapes.read_bytes() if shapes is not None else None,
            )
        finally:
            await publisher.close()
            await pool.close()

    from parrot.knowledge.ontology.vocabulary.exceptions import OntologyValidationError

    try:
        result = asyncio.run(_run())
    except OntologyValidationError as exc:
        for issue in exc.issues:
            subject = f" [{issue.subject}]" if issue.subject else ""
            click.echo(f"{issue.code}: {issue.message}{subject}", err=True)
        raise click.exceptions.Exit(1) from exc

    diff = result.diff
    click.echo(
        f"version={result.version} changed={str(result.changed).lower()} "
        f"added={len(diff.added_iris)} changed_iris={len(diff.changed_iris)} "
        f"deprecated={len(diff.deprecated)} relations_added={diff.relations_added} "
        f"relations_closed={diff.relations_closed}"
    )


@ontology.command("version")
@click.argument("ontology_id")
@_database_options
def version(ontology_id: str, dsn: str | None, schema: str | None) -> None:
    """Print the current published version of an ontology."""

    async def _run() -> int:
        from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore

        store = PostgresOntologyStore(None, dsn=dsn, schema=schema)
        try:
            return await store.version(ontology_id)
        finally:
            await store.close()

    click.echo(asyncio.run(_run()))


@ontology.command("export")
@click.argument("ontology_id")
@click.option("--as-of", type=int, default=None, help="Published version to export.")
@click.option("--format", "output_format", type=click.Choice(["turtle", "jsonld"]), default="turtle", show_default=True)
@click.option("-o", "output_file", type=click.Path(dir_okay=False, path_type=Path), default=None)
@_database_options
def export(
    ontology_id: str,
    as_of: int | None,
    output_format: str,
    output_file: Path | None,
    dsn: str | None,
    schema: str | None,
) -> None:
    """Export an ontology version as Turtle or JSON-LD."""

    async def _run() -> bytes:
        from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore

        store = PostgresOntologyStore(None, dsn=dsn, schema=schema)
        try:
            return await store.export(ontology_id, output_format, as_of=as_of)
        finally:
            await store.close()

    payload = asyncio.run(_run())
    if output_file is None:
        click.echo(payload.decode("utf-8"), nl=False)
    else:
        output_file.write_bytes(payload)
        click.echo(output_file)


@ontology.command("snapshot")
@click.argument("ontology_id")
@click.option("--version", "snapshot_version", type=int, default=None, help="Published version to snapshot.")
@click.option("--dest", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--from-turtle", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option("--base-iri", default=None, help="Base IRI required with --from-turtle.")
@_database_options
def snapshot(
    ontology_id: str,
    snapshot_version: int | None,
    dest: Path | None,
    from_turtle: Path | None,
    base_iri: str | None,
    dsn: str | None,
    schema: str | None,
) -> None:
    """Build a read-only SQLite snapshot from PostgreSQL or a Turtle file."""
    if from_turtle is None and base_iri is not None:
        raise click.UsageError("--base-iri requires --from-turtle")
    if from_turtle is not None and base_iri is None:
        raise click.UsageError("--base-iri is required with --from-turtle")

    async def _run() -> Path:
        from parrot.knowledge.ontology.vocabulary.snapshot import build_snapshot
        from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings

        settings = resolve_ontology_settings(dsn=dsn, schema=schema)
        destination = dest or settings.snapshot_dir
        if from_turtle is None:
            from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore

            store = PostgresOntologyStore(None, dsn=dsn, schema=schema)
            try:
                content = await store.load_version(ontology_id, snapshot_version)
            finally:
                await store.close()
        else:
            from parrot.knowledge.ontology.vocabulary.closure import build_closure, materialise_inverses
            from parrot.knowledge.ontology.vocabulary.contracts import VersionContent
            from parrot.knowledge.ontology.vocabulary.exceptions import OntologyValidationError
            from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, parse_turtle, validate_content

            parsed = parse_turtle(from_turtle.read_bytes(), base_iri=base_iri, default_lang=settings.default_lang)
            issues = validate_content(parsed)
            if issues:
                raise OntologyValidationError(issues)
            parsed.relations.extend(materialise_inverses(parsed.relations))
            closure = build_closure(parsed.relations, (concept.iri for concept in parsed.concepts))
            content = VersionContent(
                ontology_id=ontology_id,
                version=snapshot_version or 1,
                checksum=content_checksum(parsed),
                content=parsed,
                closure=closure,
            )
        return await build_snapshot(content, destination)

    click.echo(asyncio.run(_run()))


@ontology.command("publish-catalog")
@click.option("--tenant", "tenant_id", required=True, help="Tenant whose approved catalog is published.")
@click.option("--catalog-dsn", default=None, help="Catalog DSN (default: parrot.conf.default_dsn).")
@_database_options
def publish_catalog(
    tenant_id: str,
    catalog_dsn: str | None,
    dsn: str | None,
    schema: str | None,
) -> None:
    """Publish one tenant's approved concept catalog."""

    async def _run() -> Any:
        from parrot.conf import default_dsn
        from parrot.knowledge.ontology.vocabulary.catalog_bridge import CatalogVocabularyPublisher
        from parrot.knowledge.ontology.vocabulary.pg_schema import create_ontology_pg_pool
        from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher

        vocabulary_pool = await create_ontology_pg_pool(dsn, schema=schema)
        publisher = PostgresOntologyPublisher(vocabulary_pool, schema=schema)
        catalog_pool = await create_ontology_pg_pool(catalog_dsn or default_dsn, schema=schema)
        bridge = CatalogVocabularyPublisher(catalog_pool, publisher)
        try:
            return await bridge.publish_tenant(tenant_id)
        finally:
            await publisher.close()
            await catalog_pool.close()
            await vocabulary_pool.close()

    result = asyncio.run(_run())
    click.echo(f"version={result.version} changed={str(result.changed).lower()}")
