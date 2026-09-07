"""What one flow execution looked like, as this plane records it.

Distinct from the crew execution rows ``PersistenceMixin._save_result``
writes, and deliberately so. Those are an observability trail with a
process-wide schema, written fire-and-forget through a backend the deployment
chooses. This is tenant state: it answers ``GET /runs/{run_id}``, it is what a
resume looks up, and it lives in ``saas.runs`` under the same ``tenant_id``
guard rails as every other table here.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(str, Enum):
    """Where a run is.

    ``FAILED`` means the flow itself failed — a node raised and the failure
    handler recorded it. A run that deliberately did nothing (a skipped
    triage, a blocked draft, an ineligible guest) is ``COMPLETED``: those are
    outcomes of the flow, not failures of it, and conflating them would make
    an error dashboard useless within a day.
    """

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SUSPENDED = "suspended"


class Run(BaseModel):
    """One flow execution.

    Attributes:
        run_id: Identifier minted at ingest, shared with the job record and
            used as the flow's checkpoint key.
        tenant_id: Owning tenant.
        flow: Which flow ran. One today; named so the table does not have to
            be migrated when there is a second.
        review_id: The review that started it.
        status: Where the run is.
        outcome: The flow's own terminal label (``replied``,
            ``coupon_delivered``, ``skipped``, ``blocked``, …), richer than
            :attr:`status` and what an operator actually reads.
        replied: Whether a public reply reached the platform.
        coupon_code: The coupon issued, when there was one.
        failed_node: Node that raised, for a failed run.
        error: That node's error.
        usage: Token usage per LLM role. Recorded from the first run because
            these calls are paid for with the tenant's own key and nothing
            else in the observability path carries a tenant dimension.
        nodes: Per-node execution summary — id, status, duration.
        duration_ms: Wall-clock time of the run.
        started_at: When the run was created.
        finished_at: When it reached a terminal state.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    run_id: str = ""
    tenant_id: str = ""
    flow: str = "community_manager"
    review_id: str = ""
    status: RunStatus = RunStatus.QUEUED
    outcome: str = ""
    replied: bool = False
    coupon_code: str = ""
    failed_node: str = ""
    error: str = ""
    usage: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    duration_ms: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Run":
        """Build a run from a database row.

        ``run_id`` and ``review_id`` come back as ``UUID`` objects and the two
        ``jsonb`` columns as either parsed structures or strings depending on
        the driver's codec registration, so both are normalised here rather
        than at each call site.

        Args:
            row: The database row.

        Returns:
            The typed run.
        """
        import json

        data = dict(row)
        for key in ("run_id", "review_id"):
            data[key] = str(data[key]) if data.get(key) is not None else ""
        for key, empty in (("usage", {}), ("nodes", [])):
            value = data.get(key)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    value = empty
            data[key] = value if value is not None else empty
        return cls(**data)

    def to_json(self) -> dict[str, Any]:
        """Render for the wire.

        Built field by field rather than with ``model_dump`` so a field added
        later cannot start appearing in a tenant-facing response on its own.
        """
        return {
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "flow": self.flow,
            "review_id": self.review_id,
            "status": self.status,
            "outcome": self.outcome,
            "replied": self.replied,
            "coupon_code": self.coupon_code,
            "failed_node": self.failed_node,
            "error": self.error,
            "usage": self.usage,
            "nodes": self.nodes,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": (
                self.finished_at.isoformat() if self.finished_at else None
            ),
        }


__all__ = ("Run", "RunStatus")
