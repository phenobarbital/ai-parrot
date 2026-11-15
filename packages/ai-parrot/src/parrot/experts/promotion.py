"""Finding → inferred decision (FEAT-890 M10)."""

from __future__ import annotations

import logging
from pathlib import Path

from parrot.experts.contributions import Contribution, Finding, load_contribution
from parrot.knowledge.wiki.decisions.codec import candidate_decision_id
from parrot.knowledge.wiki.decisions.models import ADR_REVISION_CONFLICT, DecisionError, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository

logger = logging.getLogger(__name__)

#: ``prompt_version`` slot of the deterministic id; no model is involved, so it is fixed.
_PROMOTION_VERSION = 0


def _scope_id(contribution: Contribution) -> str:
    """Return the stable scope an expert's promoted findings are minted under."""
    return f"expert:{contribution.expert}:{contribution.doc_path}"


def _record_for(contribution: Contribution, finding: Finding) -> DecisionRecord:
    """Build the unreviewed, inferred decision that carries the finding's own statement.

    ``DecisionService.generate`` is deliberately NOT used: it asks a model to infer candidates from a
    target's evidence and so cannot carry a statement an expert already produced and a human confirmed.
    The record is saved exactly as ``generate`` saves a candidate (``origin="inferred"``,
    ``source_status="unknown"``, ``review_status="unreviewed"``) so it goes through the normal review.
    """
    observations = [f"Expert {contribution.expert} ({contribution.tier}) reported this on {contribution.doc_path}."]
    observations.extend(f"Cited by the expert: {item}" for item in finding.evidence)
    return DecisionRecord(
        decision_id=candidate_decision_id(
            _scope_id(contribution), contribution.doc_digest, _PROMOTION_VERSION, finding.statement
        ),
        title=f"{finding.section}: {finding.statement}"[:120],
        context=(
            f"Confirmed {finding.severity} finding from expert {contribution.expert} on "
            f"{contribution.doc_path}. Triage reason: {finding.reason or 'none given'}."
        ),
        decision=finding.statement,
        origin="inferred",
        source_status="unknown",
        review_status="unreviewed",
        observations=observations,
    )


def _open_repository(repo_root: Path) -> DecisionRepository:
    """Open the project's decision repository over its own wiki store, like the ``adr`` CLI does."""
    from parrot.knowledge.wiki.decisions.cli import _resolve_scoped_store  # noqa: PLC0415

    store, _root, config = _resolve_scoped_store(str(repo_root), None, writable=True)
    return DecisionRepository(store, max_records=config.decisions.max_records)


async def promote_finding(
    contribution_path: Path,
    finding_id: str,
    *,
    repo_root: Path,
    repository: DecisionRepository | None = None,
) -> str:
    """Persist a confirmed finding as an unreviewed inferred decision and return its id.

    The id is derived from the expert, document, document digest and statement, so promoting the same
    finding twice returns the existing decision untouched (a reviewed record is never overwritten).

    Args:
        contribution_path: Path to the contribution JSON file.
        finding_id: Id of the finding to promote.
        repo_root: Repository root, used to open the project's wiki store.
        repository: Decision repository to write to; opened from ``repo_root`` when omitted.

    Returns:
        The decision id of the inferred decision.

    Raises:
        ValueError: If the finding does not exist or is not confirmed.
        DecisionError: If the wiki cannot take the write (for example it was never built).
    """
    contribution = load_contribution(contribution_path)
    finding = next((item for item in contribution.findings if item.id == finding_id), None)
    if finding is None:
        raise ValueError(f"Finding {finding_id} not found in contribution")
    if finding.status != "confirm":
        raise ValueError(f"Finding {finding_id} is not confirmed (status: {finding.status})")

    record = _record_for(contribution, finding)
    repo = repository if repository is not None else _open_repository(repo_root)
    try:
        await repo.save(record, None)
    except DecisionError as exc:
        if exc.code != ADR_REVISION_CONFLICT:
            raise
        logger.info("finding %s was already promoted as %s", finding_id, record.decision_id)
    return record.decision_id
