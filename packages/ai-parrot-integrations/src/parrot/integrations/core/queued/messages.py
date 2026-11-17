"""Shared texts for queued commands and job controls."""

from datetime import datetime, timezone
from typing import Sequence

from .models import JobNotice, JobView, SubmitOutcome

JOB_COMMANDS: tuple[tuple[str, str], ...] = (
    ("jobs", "Your recent jobs"),
    ("job_status", "Show one of your jobs"),
    ("job_cancel", "Cancel one of your running jobs"),
)

_STATUS_ICONS = {
    "queued": "⏳",
    "running": "🔄",
    "completed": "✅",
    "failed": "❌",
    "cancelled": "🛑",
    "expired": "⌛",
}


def _format_duration(seconds: float) -> str:
    """Render a non-negative duration compactly."""

    total_seconds = max(0, round(seconds))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _bounded(value: str, limit: int = 500) -> str:
    """Bound stored or error text before displaying it."""

    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def _label_suffix(label: str) -> str:
    """Render an optional human-readable job label."""

    return f": {label}" if label else ""


def format_ack(outcome: SubmitOutcome) -> str:
    """Render acceptance, duplicate, or rejection with its job context."""

    if outcome.status == "rejected":
        return outcome.message
    if not outcome.job_id:
        return outcome.message
    if outcome.status == "duplicate":
        return f"🔁 Already running — job `{outcome.job_id}`{_label_suffix(outcome.label)}"
    return (
        f"⏳ Accepted — job `{outcome.job_id}`{_label_suffix(outcome.label)}.\n"
        f"I'll post the result here. Track it with /job_status {outcome.job_id}"
    )


def format_notice_header(notice: JobNotice) -> str:
    """Render terminal state, elapsed time, label, and job ID."""

    elapsed = _format_duration(notice.elapsed_s)
    label = f" — {notice.label}" if notice.label else ""
    if notice.status == "completed":
        return f"✅ Job `{notice.job_id}` finished in {elapsed}{label}"
    if notice.status == "timed_out":
        if notice.error and notice.error.startswith("timed out"):
            return f"⌛ Job `{notice.job_id}` {_bounded(notice.error)}{label}"
        return f"⌛ Job `{notice.job_id}` timed out after {elapsed}{label}"
    if notice.status == "cancelled":
        error = notice.error
        if error and error.startswith("interrupted — "):
            error = error.removeprefix("interrupted — ")
        detail = f" — {_bounded(error)}" if error else label
        return f"🛑 Job `{notice.job_id}` was interrupted{detail}"
    detail = f": {_bounded(notice.error)}" if notice.error else ""
    return f"❌ Job `{notice.job_id}` failed after {elapsed}{label}{detail}"


def format_job_view(view: JobView) -> str:
    """Render status, progress, timing, and bounded result details."""

    icon = _STATUS_ICONS[view.status]
    label = f" — {view.label}" if view.label else ""
    if view.status == "queued":
        headline = f"{icon} Job `{view.job_id}` queued (waiting for a slot){label}"
    elif view.status == "running":
        headline = f"{icon} Job `{view.job_id}` running{label}"
    else:
        headline = f"{icon} Job `{view.job_id}` {view.status}{label}"

    details: list[str] = []
    if view.progress:
        details.append(f"Progress: {_bounded(view.progress)}")
    if view.started_at is not None:
        end = view.completed_at or datetime.now(timezone.utc)
        started = view.started_at
        if started.tzinfo is None and end.tzinfo is not None:
            end = end.replace(tzinfo=None)
        elif started.tzinfo is not None and end.tzinfo is None:
            started = started.replace(tzinfo=None)
        details.append(f"Elapsed: {_format_duration((end - started).total_seconds())}")
    if view.error:
        details.append(f"Error: {_bounded(view.error)}")
    if view.summary:
        details.append(f"Result: {_bounded(view.summary)}")
    return "\n".join((headline, *details))


def format_job_list(views: Sequence[JobView]) -> str:
    """Render the requester's recent jobs in supplied order."""

    if not views:
        return "You have no recent jobs."
    lines = ["Your recent jobs:"]
    for view in views:
        label = f" · {view.label}" if view.label else ""
        lines.append(f"`{view.job_id}` {_STATUS_ICONS[view.status]} {view.status}{label}")
    return "\n".join(lines)


def format_cancel(result: str, job_id: str) -> str:
    """Render cancellation outcomes without revealing foreign job IDs."""

    if result == "cancelling":
        return f"Cancelling job `{job_id}`."
    if result == "finished":
        return f"Job `{job_id}` has already finished."
    if result == "not_on_this_worker":
        return f"Job `{job_id}` is running on another worker and cannot be cancelled from here."
    return f"No job `{job_id}` found for you."
