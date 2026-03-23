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
        ..., description="The question or request to present to the human."
    )
    interaction_type: str = Field(
        default="free_text",
        description=(
            "Type of interaction: free_text, single_choice, "
            "multi_choice, approval, form, or poll."
        ),
    )
    options: Optional[List[Union[str, Dict[str, Any]]]] = Field(
        default=None,
        description=(
            "List of choice options. Each item can be a plain string "
            "(e.g. 'Paris') or a dict with 'key' and 'label'. "
            "Required for single_choice, multi_choice, and poll types."
        ),
    )
    context: Optional[str] = Field(
        default=None,
        description="Additional context to help the human answer.",
    )
    timeout: float = Field(
        default=7200.0,
        description="Maximum wait time in seconds (default 2 hours).",
    )
    form_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "JSON Schema for form interactions. Must have 'properties' "
            "with field definitions. Only used when interaction_type is 'form'."
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
        "Ask a human for input, approval, or a decision. "
        "Use this when you need human judgment, confirmation, "
        "or information that cannot be obtained automatically."
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
