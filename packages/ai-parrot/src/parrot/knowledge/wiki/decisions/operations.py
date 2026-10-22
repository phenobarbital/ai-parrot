"""Framework-free decision-plane operations (FEAT-540 M3)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.context import truncate_to_tokens
from parrot.knowledge.wiki.decisions.models import DecisionDossier, DecisionError
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
