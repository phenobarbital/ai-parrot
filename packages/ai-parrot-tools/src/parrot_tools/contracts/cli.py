"""Contracts operator CLI (FEAT-539 M11).

``python -m parrot_tools.contracts <command>`` — the operator surface for
ingestion, verification, party merges, the verification queue, search,
relation judgement, publication and answer retirement.

The CLI is a *thin* front-end: it builds tenant-bound services from
deployment configuration and an authenticated operator context, then calls
the same library/service methods every other path uses. It therefore
inherits the same policies — owner role plus explicit confirmation for
administrative actions, optimistic revisions for corrections — instead of
re-implementing them. It never deletes a source document, never sends
anything and imports no scheduler.

Confirmation comes from an explicit ``--confirm`` flag typed by the human
at the terminal, not from any argument a model could produce.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any, Callable, Optional, Sequence

from .retrieval import AuthorizationDenied, RequestContext
from .service import ConfirmationRequired, ServiceUnavailable

__all__ = ("COMMANDS", "build_parser", "run_command", "main")

logger = logging.getLogger(__name__)

#: Every operator command this CLI exposes.
COMMANDS: tuple[str, ...] = (
    "add",
    "add-folder",
    "refresh",
    "verify",
    "merge-parties",
    "queue",
    "search",
    "relate",
    "publish",
    "retire-answer",
)

#: Commands that change state and therefore require ``--confirm``.
CONFIRMING_COMMANDS: frozenset[str] = frozenset({"verify", "merge-parties", "retire-answer"})

#: Commands that change catalog, graph or relation state. Each is
#: authorized as an owner action before it runs — the CLI is a transport
#: like any other, not an exemption from the gate.
WRITE_COMMANDS: frozenset[str] = frozenset({"add", "add-folder", "refresh", "relate", "publish"})


def build_parser() -> argparse.ArgumentParser:
    """Build the operator argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m parrot_tools.contracts",
        description=(
            "Contracts operator commands. Administrative actions require "
            "--confirm; nothing is ever sent and no source document is deleted."
        ),
    )
    parser.add_argument("--tenant", help="Tenant id (defaults to the configured one).")
    parser.add_argument("--user", required=True, help="Authenticated operator id.")
    parser.add_argument(
        "--role",
        action="append",
        default=[],
        dest="roles",
        help="Role granted to the operator by the deployment (repeatable).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicit human confirmation for an administrative action.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")

    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Ingest one document.")
    add.add_argument("source")
    add.add_argument("--source-uri")
    add.add_argument("--force", action="store_true")

    folder = sub.add_parser("add-folder", help="Ingest a folder of documents.")
    folder.add_argument("folder")
    folder.add_argument("--recursive", action="store_true")
    folder.add_argument("--force", action="store_true")

    refresh = sub.add_parser("refresh", help="Re-card a contract from its source.")
    refresh.add_argument("contract_id")
    refresh.add_argument("--source")

    verify = sub.add_parser("verify", help="Verify or correct card fields.")
    verify.add_argument("contract_id")
    verify.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="Correct a field; repeat for several. Omit to verify the card.",
    )
    verify.add_argument("--expected-revision", type=int)

    merge = sub.add_parser("merge-parties", help="Merge two party identities.")
    merge.add_argument("keep_party_id")
    merge.add_argument("merge_party_id")

    queue = sub.add_parser("queue", help="Show the verification queue.")
    queue.add_argument("--limit", type=int, default=20)

    search = sub.add_parser("search", help="Search the catalog.")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=8)

    relate = sub.add_parser("relate", help="Judge contract relations.")
    relate.add_argument("contract_ids", nargs="*")
    relate.add_argument("--force", action="store_true")

    publish = sub.add_parser("publish", help="Publish the catalog to the graph.")
    publish.add_argument("--contract-id")

    retire = sub.add_parser("retire-answer", help="Retire an audited answer.")
    retire.add_argument("answer_id")
    retire.add_argument("--reason", required=True)

    return parser


def _parse_fields(assignments: Sequence[str]) -> Optional[dict[str, Any]]:
    """Parse ``PATH=VALUE`` assignments into a correction map.

    ``PATH=`` (empty value) confirms the current value instead of
    correcting it.
    """
    if not assignments:
        return None
    fields: dict[str, Any] = {}
    for assignment in assignments:
        path, _, raw = assignment.partition("=")
        path = path.strip()
        if not path:
            raise ValueError(f"invalid --set {assignment!r}: missing field path")
        value: Any = raw.strip()
        if value == "":
            value = None
        elif value.lower() in ("true", "false"):
            value = value.lower() == "true"
        elif value.isdigit():
            value = int(value)
        fields[path] = value
    return fields


def _context(args: argparse.Namespace, tenant_id: str) -> RequestContext:
    """Build the trusted operator context from CLI arguments.

    Roles come from the deployment's invocation, and ``confirmed`` from the
    explicit ``--confirm`` flag — never from anything a model produced.
    """
    return RequestContext(
        user_id=args.user,
        roles=tuple(args.roles),
        tenant_id=args.tenant or tenant_id,
        employee_id=args.user,
        confirmed=bool(args.confirm),
    )


async def run_command(
    args: argparse.Namespace,
    *,
    library: Any,
    service: Any,
    graph_loader: Any = None,
    temporal: Any = None,
    tenant_context: Any = None,
) -> tuple[int, dict[str, Any]]:
    """Dispatch one command against real, tenant-bound services.

    Args:
        args: Parsed arguments.
        library: The contract library.
        service: The shared answer service.
        graph_loader: Optional graph loader for ``publish``.
        temporal: Optional temporal publisher for ``publish``.
        tenant_context: Tenant context for the temporal drain.

    Returns:
        ``(exit_code, payload)`` — a nonzero code for any refusal or
        failure, and a bounded payload for printing.
    """
    context = _context(args, library.catalog.tenant_id)
    command = args.command

    if command in CONFIRMING_COMMANDS and not context.confirmed:
        return 2, {"error": f"{command} is an administrative action; pass --confirm to proceed"}

    try:
        # Default deny, on the same gate every other surface uses. The
        # write commands mutate the catalog, the graph projection or the
        # relation judgements, so they require the owner role. `verify`,
        # `merge-parties` and `retire-answer` are authorized inside the
        # service itself and are deliberately not gated twice here.
        if command in WRITE_COMMANDS:
            service.retrieval.authorize(context, pattern=command, owner_only=True)

        if command == "add":
            result = await library.add_contract(args.source, source_uri=args.source_uri, force=args.force)
            return (0 if result.outcome != "error" else 1), {
                "outcome": result.outcome,
                "contract_id": result.card.contract_id if result.card else None,
                "reason": result.reason,
                "publication_state": result.publication_state,
            }

        if command == "add-folder":
            report = await library.add_folder(args.folder, recursive=args.recursive, force=args.force)
            return (0 if report.errors == 0 else 1), {
                "summary": report.summary(),
                "items": [item.model_dump(mode="json") for item in report.items][:200],
            }

        if command == "refresh":
            result = await library.refresh_card(args.contract_id, source=args.source)
            return (0 if result.outcome != "error" else 1), {
                "outcome": result.outcome,
                "contract_id": result.card.contract_id if result.card else None,
                "reason": result.reason,
            }

        if command == "verify":
            outcome = await service.verify_card(
                args.contract_id,
                _parse_fields(args.set),
                request_context=context,
                expected_revision=args.expected_revision,
            )
            return 0, {
                "contract_id": args.contract_id,
                "verified": list(outcome.verified),
                "corrected": list(outcome.corrected),
                "blockers": list(outcome.blockers),
                "card_verified": outcome.card_verified,
            }

        if command == "merge-parties":
            merged = await service.merge_parties(args.keep_party_id, args.merge_party_id, request_context=context)
            return 0, {"merged": merged.model_dump(mode="json")}

        if command == "queue":
            service.retrieval.authorize(context)
            entries = await library.catalog.verification_queue(limit=args.limit)
            return 0, {
                "queue": [
                    {
                        "contract_id": entry.card.contract_id,
                        "title": entry.card.title,
                        "reason": entry.reason,
                        "fields": entry.fields,
                    }
                    for entry in entries
                ]
            }

        if command == "search":
            service.retrieval.authorize(context)
            hits = await library.catalog.search(args.query, top_k=args.top_k)
            return 0, {
                "results": [
                    {"contract_id": hit.card.contract_id, "title": hit.card.title, "rank": hit.rank} for hit in hits
                ]
            }

        if command == "relate":
            report = await library.relate_contracts(args.contract_ids or None, force=args.force)
            return (0 if not report.errors else 1), {
                "calls": report.calls,
                "judged": report.judged,
                "none_outcomes": report.none_outcomes,
                "rejected": report.rejected,
                "invalidated": report.invalidated,
                "errors": report.errors,
            }

        if command == "publish":
            payload: dict[str, Any] = {}
            code = 0
            if graph_loader is not None:
                if args.contract_id:
                    card = await library.catalog.get(args.contract_id)
                    if card is None:
                        return 1, {"error": f"unknown contract {args.contract_id!r}"}
                    report = await graph_loader.publish(card)
                else:
                    report = await graph_loader.publish_all()
                payload["ontology"] = {
                    "published": report.published,
                    "contracts": report.contracts,
                    "errors": report.errors,
                    "missing_nodes": report.missing_nodes,
                    "missing_edges": report.missing_edges,
                }
                if not report.published:
                    code = 1
            if temporal is not None:
                drain = await temporal.drain(tenant_context)
                payload["temporal"] = {
                    "published": drain.published,
                    "recovered": drain.recovered,
                    "failed": drain.failed,
                    "errors": drain.errors,
                }
                if drain.failed or drain.errors or drain.unavailable:
                    # A partially failed target is not a success.
                    code = 1
            if not payload:
                return 1, {"error": "no publication target configured"}
            return code, payload

        if command == "retire-answer":
            record = await service.retire_answer(args.answer_id, request_context=context, reason=args.reason)
            return 0, {
                "answer_id": record.answer_id,
                "retired_by": record.retired_by,
                "reason": record.retirement_reason,
            }

    except AuthorizationDenied as exc:
        return 3, {"error": f"denied: {exc.reason}"}
    except ConfirmationRequired as exc:
        return 2, {"error": str(exc)}
    except ServiceUnavailable as exc:
        return 4, {"error": str(exc)}
    except (ValueError, KeyError) as exc:
        return 2, {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - operators get an actionable message
        logger.exception("Command %s failed", command)
        return 1, {"error": f"{type(exc).__name__}: {exc}"}

    return 2, {"error": f"unknown command {command!r}"}  # pragma: no cover


def render(payload: dict[str, Any], *, as_json: bool) -> str:
    """Render a bounded, human-readable (or JSON) result."""
    if as_json:
        return json.dumps(payload, indent=2, sort_keys=True, default=str)
    lines = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            lines.append(f"{key}: {json.dumps(value, default=str)[:2000]}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    factory: Optional[Callable[[argparse.Namespace], dict[str, Any]]] = None,
    stream: Any = None,
) -> int:
    """CLI entrypoint.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).
        factory: Builds the tenant-bound services from parsed arguments.
            Required — deployment configuration lives outside this module.
        stream: Output stream (defaults to stdout).

    Returns:
        The process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    out = stream or sys.stdout
    if factory is None:
        print(
            "No service factory configured. Wire parrot_tools.contracts.cli.main(" "factory=...) in your deployment.",
            file=out,
        )
        return 2
    services = factory(args)
    code, payload = asyncio.run(run_command(args, **services))
    print(render(payload, as_json=args.json), file=out)
    return code
