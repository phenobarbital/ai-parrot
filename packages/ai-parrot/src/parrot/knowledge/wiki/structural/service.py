"""``StructuralService`` — symbol lookup, code outline, blast radius.

The only component in the FEAT-498 structural plane that reads the
working tree: :meth:`StructuralService._ensure_fresh` hashes candidate
files, compares against the persisted ``content_hash`` (TASK-2747/2748),
and re-scans stale ones through the exact same code path as
``wikitoolkit upsert --changed`` (:func:`parrot.knowledge.wiki.cli._ingest_files`).
Everything else in this feature is a pure function over already-persisted
facts.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.cli import _ingest_files, _open_sources
from parrot.knowledge.wiki.project import WikiProjectConfig, wiki_write_lock
from parrot.knowledge.wiki.repo_scan import (
    DEFAULT_EXCLUDE_DIRS,
    file_concept_id,
    scan_repository,
)
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.symbols import (
    SymbolKind,
    SymbolRecord,
    parse_sym_id,
    sym_concept_id,
    symbol_from_page,
)

logger = logging.getLogger(__name__)

#: Node cap for a single blast_radius BFS, to keep tool output bounded on
#: a highly-connected symbol graph.
_BLAST_RADIUS_NODE_CAP = 500

#: Default relations walked by blast_radius when the caller does not
#: override them.
_DEFAULT_BLAST_RELATIONS = ("calls", "extends", "implements")


class SymbolHit(BaseModel):
    """One symbol result row (lookup / outline / blast radius)."""

    symbol_id: str
    rel_path: str
    qualname: str
    kind: SymbolKind
    signature: str = ""
    doc: str = ""
    start_line: int
    end_line: int
    exported: bool = False
    score: float = 0.0
    stale: bool = False


class SymbolLookupOutput(BaseModel):
    """Result of :meth:`StructuralService.lookup`."""

    hits: list[SymbolHit] = Field(default_factory=list)
    total: int = 0
    repaired_files: list[str] = Field(default_factory=list)


class CodeOutlineOutput(BaseModel):
    """Result of :meth:`StructuralService.outline`."""

    target: str
    language: str = ""
    symbols: list[SymbolHit] = Field(default_factory=list)
    source: str | None = None
    truncated: bool = False


class ImpactedSymbol(BaseModel):
    """One node reached while walking :meth:`StructuralService.blast_radius`."""

    symbol: SymbolHit
    via: str
    distance: int
    provenance: str


class BlastRadiusOutput(BaseModel):
    """Result of :meth:`StructuralService.blast_radius`."""

    root: SymbolHit | None = None
    impacted: list[ImpactedSymbol] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    truncated: bool = False


def _record_to_hit(record: SymbolRecord, *, score: float = 0.0, stale: bool = False) -> SymbolHit:
    """Project a :class:`SymbolRecord` into the token-budgeted :class:`SymbolHit`."""
    return SymbolHit(
        symbol_id=sym_concept_id(record.rel_path, record.qualname),
        rel_path=record.rel_path,
        qualname=record.qualname,
        kind=record.kind,
        signature=record.signature[:200],
        doc=record.doc[:240],
        start_line=record.start_line,
        end_line=record.end_line,
        exported=record.exported,
        score=score,
        stale=stale,
    )


class StructuralService:
    """Read-only queries over the persisted symbol plane, with read-repair.

    Args:
        store: The local wiki retrieval-plane backend.
        root: Repository root the store's symbols/pages describe.
        config: Effective project configuration (storage path, include/
            exclude filters) — used only by :meth:`_ensure_fresh`.
    """

    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> None:
        self._store = store
        self._root = root.resolve()
        self._config = config
        self._sources = _open_sources(self._root, config, store=store)
        self._lock_busy = False

    # -- lookup -----------------------------------------------------------

    async def lookup(
        self,
        query: str,
        *,
        kind: SymbolKind | None = None,
        language: str | None = None,
        path_prefix: str | None = None,
        limit: int = 20,
    ) -> SymbolLookupOutput:
        """Find symbols by exact qualname, exact name, then lexical search.

        Args:
            query: Symbol name or qualname to look up.
            kind: Optional exact :class:`SymbolKind` filter.
            language: Optional exact scanner-name filter.
            path_prefix: Optional ``rel_path`` prefix filter.
            limit: Maximum results.

        Returns:
            Ranked hits (exact qualname > exact name > lexical match),
            refreshed via read-repair on the hit files first.
        """
        hits = await self._search(query, kind=kind, language=language, path_prefix=path_prefix, limit=limit)
        rel_paths = sorted({hit.rel_path for hit in hits})
        repaired = await self._ensure_fresh(rel_paths)
        if repaired:
            hits = await self._search(query, kind=kind, language=language, path_prefix=path_prefix, limit=limit)
        elif self._lock_busy:
            hits = [hit.model_copy(update={"stale": True}) for hit in hits]
        return SymbolLookupOutput(hits=hits, total=len(hits), repaired_files=repaired)

    async def _search(
        self,
        query: str,
        *,
        kind: SymbolKind | None,
        language: str | None,
        path_prefix: str | None,
        limit: int,
    ) -> list[SymbolHit]:
        """Exact qualname -> exact name -> ``search_symbols_fts``, deduped."""
        kind_value = kind.value if kind is not None else None
        seen: set[str] = set()
        hits: list[SymbolHit] = []

        def _add(record: SymbolRecord, score: float) -> None:
            symbol_id = sym_concept_id(record.rel_path, record.qualname)
            if symbol_id in seen:
                return
            seen.add(symbol_id)
            hits.append(_record_to_hit(record, score=score))

        qualname_matches = await self._store.find_symbols(
            qualname_prefix=query, kind=kind_value, language=language, path_prefix=path_prefix, limit=limit * 3
        )
        for record in qualname_matches:
            if record.qualname == query:
                _add(record, 1.0)
        if len(hits) < limit:
            name_matches = await self._store.find_symbols(
                name=query, kind=kind_value, language=language, path_prefix=path_prefix, limit=limit * 3
            )
            for record in name_matches:
                if len(hits) >= limit:
                    break
                _add(record, 0.9)
        if len(hits) < limit:
            fts_matches = await self._store.search_symbols_fts(query, limit=limit * 3)
            for rank, record in enumerate(fts_matches):
                if len(hits) >= limit:
                    break
                if kind_value is not None and record.kind.value != kind_value:
                    continue
                if language is not None and record.language != language:
                    continue
                if path_prefix is not None and not record.rel_path.startswith(path_prefix):
                    continue
                _add(record, max(0.1, 0.5 - rank * 0.05))
        return hits[:limit]

    # -- outline ------------------------------------------------------------

    async def outline(
        self,
        target: str,
        *,
        depth: int = 2,
        include_source: bool = False,
    ) -> CodeOutlineOutput:
        """Symbol outline of one file (or the file owning a ``sym:`` id).

        Args:
            target: A ``file:<rel>`` id, a ``sym:<rel>#<qualname>`` id, or
                a bare relative path.
            depth: Maximum symbol nesting depth included.
            include_source: When ``True`` and ``target`` is a ``sym:`` id,
                include a capped (4 000 char) source excerpt.

        Returns:
            The file's symbols (depth-filtered), refreshed via
            read-repair first. An out-of-root or excluded ``target``
            yields an empty, unrepaired result rather than raising.
        """
        rel_path = self._resolve_rel_path(target)
        if rel_path is None or not self._is_confined(rel_path):
            return CodeOutlineOutput(target=target, language="", symbols=[], source=None, truncated=False)

        await self._ensure_fresh([rel_path])
        records = await self._store.symbols_for(rel_path)
        records = [r for r in records if r.depth <= depth]
        hits = [_record_to_hit(r, score=1.0, stale=self._lock_busy) for r in records]
        language = records[0].language if records else ""

        source_text: str | None = None
        truncated = False
        if include_source and target.startswith("sym:"):
            source_text, truncated = self._read_source_excerpt(target, records)

        return CodeOutlineOutput(
            target=target, language=language, symbols=hits, source=source_text, truncated=truncated
        )

    def _read_source_excerpt(self, sym_id: str, records: list[SymbolRecord]) -> tuple[str | None, bool]:
        """Bounded ``start_byte:end_byte`` read (<= 4 000 chars) for a ``sym:`` target.

        Matched against ``records`` (already fetched by ``outline()`` via
        ``symbols_for``, which is full-byte-fidelity on the SQLite native
        table) rather than re-resolving through the page-based
        ``symbol_from_page`` decode, whose ``start_byte``/``end_byte``
        are intentionally zeroed (the rendered markdown body does not
        carry them precisely — see ``symbol_from_page``'s docstring).
        """
        try:
            _rel, qualname, _ordinal = parse_sym_id(sym_id)
        except ValueError:
            return None, False
        record = next((r for r in records if r.qualname == qualname), None)
        if record is None:
            return None, False
        try:
            data = (self._root / record.rel_path).read_bytes()
        except OSError:
            return None, False
        excerpt = data[record.start_byte : record.end_byte]
        text = excerpt.decode("utf-8", errors="replace")
        if len(text) > 4000:
            return text[:4000], True
        return text, False

    # -- blast radius ---------------------------------------------------

    async def blast_radius(
        self,
        symbol: str,
        *,
        relations: list[str] | None = None,
        depth: int = 2,
        include_inferred: bool = True,
        include_tests: bool = True,
    ) -> BlastRadiusOutput:
        """Symbols that transitively depend on ``symbol`` (reverse BFS).

        Args:
            symbol: A ``sym:`` id or an exact qualname.
            relations: Edge relations to follow (default: ``calls``,
                ``extends``, ``implements``).
            depth: Maximum BFS depth.
            include_inferred: Whether to follow ``provenance="inferred"``
                edges (globally-unique-name resolutions).
            include_tests: Whether to include symbols under a ``tests/``
                path prefix/segment.

        Returns:
            The root symbol, every impacted symbol reached, the sorted
            unique set of their files, and whether the node cap
            (:data:`_BLAST_RADIUS_NODE_CAP`) was hit.
        """
        rels = relations if relations else list(_DEFAULT_BLAST_RELATIONS)
        root_record = await self._resolve_symbol(symbol)
        if root_record is None:
            return BlastRadiusOutput(root=None, impacted=[], files=[], truncated=False)

        repaired = await self._ensure_fresh([root_record.rel_path])
        if repaired:
            root_record = await self._resolve_symbol(symbol) or root_record

        root_concept_id = sym_concept_id(root_record.rel_path, root_record.qualname)
        root_hit = _record_to_hit(root_record, score=1.0, stale=self._lock_busy)

        visited = {root_concept_id}
        impacted: list[ImpactedSymbol] = []
        frontier: list[tuple[str, int]] = [(root_concept_id, 0)]
        truncated = False

        while frontier:
            current_id, distance = frontier.pop(0)
            if distance >= depth:
                continue
            for rel in rels:
                if truncated:
                    break
                neighbors = await self._store.neighbors(current_id, rel=rel, direction="in")
                for neighbor in neighbors:
                    neighbor_id = str(neighbor.get("concept_id") or "")
                    if not neighbor_id or neighbor_id in visited:
                        continue
                    if len(visited) >= _BLAST_RADIUS_NODE_CAP:
                        truncated = True
                        break
                    visited.add(neighbor_id)
                    provenance = str(neighbor.get("provenance") or "extracted")
                    if not include_inferred and provenance == "inferred":
                        continue
                    record = await self._record_for_concept_id(neighbor_id)
                    if record is None:
                        continue  # dangling target — skipped, never followed
                    if not include_tests and self._is_test_path(record.rel_path):
                        continue
                    hit = _record_to_hit(record, score=1.0)
                    impacted.append(ImpactedSymbol(symbol=hit, via=rel, distance=distance + 1, provenance=provenance))
                    frontier.append((neighbor_id, distance + 1))

        files = sorted({imp.symbol.rel_path for imp in impacted})
        return BlastRadiusOutput(root=root_hit, impacted=impacted, files=files, truncated=truncated)

    @staticmethod
    def _is_test_path(rel_path: str) -> bool:
        return rel_path.startswith("tests/") or "/tests/" in rel_path

    async def _resolve_symbol(self, symbol: str) -> SymbolRecord | None:
        """Resolve a ``sym:`` id or exact qualname to its full record."""
        if symbol.startswith("sym:"):
            return await self._record_for_concept_id(symbol)
        matches = await self._store.find_symbols(qualname_prefix=symbol, limit=5)
        exact = [m for m in matches if m.qualname == symbol]
        if len(exact) == 1:
            return exact[0]
        if len(matches) == 1:
            return matches[0]
        return None

    async def _record_for_concept_id(self, concept_id: str) -> SymbolRecord | None:
        """Decode a ``sym:`` page (any backend) back into a :class:`SymbolRecord`."""
        page = await self._store.get_page(concept_id, include_body=True)
        if page is None or page.get("category") != "symbol":
            return None
        return symbol_from_page(page)

    # -- root confinement -------------------------------------------------

    def _resolve_rel_path(self, target: str) -> str | None:
        """Rel path a ``file:``/``sym:``/bare-path outline target names."""
        if target.startswith("file:"):
            return target[len("file:") :]
        if target.startswith("sym:"):
            try:
                rel_path, _qualname, _ordinal = parse_sym_id(target)
            except ValueError:
                return None
            return rel_path
        return target

    def _is_confined(self, rel_path: str) -> bool:
        """Whether ``rel_path`` resolves inside ``root`` and outside excluded dirs.

        ``Path.__truediv__`` already discards ``self._root`` when
        ``rel_path`` is itself absolute, so a single join + ``resolve()``
        correctly rejects both ``../escape.py`` and an absolute path
        outside the repository.
        """
        posix_rel = PurePosixPath(rel_path)
        try:
            resolved = (self._root / rel_path).resolve()
        except OSError:
            return False
        if not (resolved == self._root or resolved.is_relative_to(self._root)):
            return False
        return not any(part in DEFAULT_EXCLUDE_DIRS for part in posix_rel.parts)

    # -- read-repair --------------------------------------------------------

    def _disk_hash(self, rel_path: str) -> str | None:
        """SHA-1 of a file's current bytes on disk, or ``None`` when missing."""
        try:
            data = (self._root / rel_path).read_bytes()
        except OSError:
            return None
        return hashlib.sha1(data).hexdigest()

    async def _ensure_fresh(self, rel_paths: list[str]) -> list[str]:
        """Re-scan any of ``rel_paths`` whose disk hash disagrees with the plane.

        Args:
            rel_paths: Candidate files to check (never the whole repo).

        Returns:
            The rel paths actually re-scanned/removed. Empty when
            nothing was stale, or when the write lock was held by
            another writer (in which case :attr:`_lock_busy` is set so
            callers can flag their hits ``stale=True``).
        """
        self._lock_busy = False
        if not rel_paths:
            return []
        concept_ids = [file_concept_id(p) for p in rel_paths]
        known = await self._store.page_hashes(concept_ids)
        stale = [
            rel_path
            for rel_path, concept_id in zip(rel_paths, concept_ids)
            if self._disk_hash(rel_path) != known.get(concept_id)
        ]
        if not stale:
            return []

        with wiki_write_lock(self._config.storage_path(self._root), timeout=0) as acquired:
            if not acquired:
                self._lock_busy = True
                return []

            existing = [p for p in stale if (self._root / p).is_file()]
            deleted = [p for p in stale if p not in existing]

            if existing:
                scan = scan_repository(
                    self._root,
                    rel_paths=existing,
                    suffixes=self._config.include_suffixes or None,
                    exclude_dirs=self._config.exclude_dirs,
                )
                await _ingest_files(self._store, self._sources, self._root, scan, force=True)

            for rel_path in deleted:
                await self._drop_slice(rel_path)

        return stale

    async def _drop_slice(self, rel_path: str) -> None:
        """Remove a deleted file's slice — mirrors ``wikitoolkit upsert``'s handling."""
        uri = str((self._root / rel_path).resolve())
        source_id = await asyncio.to_thread(self._sources.find_by_uri, uri)
        if source_id:
            await self._store.replace_source_slice(source_id, [], [])
            await asyncio.to_thread(self._sources.remove_source, source_id)
