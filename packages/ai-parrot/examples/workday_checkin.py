"""Demo: HITL Tool-Call Confirmation — workday_checkin (FEAT-235).

This example shows how to wire a tool that requires HITL confirmation
before execution, using ConfirmationGuard + ToolManager.

Usage pattern:
    1. Declare a tool with ``requires_confirmation=True`` in routing_meta.
    2. Create a ConfirmationGuard with an InMemoryConfirmationWindowStore and a
       HumanInteractionManager.
    3. Call ``tool_manager.set_confirmation_guard(guard)`` before executing.
    4. The ToolManager will pause and ask a human to approve/cancel/edit
       before running the tool.

Compare with: agents/expense_approval.py (HITL SUSPEND + escalation pattern).
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from parrot.auth.confirmation import (
    ConfirmationConfig,
    ConfirmationGuard,
    InMemoryConfirmationWindowStore,
)
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager


# ── Tool definition ────────────────────────────────────────────────────────────


class WorkdayCheckinTool(AbstractTool):
    """Register an employee check-in in the Workday HR system.

    This tool is marked ``requires_confirmation=True`` so the agent always
    asks the user to approve before registering a time entry.  An accidental
    call with wrong values would be irreversible, so the HITL gate is critical.
    """

    name = "workday_checkin"
    description = "Register an employee check-in in Workday."

    def __init__(self, **kwargs: Any) -> None:
        """Initialize with confirmation routing metadata."""
        super().__init__(
            routing_meta={
                "requires_confirmation": True,
                "confirm_template": (
                    "I am about to register a check-in for employee {employee_id} "
                    "at {time}. Do you confirm?"
                ),
                "confirm_window_seconds": 60,   # Within 60s, same call skips re-ask
                "allow_edit": True,             # Human can correct values before approving
            },
            **kwargs,
        )

    async def _execute(self, employee_id: int, time: str, **kwargs: Any) -> ToolResult:
        """Execute the check-in (only called after human approval).

        Args:
            employee_id: The employee's HR identifier.
            time: Check-in time (HH:MM format).

        Returns:
            ToolResult with check-in confirmation.
        """
        self.logger.info(
            "Check-in registered: employee=%s time=%s", employee_id, time
        )
        return ToolResult(
            success=True,
            status="success",
            result=f"Check-in registered for employee {employee_id} at {time}.",
        )


# ── Demo setup ─────────────────────────────────────────────────────────────────


async def build_tool_manager_with_confirmation(
    human_manager: Optional[Any] = None,
) -> ToolManager:
    """Build a ToolManager wired with a ConfirmationGuard.

    Args:
        human_manager: A HumanInteractionManager instance.  Pass None to run
            in fail-closed mode (useful for testing that the guard is active).

    Returns:
        Configured ToolManager.
    """
    mgr = ToolManager()

    # Register the confirming tool
    checkin_tool = WorkdayCheckinTool()
    mgr._tools[checkin_tool.name] = checkin_tool

    # Wire the confirmation guard
    store = InMemoryConfirmationWindowStore()
    config = ConfirmationConfig(
        approval_timeout=120.0,
        default_channel="telegram",
        max_edit_retries=1,
    )
    guard = ConfirmationGuard(
        store=store,
        human_manager=human_manager,
        config=config,
    )
    mgr.set_confirmation_guard(guard)

    return mgr


# ── Entry point ────────────────────────────────────────────────────────────────


async def main() -> None:
    """Run the demo with a fail-closed guard (no real HITL channel)."""
    print("WorkdayCheckin HITL Confirmation Demo (FEAT-235)")
    print("=" * 50)

    # Without a real HumanInteractionManager, the guard is fail-closed.
    mgr = await build_tool_manager_with_confirmation(human_manager=None)

    result = await mgr.execute_tool(
        "workday_checkin",
        {"employee_id": 42, "time": "09:00"},
    )
    print(f"Result: success={result.success} status={result.status}")
    if not result.success:
        print(f"Reason: {result.error}")
    print()
    print("To run with a real channel, pass a HumanInteractionManager to")
    print("build_tool_manager_with_confirmation(human_manager=<your manager>).")


if __name__ == "__main__":
    asyncio.run(main())
