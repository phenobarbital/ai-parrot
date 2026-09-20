"""``wikitoolkit adr`` — the maintainer surface for the decision plane (FEAT-578).

This module is the ONLY place a candidate can be accepted. Review is
deliberately absent from every agent-facing surface (spec §2, AC11).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click
from pydantic import ValidationError

from parrot.knowledge.wiki.decisions.models import (
    ADR_INVALID_ARGUMENT,
    CandidateEdit,
    DecisionError,
    ReviewRequest,
    as_json_dict,
)
from parrot.knowledge.wiki.decisions.render import render_dossier_text
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.review import render_export
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore

#: Exit codes (spec §2 "Errors and transport").
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INVALID_ARGUMENT = 2


def _emit_error(exc: DecisionError, as_json: bool) -> int:
    """Print a typed failure and return its exit code.

    Errors go to stderr so stdout stays protocol-safe for ``--json``
    consumers (spec §4 ``test_cli_mcp_parity``: "stdout remains
    protocol-safe").
    """
    payload = {"error": {"code": exc.code, "message": exc.message}}
    if exc.decision_id:
        payload["error"]["decision_id"] = exc.decision_id
    click.echo(json.dumps(payload) if as_json else f"{exc.code}: {exc.message}", err=True)
    return EXIT_INVALID_ARGUMENT if exc.code == ADR_INVALID_ARGUMENT else EXIT_FAILED


def _resolve_scoped_store(
    path_: str | None, namespace: str | None, *, writable: bool
) -> tuple[BaseWikiStore, Path | None, WikiProjectConfig]:
    """Resolve the project, open its store, and narrow it to ``namespace``.

    Uses the same ``_federate`` helper every other ``wiki`` CLI command uses
    (``cli.py:584``) rather than a bare, unfederated store — ``_require_built``
    alone never returns a ``FederatedWikiStore``, so narrowing it with the
    tool-side ``_scoped_store`` no-ops for ANY ``--ns`` value, including an
    unknown namespace name. ``namespace`` also defaults to ``"local"`` here
    (never passed through as ``None``), because ``_federate``/``_selected_
    namespaces`` treat an omitted selector as a broadcast across every
    federated namespace — correct for generic ``wiki query``, but not for
    decisions: spec §2 Module 6 requires lookup/why to target exactly one
    namespace per call, ``local`` by default.

    Returns:
        ``(store, root, config)``. ``root`` is ``None`` for a scoped-away
        (foreign) namespace — the caller should then skip anything that
        needs local evidence (freshness, generation, sync).

    Raises:
        DecisionError: ``ADR_INVALID_ARGUMENT`` when ``namespace == "all"``
            (unsupported for decisions in v1, for ANY command — spec §2
            Module 6), when an unknown namespace is requested, or when
            ``writable`` is set and the resolved scope has no local
            evidence root.
    """
    if namespace == "all":
        raise DecisionError(ADR_INVALID_ARGUMENT, "namespace='all' is not supported for decisions")

    # Deferred: `cli.py` imports this module to register the `adr` group,
    # and `structural.service` (imported by `_build_service` below) itself
    # imports `cli.py` — a module-level import back here would be circular
    # (mirrors `_structural_tool`'s own local import in `cli.py` for the
    # same reason).
    from parrot.knowledge.wiki.cli import _federate, _require_built, _resolve_project

    root, config = _resolve_project(path_)
    local = _require_built(root, config)
    effective_ns = namespace or "local"

    try:
        scoped_store = _federate(root, config, local, effective_ns)
    except click.ClickException as exc:
        raise DecisionError(ADR_INVALID_ARGUMENT, str(exc)) from exc

    effective_root: Path | None = root if effective_ns == "local" else None
    if writable and effective_root is None:
        raise DecisionError(
            ADR_INVALID_ARGUMENT,
            "this command requires a local project root; a foreign namespace has none",
        )
    return scoped_store, effective_root, config


def _build_service(path_: str | None, namespace: str | None, *, writable: bool) -> DecisionService:
    """Resolve the project and build a namespace-scoped service.

    Raises:
        DecisionError: ``ADR_INVALID_ARGUMENT`` when ``writable`` is set and
            the namespace is ``all`` or there is no local evidence root
            (spec §2 Module 6).
    """
    from parrot.knowledge.wiki.structural.service import StructuralService

    store, effective_root, config = _resolve_scoped_store(path_, namespace, writable=writable)
    structural = StructuralService(store, effective_root, config) if effective_root is not None else None
    return DecisionService(store, effective_root, config.decisions, structural=structural)


@click.group(name="adr")
def adr() -> None:
    """Architectural decisions: ingest ADRs, look them up, and review candidates."""


def _ns_option(func):
    """Shared ``--ns`` option for write commands (spec §2 Module 6: "write
    commands reject --ns all and missing local evidence roots")."""
    return click.option("--ns", "namespace", default=None, help="Namespace ('all' is not supported).")(func)


def _read_options(func):
    """Shared options for the two read commands (spec §2 Module 6)."""
    func = click.option("--include-history", is_flag=True, help="Include rejected/deprecated/superseded records.")(func)
    func = click.option("--limit", default=10, type=int, show_default=True, help="Maximum hits (1-50).")(func)
    func = click.option("--budget", default=3000, type=int, show_default=True, help="Token budget (min 256).")(func)
    func = click.option("--json", "as_json", is_flag=True, help="Emit the typed result as JSON.")(func)
    func = click.option("--ns", "namespace", default=None, help="Namespace to read ('all' is not supported).")(func)
    return func


def _run(coro):
    """Run an async decision-service call from a sync click command.

    Mirrors `cli.py`'s own `_run` (``asyncio.run``); defined locally rather
    than imported so this module never needs `cli.py` at module scope.
    """
    return asyncio.run(coro)


@adr.command("sync")
@click.argument("paths", nargs=-1)
@click.option("--path", "path_", default=None, help="Project root.")
@click.option("--json", "as_json", is_flag=True, help="Emit the SyncResult as JSON.")
@_ns_option
def adr_sync(paths: tuple[str, ...], path_: str | None, as_json: bool, namespace: str | None) -> None:
    """Refresh ADR records from source. Never invokes a model."""
    try:
        service = _build_service(path_, namespace, writable=True)
        result = _run(service.sync(list(paths) or None))
    except DecisionError as exc:
        raise SystemExit(_emit_error(exc, as_json)) from exc
    if as_json:
        click.echo(json.dumps(as_json_dict(result)))
    else:
        click.echo(
            f"sync: created={result.created} updated={result.updated} unchanged={result.unchanged} "
            f"missing={result.missing} unresolved={result.unresolved}"
        )
        for diagnostic in result.diagnostics:
            click.echo(f"  - {diagnostic.code}: {diagnostic.message}", err=True)
    if result.diagnostics:
        raise SystemExit(EXIT_FAILED)


@adr.command("lookup")
@click.argument("symbol")
@click.option("--path", "path_", default=None, help="Project root.")
@_read_options
def adr_lookup(symbol, path_, include_history, limit, budget, as_json, namespace) -> None:
    """Find the decisions that apply to SYMBOL, with citations."""
    try:
        service = _build_service(path_, namespace, writable=False)
        dossier = _run(service.for_symbol(symbol, include_history=include_history, limit=limit, budget_tokens=budget))
    except DecisionError as exc:
        raise SystemExit(_emit_error(exc, as_json)) from exc
    if as_json:
        click.echo(json.dumps(as_json_dict(dossier)))
    else:
        click.echo(render_dossier_text(dossier))


@adr.command("why")
@click.argument("question")
@click.option("--path", "path_", default=None, help="Project root.")
@_read_options
def adr_why(question, path_, include_history, limit, budget, as_json, namespace) -> None:
    """Answer a 'why' question with cited decision excerpts."""
    try:
        service = _build_service(path_, namespace, writable=False)
        dossier = _run(service.why(question, include_history=include_history, limit=limit, budget_tokens=budget))
    except DecisionError as exc:
        raise SystemExit(_emit_error(exc, as_json)) from exc
    if as_json:
        click.echo(json.dumps(as_json_dict(dossier)))
    else:
        click.echo(render_dossier_text(dossier))


@adr.command("generate")
@click.argument("target")
@click.option("--path", "path_", default=None, help="Project root.")
@click.option("--json", "as_json", is_flag=True, help="Emit the GenerationResult as JSON.")
@_ns_option
def adr_generate(target: str, path_: str | None, as_json: bool, namespace: str | None) -> None:
    """Generate labeled CANDIDATE rationale for TARGET (a sym: id or a file).

    Requires generation to be enabled and a model configured. Candidates are
    created unreviewed; accepting one is a separate, explicit `adr review`.
    """
    try:
        service = _build_service(path_, namespace, writable=True)
        result = _run(service.generate(target))
    except DecisionError as exc:
        raise SystemExit(_emit_error(exc, as_json)) from exc
    if as_json:
        click.echo(json.dumps(as_json_dict(result)))
    else:
        click.echo(f"Created: {', '.join(result.decision_ids) or '(none)'}")
        click.echo(f"Reused (unchanged evidence): {', '.join(result.reused) or '(none)'}")
        for diagnostic in result.diagnostics:
            click.echo(f"  - {diagnostic.code}: {diagnostic.message}", err=True)
    if result.diagnostics:
        raise SystemExit(EXIT_FAILED)


@adr.command("review")
@click.argument("decision_id")
@click.option("--action", required=True, type=click.Choice(["accept", "reject", "revise", "link"]))
@click.option("--expected-revision", required=True, type=int, help="Revision you read; guards concurrent edits.")
@click.option("--actor", required=True, help="Who is reviewing, e.g. 'human:jlara'. Attribution is mandatory.")
@click.option("--reason", default="", help="Why.")
@click.option(
    "--edit-file",
    "edit_file",
    default=None,
    type=click.Path(exists=True),
    help="CandidateEdit JSON; required for --action revise.",
)
@click.option(
    "--documented-id",
    "documented_id",
    default=None,
    help="Documented ADR to associate; required for --action link.",
)
@click.option("--path", "path_", default=None, help="Project root.")
@click.option("--json", "as_json", is_flag=True, help="Emit the updated record as JSON.")
@_ns_option
def adr_review(
    decision_id: str,
    action: str,
    expected_revision: int,
    actor: str,
    reason: str,
    edit_file: str | None,
    documented_id: str | None,
    path_: str | None,
    as_json: bool,
    namespace: str | None,
) -> None:
    """Accept, reject, revise, or link a decision record.

    Accepting a candidate records the team's agreement. It does NOT turn the
    candidate into documented history: the record stays inferred with an
    unknown source status, and no ADR file is written (Q3, AC11).
    """
    replacement: CandidateEdit | None = None
    if action == "revise":
        if edit_file is None:
            raise SystemExit(
                _emit_error(DecisionError(ADR_INVALID_ARGUMENT, "action='revise' requires --edit-file"), as_json)
            )
        try:
            payload = json.loads(Path(edit_file).read_text(encoding="utf-8"))
            replacement = CandidateEdit.model_validate(payload)
        except (OSError, ValueError) as exc:
            raise SystemExit(
                _emit_error(DecisionError(ADR_INVALID_ARGUMENT, f"malformed --edit-file: {exc}"), as_json)
            ) from exc

    documented_decision_id: str | None = None
    if action == "link":
        if documented_id is None:
            raise SystemExit(
                _emit_error(DecisionError(ADR_INVALID_ARGUMENT, "action='link' requires --documented-id"), as_json)
            )
        documented_decision_id = documented_id

    try:
        request = ReviewRequest(
            decision_id=decision_id,
            expected_revision=expected_revision,
            action=action,
            actor=actor,
            reason=reason,
            replacement=replacement,
            documented_decision_id=documented_decision_id,
        )
    except ValidationError as exc:
        raise SystemExit(_emit_error(DecisionError(ADR_INVALID_ARGUMENT, str(exc)), as_json)) from exc

    try:
        service = _build_service(path_, namespace, writable=True)
        record = _run(service.review(request))
    except DecisionError as exc:
        raise SystemExit(_emit_error(exc, as_json)) from exc

    if as_json:
        click.echo(json.dumps(as_json_dict(record)))
        return
    click.echo(f"{decision_id} -> revision {record.revision} ({record.review_status})")
    if record.origin == "inferred":
        click.echo(
            "Note: this record remains origin='inferred' with source_status='unknown'; "
            "accepting it records the team's agreement, it does not become documented history."
        )


@adr.command("export")
@click.argument("decision_id")
@click.option("--path", "path_", default=None, help="Project root.")
@_ns_option
def adr_export(decision_id: str, path_: str | None, namespace: str | None) -> None:
    """Print DECISION_ID as Markdown on stdout.

    Writing or committing this output is deliberately outside the feature —
    accepting a candidate in the wiki is sufficient (Q3).
    """
    try:
        store, _root, config = _resolve_scoped_store(path_, namespace, writable=False)
        repo = DecisionRepository(store, max_records=config.decisions.max_records)
        loaded = _run(repo.get(decision_id))
    except DecisionError as exc:
        raise SystemExit(_emit_error(exc, False)) from exc
    if loaded is None:
        raise SystemExit(
            _emit_error(
                DecisionError(ADR_INVALID_ARGUMENT, f"no such decision: {decision_id}", decision_id=decision_id),
                False,
            )
        )
    record, _content_hash = loaded
    click.echo(render_export(record))
