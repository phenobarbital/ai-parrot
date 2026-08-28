"""Obsidian sync — mirror LLM Wiki planes into an Obsidian vault (one-way).

``sync_obsidian`` projects wiki pages from one or more planes (the local
project plane and/or declared federated namespaces) into an Obsidian
vault as markdown notes with YAML frontmatter. What moves and where it
lands is driven by :class:`~parrot.knowledge.wiki.project.ObsidianSyncConfig`
(``obsidian_sync`` in ``.parrot/wiki.json``): the selected page
*categories* and the vault *folder* each category maps onto.

Design points:

* **One-way, wiki -> vault.** The vault-to-wiki direction already exists
  (``wikitoolkit build`` vault mode / a ``vault``-kind namespace); this
  module is the reverse projection, so agents' knowledge becomes
  browsable, linkable Obsidian notes.
* **Marker-guarded.** Every synced note carries ``wiki_sync: <wiki_name>``
  frontmatter. Prune only ever deletes notes carrying that marker —
  hand-written notes are never touched.
* **Deterministic and idempotent.** Note rendering is stable; an
  unchanged page produces byte-identical text and is skipped, so a
  repeated run reports ``unchanged`` instead of rewriting the vault.
* **Edges become wikilinks.** ``asserted``/extracted edges between two
  synced pages render as a ``## Related`` section of ``[[wikilinks]]``,
  so the wiki graph is visible in Obsidian's graph view.

Writes go through the shared vault interface
(:func:`parrot.interfaces.obsidian.create_vault_backend`) — the same
engine behind ``ObsidianToolkit`` — never raw file I/O.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from parrot.knowledge.okf.utils import flatten_concept_id_for_filename
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.export import category_dir
from parrot.knowledge.wiki.federation import resolve_namespaces
from parrot.knowledge.wiki.project import (
    ObsidianSyncConfig,
    WikiProjectConfig,
    load_effective_config,
    load_global_registry,
    merge_namespaces,
    resolve_vault_dir,
)
from parrot.knowledge.wiki.store import BaseWikiStore

# Package-internal reuse: `_open_plane` is sync.py's canonical
# "open the plane for a resolved config" helper; both modules live in
# the same package and must open planes identically.
from parrot.knowledge.wiki.sync import _open_plane

logger = logging.getLogger(__name__)

#: Frontmatter key marking a note as managed by this sync (prune guard).
SYNC_MARKER_KEY = "wiki_sync"

#: Frontmatter key carrying the owning project's scope identity —
#: ``<wiki_name>@<digest of the resolved repo root>``. Prune requires an
#: exact scope match, so two projects that happen to share a vault AND a
#: ``wiki_name`` (the config default is the literal ``"codebase"``) can
#: never prune each other's notes.
SYNC_SCOPE_KEY = "wiki_scope"

#: Frontmatter key carrying the source page's stable ``concept_id``.
SYNC_ID_KEY = "wiki_id"

#: Frontmatter key carrying the source plane name (``local`` or a namespace).
SYNC_NAMESPACE_KEY = "namespace"

#: The name of the project's own plane on the ``namespaces`` selector.
LOCAL_PLANE = "local"


class ObsidianSyncError(RuntimeError):
    """Raised when the sync cannot run (no vault, unbuilt plane, unknown
    namespace) — always before the first note is touched — or, wrapping
    an unexpected mid-apply failure, after the partial report has been
    audited to the bookkeeper."""


def project_scope(root: Path, wiki_name: str) -> str:
    """Stable scope identity written as :data:`SYNC_SCOPE_KEY`.

    ``wiki_name`` alone is not unique (it defaults to ``"codebase"``), so
    the resolved repo root is digested in. Moving the repo changes the
    scope, which fails SAFE: old notes are simply never pruned again.
    """
    digest = hashlib.sha1(str(Path(root).resolve()).encode()).hexdigest()[:12]
    return f"{wiki_name}@{digest}"


def _safe_segment(value: str, fallback: str = "other") -> str:
    """Sanitize one vault path segment derived from store content.

    Page categories (and namespace names, which may carry ``:``) come
    from data, not config, so they never get to inject separators or
    traversal into the vault-relative path — the vault backend's own
    sandbox would refuse the write, but only with an untyped mid-run
    crash. Separators collapse to ``-``; leading/trailing dots are
    stripped; an empty result falls back.
    """
    clean = re.sub(r"[\\/:]+", "-", str(value)).strip().strip(".")
    if not clean:
        return fallback
    return clean


class ObsidianSyncReport(BaseModel):
    """Outcome of one :func:`sync_obsidian` run.

    Attributes:
        vault: Resolved vault root the notes were written into.
        root_folder: Vault folder holding the mirror.
        namespaces: Plane names actually synced (skips excluded).
        created: Notes written that did not exist in the vault.
        updated: Notes rewritten because the page changed.
        unchanged: Notes skipped because the rendered text was identical.
        pruned: Marker-carrying notes deleted for vanished/deselected pages.
        skipped_namespaces: Human-readable ``name: reason`` lines for
            requested namespaces that could not be opened.
        dry_run: Whether this report describes a dry run (nothing applied).
        details: Per-note lines for verbose CLI output.
    """

    vault: str = ""
    root_folder: str = ""
    namespaces: list[str] = Field(default_factory=list)
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    pruned: int = 0
    skipped_namespaces: list[str] = Field(default_factory=list)
    dry_run: bool = False
    details: list[str] = Field(default_factory=list)


def folder_for_category(category: str, sync_config: ObsidianSyncConfig) -> str:
    """Vault folder a category maps onto.

    An explicit override wins — including an EMPTY override, meaning
    "no per-category subfolder" (mirrors how an empty ``root_folder`` is
    honored). Otherwise the pluralized category directory (sanitized:
    the category value is page data, not config).
    """
    if category in sync_config.folders:
        return sync_config.folders[category]
    return _safe_segment(category_dir(category))


def note_relpath(
    sync_config: ObsidianSyncConfig, namespace: str, category: str, concept_id: str
) -> str:
    """Vault-relative path of the note mirroring one page.

    Layout: ``<root_folder>/[<namespace>/]<category folder>/<flat id>.md``
    — the local plane writes directly under the root folder, foreign
    namespaces each get their own (sanitized) subtree; empty segments
    are skipped. Known caveat (shared with the OKF export convention):
    two distinct concept_ids whose flattened stems collide within one
    folder resolve to the same note path (last write wins), and a local
    page id equal to a namespace's folder name would clash file-vs-dir.
    """
    ns_segment = "" if namespace == LOCAL_PLANE else _safe_segment(namespace)
    segments = (
        sync_config.root_folder,
        ns_segment,
        folder_for_category(category, sync_config),
        f"{flatten_concept_id_for_filename(concept_id)}.md",
    )
    return "/".join(part for part in segments if part)


def render_note(
    page: dict[str, Any],
    related: list[tuple[str, str, str]],
    *,
    wiki_name: str,
    scope: str,
    namespace: str,
) -> str:
    """Render one wiki page as a deterministic Obsidian note.

    Args:
        page: Full page dict (``dump_pages`` shape, body included).
        related: ``(link_target, display_title, rel)`` rows for the
            ``## Related`` section; targets are vault paths sans ``.md``.
        wiki_name: Written as the :data:`SYNC_MARKER_KEY` marker value.
        scope: Project scope identity (:func:`project_scope`) written as
            :data:`SYNC_SCOPE_KEY` — the prune ownership guard.
        namespace: Source plane name (``local`` or a namespace).

    Returns:
        The full note text (frontmatter + body + related section).
    """
    category = str(page.get("category") or "concept")
    title = str(page.get("title") or page["concept_id"])
    frontmatter: dict[str, Any] = {
        SYNC_MARKER_KEY: wiki_name,
        SYNC_SCOPE_KEY: scope,
        SYNC_ID_KEY: page["concept_id"],
        SYNC_NAMESPACE_KEY: namespace,
        "category": category,
        "aliases": [title],
        "tags": [f"wiki/{category}"],
        "updated": page.get("updated_at") or "",
    }
    summary = str(page.get("summary") or "")
    if summary:
        frontmatter["summary"] = summary
    block = yaml.dump(
        frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    parts = [f"---\n{block}---\n"]
    body = str(page.get("body") or summary or "").rstrip()
    if body:
        parts.append(f"\n{body}\n")
    if related:
        lines = "\n".join(
            f"- [[{target}|{label}]] — {rel}" for target, label, rel in related
        )
        parts.append(f"\n## Related\n\n{lines}\n")
    return "".join(parts)


def _resolve_settings(
    config: WikiProjectConfig,
    *,
    namespaces: Sequence[str] | None,
    categories: Sequence[str] | None,
    prune: bool | None,
) -> tuple[ObsidianSyncConfig, list[str], set[str] | None, bool]:
    """Merge per-call overrides over the configured sync settings.

    Returns:
        ``(sync_config, plane_names, category_filter, prune)`` — the
        effective settings; ``category_filter`` is ``None`` for "all".
    """
    sync_config = config.obsidian_sync or ObsidianSyncConfig()
    names = list(namespaces) if namespaces else list(sync_config.namespaces)
    if not names:
        names = [LOCAL_PLANE]
    selected = list(categories) if categories else list(sync_config.categories)
    category_filter = set(selected) if selected else None
    effective_prune = sync_config.prune if prune is None else prune
    return sync_config, names, category_filter, effective_prune


def _expand_planes(
    names: list[str], declared: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Expand the plane selector into ``(include_local, foreign_names)``.

    Raises:
        ObsidianSyncError: A selector names an undeclared namespace.
    """
    if "all" in names:
        return True, sorted(declared)
    include_local = LOCAL_PLANE in names
    foreign = [name for name in dict.fromkeys(names) if name != LOCAL_PLANE]
    unknown = sorted(set(foreign) - set(declared))
    if unknown:
        listing = ", ".join(sorted(declared)) or "(none declared)"
        raise ObsidianSyncError(
            f"Unknown namespace(s): {', '.join(unknown)}. Known: {listing} "
            "(plus 'local', 'all'). Add one with `wikitoolkit ns add`."
        )
    return include_local, foreign


async def _sync_plane(
    vault: Any,
    plane_name: str,
    store: BaseWikiStore,
    *,
    wiki_name: str,
    scope: str,
    sync_config: ObsidianSyncConfig,
    category_filter: set[str] | None,
    dry_run: bool,
    report: ObsidianSyncReport,
) -> set[str]:
    """Mirror one plane's selected pages into the vault.

    Returns:
        The ``concept_id`` set selected for this plane (feeds prune).
    """
    pages = await store.dump_pages()
    if category_filter is not None:
        pages = [
            p for p in pages if str(p.get("category") or "concept") in category_filter
        ]
    selected = {p["concept_id"] for p in pages}
    titles = {p["concept_id"]: str(p.get("title") or p["concept_id"]) for p in pages}
    paths = {
        p["concept_id"]: note_relpath(
            sync_config,
            plane_name,
            str(p.get("category") or "concept"),
            p["concept_id"],
        )
        for p in pages
    }

    related_by_src: dict[str, list[tuple[str, str, str]]] = {}
    for edge in await store.dump_edges():
        src, dst = edge["src"], edge["dst"]
        if src in selected and dst in selected and src != dst:
            related_by_src.setdefault(src, []).append(
                (paths[dst][:-3], titles[dst], str(edge.get("rel") or "references"))
            )
    for rows in related_by_src.values():
        rows.sort()

    for page in sorted(pages, key=lambda p: p["concept_id"]):
        concept_id = page["concept_id"]
        rel_path = paths[concept_id]
        text = render_note(
            page,
            related_by_src.get(concept_id, []),
            wiki_name=wiki_name,
            scope=scope,
            namespace=plane_name,
        )
        try:
            existing: str | None = await vault.read_note(rel_path)
        except FileNotFoundError:
            existing = None
        if existing == text:
            report.unchanged += 1
            report.details.append(f"unchanged: {rel_path}")
            continue
        if existing is None:
            report.created += 1
            report.details.append(f"created: {rel_path}")
        else:
            report.updated += 1
            report.details.append(f"updated: {rel_path}")
        if not dry_run:
            await vault.write_note(rel_path, text, overwrite=True)
    return selected


async def _prune_vanished(
    vault: Any,
    *,
    wiki_name: str,
    scope: str,
    sync_config: ObsidianSyncConfig,
    synced: dict[str, set[str]],
    dry_run: bool,
    report: ObsidianSyncReport,
) -> None:
    """Delete marker-carrying notes whose page vanished or was deselected.

    Only notes whose frontmatter carries ``wiki_sync == wiki_name`` AND
    an exactly matching ``wiki_scope`` (this project's identity — two
    projects sharing a vault and a wiki_name never prune each other) AND
    a ``namespace`` that was actually synced in THIS run are candidates —
    a skipped namespace's notes are left alone (its pages were never
    enumerated), and hand-written notes are never touched.
    """
    folder = sync_config.root_folder or None
    try:
        infos = await vault.list_files(folder=folder, suffixes=frozenset({".md"}))
    except FileNotFoundError:
        return
    for info in infos:
        try:
            note = await vault.get_note(info.path)
        except (FileNotFoundError, UnicodeDecodeError, ValueError) as exc:
            logger.warning("prune: skipping unreadable note %s: %s", info.path, exc)
            continue
        front = note.frontmatter
        if front.get(SYNC_MARKER_KEY) != wiki_name:
            continue
        if front.get(SYNC_SCOPE_KEY) != scope:
            continue
        plane = front.get(SYNC_NAMESPACE_KEY)
        if plane not in synced:
            continue
        if front.get(SYNC_ID_KEY) in synced[plane]:
            continue
        report.pruned += 1
        report.details.append(f"pruned: {info.path}")
        if not dry_run:
            await vault.delete_note(info.path)


async def sync_obsidian(
    root: Path,
    *,
    vault: str | Path | None = None,
    namespaces: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    prune: bool | None = None,
    dry_run: bool = False,
    env: str | None = None,
) -> ObsidianSyncReport:
    """Mirror the selected wiki planes into the Obsidian vault.

    Args:
        root: Repository root.
        vault: Vault root override; falls back to the ``obsidian_sync``
            config, then the project ``vault_dir``, then the project root
            when it is itself a vault.
        namespaces: Plane selector override (``local``, declared
            namespace names, or ``all``); defaults to the configured
            ``obsidian_sync.namespaces``.
        categories: Category filter override; defaults to the configured
            ``obsidian_sync.categories`` (empty = every category).
        prune: Prune override; defaults to ``obsidian_sync.prune``.
        dry_run: Compute and return the report; write nothing.
        env: Wiki environment override (``WIKI_ENV`` resolution otherwise).

    Returns:
        The sync report.

    Raises:
        ObsidianSyncError: No vault is configured (or the configured one
            does not exist), the local plane is not built, the selector
            names an undeclared namespace — or, wrapping the cause, a
            run aborted mid-apply (the partial report is audited first).
    """
    from parrot.interfaces.obsidian import create_vault_backend

    config = load_effective_config(root, env=env).config
    sync_config, names, category_filter, effective_prune = _resolve_settings(
        config, namespaces=namespaces, categories=categories, prune=prune
    )

    declared = merge_namespaces(config.namespaces, load_global_registry().namespaces)
    include_local, foreign = _expand_planes(names, declared)

    override = vault or sync_config.vault_dir
    vault_dir = resolve_vault_dir(root, config, override=override)
    if vault_dir is None:
        configured = override or config.vault_dir
        if configured:
            raise ObsidianSyncError(
                f"Configured Obsidian vault directory does not exist: {configured}"
            )
        raise ObsidianSyncError(
            "No Obsidian vault configured. Pass --vault, or set "
            "`obsidian_sync.vault_dir` (or `vault_dir`) in .parrot/wiki.json."
        )

    report = ObsidianSyncReport(
        vault=str(vault_dir),
        root_folder=sync_config.root_folder,
        dry_run=dry_run,
    )

    planes: list[tuple[str, BaseWikiStore]] = []
    if include_local:
        if not config.is_built(root):
            raise ObsidianSyncError(
                "The local wiki plane is not built yet — run `wikitoolkit build` "
                "first (an empty plane plus --prune would empty the mirror)."
            )
        local_store = _open_plane(root, config)
        if config.backend == "arangodb":
            # Server-hosted plane — connect eagerly (idempotent), mirroring
            # sync.py's `_open_remote`, so an unreachable server fails with
            # a clear message before any vault write is attempted.
            try:
                await local_store.initialize()
            except Exception as exc:
                raise ObsidianSyncError(
                    f"Could not reach the ArangoDB wiki plane for "
                    f"{config.wiki_name!r}: {exc}"
                ) from exc
        planes.append((LOCAL_PLANE, local_store))
    if foreign:
        handles, skips = await resolve_namespaces(root, config, only=set(foreign))
        for skip in skips:
            report.skipped_namespaces.append(f"{skip.name}: {skip.reason} — {skip.detail}")
        planes.extend((handle.name, handle.store) for handle in handles)

    scope = project_scope(root, config.wiki_name)
    backend = create_vault_backend(backend="local", vault_path=vault_dir)
    await backend.open()
    try:
        synced: dict[str, set[str]] = {}
        for plane_name, store in planes:
            synced[plane_name] = await _sync_plane(
                backend,
                plane_name,
                store,
                wiki_name=config.wiki_name,
                scope=scope,
                sync_config=sync_config,
                category_filter=category_filter,
                dry_run=dry_run,
                report=report,
            )
        report.namespaces = list(synced)
        if effective_prune:
            await _prune_vanished(
                backend,
                wiki_name=config.wiki_name,
                scope=scope,
                sync_config=sync_config,
                synced=synced,
                dry_run=dry_run,
                report=report,
            )
    except Exception as exc:
        # A mid-apply failure must never leave the writes already made
        # invisible to the audit log — log what was applied, then fail
        # typed instead of leaking a backend/store exception.
        report.namespaces = list(synced)
        _audit(root, config, report)
        raise ObsidianSyncError(
            f"Obsidian sync aborted mid-apply (created={report.created}, "
            f"updated={report.updated}, pruned={report.pruned} already "
            f"applied and audited): {exc}"
        ) from exc
    finally:
        await backend.close()

    _audit(root, config, report)
    return report


def _audit(root: Path, config: WikiProjectConfig, report: ObsidianSyncReport) -> None:
    """Log one bookkeeper entry per applied run — none on a dry/no-op run."""
    if report.dry_run:
        return
    applied = report.created + report.updated + report.pruned
    if applied == 0:
        return
    details = (
        f"vault: {report.vault}, planes: {','.join(report.namespaces)}, "
        f"created: {report.created}, updated: {report.updated}, "
        f"unchanged: {report.unchanged}, pruned: {report.pruned}"
    )
    WikiBookkeeper().log_operation(config.storage_path(root), "SYNC_OBSIDIAN", details)
