"""Jira sweep: scope/watermark resolution, render, write, orphans (FEAT-454, M4).

The orchestrator: resolve the effective JQL scope and watermark, page
through matching issues via :class:`JiraInterface`, render each with
:mod:`parrot.knowledge.wiki.jira_render` and write only when the bytes
differ, accumulate satellite entity notes, detect orphans, mark
unreachable tickets, and advance the watermark **only** after a fully
successful pass.

Three invariants carry the most risk here:

- **G5** — the watermark must never advance over a corpus that was not
  fetched. ``last_run_status`` is written as ``"partial"`` *before* the
  fetch starts, so a crash (or ``SIGKILL``) mid-sweep leaves the on-disk
  state honest — the next run does not trust an incomplete watermark.
- **G3** — one document per ticket, updated in place; a byte-identical
  re-render leaves the file's mtime untouched.
- **G8** — the corpus root resolves to an absolute path outside the repo
  working tree even when ``PARROT_HOME`` is unset.

No LLM call is possible on this path: :func:`sweep_jira_issues` accepts no
client and no model config.
"""
import hashlib
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from parrot.interfaces.jira import JiraInterface, JiraPerson
from parrot.knowledge.wiki.jira_render import (
    EXTRACTOR_VERSION,
    group_slug,
    issue_filename,
    person_slug,
    render_group_note,
    render_issue_document,
    render_person_note,
    split_at_marker,
)
from parrot.knowledge.wiki.project import parrot_home, wiki_write_lock

logger = logging.getLogger(__name__)

# Filename of the persisted sync state, inside <issues-dir>/.parrot/ — a
# directory already excluded from vault scanning (vault_scan.py:58's
# VAULT_EXCLUDE_DIRS includes ".parrot"), so this file is never re-ingested
# as a note.
_SYNC_STATE_FILENAME = "jira_sync.json"

# Directories that ARE the corpus but must never be scanned for orphans —
# only the corpus root (one *.md per ticket) is orphan-eligible.
_ENTITY_SUBDIRS = ("people", "projects", "components", "labels")

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


class JiraScopeState(BaseModel):
    """Per-JQL-fingerprint watermark and run bookkeeping."""

    jql: str
    jql_fingerprint: str  # sha256 of the normalized JQL
    last_watermark: str | None = None  # ISO-8601 `updated` high-water mark
    extractor_version: int
    last_run_at: str | None = None
    last_run_status: Literal["ok", "partial", "failed"] = "ok"


class JiraSyncState(BaseModel):
    """Persisted at ``<issues-dir>/.parrot/jira_sync.json``."""

    version: int = 1
    scopes: dict[str, JiraScopeState] = Field(default_factory=dict)


class SweepReport(BaseModel):
    """Summary of one sweep run."""

    fetched: int = 0
    written: int = 0
    unchanged: int = 0
    skipped: int = 0
    orphaned: int = 0
    entity_notes: int = 0
    unresolved_link_keys: list[str] = Field(default_factory=list)
    watermark_advanced: bool = False
    errors: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Scope / storage resolution
# ----------------------------------------------------------------------


def jql_fingerprint(jql: str) -> str:
    """Return a stable sha256 fingerprint of a normalized JQL string.

    Normalization (collapsed whitespace, lowercased) means a cosmetic edit
    to the JQL does not orphan its watermark — but a *semantic* change is
    expected to, and intentionally starts a fresh scope.

    Args:
        jql: The raw JQL string.

    Returns:
        A hex sha256 digest.
    """
    normalized = " ".join(jql.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def resolve_issues_dir(explicit: Path | str | None = None) -> Path:
    """Resolve the corpus root, guaranteed absolute and outside the repo (G8).

    Precedence: ``explicit``, then ``JIRA_WIKI_ISSUES_DIR``, then
    ``${PARROT_HOME}/wikis/issues``. :func:`parrot.knowledge.wiki.project
    .parrot_home` already resolves ``PARROT_HOME`` to an absolute,
    expanded path (defaulting to ``~/.parrot``) — reused here rather than
    re-implemented, so a relative default can never leak into the working
    tree.

    Args:
        explicit: An explicit override, if any.

    Returns:
        An absolute path.
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    env = os.environ.get("JIRA_WIKI_ISSUES_DIR")
    if env:
        return Path(env).expanduser()
    return parrot_home() / "wikis" / "issues"


def load_sync_state(issues_dir: Path) -> JiraSyncState:
    """Load the persisted sync state, or a fresh one if absent/corrupt.

    Args:
        issues_dir: The corpus root.

    Returns:
        The parsed :class:`JiraSyncState`, or a default instance when the
        state file is missing or unparseable — malformed state is never a
        hard error.
    """
    path = issues_dir / ".parrot" / _SYNC_STATE_FILENAME
    if not path.exists():
        return JiraSyncState()
    try:
        return JiraSyncState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — corrupt state must not crash a sweep
        logger.warning("Could not parse %s: %s; starting fresh", path, exc)
        return JiraSyncState()


def save_sync_state(issues_dir: Path, state: JiraSyncState) -> None:
    """Persist the sync state to ``<issues_dir>/.parrot/jira_sync.json``.

    Args:
        issues_dir: The corpus root.
        state: The state to persist.
    """
    state_dir = issues_dir / ".parrot"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / _SYNC_STATE_FILENAME
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------

_DT_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def _fmt_dt(value: datetime) -> str:
    """Format a datetime through the single fixed shape used everywhere."""
    return value.strftime(_DT_FORMAT)


def _existing_note_keys(existing_text: str | None) -> set[str]:
    """Parse the ticket keys already listed in a satellite note's body.

    Reads only the generated region (above the sync marker) — this is the
    one place this module reads back its own rendered output, so an
    incremental sweep can merge (not replace) an entity note's key list.

    Args:
        existing_text: The note's current on-disk content, if any.

    Returns:
        The set of ``[[KEY]]`` wikilink targets found.
    """
    if not existing_text:
        return set()
    generated, _tail = split_at_marker(existing_text)
    return set(_WIKILINK_RE.findall(generated))


def _mark_unreachable(text: str, *, unreachable_since: str) -> str:
    """Patch ``sync.unreachable_since`` into an existing document in place.

    Touches only that one frontmatter field — body and human tail survive
    byte-for-byte. Used when a previously-known ticket now 404s/403s: a
    fresh :class:`JiraIssue` is not available for a ticket that no longer
    resolves, so :func:`render_issue_document` cannot be used here.

    Args:
        text: The document's current full text.
        unreachable_since: Timestamp to stamp into the field.

    Returns:
        The patched text, or the original text unchanged if it has no
        parseable leading frontmatter block.
    """
    if not text.startswith("---\n"):
        return text
    _, _, rest = text.partition("---\n")
    fm_block, sep, body = rest.partition("---\n")
    if not sep:
        return text
    try:
        payload = yaml.safe_load(fm_block)
    except yaml.YAMLError:
        return text
    if not isinstance(payload, dict):
        return text
    sync = payload.get("sync") or {}
    if not isinstance(sync, dict):
        sync = {}
    sync["unreachable_since"] = unreachable_since
    payload["sync"] = sync
    new_fm = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{new_fm}---\n{body}"


# ----------------------------------------------------------------------
# The sweep
# ----------------------------------------------------------------------


async def sweep_jira_issues(
    interface: JiraInterface,
    issues_dir: Path,
    *,
    jql: str,
    since: datetime | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> SweepReport:
    """Sweep ``jql`` into ``issues_dir``: fetch, render, write, report.

    No LLM call is possible on this path — this function takes no client
    and no model configuration.

    Args:
        interface: The shared Jira read interface (TASK-2400).
        issues_dir: The corpus root (see :func:`resolve_issues_dir`).
        jql: The caller-declared JQL scope.
        since: Overrides the stored watermark with an explicit
            ``updated >=`` bound, when given.
        force: Re-render every issue in scope, ignoring the watermark
            (still respects byte-identical unchanged detection).
        dry_run: Report what would change; write nothing at all — not the
            documents, not the entity notes, not the state file.

    Returns:
        A :class:`SweepReport` summarizing the run.
    """
    if dry_run:
        return await _run_sweep(interface, issues_dir, jql=jql, since=since, force=force, dry_run=True)

    with wiki_write_lock(issues_dir / ".parrot") as acquired:
        if not acquired:
            report = SweepReport()
            report.errors.append(
                "Another Jira sync is already running against this issues "
                "directory — refusing to run two writers concurrently."
            )
            return report
        return await _run_sweep(interface, issues_dir, jql=jql, since=since, force=force, dry_run=False)


async def _run_sweep(
    interface: JiraInterface,
    issues_dir: Path,
    *,
    jql: str,
    since: datetime | None,
    force: bool,
    dry_run: bool,
) -> SweepReport:
    """The actual sweep body, run under the write lock (or not, for dry_run)."""
    report = SweepReport()
    fp = jql_fingerprint(jql)
    state = load_sync_state(issues_dir)
    scope = state.scopes.get(fp)
    version_stale = scope is not None and scope.extractor_version < EXTRACTOR_VERSION

    if force or since is not None:
        effective_jql = jql
        if since is not None:
            since_str = since.strftime("%Y-%m-%d %H:%M")
            effective_jql = f'{jql} AND updated >= "{since_str}"'
    elif version_stale:
        effective_jql = jql
    elif scope is not None and scope.last_watermark:
        effective_jql = f'{jql} AND updated >= "{scope.last_watermark}"'
    else:
        effective_jql = jql

    is_full_sweep = "updated >=" not in effective_jql

    fetched_at = datetime.now(UTC)
    new_scope = JiraScopeState(
        jql=jql,
        jql_fingerprint=fp,
        last_watermark=scope.last_watermark if scope else None,
        extractor_version=scope.extractor_version if scope else EXTRACTOR_VERSION,
        last_run_at=_fmt_dt(fetched_at),
        last_run_status="partial",
    )
    if not dry_run:
        # Written BEFORE the fetch starts — this is what makes a crash
        # mid-sweep safe: the next run never trusts an incomplete pass.
        state.scopes[fp] = new_scope
        save_sync_state(issues_dir, state)

    ac_field_id = await interface.resolve_ac_field_id()

    fetched_keys: set[str] = set()
    referenced_keys: set[str] = set()
    max_updated: datetime | None = None
    people: dict[str, tuple[JiraPerson, set[str]]] = {}
    projects: dict[str, set[str]] = {}
    components: dict[str, set[str]] = {}
    labels: dict[str, set[str]] = {}

    try:
        async for raw in interface.search_issues(effective_jql, expand="renderedFields,changelog"):
            report.fetched += 1
            issue = interface.parse_issue(raw, base_url=interface.server_url, ac_field_id=ac_field_id)
            fetched_keys.add(issue.key)

            if issue.updated_at is not None and (max_updated is None or issue.updated_at > max_updated):
                max_updated = issue.updated_at

            if issue.assignee is not None:
                slug = person_slug(issue.assignee)
                people.setdefault(slug, (issue.assignee, set()))[1].add(issue.key)
            if issue.reporter is not None:
                slug = person_slug(issue.reporter)
                people.setdefault(slug, (issue.reporter, set()))[1].add(issue.key)
            projects.setdefault(issue.project_key, set()).add(issue.key)
            for component in issue.components:
                components.setdefault(component, set()).add(issue.key)
            for label in issue.labels:
                labels.setdefault(label, set()).add(issue.key)

            if issue.epic_key:
                referenced_keys.add(issue.epic_key)
            if issue.parent_key:
                referenced_keys.add(issue.parent_key)
            referenced_keys.update(issue.subtask_keys)
            referenced_keys.update(link.target_key for link in issue.links)

            path = issues_dir / issue_filename(issue.key)
            existing_text = path.read_text(encoding="utf-8") if path.exists() else None
            new_text = render_issue_document(issue, fetched_at=fetched_at, existing=existing_text)

            if existing_text is not None and new_text == existing_text and not version_stale:
                report.unchanged += 1
            else:
                if not dry_run:
                    path.write_text(new_text, encoding="utf-8")
                report.written += 1
    except Exception as exc:  # noqa: BLE001 — record and stop; never advance on failure
        report.errors.append(str(exc))
        new_scope.last_run_status = "partial"
        if not dry_run:
            state.scopes[fp] = new_scope
            save_sync_state(issues_dir, state)
        return report

    # --- Orphans + unreachable tickets (full sweeps only) ---------------
    if is_full_sweep:
        existing_keys = {p.stem for p in issues_dir.glob("*.md")}
        orphan_keys = sorted(existing_keys - fetched_keys)
        report.orphaned = len(orphan_keys)
        for key in orphan_keys:
            await _check_and_mark_unreachable(interface, issues_dir, key, fetched_at, report, dry_run=dry_run)

    # --- Unresolved wikilinks (report only; scan_vault drops these) -----
    on_disk_keys = {p.stem for p in issues_dir.glob("*.md")}
    known_keys = fetched_keys | on_disk_keys
    report.unresolved_link_keys = sorted(referenced_keys - known_keys)

    # --- Entity notes -----------------------------------------------------
    _write_entity_notes(issues_dir, people, projects, components, labels, report, dry_run=dry_run)

    # --- Advance the watermark — only reached on a fully successful pass -
    if max_updated is not None:
        new_scope.last_watermark = _fmt_dt(max_updated)
    new_scope.last_run_status = "ok"
    new_scope.extractor_version = EXTRACTOR_VERSION
    report.watermark_advanced = True
    if not dry_run:
        state.scopes[fp] = new_scope
        save_sync_state(issues_dir, state)

    return report


async def _check_and_mark_unreachable(
    interface: JiraInterface,
    issues_dir: Path,
    key: str,
    fetched_at: datetime,
    report: SweepReport,
    *,
    dry_run: bool,
) -> None:
    """Probe an orphan candidate; patch it unreachable on a definitive 404/403.

    A ticket that still resolves but fell outside the current JQL scope
    stays a plain orphan (reported, never touched). Duck-typed on
    ``status_code`` rather than importing ``jira.exceptions.JIRAError`` —
    this module must stay importable with ``jira`` absent.
    """
    try:
        await interface.get_issue(key)
    except Exception as exc:  # noqa: BLE001 — duck-typed, see docstring
        status = getattr(exc, "status_code", None)
        if status not in (404, 403):
            report.errors.append(f"Could not verify orphan candidate {key}: {exc}")
            return
        if dry_run:
            return
        path = issues_dir / issue_filename(key)
        text = path.read_text(encoding="utf-8")
        patched = _mark_unreachable(text, unreachable_since=_fmt_dt(fetched_at))
        path.write_text(patched, encoding="utf-8")


def _write_entity_notes(
    issues_dir: Path,
    people: dict[str, tuple[JiraPerson, set[str]]],
    projects: dict[str, set[str]],
    components: dict[str, set[str]],
    labels: dict[str, set[str]],
    report: SweepReport,
    *,
    dry_run: bool,
) -> None:
    """Emit person/project/component/label satellite notes, merging keys.

    On an incremental sweep the accumulated ``keys`` sets only cover
    *this run's* tickets — merged here with whatever keys the existing
    on-disk note already lists, so a daily run never rewrites a note down
    to just the one ticket that changed that day.
    """
    written = 0

    for slug, (person, keys) in people.items():
        path = issues_dir / "people" / f"{slug}.md"
        existing_text = path.read_text(encoding="utf-8") if path.exists() else None
        merged = sorted(keys | _existing_note_keys(existing_text))
        new_text = render_person_note(person, merged, existing=existing_text)
        if not dry_run and (existing_text is None or new_text != existing_text):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_text, encoding="utf-8")
        written += 1

    # Project note filenames preserve the raw project key (e.g. "NAV.md")
    # — Jira project keys are already filename-safe, unlike arbitrary
    # component/label names.
    for project_key, keys in projects.items():
        path = issues_dir / "projects" / f"{project_key}.md"
        existing_text = path.read_text(encoding="utf-8") if path.exists() else None
        merged = sorted(keys | _existing_note_keys(existing_text))
        new_text = render_group_note("project", project_key, merged, existing=existing_text)
        if not dry_run and (existing_text is None or new_text != existing_text):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_text, encoding="utf-8")
        written += 1

    for name, keys in components.items():
        path = issues_dir / "components" / f"{group_slug(name)}.md"
        existing_text = path.read_text(encoding="utf-8") if path.exists() else None
        merged = sorted(keys | _existing_note_keys(existing_text))
        new_text = render_group_note("component", name, merged, existing=existing_text)
        if not dry_run and (existing_text is None or new_text != existing_text):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_text, encoding="utf-8")
        written += 1

    for name, keys in labels.items():
        path = issues_dir / "labels" / f"{group_slug(name)}.md"
        existing_text = path.read_text(encoding="utf-8") if path.exists() else None
        merged = sorted(keys | _existing_note_keys(existing_text))
        new_text = render_group_note("label", name, merged, existing=existing_text)
        if not dry_run and (existing_text is None or new_text != existing_text):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_text, encoding="utf-8")
        written += 1

    report.entity_notes = written
