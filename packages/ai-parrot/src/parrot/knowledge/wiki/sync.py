"""Sync engine — moves authored knowledge between two wiki planes (FEAT-461).

``sync_push``/``sync_pull`` replicate memory pages (``origin="memory"``),
their attributed notes, and the ``asserted`` edges touching them, between
the LOCAL plane (env ``"local"``) and a shared REMOTE plane (typically
ArangoDB, resolved from ``target_env``'s effective config). Conflict rule
is last-write-wins per record by :attr:`WikiPageRecord.updated_at`
(TASK-2465); notes merge append-if-absent so a note is never dropped by a
merge; deletes are never propagated (v1 limitation, documented).

The engine talks only :class:`BaseWikiStore` APIs — never a raw driver —
so tests can fake the remote with a second local (sqlite/memory) plane.
"""

from __future__ import annotations

import getpass
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    load_effective_config,
    resolve_arango_params,
)
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, create_wiki_store

logger = logging.getLogger(__name__)

#: Generous cap on `list_pages(...)` calls so a single sync run sees every
#: memory page — `list_pages`'s own default (100) is meant for interactive
#: browsing, not bulk sync.
_SYNC_LIST_LIMIT = 100_000

#: A note line, as appended by `remember()`/`WikiNoteTool` (tools.py:373-375):
#: ``\n\n> **Note (YYYY-MM-DD, <author>):** <text>``.
_NOTE_RE = re.compile(
    r"^> \*\*Note \((?P<date>\d{4}-\d{2}-\d{2}), (?P<author>[^)]+)\):\*\* (?P<text>.*)$",
    re.MULTILINE,
)


class SyncError(RuntimeError):
    """Raised when the remote plane cannot be reached or opened.

    Always names the target host/env, and is only ever raised BEFORE any
    write is attempted — a sync run never partially applies changes
    without logging them.
    """


class SyncReport(BaseModel):
    """Outcome of one :func:`sync_push` / :func:`sync_pull` run.

    Attributes:
        direction: Which way knowledge moved.
        env: The target (remote) environment name.
        created: Records written that did not exist at the destination.
        updated: Records overwritten because the source was strictly newer.
        skipped_older: Records left alone because the destination was
            already as new or newer (LWW).
        skipped_own: Pull-only — source records whose `asserted_by`
            matched the local identity, excluded by default.
        dry_run: Whether this report describes a dry run (nothing applied).
        details: Optional human-readable per-record lines, for CLI
            verbose output.
    """

    direction: Literal["push", "pull"]
    env: str
    created: int = 0
    updated: int = 0
    skipped_older: int = 0
    skipped_own: int = 0
    dry_run: bool = False
    details: list[str] = Field(default_factory=list)


def default_local_identity() -> str:
    """The local identity used to filter own-authored records on pull."""
    return f"human:{getpass.getuser()}"


def _open_plane(root: Path, config: WikiProjectConfig) -> BaseWikiStore:
    """Open a plane for an already-resolved config.

    Mirrors ``cli.py``'s ``_open_store`` — the arangodb branch resolves
    connection params via :func:`resolve_arango_params`; every other
    backend opens (creating if absent) the local on-disk plane.
    """
    storage = config.storage_path(root)
    if config.backend == "arangodb":
        return create_wiki_store(
            storage,
            wiki_name=config.wiki_name,
            backend="arangodb",
            arango_params=resolve_arango_params(config),
            database=config.arango_database or "",
            text_analyzer=config.arango_text_analyzer,
        )
    storage.mkdir(parents=True, exist_ok=True)
    return create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)


async def _open_remote(root: Path, target_env: str) -> tuple[BaseWikiStore, WikiProjectConfig]:
    """Open the remote plane for `target_env`, failing loud and clean.

    Raises:
        SyncError: The remote could not be reached/opened — names the
            target env (and, for arangodb, the resolved host).
    """
    effective = load_effective_config(root, env=target_env)
    config = effective.config
    try:
        store = _open_plane(root, config)
        if config.backend == "arangodb":
            await store.initialize()
    except Exception as exc:  # re-raised below as a typed, clean error
        host = resolve_arango_params(config).get("host") if config.backend == "arangodb" else None
        where = f"{target_env!r} ({host})" if host else repr(target_env)
        raise SyncError(f"Could not reach the remote wiki plane for env {where}: {exc}") from exc
    return store, config


def _note_identity(author: str, date: str, text: str) -> str:
    """Stable identity hash for one note (author + date + text)."""
    return hashlib.sha1(f"{author}|{date}|{text}".encode()).hexdigest()


def _parse_notes(body: str) -> dict[str, tuple[str, str, str]]:
    """Extract every note line from a page body.

    Returns:
        Mapping of identity hash -> ``(date, author, text)``.
    """
    notes: dict[str, tuple[str, str, str]] = {}
    for match in _NOTE_RE.finditer(body or ""):
        date, author, text = match.group("date"), match.group("author"), match.group("text")
        notes[_note_identity(author, date, text)] = (date, author, text)
    return notes


def _strip_notes(body: str) -> str:
    """Return `body` with every note blockquote line removed."""
    return _NOTE_RE.sub("", body or "").rstrip()


def _render_notes(notes: dict[str, tuple[str, str, str]]) -> str:
    """Render a note mapping back into appended blockquote lines.

    Ordered by ``(date, identity hash)`` — date-ordered and otherwise
    deterministic, so a repeated merge is idempotent (never reorders).
    """
    ordered = sorted(notes.items(), key=lambda item: (item[1][0], item[0]))
    return "".join(f"\n\n> **Note ({date}, {author}):** {text}" for _, (date, author, text) in ordered)


def _merge_body(winner_body: str, loser_body: str) -> str:
    """Reconstruct a body: winner's main content + the UNION of notes.

    No note present on either side is ever dropped; non-note content
    follows the LWW winner exclusively.
    """
    merged_notes = {**_parse_notes(loser_body), **_parse_notes(winner_body)}
    return _strip_notes(winner_body) + _render_notes(merged_notes)


async def _synced_memory_pages(store: BaseWikiStore) -> list[dict[str, Any]]:
    """Full (with body) memory-origin page dicts from `store`."""
    stubs = await store.list_pages(origin=["memory"], limit=_SYNC_LIST_LIMIT)
    pages: list[dict[str, Any]] = []
    for stub in stubs:
        full = await store.get_page(stub["concept_id"], include_body=True)
        if full is not None:
            pages.append(full)
    return pages


async def _sync_edges(
    source: BaseWikiStore, destination: BaseWikiStore, concept_ids: set[str]
) -> int:
    """Copy `asserted` edges whose src is one of `concept_ids`.

    `add_edges` is an idempotent upsert on every backend (``INSERT OR
    REPLACE`` / AQL ``UPSERT``), so re-applying an edge that already
    exists at the destination is harmless — this always runs for every
    selected memory page, not only ones that were just written.
    """
    if not concept_ids:
        return 0
    all_edges = await source.dump_edges()
    # `dump_edges()` does not carry provenance on any backend; an edge
    # whose src is a memory page is only ever created via the `asserted`
    # path (`remember()`'s related-page links, toolkit.py:993) — so
    # filtering by src membership IS the provenance filter here.
    to_write = [
        (edge["src"], edge["dst"], edge["rel"], "asserted")
        for edge in all_edges
        if edge["src"] in concept_ids
    ]
    if not to_write:
        return 0
    return await destination.add_edges(to_write)


async def _sync_records(
    *,
    source: BaseWikiStore,
    destination: BaseWikiStore,
    direction: Literal["push", "pull"],
    env: str,
    dry_run: bool,
    skip_asserted_by: str | None,
) -> tuple[SyncReport, set[str]]:
    """Shared push/pull core: select, filter, LWW-compare, write.

    Returns:
        ``(report, concept_ids_selected)`` — the second element feeds
        edge sync, which runs for every selected page regardless of its
        own LWW outcome.
    """
    report = SyncReport(direction=direction, env=env, dry_run=dry_run)
    selected_ids: set[str] = set()

    for page in await _synced_memory_pages(source):
        concept_id = page["concept_id"]
        if skip_asserted_by is not None and page.get("asserted_by") == skip_asserted_by:
            report.skipped_own += 1
            report.details.append(f"skipped_own: {concept_id}")
            continue
        selected_ids.add(concept_id)

        existing = await destination.get_page(concept_id, include_body=True)
        source_stamp = page.get("updated_at") or ""
        if existing is None:
            report.created += 1
            report.details.append(f"created: {concept_id}")
            if not dry_run:
                await destination.upsert_pages([_record_from(page, page.get("body", ""))])
            continue

        dest_stamp = existing.get("updated_at") or ""
        if source_stamp <= dest_stamp:
            report.skipped_older += 1
            report.details.append(f"skipped_older: {concept_id}")
            continue

        report.updated += 1
        report.details.append(f"updated: {concept_id}")
        if not dry_run:
            merged_body = _merge_body(page.get("body", ""), existing.get("body", ""))
            await destination.upsert_pages([_record_from(page, merged_body)])

    return report, selected_ids


def _record_from(page: dict[str, Any], body: str) -> WikiPageRecord:
    """Build the `WikiPageRecord` written to the destination.

    Preserves the SOURCE's `updated_at` verbatim (TASK-2465 semantics) —
    a synced record must never look "just written" at the destination.
    """
    return WikiPageRecord(
        concept_id=page["concept_id"],
        node_id=page.get("node_id"),
        title=page.get("title") or "",
        category=page.get("category") or "concept",
        summary=page.get("summary") or "",
        body=body,
        source_id=page.get("source_id"),
        token_count=page.get("token_count") or 0,
        origin="memory",
        asserted_by=page.get("asserted_by"),
        updated_at=page.get("updated_at"),
    )


async def sync_push(
    root: Path,
    *,
    target_env: str = "dev",
    dry_run: bool = False,
    local_identity: str | None = None,
) -> SyncReport:
    """Push local authored knowledge to the shared plane of `target_env`.

    Args:
        root: Repository root.
        target_env: Environment whose effective config names the remote
            plane (default ``"dev"``).
        dry_run: Compute and return the report; apply nothing, log nothing.
        local_identity: Unused for push (accepted for a symmetric
            signature with :func:`sync_pull`; push never filters by
            authorship — every local memory page moves).

    Returns:
        The sync report.

    Raises:
        SyncError: The remote plane could not be reached.
    """
    del local_identity  # push does not filter by authorship
    local_config = load_effective_config(root, env="local").config
    local_store = _open_plane(root, local_config)
    remote_store, remote_config = await _open_remote(root, target_env)

    report, selected_ids = await _sync_records(
        source=local_store,
        destination=remote_store,
        direction="push",
        env=target_env,
        dry_run=dry_run,
        skip_asserted_by=None,
    )
    if not dry_run and selected_ids:
        await _sync_edges(local_store, remote_store, selected_ids)
    _audit(root, remote_config, "SYNC_PUSH", report)
    return report


async def sync_pull(
    root: Path,
    *,
    target_env: str = "dev",
    include_own: bool = False,
    dry_run: bool = False,
    local_identity: str | None = None,
) -> SyncReport:
    """Pull authored knowledge from the shared plane of `target_env`.

    Args:
        root: Repository root.
        target_env: Environment whose effective config names the remote
            plane (default ``"dev"``).
        include_own: When ``False`` (default), records whose
            `asserted_by` matches `local_identity` are excluded
            (`skipped_own`) — your own memories stay authoritative
            locally. ``True`` switches to pure LWW.
        dry_run: Compute and return the report; apply nothing, log nothing.
        local_identity: Identity string to filter on; defaults to
            :func:`default_local_identity`.

    Returns:
        The sync report.

    Raises:
        SyncError: The remote plane could not be reached.
    """
    identity = local_identity if local_identity is not None else default_local_identity()
    local_config = load_effective_config(root, env="local").config
    local_store = _open_plane(root, local_config)
    remote_store, _remote_config = await _open_remote(root, target_env)

    report, selected_ids = await _sync_records(
        source=remote_store,
        destination=local_store,
        direction="pull",
        env=target_env,
        dry_run=dry_run,
        skip_asserted_by=None if include_own else identity,
    )
    if not dry_run and selected_ids:
        await _sync_edges(remote_store, local_store, selected_ids)
    _audit(root, local_config, "SYNC_PULL", report)
    return report


def _audit(root: Path, config: WikiProjectConfig, operation: str, report: SyncReport) -> None:
    """Log one bookkeeper entry per applied change — none on a dry run."""
    if report.dry_run:
        return
    applied = report.created + report.updated
    if applied == 0:
        return
    wiki_dir = config.storage_path(root)
    details = (
        f"env: {report.env}, created: {report.created}, updated: {report.updated}, "
        f"skipped_older: {report.skipped_older}, skipped_own: {report.skipped_own}"
    )
    WikiBookkeeper().log_operation(wiki_dir, operation, details)
