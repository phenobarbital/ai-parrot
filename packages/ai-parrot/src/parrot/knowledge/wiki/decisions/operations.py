"""Framework-free decision-plane operations (FEAT-540 M3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.context import truncate_to_tokens
from parrot.knowledge.wiki.decisions.models import ADR_PATH_OUTSIDE_ROOT, DecisionDossier, DecisionError
from parrot.knowledge.wiki.decisions.render import DEFAULT_BUDGET_TOKENS, render_dossier_text
from parrot.knowledge.wiki.operations import OperationResult
from parrot.knowledge.wiki.store import estimate_tokens

_NAMESPACE_DESC = (
    "Federated namespace to read: a namespace name, or 'local' for this "
    "repo's own wiki. 'all' is not supported for decisions."
)


class DecisionsForSymbolInput(BaseModel):
    """Arguments for ``wiki_decisions_for_symbol`` / ``decision_for_symbol``."""

    symbol: str = Field(..., description="A sym:<rel>#<qualname> id, or an exact symbol name")
    include_history: bool = Field(default=False, description="Include rejected/deprecated/superseded records")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum hits across both groups")
    budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, ge=256, description="Estimated output budget")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class DecisionWhyInput(BaseModel):
    """Arguments for ``wiki_decision_why`` / ``decision_why``."""

    question: str = Field(..., description="Natural-language question, optionally naming a symbol")
    include_history: bool = Field(default=False, description="Include rejected/deprecated/superseded records")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum hits across both groups")
    budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, ge=256, description="Estimated output budget")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class DecisionGenerateInput(BaseModel):
    """Arguments for ``wiki_decision_generate``."""

    target: str = Field(..., description="One sym: id or one repository-relative file path")


def _dossier_result(dossier: DecisionDossier, budget_tokens: int) -> OperationResult:
    """Render a dossier without truncating its JSON tail."""
    tail = json.dumps(dossier.model_dump(mode="json"))
    text_budget = budget_tokens - estimate_tokens(tail)
    if text_budget <= 0:
        body, body_truncated = "", True
    else:
        body, body_truncated = truncate_to_tokens(render_dossier_text(dossier), text_budget)
    return OperationResult(
        text=f"{body}\n\n{tail}",
        data={"status": dossier.status, "truncated": dossier.truncated or body_truncated},
    )


def _error_result(exc: DecisionError) -> OperationResult:
    """Render a DecisionError with its stable code."""
    return OperationResult(text=f"{exc.code}: {exc.message}", is_error=True)


async def op_decisions_for_symbol(store: Any, params: DecisionsForSymbolInput, **context: Any) -> OperationResult:
    """Run ``wiki_decisions_for_symbol`` with unchanged error conversion."""
    factory = context["service_factory"]
    try:
        service = factory(params.namespace)
        dossier = await service.for_symbol(
            params.symbol,
            include_history=params.include_history,
            limit=params.limit,
            budget_tokens=params.budget_tokens,
        )
    except ValueError as exc:
        return OperationResult(text=str(exc), is_error=True)
    except DecisionError as exc:
        return _error_result(exc)
    return _dossier_result(dossier, params.budget_tokens)


async def op_decision_why(store: Any, params: DecisionWhyInput, **context: Any) -> OperationResult:
    """Run ``wiki_decision_why`` with unchanged error conversion."""
    factory = context["service_factory"]
    try:
        service = factory(params.namespace)
        dossier = await service.why(
            params.question,
            include_history=params.include_history,
            limit=params.limit,
            budget_tokens=params.budget_tokens,
        )
    except ValueError as exc:
        return OperationResult(text=str(exc), is_error=True)
    except DecisionError as exc:
        return _error_result(exc)
    return _dossier_result(dossier, params.budget_tokens)


async def op_decision_generate(store: Any, params: DecisionGenerateInput, **context: Any) -> OperationResult:
    """Run ``wiki_decision_generate`` with unchanged error conversion."""
    factory = context["service_factory"]
    try:
        service = factory(None)
        result = await service.generate(params.target)
    except (ValueError, DecisionError) as exc:
        return _error_result(exc) if isinstance(exc, DecisionError) else OperationResult(text=str(exc), is_error=True)
    return OperationResult(data=result.model_dump(mode="json"))


class SpecConsequencesInput(BaseModel):
    """Arguments for ``wiki_spec_consequences``."""

    spec_path: str = Field(..., description="Repository-relative path of the spec, e.g. sdd/specs/<slug>.spec.md")
    mode: Literal["check", "governing"] = Field(
        default="check", description="check: evaluate (read-only); governing: the governing-decisions dossier"
    )
    budget_tokens: int = Field(
        default=DEFAULT_BUDGET_TOKENS, ge=256, description="Estimated output budget for the dossier text"
    )


def _confined_spec_path(root: Path, spec_path: str) -> Path:
    """Return ``spec_path`` as a root-relative path, rejecting escapes.

    Raises:
        DecisionError: ``ADR_PATH_OUTSIDE_ROOT`` for absolute, ``..`` or symlink-escaping paths.
    """
    rel = Path(spec_path)
    if not spec_path or rel.is_absolute() or ".." in rel.parts:
        raise DecisionError(ADR_PATH_OUTSIDE_ROOT, f"spec path must be repository-relative: {spec_path!r}")
    resolved_root = root.resolve()
    if not (resolved_root / rel).resolve().is_relative_to(resolved_root):
        raise DecisionError(ADR_PATH_OUTSIDE_ROOT, f"spec path escapes the repository: {spec_path!r}")
    return rel


async def op_spec_consequences(store: Any, params: SpecConsequencesInput, **context: Any) -> OperationResult:
    """Evaluate a spec's declared decisions (read-only); never writes the spec.

    Args:
        store: The local wiki store, or None to resolve and require a built plane from ``root``.
        params: Validated arguments.
        **context: ``root`` (required) and ``config`` (``WikiProjectConfig``).

    Returns:
        Rendered Markdown text with the report (``check``) or dossier (``governing``) as ``data``.
    """
    from parrot.knowledge.wiki.decisions.spec_audit import open_consequence_service

    root = context.get("root")
    if root is None:
        return OperationResult(text="wiki_spec_consequences requires a local project root", is_error=True)
    try:
        rel = _confined_spec_path(Path(root), params.spec_path)
        service = open_consequence_service(Path(root), store=store, config=context.get("config"))
        from parrot.knowledge.wiki.decisions.consequences_render import (
            check_spec,
            render_consequences,
            render_governing,
        )

        if params.mode == "check":
            result = await check_spec(service, rel)
            report = result.report
            text = render_consequences(report) + f"\ncheck: {result.status}"
            return OperationResult(text=text, data={**report.model_dump(mode="json"), "check": result.status})
        dossier = await service.governing(rel, budget_tokens=params.budget_tokens)
        report = await service.evaluate(rel)
        text = render_governing(dossier, budget_tokens=params.budget_tokens, report=report)
        return OperationResult(text=text, data=dossier.model_dump(mode="json"))
    except DecisionError as exc:
        return _error_result(exc)
