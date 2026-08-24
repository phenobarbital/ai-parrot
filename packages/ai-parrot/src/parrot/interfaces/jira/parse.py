"""Pure raw-Jira-JSON → :class:`JiraIssue` projection (FEAT-454, M1).

``parse_issue`` is a deterministic function of its inputs: no network, no
filesystem, no LLM, no clock. It is the PII boundary for this feature (G9) —
every Jira user object is routed through :func:`_person`, which reads only
``accountId`` and ``displayName`` and never spreads or `model_validate`s the
raw dict, so ``emailAddress`` (present on every raw Jira user object) can
never reach a :class:`JiraPerson` instance.
"""

import logging
from datetime import datetime
from typing import Any

from .models import (
    JiraAttachmentRef,
    JiraChangeEvent,
    JiraIssue,
    JiraIssueLink,
    JiraIssueLinkKind,
    JiraPerson,
    JiraRemoteLink,
)

logger = logging.getLogger(__name__)

# Epic-link custom field id used by classic (company-managed) Jira projects.
# Team-managed projects instead nest the epic under `fields.parent`, which
# is handled directly in `_epic_and_parent`.
_EPIC_LINK_FIELD = "customfield_10014"

# (type.name.lower(), direction) -> JiraIssueLinkKind. An unknown type.name
# degrades to RELATES rather than raising — Jira admins can add link types
# at any time and a sweep must not die on one (see module docstring).
_LINK_KIND_MAP: dict[tuple[str, str], JiraIssueLinkKind] = {
    ("blocks", "outward"): JiraIssueLinkKind.BLOCKS,
    ("blocks", "inward"): JiraIssueLinkKind.BLOCKED_BY,
    ("duplicate", "outward"): JiraIssueLinkKind.DUPLICATES,
    ("duplicate", "inward"): JiraIssueLinkKind.DUPLICATED_BY,
    ("cloners", "outward"): JiraIssueLinkKind.CLONES,
    ("cloners", "inward"): JiraIssueLinkKind.CLONED_BY,
    ("relates", "outward"): JiraIssueLinkKind.RELATES,
    ("relates", "inward"): JiraIssueLinkKind.RELATES,
}


def _person(raw_user: dict[str, Any] | None) -> JiraPerson | None:
    """Project a raw Jira user object to a :class:`JiraPerson`.

    Reads only ``accountId`` and ``displayName`` — never ``**raw_user``,
    never ``JiraPerson.model_validate(raw_user)``. Either would silently
    carry ``emailAddress`` through the moment someone relaxed
    ``model_config`` (G9).

    Args:
        raw_user: Raw Jira user object, or ``None``.

    Returns:
        A :class:`JiraPerson`, or ``None`` if ``raw_user`` is falsy.
    """
    if not raw_user:
        return None
    return JiraPerson(
        account_id=raw_user.get("accountId", ""),
        display_name=raw_user.get("displayName", ""),
    )


def _dt(value: str | None) -> datetime | None:
    """Parse a Jira ISO-8601 timestamp, returning ``None`` on failure.

    Jira emits timestamps like ``2026-08-20T16:02:07.000+0000`` (no colon in
    the UTC offset), which ``datetime.fromisoformat`` handles natively on
    Python 3.11+.

    Args:
        value: Raw timestamp string, or ``None``.

    Returns:
        A parsed ``datetime``, or ``None`` if ``value`` is falsy or
        unparseable.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.debug("Could not parse Jira timestamp %r", value)
        return None


def _issue_links(raw_links: list[dict[str, Any]] | None) -> list[JiraIssueLink]:
    """Normalize ``fields.issuelinks`` into direction-aware links.

    Each raw entry carries either ``inwardIssue`` or ``outwardIssue`` plus a
    ``type`` object with a ``name``. An unknown ``type.name`` degrades to
    :attr:`JiraIssueLinkKind.RELATES` rather than raising.

    Args:
        raw_links: Raw ``fields.issuelinks`` list, or ``None``.

    Returns:
        Normalized :class:`JiraIssueLink` list.
    """
    links: list[JiraIssueLink] = []
    for entry in raw_links or []:
        type_name = (entry.get("type") or {}).get("name", "")
        if "outwardIssue" in entry:
            direction = "outward"
            target = entry["outwardIssue"].get("key")
        elif "inwardIssue" in entry:
            direction = "inward"
            target = entry["inwardIssue"].get("key")
        else:
            continue
        if not target:
            continue
        kind = _LINK_KIND_MAP.get((type_name.lower(), direction))
        if kind is None:
            logger.debug(
                "Unknown Jira link type %r (%s); degrading to RELATES",
                type_name,
                direction,
            )
            kind = JiraIssueLinkKind.RELATES
        links.append(JiraIssueLink(kind=kind, target_key=target))
    return links


def _attachments(
    raw_attachments: list[dict[str, Any]] | None,
) -> list[JiraAttachmentRef]:
    """Project ``fields.attachment`` into reference-only models.

    Args:
        raw_attachments: Raw ``fields.attachment`` list, or ``None``.

    Returns:
        A list of :class:`JiraAttachmentRef`. Nothing is downloaded.
    """
    refs: list[JiraAttachmentRef] = []
    for att in raw_attachments or []:
        refs.append(
            JiraAttachmentRef(
                filename=att.get("filename", ""),
                size_bytes=att.get("size"),
                mime_type=att.get("mimeType"),
                url=att.get("content", ""),
            )
        )
    return refs


def _remote_links(
    raw_remote_links: list[dict[str, Any]] | None,
) -> list[JiraRemoteLink]:
    """Project a raw ``/remotelink`` payload into reference-only models.

    Args:
        raw_remote_links: Raw remote-link entries (``{"object": {...}}``),
            or ``None``.

    Returns:
        A list of :class:`JiraRemoteLink`.
    """
    refs: list[JiraRemoteLink] = []
    for entry in raw_remote_links or []:
        obj = entry.get("object") or {}
        refs.append(JiraRemoteLink(title=obj.get("title", ""), url=obj.get("url", "")))
    return refs


def _history(raw_changelog: dict[str, Any] | None) -> list[JiraChangeEvent]:
    """Flatten and sort ``changelog.histories`` into change events.

    Sorted ascending by ``at``, then by ``field``, so the projection is
    stable when two changes share a timestamp — determinism (G2) depends
    on this.

    Args:
        raw_changelog: Raw ``changelog`` dict (``{"histories": [...]}}``),
            or ``None``.

    Returns:
        A list of :class:`JiraChangeEvent`, sorted ascending.
    """
    events: list[JiraChangeEvent] = []
    for entry in (raw_changelog or {}).get("histories") or []:
        at = _dt(entry.get("created"))
        if at is None:
            continue
        author = _person(entry.get("author"))
        for item in entry.get("items") or []:
            events.append(
                JiraChangeEvent(
                    at=at,
                    field=item.get("field", ""),
                    from_value=item.get("fromString"),
                    to_value=item.get("toString"),
                    author=author,
                )
            )
    events.sort(key=lambda e: (e.at, e.field))
    return events


def _epic_and_parent(fields: dict[str, Any]) -> tuple[str | None, str | None]:
    """Resolve epic and parent keys from ``fields``.

    Classic (company-managed) projects carry the epic link in the
    ``customfield_10014`` epic-link field; team-managed projects instead
    nest the epic under ``fields.parent`` when the parent's issue type is
    ``Epic``. Since the fixture/raw shape used here targets the classic
    field, ``fields.parent`` is treated as the plain parent-issue key.

    Args:
        fields: Raw ``fields`` dict.

    Returns:
        A ``(epic_key, parent_key)`` tuple; either may be ``None``.
    """
    epic_key = fields.get(_EPIC_LINK_FIELD)
    parent = fields.get("parent") or {}
    parent_key = parent.get("key")
    return epic_key, parent_key


def parse_issue(
    raw: dict[str, Any],
    *,
    base_url: str,
    ac_field_id: str | None = None,
) -> JiraIssue:
    """Project a raw Jira issue payload into a validated :class:`JiraIssue`.

    Pure: no network, no filesystem, no LLM, no clock. Called twice with the
    same arguments, it returns equal models (G2).

    Args:
        raw: Raw Jira issue JSON (as returned by ``GET /issue/{key}`` with
            ``expand=renderedFields,changelog``).
        base_url: Jira instance base URL, used to build the browse ``url``.
        ac_field_id: Resolved acceptance-criteria custom field id (see
            ``JiraInterface.resolve_ac_field_id``, TASK-2400), or ``None``
            to omit the acceptance-criteria section entirely.

    Returns:
        A validated :class:`JiraIssue`.

    Raises:
        ValueError: If a required field (``key``, ``issue_id``,
            ``project_key``, ``issue_type``, ``status``, ``summary``) is
            missing from the payload — never a bare ``KeyError``.
    """
    fields = raw.get("fields")
    if not isinstance(fields, dict):
        # ValueError (not TypeError) is required by the spec/AC — a missing
        # or malformed 'fields' dict is a missing-required-data condition,
        # not a caller type error.
        raise ValueError("Raw Jira issue payload is missing required field 'fields'")  # noqa: TRY004

    key = raw.get("key")
    if not key:
        raise ValueError("Raw Jira issue payload is missing required field 'key'")
    issue_id = raw.get("id")
    if not issue_id:
        raise ValueError("Raw Jira issue payload is missing required field 'id'")

    project = fields.get("project") or {}
    project_key = project.get("key")
    if not project_key:
        raise ValueError("Raw Jira issue payload is missing required field 'fields.project.key'")

    issuetype = (fields.get("issuetype") or {}).get("name")
    if not issuetype:
        raise ValueError("Raw Jira issue payload is missing required field 'fields.issuetype.name'")

    status = (fields.get("status") or {}).get("name")
    if not status:
        raise ValueError("Raw Jira issue payload is missing required field 'fields.status.name'")

    summary = fields.get("summary")
    if not summary:
        raise ValueError("Raw Jira issue payload is missing required field 'fields.summary'")

    rendered = raw.get("renderedFields") or {}
    description_html = rendered.get("description")
    acceptance_criteria_html = rendered.get(ac_field_id) if ac_field_id else None

    resolution = (fields.get("resolution") or {}).get("name")
    priority = (fields.get("priority") or {}).get("name")

    epic_key, parent_key = _epic_and_parent(fields)
    subtask_keys = [st.get("key") for st in (fields.get("subtasks") or []) if st.get("key")]

    labels = list(fields.get("labels") or [])
    components = [c.get("name") for c in (fields.get("components") or []) if c.get("name")]

    url = f"{base_url.rstrip('/')}/browse/{key}"

    return JiraIssue(
        key=key,
        issue_id=str(issue_id),
        project_key=project_key,
        issue_type=issuetype,
        status=status,
        resolution=resolution,
        priority=priority,
        summary=summary,
        description_html=description_html,
        acceptance_criteria_html=acceptance_criteria_html,
        assignee=_person(fields.get("assignee")),
        reporter=_person(fields.get("reporter")),
        labels=labels,
        components=components,
        epic_key=epic_key,
        parent_key=parent_key,
        subtask_keys=subtask_keys,
        links=_issue_links(fields.get("issuelinks")),
        created_at=_dt(fields.get("created")),
        updated_at=_dt(fields.get("updated")),
        resolved_at=_dt(fields.get("resolutiondate")),
        history=_history(raw.get("changelog")),
        attachments=_attachments(fields.get("attachment")),
        remote_links=[],
        url=url,
    )
