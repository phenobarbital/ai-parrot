"""``parrot manuals`` — operator commands for the procedures plane (FEAT-601 M13)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import click

from parrot_tools.procedures.retrieval import AuthorizationDenied, ProcedureRetrieval, RequestContext

logger = logging.getLogger(__name__)


def build_library(*, dsn: str, tenant: str, storage_root: Path, evidence_root: Path, adapter: Any | None) -> Any:
    """Default factory: PostgresManualCatalog + ManualLibrary for ``tenant`` (imports are lazy).

    Note:
        ``file_manager``/``vision_client``/``graph_loader`` are left unwired (``None``): no
        concrete ``FileManagerInterface``/``S3FileManager`` implementation exists in this
        codebase yet, and constructing a real ``graph_store`` is outside this task's verified
        Codebase Contract. Operators that need figure uploads, captioning, or graph publishing
        must inject their own factory via ``ctx.obj["factory"]`` until those pieces land.
    """
    from parrot.knowledge.manuals.catalog_postgres import PostgresManualCatalog
    from parrot.knowledge.manuals.library import ManualLibrary

    catalog = PostgresManualCatalog(dsn, tenant_id=tenant)
    return ManualLibrary(
        catalog=catalog,
        storage_root=storage_root,
        evidence_root=evidence_root,
        adapter=adapter,
        file_manager=None,
    )


def _context(obj: dict[str, Any]) -> RequestContext:
    """Trusted operator context from explicit CLI options — never from a model."""
    return RequestContext(
        authenticated=True,
        tenant_id=obj["tenant"],
        user_id=obj["user"],
        employee_id=obj["user"],
        roles=frozenset(obj["roles"]),
        channel="cli",
    )


def _gate(library: Any, obj: dict[str, Any], *, curator_only: bool = True) -> RequestContext:
    """Run the shared ProcedureRetrieval gate for this operator; raise ClickException on denial."""
    context = _context(obj)
    gate = ProcedureRetrieval(
        catalog=library.catalog, graph_store=None, tenant_context=None, ontology=None, authorization=None
    )
    try:
        gate.authorize(context, curator_only=curator_only)
    except AuthorizationDenied as exc:
        raise click.ClickException(exc.reason) from exc
    return context


def _run(obj: dict[str, Any], body: Callable[[Any], Awaitable[Any]]) -> None:
    """Build the library, run ``body`` once under asyncio, print JSON, always close the catalog."""
    factory = obj.get("factory") or build_library

    async def _main() -> Any:
        library = factory(
            dsn=obj["dsn"],
            tenant=obj["tenant"],
            storage_root=obj["storage_root"],
            evidence_root=obj["evidence_root"],
            adapter=None,
        )
        try:
            return await body(library)
        finally:
            await library.catalog.close()

    result = asyncio.run(_main())
    payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    click.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


@click.group(name="manuals")
@click.option("--tenant", required=True, help="Tenant id.")
@click.option("--user", required=True, help="Authenticated operator id.")
@click.option("--role", "roles", multiple=True, help="Role granted by the deployment (repeatable).")
@click.option("--dsn", default=lambda: os.environ.get("GRAPHINDEX_PG_DSN", ""), help="Postgres DSN.")
@click.option("--storage-root", type=click.Path(path_type=Path), default=Path("manuals_storage"))
@click.option("--evidence-root", type=click.Path(path_type=Path), default=Path("manuals_evidence"))
@click.pass_context
def manuals(
    ctx: click.Context,
    tenant: str,
    user: str,
    roles: tuple[str, ...],
    dsn: str,
    storage_root: Path,
    evidence_root: Path,
) -> None:
    """Manuals: ingest assembly manuals, align videos, curate procedures."""
    ctx.ensure_object(dict)
    ctx.obj.update(
        tenant=tenant, user=user, roles=roles, dsn=dsn, storage_root=storage_root, evidence_root=evidence_root
    )


@manuals.command("add")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--equipment", multiple=True, required=True)
@click.option("--revision", required=True)
@click.option("--source-uri", default=None)
@click.option("--force", is_flag=True)
@click.pass_obj
def add(
    obj: dict[str, Any], source: Path, equipment: tuple[str, ...], revision: str, source_uri: Optional[str], force: bool
) -> None:
    """Ingest one manual (PDF/DOCX) for the given equipment and revision."""

    async def body(library: Any) -> Any:
        _gate(library, obj)
        return await library.add_manual(
            source, equipment=list(equipment), revision=revision, source_uri=source_uri, force=force
        )

    _run(obj, body)


@manuals.command("add-video")
@click.argument("url")
@click.option("--manual", "manual_id", required=True)
@click.option("--transcript", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--force", is_flag=True)
@click.pass_obj
def add_video(obj: dict[str, Any], url: str, manual_id: str, transcript: Optional[Path], force: bool) -> None:
    """Align a training video's transcript to a manual's steps."""

    async def body(library: Any) -> Any:
        _gate(library, obj)
        if transcript is not None:
            raw = await asyncio.to_thread(transcript.read_text, encoding="utf-8")
            data = json.loads(raw)
        else:
            data = None
        return await library.add_video(manual_id, uri=url, transcript=data, force=force)

    _run(obj, body)


@manuals.command("refresh")
@click.argument("manual_id")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--revision", required=True)
@click.pass_obj
def refresh(obj: dict[str, Any], manual_id: str, source: Path, revision: str) -> None:
    """Re-ingest a new manual revision; tips are re-linked and orphans reported."""

    async def body(library: Any) -> Any:
        _gate(library, obj)
        return await library.refresh(manual_id, source, revision=revision)

    _run(obj, body)


@manuals.command("verify")
@click.argument("manual_id")
@click.argument("procedure_id")
@click.pass_obj
def verify(obj: dict[str, Any], manual_id: str, procedure_id: str) -> None:
    """Mark a procedure verified (curator)."""

    async def body(library: Any) -> Any:
        context = _gate(library, obj)
        return await library.verify_procedure(manual_id, procedure_id, user=context.user_id)

    _run(obj, body)


@manuals.command("queue")
@click.option("--limit", default=50, show_default=True)
@click.pass_obj
def queue(obj: dict[str, Any], limit: int) -> None:
    """List the curator verification queue."""

    async def body(library: Any) -> Any:
        _gate(library, obj)
        return [entry.model_dump(mode="json") for entry in await library.catalog.verification_queue(limit=limit)]

    _run(obj, body)


@manuals.command("relink-tips")
@click.argument("manual_id")
@click.pass_obj
def relink_tips(obj: dict[str, Any], manual_id: str) -> None:
    """Re-run the idempotent tip re-link for one manual."""

    async def body(library: Any) -> Any:
        _gate(library, obj)
        card = await library.catalog.get(manual_id)
        if card is None:
            raise click.ClickException(f"manual {manual_id!r} not found")
        if library.graph_loader is None:
            raise click.ClickException("no graph loader configured for this deployment")
        return await library.graph_loader.publish(card)

    _run(obj, body)


@manuals.command("export")
@click.argument("manual_id")
@click.option("--out", "out_dir", type=click.Path(path_type=Path), required=True)
@click.option("--zip/--no-zip", "zip_bundle", default=True)
@click.option("--include-tips/--no-include-tips", default=True)
@click.pass_obj
def export(obj: dict[str, Any], manual_id: str, out_dir: Path, zip_bundle: bool, include_tips: bool) -> None:
    """Write an offline bundle for one manual revision (curator only)."""

    async def body(library: Any) -> Any:
        _gate(library, obj, curator_only=True)
        from parrot.knowledge.manuals.export import export_bundle

        card = await library.catalog.get(manual_id)
        if card is None:
            raise click.ClickException(f"manual {manual_id!r} not found")

        tips: tuple[Any, ...] = ()
        if include_tips and library.graph_loader is not None:
            from parrot.knowledge.manuals.models import Tip
            from parrot.knowledge.manuals.tips import TIP_COLLECTION

            ctx = library.graph_loader.context()
            docs = await library.graph_loader.graph_store.query_documents(ctx, TIP_COLLECTION, filters={"active": True})
            tip_fields = set(Tip.model_fields)
            tips = tuple(
                Tip.model_validate({key: value for key, value in doc.items() if key in tip_fields}) for doc in docs
            )

        return await export_bundle(
            card,
            file_manager=library.file_manager,
            out_dir=out_dir,
            include_tips=include_tips,
            zip_bundle=zip_bundle,
            tips=tips,
        )

    _run(obj, body)


@manuals.command("spike")
@click.argument("name", type=click.Choice(["figures", "media", "video", "tips"]))
@click.option("--corpus", type=click.Path(exists=True, path_type=Path), required=True)
@click.pass_obj
def spike(obj: dict[str, Any], name: str, corpus: Path) -> None:
    """Run one M0 spike and write its report under artifacts/logs/FEAT-601/.

    Note:
        The owner-supplied corpus carries an ``expected.json`` of hand counts (per
        ``corpus_dir_from_env``'s documented convention); ``tips``/``media`` additionally read
        their ``revisions``/``answer``+``channels`` from that same file so every spike kind
        shares one ``--corpus`` contract.
    """

    async def body(library: Any) -> Any:
        _gate(library, obj)
        from parrot.knowledge.manuals import spikes

        expected_path = corpus / "expected.json"
        expected = json.loads(await asyncio.to_thread(expected_path.read_text, encoding="utf-8"))
        if name == "figures":
            report = await spikes.spike_figures(corpus, adapter=library.adapter, expected=expected, library=library)
        elif name == "video":
            report = await spikes.spike_video(corpus, adapter=library.adapter, expected=expected)
        elif name == "tips":
            if library.graph_loader is None:
                raise click.ClickException("no graph loader configured for this deployment")
            rev_a, rev_b = (corpus / filename for filename in expected["tips"]["revisions"])
            report = await spikes.spike_tips(
                library.graph_loader.graph_store, library.catalog, revisions=(rev_a, rev_b)
            )
        else:
            from parrot.knowledge.manuals.models import ProcedureAnswer

            media_cfg = expected["media"]
            answer = ProcedureAnswer.model_validate(media_cfg["answer"])
            channels = media_cfg.get("channels", spikes.REQUIRED_MEDIA_CHANNELS)
            report = await spikes.spike_media(answer, channels=channels)

        return spikes.write_report(report)

    _run(obj, body)
