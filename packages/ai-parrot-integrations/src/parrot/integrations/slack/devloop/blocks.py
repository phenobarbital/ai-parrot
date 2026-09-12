"""Block Kit builders for the Slack dev-loop adapter (FEAT-555 M10). Pure functions, no I/O."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from parrot.integrations.devloop.models import (  # verified: spec §2 Data Models (TASK-3200)
    GateView,
    RequestType,
    RunEvent,
    RunRecord,
)

_KIND_LABEL = {"feature": "Feature", "bug": "Bug"}
_GATE_EMOJI = {
    "pending": ":hourglass_flowing_sand:",
    "approved": ":white_check_mark:",
    "rejected": ":x:",
    "expired": ":alarm_clock:",
}

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


def gate_blocks(record: RunRecord, gate: GateView) -> list[dict[str, Any]]:
    """Gate card body.

    ``open_questions`` ⇒ numbered questions + Answer / Abort ideation;
    other kinds ⇒ title/instructions/payload_ref + Approve / Reject.

    Args:
        record: The run the gate belongs to.
        gate: The pending gate.

    Returns:
        The Block Kit blocks for the card.
    """
    suffix = f"{record.run_id}:{gate.gate_id}"
    header = _section(f"{_GATE_EMOJI['pending']} *{gate.title}*\n{gate.instructions}".strip())
    if gate.kind == "open_questions":
        numbered = "\n".join(f"*{i}.* {q}" for i, q in enumerate(gate.questions, 1))
        elements = [
            _button("Answer", f"devloop_answer:{suffix}", suffix, "primary"),
            _button("Abort ideation", f"devloop_reject:{suffix}", suffix, "danger"),
        ]
        return [header, _section(numbered), {"type": "actions", "elements": elements}]

    elements = [
        _button("Approve", f"devloop_approve:{suffix}", suffix, "primary"),
        _button("Reject", f"devloop_reject:{suffix}", suffix, "danger"),
    ]
    blocks: list[dict[str, Any]] = [header]
    if gate.payload_ref:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Evidence: {gate.payload_ref}"}]})
    if gate.expires_at:
        deadline = datetime.fromtimestamp(gate.expires_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Deadline: {deadline}"}]})
    return [*blocks, {"type": "actions", "elements": elements}]


def answers_modal(record: RunRecord, gate: GateView) -> dict[str, Any]:
    """form_definition for open_modal: callback_id devloop_answers.

    One optional multiline text input per question (block_id ``q<N>``).

    Args:
        record: The run the gate belongs to.
        gate: The ``open_questions`` gate.

    Returns:
        The form_definition dict.
    """
    fields = [
        {
            "id": f"q{i}",
            "label": q[:150],
            "type": "text",
            "optional": True,
            "multiline": True,
            "hint": "Leave empty to keep the question open",
        }
        for i, q in enumerate(gate.questions, 1)
    ]
    return {
        "id": "devloop_answers",
        "title": "Answer questions",
        "fields": fields,
        "metadata": {"run_id": record.run_id, "gate_id": gate.gate_id},
    }


def gate_resolved_blocks(record: RunRecord, gate: GateView) -> list[dict[str, Any]]:
    """Card body after resolution: 'Answered by <@user> (k of n)' / 'Rejected by …' / 'Expired'.

    Args:
        record: The run the gate belongs to.
        gate: The resolved/expired gate.

    Returns:
        The Block Kit blocks for the updated card.
    """
    resolved_by_user = gate.resolved_by.rsplit(":", 1)[-1] if gate.resolved_by else ""
    if gate.status == "expired":
        text = f"{_GATE_EMOJI['expired']} *{gate.title}*\nExpired — no answer was received in time."
    elif gate.status == "rejected":
        who = f"<@{resolved_by_user}>" if resolved_by_user else "someone"
        text = f"{_GATE_EMOJI['rejected']} *{gate.title}*\nRejected by {who}."
    else:
        who = f"<@{resolved_by_user}>" if resolved_by_user else "someone"
        if gate.kind == "open_questions":
            n = len(gate.questions)
            k = len([v for v in gate.answers.values() if v])
            text = f"{_GATE_EMOJI['approved']} *{gate.title}*\nAnswered by {who} ({k} of {n})."
        else:
            text = f"{_GATE_EMOJI['approved']} *{gate.title}*\nApproved by {who}."
    return [_section(text)]


def terminal_blocks(record: RunRecord, event: RunEvent) -> list[dict[str, Any]]:
    """Terminal summary for the run thread.

    ``run_closed`` ⇒ completed/failed summary (PR URL, Jira key);
    ``run_cancelled`` ⇒ cancelled by; ``process_exited`` ⇒ exit code +
    stderr tail.

    Args:
        record: The finished run.
        event: The terminal :class:`RunEvent`.

    Returns:
        The Block Kit blocks for the terminal message.
    """
    state = event.state or {}
    if event.kind == "run_closed":
        outcome = state.get("outcome", "")
        emoji = ":white_check_mark:" if outcome == "succeeded" else ":x:"
        lines = [f"{emoji} *Run `{record.run_id}` {outcome}*"]
        if state.get("pr_url"):
            lines.append(f"PR: {state['pr_url']}")
        if state.get("jira_issue_key"):
            lines.append(f"Jira: `{state['jira_issue_key']}`")
        return [_section("\n".join(lines))]
    if event.kind == "run_cancelled":
        requested_by = state.get("requested_by", "")
        who = requested_by.rsplit(":", 1)[-1] if requested_by else ""
        who_text = f"<@{who}>" if who else "the initiator"
        return [_section(f":no_entry_sign: *Run `{record.run_id}` cancelled* by {who_text}.")]
    # process_exited
    tail = (event.stderr_tail or "")[-2000:]
    text = f":boom: *Run `{record.run_id}` exited unexpectedly* (code {event.exit_code})."
    if tail:
        text += f"\n```{tail}```"
    return [_section(text)]
