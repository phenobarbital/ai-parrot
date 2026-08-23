"""Multi-wiki federation for the LLM Wiki (FEAT-450).

A repository's wiki is one *plane*. Real work spans several: the sibling
libraries a project depends on, an Obsidian vault of notes, a corpus of
legislation held in ArangoDB. This module composes them.

Namespaces are **declared** in ``project.py`` (``.parrot/wiki.json`` and
the per-user ``PARROT_HOME/wikis.json``); here they are **resolved** into
opened stores (:func:`resolve_namespaces`) and composed behind one
:class:`BaseWikiStore` (:class:`FederatedWikiStore`) that the CLI, the
``AbstractTool`` wrappers and the MCP server can hold in place of a
plain store.

Three rules shape the design:

* **Foreign planes are read-only.** A read of another project's wiki
  never migrates, mutates, or even creates a sidecar next to it — SQLite
  namespaces are opened with ``read_only=True``.
* **Local ids stay unprefixed.** Only foreign pages are qualified
  ``<ns>::<id>``; the underlying stores never see the prefix.
* **A broken namespace is a note, not a failure.** An unbuilt plane or
  an unreachable server is recorded as a :class:`NamespaceSkip` and the
  remaining namespaces still answer.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from parrot.knowledge.wiki.context import qualify_id, split_namespaced_id
from parrot.knowledge.wiki.project import (
    WikiNamespaceConfig,
    WikiProjectConfig,
    load_global_registry,
    load_project_config,
    merge_namespaces,
    resolve_arango_params,
    resolve_entry_base,
)
from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    SQLiteWikiStore,
    WikiPageRecord,
    create_wiki_store,
)

logger = logging.getLogger(__name__)

#: Default seconds allowed for an ArangoDB namespace to connect before it
#: is skipped as unreachable.
DEFAULT_ARANGO_TIMEOUT = 5.0

#: Routing selectors that are not namespace names.
SELECTOR_ALL = "all"
SELECTOR_LOCAL = "local"


class NamespaceSkip(BaseModel):
    """A namespace that could not be served, and why.

    Attributes:
        name: Namespace name.
        reason: ``unbuilt`` (no plane yet), ``unreachable`` (open or
            query failed), or ``invalid`` (the entry itself is broken).
        detail: Human-readable cause.
        hint: Optional command that would fix it.
    """

    name: str
    reason: Literal["unbuilt", "unreachable", "invalid"]
    detail: str = ""
    hint: str = ""


@dataclass
class NamespaceHandle:
    """An opened namespace, ready to be read.

    Attributes:
        name: Namespace name (the ``<ns>`` of ``<ns>::<id>``).
        store: The opened backing store.
        config: Declaration this handle was resolved from.
        origin: Which registry declared it (``repo`` or ``global``).
        storage_dir: On-disk plane directory, when the backend has one.
        read_only: Whether the store was opened read-only.
    """

    name: str
    store: BaseWikiStore
    config: WikiNamespaceConfig
    origin: Literal["repo", "global"] = "repo"
    storage_dir: Path | None = None
    read_only: bool = True

    @property
    def kind(self) -> str:
        """Entry kind of the declaration (``path``/``store``/…)."""
        return self.config.kind

    @property
    def backend(self) -> str:
        """Backend serving this namespace."""
        return self.config.backend

    @property
    def weight(self) -> float:
        """Score multiplier applied when merging this namespace."""
        return self.config.weight


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _resolve_dir(value: str, base_dir: Path) -> Path:
    """Expand ``value`` and resolve it against ``base_dir`` when relative."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate


def _arango_config_for(cfg: WikiNamespaceConfig) -> WikiProjectConfig:
    """Build the throwaway project config an ArangoDB entry resolves through."""
    return WikiProjectConfig(
        wiki_name=cfg.database or "codebase",
        backend="arangodb",
        arango_database=cfg.database,
        arango_credentials_env=cfg.credentials_env,
    )


async def _open_project_plane(
    name: str,
    cfg: WikiNamespaceConfig,
    project_root: Path,
    *,
    read_only: bool,
    arango_timeout: float,
) -> tuple[BaseWikiStore, Path | None]:
    """Open the plane of another wiki project (``path`` / ``vault`` kinds).

    The project's own ``.parrot/wiki.json`` decides where its plane lives
    and which backend serves it — a vault is resolved exactly like a
    project root (spec Delta 2), defaulting to ``<vault>/.parrot/wiki``.

    Args:
        name: Namespace name (used for the wiki name / error text).
        cfg: Namespace declaration.
        project_root: Resolved project (or vault) root.
        read_only: Open the plane read-only.
        arango_timeout: Seconds allowed for an ArangoDB connect.

    Returns:
        ``(store, storage_dir)``; ``storage_dir`` is ``None`` for
        server-hosted backends.

    Raises:
        FileNotFoundError: When the root or its sqlite plane is missing.
    """
    if not project_root.is_dir():
        raise FileNotFoundError(f"namespace {name!r} root does not exist: {project_root}")
    foreign = load_project_config(project_root)
    if foreign.backend == "arangodb":
        store = await _open_arango(
            arango_params=resolve_arango_params(foreign),
            database=foreign.arango_database or "",
            wiki_name=foreign.wiki_name,
            text_analyzer=foreign.arango_text_analyzer,
            timeout=arango_timeout,
        )
        return store, None
    storage_dir = foreign.storage_path(project_root)
    return (
        _open_local_plane(
            storage_dir,
            wiki_name=foreign.wiki_name,
            backend=foreign.backend,
            read_only=read_only,
        ),
        storage_dir,
    )


def _open_local_plane(
    storage_dir: Path,
    *,
    wiki_name: str,
    backend: str,
    read_only: bool,
) -> BaseWikiStore:
    """Open an on-disk plane, honouring read-only mode.

    ``create_wiki_store`` (and ``SQLiteWikiStore``'s writable path)
    create directories; a read-only open must not, so the sqlite store is
    constructed directly.

    Args:
        storage_dir: Plane directory.
        wiki_name: Wiki name recorded in / read from the plane.
        backend: ``sqlite`` or ``memory``.
        read_only: Open read-only.

    Returns:
        The opened store.

    Raises:
        FileNotFoundError: When ``read_only`` and the plane is unbuilt.
    """
    if backend == "sqlite" and read_only:
        return SQLiteWikiStore(
            storage_dir / "wiki.db", wiki_name=wiki_name, read_only=True
        )
    if backend == "memory" and read_only and not (storage_dir / "pages").exists():
        raise FileNotFoundError(
            f"read-only wiki store has no plane at {storage_dir / 'pages'}"
        )
    return create_wiki_store(storage_dir, wiki_name=wiki_name, backend=backend)


async def _open_arango(
    *,
    arango_params: dict[str, Any],
    database: str,
    wiki_name: str,
    text_analyzer: str,
    timeout: float,
) -> BaseWikiStore:
    """Open and eagerly connect an ArangoDB plane under a timeout.

    Args:
        arango_params: Connection params from :func:`resolve_arango_params`.
        database: Database name holding the plane.
        wiki_name: Wiki name (used when ``database`` is empty).
        text_analyzer: ArangoSearch analyzer for FTS.
        timeout: Seconds allowed for ``initialize()``.

    Returns:
        The connected store.

    Raises:
        TimeoutError: When the server does not answer in time.
    """
    from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore

    store = ArangoDBWikiStore(
        arango_params=arango_params,
        database=database,
        wiki_name=wiki_name,
        text_analyzer=text_analyzer,
    )
    await asyncio.wait_for(store.initialize(), timeout=timeout)
    return store


async def open_namespace_store(
    name: str,
    cfg: WikiNamespaceConfig,
    *,
    base_dir: Path,
    read_only: bool = True,
    arango_timeout: float = DEFAULT_ARANGO_TIMEOUT,
) -> tuple[BaseWikiStore, Path | None]:
    """Open the single store behind one namespace declaration.

    This is both the read path (``read_only=True``, used by
    :func:`resolve_namespaces`) and the ``--ns <name>`` write path
    (``read_only=False``, spec U2) — the latter bypasses the federation
    entirely and hands the caller that one plane, writable.

    Args:
        name: Namespace name.
        cfg: Namespace declaration.
        base_dir: Directory relative paths resolve against (see
            :func:`parrot.knowledge.wiki.project.resolve_entry_base`).
        read_only: Open the plane read-only.
        arango_timeout: Seconds allowed for an ArangoDB connect.

    Returns:
        ``(store, storage_dir)``; ``storage_dir`` is ``None`` for
        server-hosted backends.

    Raises:
        FileNotFoundError: The plane (or its root) does not exist.
        TimeoutError: An ArangoDB namespace did not answer in time.
    """
    kind = cfg.kind
    if kind in ("path", "vault"):
        return await _open_project_plane(
            name,
            cfg,
            _resolve_dir(cfg.target, base_dir),
            read_only=read_only,
            arango_timeout=arango_timeout,
        )
    if kind == "store":
        if cfg.backend == "arangodb":
            raise ValueError(
                f"namespace {name!r}: backend 'arangodb' needs a `database` "
                "entry, not a `store` directory"
            )
        storage_dir = _resolve_dir(cfg.store or "", base_dir)
        return (
            _open_local_plane(
                storage_dir,
                wiki_name=name,
                backend=cfg.backend,
                read_only=read_only,
            ),
            storage_dir,
        )
    # kind == "database"
    store = await _open_arango(
        arango_params=resolve_arango_params(_arango_config_for(cfg)),
        database=cfg.database or "",
        wiki_name=name,
        text_analyzer="text_en",
        timeout=arango_timeout,
    )
    return store, None


def _skip_for(name: str, cfg: WikiNamespaceConfig, exc: BaseException) -> NamespaceSkip:
    """Classify a failed namespace open into a :class:`NamespaceSkip`."""
    if isinstance(exc, FileNotFoundError):
        hint = ""
        if cfg.kind in ("path", "vault"):
            hint = f"wikitoolkit build --path {cfg.target}"
        elif cfg.kind == "store":
            hint = f"wikitoolkit build --store {cfg.target}"
        return NamespaceSkip(
            name=name, reason="unbuilt", detail=str(exc), hint=hint
        )
    if isinstance(exc, (ValueError, TypeError)):
        return NamespaceSkip(name=name, reason="invalid", detail=str(exc))
    return NamespaceSkip(name=name, reason="unreachable", detail=str(exc))


async def resolve_namespaces(
    root: Path,
    config: WikiProjectConfig,
    *,
    only: set[str] | None = None,
    registry_path: Path | None = None,
    read_only: bool = True,
    arango_timeout: float = DEFAULT_ARANGO_TIMEOUT,
) -> tuple[list[NamespaceHandle], list[NamespaceSkip]]:
    """Merge both registries and open every declared namespace.

    Repo declarations win over global ones on a name clash. A namespace
    that cannot be opened never propagates its error: it comes back as a
    :class:`NamespaceSkip` so a broadcast still answers from the rest
    (spec G9).

    Args:
        root: Repository root (base for relative repo-entry paths).
        config: The repo's project config.
        only: When given, resolve just these namespace names.
        registry_path: Override for the global registry file.
        read_only: Open the namespaces read-only.
        arango_timeout: Seconds allowed for an ArangoDB connect.

    Returns:
        ``(handles, skipped)`` — the opened namespaces and the notes for
        the ones that were not.
    """
    merged = merge_namespaces(
        config.namespaces, load_global_registry(registry_path).namespaces
    )
    if only is not None:
        merged = {name: entry for name, entry in merged.items() if name in only}

    handles: list[NamespaceHandle] = []
    skipped: list[NamespaceSkip] = []
    for name in sorted(merged):
        cfg, origin = merged[name]
        base_dir = resolve_entry_base(origin, root)
        try:
            store, storage_dir = await open_namespace_store(
                name,
                cfg,
                base_dir=base_dir,
                read_only=read_only,
                arango_timeout=arango_timeout,
            )
        except TimeoutError as exc:
            logger.warning("Namespace %s timed out while opening: %s", name, exc)
            skipped.append(
                NamespaceSkip(
                    name=name,
                    reason="unreachable",
                    detail=f"timed out after {arango_timeout}s",
                )
            )
        except Exception as exc:  # noqa: BLE001 — a bad namespace is a note
            logger.warning("Namespace %s could not be opened: %s", name, exc)
            skipped.append(_skip_for(name, cfg, exc))
        else:
            handles.append(
                NamespaceHandle(
                    name=name,
                    store=store,
                    config=cfg,
                    origin=origin,  # type: ignore[arg-type]
                    storage_dir=storage_dir,
                    read_only=read_only,
                )
            )
    return handles, skipped


# ---------------------------------------------------------------------------
# Score merging
# ---------------------------------------------------------------------------


def normalize_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Min-max the ``score`` of one namespace's rows into ``[0, 1]``.

    ``search_fts`` returns raw ``-bm25``, which is corpus-relative: a
    five-page plane and a five-hundred-page plane produce scores on
    different scales, and merging them raw lets the smaller corpus
    dominate. Normalising per namespace before the merge is what makes
    the comparison meaningful (same semantics as
    ``WikiCombinedSearch._apply_weight``: an all-equal group maps to
    1.0).

    Args:
        rows: Result rows of one namespace, mutated in place.

    Returns:
        The same rows.
    """
    scores = [float(row.get("score") or 0.0) for row in rows]
    if not scores:
        return rows
    low, high = min(scores), max(scores)
    span = high - low
    for row, score in zip(rows, scores):
        row["score"] = 1.0 if span == 0 else (score - low) / span
    return rows


def _weighted(rows: list[dict[str, Any]], weight: float) -> list[dict[str, Any]]:
    """Apply a namespace weight to already-normalised scores."""
    for row in rows:
        row["score"] = min(max(float(row.get("score") or 0.0) * weight, 0.0), 1.0)
    return rows


def _qualify_row(row: dict[str, Any], namespace: str | None) -> dict[str, Any]:
    """Return a copy of ``row`` with its ids qualified and ns recorded."""
    out = dict(row)
    if namespace:
        for key in ("concept_id", "node_id", "page_id"):
            value = out.get(key)
            if value:
                out[key] = qualify_id(namespace, str(value))
    out["namespace"] = namespace
    return out


def _row_id(row: dict[str, Any]) -> str:
    """Identity used to dedup merged rows."""
    return str(
        row.get("concept_id") or row.get("node_id") or row.get("page_id") or ""
    )


# ---------------------------------------------------------------------------
# The federated store
# ---------------------------------------------------------------------------


@dataclass
class _CallSkips:
    """Per-call degradation notes, reset by each fan-out."""

    items: list[NamespaceSkip] = field(default_factory=list)


class FederatedWikiStore(BaseWikiStore):
    """One :class:`BaseWikiStore` over the local plane plus N namespaces.

    Reads fan out concurrently, are normalised per namespace, weighted,
    qualified (foreign only) and merged. Writes go to the local plane —
    writing into a namespace is an explicit, single-target operation
    (``--ns <name>``) that opens that store directly and never travels
    through the federation.

    Attributes:
        local_name: Display name of the local plane.
        namespaces: Opened namespaces by name.
        skipped: Namespaces that could not be opened at resolve time.
        last_skipped: Namespaces that failed during the most recent read.
    """

    def __init__(
        self,
        local: BaseWikiStore,
        local_name: str = "local",
        handles: list[NamespaceHandle] | None = None,
        skipped: list[NamespaceSkip] | None = None,
        *,
        qualify_local: bool = False,
    ) -> None:
        """Compose a federated store.

        Args:
            local: The local (writable) plane.
            local_name: Name shown for the local plane.
            handles: Opened foreign namespaces.
            skipped: Resolve-time skips to surface in ``stats``.
            qualify_local: Qualify the local plane's ids with
                ``local_name`` too. Used by :meth:`scoped` when a single
                foreign namespace is selected, so its rows keep the
                ``ns::`` prefix the caller expects.
        """
        self._local = local
        self.local_name = local_name
        self.namespaces: dict[str, NamespaceHandle] = {
            handle.name: handle for handle in (handles or [])
        }
        self.skipped: list[NamespaceSkip] = list(skipped or [])
        self._qualify_local = qualify_local
        self.last_skipped: list[NamespaceSkip] = []
        self.logger = logging.getLogger(__name__)

    # -- introspection --------------------------------------------------

    @property
    def local(self) -> BaseWikiStore:
        """The local (writable) plane."""
        return self._local

    @property
    def _local_prefix(self) -> str | None:
        """Namespace applied to local rows (``None`` unless qualifying)."""
        return self.local_name if self._qualify_local else None

    def scoped(self, selector: str | None) -> BaseWikiStore:
        """Narrow the federation to one routing selector.

        Args:
            selector: ``None`` or ``"all"`` for the whole federation,
                ``"local"`` for the local plane only, or a namespace
                name. A comma-separated list selects that subset.

        Returns:
            A store honouring the selector — ``self`` for a broadcast.

        Raises:
            KeyError: When a named namespace is not resolved.
        """
        if selector is None or selector == SELECTOR_ALL:
            return self
        names = [part.strip() for part in selector.split(",") if part.strip()]
        if names == [SELECTOR_LOCAL]:
            return self._local
        if len(names) == 1:
            name = names[0]
            handle = self.namespaces.get(name)
            if handle is None:
                raise KeyError(name)
            return FederatedWikiStore(
                local=handle.store,
                local_name=name,
                handles=[],
                skipped=[],
                qualify_local=True,
            )
        # A subset: keep the local plane only when explicitly named.
        include_local = SELECTOR_LOCAL in names
        handles: list[NamespaceHandle] = []
        for name in names:
            if name == SELECTOR_LOCAL:
                continue
            handle = self.namespaces.get(name)
            if handle is None:
                raise KeyError(name)
            handles.append(handle)
        if include_local:
            return FederatedWikiStore(
                local=self._local,
                local_name=self.local_name,
                handles=handles,
                skipped=[],
            )
        return FederatedWikiStore(
            local=_EmptyStore(),
            local_name=self.local_name,
            handles=handles,
            skipped=[],
        )

    # -- fan-out helpers -------------------------------------------------

    async def _fan_out(
        self,
        call: str,
        *args: Any,
        **kwargs: Any,
    ) -> list[tuple[str | None, float, list[dict[str, Any]]]]:
        """Run one read across the local plane and every namespace.

        Args:
            call: Method name to invoke on each store.
            *args: Positional arguments for that method.
            **kwargs: Keyword arguments for that method.

        Returns:
            ``(namespace, weight, rows)`` triples; a namespace that
            raised is omitted and recorded in :attr:`last_skipped`.
        """
        self.last_skipped = []
        handles = list(self.namespaces.values())
        tasks = [getattr(self._local, call)(*args, **kwargs)]
        tasks += [getattr(handle.store, call)(*args, **kwargs) for handle in handles]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        groups: list[tuple[str | None, float, list[dict[str, Any]]]] = []
        local_rows = outcomes[0]
        if isinstance(local_rows, BaseException):
            self.logger.warning("Local plane failed on %s: %s", call, local_rows)
            self.last_skipped.append(
                NamespaceSkip(
                    name=self.local_name,
                    reason="unreachable",
                    detail=str(local_rows),
                )
            )
        else:
            groups.append((self._local_prefix, 1.0, list(local_rows)))

        for handle, outcome in zip(handles, outcomes[1:]):
            if isinstance(outcome, BaseException):
                self.logger.warning(
                    "Namespace %s failed on %s: %s", handle.name, call, outcome
                )
                self.last_skipped.append(
                    NamespaceSkip(
                        name=handle.name,
                        reason="unreachable",
                        detail=str(outcome),
                    )
                )
                continue
            groups.append((handle.name, handle.weight, list(outcome)))
        return groups

    def _merge(
        self,
        groups: list[tuple[str | None, float, list[dict[str, Any]]]],
        limit: int,
        *,
        rank: bool = True,
    ) -> list[dict[str, Any]]:
        """Normalise, weight, qualify, dedup and rank fan-out results.

        Args:
            groups: ``(namespace, weight, rows)`` triples.
            limit: Maximum rows returned.
            rank: Whether the rows carry comparable scores to sort on.

        Returns:
            The merged rows, highest score first.
        """
        merged: dict[str, dict[str, Any]] = {}
        for namespace, weight, rows in groups:
            prepared = [_qualify_row(row, namespace) for row in rows]
            if rank:
                _weighted(normalize_scores(prepared), weight)
            for row in prepared:
                key = _row_id(row)
                current = merged.get(key)
                if current is None or rank and float(row.get("score") or 0.0) > float(
                    current.get("score") or 0.0
                ):
                    merged[key] = row
        out = list(merged.values())
        if rank:
            out.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
        return out[:limit]

    def _route(self, page_id: str) -> tuple[NamespaceHandle | None, str, bool]:
        """Resolve a possibly qualified id to its store.

        Args:
            page_id: Page id, qualified or not.

        Returns:
            ``(handle, local_id, known)``. ``handle`` is ``None`` for the
            local plane; ``known`` is ``False`` when the id names a
            namespace this store does not serve.
        """
        namespace, local_id = split_namespaced_id(page_id)
        if namespace is None:
            return None, page_id, True
        if self._qualify_local and namespace == self.local_name:
            return None, local_id, True
        handle = self.namespaces.get(namespace)
        if handle is None:
            return None, local_id, False
        return handle, local_id, True

    # -- reads -----------------------------------------------------------

    async def search_fts(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Lexical search across the local plane and every namespace."""
        groups = await self._fan_out(
            "search_fts", query, category=category, limit=limit
        )
        return self._merge(groups, limit)

    async def search_vector(
        self, embedding: list[float], limit: int = 10
    ) -> list[dict[str, Any]]:
        """Vector search across the local plane and every namespace."""
        groups = await self._fan_out("search_vector", embedding, limit=limit)
        return self._merge(groups, limit)

    async def list_pages(
        self,
        category: str | None = None,
        limit: int = 100,
        origin: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """List page stubs across the local plane and every namespace."""
        groups = await self._fan_out(
            "list_pages", category=category, limit=limit, origin=origin
        )
        return self._merge(groups, limit, rank=False)

    async def get_page(
        self, concept_id: str, include_body: bool = True
    ) -> dict[str, Any] | None:
        """Fetch one page, routing a qualified id to its namespace."""
        handle, local_id, known = self._route(concept_id)
        if not known:
            return None
        store = handle.store if handle else self._local
        namespace = handle.name if handle else self._local_prefix
        try:
            row = await store.get_page(local_id, include_body=include_body)
        except Exception as exc:  # noqa: BLE001 — a broken namespace is a note
            self.logger.warning(
                "Namespace %s failed on get_page: %s", namespace or "local", exc
            )
            return None
        if row is None:
            return None
        return _qualify_row(row, namespace)

    async def neighbors(
        self,
        concept_id: str,
        rel: str | None = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Return edge neighbours, qualified with the seed's namespace."""
        handle, local_id, known = self._route(concept_id)
        if not known:
            return []
        store = handle.store if handle else self._local
        namespace = handle.name if handle else self._local_prefix
        try:
            rows = await store.neighbors(local_id, rel=rel, direction=direction)
        except Exception as exc:  # noqa: BLE001 — a broken namespace is a note
            self.logger.warning(
                "Namespace %s failed on neighbors: %s", namespace or "local", exc
            )
            return []
        return [_qualify_row(row, namespace) for row in rows]

    async def stats(self) -> dict[str, Any]:
        """Local counters plus a per-namespace block and the skip notes.

        The local top-level keys (``pages``, ``edges``, …) are preserved
        untouched so every existing ``status`` / ``WikiStatusTool``
        consumer keeps working.

        Returns:
            The local stats dict extended with ``local``, ``namespaces``
            and ``skipped``.
        """
        out: dict[str, Any] = {}
        try:
            out = dict(await self._local.stats())
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Local plane failed on stats: %s", exc)
            out = {"error": str(exc)}
        out["local"] = self.local_name

        handles = list(self.namespaces.values())
        outcomes = await asyncio.gather(
            *(handle.store.stats() for handle in handles), return_exceptions=True
        )
        blocks: dict[str, Any] = {}
        skipped = [skip.model_dump() for skip in self.skipped]
        for handle, outcome in zip(handles, outcomes):
            common = {
                "kind": handle.kind,
                "backend": handle.backend,
                "origin": handle.origin,
                "read_only": handle.read_only,
                "weight": handle.weight,
                "description": handle.config.description,
                "storage_dir": str(handle.storage_dir) if handle.storage_dir else None,
            }
            if isinstance(outcome, BaseException):
                self.logger.warning(
                    "Namespace %s failed on stats: %s", handle.name, outcome
                )
                blocks[handle.name] = {**common, "status": "unreachable"}
                skipped.append(
                    NamespaceSkip(
                        name=handle.name,
                        reason="unreachable",
                        detail=str(outcome),
                    ).model_dump()
                )
                continue
            blocks[handle.name] = {**dict(outcome), **common, "status": "ok"}
        out["namespaces"] = blocks
        out["skipped"] = skipped
        return out

    # -- writes (local plane only) ---------------------------------------

    def _assert_local(self, page_id: str) -> str:
        """Reject a qualified id on a write path.

        Args:
            page_id: Page id supplied to a write method.

        Returns:
            The id, unchanged, when it addresses the local plane.

        Raises:
            ValueError: When the id names a foreign namespace.
        """
        namespace, local_id = split_namespaced_id(page_id)
        if namespace is None:
            return page_id
        if self._qualify_local and namespace == self.local_name:
            return local_id
        raise ValueError(
            f"write to namespace {namespace!r} requires --ns {namespace}"
        )

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:
        """Write pages into the local plane."""
        for page in pages:
            self._assert_local(page.concept_id)
        return await self._local.upsert_pages(pages)

    async def add_edges(self, edges: list[tuple]) -> int:
        """Write edges into the local plane (no cross-namespace edges)."""
        for edge in edges:
            self._assert_local(str(edge[0]))
            self._assert_local(str(edge[1]))
        return await self._local.add_edges(edges)

    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: list[tuple[str, str, str]] | None = None,
    ) -> dict[str, Any]:
        """Replace one source's slice of the local plane."""
        for page in pages:
            self._assert_local(page.concept_id)
        return await self._local.replace_source_slice(source_id, pages, edges)

    async def delete_page(self, concept_id: str) -> bool:
        """Delete a page from the local plane."""
        return await self._local.delete_page(self._assert_local(concept_id))

    async def upsert_embedding(
        self, concept_id: str, vector: list[float], model: str = ""
    ) -> None:
        """Store an embedding on the local plane."""
        await self._local.upsert_embedding(
            self._assert_local(concept_id), vector, model
        )

    async def rebuild_from_tree(
        self,
        tree: dict[str, Any],
        content_loader: Any = None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Rebuild the local plane from a PageIndex tree."""
        return await self._local.rebuild_from_tree(tree, content_loader, source_id)

    # -- export / lint (local plane only) ---------------------------------

    async def dump_pages(self) -> list[dict[str, Any]]:
        """Dump the local plane's pages (export is a local operation)."""
        return await self._local.dump_pages()

    async def dump_edges(self) -> list[dict[str, Any]]:
        """Dump the local plane's edges."""
        return await self._local.dump_edges()

    async def orphan_sources(self) -> list[str]:
        """Lint the local plane only."""
        return await self._local.orphan_sources()

    async def broken_edges(self) -> list[dict[str, Any]]:
        """Lint the local plane only."""
        return await self._local.broken_edges()

    async def missing_bodies(self) -> list[str]:
        """Lint the local plane only."""
        return await self._local.missing_bodies()


class _EmptyStore(BaseWikiStore):
    """A plane with nothing in it.

    Stands in for the local plane when :meth:`FederatedWikiStore.scoped`
    selects a subset of namespaces without ``local``.
    """

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:
        raise PermissionError("no local plane in this scope")

    async def add_edges(self, edges: list[tuple]) -> int:
        raise PermissionError("no local plane in this scope")

    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: list[tuple[str, str, str]] | None = None,
    ) -> dict[str, Any]:
        raise PermissionError("no local plane in this scope")

    async def delete_page(self, concept_id: str) -> bool:
        raise PermissionError("no local plane in this scope")

    async def upsert_embedding(
        self, concept_id: str, vector: list[float], model: str = ""
    ) -> None:
        raise PermissionError("no local plane in this scope")

    async def get_page(
        self, concept_id: str, include_body: bool = True
    ) -> dict[str, Any] | None:
        return None

    async def list_pages(
        self,
        category: str | None = None,
        limit: int = 100,
        origin: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    async def search_fts(
        self, query: str, category: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        return []

    async def search_vector(
        self, embedding: list[float], limit: int = 10
    ) -> list[dict[str, Any]]:
        return []

    async def neighbors(
        self,
        concept_id: str,
        rel: str | None = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        return []

    async def dump_pages(self) -> list[dict[str, Any]]:
        return []

    async def dump_edges(self) -> list[dict[str, Any]]:
        return []

    async def stats(self) -> dict[str, Any]:
        return {
            "pages": 0,
            "edges": 0,
            "sources": 0,
            "embeddings": 0,
            "total_tokens": 0,
            "categories": {},
        }

    async def orphan_sources(self) -> list[str]:
        return []

    async def broken_edges(self) -> list[dict[str, Any]]:
        return []

    async def missing_bodies(self) -> list[str]:
        return []
