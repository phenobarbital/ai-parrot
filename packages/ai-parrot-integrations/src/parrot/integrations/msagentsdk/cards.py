"""Deterministic Adaptive Card renderer for the Semantic UI Model (FEAT-303).

Pure functions turning a :class:`~parrot.integrations.msagentsdk.semantic.
SemanticUIResult` into Adaptive Card 1.5 JSON (plain ``dict``), plus a total
plain-text fallback (:func:`render_text`) that never raises.

Delegates to the shared :mod:`parrot.outputs.cards` builder for card
construction (AC 1.5, native ``Table`` element).  This module remains the
public API surface for the ``msagentsdk`` bridge.

This module must be importable without ``microsoft_agents.*`` installed —
cards are plain dicts here; wrapping them in SDK ``Activity`` objects is the
bridge's job (``agent.py``, TASK-1753).
"""
from __future__ import annotations

from typing import Any

from parrot.integrations.msagentsdk.semantic import (
    DetailPayload,
    MetricsPayload,
    SemanticUIResult,
    StatusPayload,
    TablePayload,
    UIAction,
)
from parrot.outputs.cards import (
    ActionOpenUrl,
    ActionSubmit,
    CardSpec,
    DetailField,
    DetailSection,
    MetricEntry,
    MetricsSection,
    StatusSection,
    TableSection,
    TextSection,
    build_attachment,
)
from parrot.outputs.cards import CardRenderError  # noqa: F401 — re-export
from parrot.outputs.cards import render as _card_render


class _DefaultFormatDict(dict):
    """A dict that substitutes literal ``{key}`` for missing format keys."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _safe_format(template: str, params: dict[str, Any]) -> str:
    """Format ``template`` with ``params``, tolerating missing keys.

    Missing placeholders degrade to the literal ``{key}`` text rather than
    raising ``KeyError``.
    """
    try:
        return template.format_map(_DefaultFormatDict(params))
    except (ValueError, IndexError):
        # Malformed template (e.g. stray braces) — degrade to literal text.
        return template


def _ui_action_to_ac_action(action: UIAction) -> ActionOpenUrl | ActionSubmit:
    """Map a :class:`UIAction` to the shared builder's action model.

    ``prompt_template`` actions render as ``Action.Submit`` with a
    ``msteams.messageBack`` payload; ``url`` actions render as
    ``Action.OpenUrl``.
    """
    if action.url is not None:
        return ActionOpenUrl(title=action.title, url=action.url)

    filled_prompt = _safe_format(action.prompt_template or "", action.params)
    return ActionSubmit(
        title=action.title,
        data={
            "msteams": {
                "type": "messageBack",
                "text": filled_prompt,
                "displayText": action.title,
            },
            "feat303_prompt": filled_prompt,
        },
    )


def _semantic_to_card_spec(
    result: SemanticUIResult,
    *,
    max_table_rows: int = 50,
) -> CardSpec:
    """Map a :class:`SemanticUIResult` to a :class:`CardSpec`.

    Translates each semantic payload type into the corresponding
    :mod:`parrot.outputs.cards` section model, preserving full fidelity
    with the original per-type renderers.

    Args:
        result: The semantic UI result to convert.
        max_table_rows: Maximum table rows before truncation.

    Returns:
        A :class:`CardSpec` ready for :func:`parrot.outputs.cards.render`.

    Raises:
        CardRenderError: If the ``result_type`` is unknown.
    """
    payload = result.payload
    sections: list = []

    if isinstance(payload, TablePayload):
        if not payload.columns or not payload.rows:
            sections.append(StatusSection(level="info", message="No results."))
        else:
            sections.append(TableSection(
                columns=payload.columns,
                rows=payload.rows,
                total_rows=payload.total_rows,
                max_display_rows=max_table_rows,
            ))
    elif isinstance(payload, MetricsPayload):
        if not payload.metrics:
            sections.append(StatusSection(level="info", message="No results."))
        else:
            sections.append(MetricsSection(
                metrics=[
                    MetricEntry(label=m.label, value=m.value, delta=m.delta)
                    for m in payload.metrics
                ],
            ))
    elif isinstance(payload, DetailPayload):
        if not payload.fields:
            sections.append(StatusSection(level="info", message="No results."))
        else:
            sections.append(DetailSection(
                fields=[
                    DetailField(label=f.label, value=f.value)
                    for f in payload.fields
                ],
            ))
    elif isinstance(payload, StatusPayload):
        sections.append(StatusSection(
            level=payload.level,
            message=payload.message,
            details=payload.details,
        ))
    else:
        raise CardRenderError(
            f"unknown result_type {getattr(payload, 'result_type', '?')!r}"
        )

    actions = [_ui_action_to_ac_action(a) for a in result.actions]

    return CardSpec(
        title=result.title,
        summary=result.summary,
        sections=sections,
        actions=actions,
    )


def render_card(
    result: SemanticUIResult,
    *,
    max_table_rows: int = 50,
    max_card_bytes: int = 25_000,
) -> dict:
    """Render a `SemanticUIResult` as Adaptive Card 1.5 JSON.

    Args:
        result: The semantic UI result to render.
        max_table_rows: Maximum table rows to render before truncating with
            a "showing N of M" note.
        max_card_bytes: Maximum serialized card size in bytes; exceeding it
            raises `CardRenderError` so the caller can fall back to
            `render_text`.

    Returns:
        The Adaptive Card as a plain dict (`type`, `version`, `body`,
        `actions`).

    Raises:
        CardRenderError: If the result cannot be rendered within limits
            (unknown `result_type` at runtime, or the serialized card
            exceeds `max_card_bytes`).
    """
    spec = _semantic_to_card_spec(result, max_table_rows=max_table_rows)
    return _card_render(spec, max_card_bytes=max_card_bytes)


def render_text(result: SemanticUIResult) -> str:
    """Render a `SemanticUIResult` as plain/markdown text.

    Total fallback: handles every payload shape (including empty lists and
    `None` fields) and never raises.

    Args:
        result: The semantic UI result to render.

    Returns:
        A readable plain/markdown text rendering of `result`.
    """
    try:
        lines = [f"**{result.title}**"]
        if result.summary:
            lines.append(result.summary)

        payload = result.payload

        if isinstance(payload, TablePayload):
            if not payload.columns or not payload.rows:
                lines.append("No results.")
            else:
                lines.append(" | ".join(payload.columns))
                for row in payload.rows:
                    lines.append(" | ".join(str(cell) for cell in row))
                if payload.total_rows and payload.total_rows > len(payload.rows):
                    lines.append(
                        f"Showing {len(payload.rows)} of {payload.total_rows}"
                    )
        elif isinstance(payload, MetricsPayload):
            if not payload.metrics:
                lines.append("No results.")
            else:
                for metric in payload.metrics:
                    text = f"{metric.label}: {metric.value}"
                    if metric.delta:
                        text += f" ({metric.delta})"
                    lines.append(text)
        elif isinstance(payload, DetailPayload):
            if not payload.fields:
                lines.append("No results.")
            else:
                for field in payload.fields:
                    lines.append(f"{field.label}: {field.value}")
        elif isinstance(payload, StatusPayload):
            lines.append(f"[{payload.level.upper()}] {payload.message}")
            if payload.details:
                lines.append(payload.details)
        else:
            lines.append("Unsupported result.")

        for action in result.actions:
            if action.url is not None:
                lines.append(f"- {action.title}: {action.url}")
            else:
                filled_prompt = _safe_format(
                    action.prompt_template or "", action.params
                )
                lines.append(f"- {action.title}: {filled_prompt}")

        return "\n".join(lines)
    except Exception:  # noqa: BLE001 - render_text must never raise
        return "Unable to render result."


def render_text_card(text: str) -> dict:
    """Wrap a plain/markdown text string in a minimal Adaptive Card 1.5.

    Teams renders markdown inside a ``TextBlock`` when ``markdown`` style
    is used, giving proper formatting (bold, lists, tables, code blocks)
    that ``TextFormatTypes.plain`` strips away.

    Args:
        text: The markdown/plain text to wrap.

    Returns:
        The Adaptive Card as a plain dict (``type``, ``version``, ``body``).
    """
    spec = CardSpec(sections=[TextSection(text=text)])
    return _card_render(spec)


def render_data_card(
    text: str,
    columns: list[str],
    rows: list[list],
    *,
    max_table_rows: int = 50,
) -> dict:
    """Build an Adaptive Card with an explanation block and a data table.

    Used when the agent response carries structured tabular data (e.g.
    ``PandasAgentResponse`` with a ``data`` field) that should be rendered
    as a native Table element in Teams rather than discarded.

    Args:
        text: Explanation / summary text shown above the table.
        columns: Column header names.
        rows: Row data as lists of scalars aligned with *columns*.
        max_table_rows: Maximum rows rendered before a truncation note.

    Returns:
        The Adaptive Card as a plain dict.
    """
    sections: list = []
    if text:
        sections.append(TextSection(text=text))

    if not columns or not rows:
        sections.append(TextSection(text="No data."))
    else:
        sections.append(TableSection(
            columns=columns,
            rows=[[str(c) for c in row] for row in rows],
            total_rows=len(rows),
            max_display_rows=max_table_rows,
        ))

    spec = CardSpec(sections=sections)
    return _card_render(spec)


def build_card_attachment(card: dict) -> dict:
    """Wrap card JSON in the Bot Framework attachment envelope.

    Args:
        card: The Adaptive Card JSON dict (as returned by `render_card`).

    Returns:
        The attachment envelope dict with `contentType`
        `"application/vnd.microsoft.card.adaptive"` and `content` set to
        `card`.
    """
    return build_attachment(card)
