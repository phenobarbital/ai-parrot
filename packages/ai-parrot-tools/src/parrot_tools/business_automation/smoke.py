"""SmokeCheck — scheduled canary mechanism (FEAT-453, Decision D4).

Every ``TemplatePlan`` in this feature is selector-bound to a third-party
site nobody controls. When that site's DOM changes, every operation breaks
at once, and the operator otherwise finds out only when a real write fails
half-way through. A scheduled canary that runs a READ-kind operation turns
that into an alert *before* any write is attempted.

Per Decision D4, the split follows the same public/private seam as the rest
of the engine: this *mechanism* is public and domain-neutral; the actual
canary plan it runs (e.g. a login + dashboard read for a specific site) is
private, out-of-repo (Deliverable X). Tests exercise the mechanism only,
against a mocked flow executor — never a real third-party site.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from pydantic import BaseModel

from .models import OperationKind
from .toolkit import BusinessAutomationToolkit

if TYPE_CHECKING:
    from parrot.human.channels.base import HumanChannel
    from parrot.scheduler.inprocess import InProcessScheduler

logger = logging.getLogger(__name__)

#: Default recipient label for smoke-check alerts.
_DEFAULT_RECIPIENT = "operator"


class SmokeCheck(BaseModel):
    """Scheduled canary: runs one READ-kind operation and alerts on failure.

    Attributes:
        operation: Must resolve to :class:`~parrot_tools.business_automation.models.OperationKind.READ`
            — enforced at :func:`register_smoke` *registration* time, not
            run time (Decision D4 / Key Constraint: a canary must never write).
        cron: 5-field cron expression forwarded to
            :meth:`~parrot.scheduler.inprocess.InProcessScheduler.add_cron`.
        alert_channel: Channel label carried for operator reference; the
            actual :class:`HumanChannel` instance is injected into
            :func:`register_smoke` separately (this field documents intent,
            e.g. for a runbook, rather than resolving a channel by name).
    """

    operation: str
    cron: str
    alert_channel: str = "telegram"


def register_smoke(
    scheduler: InProcessScheduler,
    toolkit: BusinessAutomationToolkit,
    check: SmokeCheck,
    *,
    channel: Optional[HumanChannel] = None,
    recipient: str = _DEFAULT_RECIPIENT,
) -> str:
    """Register a :class:`SmokeCheck` canary job on *scheduler*.

    Refuses at registration time — before any job is scheduled — to accept
    an operation that is not :class:`OperationKind.READ`. A canary that
    fires a SUBMIT or DRAFT operation on a schedule is not a smoke test, it
    is an unattended write, which is exactly what Decision D2 exists to
    prevent.

    Args:
        scheduler: The :class:`~parrot.scheduler.inprocess.InProcessScheduler`
            to register the job on.
        toolkit: The :class:`BusinessAutomationToolkit` whose operation
            registry is consulted (and whose ``run_operation`` executes the
            canary).
        check: The :class:`SmokeCheck` definition.
        channel: Optional :class:`HumanChannel` to alert on failure.
        recipient: Alert recipient label.

    Returns:
        The APScheduler job id.

    Raises:
        ValueError: If ``check.operation`` is unregistered, or is not
            ``OperationKind.READ``.
    """
    operation = toolkit._operations.get(check.operation)
    if operation is None:
        raise ValueError(f"SmokeCheck operation {check.operation!r} is not a registered " "BusinessOperation")
    if operation.kind != OperationKind.READ:
        raise ValueError(
            f"SmokeCheck operation {check.operation!r} is "
            f"OperationKind.{operation.kind.name}, not READ — a canary must "
            "never write"
        )

    async def _run() -> Dict[str, Any]:
        return await run_smoke_check(toolkit, check, channel=channel, recipient=recipient)

    return scheduler.add_cron(f"smoke-{check.operation}", check.cron, _run)


async def run_smoke_check(
    toolkit: BusinessAutomationToolkit,
    check: SmokeCheck,
    *,
    channel: Optional[HumanChannel] = None,
    recipient: str = _DEFAULT_RECIPIENT,
    poll_interval: float = 0.1,
    poll_timeout: float = 30.0,
) -> Dict[str, Any]:
    """Run *check* once and alert over *channel* on failure — silent on pass.

    Args:
        toolkit: The :class:`BusinessAutomationToolkit` to run the canary
            operation through.
        check: The :class:`SmokeCheck` to execute.
        channel: Optional :class:`HumanChannel` to alert on failure.
        recipient: Alert recipient label.
        poll_interval: Seconds between polls of the background run's status.
        poll_timeout: Maximum seconds to wait for the run to finish before
            treating it as a (alerted) timeout.

    Returns:
        The final run record (``{"status": ..., ...}``).
    """
    result = await toolkit.run_operation(check.operation, {})
    if result.get("status") != "started":
        error = result.get("error") or result.get("reason") or "unknown error"
        await _alert(channel, recipient, check.operation, "registration", error)
        return result

    run_id = result["run_id"]
    elapsed = 0.0
    record: Dict[str, Any] = toolkit._runs.get(run_id, {})
    while record.get("status") == "running" and elapsed < poll_timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        record = toolkit._runs.get(run_id, {})

    if record.get("status") != "done":
        node, error = _extract_failure_detail(record)
        await _alert(channel, recipient, check.operation, node, error)

    return record


def _extract_failure_detail(record: Dict[str, Any]) -> Tuple[str, str]:
    """Best-effort ``(failing_node, error_message)`` extraction from a run record."""
    if "error" in record:
        return "background-task", str(record["error"])

    flow_result = record.get("result")
    if flow_result is not None:
        node_results = getattr(flow_result, "node_results", None) or {}
        for node_id, node_result in node_results.items():
            success = (
                node_result.get("success") if isinstance(node_result, dict) else getattr(node_result, "success", None)
            )
            if success is False:
                error_message = (
                    node_result.get("error_message")
                    if isinstance(node_result, dict)
                    else getattr(node_result, "error_message", None)
                )
                return node_id, error_message or "node reported failure"
        return "unknown", getattr(flow_result, "error_message", None) or "flow reported failure"

    return "unknown", "smoke check timed out waiting for the run to complete"


async def _alert(
    channel: Optional[HumanChannel],
    recipient: str,
    operation: str,
    node: str,
    error: str,
) -> None:
    """Send an actionable failure alert — names the operation, node, and error."""
    message = f"SmokeCheck failed: operation={operation!r} node={node!r} error={error}"
    logger.error(message)
    if channel is not None:
        await channel.send_notification(recipient, message)
