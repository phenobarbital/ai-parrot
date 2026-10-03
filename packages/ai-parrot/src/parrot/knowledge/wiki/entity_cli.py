"""Typed entity authoring, listing and deterministic local back-fill.

This module deliberately does NOT import ``parrot.knowledge.wiki.cli``: the
``entity`` group is registered lazily from ``cli.py``, so it resolves the
project, store and federation through the underlying primitives directly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import click

from parrot.knowledge.wiki.entities import (
    EntityValidationError,
    normalize_frontmatter,
    parse_leading_yaml,
)
from parrot.knowledge.wiki.federation import FederatedWikiStore, resolve_namespaces
from parrot.knowledge.wiki.file_suffixes import DOC_SUFFIXES
from parrot.knowledge.wiki.identity import authoring_identity
from parrot.knowledge.wiki.project import (
    WikiConfigError,
    WikiProjectConfig,
    find_project_root,
    load_effective_config,
    load_global_registry,
    merge_namespaces,
    sqlite_policy_from_config,
    wiki_write_lock,
)
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, create_wiki_store

logger = logging.getLogger("wikitoolkit.entity_cli")

#: Pages processed per reindex batch.
REINDEX_BATCH_SIZE = 500
#: Seconds a write waits for a contended store lock.
_LOCK_WAIT_SECONDS = 5.0
#: Leading repo-scan wrapper: ``# <path>`` header followed by ``## Content``.
_WRAPPER_RE = re.compile(r"\A# [^\n]*\n\n## Content(?: \(truncated\))?\n(?P<content>.*)\Z", re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _run(coro: Any) -> Any:
    """Run an async store operation from a sync click command."""
    return asyncio.run(coro)


def _env_setting(name: str) -> str | None:
    """Read a wiki env setting through navconfig, falling back to ``os.environ``."""
    try:
        from navconfig import config as _nav

        value = _nav.get(name, fallback=None)
    except Exception:  # noqa: BLE001 - navconfig is optional; the env is enough
        value = os.environ.get(name)
    return value or None


def _fail_validation(exc: EntityValidationError) -> click.exceptions.Exit:
    """Report a strict validation error with its stable code and return the exit."""
    click.echo(f"{exc.code}: {exc}", err=True)
    return click.exceptions.Exit(2)


def _find_root(path_: str | None) -> Path:
    """Resolve the repo root, aborting with guidance when absent."""
    if path_:
        root = Path(path_).resolve()
        if not root.is_dir():
            raise click.ClickException(f"Not a directory: {root}")
        return root
    found = find_project_root()
    if found is None:
        raise click.ClickException(
            "No wiki project found (no .parrot/wiki.json or .git upwards from here). "
            "Run inside a repository or pass --path."
        )
    return found


def _resolve_project(path_: str | None, backend_opt: str | None) -> tuple[Path, WikiProjectConfig]:
    """Resolve the root and the effective config, applying the backend override."""
    root = _find_root(path_)
    try:
        config = load_effective_config(root).config
    except WikiConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    backend = backend_opt or _env_setting("WIKI_STORE_BACKEND")
    if backend:
        config.backend = backend  # type: ignore[assignment]
    return root, config


def _open_project_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore:
    """Create the local retrieval-plane store of a project."""
    storage = config.storage_path(root)
    if config.backend == "arangodb":
        from parrot.knowledge.wiki.project import resolve_arango_params

        return create_wiki_store(
            storage,
            wiki_name=config.wiki_name,
            backend="arangodb",
            arango_params=resolve_arango_params(config),
            database=config.arango_database or "",
            text_analyzer=config.arango_text_analyzer,
        )
    storage.mkdir(parents=True, exist_ok=True)
    return create_wiki_store(
        storage,
        wiki_name=config.wiki_name,
        backend=config.backend,
        sqlite_policy=sqlite_policy_from_config(config),
    )


def _open_local_write_store(
    path_: str | None, store_opt: str | None, backend_opt: str | None
) -> tuple[BaseWikiStore, Path]:
    """Open the true local plane for writing, creating it lazily.

    Precedence matches the other authoring commands:
    ``--store`` > ``--path`` project > ``WIKI_STORE`` env > detected project.

    Returns:
        ``(store, storage_dir)``.
    """
    store_override = store_opt
    if not store_override and not path_:
        store_override = _env_setting("WIKI_STORE")
    if store_override:
        backend = backend_opt or _env_setting("WIKI_STORE_BACKEND") or "sqlite"
        storage_dir = Path(store_override).expanduser()
        storage_dir.mkdir(parents=True, exist_ok=True)
        return create_wiki_store(storage_dir, backend=backend), storage_dir
    root, config = _resolve_project(path_, backend_opt)
    return _open_project_store(root, config), config.storage_path(root)


def _open_read_store(
    path_: str | None, store_opt: str | None, backend_opt: str | None, ns_opt: str | None
) -> BaseWikiStore:
    """Open the local plane federated with its declared namespaces, honouring ``--ns``."""
    store_override = store_opt
    if not store_override and not path_:
        store_override = _env_setting("WIKI_STORE")
    if store_override:
        backend = backend_opt or _env_setting("WIKI_STORE_BACKEND") or "sqlite"
        storage_dir = Path(store_override).expanduser()
        if not storage_dir.is_dir():
            raise click.ClickException(f"No wiki store directory: {storage_dir}")
        if ns_opt not in (None, "local"):
            raise click.ClickException(
                "--store targets one pre-built store and never federates; drop --store to read namespaces."
            )
        return create_wiki_store(storage_dir, backend=backend)
    root, config = _resolve_project(path_, backend_opt)
    if not config.is_built(root):
        raise click.ClickException(f"Wiki not built yet for {root}. Run `wikitoolkit build` first.")
    local = _open_project_store(root, config)
    try:
        registry = load_global_registry()
    except WikiConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    declared = merge_namespaces(config.namespaces, registry.namespaces)
    if ns_opt is None or ns_opt == "all":
        only: set[str] | None = None
    else:
        only = {part.strip() for part in ns_opt.split(",") if part.strip() and part.strip() != "local"}
        unknown = sorted(only - set(declared))
        if unknown:
            known = ", ".join(sorted(declared)) or "(none declared)"
            raise click.ClickException(
                f"Unknown namespace {', '.join(unknown)!r}. Known: {known} (plus 'all', 'local')."
            )
        if not only:
            return local
    if not declared:
        return local
    handles, skipped = _run(resolve_namespaces(root, config, only=only))
    federated = FederatedWikiStore(local, config.wiki_name, handles, skipped)
    try:
        return federated.scoped(ns_opt)
    except KeyError as exc:
        name = str(exc.args[0])
        skip = next((s for s in skipped if s.name == name), None)
        if skip is not None:
            raise click.ClickException(f"Namespace {name!r} is {skip.reason}: {skip.detail}.") from exc
        raise click.ClickException(f"Unknown namespace {name!r}.") from exc


def _require_attrs_support(store: BaseWikiStore) -> None:
    """Fail actionably when the backend cannot persist page attributes."""
    if getattr(store, "supports_attrs", False) is not True:
        raise click.ClickException(
            "This wiki backend does not support page attributes. Use the sqlite backend "
            "(`--backend sqlite` or WIKI_STORE_BACKEND=sqlite) for entity commands."
        )


def _log_operation(storage_dir: Path, operation: str, details: str) -> None:
    """Append an audit line to the plane's log.md; never fail the command."""
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

    try:
        WikiBookkeeper().log_operation(storage_dir, operation, details)
    except Exception:  # noqa: BLE001 - the audit trail must never break the write
        logger.warning("Could not log %s operation", operation, exc_info=True)


def _entity_page_id(type_: str, title: str) -> str:
    """Build the deterministic ``entity:<type>:<slug-hash>`` page id."""
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")[:40].strip("-") or "untitled"
    digest = hashlib.sha1(f"{type_}::{title}".encode()).hexdigest()[:8]
    return f"entity:{type_}:{slug}-{digest}"


def _validate_bound(value: str | None, name: str) -> str | None:
    """Validate an optional ISO date bound, exiting 2 with a stable code on error."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise _fail_validation(EntityValidationError("E_ENTITY_DATE", f"Invalid --{name}: {value!r}")) from None


@click.group(name="entity")
def entity() -> None:
    """Typed entities: add, list and reindex page attributes."""


@entity.command("add")
@click.argument("type_")
@click.argument("title")
@click.option("--body", default=None, help="Page body (default: the title).")
@click.option("--project", default=None, help="Owning project.")
@click.option("--status", default=None, help="Status valid for the entity type.")
@click.option("--date", "date_", default=None, help="ISO date (YYYY-MM-DD).")
@click.option("--due", default=None, help="ISO due date (YYYY-MM-DD).")
@click.option("--owner", default=None, help="Owner identity.")
@click.option("--link", "links", multiple=True, help="Existing page id to link to (repeatable).")
@click.option("--rel", default="related_to", help="Relation for --link edges.")
@click.option("--by", default=None, help="Identity authoring this entity.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@click.option("--path", "path_", default=None, help="Repo root (default: auto-detect).")
@click.option("--store", "store_opt", default=None, help="Write to this wiki store directory.")
@click.option("--backend", "backend_opt", default=None, help="Backend (default: sqlite / WIKI_STORE_BACKEND).")
def add_entity(
    type_: str,
    title: str,
    body: str | None,
    project: str | None,
    status: str | None,
    date_: str | None,
    due: str | None,
    owner: str | None,
    links: tuple[str, ...],
    rel: str,
    by: str | None,
    as_json: bool,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
) -> None:
    """Create a strictly validated authored entity and optional asserted links."""
    resolved_title = title.strip()
    if not resolved_title:
        raise click.UsageError("Entity title must not be empty.")
    raw = {
        "type": type_,
        "status": status,
        "project": project,
        "date": date_,
        "due": due,
        "owner": owner,
    }
    try:
        attrs = normalize_frontmatter({k: v for k, v in raw.items() if v is not None}, source="authored", strict=True)
    except EntityValidationError as exc:
        raise _fail_validation(exc) from exc
    if attrs.type is None:  # pragma: no cover - strict normalization rejects unknown types
        raise _fail_validation(EntityValidationError("E_ENTITY_TYPE", f"Unknown entity type: {type_}"))
    entity_type = str(attrs.type)

    store, storage_dir = _open_local_write_store(path_, store_opt, backend_opt)
    _require_attrs_support(store)
    asserted_by = authoring_identity(by)
    page_id = _entity_page_id(entity_type, resolved_title)
    page_body = body if body else resolved_title

    from parrot.knowledge.wiki.store import estimate_tokens

    async def _write() -> tuple[bool, list[str], list[str]]:
        existing = await store.get_page(page_id, include_body=False)
        await store.upsert_pages(
            [
                WikiPageRecord(
                    concept_id=page_id,
                    node_id=page_id,
                    title=resolved_title,
                    category=entity_type,
                    summary=page_body[:300],
                    body=page_body,
                    token_count=estimate_tokens(page_body),
                    origin="authored",
                    asserted_by=asserted_by,
                    attrs=attrs.to_rows(),
                )
            ]
        )
        linked: list[str] = []
        skipped: list[str] = []
        for target in links:
            page = await store.get_page(target, include_body=False)
            if page is None:
                skipped.append(target)
                continue
            await store.add_edges([(page_id, page["concept_id"], rel, "asserted")])
            linked.append(page["concept_id"])
        return existing is not None, linked, skipped

    with wiki_write_lock(storage_dir, timeout=_LOCK_WAIT_SECONDS) as acquired:
        if not acquired:
            raise click.ClickException("Another wikitoolkit writer holds the store lock; retry shortly.")
        existed, linked, skipped_links = _run(_write())
        _log_operation(
            storage_dir,
            "ENTITY",
            f"page_id: {page_id}, type: {entity_type}, title: {resolved_title!r}, by: {asserted_by}",
        )

    result = {
        "page_id": page_id,
        "type": entity_type,
        "title": resolved_title,
        "status": "updated" if existed else "created",
        "asserted_by": asserted_by,
        "attrs": attrs.to_rows(),
        "linked": linked,
        "skipped_links": skipped_links,
    }
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(f"{'Updated' if existed else 'Created'} {entity_type} {page_id}: {resolved_title!r}")
    for target in linked:
        click.echo(f"  linked -> {target} ({rel})")
    for target in skipped_links:
        click.echo(f"  [skipped link: no page {target!r}]")


@entity.command("list")
@click.option("--type", "type_", default=None, help="Entity type filter.")
@click.option("--status", default=None, help="Canonical status filter.")
@click.option("--project", default=None, help="Project filter.")
@click.option("--since", default=None, help="Inclusive lower ISO-date bound on the date attribute.")
@click.option("--until", default=None, help="Inclusive upper ISO-date bound on the date attribute.")
@click.option("--ns", "ns_opt", default=None, help="Namespace(s) to read: name, comma list, 'all' or 'local'.")
@click.option("--limit", type=click.IntRange(min=1), default=200, show_default=True, help="Maximum rows.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@click.option("--path", "path_", default=None, help="Repo root (default: auto-detect).")
@click.option("--store", "store_opt", default=None, help="Read this pre-built wiki store directly.")
@click.option("--backend", "backend_opt", default=None, help="Backend (default: sqlite / WIKI_STORE_BACKEND).")
def list_entities(
    type_: str | None,
    status: str | None,
    project: str | None,
    since: str | None,
    until: str | None,
    ns_opt: str | None,
    limit: int,
    as_json: bool,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
) -> None:
    """List matching entity stubs from selected readable planes."""
    since_bound = _validate_bound(since, "since")
    until_bound = _validate_bound(until, "until")
    filters: dict[str, str] = {}
    if type_:
        filters["type"] = type_.strip().lower()
    if status:
        filters["status"] = status.strip().lower()
    if project:
        filters["project"] = project
    store = _open_read_store(path_, store_opt, backend_opt, ns_opt)
    _require_attrs_support(store)
    date_key = "date" if (since_bound or until_bound) else None
    try:
        rows = _run(store.list_by_attrs(filters, date_key=date_key, since=since_bound, until=until_bound, limit=limit))
    except ValueError as exc:
        raise _fail_validation(EntityValidationError("E_ENTITY_DATE", str(exc))) from exc
    if as_json:
        click.echo(json.dumps({"count": len(rows), "entities": rows}, indent=2, default=str))
        return
    if not rows:
        click.echo("No matching entities.")
        return
    for row in rows:
        attrs = row.get("attrs") or {}
        click.echo(
            "\t".join(
                [
                    str(row.get("concept_id", "")),
                    attrs.get("type", "-"),
                    attrs.get("status", "-"),
                    attrs.get("project", "-"),
                    attrs.get("date", "-"),
                    str(row.get("title", "")),
                ]
            )
        )


def _frontmatter_text(page: dict[str, Any]) -> tuple[str | None, str]:
    """Return the text holding leading YAML for a stored page, or a skip reason.

    Only the verified leading repo-scan ``## Content`` wrapper is unwrapped,
    and only for document-suffix ``file:`` pages. Vault pages discard their
    frontmatter at ingest time, so nothing can be reconstructed for them.

    Returns:
        ``(text, reason)`` — ``text`` is ``None`` when the page is skipped.
    """
    body = str(page.get("body") or "")
    concept_id = str(page.get("concept_id") or "")
    if concept_id.startswith("file:") and PurePosixPath(concept_id[len("file:") :]).suffix.lower() in DOC_SUFFIXES:
        match = _WRAPPER_RE.match(body)
        if match:
            return match.group("content"), ""
    if body.lstrip("\n").startswith("---"):
        return body.lstrip("\n"), ""
    return None, "no_frontmatter"


@entity.command("reindex")
@click.option("--category", default=None, help="Only reindex pages of this category.")
@click.option("--dry-run", is_flag=True, help="Report what would change without writing or auditing.")
@click.option("--ns", "ns_opt", default=None, help="Only the local plane may be reindexed.")
@click.option("--path", "path_", default=None, help="Repo root (default: auto-detect).")
@click.option("--store", "store_opt", default=None, help="Reindex this wiki store directory.")
@click.option("--backend", "backend_opt", default=None, help="Backend (default: sqlite / WIKI_STORE_BACKEND).")
def reindex_entities(
    category: str | None,
    dry_run: bool,
    ns_opt: str | None,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
) -> None:
    """Back-fill preserved source frontmatter in one writable local plane."""
    if ns_opt not in (None, "local"):
        raise click.UsageError(f"reindex only writes the local plane; `--ns {ns_opt}` is a foreign target.")
    store, storage_dir = _open_local_write_store(path_, store_opt, backend_opt)
    _require_attrs_support(store)

    async def _reindex() -> dict[str, int]:
        counts = {"scanned": 0, "updated": 0, "unchanged": 0, "skipped": 0}
        # list_pages has no offset/cursor: snapshot the whole inventory once,
        # before any write, then batch that stable list of ids.
        total = int((await store.stats()).get("pages", 0))
        stubs = await store.list_pages(category=category, limit=max(total, 1) + 1)
        ids = list(dict.fromkeys(str(stub["concept_id"]) for stub in stubs))
        for start in range(0, len(ids), REINDEX_BATCH_SIZE):
            for concept_id in ids[start : start + REINDEX_BATCH_SIZE]:
                counts["scanned"] += 1
                page = await store.get_page(concept_id, include_body=True)
                if page is None or page.get("origin") in ("authored", "memory"):
                    counts["skipped"] += 1
                    continue
                text, _reason = _frontmatter_text(page)
                frontmatter = parse_leading_yaml(text) if text is not None else None
                if frontmatter is None:
                    counts["skipped"] += 1
                    continue
                rows = normalize_frontmatter(frontmatter, source="markdown").to_rows()
                if rows == dict(page.get("attrs") or {}):
                    counts["unchanged"] += 1
                    continue
                counts["updated"] += 1
                if not dry_run:
                    await store.upsert_attrs(concept_id, rows, replace=True)
        return counts

    if dry_run:
        counts = _run(_reindex())
    else:
        with wiki_write_lock(storage_dir, timeout=_LOCK_WAIT_SECONDS) as acquired:
            if not acquired:
                raise click.ClickException("Another wikitoolkit writer holds the store lock; retry shortly.")
            counts = _run(_reindex())
            _log_operation(
                storage_dir,
                "REINDEX",
                f"scanned: {counts['scanned']}, updated: {counts['updated']}, "
                f"unchanged: {counts['unchanged']}, skipped: {counts['skipped']}"
                + (f", category: {category}" if category else ""),
            )
    verb = "would update" if dry_run else "updated"
    click.echo(
        f"Reindex{' (dry run)' if dry_run else ''}: scanned {counts['scanned']}, {verb} {counts['updated']}, "
        f"unchanged {counts['unchanged']}, skipped {counts['skipped']}."
    )
