"""SDD Graph Ingestion — parse SDD specs and task indexes into the ledger graph.

Scans `sdd/specs/*.spec.md` and `sdd/tasks/index/*.json` in the main checkout
and projects them into the wiki/ledger graph as `spec:` and `task:` nodes with
`implements`, `blocks`, and `touches` edges.

Implements spec §3 Module 7.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from parrot.knowledge.wiki.ledger.sdd_meta import parse as parse_spec_meta
from parrot.knowledge.wiki.store import WikiPageRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from parrot.knowledge.wiki.ledger.store import LedgerStore

logger = logging.getLogger(__name__)


class SDDGraphIngest:
    """Parses SDD specs and task indexes into graph pages and edges."""

    def __init__(self, store: "LedgerStore", shared_root: Path) -> None:
        """Initialize the SDD graph ingester.

        Args:
            store: LedgerStore instance for writing pages and edges.
            shared_root: Shared repository root directory.
        """
        self.store = store
        self.shared_root = shared_root
        self.specs_dir = shared_root / "sdd" / "specs"
        self.tasks_index_dir = shared_root / "sdd" / "tasks" / "index"

    async def ingest_all(self) -> dict[str, int]:
        """Ingest all specs, tasks, and dependency/file edges.

        Makes repeated ingestion idempotent through LedgerStore connection-scoped writers.

        Returns:
            Stats dict: {'specs': N, 'tasks': M, 'edges': E}.
        """
        stats = {"specs": 0, "tasks": 0, "edges": 0}

        # Ingest specs
        spec_stats = await self._ingest_specs()
        stats["specs"] += spec_stats["specs"]
        stats["edges"] += spec_stats["edges"]

        # Ingest tasks
        task_stats = await self._ingest_tasks()
        stats["tasks"] += task_stats["tasks"]
        stats["edges"] += task_stats["edges"]

        return stats

    async def _ingest_specs(self) -> dict[str, int]:
        """Ingest all SDD specifications."""
        # Directory listing + per-file parsing/reading is all blocking
        # filesystem I/O (`Path.glob`/`Path.read_text`) — run it off-thread
        # so this coroutine never blocks the event loop other concurrent
        # agent sessions share (e.g. via the MCP server). Only the actual
        # SQLite write below stays on the loop, via LedgerStore's own
        # async transaction.
        pages, edges, stats = await asyncio.to_thread(self._collect_spec_pages)

        if pages:
            async with self.store.ledger_transaction("ledger.ingest.specs") as conn:
                await self.store.upsert_pages_in(conn, pages)
                if edges:
                    await self.store.add_edges_in(conn, edges)

        return stats

    def _collect_spec_pages(self) -> tuple[list[WikiPageRecord], list[tuple], dict[str, int]]:
        """Blocking half of :meth:`_ingest_specs` — run via ``asyncio.to_thread``."""
        stats = {"specs": 0, "edges": 0}

        if not self.specs_dir.exists():
            logger.warning("Specs directory does not exist: %s", self.specs_dir)
            return [], [], stats

        spec_files = list(self.specs_dir.glob("*.spec.md"))
        logger.info("Found %d spec files to ingest", len(spec_files))

        pages: list[WikiPageRecord] = []
        edges: list[tuple] = []

        for spec_path in spec_files:
            try:
                spec_data = self._process_spec_file(spec_path)
                if spec_data:
                    page, spec_edges = spec_data
                    pages.append(page)
                    edges.extend(spec_edges)
                    stats["specs"] += 1
                    stats["edges"] += len(spec_edges)
            except Exception as e:
                logger.error("Failed to process spec file %s: %s", spec_path, e)
                continue

        return pages, edges, stats

    def _process_spec_file(self, spec_path: Path) -> tuple[WikiPageRecord, list[tuple]] | None:
        """Process a single spec file and return its page and edges.

        Sync (not ``async def``): it does nothing but blocking file I/O and
        is only ever called from :meth:`_collect_spec_pages`, itself run
        via ``asyncio.to_thread``.
        """
        try:
            # Get spec ID from filename
            spec_filename = spec_path.stem  # removes .md extension
            spec_id = f"spec:{spec_filename}"

            # Parse spec metadata
            meta = parse_spec_meta(spec_path)

            # Read file content
            content = spec_path.read_text(encoding="utf-8")

            # Create spec page
            page = WikiPageRecord(
                concept_id=spec_id,
                title=f"Spec: {spec_filename}",
                category="spec",
                summary=f"SDD specification for {spec_filename} (type: {meta.type}, base: {meta.base_branch})",
                body=content,
                source_id=str(spec_path.relative_to(self.shared_root)),
                token_count=len(content.split()),
                origin="sdd-spec",
                asserted_by="agent:sdd-ingest",
            )

            # For now, we don't create edges from specs in this basic implementation
            # More sophisticated edge creation would happen in a fuller implementation
            edges = []

            return page, edges

        except Exception as e:
            logger.error("Error processing spec file %s: %s", spec_path, e)
            return None

    async def _ingest_tasks(self) -> dict[str, int]:
        """Ingest all task indexes."""
        # See `_ingest_specs`'s comment: directory listing + per-file
        # read/parse is blocking filesystem I/O, run off-thread.
        pages, edges, stats = await asyncio.to_thread(self._collect_task_pages)

        if pages:
            async with self.store.ledger_transaction("ledger.ingest.tasks") as conn:
                await self.store.upsert_pages_in(conn, pages)
                if edges:
                    await self.store.add_edges_in(conn, edges)

        return stats

    def _collect_task_pages(self) -> tuple[list[WikiPageRecord], list[tuple], dict[str, int]]:
        """Blocking half of :meth:`_ingest_tasks` — run via ``asyncio.to_thread``."""
        stats = {"tasks": 0, "edges": 0}

        if not self.tasks_index_dir.exists():
            logger.warning("Tasks index directory does not exist: %s", self.tasks_index_dir)
            return [], [], stats

        index_files = list(self.tasks_index_dir.glob("*.json"))
        logger.info("Found %d task index files to ingest", len(index_files))

        pages: list[WikiPageRecord] = []
        edges: list[tuple] = []

        for index_path in index_files:
            try:
                task_data = self._process_task_index_file(index_path)
                if task_data:
                    task_pages, task_edges = task_data
                    pages.extend(task_pages)
                    edges.extend(task_edges)
                    stats["tasks"] += len(task_pages)
                    stats["edges"] += len(task_edges)
            except Exception as e:
                logger.error("Failed to process task index file %s: %s", index_path, e)
                continue

        return pages, edges, stats

    def _process_task_index_file(self, index_path: Path) -> tuple[list[WikiPageRecord], list[tuple]] | None:
        """Process a single task index file and return its pages and edges.

        Sync (not ``async def``): it does nothing but blocking file I/O and
        is only ever called from :meth:`_collect_task_pages`, itself run
        via ``asyncio.to_thread``.
        """
        try:
            # Read and parse the index file
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)

            feature_id = index_data.get("feature", "unknown")
            spec_path = index_data.get("spec", "")

            pages = []
            edges = []

            # Process each task in the index
            for task_entry in index_data.get("tasks", []):
                task_id = task_entry.get("id")
                if not task_id:
                    continue

                task_concept_id = f"task:{task_id}"

                # Create task page
                title = task_entry.get("title", f"Task {task_id}")
                file_path = task_entry.get("file", "")
                status = task_entry.get("status", "unknown")
                priority = task_entry.get("priority", "medium")
                effort = task_entry.get("effort", "M")
                depends_on = task_entry.get("depends_on", [])

                # Build task body with metadata
                body_parts = [
                    f"# {title}",
                    "",
                    f"**ID**: {task_id}",
                    f"**Feature**: {feature_id}",
                    f"**Status**: {status}",
                    f"**Priority**: {priority}",
                    f"**Effort**: {effort}",
                ]

                if spec_path:
                    body_parts.extend([f"**Spec**: {spec_path}", ""])

                if file_path:
                    body_parts.extend([f"**File**: {file_path}", ""])

                body = "\n".join(body_parts)

                page = WikiPageRecord(
                    concept_id=task_concept_id,
                    title=title,
                    category="task",
                    summary=f"Task {task_id}: {title}",
                    body=body,
                    source_id=file_path,
                    token_count=len(body.split()),
                    origin="sdd-task",
                    asserted_by="agent:sdd-ingest",
                )

                pages.append(page)

                # Create edges for dependencies. "blocks" is directed from the
                # blocker to the blocked task: dep_concept_id must complete
                # before task_concept_id can start, so the dependency blocks
                # the dependent — not the other way around.
                for dep_id in depends_on:
                    if dep_id.startswith("TASK-"):
                        dep_concept_id = f"task:{dep_id}"
                        edges.append((dep_concept_id, task_concept_id, "blocks", "asserted"))

                # Create edge to spec if available
                if spec_path:
                    spec_name = Path(spec_path).stem.replace(".spec", "")
                    spec_concept_id = f"spec:{spec_name}"
                    edges.append((task_concept_id, spec_concept_id, "implements", "asserted"))

                # Create edges for file scope if available
                # In a more complete implementation, we would parse the task file
                # to extract the exact files it touches, but for now we'll use
                # the file field from the index
                if file_path:
                    # Convert file path to a file concept ID
                    file_concept_id = f"file:{file_path}"
                    edges.append((task_concept_id, file_concept_id, "touches", "asserted"))

            return pages, edges

        except Exception as e:
            logger.error("Error processing task index file %s: %s", index_path, e)
            return None
