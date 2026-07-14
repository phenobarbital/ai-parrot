"""Semantic UI Model for custom engine Copilot agents (FEAT-303).

This module defines the channel-neutral, card-oriented contract that domain
agents return as explicit structured output so that the ``msagentsdk`` bridge
can render rich Adaptive Cards for Microsoft 365 Copilot and Teams instead of
flat text.

The models here are pure Pydantic — this module MUST be importable without
``microsoft_agents.*`` installed, and it imports nothing from the rest of
``parrot`` so that import isolation always holds.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


class UIAction(BaseModel):
    """A card action button.

    Exactly one of ``prompt_template`` or ``url`` must be set. Actions with
    ``prompt_template`` render as ``Action.Submit`` (messageBack) and re-enter
    the agent's ``ask()`` pipeline as natural language. Actions with ``url``
    render as ``Action.OpenUrl``.

    Attributes:
        title: The button label shown on the card.
        prompt_template: Natural-language prompt template re-entering
            ``ask()``, e.g. ``"Show details for order {id}"``. Mutually
            exclusive with ``url``.
        params: Values used to fill ``prompt_template`` placeholders.
        url: A URL to open instead of re-entering the agent. Mutually
            exclusive with ``prompt_template``.
    """

    title: str
    prompt_template: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    url: Optional[str] = None

    @model_validator(mode="after")
    def _prompt_xor_url(self) -> "UIAction":
        """Ensure exactly one of ``prompt_template`` / ``url`` is set."""
        if bool(self.prompt_template) == bool(self.url):
            raise ValueError(
                "UIAction requires exactly one of prompt_template or url"
            )
        return self


class UIField(BaseModel):
    """A single labeled field, used by :class:`DetailPayload`.

    Attributes:
        label: The field's display label.
        value: The field's display value.
    """

    label: str
    value: str


class UIMetric(BaseModel):
    """A single KPI/metric entry, used by :class:`MetricsPayload`.

    Attributes:
        label: The metric's display label.
        value: The metric's display value.
        delta: Optional trend/delta text (e.g. ``"+5% vs last week"``).
    """

    label: str
    value: str
    delta: Optional[str] = None


class TablePayload(BaseModel):
    """A tabular result payload.

    Attributes:
        result_type: Discriminator, always ``"table"``.
        columns: Column headers, in display order.
        rows: Row data; each row is a list of string cells aligned to
            ``columns``.
        total_rows: The total number of rows available upstream, used to
            render a "showing N of M" truncation note when ``rows`` has been
            capped by the renderer.
    """

    result_type: Literal["table"]
    columns: list[str]
    rows: list[list[str]]
    total_rows: Optional[int] = None


class MetricsPayload(BaseModel):
    """A metrics/KPI result payload.

    Attributes:
        result_type: Discriminator, always ``"metrics"``.
        metrics: The list of metrics to render.
    """

    result_type: Literal["metrics"]
    metrics: list[UIMetric]


class DetailPayload(BaseModel):
    """An entity-detail result payload.

    Attributes:
        result_type: Discriminator, always ``"detail"``.
        fields: The labeled fields describing the entity.
    """

    result_type: Literal["detail"]
    fields: list[UIField]


class StatusPayload(BaseModel):
    """A status/error result payload.

    Attributes:
        result_type: Discriminator, always ``"status"``.
        level: The severity level of the status.
        message: The primary status message.
        details: Optional additional details/context.
    """

    result_type: Literal["status"]
    level: Literal["success", "warning", "error", "info"]
    message: str
    details: Optional[str] = None


class SemanticUIResult(BaseModel):
    """Card-oriented semantic description of an agent result.

    Domain agents/tools construct this model and return it as explicit
    structured output (via ``ask(structured_output=SemanticUIResult)`` or by
    setting it on the response) to opt in to rich Adaptive Card rendering in
    the ``msagentsdk`` bridge. The adapter never infers this model from free
    text.

    Attributes:
        title: The card's title.
        summary: Optional short summary text shown below the title.
        payload: The result payload, discriminated by ``result_type`` into
            one of :class:`TablePayload`, :class:`MetricsPayload`,
            :class:`DetailPayload`, :class:`StatusPayload`.
        actions: Card action buttons rendered below the payload.
    """

    title: str
    summary: Optional[str] = None
    payload: Union[TablePayload, MetricsPayload, DetailPayload, StatusPayload] = (
        Field(discriminator="result_type")
    )
    actions: list[UIAction] = Field(default_factory=list)
