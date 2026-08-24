"""Deterministic `JiraIssue` -> markdown renderer (FEAT-454, M3).

Pure function library: no network, no filesystem, no LLM, no clock
(``fetched_at`` is always a parameter). Mirrors the determinism contract of
:func:`parrot.knowledge.wiki.documents.render_frontmatter` — fixed key
order, sorted collections, ``None``/``[]`` omitted — so identical input
renders byte-identical output (G2), which is what makes a daily cron free
and diffable.

The sync marker (:data:`SYNC_MARKER`) is the highest-consequence path in
this module: everything below it, once written by a human, must survive
every future re-sync byte-for-byte (G4). See :func:`split_at_marker`'s
docstring for the exact preservation contract before touching it.

Relations are emitted as ``[[KEY]]`` wikilinks and ``#tags`` — this is how
G7 (a navigable graph) is delivered without this feature writing a single
edge itself: ``wikitoolkit build``'s ``scan_vault`` turns a resolved
wikilink into a ``references`` edge and a ``#tag`` into a first-class tag
page (`vault_scan.py:16-21`).
"""
import hashlib
import logging
import re
from datetime import datetime
from typing import Literal

import html2text
import yaml
from pydantic import BaseModel

from parrot.interfaces.jira import JiraIssue, JiraPerson
from parrot.knowledge.okf import ConceptType

logger = logging.getLogger(__name__)

# Everything from this marker (at the start of a line) onward is the human's
# forever — the extractor only ever owns the region above it.
SYNC_MARKER: str = (
    "<!-- jira-sync:end — everything below is yours; "
    "the extractor never touches it -->"
)

# Bumping this forces a full re-render even when `updated` is unchanged
# (e.g. after a renderer bugfix) — consumed by the sweep (TASK-2403).
EXTRACTOR_VERSION: int = 1

# Explicit, fixed order — this tuple IS the determinism guarantee, mirroring
# documents.py:39-50 (`_FRONTMATTER_FIELD_ORDER`). Never iterate
# model_dump() insertion order and never sort_keys=True over the payload.
_ISSUE_FRONTMATTER_FIELD_ORDER: tuple[str, ...] = (
    "type",
    "key",
    "title",
    "status",
    "resolution",
    "category",
    "project",
    "priority",
    "assignee",
    "assignee_id",
    "reporter",
    "reporter_id",
    "created_at",
    "updated_at",
    "resolved_at",
    "labels",
    "components",
    "epic",
    "parent",
    "subtasks",
    "blocks",
    "blocked_by",
    "relates",
    "duplicates",
    "repo_pages",
    "url",
    "sync",
)

# Frontmatter fields whose values are lists — sorted exactly once, here.
# TASK-2399's parse_issue deliberately leaves Jira's native order intact.
_LIST_FIELDS: frozenset[str] = frozenset(
    {"labels", "components", "subtasks", "blocks", "blocked_by", "relates",
     "duplicates", "repo_pages"}
)

# Single fixed datetime shape used everywhere in this module's output.
_DT_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_SYNC_MARKER_RE = re.compile(
    r"^" + re.escape(SYNC_MARKER), re.MULTILINE,
)

# Filename-unsafe characters stripped/replaced by group_slug().
_SLUG_UNSAFE_RE = re.compile(r"[^a-z0-9]+")


class IssueSyncStamp(BaseModel):
    """Sync bookkeeping embedded in a ticket document's frontmatter."""

    fetched_at: str
    extractor_version: int
    unreachable_since: str | None = None  # set when the ticket stops resolving


class IssueFrontmatter(BaseModel):
    """Deterministic frontmatter projection of a :class:`JiraIssue`.

    Field declaration order IS the emitted YAML key order — mirrored into
    :data:`_ISSUE_FRONTMATTER_FIELD_ORDER` rather than relying on
    ``model_fields`` (an implementation detail whose reordering would
    silently churn every document).
    """

    type: ConceptType = ConceptType.ISSUE
    key: str
    title: str
    status: str
    resolution: str | None = None
    category: str  # Jira issuetype
    project: str
    priority: str | None = None
    assignee: str | None = None
    assignee_id: str | None = None
    reporter: str | None = None
    reporter_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    resolved_at: str | None = None
    labels: list[str] = []
    components: list[str] = []
    epic: str | None = None
    parent: str | None = None
    subtasks: list[str] = []
    blocks: list[str] = []
    blocked_by: list[str] = []
    relates: list[str] = []
    duplicates: list[str] = []
    repo_pages: list[str] = []  # qualified ids, e.g. "repo::file:sdd/specs/x.spec.md"
    url: str
    sync: IssueSyncStamp


# ----------------------------------------------------------------------
# Filenames / slugs
# ----------------------------------------------------------------------


def issue_filename(key: str) -> str:
    """Return the stable filename for an issue document.

    Args:
        key: Issue key, e.g. ``"NAV-9372"``.

    Returns:
        ``"NAV-9372.md"``.
    """
    return f"{key}.md"


def person_slug(person: JiraPerson) -> str:
    """Return a stable, filename-safe slug for a person note.

    Derived from ``account_id`` **alone** — never the display name — so a
    display-name change (or a re-fetch that renames someone) never orphans
    the page. Jira account ids may contain characters like ``:`` that are
    not filename-safe, so this sanitizes them the same way
    :func:`group_slug` does.

    Args:
        person: The person to slug.

    Returns:
        A filename-safe, stable slug.
    """
    return group_slug(person.account_id)


def group_slug(name: str) -> str:
    """Sanitize a project/component/label (or account id) into a filename slug.

    Lowercases, replaces runs of non-alphanumeric characters with a single
    ``-``, and strips leading/trailing ``-``. On collision with the empty
    string (an all-non-alphanumeric input), falls back to a short hash so
    the result is never empty.

    Args:
        name: Raw name to slugify.

    Returns:
        A non-empty, filename-safe slug.
    """
    slug = _SLUG_UNSAFE_RE.sub("-", name.strip().lower()).strip("-")
    if not slug:
        slug = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return slug


# ----------------------------------------------------------------------
# Sync marker
# ----------------------------------------------------------------------


def split_at_marker(text: str) -> tuple[str, str]:
    """Split a document at the first line-anchored :data:`SYNC_MARKER`.

    Contract (G4 — the highest-consequence path in this feature):

    - The **first** occurrence of ``SYNC_MARKER`` at the start of a line
      splits the document. Everything from that line onward (marker
      included) is the human tail, returned byte-for-byte — trailing
      whitespace and all.
    - No marker at all: returns ``(text, "")``. The caller is responsible
      for treating the *whole* existing text as human content when
      appending a marker for the first time (see :func:`render_issue_document`).
    - A **duplicated** marker: only the first splits. Any later marker is
      inert text inside the human tail — never "cleaned up".
    - A marker **inside a fenced code block**: this is a deliberate, known
      false positive. Splitting on the first line-anchored occurrence is
      the one behaviour that can never *lose* content — the code fence
      simply ends up (preserved verbatim) in the human tail. Fence-aware
      parsing would trade this harmless mis-split for a real
      content-loss risk, so v1 does not attempt it.

    Args:
        text: The full existing document text.

    Returns:
        A ``(generated, human_tail)`` tuple. ``human_tail`` is ``""`` when
        no marker is present.
    """
    match = _SYNC_MARKER_RE.search(text)
    if match is None:
        return text, ""
    return text[: match.start()], text[match.start() :]


# ----------------------------------------------------------------------
# HTML -> markdown
# ----------------------------------------------------------------------


def _converter() -> html2text.HTML2Text:
    """Build a fresh, explicitly-configured `HTML2Text` instance.

    ``HTML2Text`` carries mutable state between conversions, so a new
    instance is built per call. Every option that affects determinism or
    line width is set explicitly — the library's defaults wrap lines at
    78 columns, which would make output terminal-width dependent.
    """
    conv = html2text.HTML2Text()
    conv.body_width = 0  # never wrap — default 78 is non-deterministic
    conv.unicode_snob = True  # keep real unicode, don't ASCII-fold
    conv.inline_links = True  # no [1]-style reference-link footnotes
    conv.protect_links = True
    conv.ignore_images = True  # attachments are refs; no inline images
    conv.single_line_break = True
    conv.wrap_links = False
    conv.wrap_list_items = False
    conv.mark_code = True  # preserve <code>/<pre> as fenced code
    return conv


def html_to_markdown(html: str | None) -> str:
    """Convert Jira `renderedFields` HTML into deterministic markdown.

    A ``None``/empty input degrades to ``""`` — never raises. This is the
    only HTML entry point this feature uses; no ADF parser is written
    because both Jira REST API versions can be asked for
    ``expand=renderedFields``, which is HTML on both.

    Args:
        html: Rendered HTML from Jira, or ``None``.

    Returns:
        Deterministic markdown, or ``""``.
    """
    if not html:
        return ""
    return _converter().handle(html).strip()


# ----------------------------------------------------------------------
# Frontmatter
# ----------------------------------------------------------------------


def _fmt_dt(value: datetime | None) -> str | None:
    """Format a datetime through the single fixed shape used everywhere."""
    if value is None:
        return None
    return value.strftime(_DT_FORMAT)


def _render_frontmatter(fm: IssueFrontmatter) -> str:
    """Render `IssueFrontmatter` as deterministic YAML.

    Mirrors ``documents.render_frontmatter``'s algorithm: fixed key order
    (:data:`_ISSUE_FRONTMATTER_FIELD_ORDER`), every list field sorted,
    ``None``/``[]`` omitted, ``sort_keys=False`` so the explicit order
    survives ``yaml.safe_dump``.

    Args:
        fm: The frontmatter model to render.

    Returns:
        A YAML frontmatter block (``---\\n...\\n---\\n\\n``).
    """
    dumped = fm.model_dump(mode="json")
    payload: dict[str, object] = {}
    for field in _ISSUE_FRONTMATTER_FIELD_ORDER:
        value = dumped.get(field)
        if value is None:
            continue
        if field in _LIST_FIELDS:
            if not value:
                continue
            value = sorted(value)
        if field == "sync":
            value = {k: v for k, v in value.items() if v is not None}
        payload[field] = value

    body = yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return f"---\n{body}---\n\n"


# ----------------------------------------------------------------------
# Body sections
# ----------------------------------------------------------------------


def _fmt_size(size_bytes: int | None) -> str:
    """Format an attachment size in KB, or ``"?"`` when unknown."""
    if size_bytes is None:
        return "?"
    return f"{size_bytes / 1024:.1f} KB"


def _render_body(
    issue: JiraIssue, *, repo_pages: list[str] | None = None
) -> str:
    """Render the generated body (everything above the sync marker)."""
    lines: list[str] = []
    lines.append(f"# {issue.key} — {issue.summary}")
    lines.append("")
    lines.append(f"**Jira**: {issue.url}")

    tags = _tags(issue)
    if tags:
        lines.append("Tags: " + " ".join(f"#{t}" for t in tags))
    lines.append("")

    description = html_to_markdown(issue.description_html)
    if description:
        lines.append("## Description")
        lines.append(description)
        lines.append("")

    ac = html_to_markdown(issue.acceptance_criteria_html)
    if ac:
        lines.append("## Acceptance Criteria")
        lines.append(ac)
        lines.append("")

    relations = _render_relations(issue)
    if relations:
        lines.append("## Relations")
        lines.extend(relations)
        lines.append("")

    people = _render_people(issue)
    if people:
        lines.append("## People")
        lines.extend(people)
        lines.append("")

    if issue.history:
        lines.append("## Status History")
        for event in issue.history:
            at = _fmt_dt(event.at)
            lines.append(
                f"- {at} — {event.field}: {event.from_value} → {event.to_value}"
            )
        lines.append("")

    if issue.attachments:
        lines.append("## Attachments")
        for att in issue.attachments:
            size = _fmt_size(att.size_bytes)
            mime = att.mime_type or "unknown"
            lines.append(f"- `{att.filename}` ({size}, {mime}) — {att.url}")
        lines.append("")

    if repo_pages:
        lines.append("## Related Repo Pages")
        for page in sorted(repo_pages):
            lines.append(f"- `{page}`")
        lines.append("")

    # Trim the single trailing blank line each section appended — the
    # marker append below supplies its own leading newline.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _tags(issue: JiraIssue) -> list[str]:
    """Return the deterministic tag list for the header ``Tags:`` line."""
    tags = [issue.project_key, *issue.components, *issue.labels]
    return sorted(dict.fromkeys(tags))


def _render_relations(issue: JiraIssue) -> list[str]:
    """Render the `## Relations` bullet list, each target a `[[KEY]]`."""
    lines: list[str] = []
    if issue.epic_key:
        lines.append(f"- Epic: [[{issue.epic_key}]]")
    if issue.parent_key:
        lines.append(f"- Parent: [[{issue.parent_key}]]")
    if issue.subtask_keys:
        keys = ", ".join(f"[[{k}]]" for k in sorted(issue.subtask_keys))
        lines.append(f"- Subtasks: {keys}")

    by_kind: dict[str, list[str]] = {}
    for link in issue.links:
        by_kind.setdefault(link.kind.value, []).append(link.target_key)

    _KIND_LABELS = {
        "blocks": "Blocks",
        "blocked_by": "Blocked by",
        "relates": "Relates to",
        "duplicates": "Duplicates",
        "duplicated_by": "Duplicated by",
        "clones": "Clones",
        "cloned_by": "Cloned by",
    }
    for kind in sorted(by_kind):
        label = _KIND_LABELS.get(kind, kind.replace("_", " ").title())
        keys = ", ".join(f"[[{k}]]" for k in sorted(by_kind[kind]))
        lines.append(f"- {label}: {keys}")
    return lines


def _render_people(issue: JiraIssue) -> list[str]:
    """Render the `## People` bullet list, each person a `[[slug]]`."""
    lines: list[str] = []
    if issue.assignee is not None:
        lines.append(f"- Assignee: [[{person_slug(issue.assignee)}]]")
    if issue.reporter is not None:
        lines.append(f"- Reporter: [[{person_slug(issue.reporter)}]]")
    return lines


def _relation_frontmatter_lists(
    issue: JiraIssue,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Split issue.links into the four frontmatter relation lists."""
    blocks: list[str] = []
    blocked_by: list[str] = []
    relates: list[str] = []
    duplicates: list[str] = []
    for link in issue.links:
        kind = link.kind.value
        if kind == "blocks":
            blocks.append(link.target_key)
        elif kind == "blocked_by":
            blocked_by.append(link.target_key)
        elif kind in ("relates", "clones", "cloned_by"):
            relates.append(link.target_key)
        elif kind in ("duplicates", "duplicated_by"):
            duplicates.append(link.target_key)
    return blocks, blocked_by, relates, duplicates


# ----------------------------------------------------------------------
# Public renderers
# ----------------------------------------------------------------------


def render_issue_document(
    issue: JiraIssue,
    *,
    fetched_at: datetime,
    existing: str | None = None,
    repo_pages: list[str] | None = None,
) -> str:
    """Render a full ticket document: frontmatter + body + human tail.

    Pure: no filesystem, no network, no LLM, no clock — ``fetched_at`` is
    always supplied by the caller. Takes no client/model config; the
    `--enrich` LLM path (out of scope for v1) can only ever be a caller-side
    concern layered on top of this function's output.

    Args:
        issue: The parsed issue to render.
        fetched_at: Timestamp to stamp into ``sync.fetched_at``.
        existing: The document's current on-disk content, if any. When it
            carries :data:`SYNC_MARKER`, everything from the marker onward
            is preserved byte-for-byte. When it has no marker, its entire
            content is treated as human content and moved below a freshly
            appended marker — nothing is ever lost.
        repo_pages: Qualified repo-plane page ids to record as a
            frontmatter list and a plain-text section (never a wikilink —
            cross-namespace edges do not exist).

    Returns:
        The full document text.
    """
    blocks, blocked_by, relates, duplicates = _relation_frontmatter_lists(issue)
    fm = IssueFrontmatter(
        type=ConceptType.ISSUE,
        key=issue.key,
        title=issue.summary,
        status=issue.status,
        resolution=issue.resolution,
        category=issue.issue_type,
        project=issue.project_key,
        priority=issue.priority,
        assignee=issue.assignee.display_name if issue.assignee else None,
        assignee_id=issue.assignee.account_id if issue.assignee else None,
        reporter=issue.reporter.display_name if issue.reporter else None,
        reporter_id=issue.reporter.account_id if issue.reporter else None,
        created_at=_fmt_dt(issue.created_at),
        updated_at=_fmt_dt(issue.updated_at),
        resolved_at=_fmt_dt(issue.resolved_at),
        labels=list(issue.labels),
        components=list(issue.components),
        epic=issue.epic_key,
        parent=issue.parent_key,
        subtasks=list(issue.subtask_keys),
        blocks=blocks,
        blocked_by=blocked_by,
        relates=relates,
        duplicates=duplicates,
        repo_pages=list(repo_pages or []),
        url=issue.url,
        sync=IssueSyncStamp(
            fetched_at=_fmt_dt(fetched_at) or "",
            extractor_version=EXTRACTOR_VERSION,
        ),
    )

    generated = _render_frontmatter(fm) + _render_body(issue, repo_pages=repo_pages)

    if existing is None:
        return generated + "\n" + SYNC_MARKER + "\n"

    _, human_tail = split_at_marker(existing)
    if not human_tail:
        # No marker in the existing content: the whole thing is human
        # content that must move below a freshly appended marker.
        return generated + "\n" + SYNC_MARKER + "\n\n" + existing
    return generated + "\n" + human_tail


def render_person_note(
    person: JiraPerson,
    issue_keys: list[str],
    *,
    existing: str | None = None,
) -> str:
    """Render a person satellite note (assignee/reporter roll-up).

    No email anywhere — G9. The filename this note is stored under must be
    :func:`person_slug`'s output, driven by ``account_id`` alone.

    Args:
        person: The person to render.
        issue_keys: Ticket keys this person is assignee/reporter on.
        existing: The note's current on-disk content, if any (see
            :func:`render_issue_document` for the preservation contract).

    Returns:
        The full note text.
    """
    lines = [
        "---",
        f"type: {ConceptType.PERSON.value}",
        f"title: {person.display_name}",
        "---",
        "",
        f"# {person.display_name}",
        "",
        "## Tickets",
    ]
    for key in sorted(issue_keys):
        lines.append(f"- [[{key}]]")
    generated = "\n".join(lines) + "\n"
    return _append_or_preserve(generated, existing)


def render_group_note(
    kind: Literal["project", "component", "label"],
    name: str,
    issue_keys: list[str],
    *,
    existing: str | None = None,
) -> str:
    """Render a project/component/label roll-up satellite note.

    Args:
        kind: Which roll-up this is.
        name: The project key, component name, or label.
        issue_keys: Ticket keys carrying this project/component/label.
        existing: The note's current on-disk content, if any (see
            :func:`render_issue_document` for the preservation contract).

    Returns:
        The full note text.
    """
    concept_type = {
        "project": ConceptType.PROJECT,
        "component": ConceptType.OTHER,
        "label": ConceptType.OTHER,
    }[kind]
    lines = [
        "---",
        f"type: {concept_type.value}",
        f"title: {name}",
        "---",
        "",
        f"# {name}",
        "",
        "## Tickets",
    ]
    for key in sorted(issue_keys):
        lines.append(f"- [[{key}]]")
    generated = "\n".join(lines) + "\n"
    return _append_or_preserve(generated, existing)


def _append_or_preserve(generated: str, existing: str | None) -> str:
    """Shared marker-append/preserve logic for the satellite note renderers."""
    if existing is None:
        return generated + "\n" + SYNC_MARKER + "\n"
    _, human_tail = split_at_marker(existing)
    if not human_tail:
        return generated + "\n" + SYNC_MARKER + "\n\n" + existing
    return generated + "\n" + human_tail
