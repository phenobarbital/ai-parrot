"""``wikitoolkit spec`` / ``wikitoolkit decisions`` decision-audit CLI."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

_NOT_CONFIGURED = "decision audit not configured in this repository"


def _root(path_: str | None) -> Path:
    """Resolve a project root from the command option.

    Args:
        path_: Optional project-root option value.

    Returns:
        Absolute project root.
    """
    return Path(path_ or ".").resolve()


def _service(root: Path):
    """Open the local consequence service on demand.

    Args:
        root: Repository root.

    Returns:
        The configured consequence service.
    """
    from parrot.knowledge.wiki.decisions.spec_audit import open_consequence_service

    return open_consequence_service(root)


def _fail(exc: Exception, as_json: bool) -> None:
    """Emit an operational error without corrupting JSON stdout.

    Args:
        exc: Operational exception to render.
        as_json: Whether an error JSON envelope was requested.
    """
    code = getattr(exc, "code", type(exc).__name__)
    message = getattr(exc, "message", str(exc))
    payload = {"error": {"code": code, "message": message}}
    click.echo(json.dumps(payload) if as_json else f"{code}: {message}", err=True)
    sys.exit(3)


def _emit(value: object, as_json: bool, summary: str) -> None:
    """Emit a typed CLI result in JSON or concise human form.

    Args:
        value: Pydantic-compatible result object.
        as_json: Whether JSON output was requested.
        summary: Human-readable output for the result.
    """
    if as_json:
        click.echo(json.dumps(value.model_dump(mode="json")))
    else:
        click.echo(summary)


@click.group(name="spec")
def spec() -> None:
    """Decision audit for SDD specs: governing decisions and consequences."""


@spec.command("governing")
@click.argument("spec_path")
@click.option("--path", "path_", default=None, help="Project root (default: current directory).")
@click.option("--budget", default=3000, type=int, show_default=True, help="Token budget for the dossier text.")
@click.option("--json", "as_json", is_flag=True, help="Emit the dossier as JSON.")
def spec_governing(spec_path: str, path_: str | None, budget: int, as_json: bool) -> None:
    """Render the governing-decisions dossier to stdout without writing it."""
    from parrot.knowledge.wiki.decisions.consequences_render import render_governing
    from parrot.knowledge.wiki.decisions.models import DecisionError
    from parrot.knowledge.wiki.decisions.spec_audit import is_configured

    root = _root(path_)
    if not is_configured(root):
        click.echo(_NOT_CONFIGURED)
        return
    try:
        service = _service(root)
        report = asyncio.run(service.evaluate(Path(spec_path)))
        dossier = asyncio.run(service.governing(Path(spec_path), budget_tokens=budget))
    except DecisionError as exc:
        _fail(exc, as_json)
        return
    if as_json:
        click.echo(json.dumps(dossier.model_dump(mode="json")))
    else:
        click.echo(render_governing(dossier, budget_tokens=budget, report=report), nl=False)


@spec.group("consequences")
def consequences() -> None:
    """Render or check the generated governing-decision sections."""


@consequences.command("render")
@click.argument("spec_path")
@click.option("--path", "path_", default=None, help="Project root (default: current directory).")
@click.option("--budget", default=3000, type=int, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def consequences_render(spec_path: str, path_: str | None, budget: int, as_json: bool) -> None:
    """Write generated sections into a spec and exit with its report code."""
    from parrot.knowledge.wiki.decisions.consequences_render import _render_skipped, render_spec
    from parrot.knowledge.wiki.decisions.models import DecisionError
    from parrot.knowledge.wiki.decisions.spec_audit import is_configured

    root = _root(path_)
    if not is_configured(root):
        path = root / spec_path
        try:
            text = path.read_text(encoding="utf-8")
            rendered = _render_skipped(text)
            if rendered != text:
                path.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            _fail(exc, as_json)
            return
        click.echo(_NOT_CONFIGURED)
        return
    try:
        report = asyncio.run(render_spec(_service(root), Path(spec_path), budget_tokens=budget))
    except DecisionError as exc:
        _fail(exc, as_json)
        return
    _emit(report, as_json, f"consequences: {report.status} (exit {report.exit_code})")
    if report.exit_code:
        raise SystemExit(report.exit_code)


@consequences.command("check")
@click.argument("spec_path")
@click.option("--path", "path_", default=None, help="Project root (default: current directory).")
@click.option("--json", "as_json", is_flag=True)
def consequences_check(spec_path: str, path_: str | None, as_json: bool) -> None:
    """Check generated sections using the decision-audit exit matrix."""
    from parrot.knowledge.wiki.decisions.consequences_render import check_spec
    from parrot.knowledge.wiki.decisions.models import DecisionError
    from parrot.knowledge.wiki.decisions.spec_audit import is_configured

    root = _root(path_)
    if not is_configured(root):
        click.echo(_NOT_CONFIGURED)
        return
    try:
        result = asyncio.run(check_spec(_service(root), Path(spec_path)))
    except DecisionError as exc:
        _fail(exc, as_json)
        return
    if as_json:
        click.echo(json.dumps({**result.report.model_dump(mode="json"), "check": result.status}))
    else:
        click.echo(f"consequences: {result.report.status}; check: {result.status} (exit {result.report.exit_code})")
    exit_code = result.report.exit_code if result.status == "current" else max(result.report.exit_code, 3)
    if exit_code:
        raise SystemExit(exit_code)


@click.group(name="decisions")
def decisions() -> None:
    """Publish approved decision batches into the decision plane."""


@decisions.command("publish")
@click.option("--batch", "batch_id", required=True, help="Approval batch id from sdd/decisions/approvals.jsonl.")
@click.option("--path", "path_", default=None, help="Project root (default: current directory).")
@click.option("--json", "as_json", is_flag=True)
def decisions_publish(batch_id: str, path_: str | None, as_json: bool) -> None:
    """Publish one approved batch all-or-nothing."""
    from parrot.knowledge.wiki.decisions.approvals import ApprovalManifest
    from parrot.knowledge.wiki.decisions.models import DecisionError
    from parrot.knowledge.wiki.decisions.publish import BatchPublisher
    from parrot.knowledge.wiki.decisions.spec_audit import approvals_path

    root = _root(path_)
    try:
        service = _service(root)
        approvals = ApprovalManifest.load(approvals_path(root))
        publisher = BatchPublisher(service.store, root, service.config, service, approvals, service.adapter)
        result = asyncio.run(publisher.publish(batch_id))
    except DecisionError as exc:
        _fail(exc, as_json)
        return
    _emit(result, as_json, f"publish: {result.status} ({result.batch_id})")
    if result.status == "refused":
        raise SystemExit(1)
