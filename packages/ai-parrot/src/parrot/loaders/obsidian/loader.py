"""ObsidianVaultLoader — Phase-1 raw vault ingest into PageIndex (FEAT-392).

Two entry points:

* :class:`ObsidianVaultLoader` — the FEAT-392 orchestration class:
  ``discover()`` parses the vault through the shared interface,
  ``ingest()`` stores one PageIndex node per note (no LLM required) and
  registers every file in :class:`SourceCollectionManager`;
  ``incremental_update()`` re-ingests only changed files and prunes
  deleted ones (local backend only — staleness is hash+mtime based).
* :class:`ObsidianLoader` — a thin :class:`AbstractLoader` adapter that
  yields one :class:`Document` per note with canonical metadata, so a
  vault can also feed the generic RAG loader pipeline.
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Optional

from parrot.interfaces.obsidian import (
    CANVAS_SUFFIX,
    NOTE_SUFFIX,
    LocalVaultBackend,
    ObsidianCanvas,
    ObsidianNote,
    ObsidianVaultInterface,
    VaultIndex,
    VaultIngestConfig,
    VaultIngestReport,
)
from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document

logger = logging.getLogger(__name__)


def _norm_path(rel: str) -> str:
    return rel[: -len(NOTE_SUFFIX)] if rel.lower().endswith(NOTE_SUFFIX) else rel


class ObsidianVaultLoader:
    """Parse and ingest Obsidian vault directories into PageIndex."""

    def __init__(self, vault: ObsidianVaultInterface | str | Path) -> None:
        """Initialize the loader.

        Args:
            vault: A prebuilt vault backend, or a vault directory path
                (auto-wrapped in :class:`LocalVaultBackend`).
        """
        if isinstance(vault, (str, Path)):
            vault = LocalVaultBackend(vault)
        self.vault = vault
        self.logger = logger

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    async def discover(
        self,
    ) -> tuple[list[ObsidianNote], list[ObsidianCanvas]]:
        """Scan the vault and parse all notes and canvas files.

        Returns:
            ``(notes, canvases)`` — unreadable files are skipped with a
            logged warning (never raises for individual files).
        """
        notes = await self.vault.load_notes()
        canvases: list[ObsidianCanvas] = []
        for info in await self.vault.list_files(
            suffixes=frozenset({CANVAS_SUFFIX})
        ):
            try:
                canvases.append(await self.vault.get_canvas(info.path))
            except (ValueError, FileNotFoundError, UnicodeDecodeError) as exc:
                self.logger.warning("Skipping canvas %s: %s", info.path, exc)
        return notes, canvases

    # ------------------------------------------------------------------ #
    # Embed-cycle detection (spec §7 gotcha)
    # ------------------------------------------------------------------ #
    def _detect_embed_cycles(
        self, notes: list[ObsidianNote], index: VaultIndex, depth_limit: int
    ) -> list[str]:
        """Detect circular ``![[embeds]]`` beyond the depth limit.

        Returns:
            Warning strings (also logged) — ingestion is never aborted.
        """
        embed_graph: dict[str, list[str]] = {}
        for note in notes:
            norm = _norm_path(note.path.as_posix())
            targets = []
            for link in note.links:
                if link.is_embed:
                    resolved = index.resolve(link.target, from_path=norm)
                    if resolved is not None:
                        targets.append(resolved)
            if targets:
                embed_graph[norm] = targets

        warnings: list[str] = []

        def _walk(start: str, node: str, depth: int, seen: set[str]) -> None:
            if depth > depth_limit:
                message = (
                    f"Embed depth limit ({depth_limit}) exceeded from "
                    f"'{start}' — stopping recursion"
                )
                if message not in warnings:
                    warnings.append(message)
                return
            for target in embed_graph.get(node, []):
                if target in seen:
                    message = (
                        f"Circular embed detected: '{target}' re-embedded "
                        f"along the chain starting at '{start}'"
                    )
                    if message not in warnings:
                        warnings.append(message)
                    continue
                _walk(start, target, depth + 1, seen | {target})

        for start in embed_graph:
            _walk(start, start, 1, {start})
        for message in warnings:
            self.logger.warning("%s", message)
        return warnings

    # ------------------------------------------------------------------ #
    # Phase 1: full ingest
    # ------------------------------------------------------------------ #
    async def ingest(
        self,
        pageindex_toolkit: Any,
        tree_name: str,
        source_manager: Any,
        config: Optional[VaultIngestConfig] = None,
    ) -> VaultIngestReport:
        """Full vault ingest into PageIndex (no LLM).

        One PageIndex node per note (aliases/tags/dataview queries in the
        node metadata); every source file registered with the
        :class:`SourceCollectionManager` for staleness tracking.

        Args:
            pageindex_toolkit: ``PageIndexToolkit`` storage target.
            tree_name: PageIndex tree to ingest into (created if missing).
            source_manager: ``SourceCollectionManager`` for the wiki.
            config: Optional ingest configuration (concurrency, skip
                patterns, embed depth limit).

        Returns:
            A :class:`VaultIngestReport` for phase ``"raw_ingest"``.
        """
        started = time.monotonic()
        config = config or VaultIngestConfig(
            vault_path=getattr(self.vault, "vault_path", Path(".")),
            tree_name=tree_name,
        )
        report = VaultIngestReport(
            vault_path=str(config.vault_path),
            tree_name=tree_name,
            phase="raw_ingest",
        )

        notes, canvases = await self.discover()
        index = await self.vault.build_index()
        report.errors.extend(
            self._detect_embed_cycles(notes, index, config.embed_depth_limit)
        )

        try:
            await pageindex_toolkit.get_tree(tree_name)
        except (KeyError, FileNotFoundError, ValueError):
            await pageindex_toolkit.create_tree(
                tree_name, doc_name=self.vault.vault_name
            )

        semaphore = asyncio.Semaphore(config.concurrency)

        async def _ingest_note(note: ObsidianNote) -> None:
            async with semaphore:
                rel = note.path.as_posix()
                try:
                    result = await pageindex_toolkit.add_node(
                        tree_name,
                        title=note.title,
                        body=note.content,
                        summary=None,
                        categories=sorted(note.tags) or None,
                        metadata=self._node_metadata(note),
                    )
                    node_id = result.get("node_id")
                    self._register_source(
                        source_manager, rel, [node_id] if node_id else []
                    )
                    report.notes_processed += 1
                    report.nodes_created += 1
                    report.files_added += 1
                except Exception as exc:  # noqa: BLE001 — collect, don't abort
                    self.logger.error("Failed to ingest %s: %s", rel, exc)
                    report.errors.append(f"{rel}: {exc}")
                    report.files_skipped += 1

        await asyncio.gather(*(_ingest_note(note) for note in notes))

        for canvas in canvases:
            rel = canvas.path.as_posix()
            try:
                card_titles = [
                    card.text or card.file_path or card.url or card.card_id
                    for card in canvas.cards
                ]
                result = await pageindex_toolkit.add_node(
                    tree_name,
                    title=canvas.title,
                    body="\n".join(f"- {title}" for title in card_titles),
                    metadata={"obsidian_type": "canvas", "obsidian_path": rel},
                )
                node_id = result.get("node_id")
                self._register_source(
                    source_manager, rel, [node_id] if node_id else []
                )
                report.canvas_processed += 1
                report.nodes_created += 1
                report.files_added += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.error("Failed to ingest canvas %s: %s", rel, exc)
                report.errors.append(f"{rel}: {exc}")
                report.files_skipped += 1

        report.duration_ms = (time.monotonic() - started) * 1000.0
        return report

    # ------------------------------------------------------------------ #
    # Incremental update
    # ------------------------------------------------------------------ #
    async def incremental_update(
        self,
        pageindex_toolkit: Any,
        tree_name: str,
        source_manager: Any,
        config: Optional[VaultIngestConfig] = None,
    ) -> VaultIngestReport:
        """Detect changed/new/deleted files and update PageIndex.

        Local backend only: staleness detection needs real filesystem
        paths (SHA-1 + mtime via ``SourceCollectionManager``).

        Args:
            pageindex_toolkit: ``PageIndexToolkit`` storage target.
            tree_name: PageIndex tree to update.
            source_manager: ``SourceCollectionManager`` with the previous
                ingest's manifest.
            config: Optional ingest configuration.

        Returns:
            A :class:`VaultIngestReport` with added/updated/deleted counts.

        Raises:
            NotImplementedError: For non-filesystem backends (REST).
        """
        if not isinstance(self.vault, LocalVaultBackend):
            raise NotImplementedError(
                "incremental_update requires the local filesystem backend — "
                "SourceCollectionManager staleness tracking is path-based"
            )
        started = time.monotonic()
        vault_root: Path = self.vault.vault_path
        config = config or VaultIngestConfig(
            vault_path=vault_root, tree_name=tree_name
        )
        report = VaultIngestReport(
            vault_path=str(vault_root),
            tree_name=tree_name,
            phase="raw_ingest",
        )

        infos = await self.vault.list_files()
        current = {info.path for info in infos}

        # --- Deletions: manifest entries whose file vanished ------------
        for entry in list(source_manager.list_sources()):
            uri = getattr(entry, "source_uri", "") or ""
            try:
                rel = Path(uri).resolve().relative_to(vault_root).as_posix()
            except ValueError:
                continue  # not under this vault
            if rel in current:
                continue
            for node_id in getattr(entry, "pages_generated", None) or []:
                try:
                    await pageindex_toolkit.delete_node(tree_name, node_id)
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"delete {node_id}: {exc}")
            source_manager.remove_source(entry.source_id)
            report.files_deleted += 1

        # --- Additions / modifications ----------------------------------
        semaphore = asyncio.Semaphore(config.concurrency)

        async def _sync_file(rel: str) -> None:
            async with semaphore:
                full = vault_root / rel
                source_id = source_manager.find_by_uri(str(full))
                is_new = source_id is None
                entry = None if is_new else source_manager.get_source(source_id)
                # FEAT-472: a row can exist and be hash/mtime-fresh without
                # this loader ever having ingested it — MeetingRegistry
                # (parrot.agents.meeting_registry) registers the SAME
                # sources row via add_source() for its own id-keyed dedup,
                # independently of any wiki ingest. "not stale" used to be
                # a reliable proxy for "already has PageIndex nodes"
                # because this loader was the row's only writer; that
                # assumption no longer holds, so an entry with no
                # pages_generated yet is always (re-)ingested regardless
                # of staleness.
                never_ingested = entry is not None and not (entry.pages_generated or [])
                if not is_new and not never_ingested and not source_manager.is_stale(source_id):
                    return
                # Stale (or never ingested): drop any previous nodes, then re-ingest.
                if entry is not None:
                    for node_id in getattr(entry, "pages_generated", None) or []:
                        try:
                            await pageindex_toolkit.delete_node(
                                tree_name, node_id
                            )
                        except Exception as exc:  # noqa: BLE001
                            report.errors.append(f"delete {node_id}: {exc}")
                try:
                    if rel.lower().endswith(NOTE_SUFFIX):
                        note = await self.vault.get_note(rel)
                        result = await pageindex_toolkit.add_node(
                            tree_name,
                            title=note.title,
                            body=note.content,
                            categories=sorted(note.tags) or None,
                            metadata=self._node_metadata(note),
                        )
                        report.notes_processed += 1
                    else:
                        canvas = await self.vault.get_canvas(rel)
                        result = await pageindex_toolkit.add_node(
                            tree_name,
                            title=canvas.title,
                            body="",
                            metadata={
                                "obsidian_type": "canvas",
                                "obsidian_path": rel,
                            },
                        )
                        report.canvas_processed += 1
                    node_id = result.get("node_id")
                    self._register_source(
                        source_manager, rel, [node_id] if node_id else []
                    )
                    report.nodes_created += 1
                    if is_new:
                        report.files_added += 1
                    else:
                        report.files_updated += 1
                except (UnicodeDecodeError, ValueError) as exc:
                    self.logger.warning("Skipping %s: %s", rel, exc)
                    report.files_skipped += 1
                except Exception as exc:  # noqa: BLE001
                    self.logger.error("Failed to sync %s: %s", rel, exc)
                    report.errors.append(f"{rel}: {exc}")
                    report.files_skipped += 1

        await asyncio.gather(*(_sync_file(info.path) for info in infos))
        report.duration_ms = (time.monotonic() - started) * 1000.0
        return report

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _node_metadata(note: ObsidianNote) -> dict[str, Any]:
        """PageIndex node metadata for a note (spec §5 conventions)."""
        metadata: dict[str, Any] = {
            "obsidian_type": "note",
            "obsidian_path": note.path.as_posix(),
        }
        if note.aliases:
            metadata["aliases"] = list(note.aliases)
        if note.dataview_queries:
            metadata["dataview_queries"] = list(note.dataview_queries)
        if note.frontmatter:
            # Keep only JSON-safe scalars to avoid store surprises.
            metadata["frontmatter_keys"] = sorted(
                str(key) for key in note.frontmatter
            )
        return metadata

    def _register_source(
        self, source_manager: Any, rel: str, node_ids: list[str]
    ) -> None:
        """Register a vault file in the source manifest (best-effort)."""
        vault_root = getattr(self.vault, "vault_path", None)
        if source_manager is None or vault_root is None:
            return
        try:
            entry = source_manager.add_source(Path(vault_root) / rel)
            source_manager.mark_ingested(entry.source_id, node_ids)
        except Exception as exc:  # noqa: BLE001 — manifest is advisory
            self.logger.warning("Source registration failed for %s: %s", rel, exc)


class ObsidianLoader(AbstractLoader):
    """AbstractLoader adapter: one :class:`Document` per Obsidian note.

    Enables the generic loader pipeline (chunking, vector stores) over a
    vault. Obsidian-specific extras (tags, aliases, links, dataview
    queries) go top-level in the metadata — the canonical
    ``document_meta`` sub-dict stays closed per the metadata contract.
    """

    extensions: list[str] = [".md"]

    def __init__(self, source: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("doctype", "markdown")
        kwargs.setdefault("category", "obsidian-note")
        super().__init__(source, **kwargs)
        self._vault_cache: dict[Path, LocalVaultBackend] = {}

    def _vault_for(self, path: Path) -> LocalVaultBackend:
        """Find (or wrap) the vault containing ``path``."""
        candidate = path if path.is_dir() else path.parent
        for parent in [candidate, *candidate.parents]:
            if (parent / ".obsidian").is_dir():
                candidate = parent
                break
        vault = self._vault_cache.get(candidate)
        if vault is None:
            vault = LocalVaultBackend(candidate)
            self._vault_cache[candidate] = vault
        return vault

    async def _load(self, source: Any, **kwargs: Any) -> list[Document]:
        """Load one note file (or every note of a vault directory).

        Args:
            source: Path to a ``.md`` note or a vault directory.

        Returns:
            One :class:`Document` per note.
        """
        path = Path(source).expanduser().resolve()
        vault = self._vault_for(path)
        if path.is_dir():
            notes = await vault.load_notes()
        else:
            rel = path.relative_to(vault.vault_path).as_posix()
            notes = [await vault.get_note(rel)]
        documents: list[Document] = []
        for note in notes:
            metadata = self.create_metadata(
                path=vault.vault_path / note.path,
                doctype="markdown",
                source_type="obsidian",
                title=note.title,
                obsidian_vault=vault.vault_name,
                obsidian_path=note.path.as_posix(),
                tags=sorted(note.tags),
                aliases=list(note.aliases),
                links=[link.target for link in note.links],
                dataview_queries=list(note.dataview_queries),
            )
            documents.append(
                self.create_document(content=note.content, path=path, metadata=metadata)
            )
        return documents
