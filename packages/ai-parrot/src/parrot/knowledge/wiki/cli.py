"""``wikitoolkit`` — machine-first CLI over the LLM Wiki retrieval plane.

Gives agents (and humans) scoped, token-budgeted access to a codebase
knowledge base built from the current repository — fully offline: the
build path is deterministic (:mod:`parrot.knowledge.wiki.repo_scan`)
and queries run on the SQLite FTS5/BM25 plane (FEAT-260).

Exposed two ways:

- ``wikitoolkit <command>`` — standalone console script, so coding
  assistants can run ``wikitoolkit query "<question>"`` cheaply;
- ``parrot wiki <command>`` — subcommand of the main parrot CLI.

Commands:
    build        Generate/refresh the KB graph from the repository.
    upsert       Incrementally re-ingest specific/changed files.
    query        Scoped question → token-budgeted context pack.
    page         Read one wiki page (progressive disclosure).
    related      Follow typed edges from a page.
    communities  Community detection + inter-community relations (FEAT-401).
    status       Plane statistics + staleness report.
    export       Export the wiki as a human-readable markdown bundle.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

import click
from pydantic import ValidationError

from parrot.knowledge.wiki.context import (
    DEFAULT_BUDGET_TOKENS,
    pack_results,
    qualify_id,
    split_namespaced_id,
    truncate_to_tokens,
)
from parrot.knowledge.wiki.documents import (
    DocumentAcquirer,
    DocumentAcquisitionError,
    resolve_sources,
)
from parrot.knowledge.wiki.federation import (
    FederatedWikiStore,
    NamespaceSkip,
    open_namespace_store,
    resolve_namespaces,
)
from parrot.knowledge.wiki.languages import all_scanners
from parrot.knowledge.wiki.project import (
    PARROT_DIR,
    WikiConfigError,
    WikiEffectiveConfig,
    WikiNamespaceConfig,
    WikiProjectConfig,
    config_path,
    derive_env_overlay,
    find_project_root,
    global_registry_path,
    load_effective_config,
    load_global_registry,
    load_project_config,
    merge_namespaces,
    parrot_home,
    resolve_entry_base,
    save_env_overlay,
    save_global_registry,
    save_project_config,
    validate_namespace_name,
    wiki_write_lock,
)
from parrot.knowledge.wiki.repo_scan import (
    is_inside_wiki_bundle,
    is_wiki_relevant,
    scan_repository,
)
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store
from parrot.knowledge.wiki.symbols import SymbolKind, parse_sym_id

_cli_logger = logging.getLogger("wikitoolkit.cli")

# Silence chatty DEBUG logging that floods build/query output when the
# root logger is set to DEBUG (e.g. by navconfig/Navigator).
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
# Per-record debug messages from store (replace_source_slice) and
# sources (is_stale) are useful for troubleshooting but noisy during
# normal operation.  Default to INFO; --verbose restores DEBUG.
logging.getLogger("parrot.knowledge.wiki.store").setLevel(logging.INFO)
logging.getLogger("parrot.knowledge.wiki.sources").setLevel(logging.INFO)

#: How long a `ns add`/`ns remove` waits for the global registry lock.
REGISTRY_LOCK_WAIT_SECONDS = 5.0

#: How long `upsert` waits for a contended store lock before skipping.
#: Long enough to outlast a peer upsert (sub-second), short enough that
#: a commit hook never stalls behind a multi-minute build.
UPSERT_LOCK_WAIT_SECONDS = 3.0


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

#: Shared `--path` option — every command resolves the repo root the same way.
path_option = click.option("--path", "path_", default=None, help="Repo root (default: auto-detect).")


#: Shared `--ns` option for the read commands (FEAT-450).
ns_option = click.option(
    "--ns",
    "ns_opt",
    default=None,
    help=(
        "Namespace to read: a name (or comma-separated names), 'all' "
        "(default when namespaces are configured), or 'local'."
    ),
)


def _declared_namespaces(
    config: WikiProjectConfig,
) -> dict[str, tuple[WikiNamespaceConfig, str]]:
    """Merge the repo and global namespace registries (repo wins).

    Args:
        config: The repo's project config.

    Returns:
        ``name -> (config, origin)`` for every declared namespace.
    """
    try:
        registry = load_global_registry()
    except WikiConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    return merge_namespaces(config.namespaces, registry.namespaces)


def _selected_namespaces(ns_opt: str | None) -> set[str] | None:
    """Namespace names a ``--ns`` selector asks to resolve.

    Args:
        ns_opt: The raw ``--ns`` value.

    Returns:
        ``None`` for a broadcast (every namespace), otherwise the named
        subset — empty for ``--ns local``, which needs none opened.
    """
    if ns_opt is None or ns_opt == "all":
        return None
    return {part.strip() for part in ns_opt.split(",") if part.strip() and part.strip() != "local"}


def _unknown_namespace(ns_opt: str, known: list[str]) -> click.ClickException:
    """Build the error raised for a ``--ns`` name that is not declared."""
    listing = ", ".join(sorted(known)) or "(none declared)"
    return click.ClickException(
        f"Unknown namespace {ns_opt!r}. Known: {listing} " "(plus 'all', 'local'). Add one with `wikitoolkit ns add`."
    )


def _federate(
    root: Path,
    config: WikiProjectConfig,
    local: BaseWikiStore,
    ns_opt: str | None,
) -> BaseWikiStore:
    """Wrap the local plane in its federated namespaces, honouring ``--ns``.

    Returns the local store untouched when no namespace is declared (or
    when ``--ns local`` asked for exactly that), so a project without
    namespaces behaves as it always has.

    Args:
        root: Repository root.
        config: The repo's project config.
        local: The already-opened local plane.
        ns_opt: The ``--ns`` selector.

    Returns:
        The store the command should read from.

    Raises:
        click.ClickException: The selector names an undeclared namespace,
            or one that could not be opened.
    """
    declared = _declared_namespaces(config)
    only = _selected_namespaces(ns_opt)
    if only is not None:
        unknown = sorted(only - set(declared))
        if unknown:
            raise _unknown_namespace(", ".join(unknown), list(declared))
        if not only:
            # `--ns local` — nothing foreign to open.
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
            hint = f" Fix: {skip.hint}" if skip.hint else ""
            raise click.ClickException(f"Namespace {name!r} is {skip.reason}: {skip.detail}.{hint}") from exc
        raise _unknown_namespace(name, list(declared)) from exc


def _qualify_for_ns(page_id: str, ns_opt: str | None) -> str:
    """Qualify a bare page id with the single namespace ``--ns`` selected.

    Args:
        page_id: The id as typed, qualified or not.
        ns_opt: The ``--ns`` selector.

    Returns:
        ``<ns>::<page_id>`` when ``ns_opt`` names exactly one namespace
        and the id is not already qualified; the id unchanged otherwise.
    """
    if not ns_opt or ns_opt in ("all", "local") or "," in ns_opt:
        return page_id
    return qualify_id(ns_opt, page_id)


def _write_id_for_ns(page_id: str, ns_opt: str | None) -> str:
    """Strip the namespace prefix a write is already scoped to.

    A write path holds the target namespace's own store, which knows
    nothing about the ``ns::`` prefix. An id qualified with a DIFFERENT
    namespace is a mistake worth reporting rather than silently writing
    to the wrong plane.

    Args:
        page_id: Page id as typed.
        ns_opt: The ``--ns`` selector of this write.

    Returns:
        The id as the target store knows it.

    Raises:
        click.ClickException: The id names another namespace.
    """
    namespace, local_id = split_namespaced_id(page_id)
    if namespace is None:
        return page_id
    target = None if ns_opt in (None, "local") else ns_opt
    if namespace == target:
        return local_id
    raise click.ClickException(
        f"Page id {page_id!r} belongs to namespace {namespace!r} — " f"pass `--ns {namespace}` to write there."
    )


def _scoped_namespace(
    root: Path, config: WikiProjectConfig, ns_opt: str | None
) -> tuple[str, WikiNamespaceConfig, Path | None] | None:
    """The single namespace a ``--ns`` selector narrowed a read to.

    Args:
        root: Repository root.
        config: The repo's project config.
        ns_opt: The ``--ns`` selector.

    Returns:
        ``(name, config, storage_dir)`` when the selector names exactly
        one namespace, else ``None`` (broadcast, ``local``, or a subset).
    """
    if not ns_opt or ns_opt in ("all", "local") or "," in ns_opt:
        return None
    entry = _declared_namespaces(config).get(ns_opt)
    if entry is None:
        return None
    cfg, origin = entry
    storage_dir: Path | None = None
    if cfg.kind != "database":
        base = resolve_entry_base(origin, root)
        target = Path(cfg.target).expanduser()
        if not target.is_absolute():
            target = base / target
        if cfg.kind in ("path", "vault"):
            try:
                # The FOREIGN root's own environment/overlay applies here —
                # federation.py's actual plane-open already routes through
                # load_effective_config; this scoping lookup must agree.
                storage_dir = load_effective_config(target).config.storage_path(target)
            except WikiConfigError:
                storage_dir = None
        else:
            storage_dir = target
    return ns_opt, cfg, storage_dir


def _collect_skips(store: BaseWikiStore) -> list[NamespaceSkip]:
    """Namespaces this store could not serve (resolve-time and per-call)."""
    seen: dict[str, NamespaceSkip] = {}
    for skip in [
        *(getattr(store, "skipped", None) or []),
        *(getattr(store, "last_skipped", None) or []),
    ]:
        seen.setdefault(skip.name, skip)
    return list(seen.values())


def _echo_skips(store: BaseWikiStore, *, err: bool = False) -> None:
    """Print one trailing note per skipped namespace (never an error).

    Args:
        store: The store the command read from.
        err: Write to stderr (used when stdout carries JSON).
    """
    for skip in _collect_skips(store):
        hint = f" — {skip.hint}" if skip.hint else ""
        click.echo(f"(namespace {skip.name!r} skipped: {skip.reason}{hint})", err=err)


def _find_repo_root(path: str | None) -> Path:
    """Resolve the repo root, aborting with guidance if absent."""
    if path:
        root = Path(path).resolve()
        if not root.is_dir():
            raise click.ClickException(f"Not a directory: {root}")
        return root
    found = find_project_root()
    if found is None:
        raise click.ClickException(
            "No wiki project found (no .parrot/wiki.json or .git "
            "upwards from here). Run inside a repository or pass "
            "--path."
        )
    return found


def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]:
    """Resolve the repo root + the *effective* (env-merged) config.

    Routes through :func:`load_effective_config` (FEAT-461): the
    committed base ``.parrot/wiki.json`` merged with the active
    environment's overlay (``.parrot/wiki.{env}.json``), if any — so
    every caller automatically honours ``WIKI_ENV``/``ENV`` without
    knowing overlays exist. This is the right resolver for READ paths.

    Callers that also need provenance (the active env name, which
    overlay was used) — e.g. ``status`` — should call
    :func:`_resolve_project_effective` instead. Callers that WRITE the
    base config back (``build``'s ``--backend``/``--name`` persistence,
    ``ns add``) must keep using :func:`load_project_config` directly, so
    an environment/overlay value is never accidentally baked into the
    committed base.
    """
    root = _find_repo_root(path)
    try:
        effective = load_effective_config(root)
    except WikiConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    return root, effective.config


def _resolve_project_effective(path: str | None) -> tuple[Path, WikiEffectiveConfig]:
    """Resolve the repo root + full effective config, with provenance.

    Same resolution as :func:`_resolve_project`, but returns the
    :class:`WikiEffectiveConfig` wrapper (active env name, overlay path
    or ``None`` for a base fallback) instead of just the merged config —
    for callers that report on the environment itself (``status``).
    """
    root = _find_repo_root(path)
    try:
        effective = load_effective_config(root)
    except WikiConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    return root, effective


def _require_built(root: Path, config: WikiProjectConfig) -> BaseWikiStore:
    """Open the store, aborting when the wiki was never built."""
    if not config.is_built(root):
        raise click.ClickException(f"Wiki not built yet for {root}. " "Run `wikitoolkit build` first.")
    return _open_store(root, config)


def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore:
    """Create the retrieval-plane store for a repo.

    Trusts ``config.backend`` as already resolved (FEAT-461): every
    caller is expected to pass a config produced by
    :func:`_resolve_project` (or otherwise precedence-resolved —
    ``--backend`` flag > environment (overlay / ``WIKI_STORE_BACKEND``)
    > base ``wiki.json``), so this function itself has no precedence
    logic of its own. This closes the single-backend limitation the
    module previously tracked as a follow-up: an env-aware overlay
    (``.parrot/wiki.{env}.json``) now lets the same repo resolve a local
    sqlite plane with no ``ENV`` set and the shared ArangoDB plane under
    ``ENV=dev``/``ENV=prod``, without editing ``wiki.json`` by hand.
    """
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
    return create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)


def _open_sources(
    root: Path,
    config: WikiProjectConfig,
    store: Optional[BaseWikiStore] = None,
) -> SourceCollectionManager:
    """Create the source manifest manager matching the store backend.

    For the ``arangodb`` backend the ``ArangoDBWikiStore`` itself is
    handed over (not its private ``_db``), so the manager shares that one
    connection AND inherits the store's reconnect-on-a-dead-loop handling
    — grabbing the raw connection here froze whatever was cached at this
    moment, which a later ``asyncio.run(...)`` then used after its loop
    had closed. The store's ``initialize()`` is idempotent, so it no
    longer matters whether the caller connected it first.
    """
    storage = config.storage_path(root)
    if config.backend == "sqlite":
        return SourceCollectionManager(storage / "sources", db_path=storage / "wiki.db")
    if config.backend == "arangodb":
        return SourceCollectionManager(storage / "sources", backend="arangodb", arango_store=store)
    return SourceCollectionManager(storage / "sources", backend="json")


def _normalize_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Min-max normalise raw FTS scores into [0, 1] for packing."""
    if not rows:
        return rows
    scores = [float(r.get("score", 0.0)) for r in rows]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    for row, score in zip(rows, scores):
        row["score"] = 1.0 if span <= 0 else (score - lo) / span
    return rows


def _run(coro: Any) -> Any:
    """Run an async store operation from a sync click command."""
    return asyncio.run(coro)


def _env_setting(name: str) -> str | None:
    """Read a wiki env setting (``WIKI_STORE`` / ``WIKI_STORE_BACKEND``).

    Prefers navconfig (so values in ``.env`` are honoured, matching the
    legacy ``parrot llmwiki`` behaviour) and falls back to ``os.environ``
    when navconfig is unavailable.
    """
    try:
        from navconfig import config as _nav

        value = _nav.get(name, fallback=None)
    except Exception:  # noqa: BLE001 — navconfig optional; env is enough
        import os

        value = os.environ.get(name)
    return value or None


def _resolve_read_store(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    ns_opt: str | None = None,
) -> BaseWikiStore:
    """Open a store for a read command (``query`` / ``page`` / ``related``).

    With ``--store`` the CLI reads an arbitrary pre-built wiki store
    directly — e.g. the rich ``docs/parrot`` bundle produced by
    ``scripts/build_llm_wiki.py`` — instead of the project's own
    ``.parrot/wiki`` plane. Otherwise the project config resolves the
    plane exactly as ``build`` writes it.

    Resolution precedence (an *explicit* target always wins over the
    ambient env, so a ``--path``-scoped invocation is never silently
    redirected by ``WIKI_STORE``)::

        --store  >  --path project  >  WIKI_STORE env  >  auto-detected project

    An explicit ``--backend arangodb`` always resolves via the project
    config (ArangoDB is server-hosted — there is no local ``--store``
    directory to point at) and connects eagerly here, so an unreachable
    server fails with a clear message before any query is attempted.

    Whichever branch resolves the *local* plane, its declared namespaces
    are then federated on top (FEAT-450) and narrowed by ``ns_opt``.
    ``--store`` is the one exception: it targets one specific pre-built
    store, so it never federates.
    """
    if backend_opt == "arangodb":
        root, config = _resolve_project(path_)
        config.backend = "arangodb"  # --backend flag wins over environment/base
        store = _open_store(root, config)
        try:
            _run(store.initialize())
        except Exception as exc:  # surfaced as a clear CLI error
            raise click.ClickException(
                f"Could not connect to ArangoDB for wiki {config.wiki_name!r}: " f"{exc}"
            ) from exc
        return _federate(root, config, store, ns_opt)
    store_override = store_opt
    if not store_override and not path_:
        # Only consult the env when neither an explicit store nor an
        # explicit project path was given.
        store_override = _env_setting("WIKI_STORE")
    if store_override:
        backend = backend_opt or _env_setting("WIKI_STORE_BACKEND") or "sqlite"
        storage_dir = Path(store_override).expanduser()
        if not storage_dir.is_dir():
            raise click.ClickException(f"No wiki store directory: {storage_dir}")
        if backend == "sqlite" and not (storage_dir / "wiki.db").exists():
            raise click.ClickException(
                f"No wiki database at {storage_dir / 'wiki.db'}. Build it " "first, or point --store at the right root."
            )
        if ns_opt not in (None, "local"):
            raise click.ClickException(
                "--store targets one pre-built store and never federates; " "drop --store to read namespaces."
            )
        return create_wiki_store(storage_dir, backend=backend)
    root, config = _resolve_project(path_)
    if backend_opt:
        config.backend = backend_opt  # type: ignore[assignment]  # flag wins over environment/base
    else:
        env_backend = _env_setting("WIKI_STORE_BACKEND")
        if env_backend:
            config.backend = env_backend  # type: ignore[assignment]
    return _federate(root, config, _require_built(root, config), ns_opt)


#: Shared `--store`/`--backend` options for the read commands.
def _store_options(func: Any) -> Any:
    """Attach ``--store`` and ``--backend`` to a read command."""
    func = click.option(
        "--backend",
        "backend_opt",
        type=click.Choice(["sqlite", "memory", "arangodb"]),
        default=None,
        help="Backend for --store (default: sqlite / WIKI_STORE_BACKEND).",
    )(func)
    func = click.option(
        "--store",
        "store_opt",
        default=None,
        help="Read a pre-built wiki store directly (e.g. docs/parrot); "
        "defaults to WIKI_STORE env or the project's own plane.",
    )(func)
    return func


def _render_results_table(rows: list[dict[str, Any]], question: str, show_body: bool) -> None:
    """Pretty-print ranked results as a Rich table (+ optional body panel).

    Human-facing counterpart to the machine-first context pack — ported
    from the legacy ``parrot llmwiki`` renderer so ``wiki query --table``
    keeps the same at-a-glance output.
    """
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    table = Table(title=f"LLM Wiki · {question!r}", title_justify="left")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Score", justify="right", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Title", style="bold")
    table.add_column("Summary")
    for idx, row in enumerate(rows, start=1):
        score = row.get("score")
        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "-"
        summary = (row.get("summary") or "").strip().replace("\n", " ")
        if len(summary) > 140:
            summary = summary[:137] + "..."
        table.add_row(
            str(idx),
            score_str,
            str(row.get("category", "")),
            str(row.get("title", "")),
            summary,
        )
    console.print(table)
    if show_body and rows:
        top = rows[0]
        body = (top.get("body") or "").strip()
        if body:
            console.print(
                Panel(
                    Markdown(body),
                    title=f"{top.get('title', '')} · {top.get('concept_id', '')}",
                    border_style="green",
                )
            )


# --------------------------------------------------------------------------
# Build / upsert pipeline
# --------------------------------------------------------------------------


def _owning_rel_path(concept_id: str) -> str | None:
    """Rel path of the file a symbol-plane edge's ``src`` concept belongs to.

    FEAT-498: ``defines`` edges are sourced at ``file:<rel>``; every
    other symbol edge (``contains``/``calls``/``extends``/``implements``)
    is sourced at ``sym:<rel>#<qualname>[~n]`` — both resolve to the same
    rel path the edge should travel with in ``replace_source_slice``.

    Args:
        concept_id: A ``file:`` or ``sym:`` concept id.

    Returns:
        The rel path, or ``None`` for any other id shape.
    """
    if concept_id.startswith("file:"):
        return concept_id[len("file:"):]
    if concept_id.startswith("sym:"):
        try:
            rel_path, _qualname, _ordinal = parse_sym_id(concept_id)
        except ValueError:
            return None
        return rel_path
    return None


async def _ingest_files(
    store: BaseWikiStore,
    sources: SourceCollectionManager,
    root: Path,
    scan: Any,
    force: bool = False,
) -> dict[str, int]:
    """Ingest scanned file slices into the plane (incremental).

    Unchanged files (same hash + mtime as the manifest) are skipped
    unless ``force`` is set; changed/new files replace their previous
    slice atomically so re-builds never accumulate duplicates (and
    ``replace_source_slice`` preserves incoming edges to stable
    concept ids). On a fresh, empty plane the per-slice path is
    skipped in favour of one bulk ``upsert_pages``/``add_edges`` write.

    Sync manifest I/O (hashing, SQLite writes) is offloaded via
    ``asyncio.to_thread`` so the event loop is never blocked.
    """
    written = 0
    unchanged = 0
    edges_by_src: dict[str, list[tuple[str, str, str]]] = {}
    for edge in scan.import_edges:
        edges_by_src.setdefault(edge[0], []).append(edge)

    # FEAT-498: sym: pages + defines/contains/calls/extends/implements
    # edges, grouped by the rel_path that "owns" them, so each file's
    # slice carries its own symbols atomically. An edge's src concept
    # (file:<rel> for `defines`, sym:<rel>#... for everything else) is
    # always inside the same file the ref/symbol was extracted from.
    sym_records_by_rel: dict[str, list[Any]] = {}
    for sym_record in scan.symbol_records:
        sym_records_by_rel.setdefault(sym_record.node_id or "", []).append(sym_record)
    symbol_edges_by_rel: dict[str, list[tuple[str, str, str, str]]] = {}
    for edge in scan.symbol_edges:
        rel = _owning_rel_path(edge[0])
        if rel is not None:
            symbol_edges_by_rel.setdefault(rel, []).append(edge)

    stats = await store.stats()
    fresh = int(stats.get("pages", 0)) == 0
    bulk_records = []
    bulk_edges: list[tuple[str, ...]] = []

    # The manifest is read and written in BATCHES, not per file. The
    # per-file API costs one round trip per call — invisible on a local
    # sqlite manifest, dominant on a server-hosted one: registering a new
    # file took ~5 round trips (find_by_uri, add_source's own lookup +
    # write, mark_ingested's read + write), ~0.5s/file measured against a
    # remote ArangoDB, i.e. ~80 minutes for a 9k-file corpus.
    paths = [(root / fs.rel_path).resolve() for fs in scan.files]
    known = await asyncio.to_thread(sources.find_entries_by_uris, [str(path) for path in paths])

    # Staleness is decided from the entries just read (same rule, no extra
    # read per file), so only the files that will actually be re-ingested
    # get registered.
    pending: list[tuple[Any, Path]] = []
    for file_slice, abs_path in zip(scan.files, paths):
        entry = known.get(str(abs_path))
        if entry is not None and not force and not sources.entry_is_stale(entry):
            unchanged += 1
            continue
        pending.append((file_slice, abs_path))

    # `known` is handed over so the registration does not repeat the read
    # the loop above already did.
    registered = await asyncio.to_thread(sources.add_sources, [path for _, path in pending], known)
    id_by_uri = {entry.source_uri: entry.source_id for entry in registered}

    ingested_pages: dict[str, list[str]] = {}
    for file_slice, abs_path in pending:
        source_id = id_by_uri[str(abs_path)]
        file_slice.record.source_id = source_id
        slice_edges = edges_by_src.get(file_slice.record.concept_id, [])

        # FEAT-498: this file's sym: records + defines/contains/calls/
        # extends/implements edges travel in the SAME replace_source_slice
        # call as the file: page (atomic per source) — never upserted
        # separately on the per-slice path.
        sym_records = sym_records_by_rel.get(file_slice.rel_path, [])
        for sym_record in sym_records:
            sym_record.source_id = source_id
        symbol_edges = symbol_edges_by_rel.get(file_slice.rel_path, [])

        if fresh:
            bulk_records.append(file_slice.record)
            bulk_records.extend(sym_records)
            bulk_edges.extend(slice_edges)
            bulk_edges.extend(symbol_edges)
        else:
            # Incremental path: each slice is replaced atomically, so it
            # stays one call per changed file — a re-build touches a
            # handful of files, not the whole corpus.
            # FEAT-498: symbol_edges are 4-tuples (with provenance);
            # BaseWikiStore.replace_source_slice's declared type is
            # 3-tuples only even though every backend's own edge-insert
            # helper already accepts a 4th provenance element (mirrors
            # add_edges) — a type-annotation gap, not a runtime one.
            combined_edges = cast("list[tuple[str, str, str]]", [*slice_edges, *symbol_edges])
            await store.replace_source_slice(
                source_id, [file_slice.record, *sym_records], combined_edges
            )
        if file_slice.symbols:
            await store.upsert_symbols(file_slice.symbols, source_id=source_id)
        ingested_pages.setdefault(source_id, []).append(file_slice.record.concept_id)
        written += 1

    if bulk_records:
        await store.upsert_pages(bulk_records)
    if bulk_edges:
        await store.add_edges(bulk_edges)
    if ingested_pages:
        await asyncio.to_thread(sources.mark_ingested_many, ingested_pages)
    return {"written": written, "unchanged": unchanged}


async def _prune_removed(
    store: BaseWikiStore,
    sources: SourceCollectionManager,
    root: Path,
    scan: Any,
    *,
    scope: str = "plane",
) -> int:
    """Drop pages/sources no longer in scan scope.

    Covers deleted files as well as files that fell out of scope
    (newly ignored directories, changed suffix filters).

    A plane is not always one corpus (FEAT-450, D4.4): a vault can be
    ingested into the repo's plane. Two invariants keep the corpora from
    deleting each other, and they hold in BOTH scopes:

    * a source outside ``root`` is not this scan's to remove;
    * a page whose source is still registered is not stale, whatever the
      scan produced.

    On top of that, ``scope`` decides how aggressive the leftover sweep
    is:

    - ``"plane"`` (``build``) — sweep every sourceless ``file:``/``dir:``
      page the scan did not produce. The plane is this corpus plus
      whatever other corpora registered sources, and only the former is
      swept.
    - ``"root"`` (``VaultIngestTool``) — sweep only the ``dir:`` pages
      this run's removals could have emptied.

    Args:
        store: The plane being pruned.
        sources: Source manifest for that plane.
        root: Directory the scan covered.
        scan: The fresh scan result.
        scope: ``"plane"`` (default) or ``"root"``.

    Returns:
        Number of sources and pages removed.
    """
    expected_files = {fs.record.concept_id for fs in scan.files}
    expected_dirs = {r.concept_id for r in scan.dir_records}
    expected_uris = {str((root / fs.rel_path).resolve()) for fs in scan.files}
    root_prefix = str(root.resolve()) + os.sep
    removed = 0

    #: `dir:` ids that this run's removals could have emptied.
    emptied_dirs: set[str] = set()
    live_source_ids: set[str] = set()

    for entry in await asyncio.to_thread(sources.list_sources):
        if entry.source_uri in expected_uris:
            live_source_ids.add(entry.source_id)
            continue
        if not entry.source_uri.startswith(root_prefix):
            # Another corpus sharing this plane — not ours to prune.
            live_source_ids.add(entry.source_id)
            continue
        for parent in PurePosixPath(Path(entry.source_uri).relative_to(root.resolve()).as_posix()).parents:
            emptied_dirs.add(f"dir:{parent if str(parent) != '.' else '.'}")
        await store.replace_source_slice(entry.source_id, [], [])
        await asyncio.to_thread(sources.remove_source, entry.source_id)
        removed += 1

    stubs = await store.list_pages(limit=1_000_000)
    surviving = {str(stub.get("concept_id", "")) for stub in stubs}

    if scope == "plane":
        # Sourceless leftovers of THIS corpus: a page still backed by a
        # registered source belongs to someone (possibly another corpus)
        # and is never swept here.
        for stub in stubs:
            cid = str(stub.get("concept_id", ""))
            if stub.get("source_id") in live_source_ids:
                continue
            if cid.startswith("file:") and cid not in expected_files:
                if await store.delete_page(cid):
                    surviving.discard(cid)
                    removed += 1
        candidates = {cid for cid in surviving if cid.startswith("dir:") and cid not in expected_dirs}
    else:
        candidates = {cid for cid in surviving if cid in emptied_dirs and cid not in expected_dirs}

    # Deepest first, against a survivor set that shrinks as we go, so a
    # parent emptied by its own children going away is caught in ONE pass.
    for cid in sorted(candidates, key=lambda c: c.count("/"), reverse=True):
        prefix = cid[len("dir:") :]
        if prefix in ("", "."):
            continue
        covered = f"{prefix}/"
        if any(other != cid and other.split(":", 1)[-1].startswith(covered) for other in surviving):
            continue
        if await store.delete_page(cid):
            surviving.discard(cid)
            removed += 1
    return removed


# --------------------------------------------------------------------------
# Post-build: OKF export + graph.html
# --------------------------------------------------------------------------

_CATEGORY_TO_NODE_KIND: dict[str, str] = {
    "module": "WIKI_PAGE",
    "document": "DOCUMENT",
    "config": "DOCUMENT",
    "overview": "DOCUMENT",
    "summary": "WIKI_PAGE",
    "entity": "SYMBOL",
    "concept": "SYMBOL",
}

_REL_TO_EDGE_KIND: dict[str, str] = {
    "contains": "CONTAINS",
    "defines": "DEFINES",
    "references": "REFERENCES",
    "extends": "EXTENDS",
    "mentions": "MENTIONS",
    "explains": "EXPLAINS",
}


async def _export_okf(
    store: BaseWikiStore,
    output_dir: Path,
    wiki_name: str,
) -> dict[str, Any]:
    """Export the OKF markdown bundle and return a report dict."""
    from parrot.knowledge.wiki.export import export_okf_bundle

    report = await export_okf_bundle(store, output_dir, wiki_name=wiki_name)
    return {
        "files_written": report.files_written,
        "index_generated": report.index_generated,
    }


async def _load_graphindex_nodes_edges(
    store: BaseWikiStore,
    graph_kinds: frozenset[str],
) -> tuple[list[Any], list[Any]]:
    """Reconstruct ``UniversalNode``/``UniversalEdge`` lists from the wiki
    store's pages + typed edges, filtered to ``graph_kinds`` categories.

    Shared by the ``build`` graph.html export and the on-demand
    ``communities`` CLI command (FEAT-401) — both need the same
    wiki-page → GraphIndex-schema adaptation. Returns ``([], [])`` when
    no pages match ``graph_kinds``.
    """
    from parrot.knowledge.graphindex.schema import (
        EdgeKind,
        NodeKind,
        UniversalEdge,
        UniversalNode,
    )

    pages = await store.dump_pages()
    edges = await store.dump_edges()

    kind_pages = [p for p in pages if p.get("category", "") in graph_kinds]
    if not kind_pages:
        return [], []

    node_ids = {p["concept_id"] for p in kind_pages}

    nodes: list[UniversalNode] = []
    for p in kind_pages:
        nk_name = _CATEGORY_TO_NODE_KIND.get(p.get("category", ""), "WIKI_PAGE")
        nodes.append(
            UniversalNode(
                node_id=p["concept_id"],
                kind=NodeKind[nk_name],
                title=p.get("title", ""),
                source_uri=p.get("source_id", "") or p.get("concept_id", ""),
                summary=p.get("summary"),
                domain_tags={"category": p.get("category", "")},
            )
        )

    graph_edges: list[UniversalEdge] = []
    for e in edges:
        src, dst = e.get("src", ""), e.get("dst", "")
        if src in node_ids and dst in node_ids:
            ek_name = _REL_TO_EDGE_KIND.get(e.get("rel", ""), "REFERENCES")
            graph_edges.append(
                UniversalEdge(
                    source_id=src,
                    target_id=dst,
                    kind=EdgeKind[ek_name],
                )
            )

    return nodes, graph_edges


async def _export_graph_html(
    store: BaseWikiStore,
    output_dir: Path,
    wiki_name: str,
    graph_kinds: frozenset[str],
) -> dict[str, Any]:
    """Build the interactive graph.html from the wiki store contents."""
    try:
        from parrot.knowledge.graphindex.assemble import GraphAssembler
        from parrot.knowledge.graphindex.export_html import export_graph
    except ImportError as exc:
        _cli_logger.warning("graph export unavailable: %s", exc)
        return {"exported": False, "reason": str(exc)}

    nodes, graph_edges = await _load_graphindex_nodes_edges(store, graph_kinds)
    if not nodes:
        return {"nodes": 0, "edges": 0, "exported": False}

    assembler = GraphAssembler(tenant_id=wiki_name)
    assembler.add_nodes(nodes)
    assembler.add_edges(graph_edges)

    communities = None
    analytics = None
    inter_community = None
    try:
        from parrot.knowledge.graphindex.communities import detect_communities

        communities = detect_communities(
            graph=assembler.graph,
            nodes=nodes,
            write_back_to_nodes=True,
        )
    except Exception as exc:  # noqa: BLE001
        _cli_logger.warning("community detection skipped: %s", exc)
    try:
        from parrot.knowledge.graphindex.analytics import compute_analytics

        analytics = compute_analytics(assembler.graph, nodes, graph_edges)
    except Exception as exc:  # noqa: BLE001
        _cli_logger.warning("analytics skipped: %s", exc)
    if communities is not None:
        # FEAT-401: same treatment as GraphIndexBuilder Stage 6 — the
        # report/export "provides the full picture on build" (spec §8),
        # so the wiki's own build → graph.html path gets it too, not
        # just the on-demand `communities --inter` CLI command.
        try:
            from parrot.knowledge.graphindex.inter_community import (
                compute_inter_community_graph,
            )

            inter_community = compute_inter_community_graph(
                assembler.graph,
                communities,
            )
        except Exception as exc:  # noqa: BLE001
            _cli_logger.warning("inter-community relations skipped: %s", exc)

    try:
        html_path, json_path = export_graph(
            assembler.graph,
            output_dir,
            communities=communities,
            analytics=analytics,
            inter_community=inter_community,
            title=f"{wiki_name} — Knowledge Map",
        )
    except Exception as exc:  # noqa: BLE001
        _cli_logger.error("graph export failed: %s", exc)
        return {"nodes": len(nodes), "edges": len(graph_edges), "exported": False}

    result: dict[str, Any] = {
        "nodes": len(nodes),
        "edges": len(graph_edges),
        "exported": True,
        "html": str(html_path.name),
        "json": str(json_path.name),
    }
    if communities:
        result["communities"] = len(communities.communities)
        result["modularity"] = round(communities.modularity, 4)
    return result


def _write_build_stats(
    output_dir: Path,
    wiki_name: str,
    store_stats: dict[str, Any],
    okf_report: dict[str, Any] | None,
    graph_stats: dict[str, Any] | None,
) -> None:
    """Write wiki_stats.json and README.md into the output directory."""
    from datetime import datetime

    stats: dict[str, Any] = {
        "wiki_name": wiki_name,
        "generated_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "pages": store_stats.get("pages", 0),
        "edges": store_stats.get("edges", 0),
        "categories": store_stats.get("categories", {}),
        "okf": okf_report,
        "graph": graph_stats,
        "languages": {name: s.mode for name, s in all_scanners().items()},
    }
    (output_dir / "wiki_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        f"# {wiki_name} — LLM Wiki",
        "",
        "> Machine-first knowledge base compiled from this repository by "
        "`parrot wiki build`, using the AI-Parrot `parrot.knowledge.wiki` "
        "retrieval plane (FEAT-260).",
        "",
        "## What's here",
        "",
        "| Artefact | Purpose |",
        "| --- | --- |",
        "| `wiki.db` | SQLite retrieval plane (FTS5/BM25 + typed edges). |",
    ]
    if okf_report and okf_report.get("files_written"):
        lines.append(
            "| `index.md` + category folders | OKF v0.1 markdown bundle "
            "— the human-browsable projection of every page. |"
        )
    if graph_stats and graph_stats.get("exported"):
        lines.append("| `graph.html` | Interactive, offline knowledge-graph map " "(open in a browser). |")
        lines.append("| `graph.json` | Serialized graph (nodes, edges, communities). |")
    lines.append("| `wiki_stats.json` | Full build report. |")
    lines += [
        "",
        "## Contents",
        "",
        f"- **{stats['pages']}** pages, **{stats['edges']}** edges",
    ]
    cats = stats.get("categories", {})
    if cats:
        lines += ["", "### Pages by category", ""]
        lines += [f"- `{k}`: {v}" for k, v in sorted(cats.items())]
    if graph_stats and graph_stats.get("exported"):
        lines += [
            "",
            "### Knowledge map",
            "",
            f"- [`graph.html`](./graph.html) — {graph_stats['nodes']} nodes, "
            f"{graph_stats['edges']} edges"
            + (
                f", {graph_stats.get('communities', 0)} communities " f"(modularity {graph_stats.get('modularity')})"
                if graph_stats.get("communities")
                else ""
            ),
        ]
    lines += [
        "",
        "## Querying",
        "",
        "```bash",
        'wikitoolkit query "your question" --path .',
        "```",
        "",
        f"_Generated {stats['generated_at']}._",
        "",
    ]
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# CLI group
# --------------------------------------------------------------------------


@click.group(name="wiki")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Lower wiki loggers to DEBUG (shows per-record store/source messages).",
)
@click.pass_context
def wiki(ctx: click.Context, verbose: bool) -> None:
    """LLM Wiki — codebase knowledge base for agents (FEAT-260).

    Build a machine-first knowledge graph of the current repository
    and query it with scoped, token-budgeted questions instead of
    grepping raw files.
    """
    if verbose:
        logging.getLogger("parrot.knowledge.wiki.store").setLevel(logging.DEBUG)
        logging.getLogger("parrot.knowledge.wiki.sources").setLevel(logging.DEBUG)


@wiki.command()
def mcp() -> None:
    """Start wikitoolkit as a local MCP stdio server (FEAT-403).

    Exposes the six wiki tools (wiki_query, wiki_page, wiki_related,
    wiki_remember, wiki_note, wiki_status) as native MCP tools, giving
    them equal standing with Grep/Read at tool-selection time. Must be
    run inside a repository with a built wiki (`wikitoolkit build`).
    """
    from parrot.knowledge.wiki.mcp_server import main as mcp_main

    mcp_main()


@wiki.command()
@path_option
@click.option("--name", default=None, help="Wiki name (default: repo directory name).")
@click.option(
    "--backend",
    type=click.Choice(["sqlite", "memory", "arangodb"]),
    default=None,
    help="Retrieval-plane backend (default: sqlite).",
)
@click.option("--force", is_flag=True, help="Re-ingest every file, ignoring staleness.")
@click.option("--no-git", is_flag=True, help="Do not use git for file discovery.")
@click.option("--quiet", "-q", is_flag=True, help="Only print the final summary line.")
@click.option(
    "--no-export",
    is_flag=True,
    help="Skip OKF markdown bundle export.",
)
@click.option(
    "--no-graph",
    is_flag=True,
    help="Skip graph.html / graph.json generation.",
)
@click.option(
    "--graph-kinds",
    default="module,document,overview",
    show_default=True,
    help="Comma list of page categories included in graph.html.",
)
@click.option(
    "--vault/--no-vault",
    "vault_mode",
    default=None,
    help=(
        "Treat the path as an Obsidian vault (notes/wikilinks/tags scan) "
        "instead of a source repository. Default: auto-detect via the "
        ".obsidian/ directory."
    ),
)
def build(
    path_: str | None,
    name: str | None,
    backend: str | None,
    force: bool,
    no_git: bool,
    quiet: bool,
    no_export: bool,
    no_graph: bool,
    graph_kinds: str,
    vault_mode: bool | None,
) -> None:
    """Generate (or refresh) the KB graph from the current repository.

    Deterministic and offline: scans source files (respecting
    .gitignore), extracts summaries/API outlines, and writes pages +
    typed edges into the wiki retrieval plane.

    By default also produces an OKF markdown bundle (index.md +
    per-page files), an interactive graph.html / graph.json knowledge
    map, a wiki_stats.json build report, and a README.md entry point.
    """
    root, effective = _resolve_project_effective(path_)
    config = effective.config
    # `build` persists explicit --name/--backend overrides to the BASE
    # config (never the environment-merged one) — an environment/overlay
    # value must never leak into the committed .parrot/wiki.json.
    base_config = load_project_config(root)
    with wiki_write_lock(config.storage_path(root)) as _acquired:
        if not _acquired:
            click.echo(
                "Another wiki writer is in progress (build or upsert) — "
                "refusing to run two writers against the same store. Wait "
                "for it to finish, then retry."
            )
            raise SystemExit(1)
        if name:
            config.wiki_name = name
            base_config.wiki_name = name
        if backend:
            config.backend = backend  # type: ignore[assignment]
            base_config.backend = backend  # type: ignore[assignment]
        else:
            # One precedence rule (closes cli.py:352's former TODO):
            # --backend flag > environment (WIKI_STORE_BACKEND / overlay)
            # > base wiki.json. `config.backend` already carries the
            # overlay's value (or the base's, when no overlay applies);
            # WIKI_STORE_BACKEND — long honoured by the read/write store
            # resolvers but ignored here — now applies too, still below
            # an explicit flag and never persisted to the base config.
            env_backend = _env_setting("WIKI_STORE_BACKEND")
            if env_backend:
                config.backend = env_backend  # type: ignore[assignment]

        from parrot.knowledge.wiki.vault_scan import (
            is_obsidian_vault,
            scan_vault,
        )

        vault_stats = None
        if vault_mode is None:
            vault_mode = is_obsidian_vault(root)
        if vault_mode:
            if not quiet:
                click.echo(f"Scanning Obsidian vault {root} ...")
            scan, vault_stats = scan_vault(
                root,
                body_max_chars=config.body_max_chars,
                max_file_bytes=config.max_file_kb * 1024,
            )
        else:
            if not quiet:
                click.echo(f"Scanning {root} ...")
            scan = scan_repository(
                root,
                suffixes=config.include_suffixes or None,
                exclude_dirs=config.exclude_dirs,
                body_max_chars=config.body_max_chars,
                max_file_bytes=config.max_file_kb * 1024,
                use_git=not no_git,
            )

        output_dir = config.storage_path(root)

        async def _pipeline() -> dict[str, Any]:
            store = _open_store(root, config)
            if config.backend == "arangodb":
                await store.initialize()
            sources = _open_sources(root, config, store=store)
            counts = await _ingest_files(store, sources, root, scan, force=force)
            await store.upsert_pages(scan.dir_records)
            await store.add_edges(scan.dir_edges)
            counts["removed"] = await _prune_removed(store, sources, root, scan)
            counts["stats"] = await store.stats()

            okf_report: dict[str, Any] | None = None
            if not no_export:
                okf_report = await _export_okf(
                    store,
                    output_dir,
                    config.wiki_name,
                )
                # Exclude the export output from future scans.
                try:
                    export_rel = output_dir.resolve().relative_to(root).as_posix()
                except ValueError:
                    export_rel = None
                if export_rel and export_rel not in config.exclude_dirs:
                    config.exclude_dirs.append(export_rel)
                if export_rel and export_rel not in base_config.exclude_dirs:
                    base_config.exclude_dirs.append(export_rel)
            counts["okf"] = okf_report

            graph_stats: dict[str, Any] | None = None
            if not no_graph:
                kinds = frozenset(k.strip() for k in graph_kinds.split(",") if k.strip())
                graph_stats = await _export_graph_html(
                    store,
                    output_dir,
                    config.wiki_name,
                    kinds,
                )
            counts["graph"] = graph_stats

            return counts

        try:
            counts = _run(_pipeline())
        except Exception as exc:  # surfaced as a clear CLI error
            if config.backend == "arangodb":
                raise click.ClickException(
                    f"Could not connect to ArangoDB for wiki " f"{config.wiki_name!r}: {exc}"
                ) from exc
            raise
        save_project_config(root, base_config)

        if effective.overlay_path is None:
            # Auto-generate the missing overlay for the active env, derived
            # from the (persisted) BASE config — so it stays consistent
            # with whatever `--name`/`--backend` just committed to
            # wiki.json — but NEVER from an ephemeral, non-persisted
            # override such as WIKI_STORE_BACKEND (spec §7 Known Risks:
            # "avoid freezing a one-off flag into the overlay"). Never
            # clobbers an existing overlay (this branch only runs when
            # none exists).
            overlay = derive_env_overlay(base_config, effective.env)
            overlay_file = save_env_overlay(root, effective.env, overlay)
            click.echo(
                f"Generated wiki environment overlay for env "
                f"{effective.env!r} at {overlay_file} "
                f"(backend={overlay.backend!r})"
            )

        stats = counts["stats"]

        # Write wiki_stats.json + README.md.
        _write_build_stats(
            output_dir,
            config.wiki_name,
            stats,
            counts.get("okf"),
            counts.get("graph"),
        )

        click.echo(
            f"Wiki '{config.wiki_name}' built at "
            f"{output_dir} — "
            f"{counts['written']} ingested, {counts['unchanged']} unchanged, "
            f"{counts['removed']} removed; "
            f"{stats.get('pages', 0)} pages, {stats.get('edges', 0)} edges."
        )
        if vault_stats is not None:
            click.echo(
                f"Vault: {vault_stats.notes} notes, {vault_stats.tags} tags, "
                f"{vault_stats.wikilink_edges} wikilink edges, "
                f"{vault_stats.embed_edges} embed edges, "
                f"{len(vault_stats.unresolved_links)} unresolved links."
            )
        okf = counts.get("okf")
        if okf and not quiet:
            click.echo(f"OKF bundle: {okf['files_written']} files exported.")
        graph = counts.get("graph")
        if graph and graph.get("exported") and not quiet:
            click.echo(f"Graph: {graph['nodes']} nodes, {graph['edges']} edges " f"→ {graph['html']}")
        if scan.skipped and not quiet:
            click.echo(f"Skipped {len(scan.skipped)} binary/oversized files.")
            if len(scan.skipped) <= 10:
                for path in scan.skipped:
                    click.echo(f"  - {path}")


def _changed_files_from_git(root: Path) -> list[str]:
    """Relative paths touched by the last commit (post-commit hook).

    Uses ``-z`` so paths with spaces/unicode are not C-quoted,
    ``--root`` so the very first commit of a repository also reports
    its files, and ``-m --first-parent`` so **merge commits** report the
    files they bring in relative to the first parent. Without the latter,
    a plain ``diff-tree HEAD`` emits the (usually empty) combined diff for
    a merge, so every file a ``git merge`` introduces would silently stay
    stale in the wiki until the next full ``wikitoolkit build``.
    """
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-z",
                "-r",
                "-m",
                "--first-parent",
                "--root",
                "HEAD",
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out = proc.stdout.decode("utf-8", errors="replace")
    # `-m` can repeat a path across parent sections; dedupe while
    # preserving first-seen order.
    seen: set[str] = set()
    result: list[str] = []
    for p in out.split("\0"):
        if p and p not in seen:
            seen.add(p)
            result.append(p)
    return result


@wiki.command()
@click.argument("paths", nargs=-1)
@path_option
@click.option(
    "--changed",
    is_flag=True,
    help="Upsert the files touched by the last git commit.",
)
@click.option("--quiet", "-q", is_flag=True, help="Suppress output (for git hooks).")
def upsert(
    paths: tuple[str, ...],
    path_: str | None,
    changed: bool,
    quiet: bool,
) -> None:
    """Incrementally re-ingest specific files (or last-commit changes).

    Used by the git post-commit hook installed via
    `parrot claude install` to keep the wiki fresh. Deleted files have
    their pages removed. Directory overview pages are refreshed by the
    next full `wikitoolkit build`.
    """
    root, config = _resolve_project(path_)
    # Wait out a peer upsert (sub-second) rather than dropping the
    # commit's files; give up quickly if a multi-minute build holds it.
    with wiki_write_lock(config.storage_path(root), timeout=UPSERT_LOCK_WAIT_SECONDS) as _acquired:
        if not _acquired:
            if not quiet:
                click.echo(
                    "Another wiki writer is in progress (likely a full "
                    "build) — skipping this upsert; the build will cover "
                    "these files."
                )
            return
        if not config.is_built(root):
            if not quiet:
                click.echo("Wiki not built yet — run `wikitoolkit build` first.")
            return

        rel_paths = list(paths)
        if changed:
            rel_paths.extend(_changed_files_from_git(root))
        if not rel_paths:
            if not quiet:
                click.echo("Nothing to upsert (no paths given).")
            return

        normalized: list[str] = []
        for rel in rel_paths:
            p = Path(rel)
            if p.is_absolute():
                try:
                    rel = p.resolve().relative_to(root).as_posix()
                except ValueError:
                    continue
            rel = PurePosixPath(rel).as_posix()
            # Same selection filter as full discovery — the two paths must
            # never disagree about what belongs in the wiki. The bundle
            # guardrail is checked per path (ancestor walk) rather than by
            # discovering every bundle in the repo, so a docs-only commit
            # keeps its O(1) fast path.
            if is_wiki_relevant(
                rel,
                suffixes=config.include_suffixes or None,
                exclude_dirs=config.exclude_dirs,
            ) and not is_inside_wiki_bundle(root, rel):
                normalized.append(rel)

        existing = [rel for rel in normalized if (root / rel).is_file()]
        deleted = [rel for rel in normalized if not (root / rel).is_file()]
        if not existing and not deleted:
            if not quiet:
                click.echo("No wiki-relevant files in the given set.")
            return

        scan = scan_repository(
            root,
            suffixes=config.include_suffixes or None,
            exclude_dirs=config.exclude_dirs,
            body_max_chars=config.body_max_chars,
            max_file_bytes=config.max_file_kb * 1024,
            rel_paths=existing,
        )

        async def _pipeline() -> dict[str, int]:
            store = _open_store(root, config)
            if config.backend == "arangodb":
                await store.initialize()
            sources = _open_sources(root, config, store=store)
            counts = await _ingest_files(store, sources, root, scan, force=True)
            removed = 0
            for rel in deleted:
                uri = str((root / rel).resolve())
                source_id = await asyncio.to_thread(sources.find_by_uri, uri)
                if source_id:
                    await store.replace_source_slice(source_id, [], [])
                    await asyncio.to_thread(sources.remove_source, source_id)
                    removed += 1
            counts["removed"] = removed
            return counts

        try:
            counts = _run(_pipeline())
        except Exception as exc:  # surfaced as a clear CLI error
            if config.backend == "arangodb":
                raise click.ClickException(
                    f"Could not connect to ArangoDB for wiki " f"{config.wiki_name!r}: {exc}"
                ) from exc
            raise
        if not quiet:
            click.echo(f"Upserted {counts['written']} page(s), " f"removed {counts['removed']}.")


@wiki.command()
@click.argument("question")
@path_option
@click.option("--top-k", "-n", default=12, show_default=True, help="Max results to rank.")
@click.option(
    "--budget",
    default=DEFAULT_BUDGET_TOKENS,
    show_default=True,
    help="Token budget for the packed context.",
)
@click.option("--category", default=None, help="Filter by page category.")
@_store_options
@ns_option
@click.option(
    "--table",
    "as_table",
    is_flag=True,
    help="Render a human-facing Rich table instead of the context pack.",
)
@click.option(
    "--body",
    "-b",
    "show_body",
    is_flag=True,
    help="Also fetch/render the full body of the top-ranked page.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON results.")
def query(
    question: str,
    path_: str | None,
    top_k: int,
    budget: int,
    category: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    ns_opt: str | None,
    as_table: bool,
    show_body: bool,
    as_json: bool,
) -> None:
    """Scoped question against the codebase KB (lexical BM25 search).

    Returns a token-budgeted context pack of page stubs (or a
    human-facing Rich table with `--table`). Point `--store` at any
    pre-built wiki (e.g. `docs/parrot`) to query it directly. Follow up
    with `wikitoolkit page <id>` to read a full page, or
    `wikitoolkit related <id>` to walk the graph.
    """
    store = _resolve_read_store(path_, store_opt, backend_opt, ns_opt)
    rows = _run(store.search_fts(question, category=category, limit=top_k))
    if not isinstance(store, FederatedWikiStore):
        # A federated store already normalised each namespace and applied
        # its weight; a second global min-max here would undo that.
        rows = _normalize_scores(rows)

    # Hydrate the top hit's body once, for --body across every renderer.
    if show_body and rows:
        top = _run(store.get_page(rows[0]["concept_id"], include_body=True))
        if top:
            rows[0] = {**rows[0], **top}

    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        _echo_skips(store, err=True)
        return
    if not rows:
        click.echo(
            f"No wiki results for {question!r}. The wiki may be stale — "
            "try `wikitoolkit build`, or fall back to code search."
        )
        _echo_skips(store)
        return
    if as_table:
        _render_results_table(rows, question, show_body=show_body)
        _echo_skips(store)
        return
    packed = pack_results(rows, budget_tokens=budget)
    click.echo(f"# Wiki results for: {question}\n")
    click.echo(packed.text)
    click.echo(f"\n({packed.results_packed}/{packed.total_available} results, " f"~{packed.tokens_used} tokens)")
    if show_body and rows[0].get("body"):
        click.echo(f"\n## {rows[0].get('title')}\n{rows[0]['body']}")
    _echo_skips(store)
    click.echo("Next: `wikitoolkit page <id>` for a full page · " "`wikitoolkit related <id>` for linked pages.")


@wiki.command()
@click.argument("page_id")
@path_option
@click.option(
    "--max-tokens",
    default=None,
    type=int,
    help="Truncate the body to roughly this many tokens.",
)
@_store_options
@ns_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def page(
    page_id: str,
    path_: str | None,
    max_tokens: int | None,
    store_opt: str | None,
    backend_opt: str | None,
    ns_opt: str | None,
    as_json: bool,
) -> None:
    """Read one wiki page in full (progressive disclosure).

    PAGE_ID may carry a namespace prefix (``other::file:a.py``); with
    ``--ns <name>`` a bare id is resolved inside that namespace.
    """
    store = _resolve_read_store(path_, store_opt, backend_opt, ns_opt)
    page_id = _qualify_for_ns(page_id, ns_opt)
    data = _run(store.get_page(page_id, include_body=True))
    if data is None:
        raise click.ClickException(f"Page {page_id!r} not found. " f'Search first: wikitoolkit query "..."')
    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return
    body = str(data.get("body") or "")
    truncated = False
    if max_tokens is not None:
        body, truncated = truncate_to_tokens(body, max_tokens)
    click.echo(f"# {data.get('title')}  [{data.get('concept_id')}]")
    click.echo(f"category: {data.get('category')}")
    if data.get("summary"):
        click.echo(f"summary: {data.get('summary')}\n")
    click.echo(body)
    if truncated:
        click.echo("\n[... body truncated — re-run without --max-tokens]")


@wiki.command()
@click.argument("page_id")
@path_option
@click.option("--rel", default=None, help="Filter by edge relation (e.g. contains).")
@click.option(
    "--direction",
    type=click.Choice(["out", "in", "both"]),
    default="both",
    show_default=True,
)
@_store_options
@ns_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def related(
    page_id: str,
    path_: str | None,
    rel: str | None,
    direction: str,
    store_opt: str | None,
    backend_opt: str | None,
    ns_opt: str | None,
    as_json: bool,
) -> None:
    """List pages linked to PAGE_ID by typed edges.

    PAGE_ID may carry a namespace prefix (``other::dir:pkg``); with
    ``--ns <name>`` a bare id is resolved inside that namespace.
    """
    store = _resolve_read_store(path_, store_opt, backend_opt, ns_opt)
    page_id = _qualify_for_ns(page_id, ns_opt)
    rows = _run(store.neighbors(page_id, rel=rel, direction=direction))
    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        click.echo(f"No edges from {page_id!r}.")
        return
    for row in rows:
        arrow = "→" if row.get("direction") == "out" else "←"
        click.echo(f"{arrow} [{row.get('concept_id')}] " f"({row.get('rel')}) {row.get('title', '')}")


def _probe_backend_reachable(root: Path, config: WikiProjectConfig) -> bool | None:
    """Bounded reachability probe for the primary plane.

    Args:
        root: Repository root.
        config: The (already effective) config to probe.

    Returns:
        ``None`` for local backends (sqlite/memory — no network hop, so
        reachability is not a meaningful question); ``True``/``False``
        for ``arangodb`` after a timeout-bounded connect probe. Mirrors
        :func:`parrot.knowledge.wiki.federation._open_arango`'s
        probe-then-close discipline: never keep a probe connection
        alive on this throwaway CLI event loop.
    """
    if config.backend != "arangodb":
        return None
    from parrot.knowledge.wiki.federation import DEFAULT_ARANGO_TIMEOUT

    async def _probe() -> bool:
        store = _open_store(root, config)
        try:
            await asyncio.wait_for(store.initialize(), timeout=DEFAULT_ARANGO_TIMEOUT)
            return True
        except Exception:  # noqa: BLE001 — reachability probe, not a hard failure
            return False
        finally:
            close = getattr(store, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    _cli_logger.debug(
                        "Ignoring error closing probe connection for %r",
                        config.wiki_name,
                        exc_info=True,
                    )

    return _run(_probe())


@wiki.command()
@path_option
@ns_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def status(path_: str | None, ns_opt: str | None, as_json: bool) -> None:
    """Show wiki plane statistics, namespaces, and source staleness."""
    root, effective = _resolve_project_effective(path_)
    config = effective.config
    overlay_label = str(effective.overlay_path) if effective.overlay_path else "base (no overlay)"
    reachable = _probe_backend_reachable(root, config)
    if not as_json:
        click.echo(f"Env       : {effective.env} ({overlay_label})")
        if reachable is not None:
            click.echo(f"Reachable : {'yes' if reachable else 'no'}")
    if not config.is_built(root):
        click.echo(f"Wiki not built for {root} — run `wikitoolkit build`.")
        return
    store = _open_store(root, config)
    if config.backend == "arangodb":
        try:
            _run(store.initialize())
        except Exception as exc:  # surfaced as a clear CLI error
            raise click.ClickException(
                f"Could not connect to ArangoDB for wiki {config.wiki_name!r}: " f"{exc}"
            ) from exc
    # Source staleness is a property of the LOCAL plane — the manager
    # must see the real store, not the federation wrapping it.
    sources = _open_sources(root, config, store=store)
    read_store = _federate(root, config, store, ns_opt)
    stats = _run(read_store.stats())
    namespaces = stats.pop("namespaces", None)
    ns_skipped = stats.pop("skipped", None)
    stats.pop("local", None)
    # `--ns <name>` reports THAT plane's counters, so the header must
    # name it too — otherwise a foreign page count sits under the local
    # project's identity. Source staleness is a local-manifest concept
    # and is simply absent for a namespace.
    scoped_to = _scoped_namespace(root, config, ns_opt)
    entries = [] if scoped_to else sources.list_sources()
    stale = [e.source_id for e in entries if sources.is_stale(e.source_id)]
    payload: dict[str, Any] = {
        "root": str(root),
        "wiki_name": config.wiki_name,
        "backend": config.backend,
        "storage_dir": str(config.storage_path(root)),
        "env": effective.env,
        "overlay": overlay_label,
        "reachable": reachable,
        "stats": stats,
        "sources": len(entries),
        "stale_sources": len(stale),
        "languages": {name: s.mode for name, s in all_scanners().items()},
        # FEAT-498: same per-language mode mapping as "languages" above,
        # named for the structural symbol plane specifically — additive,
        # "languages" itself is unchanged for backward compatibility.
        "structural": {name: s.mode for name, s in all_scanners().items()},
    }
    if scoped_to is not None:
        name, handle_cfg, storage_dir = scoped_to
        payload["namespace"] = name
        payload["wiki_name"] = name
        payload["backend"] = handle_cfg.backend
        payload["storage_dir"] = str(storage_dir) if storage_dir else None
        payload["sources"] = None
        payload["stale_sources"] = None
    if namespaces is not None:
        payload["namespaces"] = namespaces
        payload["skipped"] = ns_skipped or []
    if as_json:
        click.echo(json.dumps(payload, indent=2, default=str))
        return
    click.echo(f"Wiki      : {payload['wiki_name']} ({payload['backend']})")
    if scoped_to is None:
        click.echo(f"Root      : {root}")
    else:
        click.echo(f"Namespace : {scoped_to[0]} (of {root})")
    click.echo(f"Storage   : {payload['storage_dir']}")
    click.echo(
        f"Plane     : {stats.get('pages', 0)} pages, "
        f"{stats.get('edges', 0)} edges, "
        f"{stats.get('symbols', 0)} symbols, "
        f"~{stats.get('total_tokens', 0)} tokens"
    )
    click.echo(f"Categories: {stats.get('categories', {})}")
    click.echo(f"Languages : {payload['languages']}")
    click.echo(f"Structural: {payload['structural']}")
    if scoped_to is None:
        click.echo(f"Sources   : {len(entries)} tracked, {len(stale)} stale")
    if namespaces:
        click.echo("\nNamespaces:")
        header = f"  {'name':<16} {'kind':<9} {'backend':<9} {'origin':<7} {'pages':>7}  status"
        click.echo(header)
        for name in sorted(namespaces):
            block = namespaces[name]
            pages = block.get("pages")
            click.echo(
                f"  {name:<16} {block.get('kind', ''):<9} "
                f"{block.get('backend', ''):<9} {block.get('origin', ''):<7} "
                f"{'-' if pages is None else pages:>7}  {block.get('status', '')}"
            )
    for skip in ns_skipped or []:
        hint = f" — {skip.get('hint')}" if skip.get("hint") else ""
        click.echo(f"  {skip['name']:<16} {skip['reason']}{hint}")
    if stale:
        click.echo("Run `wikitoolkit build` to refresh stale sources.")


# --------------------------------------------------------------------------
# Structural symbol plane (FEAT-498)
# --------------------------------------------------------------------------


def _structural_tool(name: str, path_: str | None) -> Any:
    """Open the named structural tool (``wiki_symbol_lookup``/etc.) for one call.

    Reuses :func:`create_structural_tools` so the CLI's human-readable
    output is byte-identical to the MCP tools' own text rendering — the
    only difference is ``--json`` prints the Pydantic dict directly
    instead of going through an MCP client.

    Imported lazily: ``structural.service`` imports ``_ingest_files``/
    ``_open_sources`` from this module (TASK-2749), so a module-level
    import here would be circular.
    """
    from parrot.knowledge.wiki.structural.tools import create_structural_tools

    root, config = _resolve_project(path_)
    store = _require_built(root, config)
    tools = {tool.name: tool for tool in create_structural_tools(store, root, config)}
    return tools[name]


def _echo_structural_result(result: Any, as_json: bool) -> None:
    """Print a structural tool's ``ToolResult`` — text by default, dict for ``--json``."""
    payload = dict(result.result)
    text = payload.pop("text", "")
    if as_json:
        click.echo(json.dumps(payload, indent=2, default=str))
        return
    click.echo(text)


@wiki.group(name="symbols")
def symbols() -> None:
    """Query the codebase's structural symbol plane (FEAT-498)."""


@symbols.command("lookup")
@path_option
@click.argument("query")
@click.option("--kind", default=None, help="Exact symbol kind filter (e.g. function, class).")
@click.option("--language", default=None, help="Exact scanner-name filter (e.g. python).")
@click.option("--path-prefix", "path_prefix", default=None, help="rel_path must start with this prefix.")
@click.option("--limit", default=20, type=int, help="Maximum results.")
@click.option("--json", "as_json", is_flag=True, help="Emit the raw Pydantic dict as JSON.")
def symbols_lookup(
    path_: str | None,
    query: str,
    kind: str | None,
    language: str | None,
    path_prefix: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """Find a symbol (function/class/method) by name or qualname."""
    tool = _structural_tool("wiki_symbol_lookup", path_)
    kind_enum = SymbolKind(kind) if kind else None
    result = _run(
        tool._execute(
            query=query, kind=kind_enum, language=language, path_prefix=path_prefix, limit=limit
        )
    )
    _echo_structural_result(result, as_json)


@symbols.command("outline")
@path_option
@click.argument("target")
@click.option("--depth", default=2, type=int, help="Maximum symbol nesting depth.")
@click.option(
    "--source", "include_source", is_flag=True, help="Include a capped source excerpt (sym: targets only)."
)
@click.option("--json", "as_json", is_flag=True, help="Emit the raw Pydantic dict as JSON.")
def symbols_outline(
    path_: str | None,
    target: str,
    depth: int,
    include_source: bool,
    as_json: bool,
) -> None:
    """Get the symbol outline of a file: file:<rel>, sym:<rel>#<q>, or a relative path."""
    tool = _structural_tool("wiki_code_outline", path_)
    result = _run(tool._execute(target=target, depth=depth, include_source=include_source))
    _echo_structural_result(result, as_json)


@symbols.command("blast")
@path_option
@click.argument("symbol")
@click.option(
    "--rel", "relations", multiple=True,
    help="Edge relation to follow (repeatable); default: calls, extends, implements.",
)
@click.option("--depth", default=2, type=int, help="Maximum BFS depth.")
@click.option(
    "--inferred/--no-inferred", "include_inferred", default=True,
    help="Follow provenance='inferred' edges (globally-unique-name resolutions).",
)
@click.option(
    "--tests/--no-tests", "include_tests", default=True,
    help="Include symbols under a tests/ path.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the raw Pydantic dict as JSON.")
def symbols_blast(
    path_: str | None,
    symbol: str,
    relations: tuple[str, ...],
    depth: int,
    include_inferred: bool,
    include_tests: bool,
    as_json: bool,
) -> None:
    """Find every symbol that transitively depends on (calls/extends/implements) SYMBOL."""
    tool = _structural_tool("wiki_blast_radius", path_)
    result = _run(
        tool._execute(
            symbol=symbol,
            relations=list(relations) or None,
            depth=depth,
            include_inferred=include_inferred,
            include_tests=include_tests,
        )
    )
    _echo_structural_result(result, as_json)


# --------------------------------------------------------------------------
# Namespace registry (FEAT-450)
# --------------------------------------------------------------------------


def _namespace_source(
    src_project: str | None,
    src_store: str | None,
    src_database: str | None,
    src_vault: str | None,
) -> None:
    """Validate that exactly one namespace source flag was given.

    Raises:
        click.ClickException: When zero or several sources were given.
    """
    given = [
        flag
        for flag, value in (
            ("--project", src_project),
            ("--store", src_store),
            ("--database", src_database),
            ("--vault", src_vault),
        )
        if value
    ]
    if len(given) != 1:
        raise click.ClickException(
            "Give exactly one of --project / --store / --database / --vault " f"(got: {', '.join(given) or 'none'})."
        )


@contextmanager
def _global_registry_lock() -> Iterator[None]:
    """Serialise read-modify-write cycles on ``PARROT_HOME/wikis.json``.

    ``save_global_registry`` replaces the file atomically, which prevents
    a torn write but not a lost update: two concurrent ``ns add --global``
    calls would both read the original registry and the later
    ``os.replace`` would drop the earlier entry. Reuse the wiki writer
    lock, held across load + mutate + save.

    Yields:
        ``None``, with the lock held (advisory; a lock that cannot be
        taken is logged and the write proceeds, matching
        :func:`wiki_write_lock`).
    """
    home = parrot_home()
    home.mkdir(parents=True, exist_ok=True)
    with wiki_write_lock(home, timeout=REGISTRY_LOCK_WAIT_SECONDS) as acquired:
        if not acquired:
            _cli_logger.warning("Could not take the %s lock; writing anyway.", home)
        yield


def _stored_namespace_path(value: str | None, root: Path, is_global: bool) -> str | None:
    """Normalise a user-typed namespace path into its stored form.

    Args:
        value: The raw ``--project`` / ``--store`` / ``--vault`` value.
        root: Repository root (the base a repo entry is read back from).
        is_global: Whether the entry goes to the per-user registry.

    Returns:
        ``None`` when ``value`` is falsy; an absolute path for a global
        entry; a repo-root-relative path for a repo entry (so a checked-in
        ``wiki.json`` stays portable across clones).
    """
    if not value:
        return value
    target = Path(value).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    target = Path(os.path.normpath(target))
    if is_global:
        return str(target)
    return os.path.relpath(target, root.resolve())


def _namespace_built(cfg: WikiNamespaceConfig, base_dir: Path) -> bool | None:
    """Whether a declared namespace already has a plane on disk.

    Args:
        cfg: The namespace declaration.
        base_dir: Directory its relative paths resolve against.

    Returns:
        ``True``/``False`` for on-disk kinds, ``None`` for ArangoDB
        (server-hosted — there is no local artifact to probe).
    """
    if cfg.kind == "database":
        return None
    target = Path(cfg.target).expanduser()
    if not target.is_absolute():
        target = base_dir / target
    if cfg.kind in ("path", "vault"):
        try:
            # Same reasoning as `_scoped_namespace` above: the foreign
            # project's own environment/overlay decides its plane.
            foreign = load_effective_config(target).config
        except WikiConfigError:
            return False
        return foreign.is_built(target)
    if cfg.backend == "memory":
        return (target / "pages").exists()
    return (target / "wiki.db").exists()


@wiki.group(name="ns")
def ns() -> None:
    """Manage federated wiki namespaces (other wikis this one can read)."""


@ns.command("list")
@path_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def ns_list(path_: str | None, as_json: bool) -> None:
    """List the namespaces visible from this project (repo + global)."""
    root, config = _resolve_project(path_)
    declared = _declared_namespaces(config)
    rows = []
    for name in sorted(declared):
        cfg, origin = declared[name]
        base_dir = resolve_entry_base(origin, root)
        built = _namespace_built(cfg, base_dir)
        rows.append(
            {
                "name": name,
                "kind": cfg.kind,
                "backend": cfg.backend,
                "origin": origin,
                "target": cfg.target,
                "weight": cfg.weight,
                "description": cfg.description,
                "built": built,
            }
        )
    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        click.echo("No namespaces declared. Add one with " "`wikitoolkit ns add <name> --project <dir>`.")
        return
    click.echo(f"{'name':<16} {'kind':<9} {'backend':<9} {'origin':<7} " f"{'built':<6} target")
    for row in rows:
        built = "n/a" if row["built"] is None else ("yes" if row["built"] else "no")
        click.echo(
            f"{row['name']:<16} {row['kind']:<9} {row['backend']:<9} " f"{row['origin']:<7} {built:<6} {row['target']}"
        )
        if row["description"]:
            click.echo(f"{'':<16} {row['description']}")


@ns.command("add")
@click.argument("name")
@path_option
@click.option(
    "--project",
    "src_project",
    default=None,
    help="Root of another wiki project (kind: path).",
)
@click.option(
    "--store",
    "src_store",
    default=None,
    help="Pre-built store directory (kind: store).",
)
@click.option(
    "--backend",
    "backend_opt",
    default=None,
    help=(
        "Backend of a --store directory ('sqlite' or 'memory', default: "
        "sqlite) OR of a --database entry ('arangodb', the default, or a "
        "satellite-registered backend name — e.g. 'ontology_legal', "
        "FEAT-449 M7 — see register_wiki_backend in wiki/store.py). Not "
        "validated against the registry here; an unknown name surfaces "
        "as a ValueError when the namespace is actually opened."
    ),
)
@click.option(
    "--database",
    "src_database",
    default=None,
    help="ArangoDB (or a registered extra backend's) database holding the plane (kind: database).",
)
@click.option(
    "--credentials-env",
    default="ARANGODB",
    show_default=True,
    help="Env var prefix for --database credentials.",
)
@click.option(
    "--vault",
    "src_vault",
    default=None,
    help="Obsidian vault root (kind: vault; requires .obsidian/).",
)
@click.option("--description", default="", help="What this namespace holds.")
@click.option(
    "--weight",
    default=1.0,
    show_default=True,
    type=float,
    help="Score multiplier when merging this namespace (0.0-1.0).",
)
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    help="Write to the per-user registry (PARROT_HOME/wikis.json) " "instead of this repo's wiki.json.",
)
def ns_add(
    name: str,
    path_: str | None,
    src_project: str | None,
    src_store: str | None,
    backend_opt: str | None,
    src_database: str | None,
    credentials_env: str,
    src_vault: str | None,
    description: str,
    weight: float,
    is_global: bool,
) -> None:
    """Register NAME as a namespace this wiki can read.

    This is the only writer of namespace entries — neither ``build`` nor
    any other command ever self-registers a wiki.
    """
    try:
        validate_namespace_name(name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    _namespace_source(src_project, src_store, src_database, src_vault)
    if src_store and backend_opt not in (None, "sqlite", "memory"):
        raise click.ClickException(
            f"--backend {backend_opt!r} is not valid for --store — a "
            "pre-built store directory only supports 'sqlite' or 'memory'. "
            "Registered extra backends (e.g. 'ontology_legal') are only "
            "valid for --database entries."
        )

    # `ns add` (non-global) mutates and re-persists the BASE config, so it
    # must resolve the raw base — never the environment-merged one, or an
    # active overlay's values would get baked permanently into wiki.json.
    root = _find_repo_root(path_)
    try:
        config = load_project_config(root)
    except WikiConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    base_dir = parrot_home() if is_global else root

    # A path typed at the shell is relative to the CALLER's cwd, but a
    # stored entry is read back relative to its registry's directory
    # (repo root / PARROT_HOME). Resolve it here so the two can never
    # disagree: repo entries keep a portable repo-relative form
    # (`../asyncdb`), global entries are stored absolute.
    src_project = _stored_namespace_path(src_project, root, is_global)
    src_store = _stored_namespace_path(src_store, root, is_global)
    src_vault = _stored_namespace_path(src_vault, root, is_global)

    if src_vault:
        vault_dir = Path(src_vault).expanduser()
        if not vault_dir.is_absolute():
            vault_dir = base_dir / vault_dir
        # Inline probe — importing vault_scan here would drag the
        # Obsidian interfaces into every `ns add`.
        if not (vault_dir / ".obsidian").is_dir():
            raise click.ClickException(
                f"{vault_dir} is not an Obsidian vault (no .obsidian/ "
                "directory). Use --project for a plain wiki project."
            )

    try:
        entry = WikiNamespaceConfig(
            path=src_project,
            store=src_store,
            backend=backend_opt or "sqlite",
            database=src_database,
            credentials_env=credentials_env,
            vault=src_vault,
            description=description,
            weight=weight,
        )
    except ValidationError as exc:
        raise click.ClickException(f"Invalid namespace entry: {exc}") from exc

    if is_global:
        with _global_registry_lock():
            registry = load_global_registry()
            if name in registry.namespaces:
                raise click.ClickException(
                    f"Namespace {name!r} already exists in the global "
                    f"registry ({global_registry_path()}). Remove it first."
                )
            registry.namespaces[name] = entry
            written = save_global_registry(registry)
    else:
        if name in config.namespaces:
            raise click.ClickException(f"Namespace {name!r} already exists in {config_path(root)}. " "Remove it first.")
        config.namespaces[name] = entry
        written = save_project_config(root, config)
        if name in load_global_registry().namespaces:
            click.echo(f"Note: this repo entry shadows the global namespace {name!r}.")

    click.echo(f"Added namespace {name!r} ({entry.kind}) → {written}")
    built = _namespace_built(entry, base_dir)
    if built is False:
        target = Path(entry.target).expanduser()
        if not target.is_absolute():
            target = base_dir / target
        flag = "--store" if entry.kind == "store" else "--path"
        click.echo(f"Namespace {name!r} has no plane yet — build it with " f"`wikitoolkit build {flag} {target}`.")


@ns.command("remove")
@click.argument("name")
@path_option
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    help="Remove from the per-user registry instead of this repo.",
)
def ns_remove(name: str, path_: str | None, is_global: bool) -> None:
    """Remove namespace NAME from this repo (or the global registry)."""
    if is_global:
        with _global_registry_lock():
            registry = load_global_registry()
            if name not in registry.namespaces:
                raise click.ClickException(f"No namespace {name!r} in {global_registry_path()}.")
            del registry.namespaces[name]
            written = save_global_registry(registry)
    else:
        root, config = _resolve_project(path_)
        if name not in config.namespaces:
            raise click.ClickException(f"No namespace {name!r} in {config_path(root)}.")
        del config.namespaces[name]
        written = save_project_config(root, config)
    click.echo(f"Removed namespace {name!r} from {written}")


@wiki.command()
@path_option
@click.option(
    "--graph-kinds",
    default="module,document,overview",
    show_default=True,
    help="Comma list of page categories included in the community graph.",
)
@click.option(
    "--inter",
    "show_inter",
    is_flag=True,
    help="Also compute and print inter-community relations (FEAT-401).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def communities(
    path_: str | None,
    graph_kinds: str,
    show_inter: bool,
    as_json: bool,
) -> None:
    """Show detected communities, or inter-community relations with --inter.

    Runs Leiden (falling back to Louvain, FEAT-401) community detection
    on demand from the current wiki store contents — no need to re-run
    `wikitoolkit build` or regenerate graph.html. With `--inter`, also
    computes the inter-community meta-graph (which community pairs are
    connected, coupling ratios, edge direction) for cross-subsystem
    questions like "how do the auth and payment areas relate?". Output
    is token-budgeted for LLM-agent consumption.
    """
    root, config = _resolve_project(path_)
    if not config.is_built(root):
        click.echo(f"Wiki not built for {root} — run `wikitoolkit build`.")
        return
    store = _open_store(root, config)

    kinds = frozenset(k.strip() for k in graph_kinds.split(",") if k.strip())
    nodes, graph_edges = _run(_load_graphindex_nodes_edges(store, kinds))
    if not nodes:
        click.echo(
            "No pages found for --graph-kinds="
            f"{graph_kinds!r}. Run `wikitoolkit build` first, or widen "
            "--graph-kinds."
        )
        return

    from parrot.knowledge.graphindex.assemble import GraphAssembler
    from parrot.knowledge.graphindex.communities import detect_communities

    assembler = GraphAssembler(tenant_id=config.wiki_name)
    assembler.add_nodes(nodes)
    assembler.add_edges(graph_edges)
    communities_result = detect_communities(
        assembler.graph,
        nodes,
        write_back_to_nodes=False,
    )

    if not show_inter:
        if as_json:
            click.echo(
                json.dumps(
                    communities_result.model_dump(mode="json"),
                    indent=2,
                )
            )
            return
        click.echo(
            f"# Communities ({len(communities_result.communities)}, "
            f"algorithm={communities_result.algorithm}, "
            f"modularity={communities_result.modularity:.4f})\n"
        )
        if not communities_result.communities:
            click.echo("(no communities detected)")
            return
        for c in communities_result.communities:
            click.echo(f"| `{c.community_id}` | {c.label or '(unlabeled)'} | {c.size} members |")
        return

    from parrot.knowledge.graphindex.inter_community import (
        compute_inter_community_graph,
    )

    inter = compute_inter_community_graph(assembler.graph, communities_result)

    if as_json:
        click.echo(json.dumps(inter.model_dump(mode="json"), indent=2))
        return

    click.echo(
        f"Inter-Community Relations (density: {inter.density:.1%}, "
        f"{inter.connected_pairs}/{inter.total_possible_pairs} pairs)\n"
    )
    if not inter.relations:
        click.echo("(no cross-community edges detected)")
        return
    for rel in inter.relations:
        arrow = "→" if rel.directed_edge_count >= rel.reverse_edge_count else "←"
        src = rel.source_label or rel.source_community_id
        tgt = rel.target_label or rel.target_community_id
        click.echo(
            f"| {src} {arrow} {tgt} | {rel.directed_edge_count}→, "
            f"{rel.reverse_edge_count}← | coupling: {rel.coupling_ratio:.2f} |"
        )


@wiki.command()
@path_option
@click.option(
    "--output",
    "-o",
    default="docs/wiki",
    show_default=True,
    help="Output directory for the markdown bundle (relative to root).",
)
def export(path_: str | None, output: str) -> None:
    """Export the wiki as a human-readable markdown bundle.

    Writes one markdown file per page (YAML frontmatter + body) plus a
    root index.md — the `--wiki` action of the /parrotwiki command.
    """
    from parrot.knowledge.wiki.export import export_okf_bundle

    root, config = _resolve_project(path_)
    store = _require_built(root, config)
    out_dir = Path(output)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    report = _run(export_okf_bundle(store, out_dir, wiki_name=config.wiki_name))
    # Exclude the export output from future scans, or the next build
    # would ingest the wiki's own exported markdown back into itself.
    try:
        export_rel = out_dir.resolve().relative_to(root).as_posix()
    except ValueError:
        export_rel = None
    if export_rel and export_rel not in config.exclude_dirs:
        config.exclude_dirs.append(export_rel)
        save_project_config(root, config)
    click.echo(
        f"Exported {report.files_written} pages to {out_dir} " f"(index: {'yes' if report.index_generated else 'no'})."
    )


# --------------------------------------------------------------------------
# Authoring / persistent-memory commands ("save things in the brain")
# --------------------------------------------------------------------------


def _authoring_identity(by: str | None) -> str:
    """Resolve who is asserting a write.

    Precedence: explicit ``--by`` > ``CLAUDE_AGENT_ID`` /
    ``PARROT_AGENT_ID`` env (prefixed ``agent:``) > the local user
    (prefixed ``human:``).
    """
    import getpass
    import os

    if by:
        return by
    for env_name in ("CLAUDE_AGENT_ID", "PARROT_AGENT_ID"):
        value = os.environ.get(env_name)
        if value:
            return f"agent:{value}"
    try:
        return f"human:{getpass.getuser()}"
    except Exception:  # noqa: BLE001 — no user db in some containers
        return "human:unknown"


def _authoring_run_id() -> str | None:
    """Session/run identifier from the ambient environment, if any."""
    import os

    for env_name in ("CLAUDE_SESSION_ID", "PARROT_RUN_ID"):
        value = os.environ.get(env_name)
        if value:
            return value
    return None


def _resolve_write_store(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    ns_opt: str | None = None,
) -> tuple[BaseWikiStore, Path | None, Path | None, WikiProjectConfig | None]:
    """Open a store for an authoring command, creating the plane lazily.

    Same precedence as ``_resolve_read_store`` (``--store`` > ``--path``
    project > ``WIKI_STORE`` env > auto-detected project), but a wiki
    that was never built is initialised on first write instead of
    aborting — remembering something must work from a blank slate.

    A write targets exactly ONE plane (spec U2): with ``--ns <name>``
    that namespace is opened read-write directly, bypassing the
    federation entirely. ``--ns all`` is rejected — there is no such
    thing as a broadcast write.

    Returns:
        ``(store, storage_dir, root, config)`` — ``root``/``config`` are
        ``None`` for ``--store`` and ``--ns`` targets (no local project
        context), and ``storage_dir`` is ``None`` for a server-hosted
        namespace.

    Raises:
        click.ClickException: On ``--ns all``, several ``--ns`` names,
            ``--store`` combined with ``--ns``, an undeclared namespace,
            or a namespace that cannot be opened.
    """
    if ns_opt not in (None, "local"):
        if store_opt:
            raise click.ClickException("--store and --ns target different planes; use one of them.")
        if ns_opt == "all" or "," in ns_opt:
            raise click.ClickException(
                "A write targets exactly one namespace — " f"`--ns {ns_opt}` is not a write target."
            )
        root, config = _resolve_project(path_)
        declared = _declared_namespaces(config)
        entry = declared.get(ns_opt)
        if entry is None:
            raise _unknown_namespace(ns_opt, list(declared))
        cfg, origin = entry
        try:
            store, storage_dir = _run(
                open_namespace_store(
                    ns_opt,
                    cfg,
                    base_dir=resolve_entry_base(origin, root),
                    read_only=False,
                )
            )
        except Exception as exc:  # surfaced as a clear CLI error
            raise click.ClickException(f"Could not open namespace {ns_opt!r} for writing: {exc}") from exc
        return store, storage_dir, None, None

    store_override = store_opt
    if not store_override and not path_:
        store_override = _env_setting("WIKI_STORE")
    if store_override:
        backend = backend_opt or _env_setting("WIKI_STORE_BACKEND") or "sqlite"
        storage_dir = Path(store_override).expanduser()
        storage_dir.mkdir(parents=True, exist_ok=True)
        return create_wiki_store(storage_dir, backend=backend), storage_dir, None, None
    root, config = _resolve_project(path_)
    if backend_opt:
        config.backend = backend_opt  # type: ignore[assignment]
    else:
        env_backend = _env_setting("WIKI_STORE_BACKEND")
        if env_backend:
            config.backend = env_backend  # type: ignore[assignment]
    return _open_store(root, config), config.storage_path(root), root, config


def _sync_memory_to_graph(
    root: Path,
    config: WikiProjectConfig,
    store: BaseWikiStore,
    page_id: str,
    title: str,
    text: str,
    links: list[tuple[str, str]],
    asserted_by: str,
    run_id: str | None,
) -> str | None:
    """Mirror a remembered fact into the project's GraphIndex plane.

    Publishes one audited commit containing a ``CONCEPT`` node for the
    memory (plus stub nodes for linked wiki pages so no edge dangles)
    into ``.parrot/graph/``. GraphIndex imports stay inside this
    function so the wiki CLI works without the graphindex extra.

    Returns:
        The commit id, or ``None`` when sync failed/unavailable.
    """
    try:
        from parrot.knowledge.graphindex.factory import make_stub_tenant_context
        from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
        from parrot.knowledge.graphindex.publish import GraphPublisher
        from parrot.knowledge.graphindex.schema import (
            EdgeKind,
            GraphUpdate,
            NodeKind,
            Provenance,
            UniversalEdge,
            UniversalNode,
        )
    except ImportError as exc:
        click.echo(f"[graph sync skipped: graphindex unavailable — {exc}]")
        return None

    try:
        ctx = make_stub_tenant_context(config.wiki_name)
        persistence = SQLitePersistence(config.graph_path(root))
        publisher = GraphPublisher(persistence, ctx)

        nodes = [
            UniversalNode(
                node_id=page_id,
                kind=NodeKind.CONCEPT,
                title=title,
                source_uri=f"wiki://{config.wiki_name}/{page_id}",
                summary=text[:300],
                provenance=Provenance.ASSERTED,
            )
        ]
        edges = []
        for target_id, rel in links:
            target = _run(store.get_page(target_id, include_body=False))
            if target is None:
                continue
            nodes.append(
                UniversalNode(
                    node_id=target_id,
                    kind=NodeKind.CONCEPT,
                    title=str(target.get("title") or target_id),
                    source_uri=f"wiki://{config.wiki_name}/{target_id}",
                    summary=str(target.get("summary") or "")[:300],
                )
            )
            try:
                kind = EdgeKind(rel)
            except ValueError:
                kind = EdgeKind.REFERENCES
            edges.append(UniversalEdge(source_id=page_id, target_id=target_id, kind=kind))
        receipt = _run(
            publisher.publish(
                GraphUpdate(
                    nodes=nodes,
                    edges=edges,
                    agent_id=asserted_by.split(":", 1)[-1],
                    run_id=run_id,
                    asserted_by=asserted_by,
                    source=f"wiki://{config.wiki_name}/{page_id}",
                    op="remember",
                )
            )
        )
        return receipt.commit_id
    except Exception as exc:  # noqa: BLE001 — sync must never block the save
        click.echo(f"[graph sync failed: {exc}]")
        return None


def _extract_into_graph(
    root: Path,
    config: WikiProjectConfig,
    text: str,
    source_uri: str,
    asserted_by: str,
    run_id: str | None,
) -> dict[str, Any] | None:
    """Run LLM entity/relation extraction into the project graph plane.

    Requires a ``WIKI_EXTRACT_LLM`` provider spec (env / .env, e.g.
    ``anthropic:claude-haiku-4-5``). All heavyweight imports are lazy;
    every failure degrades to ``None`` so the plain remember always
    succeeds.

    Returns:
        Extraction summary dict, or ``None`` when unavailable/failed.
    """
    spec = _env_setting("WIKI_EXTRACT_LLM")
    if not spec:
        click.echo("[extract skipped: set WIKI_EXTRACT_LLM (e.g." " 'anthropic:claude-haiku-4-5') to enable]")
        return None
    try:
        from parrot.clients.factory import LLMFactory
        from parrot.knowledge.graphindex.extractors.llm import LLMGraphExtractor
        from parrot.knowledge.graphindex.factory import make_stub_tenant_context
        from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
        from parrot.knowledge.graphindex.publish import GraphPublisher

        client = LLMFactory.create(spec, model_args={"temperature": 0.0})
        ctx = make_stub_tenant_context(config.wiki_name)
        publisher = GraphPublisher(SQLitePersistence(config.graph_path(root)), ctx)
        extractor = LLMGraphExtractor(client, publisher)
        result = _run(
            extractor.extract_and_publish(
                text,
                source_uri=source_uri,
                agent_id=asserted_by.split(":", 1)[-1],
                run_id=run_id,
            )
        )
        return {
            "entities": len(result.extracted.entities),
            "relations": len(result.extracted.relations),
            "nodes_written": len(result.update.nodes),
            "commit_id": result.receipt.commit_id,
        }
    except Exception as exc:  # noqa: BLE001 — extraction is best-effort
        click.echo(f"[extract failed: {exc}]")
        return None


@wiki.command()
@click.argument("text")
@path_option
@_store_options
@click.option("--title", default=None, help="Short title (default: first line).")
@click.option(
    "--category",
    default="note",
    help="Memory category: note | decision | lesson | concept.",
)
@click.option(
    "--link",
    "links",
    multiple=True,
    help="Existing page id to link the memory to (repeatable).",
)
@click.option("--rel", default="references", help="Relation for --link edges.")
@ns_option
@click.option("--source", "source_uri", default=None, help="Citation URI.")
@click.option("--by", default=None, help="Identity asserting this memory.")
@click.option(
    "--extract",
    "extract_",
    is_flag=True,
    help="Also run LLM entity/relation extraction over the text into the"
    " project graph (requires sync_graph and a WIKI_EXTRACT_LLM provider"
    " spec, e.g. 'anthropic:claude-haiku-4-5'; degrades to a plain"
    " remember when unavailable).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def remember(
    text: str,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    title: str | None,
    category: str,
    links: tuple[str, ...],
    rel: str,
    ns_opt: str | None,
    source_uri: str | None,
    by: str | None,
    extract_: bool,
    as_json: bool,
) -> None:
    """Save a fact, decision, or lesson into the wiki (persistent memory).

    The page id is a deterministic hash of title+category, so
    re-remembering the same thing updates the existing memory instead of
    duplicating it. With ``sync_graph`` enabled in ``.parrot/wiki.json``
    the memory is also mirrored into the project's knowledge graph as an
    audited commit.
    """
    import hashlib

    store, storage_dir, root, config = _resolve_write_store(path_, store_opt, backend_opt, ns_opt)
    asserted_by = _authoring_identity(by)
    run_id = _authoring_run_id()

    resolved_title = (title or text.strip().splitlines()[0][:80]).strip()
    if not resolved_title:
        raise click.ClickException("Cannot remember empty text.")
    page_id = "mem-" + hashlib.sha1(f"{resolved_title}::{category}".encode()).hexdigest()[:12]

    from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens

    existing = _run(store.get_page(page_id, include_body=False))
    body = text if not source_uri else f"{text}\n\n> Source: {source_uri}"
    _run(
        store.upsert_pages(
            [
                WikiPageRecord(
                    concept_id=page_id,
                    node_id=page_id,
                    title=resolved_title,
                    category=category,
                    summary=text[:300],
                    body=body,
                    token_count=estimate_tokens(body),
                    origin="memory",
                    asserted_by=asserted_by,
                )
            ]
        )
    )

    linked: list[tuple[str, str]] = []
    skipped_links: list[str] = []
    for target in (_write_id_for_ns(link, ns_opt) for link in links):
        page = _run(store.get_page(target, include_body=False))
        if page is None:
            skipped_links.append(target)
            continue
        _run(store.add_edges([(page_id, page["concept_id"], rel, "asserted")]))
        linked.append((page["concept_id"], rel))

    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

    if storage_dir is not None:
        WikiBookkeeper().log_operation(
            storage_dir,
            "REMEMBER",
            f"page_id: {page_id}, title: {resolved_title!r}, "
            f"category: {category}, by: {asserted_by}" + (f", run: {run_id}" if run_id else ""),
        )

    commit_id: str | None = None
    if root is not None and config is not None and config.sync_graph:
        commit_id = _sync_memory_to_graph(
            root,
            config,
            store,
            page_id,
            resolved_title,
            text,
            linked,
            asserted_by,
            run_id,
        )

    extraction: dict[str, Any] | None = None
    if extract_ and root is not None and config is not None:
        extraction = _extract_into_graph(
            root,
            config,
            text,
            source_uri or f"wiki://{config.wiki_name}/{page_id}",
            asserted_by,
            run_id,
        )

    result = {
        "page_id": page_id,
        "title": resolved_title,
        "category": category,
        "status": "updated" if existing else "created",
        "asserted_by": asserted_by,
        "linked": [t for t, _ in linked],
        "skipped_links": skipped_links,
    }
    if commit_id:
        result["graph_commit"] = commit_id
    if extraction:
        result["extraction"] = extraction
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(f"{'Updated' if existing else 'Saved'} memory {page_id} " f"({category}): {resolved_title!r}")
    for target, rel_name in linked:
        click.echo(f"  linked → {target} ({rel_name})")
    for target in skipped_links:
        click.echo(f"  [skipped link: no page {target!r}]")
    if commit_id:
        click.echo(f"  graph commit: {commit_id}")
    if extraction:
        click.echo(
            f"  extracted: {extraction.get('entities', 0)} entities,"
            f" {extraction.get('relations', 0)} relations"
            f" (commit {extraction.get('commit_id', '?')})"
        )


@wiki.command()
@click.argument("page_id")
@click.argument("text")
@path_option
@_store_options
@ns_option
@click.option("--by", default=None, help="Identity asserting this note.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def note(
    page_id: str,
    text: str,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    ns_opt: str | None,
    by: str | None,
    as_json: bool,
) -> None:
    """Append an attributed note to an existing wiki page.

    With ``--ns <name>`` the note is written into that namespace's own
    plane; PAGE_ID may be given qualified (``name::file:a.py``).
    """
    from datetime import datetime

    store, storage_dir, _root, _config = _resolve_write_store(path_, store_opt, backend_opt, ns_opt)
    page_id = _write_id_for_ns(page_id, ns_opt)
    page = _run(store.get_page(page_id, include_body=True))
    if page is None:
        raise click.ClickException(f'Page {page_id!r} not found. Search first: wikitoolkit query "..."')
    asserted_by = _authoring_identity(by)
    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    body = str(page.get("body") or "")
    body += f"\n\n> **Note ({stamp}, {asserted_by}):** {text}"

    from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens

    _run(
        store.upsert_pages(
            [
                WikiPageRecord(
                    concept_id=page["concept_id"],
                    node_id=page.get("node_id"),
                    title=page.get("title") or page["concept_id"],
                    category=page.get("category") or "concept",
                    summary=page.get("summary") or "",
                    body=body,
                    source_id=page.get("source_id"),
                    token_count=estimate_tokens(body),
                    origin=page.get("origin") or "ingest",
                    asserted_by=asserted_by,
                )
            ]
        )
    )
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

    if storage_dir is not None:
        WikiBookkeeper().log_operation(
            storage_dir,
            "NOTE",
            f"page_id: {page['concept_id']}, by: {asserted_by}",
        )
    result = {"page_id": page["concept_id"], "status": "noted", "by": asserted_by}
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Noted on {page['concept_id']} (by {asserted_by}).")


@wiki.command()
@click.argument("src")
@click.argument("dst")
@path_option
@_store_options
@click.option("--rel", default="references", help="Edge relation.")
@ns_option
@click.option("--by", default=None, help="Identity asserting this link.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def link(
    src: str,
    dst: str,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    rel: str,
    ns_opt: str | None,
    by: str | None,
    as_json: bool,
) -> None:
    """Connect two existing wiki pages with an asserted, typed edge.

    Both pages must live in the same plane — there are no
    cross-namespace edges. With ``--ns <name>`` the edge is written into
    that namespace; ids may be given qualified with that same name.
    """
    store, storage_dir, _root, _config = _resolve_write_store(path_, store_opt, backend_opt, ns_opt)
    pages = {}
    for label, cid in (
        ("src", _write_id_for_ns(src, ns_opt)),
        ("dst", _write_id_for_ns(dst, ns_opt)),
    ):
        page = _run(store.get_page(cid, include_body=False))
        if page is None:
            raise click.ClickException(f"{label} page {cid!r} not found.")
        pages[label] = page["concept_id"]
    asserted_by = _authoring_identity(by)
    _run(store.add_edges([(pages["src"], pages["dst"], rel, "asserted")]))

    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

    if storage_dir is not None:
        WikiBookkeeper().log_operation(
            storage_dir,
            "LINK",
            f"{pages['src']} -{rel}-> {pages['dst']}, by: {asserted_by}",
        )
    result = {
        "src": pages["src"],
        "dst": pages["dst"],
        "rel": rel,
        "status": "linked",
        "by": asserted_by,
    }
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Linked {pages['src']} -{rel}-> {pages['dst']}.")


@wiki.command()
@path_option
@_store_options
@click.option("--category", default=None, help="Filter by category.")
@click.option("--limit", default=50, type=int, help="Maximum rows.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def memories(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    category: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """List saved memories and agent-authored pages (newest first)."""
    store, _storage_dir, _root, _config = _resolve_write_store(path_, store_opt, backend_opt)
    rows = _run(store.list_pages(category=category, limit=limit, origin=["memory", "authored"]))
    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        click.echo('No memories saved yet. Save one: wikitoolkit remember "..."')
        return
    for row in rows:
        click.echo(
            f"{row['concept_id']}  [{row.get('category')}]"
            f"  {row.get('title')!r}"
            f"  — {row.get('asserted_by') or '?'} @ {row.get('updated_at')}"
        )


@wiki.command()
@path_option
@_store_options
@click.option("--limit", default=30, type=int, help="Maximum entries per plane.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def audit(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """Show the wiki operation log and graph write commits (audit trail)."""
    _store, storage_dir, root, config = _resolve_write_store(path_, store_opt, backend_opt)
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

    log_text = WikiBookkeeper().read_log(storage_dir, last_n=limit)

    graph_commits: list[dict[str, Any]] = []
    if root is not None and config is not None:
        graph_db = config.graph_path(root) / f"{config.wiki_name}.db"
        if graph_db.exists():
            try:
                from parrot.knowledge.graphindex.factory import (
                    make_stub_tenant_context,
                )
                from parrot.knowledge.graphindex.persist_sqlite import (
                    SQLitePersistence,
                )

                persistence = SQLitePersistence(config.graph_path(root))
                ctx = make_stub_tenant_context(config.wiki_name)
                graph_commits = _run(persistence.list_commits(ctx, limit=limit))
            except Exception as exc:  # noqa: BLE001
                click.echo(f"[graph audit unavailable: {exc}]")

    if as_json:
        click.echo(
            json.dumps(
                {"log": log_text.splitlines(), "graph_commits": graph_commits},
                indent=2,
                default=str,
            )
        )
        return
    click.echo("## Wiki operation log")
    click.echo(log_text or "(empty)")
    if graph_commits:
        click.echo("\n## Graph write commits")
        for c in graph_commits:
            reverted = " [REVERTED]" if c.get("reverted_at") else ""
            click.echo(f"{c['commit_id']}  {c['op']}  by {c['asserted_by']}" f"  @ {c['committed_at']}{reverted}")


@wiki.command()
@click.argument("claim")
@path_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def ground(
    claim: str,
    path_: str | None,
    as_json: bool,
) -> None:
    """Check a claim against the project knowledge graph (grounding).

    Requires the project graph plane (``.parrot/graph/``) created by
    ``remember`` with ``sync_graph`` enabled or by ``--extract``.
    Returns cited edge-level evidence, or a structured revise
    instruction listing the missing evidence.
    """
    root, config = _resolve_project(path_)
    graph_db = config.graph_path(root) / f"{config.wiki_name}.db"
    if not graph_db.exists():
        raise click.ClickException(
            f"No graph plane at {graph_db}. Save graph-synced knowledge"
            " first (enable sync_graph in .parrot/wiki.json, then"
            " `wikitoolkit remember ...`)."
        )
    try:
        from parrot.knowledge.graphindex.assemble import GraphAssembler
        from parrot.knowledge.graphindex.factory import (
            HashingGraphEmbedder,
            make_stub_tenant_context,
        )
        from parrot.knowledge.graphindex.grounding import GroundingEvaluator
        from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
    except ImportError as exc:
        raise click.ClickException(f"graphindex unavailable: {exc}") from exc

    async def _ground() -> dict[str, Any]:
        persistence = SQLitePersistence(config.graph_path(root))
        ctx = make_stub_tenant_context(config.wiki_name)
        nodes, edges = await persistence.load_graph(ctx)
        assembler = GraphAssembler(tenant_id=config.wiki_name)
        for node in nodes:
            assembler.add_node(node)
        for edge in edges:
            assembler.add_edge(edge)
        embedder = HashingGraphEmbedder()
        if nodes:
            await embedder.embed_nodes(nodes)
        retriever = GraphExpandedRetriever(graph=assembler.graph, nodes=nodes, embedder=embedder)
        result = await GroundingEvaluator(retriever).ground_claim(claim)
        return result.model_dump()

    data = _run(_ground())
    if as_json:
        click.echo(json.dumps(data, indent=2))
        return
    click.echo(f"Decision: {data['decision'].upper()}")
    click.echo(f"Reason:   {data['reason']}")
    if data.get("supported_paths"):
        click.echo("Evidence paths (stable edge ids):")
        for path in data["supported_paths"]:
            click.echo(f"  - {' ; '.join(path)}")
    if data.get("contradictions"):
        click.echo(f"Contradictions: {', '.join(data['contradictions'])}")
    for needed in data.get("required_evidence", []):
        click.echo(f"Required: {needed}")


# --------------------------------------------------------------------------
# Sync (FEAT-461) — push/pull authored knowledge with a shared plane.
# --------------------------------------------------------------------------


@wiki.group(name="sync")
def sync() -> None:
    """Push/pull authored knowledge (memories, notes) with a shared plane.

    The local identity used to attribute writes and filter `pull` is
    always ``human:<local-user>`` in v1 — there is no override flag yet.

    `sync obsidian` is the third direction: a one-way mirror of wiki
    planes into an Obsidian vault, configured by page category/folder.
    """


@sync.command("push")
@path_option
@click.option(
    "--env",
    "target_env",
    default="dev",
    show_default=True,
    help="Target environment whose effective config names the shared plane.",
)
@click.option("--dry-run", is_flag=True, help="Compute and print the report; apply nothing.")
def sync_push_cmd(path_: str | None, target_env: str, dry_run: bool) -> None:
    """Push local memories/notes/asserted edges to the ENV plane.

    Every local memory page moves — push never filters by authorship.
    """
    from parrot.knowledge.wiki.sync import SyncError, default_local_identity, sync_push

    root, _config = _resolve_project(path_)
    try:
        report = _run(
            sync_push(
                root,
                target_env=target_env,
                dry_run=dry_run,
                local_identity=default_local_identity(),
            )
        )
    except SyncError as exc:
        raise click.ClickException(str(exc)) from exc
    if report.dry_run:
        click.echo("DRY RUN — nothing applied")
    click.echo(f"pushed: created={report.created} updated={report.updated} " f"skipped-older={report.skipped_older}")


@sync.command("pull")
@path_option
@click.option(
    "--env",
    "target_env",
    default="dev",
    show_default=True,
    help="Target environment whose effective config names the shared plane.",
)
@click.option("--dry-run", is_flag=True, help="Compute and print the report; apply nothing.")
@click.option(
    "--all",
    "include_own",
    is_flag=True,
    help=(
        "Include records authored by the local identity (human:<user>) too "
        "— default excludes them so your own memories stay authoritative."
    ),
)
def sync_pull_cmd(path_: str | None, target_env: str, dry_run: bool, include_own: bool) -> None:
    """Pull memories/notes/asserted edges from the ENV plane.

    By default, records authored by the local identity (``human:<user>``)
    are excluded (``--all`` switches to pure last-write-wins).
    """
    from parrot.knowledge.wiki.sync import SyncError, default_local_identity, sync_pull

    root, _config = _resolve_project(path_)
    try:
        report = _run(
            sync_pull(
                root,
                target_env=target_env,
                include_own=include_own,
                dry_run=dry_run,
                local_identity=default_local_identity(),
            )
        )
    except SyncError as exc:
        raise click.ClickException(str(exc)) from exc
    if report.dry_run:
        click.echo("DRY RUN — nothing applied")
    click.echo(
        f"pulled: created={report.created} updated={report.updated} "
        f"skipped-older={report.skipped_older} skipped-own={report.skipped_own}"
    )


@sync.command("obsidian")
@path_option
@click.option(
    "--vault",
    "vault_opt",
    default=None,
    help="Obsidian vault root to sync into (default: obsidian_sync.vault_dir, then the project vault_dir).",
)
@click.option(
    "--ns",
    "ns_opt",
    default=None,
    help=(
        "Comma-separated planes to sync: 'local', declared namespace "
        "names, or 'all' (default: obsidian_sync.namespaces, else 'local')."
    ),
)
@click.option(
    "--category",
    "category_opt",
    multiple=True,
    help="Sync only these page categories (repeatable; overrides obsidian_sync.categories).",
)
@click.option(
    "--prune/--no-prune",
    "prune_opt",
    default=None,
    help=(
        "Also delete previously synced notes whose page vanished or is no "
        "longer selected. Only notes carrying the wiki_sync frontmatter "
        "marker are ever deleted (default: obsidian_sync.prune)."
    ),
)
@click.option("--dry-run", is_flag=True, help="Compute and print the report; write nothing.")
@click.option("--verbose", "-v", "verbose_", is_flag=True, help="Print one line per note.")
def sync_obsidian_cmd(
    path_: str | None,
    vault_opt: str | None,
    ns_opt: str | None,
    category_opt: tuple[str, ...],
    prune_opt: bool | None,
    dry_run: bool,
    verbose_: bool,
) -> None:
    """Mirror wiki planes into an Obsidian vault as markdown notes.

    Which categories sync and which vault folder each one maps onto is
    driven by the ``obsidian_sync`` section of ``.parrot/wiki.json``
    (categories/folders/root_folder/namespaces); flags override per run.
    One-way wiki -> vault: notes land under the configured root folder
    with a ``wiki_sync`` frontmatter marker, and edges between synced
    pages become ``[[wikilinks]]`` in a Related section.
    """
    from parrot.knowledge.wiki.obsidian_sync import ObsidianSyncError, sync_obsidian

    root, _config = _resolve_project(path_)
    namespaces = [part.strip() for part in ns_opt.split(",") if part.strip()] if ns_opt else None
    try:
        report = _run(
            sync_obsidian(
                root,
                vault=vault_opt,
                namespaces=namespaces,
                categories=list(category_opt) or None,
                prune=prune_opt,
                dry_run=dry_run,
            )
        )
    except ObsidianSyncError as exc:
        raise click.ClickException(str(exc)) from exc
    if report.dry_run:
        click.echo("DRY RUN — nothing applied")
    planes = ",".join(report.namespaces) or "(none)"
    click.echo(
        f"synced {planes} -> {report.vault}: created={report.created} "
        f"updated={report.updated} unchanged={report.unchanged} pruned={report.pruned}"
    )
    for line in report.skipped_namespaces:
        click.echo(f"(namespace skipped: {line})")
    if verbose_:
        for line in report.details:
            click.echo(line)


# --------------------------------------------------------------------------
# Supervised ingestion (FEAT-402) — charter-driven triage + HITL manifest
# review. Alongside (not inside) `build`: the deterministic, offline,
# no-LLM `build`/`_ingest_files` path above is untouched (spec §1
# Non-Goals). ALL triage/manifest/router logic lives in charter.py /
# review.py / triage.py / ingest.py — this section only wires those
# modules together and handles CLI argument parsing (hot-file discipline).
# --------------------------------------------------------------------------


def _resolve_charter_path(root: Path, charter_opt: str | None) -> Path:
    """Resolve the charter YAML path: ``--charter``, else the project default.

    Args:
        root: Repository root.
        charter_opt: The raw ``--charter`` CLI value, or ``None``.

    Returns:
        The resolved charter file path.

    Raises:
        click.ClickException: If neither an explicit path nor the
            default ``<root>/.parrot/charter.yaml`` exists.
    """
    if charter_opt:
        path = Path(charter_opt)
        if not path.exists():
            raise click.ClickException(f"No charter found at {path}.")
        return path
    default_path = root / PARROT_DIR / "charter.yaml"
    if default_path.exists():
        return default_path
    raise click.ClickException("No editorial charter found. Pass --charter <path>, or place one " f"at {default_path}.")


def _resolve_model_id(cli_value: str | None, env_name: str) -> str:
    """Resolve a model spec from a CLI flag, else an env var, else error.

    Args:
        cli_value: The raw CLI flag value, or ``None``.
        env_name: Environment variable name to fall back to.

    Returns:
        A ``"provider:model"`` (or ``"provider"``) spec string.

    Raises:
        click.ClickException: If neither is set.
    """
    value = cli_value or _env_setting(env_name)
    if not value:
        raise click.ClickException(
            f"No model configured — pass the flag or set ${env_name} "
            "(format: 'provider:model', e.g. 'groq:llama-3.3-70b-versatile')."
        )
    return value


def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:
    """Construct the lightweight/heavy ``PageIndexLLMAdapter`` pair.

    A narrow, deliberately monkeypatchable seam: tests replace this
    function wholesale to inject stub adapters instead of constructing
    real LLM clients (``LLMFactory.create``).

    Args:
        lightweight_model: Stage-1 triage model spec.
        model: Stage-2 (gray-zone escalation) model spec, also reused
            for real page-content generation (``PageIndexToolkit``).

    Returns:
        ``(lightweight_adapter, heavy_adapter, lightweight_model_id,
        same_provider)``. ``same_provider`` is ``True`` when both specs
        resolve to the same provider — see the ``ingest`` command for why
        this matters: ``PageIndexToolkit`` builds its own internal
        lightweight adapter by pairing the *heavy* adapter's client with
        the lightweight model id, so mixing providers there would send
        one provider's client a model id meant for a different provider.
    """
    from parrot.clients.factory import LLMFactory
    from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter

    light_provider, light_model_id = LLMFactory.parse_llm_string(lightweight_model)
    heavy_provider, heavy_model_id = LLMFactory.parse_llm_string(model)
    light_client = LLMFactory.create(lightweight_model)
    heavy_client = light_client if model == lightweight_model else LLMFactory.create(model)
    light_adapter = PageIndexLLMAdapter(light_client, model=light_model_id)
    heavy_adapter = PageIndexLLMAdapter(heavy_client, model=heavy_model_id)
    same_provider = light_provider == heavy_provider
    return light_adapter, heavy_adapter, light_model_id, same_provider


def _build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:
    """Construct a NoveltyScorer: grounding-backed when the graph DB
    exists (mirrors the ``ground`` command's wiring above), else a
    ``WikiCombinedSearch`` similarity-proxy fallback.

    Args:
        root: Repository root.
        config: The project's ``WikiProjectConfig``.
        store: The open retrieval-plane store, used by the search-proxy
            fallback.

    Returns:
        A configured ``NoveltyScorer``.
    """
    from parrot.knowledge.wiki.search import WikiCombinedSearch
    from parrot.knowledge.wiki.triage import NoveltyScorer

    graph_db = config.graph_path(root) / f"{config.wiki_name}.db"
    if not graph_db.exists():
        return NoveltyScorer(
            grounding_evaluator=None,
            search=WikiCombinedSearch(None, None, store=store),
        )

    try:
        from parrot.knowledge.graphindex.assemble import GraphAssembler
        from parrot.knowledge.graphindex.factory import (
            HashingGraphEmbedder,
            make_stub_tenant_context,
        )
        from parrot.knowledge.graphindex.grounding import GroundingEvaluator
        from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
    except ImportError:
        return NoveltyScorer(
            grounding_evaluator=None,
            search=WikiCombinedSearch(None, None, store=store),
        )

    async def _build_evaluator() -> Any:
        persistence = SQLitePersistence(config.graph_path(root))
        ctx = make_stub_tenant_context(config.wiki_name)
        nodes, edges = await persistence.load_graph(ctx)
        assembler = GraphAssembler(tenant_id=config.wiki_name)
        for node in nodes:
            assembler.add_node(node)
        for edge in edges:
            assembler.add_edge(edge)
        embedder = HashingGraphEmbedder()
        if nodes:
            await embedder.embed_nodes(nodes)
        retriever = GraphExpandedRetriever(graph=assembler.graph, nodes=nodes, embedder=embedder)
        return GroundingEvaluator(retriever)

    evaluator = _run(_build_evaluator())
    return NoveltyScorer(grounding_evaluator=evaluator)


def _print_triage_summary(entries: list[Any], skipped: list[str] | None = None) -> None:
    """Print a rich admit/archive/discard summary table.

    Args:
        entries: Triaged manifest entries.
        skipped: FEAT-451 — source URIs that could not be decoded/
            extracted and were skipped before triage. Adds a "skipped"
            row when non-empty.
    """
    from rich.console import Console
    from rich.table import Table

    counts = Counter(e.proposed_action for e in entries)
    table = Table(title="Supervised Ingestion — Triage Summary")
    table.add_column("Proposed action", style="bold")
    table.add_column("Count", justify="right", style="cyan")
    for action in ("admit", "archive", "discard"):
        table.add_row(action, str(counts.get(action, 0)))
    if skipped:
        table.add_row("skipped (undecodable)", str(len(skipped)))
    Console().print(table)


@wiki.command()
@click.argument("source")
@path_option
@click.option(
    "--charter",
    "charter_opt",
    default=None,
    help="Path to the editorial charter YAML " "(default: <repo>/.parrot/charter.yaml).",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Triage all docs, emit a manifest, ingest nothing.",
)
@click.option(
    "--review",
    "review_opt",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Apply human-edited decisions from a manifest.jsonl.",
)
@click.option(
    "--interactive",
    "interactive_flag",
    is_flag=True,
    help="Prompt per-document before applying (questionary).",
)
@click.option(
    "--auto",
    "auto_flag",
    is_flag=True,
    help="Charter thresholds decide automatically; flags a stratified audit sample.",
)
@click.option(
    "--extract",
    "extract_flag",
    is_flag=True,
    help="EXPERIMENTAL: include extracted claims in the manifest. Off by" " default — v1 admission is document-level.",
)
@click.option(
    "--lightweight-model",
    "lightweight_model_opt",
    default=None,
    help="Stage-1 triage model ('provider:model'). Falls back to $WIKI_LIGHTWEIGHT_MODEL.",
)
@click.option(
    "--model",
    "model_opt",
    default=None,
    help="Stage-2 escalation / page-generation model ('provider:model')." " Falls back to $WIKI_MODEL.",
)
@click.option(
    "--audit-rate",
    "audit_rate",
    default=0.1,
    show_default=True,
    help="Fraction of --auto decisions flagged for stratified audit review.",
)
@click.option(
    "--manifest",
    "manifest_opt",
    default=None,
    type=click.Path(path_type=Path),
    help="Manifest output path (default: <storage_dir>/ingest-manifest.jsonl).",
)
@click.option(
    "--recursive/--no-recursive",
    "recursive",
    default=True,
    show_default=True,
    help="When SOURCE is a directory, walk it recursively.",
)
@click.option(
    "--fetch-timeout",
    "fetch_timeout",
    default=30.0,
    show_default=True,
    help="Timeout (seconds) for a URL SOURCE fetch.",
)
def ingest(
    source: str,
    path_: str | None,
    charter_opt: str | None,
    dry_run: bool,
    review_opt: Path | None,
    interactive_flag: bool,
    auto_flag: bool,
    extract_flag: bool,
    lightweight_model_opt: str | None,
    model_opt: str | None,
    audit_rate: float,
    manifest_opt: Path | None,
    recursive: bool,
    fetch_timeout: float,
) -> None:
    """Supervised (charter-driven) ingestion of a document corpus.

    Unlike ``build`` (deterministic, offline, no-LLM), ``ingest`` triages
    each document in SOURCE against an editorial charter before it
    becomes a wiki page: free heuristics reject duplicates/oversized
    files, a lightweight model scores the rest, and only gray-zone
    documents escalate to a heavier model. Exactly one mode is required.

    SOURCE accepts a directory (recursive walk by default — see
    ``--recursive``/``--no-recursive``), a single document path, or an
    ``http(s)://`` URL. PDF, DOCX, PPTX, XLSX, HTML, and EPUB are
    extracted through the optional ``ai-parrot-loaders`` package;
    plain-text/Markdown formats need no extra dependency. A document
    that cannot be decoded is skipped, counted, and reported — never
    triaged, and never charged an LLM call.

    \b
    --dry-run      Triage everything, write a manifest, ingest nothing.
    --review PATH  Apply decisions from a hand-edited manifest.
    --interactive  Prompt per-document (before any async work starts).
    --auto         Thresholds decide; flags a stratified audit sample.
    """
    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
    from parrot.knowledge.wiki.charter import (
        TriageExample,
        append_example,
        load_charter,
    )
    from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
    from parrot.knowledge.wiki.models import WikiConfig
    from parrot.knowledge.wiki.review import (
        ManifestReader,
        ManifestRunHeader,
        ManifestWriter,
        stratified_sample,
    )
    from parrot.knowledge.wiki.triage import IngestTriageRouter

    modes_selected = sum([dry_run, review_opt is not None, interactive_flag, auto_flag])
    if modes_selected == 0:
        raise click.UsageError("Pick exactly one mode: --dry-run, --review, --interactive, or --auto.")
    if modes_selected > 1:
        raise click.UsageError("--dry-run / --review / --interactive / --auto are mutually exclusive.")
    mode = (
        "dry-run" if dry_run else "review" if review_opt is not None else "interactive" if interactive_flag else "auto"
    )

    root, config = _resolve_project(path_)
    store = _open_store(root, config)
    sources = _open_sources(root, config, store=store)
    bookkeeper = WikiBookkeeper()
    wiki_dir = config.storage_path(root)
    manifest_path = manifest_opt or (wiki_dir / "ingest-manifest.jsonl")

    def _log_triage(entry: Any) -> None:
        details = (
            f"source: {entry.source_uri}, composite: {entry.composite:.4f}, "
            f"proposed_action: {entry.proposed_action}"
        )
        bookkeeper.log_operation(wiki_dir, "TRIAGE", details)

    def _report_skipped(skipped: list[str]) -> None:
        """Echo the skip count; list the paths too under -v/--verbose."""
        if not skipped:
            return
        click.echo(f"Skipped {len(skipped)} undecodable document(s).")
        verbose = click.get_current_context().find_root().params.get("verbose")
        if verbose:
            for uri in skipped:
                click.echo(f"  skipped: {uri}")

    lightweight_model = _resolve_model_id(lightweight_model_opt, "WIKI_LIGHTWEIGHT_MODEL")
    model = _resolve_model_id(model_opt, "WIKI_MODEL")
    light_adapter, heavy_adapter, light_model_id, same_provider = _build_triage_adapters(lightweight_model, model)
    pageindex_dir = wiki_dir / "pageindex"
    pageindex_dir.mkdir(parents=True, exist_ok=True)
    # PageIndexToolkit builds its OWN internal lightweight adapter as
    # PageIndexLLMAdapter(client=heavy_adapter.client, model=lightweight_model)
    # (packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py) — i.e.
    # it always reuses the HEAVY adapter's client. When --lightweight-model
    # and --model point at different providers, passing light_model_id
    # there would send a foreign model id to the heavy provider's client.
    # Only pass it through when both tiers share a provider; otherwise
    # PageIndexToolkit falls back to using the heavy adapter for both of
    # its own internal steps (safe, just not dual-tier for page generation
    # — the triage router's own light/heavy split above is unaffected).
    pi_toolkit = PageIndexToolkit(
        heavy_adapter,
        storage_dir=pageindex_dir,
        lightweight_model=light_model_id if same_provider else None,
    )
    if not same_provider:
        _cli_logger.info(
            "Stage-1/Stage-2 triage models use different providers "
            "(%s / %s); PageIndexToolkit will use the Stage-2 (heavy) "
            "model for its own internal page-generation steps too.",
            lightweight_model,
            model,
        )
    orch = WikiIngestOrchestrator(
        pi_toolkit,
        None,
        sources,
        bookkeeper,
        store=store,
        sync_graph=config.sync_graph,
    )

    async def _triage_all(
        refs: list[Any], router: Any, acquirer: DocumentAcquirer
    ) -> tuple[list[Any], dict[str, Any], list[str]]:
        """Acquire + triage every resolved source.

        A document that cannot be decoded/extracted is skipped (logged,
        counted) rather than triaged as mojibake — never charged an LLM
        call (spec §1). The acquired document is kept alongside its
        triage entry (keyed by the SAME ``str(Path(...))`` identity
        ``router.triage`` uses for ``source_uri``) so ``--interactive``/
        ``--auto`` can pass it into ``orch.ingest(acquired=...)`` and
        avoid a second extraction pass.
        """
        entries = []
        acquired_by_uri: dict[str, Any] = {}
        skipped: list[str] = []
        for ref in refs:
            try:
                acquired = await acquirer.acquire(ref)
            except DocumentAcquisitionError as exc:
                _cli_logger.warning("Skipping %s: %s", ref.uri, exc)
                skipped.append(ref.uri)
                continue
            doc_path = Path(ref.uri)
            entry = await router.triage(doc_path, acquired.text)
            if not extract_flag:
                entry.claims = []
            entries.append(entry)
            acquired_by_uri[str(doc_path)] = acquired
            await asyncio.to_thread(_log_triage, entry)
        return entries, acquired_by_uri, skipped

    async def _apply_all(
        entries: list[Any],
        wiki_config: WikiConfig,
        charter_version: str | None,
        acquired_by_uri: dict[str, Any] | None = None,
    ) -> None:
        for entry in entries:
            if entry.decision is None:
                continue
            await orch.ingest(
                entry.source_uri,
                wiki_config,
                triage=entry,
                charter_version=charter_version,
                acquired=(acquired_by_uri or {}).get(entry.source_uri),
            )

    # ---- --review: apply pre-computed decisions, no re-triage ----------
    if mode == "review":
        header, entries = ManifestReader(review_opt).read()
        applied = [e for e in entries if e.decision is not None]

        charter_for_examples = None
        try:
            charter_for_examples = load_charter(_resolve_charter_path(root, charter_opt))
        except click.ClickException:
            charter_for_examples = None
        if charter_for_examples is not None and charter_for_examples.examples_file:
            for entry in applied:
                if entry.decision_source == "human":
                    append_example(
                        charter_for_examples,
                        TriageExample(
                            summary=entry.briefing,
                            why=f"human decision: {entry.decision}",
                            destination=entry.decision,
                        ),
                    )

        wiki_config = WikiConfig(
            wiki_name=config.wiki_name,
            storage_dir=wiki_dir,
            sync_graph=config.sync_graph,
            storage_backend=config.backend,
        )
        _run(_apply_all(applied, wiki_config, header.charter_version))
        click.echo(f"Applied {len(applied)} decision(s) from {review_opt}.")
        return

    # ---- --dry-run / --interactive / --auto: triage first --------------
    charter_path = _resolve_charter_path(root, charter_opt)
    charter = load_charter(charter_path)
    novelty_scorer = _build_novelty_scorer(root, config, store)
    router = IngestTriageRouter(charter, light_adapter, sources, novelty_scorer, heavy_adapter=heavy_adapter)
    wiki_config = WikiConfig(
        wiki_name=config.wiki_name,
        storage_dir=wiki_dir,
        charter_path=charter_path,
        sync_graph=config.sync_graph,
        storage_backend=config.backend,
    )
    refs = resolve_sources(source, recursive=recursive)
    acquirer = DocumentAcquirer(fetch_timeout=fetch_timeout)
    entries, acquired_by_uri, skipped = _run(_triage_all(refs, router, acquirer))

    if mode == "dry-run":
        header = ManifestRunHeader(
            charter_sha256=charter.fingerprint,
            charter_version=charter.version,
            mode="dry-run",
            novelty_backend=novelty_scorer.backend,
            counts=dict(Counter(e.proposed_action for e in entries)),
            created_at=datetime.now(UTC).isoformat(),
        )
        ManifestWriter(manifest_path).write(header, entries)
        click.echo(f"Triaged {len(entries)} document(s), skipped {len(skipped)}." f" Manifest: {manifest_path}")
        _print_triage_summary(entries, skipped)
        _report_skipped(skipped)
        return

    if mode == "interactive":
        # ALL prompting happens here — synchronous, blocking, BEFORE the
        # async apply pipeline below starts (questionary is blocking;
        # spec §7 risk: never call it inside async code).
        import questionary

        for entry in entries:
            click.echo(f"\n{entry.source_uri}")
            click.echo(f"  briefing: {entry.briefing}")
            click.echo(
                f"  scores: density={entry.scores.density:.2f} "
                f"novelty={entry.scores.novelty:.2f} "
                f"durability={entry.scores.durability:.2f}"
            )
            click.echo(f"  composite: {entry.composite:.4f}  proposed: {entry.proposed_action}")
            choice = questionary.select(
                "Decision:",
                choices=["admit", "archive", "discard"],
                default=entry.proposed_action,
            ).ask()
            entry.decision = choice or entry.proposed_action
            entry.decision_source = "human"
            if entry.decision != entry.proposed_action and charter.examples_file:
                append_example(
                    charter,
                    TriageExample(
                        summary=entry.briefing,
                        why=f"human override: {entry.decision}",
                        destination=entry.decision,
                    ),
                )

        header = ManifestRunHeader(
            charter_sha256=charter.fingerprint,
            charter_version=charter.version,
            mode="interactive",
            novelty_backend=novelty_scorer.backend,
            counts=dict(Counter(e.decision for e in entries)),
            created_at=datetime.now(UTC).isoformat(),
        )
        ManifestWriter(manifest_path).write(header, entries)
        _run(_apply_all(entries, wiki_config, charter.version, acquired_by_uri))
        click.echo(
            f"Applied {len(entries)} interactive decision(s)," f" skipped {len(skipped)}. Manifest: {manifest_path}"
        )
        _report_skipped(skipped)
        return

    # ---- --auto ----------------------------------------------------------
    for entry in entries:
        entry.decision = entry.proposed_action
        entry.decision_source = "auto"
    sample_size = max(1, round(len(entries) * audit_rate)) if entries else 0
    if sample_size:
        stratified_sample(
            entries,
            charter.thresholds,
            sample_size,
            near_fraction=charter.calibration.near_fraction,
            uniform_fraction=charter.calibration.uniform_fraction,
        )
    header = ManifestRunHeader(
        charter_sha256=charter.fingerprint,
        charter_version=charter.version,
        mode="auto",
        novelty_backend=novelty_scorer.backend,
        counts=dict(Counter(e.decision for e in entries)),
        created_at=datetime.now(UTC).isoformat(),
    )
    ManifestWriter(manifest_path).write(header, entries)
    _run(_apply_all(entries, wiki_config, charter.version, acquired_by_uri))
    audited = [e for e in entries if e.audit_sample]
    click.echo(
        f"Applied {len(entries)} auto decision(s), skipped {len(skipped)}."
        f" Audit sample: {len(audited)} flagged for human review"
        f" ({audit_rate:.0%} of batch). Manifest: {manifest_path}"
    )
    click.echo(
        "agreement_rate(): computable once the audit sample's `decision` "
        f"fields are filled in via a follow-up `--review` pass over {manifest_path}."
    )
    _report_skipped(skipped)


@wiki.command(name="ingest-jira")
@click.option(
    "--jql",
    default=None,
    help="JQL scope (default: JIRA_WIKI_JQL, or `project = <JIRA_DEFAULT_PROJECT>`).",
)
@click.option(
    "--project",
    "project_key",
    default=None,
    help="Shorthand for `project = <KEY>`.",
)
@click.option(
    "--since",
    default=None,
    help="Override the stored watermark (ISO-8601).",
)
@click.option(
    "--issues-dir",
    "issues_dir_opt",
    default=None,
    type=click.Path(file_okay=False),
    help="Output directory (default: JIRA_WIKI_ISSUES_DIR or ${PARROT_HOME}/wikis/issues).",
)
@click.option(
    "--build/--no-build",
    "do_build",
    default=True,
    show_default=True,
    help="Build the plane after emitting (FEAT-454, G10).",
)
@click.option(
    "--enrich",
    is_flag=True,
    help="Opt-in LLM summary for thin descriptions — not implemented in v1.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Re-render every issue in scope, ignoring the stored watermark.",
)
@click.option(
    "--backfill",
    is_flag=True,
    help=(
        "One-shot full load of the scope. A preset: implies --force, raises "
        "the default concurrency, prints progress, and FAILS the run (leaving "
        "the watermark untouched) if the fetch came up short of Jira's own "
        "count for the scope."
    ),
)
@click.option(
    "--concurrency",
    "concurrency_opt",
    default=None,
    type=click.IntRange(1, 64),  # == jira_sync.MAX_SWEEP_CONCURRENCY
    help=(
        "Issues fetched concurrently (default: JIRA_WIKI_CONCURRENCY, else 8; "
        "16 under --backfill). 1 sweeps strictly sequentially."
    ),
)
@click.option(
    "--progress-every",
    "progress_every_opt",
    default=None,
    type=click.IntRange(0, 100000),
    help="Print a progress line every N issues (0 disables; default 100 under --backfill).",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Report what would change; write nothing at all.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the SweepReport as JSON.",
)
@click.option("--quiet", "-q", is_flag=True, help="Only print the final summary line.")
def ingest_jira(
    jql: str | None,
    project_key: str | None,
    since: str | None,
    issues_dir_opt: str | None,
    do_build: bool,
    enrich: bool,
    force: bool,
    backfill: bool,
    concurrency_opt: int | None,
    progress_every_opt: int | None,
    dry_run: bool,
    as_json: bool,
    quiet: bool,
) -> None:
    """Extract Jira tickets into the `issues` markdown corpus and build it.

    Deterministic and zero-LLM by default (FEAT-454): every frontmatter
    field is a Jira field or a pure function of one, so two runs over
    unchanged tickets produce byte-identical documents and write nothing.

    Scope is JQL; each run fetches only issues updated since the last
    successful watermark, so a daily cron stays cheap. Content below the
    `<!-- jira-sync:end -->` marker in any document is preserved forever.
    Builds the plane by default so it can never silently lag the files
    (G10) — pass ``--no-build`` to emit documents only.

    Each issue costs two round trips (its share of a search page plus its
    own remote-links call), so the sweep resolves ``--concurrency`` issues
    at a time. For the initial load of a scope use ``--backfill``, which
    presets that for a one-shot run and refuses to record a watermark over
    a corpus that came up short.

    Register the corpus once as a namespace (see the runbook):

        wikitoolkit ns add issues --store <issues-dir>/.parrot/wiki --global
    """
    if enrich:
        raise click.ClickException("--enrich is not implemented in v1 (zero-LLM default path only).")
    if jql and project_key:
        raise click.UsageError("--jql and --project are mutually exclusive.")

    # Lazy imports: `wikitoolkit --help` must never pay for `jira`
    # (mirrors `build`'s vault_scan import at cli.py:1118-1121).
    from parrot.interfaces.jira import JiraAuthError, JiraDependencyError, JiraInterface
    from parrot.knowledge.wiki.jira_sync import (
        BACKFILL_SWEEP_CONCURRENCY,
        DEFAULT_SWEEP_CONCURRENCY,
        MAX_SWEEP_CONCURRENCY,
        resolve_issues_dir,
        sweep_jira_issues,
    )

    if jql:
        effective_jql = jql
    elif project_key:
        effective_jql = f"project = {project_key}"
    else:
        env_jql = _env_setting("JIRA_WIKI_JQL")
        if env_jql:
            effective_jql = env_jql
        else:
            default_project = _env_setting("JIRA_DEFAULT_PROJECT")
            if default_project:
                effective_jql = f"project = {default_project}"
            else:
                raise click.ClickException(
                    "No JQL scope resolved. Provide --jql, or --project, or "
                    "set JIRA_WIKI_JQL (or JIRA_DEFAULT_PROJECT) in the environment."
                )

    since_dt: datetime | None = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as exc:
            raise click.ClickException(f"--since must be ISO-8601 (got {since!r}): {exc}") from exc

    issues_dir = resolve_issues_dir(issues_dir_opt or _env_setting("JIRA_WIKI_ISSUES_DIR"))

    # --backfill is a preset, not a separate code path: an explicit
    # --concurrency / --progress-every still wins over what it presets.
    env_concurrency = _env_setting("JIRA_WIKI_CONCURRENCY")
    if concurrency_opt is not None:
        concurrency = concurrency_opt
    elif env_concurrency:
        try:
            concurrency = int(env_concurrency)
        except ValueError as exc:
            raise click.ClickException(
                f"JIRA_WIKI_CONCURRENCY must be an integer (got {env_concurrency!r}): {exc}"
            ) from exc
        # The env var must clear the same bar as --concurrency: the sweep's
        # resident-task bound is `concurrency * 2`.
        if not 1 <= concurrency <= MAX_SWEEP_CONCURRENCY:
            raise click.ClickException(
                f"JIRA_WIKI_CONCURRENCY must be between 1 and {MAX_SWEEP_CONCURRENCY} (got {concurrency})."
            )
    elif backfill:
        concurrency = BACKFILL_SWEEP_CONCURRENCY
    else:
        concurrency = DEFAULT_SWEEP_CONCURRENCY

    if progress_every_opt is not None:
        progress_every = progress_every_opt
    elif backfill and not quiet and not as_json:
        progress_every = 100
    else:
        progress_every = 0

    def _progress(count: int) -> None:
        click.echo(f"  ... {count} issue(s) swept", err=True)

    interface = JiraInterface()

    try:
        report = _run(
            sweep_jira_issues(
                interface,
                issues_dir,
                jql=effective_jql,
                since=since_dt,
                force=force or backfill,
                dry_run=dry_run,
                concurrency=concurrency,
                enforce_scope_count=backfill,
                progress=_progress if progress_every else None,
                progress_every=progress_every,
            )
        )
    except JiraDependencyError as exc:
        raise click.ClickException(str(exc)) from exc
    except JiraAuthError as exc:
        raise click.ClickException(str(exc)) from exc

    namespace_name = _env_setting("JIRA_WIKI_NAMESPACE") or "issues"

    if do_build and not dry_run:
        # vault_mode=True EXPLICITLY: the issues dir has no .obsidian/, and
        # build's own auto-detect (cli.py:1124-1125) would pick repository
        # mode and scan the markdown as source code. no_git=True: the
        # corpus is not a git repo. no_export/no_graph default ON to keep
        # a cron cheap — an operator can run `build` by hand for the extras.
        build.callback(
            path_=str(issues_dir),
            name=namespace_name,
            backend=None,
            force=force or backfill,
            no_git=True,
            quiet=quiet,
            no_export=True,
            no_graph=True,
            graph_kinds="module,document,overview",
            vault_mode=True,
        )

    if as_json:
        click.echo(report.model_dump_json(indent=2))
    elif quiet:
        click.echo(
            f"Jira sweep: {report.fetched} fetched, {report.written} written, "
            f"{report.unchanged} unchanged, {report.orphaned} orphaned, "
            f"{len(report.errors)} error(s)."
        )
    else:
        click.echo(f"Jira sweep against {issues_dir}:")
        click.echo(f"  fetched:      {report.fetched}")
        click.echo(f"  written:      {report.written}")
        click.echo(f"  unchanged:    {report.unchanged}")
        click.echo(f"  orphaned:     {report.orphaned}")
        click.echo(f"  entity notes: {report.entity_notes}")
        if report.approx_scope_count is not None:
            click.echo(f"  scope size (Jira's approximate count): ~{report.approx_scope_count}")
        click.echo(f"  watermark advanced: {report.watermark_advanced}")
        for warning in report.warnings:
            click.echo(f"  WARNING: {warning}")
        if report.unresolved_link_keys:
            click.echo(
                f"  WARNING: {len(report.unresolved_link_keys)} relation(s) point "
                "outside the current JQL scope and were dropped as unresolved "
                "wikilinks — widen the JQL to include them: "
                f"{', '.join(report.unresolved_link_keys[:10])}"
                + ("..." if len(report.unresolved_link_keys) > 10 else "")
            )
        if report.errors:
            click.echo(f"  ERRORS: {len(report.errors)}")
            for err in report.errors:
                click.echo(f"    - {err}")

    if report.errors:
        raise SystemExit(1)


@wiki.command(name="claude-hook", hidden=True)
def claude_hook() -> None:
    """Claude Code PreToolUse hook runtime (reads stdin JSON).

    Configured by `parrot claude install` in .claude/settings.json;
    emits a non-blocking nudge toward `wikitoolkit query` before
    search-style tool calls. Always exits 0.
    """
    import sys

    from parrot.knowledge.wiki.claude_code.hook import run_pre_tool_use_hook

    sys.exit(run_pre_tool_use_hook())


def main() -> None:
    """Console-script entry point for ``wikitoolkit``."""
    wiki()


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------
# Coding-agent integration commands (codex / claude / gemini)
# --------------------------------------------------------------------------


def _register_agent_command(name: str) -> None:
    """Create a ``wiki <agent> install|hook`` subcommand dynamically."""
    from parrot.knowledge.wiki import coding_agents

    @wiki.command(name)
    @click.option(
        "--path",
        type=click.Path(file_okay=False, path_type=Path),
        default=Path.cwd,
    )
    @click.argument("action", type=click.Choice(["install", "hook"]))
    def command(path: Path, action: str) -> None:
        """Install wiki integration or run its lifecycle hook."""
        if action == "hook":
            raise click.exceptions.Exit(coding_agents.hook(name))
        for item in coding_agents.install(name, path):
            click.echo(f"  ✓ {item}")


for _agent_name in ("codex", "claude", "gemini"):
    _register_agent_command(_agent_name)
