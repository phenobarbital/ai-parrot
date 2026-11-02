"""usage_report — per-spec token/cost report over SpecUsageRecorder rows (FEAT-783 M8)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.operations import OperationResult

USAGE_REPORT_DESCRIPTION = "Report tokens and cost for one SDD feature, grouped by task, model or seat."


class UsageReportInput(BaseModel):
    """Input for usage_report."""

    feat_id: str = Field(..., pattern=r"^FEAT-\d+$")
    by: Literal["task", "model", "seat"] = "task"


async def op_usage_report(params: UsageReportInput, *, root: Any = None) -> OperationResult:
    """Build a structured per-feature usage report.

    Args:
        params: Feature identifier and grouping dimension.
        root: Optional explicit durable usage root.

    Returns:
        The report payload, or a transport-neutral error result.
    """
    from parrot import conf
    from parrot.flows.dev_loop.usage_report import build_spec_usage_report
    from parrot.observability.recorders.spec_usage import default_spec_usage_root, read_spec_usage

    try:
        usage_root = root if root is not None else default_spec_usage_root(conf.WORKTREE_BASE_PATH)
        rows = await asyncio.to_thread(read_spec_usage, usage_root, params.feat_id)
        report = build_spec_usage_report(rows, params.feat_id, by=params.by)
    except (OSError, TypeError, ValueError) as exc:
        return OperationResult(text=str(exc), is_error=True)
    return OperationResult(data=report.model_dump(mode="json"))
