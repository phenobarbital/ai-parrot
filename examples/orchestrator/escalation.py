"""Tier-1 and Tier-2 escalation tools for the helpdesk orchestrator.

Both tiers create an incident record and send an email — to *different*
recipients. The example uses a dry-run by default so it stays runnable
without SMTP configured; set ``HELPDESK_EMAIL=real`` (and the
async-notify env vars) to send actual emails through
:class:`parrot.notifications.NotificationMixin`.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parrot.tools import tool

from examples.orchestrator.rules import TIER1_EMAIL, TIER2_EMAIL


_LOG = logging.getLogger("orchestrator.escalation")
_HERE = Path(__file__).parent
_LOG_DIR = _HERE / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_TICKETS_CSV = _LOG_DIR / "tickets.csv"
_AUDIT_JSONL = _LOG_DIR / f"audit_{time.strftime('%Y%m%d')}.jsonl"


def _new_ticket_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _append_ticket_row(row: dict[str, Any]) -> None:
    header = ["ticket_id", "tier", "priority", "category", "employee_id",
              "summary", "impact", "created_at"]
    write_header = not _TICKETS_CSV.exists()
    with _TICKETS_CSV.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in header})


def _append_audit(event: dict[str, Any]) -> None:
    event = {**event, "ts": datetime.now(timezone.utc).isoformat()}
    with _AUDIT_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


async def _send_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    importance: str = "normal",
) -> str:
    """Send an email, dry-run by default.

    When ``HELPDESK_EMAIL=real`` is set, the function delegates to
    :func:`parrot.notifications.NotificationMixin.send_email` via a
    throwaway carrier object. Otherwise it logs the message and
    appends it to the audit jsonl.
    """
    mode = os.getenv("HELPDESK_EMAIL", "dry-run").lower()
    if mode == "real":
        try:
            from parrot.notifications import NotificationMixin

            carrier = type("_Mailer", (NotificationMixin,), {})()
            result = await carrier.send_email(
                message=body,
                recipients=[recipient],
                subject=subject,
                importance=importance,
            )
            _LOG.info("Real email sent to %s (subject=%s)", recipient, subject)
            return f"email-sent:{result.get('id', 'ok')}"
        except Exception as exc:  # pragma: no cover - depends on infra
            _LOG.warning(
                "Real email failed (%s); falling back to dry-run.", exc
            )

    # Dry-run path — always reached when HELPDESK_EMAIL != "real" or when
    # the real backend errored out.
    _LOG.info(
        "📧 DRY-RUN EMAIL to %s | importance=%s | subject=%s",
        recipient, importance, subject,
    )
    _LOG.info("---- body ----\n%s\n---- /body ----", body)
    _append_audit({
        "event": "email_dry_run",
        "recipient": recipient,
        "subject": subject,
        "importance": importance,
        "body_preview": body[:200],
    })
    return f"email-dryrun:{recipient}"


def _create_jira_ticket(
    *,
    summary: str,
    employee_id: str,
    category: str,
    tier: str,
    priority: str,
    impact: str = "",
) -> str:
    """Create the ticket. Production wiring would call the Jira REST API
    (the framework's JiraConnectTool is the OAuth bridge). For the
    example we always log to CSV so the demo is reproducible.
    """
    ticket_id = _new_ticket_id("INC")
    _append_ticket_row({
        "ticket_id": ticket_id,
        "tier": tier,
        "priority": priority,
        "category": category,
        "employee_id": employee_id,
        "summary": summary,
        "impact": impact,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _append_audit({
        "event": "ticket_created",
        "ticket_id": ticket_id,
        "tier": tier,
        "priority": priority,
        "category": category,
        "employee_id": employee_id,
        "summary": summary,
        "impact": impact,
    })
    return ticket_id


@tool
async def escalate_tier1(
    summary: str,
    employee_id: str,
    category: str,
) -> str:
    """Open a Tier-1 incident and email the team manager.

    Use for single-user productivity issues: account access, password
    reset failures, software bugs, misconfigured workstations.

    Args:
        summary: One-sentence description of the issue.
        employee_id: Employee identifier (8-digit badge number).
        category: Short label, e.g. 'access', 'workstation', 'email'.

    Returns:
        A confirmation string with the ticket id and recipient.
    """
    ticket_id = _create_jira_ticket(
        summary=summary,
        employee_id=employee_id,
        category=category,
        tier="tier-1",
        priority="normal",
    )
    body = (
        f"A Tier-1 ticket was opened.\n\n"
        f"Ticket: {ticket_id}\n"
        f"Category: {category}\n"
        f"Employee ID: {employee_id}\n"
        f"Summary: {summary}\n"
    )
    email_result = await _send_email(
        recipient=TIER1_EMAIL,
        subject=f"[Tier-1] {ticket_id} — {category}",
        body=body,
        importance="normal",
    )
    return (
        f"Tier-1 incident {ticket_id} created. Team manager "
        f"({TIER1_EMAIL}) notified ({email_result})."
    )


@tool
async def escalate_tier2(
    summary: str,
    employee_id: str,
    category: str,
    impact: str,
) -> str:
    """Open a Sev-1 incident and page the on-call director.

    Use for outages, security incidents, data loss, or anything with
    direct customer impact. The email goes to a different distribution
    list than Tier-1 and is flagged URGENT.

    Args:
        summary: One-sentence description of the incident.
        employee_id: Reporter's employee identifier.
        category: Short label, e.g. 'outage', 'security', 'data-loss'.
        impact: Business impact — who/what is affected, magnitude.

    Returns:
        A confirmation string with the ticket id and recipient.
    """
    ticket_id = _create_jira_ticket(
        summary=summary,
        employee_id=employee_id,
        category=category,
        tier="tier-2",
        priority="sev-1",
        impact=impact,
    )
    body = (
        f"!! TIER-2 SEV-1 INCIDENT !!\n\n"
        f"Ticket: {ticket_id}\n"
        f"Category: {category}\n"
        f"Reporter: {employee_id}\n"
        f"Summary: {summary}\n"
        f"Impact: {impact}\n\n"
        f"On-call director paged. Please acknowledge in the incident "
        f"channel within 5 minutes.\n"
    )
    email_result = await _send_email(
        recipient=TIER2_EMAIL,
        subject=f"[Tier-2 — URGENT] {ticket_id} — {category}",
        body=body,
        importance="high",
    )
    return (
        f"Tier-2 Sev-1 incident {ticket_id} created. On-call director "
        f"({TIER2_EMAIL}) paged ({email_result})."
    )


def reset_logs() -> None:
    """Wipe the example's ticket CSV and audit log."""
    if _TICKETS_CSV.exists():
        _TICKETS_CSV.unlink()
    if _AUDIT_JSONL.exists():
        _AUDIT_JSONL.unlink()


def read_tickets() -> list[dict[str, str]]:
    """Read tickets created so far. Useful for the verification harness."""
    if not _TICKETS_CSV.exists():
        return []
    with _TICKETS_CSV.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
