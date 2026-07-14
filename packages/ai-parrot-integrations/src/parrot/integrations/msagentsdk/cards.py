"""Deterministic Adaptive Card renderer for the Semantic UI Model (FEAT-303).

Pure functions turning a :class:`~parrot.integrations.msagentsdk.semantic.
SemanticUIResult` into Adaptive Card 1.4 JSON (plain ``dict``), plus a total
plain-text fallback (:func:`render_text`) that never raises.

This module must be importable without ``microsoft_agents.*`` installed —
cards are plain dicts here; wrapping them in SDK ``Activity`` objects is the
bridge's job (``agent.py``, TASK-1753).
"""
from __future__ import annotations

import json
from typing import Any

from parrot.integrations.msagentsdk.semantic import (
    DetailPayload,
    MetricsPayload,
    SemanticUIResult,
    StatusPayload,
    TablePayload,
    UIAction,
)

# Allowed common-denominator Adaptive Card 1.4 element/action types
# (spec §2/§7): TextBlock, ColumnSet, Column, FactSet, Container,
# Action.Submit, Action.OpenUrl.

_LEVEL_TO_COLOR = {
    "success": "Good",
    "warning": "Warning",
    "error": "Attention",
    "info": "Default",
}


class CardRenderError(Exception):
    """Raised when a `SemanticUIResult` cannot be rendered within limits."""


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


def _no_results_card(message: str = "No results.") -> dict:
    """Build a minimal "no results" status-style card body."""
    return {
        "type": "Container",
        "items": [
            {
                "type": "TextBlock",
                "text": message,
                "wrap": True,
                "color": _LEVEL_TO_COLOR["info"],
            }
        ],
    }


def _render_table(result: SemanticUIResult, *, max_table_rows: int) -> dict:
    payload = result.payload
    assert isinstance(payload, TablePayload)

    body: list[dict] = [
        {"type": "TextBlock", "text": result.title, "wrap": True, "weight": "Bolder"}
    ]
    if result.summary:
        body.append({"type": "TextBlock", "text": result.summary, "wrap": True})

    if not payload.columns or not payload.rows:
        body.append(_no_results_card())
        return {"type": "AdaptiveCard", "version": "1.4", "body": body, "actions": []}

    rows = payload.rows[:max_table_rows]
    truncated = len(payload.rows) > max_table_rows

    header_columns = [
        {
            "type": "Column",
            "width": "auto",
            "items": [
                {"type": "TextBlock", "text": col, "wrap": True, "weight": "Bolder"}
            ],
        }
        for col in payload.columns
    ]
    body.append({"type": "ColumnSet", "columns": header_columns})

    for row in rows:
        row_columns = [
            {
                "type": "Column",
                "width": "auto",
                "items": [{"type": "TextBlock", "text": cell, "wrap": True}],
            }
            for cell in row
        ]
        body.append({"type": "ColumnSet", "columns": row_columns})

    if truncated:
        total = payload.total_rows if payload.total_rows is not None else len(
            payload.rows
        )
        body.append(
            {
                "type": "TextBlock",
                "text": f"Showing {len(rows)} of {total}",
                "wrap": True,
                "isSubtle": True,
            }
        )

    return {"type": "AdaptiveCard", "version": "1.4", "body": body, "actions": []}


def _render_metrics(result: SemanticUIResult, *, max_table_rows: int) -> dict:
    payload = result.payload
    assert isinstance(payload, MetricsPayload)

    body: list[dict] = [
        {"type": "TextBlock", "text": result.title, "wrap": True, "weight": "Bolder"}
    ]
    if result.summary:
        body.append({"type": "TextBlock", "text": result.summary, "wrap": True})

    if not payload.metrics:
        body.append(_no_results_card())
        return {"type": "AdaptiveCard", "version": "1.4", "body": body, "actions": []}

    facts = []
    for metric in payload.metrics:
        value = metric.value
        if metric.delta:
            value = f"{value} ({metric.delta})"
        facts.append({"title": metric.label, "value": value})

    body.append({"type": "FactSet", "facts": facts})
    return {"type": "AdaptiveCard", "version": "1.4", "body": body, "actions": []}


def _render_detail(result: SemanticUIResult, *, max_table_rows: int) -> dict:
    payload = result.payload
    assert isinstance(payload, DetailPayload)

    body: list[dict] = [
        {"type": "TextBlock", "text": result.title, "wrap": True, "weight": "Bolder"}
    ]
    if result.summary:
        body.append({"type": "TextBlock", "text": result.summary, "wrap": True})

    if not payload.fields:
        body.append(_no_results_card())
        return {"type": "AdaptiveCard", "version": "1.4", "body": body, "actions": []}

    facts = [{"title": field.label, "value": field.value} for field in payload.fields]
    body.append({"type": "FactSet", "facts": facts})
    return {"type": "AdaptiveCard", "version": "1.4", "body": body, "actions": []}


def _render_status(result: SemanticUIResult, *, max_table_rows: int) -> dict:
    payload = result.payload
    assert isinstance(payload, StatusPayload)

    items: list[dict] = [
        {
            "type": "TextBlock",
            "text": payload.message,
            "wrap": True,
            "weight": "Bolder",
            "color": _LEVEL_TO_COLOR[payload.level],
        }
    ]
    if payload.details:
        items.append({"type": "TextBlock", "text": payload.details, "wrap": True})

    body: list[dict] = [
        {"type": "TextBlock", "text": result.title, "wrap": True, "weight": "Bolder"}
    ]
    if result.summary:
        body.append({"type": "TextBlock", "text": result.summary, "wrap": True})
    body.append({"type": "Container", "items": items})

    return {"type": "AdaptiveCard", "version": "1.4", "body": body, "actions": []}


_RENDERERS = {
    "table": _render_table,
    "metrics": _render_metrics,
    "detail": _render_detail,
    "status": _render_status,
}


def _build_action(action: UIAction) -> dict:
    """Build an Adaptive Card action dict from a `UIAction`.

    ``prompt_template`` actions render as ``Action.Submit`` with a
    ``msteams.messageBack`` payload; ``url`` actions render as
    ``Action.OpenUrl``.
    """
    if action.url is not None:
        return {"type": "Action.OpenUrl", "title": action.title, "url": action.url}

    filled_prompt = _safe_format(action.prompt_template or "", action.params)
    return {
        "type": "Action.Submit",
        "title": action.title,
        "data": {
            "msteams": {
                "type": "messageBack",
                "text": filled_prompt,
                "displayText": action.title,
            },
            "feat303_prompt": filled_prompt,
        },
    }


def render_card(
    result: SemanticUIResult,
    *,
    max_table_rows: int = 15,
    max_card_bytes: int = 25_000,
) -> dict:
    """Render a `SemanticUIResult` as Adaptive Card 1.4 JSON.

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
    renderer = _RENDERERS.get(result.payload.result_type)
    if renderer is None:
        raise CardRenderError(
            f"unknown result_type {result.payload.result_type!r}"
        )

    card = renderer(result, max_table_rows=max_table_rows)
    card["actions"] = [_build_action(action) for action in result.actions]

    serialized_size = len(json.dumps(card).encode("utf-8"))
    if serialized_size > max_card_bytes:
        raise CardRenderError(
            f"card size {serialized_size} exceeds max_card_bytes={max_card_bytes}"
        )
    return card


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


def build_card_attachment(card: dict) -> dict:
    """Wrap card JSON in the Bot Framework attachment envelope.

    Args:
        card: The Adaptive Card JSON dict (as returned by `render_card`).

    Returns:
        The attachment envelope dict with `contentType`
        `"application/vnd.microsoft.card.adaptive"` and `content` set to
        `card`.
    """
    return {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": card,
    }
