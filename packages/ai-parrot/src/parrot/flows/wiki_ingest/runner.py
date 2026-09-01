"""§27 ingest orchestrator entry point (FEAT-481, spec Module 6).

Stub in Module 1 (TASK-2660): defines the pipeline's context/report
contracts (:class:`WikiIngestContext`, :class:`IngestReport`) and a stub
:func:`run_ingest`. The full ordered pipeline (fetch-gate → raw-bundle →
classify → contradictions → meeting-page → project-reconcile → entities →
concepts → daily → indexes → registry-mirror → log → §34 validation →
GraphIndex rebuild), processed chronologically oldest→newest and in
bounded chunks, is wired by a later task (spec Module 6).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class WikiIngestContext(BaseModel):
    """Parameters for one :func:`run_ingest` invocation.

    Attributes:
        limit: Per-run cap on the number of meetings processed (bounded
            chunks — spec Module 6). ``None`` means no cap.
        force_refetch: Bypass the fetch-gate cheap-skip path and always
            fetch + fingerprint already-known meeting ids.
        since: ISO date lower bound for a manual wide-window ingest.
        lookback_days: Alternative to ``since`` — how many days back to
            widen the fetch window (bounded by
            :data:`~parrot.flows.wiki_ingest.conf.WIKI_KB_MAX_CATCHUP_DAYS`).
    """

    limit: int | None = None
    force_refetch: bool = False
    since: str | None = None
    lookback_days: int | None = None


class IngestReport(BaseModel):
    """Result of one :func:`run_ingest` run (spec §35 change summary).

    Attributes:
        processed: Number of meetings compiled into the vault.
        skipped: Number of meetings skipped by the fetch gate (already
            processed / duplicate-skip).
        failed: Number of meetings whose §34 validation failed and were
            rolled back.
        errors: Human-readable error messages collected during the run.
    """

    processed: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)


async def run_ingest(ctx: WikiIngestContext) -> IngestReport:
    """Run the §27 ordered ingest pipeline.

    Stub in Module 1 — raises :class:`NotImplementedError` until the
    orchestrator (spec Module 6) wires the fetch-gate, raw-bundle,
    classification, and compilation nodes together.

    Args:
        ctx: The run's :class:`WikiIngestContext`.

    Returns:
        The resulting :class:`IngestReport`.

    Raises:
        NotImplementedError: Always, in Module 1.
    """
    raise NotImplementedError(
        "run_ingest is a Module 1 stub — wired to the full §27 pipeline "
        "by a later task (spec Module 6)."
    )
