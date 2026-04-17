"""HumanTool — an AbstractTool that asks a human for input."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel, Field

from ..tools.abstract import AbstractTool, AbstractToolArgsSchema
from .models import (
    ChoiceOption,
    HumanInteraction,
    InteractionResult,
    InteractionStatus,
    InteractionType,
)


class HumanToolInput(AbstractToolArgsSchema):
    """Input schema for the HumanTool."""

    question: str = Field(
        ...,
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
        description=(
            "Short (< 280 chars) background shown above the question, e.g. "
            "the ticket summary or the scope of the action."
        ),
    )
    timeout: float = Field(
        default=7200.0,
        description="Maximum wait time in seconds (default 2 hours).",
    )
    form_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "REQUIRED when interaction_type='form'. JSON Schema object with "
            "'properties' (field_name -> {'type': 'string', 'description': "
            "'…'}) and optional 'required' list. Keep it to 2–5 fields."
        ),
    )
    default_response: Optional[Any] = Field(
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


class HumanTool(AbstractTool):
    """Tool that pauses agent execution to request human input.

    The LLM invokes this tool when it needs information, approval,
    or a decision from a human operator.  The tool blocks until the
    human responds (or the configured timeout expires).

    Args:
        manager: HumanInteractionManager instance.
        default_channel: Channel to dispatch interactions to.
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
        default_channel: str = "telegram",
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.manager = manager
        self.default_channel = default_channel
        self.default_targets = default_targets or []
        self.source_agent = source_agent

    async def _execute(self, **kwargs: Any) -> Any:
        """Build a HumanInteraction and wait for the result."""
        if self.manager is None:
            return (
                "HumanTool error: no HumanInteractionManager configured. "
                "Cannot reach a human operator."
            )

        question: str = kwargs.get("question", "")
        raw_type: str = kwargs.get("interaction_type", "free_text")
        raw_options = kwargs.get("options")
        context: Optional[str] = kwargs.get("context")
        timeout: float = kwargs.get("timeout", 7200.0)
        form_schema: Optional[dict] = kwargs.get("form_schema")
        default_response: Any = kwargs.get("default_response")
        target_humans: Optional[list] = kwargs.get("target_humans")

        # Parse interaction type
        try:
            interaction_type = InteractionType(raw_type)
        except ValueError:
            interaction_type = InteractionType.FREE_TEXT

        # Parse options — accept both plain strings and dicts
        options: Optional[List[ChoiceOption]] = None
        if raw_options:
            options = []
            for opt in raw_options:
                if isinstance(opt, str):
                    options.append(ChoiceOption(
                        key=opt.lower().replace(" ", "_"),
                        label=opt,
                    ))
                elif isinstance(opt, dict):
                    options.append(ChoiceOption(
                        key=opt.get("key", str(len(options))),
                        label=opt.get("label", str(opt)),
                        description=opt.get("description"),
                        metadata=opt.get("metadata", {}),
                    ))

        # Determine targets: per-call override > default
        targets = target_humans if target_humans else self.default_targets

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
        )

        try:
            result: InteractionResult = (
                await self.manager.request_human_input(
                    interaction, channel=self.default_channel
                )
            )
        except Exception as exc:
            return f"HumanTool error: failed to get human input — {exc}"

        return self._format_result(result)

    @staticmethod
    def _format_result(result: InteractionResult) -> Any:
        """Convert an InteractionResult into a value for the LLM.

        Handles all terminal statuses and ensures a non-None return
        so AbstractTool.execute doesn't raise ValueError.
        """
        prefix = ""
        if result.escalated:
            prefix = "[escalated] "

        if result.status == InteractionStatus.TIMEOUT:
            if result.consolidated_value is not None:
                # TimeoutAction.DEFAULT — return the default
                return f"{prefix}{result.consolidated_value}"
            return f"{prefix}Human did not respond within the time limit."

        if result.status == InteractionStatus.CANCELLED:
            return f"{prefix}The interaction was cancelled."

        value = result.consolidated_value
        if value is None:
            # Completed with no value (edge case) — return empty string
            # rather than None to avoid AbstractTool ValueError
            return f"{prefix}(no response provided)"

        # If escalated, annotate the value so the LLM knows
        if prefix and isinstance(value, str):
            return f"{prefix}{value}"

        return value
