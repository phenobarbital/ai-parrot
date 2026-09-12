"""Block Kit builders for the Slack dev-loop adapter (FEAT-555 M10). Pure functions, no I/O."""

from __future__ import annotations

from typing import Any, Callable

from parrot.integrations.devloop.models import RequestType, RunRecord  # verified: spec §2 Data Models (TASK-3200)

_KIND_LABEL = {"feature": "Feature", "bug": "Bug"}

# Field lists per kind for the Edit modal (spec §7 "Confirm card for both kinds").
_EDIT_FIELDS: dict[str, list[tuple[str, str]]] = {
    "bug": [
        ("summary", "Summary"),
        ("description", "Description"),
        ("affected_component", "Component"),
        ("existing_issue_key", "Jira issue"),
        ("base_branch", "Base branch"),
    ],
    "feature": [
        ("title", "Title"),
        ("description", "Description"),
        ("context", "Context"),
        ("jira_issue_key", "Jira issue"),
        ("base_branch", "Base branch"),
    ],
}


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _button(text: str, action_id: str, value: str, style: str | None = None) -> dict[str, Any]:
    button: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": text},
        "action_id": action_id,
        "value": value,
    }
    if style:
        button["style"] = style
    return button


def confirm_blocks(pending_id: str, kind: RequestType, fields: dict[str, str]) -> list[dict[str, Any]]:
    """Confirm card for BOTH kinds (spec Q1): field preview + Confirm / Edit / Cancel buttons."""
    lines = "\n".join(f"*{label}*: {value}" for label, value in fields.items() if value)
    return [
        _section(f":clipboard: *{_KIND_LABEL.get(kind, kind)} request — confirm to dispatch*\n{lines}"),
        {
            "type": "actions",
            "block_id": f"devloop_confirm_block:{pending_id}",
            "elements": [
                _button("Confirm", f"devloop_confirm:{pending_id}", pending_id, "primary"),
                _button("Edit", f"devloop_edit:{pending_id}", pending_id),
                _button("Cancel", f"devloop_discard:{pending_id}", pending_id, "danger"),
            ],
        },
    ]


def edit_modal(pending_id: str, kind: RequestType, fields: dict[str, str]) -> dict[str, Any]:
    """form_definition for SlackInteractiveHandler.open_modal (interactive.py:308): callback_id devloop_edit.

    Args:
        pending_id: The pending confirmation's id (carried as modal metadata).
        kind: ``"bug"`` or ``"feature"`` — selects the field list.
        fields: The confirm card's display projection (``brief_summary_fields``),
            used as initial values.

    Returns:
        A form_definition: ``id``, ``title``, ``fields``, ``metadata``.
    """
    field_defs = _EDIT_FIELDS.get(kind, _EDIT_FIELDS["feature"])
    form_fields = [
        {
            "id": field_id,
            "label": label,
            "type": "text",
            "optional": True,
            "multiline": field_id in ("description", "context"),
            "initial_value": fields.get(field_id, "") or None,
        }
        for field_id, label in field_defs
    ]
    return {
        "id": "devloop_edit",
        "title": "Edit request",
        "fields": form_fields,
        "metadata": {"pending_id": pending_id, "kind": kind},
    }


def dispatch_root_blocks(record: RunRecord) -> list[dict[str, Any]]:
    """Public thread root: ':rocket: Development flow dispatched — run `<id>` for *<title>*, started by <@user>'."""
    return [
        _section(
            f":rocket: *Development flow dispatched* — run `{record.run_id}` for *{record.title}*, "
            f"started by <@{record.requester.user_id}> ({_KIND_LABEL.get(record.kind, record.kind)})"
        )
    ]


def run_started_blocks(record: RunRecord) -> list[dict[str, Any]]:
    """In-thread 'started' message with base branch / Jira key when present."""
    extras = []
    if record.jira_issue_key:
        extras.append(f"Jira: `{record.jira_issue_key}`")
    text = f":white_check_mark: Run `{record.run_id}` started."
    if extras:
        text += "\n" + " · ".join(extras)
    return [_section(text)]


def status_list_text(records: list[RunRecord], permalink: Callable[[RunRecord], str]) -> str:
    """Ephemeral status text: one line per run (id, kind, phase, current node, pending gate, permalink)."""
    if not records:
        return "You have no dev-loop runs."
    lines = []
    for record in records:
        gate = record.pending_gate_id or "—"
        node = record.current_node or "—"
        link = permalink(record)
        line = f"`{record.run_id}` {record.kind} · {record.phase} · node={node} · gate={gate}"
        if link:
            line += f" · <{link}|thread>"
        lines.append(line)
    return "\n".join(lines)
