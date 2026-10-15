"""Framework-free ledger operations (FEAT-540 M3).

The ledger tools in :mod:`parrot.knowledge.wiki.tools` are thin adapters over the
``op_ledger_*`` coroutines defined here. Nothing in this module imports
the tool framework; the schemas mirror the ``wikitoolkit ledger`` CLI options one
for one so an agent filing through MCP cannot persist a kind or severity the CLI
would have rejected.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, get_args

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.actor import current_actor, scoped_actor
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity, IssueStatus
from parrot.knowledge.wiki.operations import OperationResult

if TYPE_CHECKING:
    from parrot.knowledge.wiki.ledger.service import LedgerService

logger = logging.getLogger(__name__)


class LedgerOpenInput(BaseModel):
    title: str = Field(..., description="One-line issue title")
    body: str = Field(..., description="What is wrong, where (file + symbol), why it matters, suggested fix")
    kind: IssueKind = Field(default="bug", description="Issue kind: bug|tech_debt|feature_gap|vulnerability")
    severity: IssueSeverity = Field(default="minor", description="Issue severity: critical|major|minor|low")
    discovered_from: str = Field(
        ..., min_length=1, description="Source: spec:<FEAT-ID>, task:<TASK-ID> or review:<TASK-ID>"
    )
    about: list[str] | None = Field(
        default=None, description="Affected symbols/files, repo-relative, e.g. sym:pkg/mod.py#Func"
    )


class LedgerReadyInput(BaseModel):
    kind: IssueKind | None = Field(
        default=None, description="Filter by issue kind: bug|tech_debt|feature_gap|vulnerability"
    )


class LedgerClaimInput(BaseModel):
    issue_id: str = Field(..., description="Issue ID to claim")
    actor: str | None = Field(
        default=None, description="Actor claiming the issue, e.g. agent:sdd-fix (default: the request actor)"
    )


class LedgerCloseInput(BaseModel):
    issue_id: str = Field(..., description="Issue ID to close")
    reason: str = Field(..., description="Reason for closing")
    actor: str | None = Field(
        default=None, description="Actor closing the issue, e.g. agent:sdd-fix (default: the request actor)"
    )
    resolved_by: str | None = Field(
        default=None, description="Evidence that resolved the issue, e.g. commit:<sha> or task:TASK-<NNN> (FEAT-572 S4)"
    )


class LedgerContextInput(BaseModel):
    file_paths: list[str] = Field(..., description="File paths to scope context to")
    max_tokens: int = Field(default=3000, description="Maximum tokens in response")


class LedgerListInput(BaseModel):
    """Schema mirrors `wikitoolkit ledger list` options one for one."""

    statuses: list[IssueStatus] | None = Field(default=None, description="Statuses to include (default open+claimed)")
    all_statuses: bool = Field(default=False, description="Include every status; overrides statuses")
    kind: IssueKind | None = Field(default=None, description="Filter by issue kind")
    severity: IssueSeverity | None = Field(default=None, description="Filter by severity")
    about_prefix: str | None = Field(
        default=None, description="Keep issues with an about entry starting with this prefix"
    )


class LedgerShowInput(BaseModel):
    """Schema mirrors `wikitoolkit ledger show` one for one."""

    issue_id: str = Field(..., description="Issue id, with or without the issue: prefix")
    include_history: bool = Field(default=True, description="Include the issue's event history")


def _failed(exc: Exception) -> OperationResult:
    """Build a failed :class:`OperationResult` from ``exc``."""
    return OperationResult(text=str(exc), is_error=True)


async def op_ledger_open(service: LedgerService, params: LedgerOpenInput, **context: Any) -> OperationResult:
    """ledger_open — open a new issue, attributed to the request actor."""
    try:
        issue_id = await service.open_issue(
            title=params.title,
            body=params.body,
            kind=params.kind,
            severity=params.severity,
            discovered_from=params.discovered_from,
            about=params.about,
            actor=current_actor(),
        )
        return OperationResult(data={"issue_id": issue_id})
    except Exception as exc:
        return _failed(exc)


async def op_ledger_ready(service: LedgerService, params: LedgerReadyInput, **context: Any) -> OperationResult:
    """ledger_ready — list ready (unclaimed) work, optionally filtered by kind."""
    try:
        # IssueKind is a typing.Literal: the schema already validated the
        # value, and calling the Literal would raise TypeError.
        issues = await service.ready_work(params.kind)
        return OperationResult(data={"issues": issues})
    except Exception as exc:
        return _failed(exc)


async def op_ledger_claim(service: LedgerService, params: LedgerClaimInput, **context: Any) -> OperationResult:
    """ledger_claim — claim an issue; the scoped actor wins over the argument."""
    try:
        success = await service.claim(params.issue_id, scoped_actor() or params.actor or current_actor())
        return OperationResult(data={"success": success})
    except Exception as exc:
        return _failed(exc)


async def op_ledger_close(service: LedgerService, params: LedgerCloseInput, **context: Any) -> OperationResult:
    """ledger_close — close an issue, carrying the evidence reference and actor through."""
    try:
        kwargs = {"resolved_by": params.resolved_by} if params.resolved_by is not None else {}
        success = await service.close_issue(
            params.issue_id, params.reason, scoped_actor() or params.actor or current_actor(), **kwargs
        )
        return OperationResult(data={"success": success})
    except Exception as exc:
        return _failed(exc)


async def op_ledger_context(service: LedgerService, params: LedgerContextInput, **context: Any) -> OperationResult:
    """ledger_context — ledger context scoped to ``params.file_paths``."""
    try:
        text = await service.get_context(params.file_paths, params.max_tokens)
        return OperationResult(data={"context": text})
    except Exception as exc:
        return _failed(exc)


async def op_ledger_list(service: LedgerService, params: LedgerListInput, **context: Any) -> OperationResult:
    """ledger_list — list issues by status/kind/severity/about prefix → data={"issues": [...]}."""
    try:
        statuses = get_args(IssueStatus) if params.all_statuses else (params.statuses or ("open", "claimed"))
        issues = await service.list_issues(
            statuses, kind=params.kind, severity=params.severity, about_prefix=params.about_prefix
        )
        return OperationResult(data={"issues": issues})
    except Exception as exc:
        return _failed(exc)


async def op_ledger_show(service: LedgerService, params: LedgerShowInput, **context: Any) -> OperationResult:
    """ledger_show — one issue with body (+ history) → data={"issue":…, "history":[…]}; is_error when unknown."""
    try:
        issue = await service.get_issue(params.issue_id)
        if issue is None:
            from parrot.knowledge.wiki.ledger.service import normalize_issue_id

            return OperationResult(text=f"Issue {normalize_issue_id(params.issue_id)} not found", is_error=True)
        history = await service.issue_history(params.issue_id) if params.include_history else []
        return OperationResult(data={"issue": issue, "history": history})
    except Exception as exc:
        return _failed(exc)
