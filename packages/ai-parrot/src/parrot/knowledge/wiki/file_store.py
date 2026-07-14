"""In-memory wiki retrieval plane persisted as an OKF markdown bundle.

The SQLite-free backend (``WikiConfig.storage_backend = "memory"``):
all retrieval runs against RAM indexes — page dicts, a node-id map, a
hierarchical concept-id prefix tree, in/out edge adjacency, TF-IDF term
postings, and an embeddings map — while durability comes from a plain
**directory of OKF v0.1 markdown files**::

    {storage_dir}/pages/
    ├── index.md                  # auto-generated catalog
    ├── .embeddings.json          # vector sidecar (machine-only)
    ├── summaries/<id>.md         # YAML frontmatter + body
    ├── entities/<id>.md
    └── <category-plural>/<id>.md

The directory is therefore a valid, browsable OKF bundle at all times:
frontmatter carries the OKF fields (``type``, ``title``, ``id``,
``tags``, ``timestamp``, ``summary``, ``relates_to``) plus the wiki's
machine fields (``node_id``, ``source_id``, ``token_count``) — OKF
consumers tolerate unknown keys.

Loading walks the bundle once (lazily, on first use) and rebuilds every
index; queries never re-read files.  Mutations rewrite only the
affected page files plus ``index.md``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from parrot.knowledge.okf.utils import flatten_concept_id_for_filename
from parrot.knowledge.wiki.export import (
    OKF_TYPE_TO_CATEGORY,
    category_dir,
    generate_index,
    page_frontmatter,
)
from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    WikiPageRecord,
    _FTS_TOKEN_RE,
    estimate_tokens,
    rank_by_cosine,
)

logger = logging.getLogger(__name__)

_TITLE_BOOST = 3
_EMBEDDINGS_FILENAME = ".embeddings.json"


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _tokenize(text: str) -> list[str]:
    """Lowercased word tokens (same tokenizer as the FTS query builder)."""
    return [t.lower() for t in _FTS_TOKEN_RE.findall(text)]


class InMemoryWikiStore(BaseWikiStore):
    """RAM-indexed wiki store persisted as an OKF markdown directory.

    Args:
        bundle_dir: Root of the OKF bundle (typically
            ``{storage_dir}/pages`` — created automatically).
        wiki_name: Wiki name used in the bundle ``index.md`` header.

    Example::

        store = InMemoryWikiStore(storage_dir / "pages", wiki_name="my-wiki")
        await store.upsert_pages([WikiPageRecord(concept_id="intro", ...)])
        hits = await store.search_fts("neural networks", limit=5)
    """

    def __init__(self, bundle_dir: str | Path, wiki_name: str = "") -> None:
        self._bundle_dir = Path(bundle_dir)
        self._bundle_dir.mkdir(parents=True, exist_ok=True)
        self._wiki_name = wiki_name
        self.logger = logging.getLogger(__name__)

        self._loaded = False
        self._lock = asyncio.Lock()

        # RAM indexes (built by _load_bundle / maintained on mutation)
        self._pages: dict[str, dict[str, Any]] = {}
        self._by_node: dict[str, str] = {}
        self._out_edges: dict[str, list[tuple[str, str]]] = {}
        self._in_edges: dict[str, list[tuple[str, str]]] = {}
        self._embeddings: dict[str, dict[str, Any]] = {}
        self._postings: dict[str, dict[str, int]] = {}
        self._doc_len: dict[str, int] = {}
        self._tree: dict[str, Any] = {}  # nested prefix tree of concept_ids

    @property
    def bundle_dir(self) -> Path:
        """Root directory of the OKF bundle."""
        return self._bundle_dir

    # ------------------------------------------------------------------
    # Loading / persistence
    # ------------------------------------------------------------------

    async def _ensure_loaded(self) -> None:
        """Build all RAM indexes from the bundle directory once."""
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            await asyncio.to_thread(self._load_bundle)
            self._loaded = True

    def _load_bundle(self) -> None:
        """Walk ``bundle_dir`` and rebuild every index (sync, threaded)."""
        count = 0
        for md_file in sorted(self._bundle_dir.rglob("*.md")):
            if md_file.name == "index.md":
                continue
            try:
                page, relates = self._parse_page_file(md_file)
            except Exception as exc:  # noqa: BLE001 — skip bad files
                self.logger.warning(
                    "Skipping unparseable bundle file %s: %s", md_file, exc
                )
                continue
            self._index_page(page)
            for target, rel in relates:
                self._index_edge(page["concept_id"], target, rel)
            count += 1

        emb_path = self._bundle_dir / _EMBEDDINGS_FILENAME
        if emb_path.exists():
            try:
                self._embeddings = json.loads(emb_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                self.logger.warning("Could not load embeddings sidecar: %s", exc)
                self._embeddings = {}

        self.logger.debug(
            "InMemoryWikiStore loaded %d page(s) from %s", count, self._bundle_dir
        )

    @staticmethod
    def _parse_page_file(
        path: Path,
    ) -> tuple[dict[str, Any], list[tuple[str, str]]]:
        """Parse one bundle markdown file into a page row + edges.

        Uses plain ``yaml.safe_load`` (NOT the shared OKF parser, which
        enforces the closed ConceptType enum — open-string categories
        like ``"Answer"`` must load fine).
        """
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError("missing frontmatter delimiter")
        _, front_raw, body = text.split("---\n", 2)
        front = yaml.safe_load(front_raw) or {}
        if not isinstance(front, dict):
            raise ValueError("frontmatter is not a mapping")

        concept_id = str(front.get("id") or path.stem)
        okf_type_str = str(front.get("type") or "")
        tags = front.get("tags") or []
        category = str(
            front.get("category")
            or (tags[0] if tags else "")
            or OKF_TYPE_TO_CATEGORY.get(okf_type_str, okf_type_str.lower())
            or "concept"
        )
        body = body.lstrip("\n")
        page = {
            "concept_id": concept_id,
            "node_id": front.get("node_id"),
            "title": str(front.get("title") or concept_id),
            "category": category,
            "summary": str(front.get("summary") or ""),
            "body": body,
            "source_id": front.get("source_id"),
            "token_count": int(front.get("token_count") or 0)
            or estimate_tokens(body),
            "created_at": str(front.get("created_at") or front.get("timestamp") or ""),
            "updated_at": str(front.get("timestamp") or ""),
        }
        relates = [
            (str(item.get("concept")), str(item.get("rel") or "references"))
            for item in front.get("relates_to") or []
            if isinstance(item, dict) and item.get("concept")
        ]
        return page, relates

    def _page_path(self, page: dict[str, Any]) -> Path:
        """Bundle file path for a page row."""
        cat_dir = category_dir(str(page.get("category") or "concept"))
        stem = flatten_concept_id_for_filename(page["concept_id"])
        return self._bundle_dir / cat_dir / f"{stem}.md"

    def _write_page_file(self, page: dict[str, Any]) -> None:
        """Render + write one page's OKF markdown file (sync, threaded)."""
        relates = [
            {"concept": dst, "rel": rel}
            for dst, rel in self._out_edges.get(page["concept_id"], [])
        ]
        front = page_frontmatter(page, relates)
        # Machine fields appended into the same frontmatter block — OKF
        # consumers tolerate unknown keys.
        machine: dict[str, Any] = {}
        for key in ("category", "node_id", "source_id", "token_count", "created_at"):
            if page.get(key) not in (None, ""):
                machine[key] = page[key]
        if machine:
            extra = yaml.dump(
                machine, sort_keys=False, allow_unicode=True,
                default_flow_style=False,
            )
            front = front[: -len("---\n")] + extra + "---\n"
        path = self._page_path(page)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(front + "\n" + (page.get("body") or ""), encoding="utf-8")

    def _write_index_md(self) -> None:
        """Regenerate the bundle's root ``index.md`` (sync, threaded)."""
        entries = []
        for page in sorted(self._pages.values(), key=lambda p: p["concept_id"]):
            rel_path = self._page_path(page).relative_to(self._bundle_dir)
            entries.append(
                (
                    str(page.get("title") or page["concept_id"]),
                    str(rel_path),
                    str(page.get("summary") or ""),
                )
            )
        (self._bundle_dir / "index.md").write_text(
            generate_index(self._wiki_name or "wiki", entries),
            encoding="utf-8",
        )

    def _write_embeddings(self) -> None:
        """Persist the embeddings sidecar (sync, threaded)."""
        (self._bundle_dir / _EMBEDDINGS_FILENAME).write_text(
            json.dumps(self._embeddings), encoding="utf-8"
        )

    async def _persist_pages(self, pages: list[dict[str, Any]]) -> None:
        """Write the given pages' files + refresh index.md."""

        def _write_all() -> None:
            for page in pages:
                self._write_page_file(page)
            self._write_index_md()

        await asyncio.to_thread(_write_all)

    # ------------------------------------------------------------------
    # Index maintenance
    # ------------------------------------------------------------------

    def _index_page(self, page: dict[str, Any]) -> None:
        """Insert/replace a page in every RAM index."""
        cid = page["concept_id"]
        self._unindex_page(cid)
        self._pages[cid] = page
        if page.get("node_id"):
            self._by_node[str(page["node_id"])] = cid

        # term postings: title boosted, then summary + body
        counts: Counter[str] = Counter()
        for token in _tokenize(str(page.get("title") or "")):
            counts[token] += _TITLE_BOOST
        for token in _tokenize(
            f"{page.get('summary') or ''} {page.get('body') or ''}"
        ):
            counts[token] += 1
        self._doc_len[cid] = sum(counts.values())
        for term, tf in counts.items():
            self._postings.setdefault(term, {})[cid] = tf

        # hierarchical prefix tree from concept_id slash segments
        node = self._tree
        for segment in cid.split("/"):
            node = node.setdefault(segment, {})

    def _unindex_page(self, concept_id: str) -> None:
        """Remove a page from every RAM index (keeps its edges)."""
        old = self._pages.pop(concept_id, None)
        if old is None:
            return
        if old.get("node_id"):
            self._by_node.pop(str(old["node_id"]), None)
        self._doc_len.pop(concept_id, None)
        for term in list(self._postings):
            self._postings[term].pop(concept_id, None)
            if not self._postings[term]:
                del self._postings[term]
        node = self._tree
        # prune only the leaf (cheap; intermediate nodes may be shared)
        segments = concept_id.split("/")
        for segment in segments[:-1]:
            node = node.get(segment)
            if node is None:
                return
        if not node.get(segments[-1]):
            node.pop(segments[-1], None)

    def _index_edge(self, src: str, dst: str, rel: str) -> None:
        """Insert an edge into both adjacency maps (idempotent)."""
        entry = (dst, rel)
        out = self._out_edges.setdefault(src, [])
        if entry not in out:
            out.append(entry)
        rentry = (src, rel)
        inbound = self._in_edges.setdefault(dst, [])
        if rentry not in inbound:
            inbound.append(rentry)

    def _remove_edges_touching(self, concept_id: str) -> None:
        """Drop every edge where ``concept_id`` is src or dst."""
        for dst, rel in self._out_edges.pop(concept_id, []):
            self._in_edges[dst] = [
                e for e in self._in_edges.get(dst, []) if e[0] != concept_id
            ]
        for src, rel in self._in_edges.pop(concept_id, []):
            self._out_edges[src] = [
                e for e in self._out_edges.get(src, []) if e[0] != concept_id
            ]

    def _stub(self, page: dict[str, Any]) -> dict[str, Any]:
        """Stub view of a page row (no body)."""
        return {
            k: page.get(k)
            for k in (
                "concept_id",
                "node_id",
                "title",
                "category",
                "summary",
                "source_id",
                "token_count",
                "updated_at",
            )
        }

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:
        """Insert or update wiki pages (RAM indexes + bundle files)."""
        if not pages:
            return 0
        await self._ensure_loaded()
        now = _now_iso()
        rows: list[dict[str, Any]] = []
        for p in pages:
            existing = self._pages.get(p.concept_id, {})
            row = {
                "concept_id": p.concept_id,
                "node_id": p.node_id,
                "title": p.title,
                "category": p.category,
                "summary": p.summary,
                "body": p.body,
                "source_id": p.source_id,
                "token_count": p.token_count or estimate_tokens(p.body),
                "created_at": existing.get("created_at") or now,
                "updated_at": now,
            }
            old_path = (
                self._page_path(existing) if existing else None
            )
            self._index_page(row)
            new_path = self._page_path(row)
            if old_path and old_path != new_path and old_path.exists():
                old_path.unlink()
            rows.append(row)
        await self._persist_pages(rows)
        return len(rows)

    async def add_edges(self, edges: list[tuple[str, str, str]]) -> int:
        """Insert typed edges and re-persist affected source pages."""
        if not edges:
            return 0
        await self._ensure_loaded()
        touched: set[str] = set()
        for src, dst, rel in edges:
            self._index_edge(src, dst, rel)
            touched.add(src)
        # relates_to lives in the source page's frontmatter
        await self._persist_pages(
            [self._pages[cid] for cid in touched if cid in self._pages]
        )
        return len(edges)

    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None,
    ) -> dict[str, Any]:
        """Atomically replace all pages/edges derived from one source.

        Incoming edges from other sources are preserved when the
        replacement re-inserts the same stable ``concept_id`` (matching
        the SQLite backend's contract).
        """
        await self._ensure_loaded()
        old_ids = [
            cid
            for cid, page in self._pages.items()
            if page.get("source_id") == source_id
        ]
        old_set = set(old_ids)
        new_ids = {page.concept_id for page in pages}
        preserved = [
            (src, cid, rel)
            for cid in old_ids
            if cid in new_ids
            for src, rel in self._in_edges.get(cid, [])
            if src not in old_set
        ]
        for cid in old_ids:
            await self.delete_page(cid)
        written = await self.upsert_pages(pages)
        if edges:
            await self.add_edges(edges)
        if preserved:
            await self.add_edges(preserved)
        return {
            "pages_deleted": len(old_ids),
            "pages_written": written,
            "edges_written": len(edges or []),
        }

    async def delete_page(self, concept_id: str) -> bool:
        """Delete a page: RAM indexes, edges, embedding, bundle file."""
        await self._ensure_loaded()
        page = self._pages.get(concept_id)
        if page is None:
            return False
        path = self._page_path(page)
        self._unindex_page(concept_id)
        self._remove_edges_touching(concept_id)
        had_embedding = self._embeddings.pop(concept_id, None) is not None

        def _cleanup() -> None:
            if path.exists():
                path.unlink()
            self._write_index_md()
            if had_embedding:
                self._write_embeddings()

        await asyncio.to_thread(_cleanup)
        return True

    async def upsert_embedding(
        self,
        concept_id: str,
        vector: list[float],
        model: str = "",
    ) -> None:
        """Store (or replace) the embedding vector for a page."""
        await self._ensure_loaded()
        self._embeddings[concept_id] = {"vector": list(vector), "model": model}
        await asyncio.to_thread(self._write_embeddings)

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    async def get_page(
        self, concept_id: str, include_body: bool = True
    ) -> Optional[dict[str, Any]]:
        """Fetch a page by ``concept_id`` (falls back to ``node_id``)."""
        await self._ensure_loaded()
        page = self._pages.get(concept_id)
        if page is None:
            mapped = self._by_node.get(concept_id)
            page = self._pages.get(mapped) if mapped else None
        if page is None:
            return None
        row = dict(page)
        if not include_body:
            row.pop("body", None)
        return row

    async def list_pages(
        self,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List page stubs, optionally filtered by category."""
        await self._ensure_loaded()
        rows = [
            self._stub(p)
            for p in self._pages.values()
            if category is None or p.get("category") == category
        ]
        rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
        return rows[:limit]

    async def search_fts(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """TF-IDF lexical search over title/summary/body postings.

        Raw (unnormalised) scores — callers normalise per group, same
        contract as the SQLite backend's ``-bm25`` scores.
        """
        await self._ensure_loaded()
        terms = _tokenize(query)
        if not terms or not self._pages:
            return []
        n_docs = len(self._pages)
        scores: dict[str, float] = {}
        for term in set(terms):
            posting = self._postings.get(term)
            if not posting:
                continue
            idf = math.log(1.0 + n_docs / len(posting))
            for cid, tf in posting.items():
                doc_len = self._doc_len.get(cid) or 1
                scores[cid] = scores.get(cid, 0.0) + (tf / doc_len) * idf
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        out: list[dict[str, Any]] = []
        for cid, score in ranked:
            page = self._pages.get(cid)
            if page is None:
                continue
            if category is not None and page.get("category") != category:
                continue
            stub = self._stub(page)
            stub["score"] = score
            out.append(stub)
            if len(out) >= limit:
                break
        return out

    async def search_vector(
        self,
        embedding: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Cosine-similarity search over the embeddings map."""
        await self._ensure_loaded()
        candidates: list[tuple[dict[str, Any], list[float]]] = []
        for cid, entry in self._embeddings.items():
            page = self._pages.get(cid)
            if page is None:
                continue
            candidates.append((self._stub(page), entry.get("vector") or []))
        return rank_by_cosine(embedding, candidates, limit=limit)

    async def neighbors(
        self,
        concept_id: str,
        rel: Optional[str] = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Return edge-adjacent pages/targets of a concept."""
        await self._ensure_loaded()
        results: list[dict[str, Any]] = []
        if direction in ("out", "both"):
            for dst, edge_rel in self._out_edges.get(concept_id, []):
                if rel is not None and edge_rel != rel:
                    continue
                results.append(self._neighbor_item(dst, edge_rel, "out"))
        if direction in ("in", "both"):
            for src, edge_rel in self._in_edges.get(concept_id, []):
                if rel is not None and edge_rel != rel:
                    continue
                results.append(self._neighbor_item(src, edge_rel, "in"))
        return results

    def _neighbor_item(
        self, concept_id: str, rel: str, direction: str
    ) -> dict[str, Any]:
        """Build one neighbors() result row (page stub when known)."""
        page = self._pages.get(concept_id)
        return {
            "concept_id": concept_id,
            "rel": rel,
            "title": page.get("title") if page else None,
            "category": page.get("category") if page else None,
            "summary": page.get("summary") if page else None,
            "token_count": page.get("token_count") if page else None,
            "direction": direction,
        }

    async def dump_pages(self) -> list[dict[str, Any]]:
        """Return every page row WITH bodies (bulk export path)."""
        await self._ensure_loaded()
        return [
            dict(self._pages[cid]) for cid in sorted(self._pages)
        ]

    async def dump_edges(self) -> list[dict[str, Any]]:
        """Return every edge row (bulk export path)."""
        await self._ensure_loaded()
        rows = [
            {"src": src, "dst": dst, "rel": rel}
            for src, targets in self._out_edges.items()
            for dst, rel in targets
        ]
        rows.sort(key=lambda r: (r["src"], r["dst"], r["rel"]))
        return rows

    async def stats(self) -> dict[str, Any]:
        """Aggregate counters for the wiki."""
        await self._ensure_loaded()
        categories: Counter[str] = Counter(
            str(p.get("category") or "") for p in self._pages.values()
        )
        return {
            "pages": len(self._pages),
            "edges": sum(len(v) for v in self._out_edges.values()),
            "sources": len(self._load_source_manifest()),
            "embeddings": len(self._embeddings),
            "total_tokens": sum(
                int(p.get("token_count") or 0) for p in self._pages.values()
            ),
            "categories": dict(categories),
        }

    # ------------------------------------------------------------------
    # Lint API
    # ------------------------------------------------------------------

    def _load_source_manifest(self) -> dict[str, Any]:
        """Read the JSON source manifest maintained by the sources
        manager in ``json`` mode (``{storage_dir}/sources/.manifest.json``)."""
        manifest = self._bundle_dir.parent / "sources" / ".manifest.json"
        if not manifest.exists():
            return {}
        try:
            return json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    async def orphan_sources(self) -> list[str]:
        """Sources (from the JSON manifest) that produced no pages."""
        await self._ensure_loaded()
        covered = {
            p.get("source_id") for p in self._pages.values() if p.get("source_id")
        }
        return [
            sid for sid in self._load_source_manifest() if sid not in covered
        ]

    async def broken_edges(self) -> list[dict[str, Any]]:
        """Edges whose destination is neither a page nor a source."""
        await self._ensure_loaded()
        sources = set(self._load_source_manifest())
        return [
            {"src": src, "dst": dst, "rel": rel}
            for src, targets in self._out_edges.items()
            for dst, rel in targets
            if dst not in self._pages and dst not in sources
        ]

    async def missing_bodies(self) -> list[str]:
        """Pages with an empty body."""
        await self._ensure_loaded()
        return [
            cid for cid, p in sorted(self._pages.items()) if not p.get("body")
        ]
