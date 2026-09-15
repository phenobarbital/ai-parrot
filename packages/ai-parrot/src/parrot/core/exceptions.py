# -*- coding: utf-8 -*-
"""Exception Definitions for Parrot Core.

This module contains custom exceptions used by the autonomous orchestrator
and core agent runtimes.
"""

from typing import Any, Optional
from parrot.exceptions import ParrotError


class HumanInteractionInterrupt(ParrotError):
    """Raised when an agent tool requests human interaction to continue.

    This interrupt is meant to be caught by the orchestrator so it can suspend
    the current execution state and propagate the prompt out to the user via
    a chat integration.
    """

    def __init__(
        self, prompt: str, interaction_id: Optional[str] = None, policy_id: Optional[str] = None, *args, **kwargs
    ):
        """Initialize the interrupt.

        Args:
            prompt: The text prompt the agent wants to send to the human.
            interaction_id: Optional UUID of the persisted interaction in parrot.human.
            policy_id: Optional ID of the escalation policy to follow.
        """
        super().__init__(prompt, *args, **kwargs)
        self.prompt = prompt
        self.interaction_id = interaction_id
        self.policy_id = policy_id
        self.state = None
        self.tool_call_id = None
        self.agent_name = None
        self.messages = None


class BudgetError(ParrotError):
    """Base for question-token-budget control errors (FEAT-550, spec §2 Data Models).

    Attributes:
        code: Stable machine-readable code (class attribute, overridden per subclass).
        operation_id: The ``budget_operation_id`` this error belongs to, if known.
        report: Optional serialized ``BudgetReport`` (a plain dict — no model import here).
    """

    code: str = "budget_error"

    def __init__(
        self, message: Any, *, operation_id: Optional[str] = None, report: Optional[dict] = None, **kwargs
    ) -> None:
        super().__init__(message, **kwargs)
        self.operation_id = operation_id
        self.report = report


class BudgetExhausted(BudgetError):
    """Ordinary admission denied / forced termination — translated to a partial result at the bot boundary."""

    code = "budget_exhausted"


class BudgetUnsupported(BudgetError):
    """Provider/method/strict-combination cannot honour a requested or inherited budget."""

    code = "budget_unsupported"


class BudgetScopeConflict(BudgetError):
    """A child call tried to disable or replace the active question policy."""

    code = "budget_scope_conflict"


class BudgetStateMissing(BudgetError):
    """Resume without a live ledger or an admissible snapshot."""

    code = "budget_state_missing"


class BudgetResumeConflict(BudgetError):
    """Suspension nonce already consumed (duplicate/concurrent resume)."""

    code = "budget_resume_conflict"


class BudgetSnapshotInvalid(BudgetError):
    """Snapshot identity/policy/nonce/floor check failed."""

    code = "budget_snapshot_invalid"


class BudgetAccountingError(BudgetError):
    """Contradictory settlement, malformed usage, or strict reservation violation."""

    code = "budget_accounting_error"


class BudgetRegistryFull(BudgetError):
    """Registry retention capacity exhausted; call ``release()`` first."""

    code = "budget_registry_full"
