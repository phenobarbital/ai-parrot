"""HumanTool — an AbstractTool that asks a human for input."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel, Field
from typing import Literal

from ..core.exceptions import HumanInteractionInterrupt
from ..tools.abstract import AbstractTool, AbstractToolArgsSchema
from .models import (
    ChoiceOption,
    HumanInteraction,
    InteractionResult,
    InteractionStatus,
    InteractionType,
    Severity,
    WaitStrategy,
)


_CHOICE_TYPES = {
    InteractionType.SINGLE_CHOICE,
    InteractionType.MULTI_CHOICE,
    InteractionType.POLL,
}

# 7 days — anything longer is almost certainly an LLM hallucination.
_MAX_TIMEOUT_SECONDS = 7 * 24 * 3600.0


class HumanToolInput(AbstractToolArgsSchema):
    """Input schema for the HumanTool.

    The schema is a deliberate subset of :class:`HumanInteraction`:
    consensus modes, escalation targets, and timeout actions are
    intentionally NOT exposed to the LLM. Those are configuration
    decisions that should be made at the agent/tool wiring layer,
    not by the model on a per-invocation basis.
    """

    question: str = Field(
        ...,
        min_length=1,
        description=(
            "The question to present to the human. Be specific: name the "
            "ticket/entity, the action you're about to take, and the "
            "concrete choice needed."
        ),
    )
    interaction_type: str = Field(
        default="free_text",
        description=(
            "MUST match the shape of the answer you need. Pick the most "
            "structured type available — the human replies with a button "
            "tap instead of typing. Options:\n"
            "  - 'approval': yes/no decision → renders ✅ Approve / ❌ Reject "
            "buttons. Use for confirming destructive or irreversible actions.\n"
            "  - 'single_choice': pick exactly one from a closed list → "
            "renders one inline button per option. REQUIRES 'options'. Use "
            "for project, priority, issue type, transition, resolution, "
            "or any enumerated pick.\n"
            "  - 'multi_choice': pick several from a closed list → renders "
            "toggle buttons + Done. REQUIRES 'options'. Use for multiple "
            "labels/components/watchers.\n"
            "  - 'form': several structured fields in one go → REQUIRES "
            "'form_schema'. Use for multi-field status reports.\n"
            "  - 'free_text': last resort. Only when the answer is genuinely "
            "free prose (closing comment, bug repro steps, one-line ETA) or "
            "when no closed list exists."
        ),
    )
    options: Optional[List[Union[str, Dict[str, Any]]]] = Field(
        default=None,
        description=(
            "REQUIRED for single_choice, multi_choice, and poll. Each item "
            "is either a plain string label or a dict "
            "{'key': '<stable_id>', 'label': '<what the user sees>', "
            "'description': '<optional>'}. Always include an escape hatch "
            "option like {'key': 'skip', 'label': 'Skip'} or "
            "{'key': 'cancel', 'label': 'Cancel'} so the human can bail "
            "without inventing a free-text reply."
        ),
    )
    context: Optional[str] = Field(
        default=None,
        max_length=280,
        description=(
            "Short background shown above the question (max 280 chars), "
            "e.g. the ticket summary or the scope of the action."
        ),
    )
    timeout: float = Field(
        default=7200.0,
        gt=0,
        le=_MAX_TIMEOUT_SECONDS,
        description=(
            "Maximum wait time in seconds (default 2 hours, max 7 days)."
        ),
    )
    form_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "REQUIRED when interaction_type='form'. JSON Schema object with "
            "'properties' (field_name -> {'type': 'string', 'description': "
            "'…'}) and optional 'required' list. Keep it to 2–5 fields."
        ),
    )
    default_response: Any = Field(
        default=None,
        description=(
            "Default value to use if the human does not respond "
            "within the timeout window."
        ),
    )
    target_humans: Optional[List[str]] = Field(
        default=None,
        description=(
            "Override target humans for this specific request. "
            "If not provided, uses the tool's default_targets."
        ),
    )
    policy_id: Optional[str] = Field(
        default=None,
        description="The ID of the tiered escalation policy to use if no response.",
    )
    severity: Literal["low", "normal", "high", "critical"] = Field(
        default="normal",
        description=(
            "Declared criticality of this human-input request. "
            "The agent's escalation policy (if any) uses this to pick the "
            "STARTING tier — higher severity may skip lower-priority tiers "
            "and begin escalation at a more urgent level. "
            "Use 'low' for advisory/nice-to-have approvals. "
            "Use 'normal' (default) for routine decisions. "
            "Use 'high' for irreversible operations, compliance-sensitive "
            "actions, or anything affecting production data. "
            "Use 'critical' ONLY for production-down / data-loss / "
            "safety-critical situations that require immediate human response."
        ),
    )


class HumanTool(AbstractTool):
    """Tool that pauses agent execution to request human input.

    The LLM invokes this tool when it needs information, approval,
    or a decision from a human operator.  The tool blocks until the
    human responds (or the configured timeout expires).

    Args:
        manager: HumanInteractionManager instance.
        default_channel: Channel to dispatch interactions to. When ``None``
            the tool picks the first registered channel on the manager.
        default_targets: Default human IDs to send interactions to.
        source_agent: Name of the agent that owns this tool.
    """

    name: str = "ask_human"
    description: str = (
        "Ask a human for input, approval, or a decision. Prefer "
        "STRUCTURED interaction types ('approval', 'single_choice', "
        "'multi_choice', 'form') over 'free_text' whenever the answer "
        "space is bounded — structured types render as tappable inline "
        "buttons on Telegram and give the human a much faster reply UX. "
        "Only use 'free_text' when the answer is genuinely free prose "
        "and no closed list of options exists. For every single_choice "
        "or multi_choice, include a 'skip'/'cancel' option so the human "
        "can back out without typing."
    )
    args_schema: Type[BaseModel] = HumanToolInput

    def __init__(
        self,
        manager: Any = None,
        *,
        default_channel: Optional[str] = "telegram",
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        wait_strategy: WaitStrategy = WaitStrategy.BLOCK,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.manager = manager
        self.default_channel = default_channel
        self.default_targets = list(default_targets) if default_targets else []
        self.source_agent = source_agent
        # Wiring decision — never exposed to the LLM / HumanToolInput schema.
        self.wait_strategy: WaitStrategy = wait_strategy

    def _resolve_channel(self) -> Optional[str]:
        """Return the configured channel or pick one from the manager.

        - If ``default_channel`` is set, use it verbatim (current default
          is ``"telegram"`` for back-compat). The manager logs a warning
          when an unregistered channel is used.
        - If ``default_channel`` is ``None``, fall back to the first
          channel registered on the manager.
        """
        if self.default_channel is not None:
            return self.default_channel
        channels = getattr(self.manager, "channels", None)
        if isinstance(channels, dict) and channels:
            return next(iter(channels))
        return None

    @staticmethod
    def _parse_options(
        raw_options: Optional[List[Any]],
    ) -> Optional[List[ChoiceOption]]:
        """Parse option payloads. Returns None if input is None/empty.

        Raises ``ValueError`` on malformed entries so the caller can
        return an actionable error message to the LLM.
        """
        if not raw_options:
            return None
        parsed: List[ChoiceOption] = []
        for i, opt in enumerate(raw_options):
            if isinstance(opt, str):
                if not opt.strip():
                    raise ValueError(f"options[{i}]: empty string")
                parsed.append(
                    ChoiceOption(
                        key=opt.lower().replace(" ", "_"),
                        label=opt,
                    )
                )
            elif isinstance(opt, dict):
                key = opt.get("key")
                label = opt.get("label") or key
                if not label:
                    raise ValueError(
                        f"options[{i}]: each option must have 'label' "
                        "(or 'key' as a fallback)"
                    )
                parsed.append(
                    ChoiceOption(
                        key=key or label.lower().replace(" ", "_"),
                        label=label,
                        description=opt.get("description"),
                        metadata=opt.get("metadata") or {},
                    )
                )
            else:
                raise ValueError(
                    f"options[{i}]: expected str or dict, got {type(opt).__name__}"
                )
        return parsed

    async def _execute(self, **kwargs: Any) -> Any:
        """Build a HumanInteraction and wait for the result."""
        if self.manager is None:
            return (
                "HumanTool error: no HumanInteractionManager configured. "
                "Cannot reach a human operator."
            )

        # The args_schema validator has already enforced presence/types of
        # required fields and applied defaults, so we read them directly.
        question: str = kwargs["question"]
        raw_type: str = kwargs.get("interaction_type", "free_text")
        raw_options = kwargs.get("options")
        context: Optional[str] = kwargs.get("context")
        timeout: float = kwargs.get("timeout", 7200.0)
        form_schema: Optional[dict] = kwargs.get("form_schema")
        default_response: Any = kwargs.get("default_response")
        target_humans: Optional[list] = kwargs.get("target_humans")
        policy_id: Optional[str] = kwargs.get("policy_id")
        raw_severity: str = kwargs.get("severity", "normal")

        # Validate severity — Literal in the schema constrains this at schema
        # level, but provide a defensive check for LLMs that bypass validation.
        try:
            severity_enum = Severity(raw_severity)
        except ValueError:
            return (
                f"HumanTool error: unknown severity '{raw_severity}'. "
                f"Must be one of: low, normal, high, critical"
            )

        # 1. Validate interaction_type — surface a clear error to the LLM
        #    rather than silently downgrading to FREE_TEXT.
        try:
            interaction_type = InteractionType(raw_type)
        except ValueError:
            valid = ", ".join(t.value for t in InteractionType)
            return (
                f"HumanTool error: unknown interaction_type '{raw_type}'. "
                f"Must be one of: {valid}"
            )

        # 2. Parse options with structured error reporting.
        try:
            options = self._parse_options(raw_options)
        except ValueError as exc:
            return f"HumanTool error: {exc}"

        # 3. Pre-check type/payload coherence so the LLM gets an actionable
        #    error before the model validator fires.
        if interaction_type in _CHOICE_TYPES and not options:
            return (
                f"HumanTool error: {interaction_type.value} requires "
                "options=[...] (a list of strings or {key,label} dicts)"
            )
        if interaction_type == InteractionType.FORM and not form_schema:
            return (
                "HumanTool error: form interactions require form_schema "
                "(JSON Schema dict with 'properties')"
            )

        # 4. Determine targets: per-call override > default. Defensive copy
        #    so the manager can't mutate self.default_targets.
        if target_humans:
            targets = list(target_humans)
        else:
            targets = list(self.default_targets)

        try:
            interaction = HumanInteraction(
                question=question,
                context=context,
                interaction_type=interaction_type,
                options=options,
                form_schema=form_schema,
                default_response=default_response,
                timeout=timeout,
                target_humans=targets,
                source_agent=self.source_agent,
                policy_id=policy_id,
                severity=severity_enum,
            )
        except ValueError as exc:
            return f"HumanTool error: invalid interaction — {exc}"

        channel = self._resolve_channel()

        # SUSPEND: register the interaction non-blocking and raise an interrupt
        # so the HTTP handler can serialise tool-loop state and return a paused
        # envelope.  No in-process timer is relied upon in this mode — the
        # interaction TTL in Redis is the sole expiry guarantee, so we must NOT
        # schedule an in-process _handle_timeout task.
        if self.wait_strategy == WaitStrategy.SUSPEND:
            interaction_id = await self.manager.request_human_input_async(
                interaction, channel=channel, schedule_timeout=False,
            )
            self.logger.info(
                "HumanTool SUSPEND: raising HumanInteractionInterrupt for "
                "interaction %s (policy_id=%s)",
                interaction_id,
                policy_id,
            )
            raise HumanInteractionInterrupt(
                prompt=question,
                interaction_id=interaction_id,
                policy_id=policy_id,
            )

        # BLOCK (default) and HOT_THEN_SUSPEND (reserved, treated as BLOCK):
        # await the full response synchronously.
        try:
            result: InteractionResult = await self.manager.request_human_input(
                interaction, channel=channel,
            )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as exc:
            self.logger.warning(
                "HumanTool timeout waiting on interaction %s: %s",
                interaction.interaction_id,
                exc,
            )
            return (
                "HumanTool error: the manager timed out waiting for the human."
            )

        return self._format_result(result)

    @staticmethod
    def _format_result(result: InteractionResult) -> Any:
        """Convert an InteractionResult into a value for the LLM.

        Handles all terminal statuses and ensures a non-None return
        so AbstractTool.execute doesn't raise ValueError. For escalated
        results with a non-string value we wrap the payload in a dict so
        the LLM still sees the escalation signal.
        """
        prefix = "[escalated] " if result.escalated else ""

        if result.status == InteractionStatus.TIMEOUT:
            if result.consolidated_value is not None:
                # TimeoutAction.DEFAULT — return the default
                return f"{prefix}{result.consolidated_value}"
            return f"{prefix}Human did not respond within the time limit."

        if result.status == InteractionStatus.CANCELLED:
            return f"{prefix}The interaction was cancelled."

        value = result.consolidated_value

        # If the interaction was resolved via an automatic escalation action
        # (e.g. TICKET) return the action's message to the LLM.
        if result.action_metadata and "message" in result.action_metadata:
            value = result.action_metadata["message"]

        if value is None:
            # Completed with no value (edge case) — return empty string
            # rather than None to avoid AbstractTool ValueError
            return f"{prefix}(no response provided)"

        if not result.escalated:
            return value

        # Escalated: annotate strings inline, wrap non-strings so the
        # signal isn't lost.
        if isinstance(value, str):
            if value.startswith(prefix):
                return value
            return f"{prefix}{value}"
        return {"escalated": True, "value": value}
