"""Email digests — retained but shipped disabled (FEAT-481, spec Module
15, G9).

Ports the daily/weekly digest **pattern** from ``agents/fireflies_wiki.py``
(``email_daily_meeting_digest``/``email_weekly_insights``/``_run_digest``)
— never imports from or edits that file (additive-only, G11). Unlike
that agent (which reuses its own ``## Analysis`` sections), this digest
is built from **this subsystem's own compiled daily notes**
(``Diary/Daily Notes/``, spec Module 12) — never raw transcripts.

Gated by :data:`~parrot.flows.wiki_ingest.conf.FIREFLIES_WIKI_EMAIL_ENABLED`
(default ``False``, G9) — :func:`run_email_digest` never sends unless the
flag is explicitly enabled.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from .. import conf
from ..render.project import _parse_section


class DigestOutcome(BaseModel):
    """Result of one digest attempt.

    Attributes:
        status: ``"ok"`` (sent), ``"skipped"`` (disabled/no content/no
            recipients — never an error), ``"partial"`` (send attempted
            but the provider reported failure), or ``"error"``
            (unexpected exception — never raised, always captured here).
        emailed: Whether the email was actually sent successfully.
        days_covered: Number of daily notes folded into the digest.
        reason: Why nothing was sent, when ``emailed`` is ``False``.
    """

    status: Literal["ok", "skipped", "partial", "error"]
    emailed: bool = False
    days_covered: int = 0
    reason: str | None = None


def _daily_note_dates(window_days: int, *, today: date | None = None) -> list[date]:
    """The ``YYYY-MM-DD`` dates covered by a lookback window, newest last."""
    reference = today or datetime.now(UTC).date()
    return [reference - timedelta(days=offset) for offset in range(window_days - 1, -1, -1)]


async def build_digest_content(
    toolkit: Any,
    *,
    window_days: int,
    today: date | None = None,
) -> tuple[str, int]:
    """Build the digest body from compiled daily notes — never raw transcripts.

    Args:
        toolkit: This subsystem's own ``ObsidianToolkit`` (spec Module 4).
        window_days: Lookback window, in days.
        today: Reference date (defaults to today, UTC).

    Returns:
        ``(body, days_covered)`` — ``days_covered`` counts only the days
        that actually had a daily note.
    """
    sections: list[str] = []
    for day in _daily_note_dates(window_days, today=today):
        path = f"Diary/Daily Notes/{day.isoformat()}.md"
        try:
            note = await toolkit.read_note(path)
        except FileNotFoundError:
            continue
        body = note["content"].split("---", 2)[-1] if note["content"].startswith("---") else note["content"]
        summary = _parse_section(body, "Daily Summary")
        if summary and summary.lower() != "not established":
            sections.append(f"## {day.isoformat()}\n{summary}")

    return "\n\n".join(sections), len(sections)


async def run_email_digest(
    agent: Any,
    toolkit: Any,
    *,
    kind: Literal["daily", "weekly"],
    window_days: int,
    recipients: list[str],
    today: date | None = None,
) -> DigestOutcome:
    """Build and (maybe) send one digest. Never raises.

    Args:
        agent: The agent instance — needs ``send_email`` +
            ``notification_succeeded`` (``NotificationMixin``, already
            mixed into ``BasicAgent`` → ``Agent``).
        toolkit: This subsystem's own ``ObsidianToolkit``.
        kind: ``"daily"`` or ``"weekly"`` — only affects the subject line.
        window_days: Lookback window, in days.
        recipients: Email recipients (config-provided by the caller).
        today: Reference date (defaults to today, UTC).

    Returns:
        The :class:`DigestOutcome`. ``status == "skipped"`` (never an
        error) when the feature flag is off, there is no content, or no
        recipients are configured.
    """
    if not conf.FIREFLIES_WIKI_EMAIL_ENABLED:
        return DigestOutcome(status="skipped", reason="FIREFLIES_WIKI_EMAIL_ENABLED is false (G9 default)")

    try:
        body, days_covered = await build_digest_content(toolkit, window_days=window_days, today=today)
        if not body:
            return DigestOutcome(status="skipped", reason="no daily-note content in the window", days_covered=0)

        if not recipients:
            return DigestOutcome(status="skipped", reason="no recipients configured", days_covered=days_covered)

        subject_prefix = "Daily Meeting Digest" if kind == "daily" else "Weekly Meeting Insights"
        reference = today or datetime.now(UTC).date()
        subject = f"{subject_prefix} — {reference.isoformat()}"

        result = await agent.send_email(message=body, recipients=recipients, subject=subject)
        emailed = agent.notification_succeeded(result)
        if emailed:
            return DigestOutcome(status="ok", emailed=True, days_covered=days_covered)
        reason = (result or {}).get("error") or "email delivery failed"
        return DigestOutcome(status="partial", emailed=False, days_covered=days_covered, reason=reason)
    except Exception as exc:  # noqa: BLE001 — a scheduled digest job must not raise
        return DigestOutcome(status="error", reason=str(exc))
