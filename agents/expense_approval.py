"""ExpenseApprovalAgent — end-to-end Human-in-the-Loop (HITL) demo.

A drop-in :class:`parrot.bots.Agent` that approves expense / refund requests
through a **tiered escalation policy** managed by
:class:`parrot.human.manager.HumanInteractionManager`:

- **Tier 1 — Microsoft Teams approval (interactive).** The agent sends a
  proactive Adaptive Card (✅ Approve / ❌ Reject / ⏫ Escalate) to a manager
  on Teams and waits for the decision.
- **Tier 2 — Email escalation (one-way NOTIFY).** When Tier 1 **times out**
  *or* the approver taps **Escalate**, a notification email is sent to the
  finance / on-call addresses and the agent resumes with the escalation result.

A plain **Reject** is *not* an escalation — it resolves Tier 1 with a "denied"
decision that the agent reports back to the caller.

Two wait strategies are exposed as separate tools so the LLM can pick per case:

- ``request_quick_approval`` (**BLOCK**) — for small / quick yes-no decisions.
  The single REST call stays open while the manager answers in Teams.
- ``request_approval_with_escalation`` (**SUSPEND**) — for heavier decisions.
  The agent raises :class:`HumanInteractionInterrupt`; AgentTalk returns a
  ``paused`` envelope and the client resumes later with a ``hitl_response``.

Served over the AgentTalk REST API at
``POST /api/v1/agents/chat/expense_approval``.

Configuration (read from the environment via ``navconfig``):

Tier 1 — Teams HITL bot (consumed by ``TeamsHitlConfig``):
    ``MSTEAMS_HITL_APP_ID``, ``MSTEAMS_HITL_APP_PASSWORD``, ``MSTEAMS_TENANT_ID``,
    ``MSTEAMS_GRAPH_CLIENT_ID``, ``MSTEAMS_GRAPH_CLIENT_SECRET``,
    ``MSTEAMS_GRAPH_TENANT_ID``, ``REDIS_URL``.

Tier 2 — SMTP email:
    ``HITL_SMTP_HOST`` (default ``localhost``), ``HITL_SMTP_PORT`` (default ``25``),
    ``HITL_SMTP_USERNAME``, ``HITL_SMTP_PASSWORD``,
    ``HITL_SMTP_FROM`` (default ``parrot-hitl@parrot.local``),
    ``HITL_SMTP_STARTTLS`` (default ``false``), ``HITL_SMTP_SSL`` (default ``false``).

Policy & approvers:
    ``EXPENSE_TIER1_APPROVER`` (Teams email of the first-level approver),
    ``EXPENSE_TIER2_EMAILS`` (comma-separated Tier 2 escalation emails),
    ``EXPENSE_TIER1_TIMEOUT`` (seconds before escalating, default ``180``),
    ``EXPENSE_TIER2_TIMEOUT`` (seconds for the email tier, default ``3600``).

LLM:
    ``EXPENSE_APPROVAL_LLM`` (optional model override).
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from navconfig import config
from pydantic import Field

from parrot.bots import Agent
from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.registry import register_agent
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.human import (
    HumanInteraction,
    InteractionStatus,
    InteractionType,
    Severity,
    TimeoutAction,
    get_default_human_manager,
)
from parrot.human.actions.notify import NotifyAction
from parrot.human.models import (
    EscalationActionType,
    EscalationPolicy,
    EscalationTier,
)
from parrot.human.channels.teams import (
    TeamsHitlConfig,
    setup_teams_hitl,
)

_BACKSTORY = """
You are the Expense Approval Concierge. You help employees get expense and
refund requests approved by routing each decision to a human manager — you
NEVER approve or reject a request on your own.

How you work:
- Collect the essentials first: the amount, the currency, who is requesting it,
  and a short business justification (the reason). Ask follow-up questions until
  you have all four.
- Decide which approval tool to use:
    * For small, routine, low-risk amounts (a quick yes/no the manager can
      answer immediately), call `request_quick_approval`. This waits for the
      manager's reply in Microsoft Teams and returns the decision right away.
    * For larger, sensitive, or escalation-prone amounts, call
      `request_approval_with_escalation`. This suspends the conversation while
      the manager reviews; the user will be resumed once a decision is made.
- Pick a sensible `severity`: 'low' or 'normal' for routine spend, 'high' or
  'critical' for large or unusual requests.

When you receive the outcome, explain it clearly to the user:
- approved  -> tell them it was approved by the manager.
- denied    -> tell them the manager declined, and (if given) the reason.
- escalated -> explain the manager did not respond in time (or chose to
  escalate), so the request was forwarded to the finance team by email and a
  decision will follow out of band.
- timed out -> no decision was reached in the allotted window.

Never fabricate an approval. If the approval system is unavailable, say so
plainly and tell the user to try again later.
"""


def _smtp_email_cfg() -> dict:
    """Build the :class:`EmailBackend` kwargs from ``HITL_SMTP_*`` env vars.

    Returns:
        A dict suitable for ``NotifyAction(email_cfg=...)`` /
        ``EmailBackend(**cfg)``.
    """
    return {
        "host": config.get("HITL_SMTP_HOST", fallback="localhost"),
        "port": int(config.get("HITL_SMTP_PORT", fallback=25)),
        "username": config.get("HITL_SMTP_USERNAME", fallback=None),
        "password": config.get("HITL_SMTP_PASSWORD", fallback=None),
        "default_from": config.get(
            "HITL_SMTP_FROM", fallback="parrot-hitl@parrot.local"
        ),
        "use_tls": config.getboolean("HITL_SMTP_STARTTLS", fallback=False),
        "use_ssl": config.getboolean("HITL_SMTP_SSL", fallback=False),
    }


def _tier2_emails() -> List[str]:
    """Parse ``EXPENSE_TIER2_EMAILS`` (comma-separated) into a clean list."""
    raw = config.get("EXPENSE_TIER2_EMAILS", fallback="") or ""
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


class _ExpenseApprovalArgs(AbstractToolArgsSchema):
    """Arguments shared by both expense-approval tools."""

    amount: float = Field(
        ..., gt=0, description="The expense / refund amount to be approved."
    )
    reason: str = Field(
        ...,
        description="Short business justification for the expense or refund.",
    )
    requestor: str = Field(
        ...,
        description="Name or email of the employee requesting the expense.",
    )
    currency: str = Field(
        default="USD", description="ISO 4217 currency code (e.g. USD, EUR)."
    )
    severity: str = Field(
        default="normal",
        description=(
            "Declared criticality: one of 'low', 'normal', 'high', 'critical'. "
            "Drives the starting tier of the escalation policy."
        ),
    )


class _TeamsApprovalToolBase(AbstractTool):
    """Shared HITL wiring for the Teams-approval tools.

    The agent injects ``policy_id``, ``approver_email`` and ``tier1_timeout``
    onto each instance in :meth:`ExpenseApprovalAgent.configure` once the
    escalation policy has been registered on the manager.
    """

    args_schema = _ExpenseApprovalArgs

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Wired by the agent during configure():
        self.policy_id: Optional[str] = None
        self.approver_email: Optional[str] = None
        self.tier1_timeout: float = 180.0
        self.source_agent: str = "expense_approval"

    def _build_interaction(
        self,
        amount: float,
        reason: str,
        requestor: str,
        currency: str,
        severity: str,
    ) -> HumanInteraction:
        """Assemble the policy-bound APPROVAL interaction."""
        try:
            sev = Severity(severity.lower())
        except ValueError:
            sev = Severity.NORMAL

        question = f"Approve {currency} {amount:,.2f} expense for {requestor}?"
        context = (reason or "").strip()[:500]
        return HumanInteraction(
            question=question,
            context=context,
            interaction_type=InteractionType.APPROVAL,
            target_humans=[self.approver_email] if self.approver_email else [],
            timeout=self.tier1_timeout,
            timeout_action=TimeoutAction.ESCALATE,
            policy_id=self.policy_id,
            severity=sev,
            source_agent=self.source_agent,
        )

    def _preflight_error(self, manager: Any) -> Optional[str]:
        """Return an actionable error string when HITL is not usable, else None."""
        if manager is None:
            return (
                "Approval system unavailable: no HumanInteractionManager is "
                "configured on the server. Please try again later."
            )
        if not self.approver_email or not self.policy_id:
            return (
                "Approval system not fully configured: missing the Tier-1 "
                "approver or escalation policy (set EXPENSE_TIER1_APPROVER). "
                "Please contact an administrator."
            )
        return None

    @staticmethod
    def _format_result(result: Any, currency: str, amount: float) -> str:
        """Render an :class:`InteractionResult` as a concise, LLM-friendly summary."""
        amount_str = f"{currency} {amount:,.2f}"

        # Escalated to Tier 2 (email) — surface the backend message if present.
        if result.escalated or result.status == InteractionStatus.ESCALATED:
            message = ""
            if result.action_metadata and "message" in result.action_metadata:
                message = f" {result.action_metadata['message']}"
            return (
                f"[escalated] The {amount_str} request was not approved at "
                f"Tier 1 (no timely response or an explicit escalation) and "
                f"was forwarded to the finance team by email.{message}"
            )

        if result.status == InteractionStatus.TIMEOUT:
            return (
                f"[timeout] No decision was made on the {amount_str} request "
                f"within the approval window."
            )
        if result.status == InteractionStatus.CANCELLED:
            return f"[cancelled] The {amount_str} approval request was cancelled."

        decision = result.consolidated_value
        if decision is True or (isinstance(decision, str) and decision.lower() in {"approve", "approved", "yes", "true"}):
            return f"[approved] The manager approved the {amount_str} expense."
        if decision is False or (isinstance(decision, str) and decision.lower() in {"reject", "rejected", "deny", "denied", "no", "false"}):
            return f"[denied] The manager declined the {amount_str} expense."
        # Any other concrete value (e.g. a free-text note).
        if decision is not None:
            return f"[decision] Manager response on the {amount_str} expense: {decision}"
        return f"[no-response] No decision value was returned for the {amount_str} expense."


class QuickTeamsApprovalTool(_TeamsApprovalToolBase):
    """Request a quick yes/no approval and BLOCK until the manager answers.

    Sends an approval card to the configured manager on Microsoft Teams and
    waits (within the Tier-1 timeout) for the decision. If the manager does not
    answer in time, or taps Escalate, the request escalates to the email tier
    and this tool reports the escalation. Best for small, routine amounts.
    """

    name: str = "request_quick_approval"

    async def _execute(
        self,
        amount: float,
        reason: str,
        requestor: str,
        currency: str = "USD",
        severity: str = "normal",
        **kwargs: Any,
    ) -> str:
        manager = get_default_human_manager()
        error = self._preflight_error(manager)
        if error:
            return error
        if "teams" not in getattr(manager, "channels", {}):
            return (
                "Approval system unavailable: the Microsoft Teams channel is "
                "not connected (check the MSTEAMS_HITL_* settings)."
            )

        interaction = self._build_interaction(
            amount, reason, requestor, currency, severity
        )
        self.logger.info(
            "Requesting Teams approval (BLOCK) for %s %.2f (requestor=%s)",
            currency, amount, requestor,
        )
        result = await manager.request_human_input(interaction, channel="teams")
        return self._format_result(result, currency, amount)


class EscalatingTeamsApprovalTool(_TeamsApprovalToolBase):
    """Request an approval and SUSPEND the agent until a decision is made.

    Registers the interaction, dispatches the Teams card, then raises
    :class:`HumanInteractionInterrupt` so AgentTalk returns a ``paused``
    envelope. Tier-1 timeout escalation to the email tier still fires while the
    agent is suspended. The caller resumes later with a ``hitl_response``.
    Best for larger or sensitive amounts.
    """

    name: str = "request_approval_with_escalation"

    async def _execute(
        self,
        amount: float,
        reason: str,
        requestor: str,
        currency: str = "USD",
        severity: str = "normal",
        **kwargs: Any,
    ) -> str:
        manager = get_default_human_manager()
        error = self._preflight_error(manager)
        if error:
            return error
        if "teams" not in getattr(manager, "channels", {}):
            return (
                "Approval system unavailable: the Microsoft Teams channel is "
                "not connected (check the MSTEAMS_HITL_* settings)."
            )

        interaction = self._build_interaction(
            amount, reason, requestor, currency, severity
        )
        self.logger.info(
            "Requesting Teams approval (SUSPEND) for %s %.2f (requestor=%s)",
            currency, amount, requestor,
        )
        interaction_id = await manager.request_human_input_async(
            interaction, channel="teams", schedule_timeout=True
        )
        # Hand control back to the orchestrator; AgentTalk returns a paused
        # envelope carrying the interaction id for later resume.
        raise HumanInteractionInterrupt(
            prompt=interaction.question,
            interaction_id=interaction_id,
            policy_id=self.policy_id,
        )


@register_agent(name="expense_approval", at_startup=True)
class ExpenseApprovalAgent(Agent):
    """Human-in-the-loop expense / refund approval agent.

    Wires a two-tier escalation policy (Teams approval → email) onto the
    process-wide :class:`HumanInteractionManager` during :meth:`configure`,
    and exposes two approval tools (BLOCK and SUSPEND wait strategies).
    """

    agent_id: str = "expense_approval"
    llm: str = "anthropic"
    model: str = config.get("EXPENSE_APPROVAL_LLM", fallback="claude-sonnet-4-6")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._quick_tool = QuickTeamsApprovalTool()
        self._escalating_tool = EscalatingTeamsApprovalTool()
        super().__init__(
            *args,
            name=kwargs.pop("name", "expense_approval"),
            backstory=_BACKSTORY,
            **kwargs,
        )
        self.logger = logging.getLogger(__name__)
        self._policy: Optional[EscalationPolicy] = None

    def agent_tools(self) -> List[AbstractTool]:
        """Expose the two HITL approval tools."""
        return [self._quick_tool, self._escalating_tool]

    def _build_policy(
        self, approver_email: str, tier1_timeout: float, tier2_timeout: float
    ) -> EscalationPolicy:
        """Assemble the Teams-then-email escalation policy."""
        return EscalationPolicy(
            name="expense-teams-then-email",
            tiers=[
                EscalationTier(
                    level=1,
                    name="Teams Approval",
                    channel_type="teams",
                    action_type=EscalationActionType.INTERACT,
                    target_humans=[approver_email],
                    timeout=tier1_timeout,
                ),
                EscalationTier(
                    level=2,
                    name="Email Escalation",
                    action_type=EscalationActionType.NOTIFY,
                    timeout=tier2_timeout,
                    action_metadata={
                        "kind": "email",
                        "to": _tier2_emails(),
                        "subject_template": "Expense escalation: {question}",
                    },
                ),
            ],
        )

    async def configure(self, app: Any = None) -> None:
        """Wire the Teams channel, email tier and escalation policy.

        Degrades gracefully: any missing dependency / credential is logged as a
        warning and the affected tier is skipped so the rest of the agent (and
        the unit tests) still run.
        """
        await super().configure(app)

        manager = get_default_human_manager()
        if manager is None:
            self.logger.warning(
                "ExpenseApprovalAgent: no default HumanInteractionManager "
                "(setup_web_hitl did not run); approval tools will report the "
                "system as unavailable."
            )
            return

        # 1. Tier 1 — register the Teams HITL channel (best effort).
        target_app = app or getattr(self, "app", None)
        if "teams" not in getattr(manager, "channels", {}):
            try:


                cfg = TeamsHitlConfig()
                if target_app is not None and getattr(cfg, "app_id", None):
                    await setup_teams_hitl(target_app, manager, cfg, "teams")
                    # Re-wire response/cancel handlers for the new channel.
                    await manager.startup()
                    self.logger.info(
                        "ExpenseApprovalAgent: Teams HITL channel registered."
                    )
                else:
                    self.logger.warning(
                        "ExpenseApprovalAgent: Teams HITL not configured "
                        "(missing app or MSTEAMS_HITL_APP_ID); Tier 1 disabled."
                    )
            except ImportError as exc:
                self.logger.warning(
                    "ExpenseApprovalAgent: ai-parrot-integrations Teams channel "
                    "unavailable (%s); Tier 1 disabled.", exc,
                )
            except Exception as exc:  # noqa: BLE001 - defensive boot wiring
                self.logger.error(
                    "ExpenseApprovalAgent: failed to set up Teams HITL: %s",
                    exc, exc_info=True,
                )

        # 2. Tier 2 — configure the email backend on the NOTIFY action.
        try:
            manager.set_action(
                EscalationActionType.NOTIFY,
                NotifyAction(email_cfg=_smtp_email_cfg()),
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "ExpenseApprovalAgent: failed to configure email NOTIFY "
                "action: %s", exc, exc_info=True,
            )

        # 3. Build + register the escalation policy.
        approver_email = config.get("EXPENSE_TIER1_APPROVER", fallback=None)
        if not approver_email:
            self.logger.warning(
                "ExpenseApprovalAgent: EXPENSE_TIER1_APPROVER is not set; the "
                "approval policy is NOT registered and the tools will report "
                "the system as not configured."
            )
            return

        tier1_timeout = float(
            config.get("EXPENSE_TIER1_TIMEOUT", fallback=180))
        tier2_timeout = float(
            config.get("EXPENSE_TIER2_TIMEOUT", fallback=3600))
        self._policy = self._build_policy(
            approver_email, tier1_timeout, tier2_timeout
        )
        manager.register_policy(self._policy)

        # 4. Inject the resolved wiring into both tools.
        for tool in (self._quick_tool, self._escalating_tool):
            tool.policy_id = self._policy.policy_id
            tool.approver_email = approver_email
            tool.tier1_timeout = tier1_timeout

        self.logger.info(
            "ExpenseApprovalAgent: escalation policy '%s' registered "
            "(approver=%s, tier1_timeout=%ss).",
            self._policy.policy_id, approver_email, tier1_timeout,
        )
