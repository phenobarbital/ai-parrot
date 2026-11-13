"""The procedure plane: a wiki store plus compiled index (FEAT-891)."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

from parrot.knowledge.wiki.procedure.index import compile_index, publish_index
from parrot.knowledge.wiki.procedure.models import PLANE_DIR, ProbeCost, ProcedureSpec
from parrot.knowledge.wiki.project import find_shared_root
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, create_wiki_store

STORE_FILE = "wiki.db"
WIKI_NAME = "procedure"
SOURCE_PREFIX = "procedure:"
CATEGORY = "procedure"
_PAGE_LIMIT = 10_000
_LIST_FIELDS = (
    "intents",
    "applies_to",
    "preconditions",
    "done_when",
    "requires_procedures",
    "requires_facts",
    "requires_tools",
    "next",
    "alternative_to",
    "escalates_to",
    "on_failure",
    "learned_from",
    "guards",
)


def _render_item(item: object) -> str:
    """Render one procedure-list item for its readable wiki page."""
    if isinstance(item, str):
        return item
    model_dump_json = getattr(item, "model_dump_json", None)
    return model_dump_json() if callable(model_dump_json) else str(item)


def _page_body(spec: ProcedureSpec) -> str:
    """Render the stable human-readable body for one procedure page."""
    lines = [f"# {spec.title}", f"Mode: {spec.mode}"]
    if spec.command:
        lines.append(f"Command: {spec.command}")
    for field_name in _LIST_FIELDS:
        value = getattr(spec, field_name)
        if value:
            label = field_name.replace("_", " ").title()
            lines.append(f"{label}: {', '.join(_render_item(item) for item in value)}")
    if spec.body:
        lines.extend(("", spec.body))
    return "\n".join(lines)


def _page(spec: ProcedureSpec) -> WikiPageRecord:
    """Return the wiki page of one procedure node."""
    spec_json = spec.model_dump_json()
    return WikiPageRecord(
        concept_id=spec.id,
        title=spec.title,
        category=CATEGORY,
        summary=spec.advice or spec.command,
        body=_page_body(spec),
        source_id=f"{SOURCE_PREFIX}{spec.origin_path}",
        origin="ingest",
        content_hash=hashlib.sha1(spec_json.encode("utf-8")).hexdigest(),  # noqa: S324 — content fingerprint
        attrs={
            "spec": spec_json,
            "mode": spec.mode,
            "kind": spec.kind,
            "scope_kind": spec.scope_kind,
            "source": spec.source,
        },
    )


class ProcedurePlane:
    """wiki.db + procedures.json under ``<shared-root>/.parrot/procedure``."""

    def __init__(self, plane_dir: Path) -> None:
        self.plane_dir = Path(plane_dir)
        self.logger = logging.getLogger(__name__)

    @classmethod
    def for_root(cls, start: Path | None = None) -> "ProcedurePlane | None":
        """Return the shared-root plane, or None outside a repository."""
        root = find_shared_root(start)
        return cls(root / PLANE_DIR) if root is not None else None

    async def build(
        self,
        specs: Sequence[ProcedureSpec],
        sources: Sequence[Path],
        *,
        root: Path,
        probe_costs: Mapping[str, ProbeCost],
    ) -> dict[str, int]:
        """Rebuild the store, then publish the index last.

        Returns:
            Counts for pages, edges, and supplied manifest sources.
        """
        store = create_wiki_store(storage_dir=self.plane_dir, wiki_name=WIKI_NAME)
        pages_by_source: dict[str, list[WikiPageRecord]] = {}
        for spec in specs:
            page = _page(spec)
            pages_by_source.setdefault(page.source_id or SOURCE_PREFIX, []).append(page)

        existing_sources = {
            page["source_id"]
            for page in await store.list_pages(category=CATEGORY, limit=_PAGE_LIMIT)
            if isinstance(page.get("source_id"), str) and page["source_id"].startswith(SOURCE_PREFIX)
        }
        for source_id in existing_sources - pages_by_source.keys():
            await store.replace_source_slice(source_id, [])

        pages = 0
        for source_id, source_pages in pages_by_source.items():
            result = await store.replace_source_slice(source_id, source_pages)
            pages += result["pages_written"]

        edge_records = [
            (*edge, spec.id.split(":", maxsplit=1)[0]) for spec in specs for edge in spec.edges()
        ]
        edges = await store.add_edges(edge_records)
        publish_index(self.plane_dir, compile_index(specs, sources, root=root, probe_costs=probe_costs))
        self.logger.info("procedure plane built: %d pages, %d edges", pages, edges)
        return {"pages": pages, "edges": edges, "sources": len(sources)}

    async def specs(self) -> list[ProcedureSpec]:
        """Read every node back from the store, sorted by id."""
        db_path = self.plane_dir / STORE_FILE
        if not db_path.is_file():
            return []
        store = SQLiteWikiStore(db_path, wiki_name=WIKI_NAME, read_only=True)
        specs: list[ProcedureSpec] = []
        for page in await store.list_pages(category=CATEGORY, limit=_PAGE_LIMIT):
            spec_json = (await store.get_attrs(page["concept_id"])).get("spec")
            if spec_json:
                specs.append(ProcedureSpec.model_validate_json(spec_json))
        return sorted(specs, key=lambda spec: spec.id)
