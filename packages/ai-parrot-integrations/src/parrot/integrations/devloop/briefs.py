"""Command + requester + config → validated dev-loop brief (spec §3 Module 5, §7 defaults)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel

from parrot.flows.dev_flow.models import DevRequestBrief  # verified: dev_flow/models.py:61 (+ TASK-3196 fields)
from parrot.flows.dev_loop import ShellCriterion, WorkBrief  # verified: dev_loop/__init__.py:71,73
from parrot.integrations.devloop.models import DevLoopCommand, DevLoopIntegrationConfig, Requester

_SUMMARY_MAX = 255
_SUMMARY_MIN = 10
_TITLE_MAX = 80
_SENTENCE_SPLIT = re.compile(r"[.\n]")


def _first_line(text: str) -> str:
    """Return the first non-empty line of ``text``, stripped."""
    return text.strip().splitlines()[0].strip() if text.strip() else ""


def build_bug_brief(
    command: DevLoopCommand,
    requester: Requester,
    config: DevLoopIntegrationConfig,
    *,
    reporter: str,
    escalation_assignee: str,
) -> WorkBrief:
    """Build a ``WorkBrief(kind="bug")`` with the spec §7 defaults.

    Q2 resolved: the configured ``default_acceptance_criteria`` is used
    unless ``--ac`` overrides it for this run.

    Args:
        command: The parsed ``/devloop`` command.
        requester: The channel-neutral identity of the caller (currently
            unused here — kept for a uniform builder signature and
            possible future per-requester defaults).
        config: The bot's ``devloop:`` config.
        reporter: Resolved Jira reporter identity.
        escalation_assignee: Resolved Jira escalation identity.

    Returns:
        The validated :class:`WorkBrief`.
    """
    del requester  # unused today; kept for signature parity with build_feature_brief-style callers
    summary = _first_line(command.prompt)[:_SUMMARY_MAX]
    if len(summary) < _SUMMARY_MIN:
        padding = command.prompt.strip()
        summary = (f"bug: {summary} {padding}".strip())[:_SUMMARY_MAX]
        if len(summary) < _SUMMARY_MIN:
            summary = summary.ljust(_SUMMARY_MIN)

    criteria = (
        [ShellCriterion(name="slack-ac", command=command.acceptance_command)]
        if command.acceptance_command
        else [ShellCriterion(**d) for d in config.default_acceptance_criteria]
    )
    payload: Dict[str, Any] = {
        "kind": "bug",
        "summary": summary,
        "description": command.prompt,
        "affected_component": command.component or config.default_component,
        "acceptance_criteria": criteria,
        "escalation_assignee": escalation_assignee,
        "reporter": reporter,
        "existing_issue_key": command.jira_issue_key,
    }
    if command.base_branch:
        payload.update(flow_type="feature", base_branch=command.base_branch)
    return WorkBrief(**payload)


def build_feature_brief(command: DevLoopCommand, config: DevLoopIntegrationConfig) -> DevRequestBrief:
    """Build a ``DevRequestBrief(kind="new_feature")``.

    Args:
        command: The parsed ``/devloop`` command.
        config: The bot's ``devloop:`` config (unused today — kept for a
            uniform builder signature with :func:`build_bug_brief`).

    Returns:
        The validated :class:`DevRequestBrief`.
    """
    del config  # unused today; kept for signature parity with build_bug_brief
    title = (command.title or "").strip()
    if not title:
        first_sentence = _SENTENCE_SPLIT.split(command.prompt.strip(), maxsplit=1)[0].strip()
        title = first_sentence[:_TITLE_MAX]
    payload: Dict[str, Any] = {
        "kind": "new_feature",
        "title": title,
        "description": command.prompt,
        "jira_issue_key": command.jira_issue_key,
    }
    if command.base_branch:
        payload.update(flow_type="feature", base_branch=command.base_branch)  # TASK-3196 fields
    return DevRequestBrief(**payload)


def brief_to_file(brief: BaseModel, directory: str, run_id: str) -> str:
    """Write ``<directory>/<run_id>.brief.json`` (mode 0600).

    Args:
        brief: The validated brief to persist.
        directory: Target directory (created if missing, mode 0700).
        run_id: The run id; used verbatim as the file stem.

    Returns:
        The written file's path.
    """
    Path(directory).mkdir(parents=True, exist_ok=True, mode=0o700)
    path = os.path.join(directory, f"{run_id}.brief.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(brief.model_dump(mode="json"), fh)
    return path


def brief_summary_fields(brief: BaseModel) -> Dict[str, str]:
    """Display projection for the confirm card (both kinds, spec §7).

    Args:
        brief: A ``WorkBrief`` or ``DevRequestBrief`` instance.

    Returns:
        A flat ``{field_name: display_value}`` mapping suitable for a
        Block Kit confirm card.
    """
    if isinstance(brief, WorkBrief):
        criteria_names = ", ".join(c.name for c in brief.acceptance_criteria)
        return {
            "kind": brief.kind,
            "summary": brief.summary,
            "component": brief.affected_component,
            "criteria": criteria_names,
            "jira": brief.existing_issue_key or "",
            "base": brief.base_branch or "",
        }
    if isinstance(brief, DevRequestBrief):
        return {
            "kind": brief.kind,
            "title": brief.title,
            "description": brief.description[:200],
            "jira": brief.jira_issue_key or "",
            "base": brief.base_branch or "",
        }
    raise TypeError(f"brief_summary_fields: unsupported brief type {type(brief).__name__}")
