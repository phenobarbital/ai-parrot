"""ExecutionWikiRecorder — crew/flow execution content in the LLM Wiki plane.

Records everything an :class:`~parrot.bots.flows.crew.crew.AgentCrew` run
produces — the run itself, every intermediate per-agent result, and every
intermediate tool-call result — as wiki pages + typed edges in a per-crew
:class:`~parrot.knowledge.wiki.store.SQLiteWikiStore` (``wiki.db``), so the
existing wiki search machinery (FTS5/BM25 + optional embedding cosine) can
search *inside the research*, not just over final outputs.

Page/edge mapping (categories and relations are open strings — the machine
plane has no enum ceremony):

=====================  ===================================  ==============
Content                concept_id                           category
=====================  ===================================  ==============
Crew run               ``run:{execution_id}``               ``crew_run``
Agent/tool-node result ``agent:{execution_id}:{node_id}``   ``agent_result``
Tool call              ``tool:{execution_id}:{node_id}:N``  ``tool_result``
=====================  ===================================  ==============

Edges: ``run —contains→ agent``, ``agent —follows→ previous agent``,
``agent —used_tool→ tool``.  Every page carries
``source_id = "exec:{execution_id}"`` so a single run can be filtered.

The store is the standard wiki.db schema, so the ``wikitoolkit`` CLI reads
it directly (``wikitoolkit query "<q>" --store <storage_dir>`` or
``--path <storage_dir>`` — the recorder writes a minimal
``.parrot/wiki.json`` next to the database for the latter).

All public record methods are failure-tolerant: they log and continue,
never raising into the crew's execution path (mirrors
``PersistenceMixin._save_result`` error handling).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from datamodel.parsers.json import json_encoder  # pylint: disable=E0611 # noqa

from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    save_project_config,
)
from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    WikiPageRecord,
    create_wiki_store,
    estimate_tokens,
)

logger = logging.getLogger(__name__)

#: Cap on stored page body length (matches ``WikiProjectConfig.body_max_chars``).
DEFAULT_BODY_MAX_CHARS = 16_000

#: Default relative location of a crew's execution wiki.
DEFAULT_WIKI_ROOT = Path(".parrot") / "crew_wiki"

# Open-string page categories used by the execution wiki.
CATEGORY_RUN = "crew_run"
CATEGORY_AGENT = "agent_result"
CATEGORY_TOOL = "tool_result"

# Open-string edge relations used by the execution wiki.
REL_CONTAINS = "contains"
REL_FOLLOWS = "follows"
REL_USED_TOOL = "used_tool"


def crew_slug(name: str) -> str:
    """Return a filesystem-safe slug for a crew name.

    Args:
        name: Human-readable crew name.

    Returns:
        Lower-cased slug with non-alphanumeric runs collapsed to ``-``.
    """
    slug = "".join(c if c.isalnum() else "-" for c in (name or "crew").lower())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "crew"


def default_wiki_dir(crew_name: str, base_dir: Optional[Path] = None) -> Path:
    """Resolve the default storage directory for a crew's execution wiki.

    Args:
        crew_name: Crew name (slugified for the directory).
        base_dir: Base directory; defaults to the current working directory.

    Returns:
        ``{base_dir}/.parrot/crew_wiki/{crew-slug}``.
    """
    base = base_dir or Path.cwd()
    return base / DEFAULT_WIKI_ROOT / crew_slug(crew_name)


def _clip(text: str, limit: int) -> str:
    """Clip ``text`` to ``limit`` characters with an ellipsis marker."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated]"


def _to_json_text(value: Any, limit: int) -> str:
    """Render an arbitrary value as bounded JSON-ish text (never raises)."""
    try:
        rendered = json_encoder(value)
    except Exception:  # noqa: BLE001 — body building must never raise
        rendered = str(value)
    if not isinstance(rendered, str):
        rendered = str(rendered)
    return _clip(rendered, limit)


def _tool_call_field(call: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a tool-call record (dict or object)."""
    if isinstance(call, dict):
        return call.get(key, default)
    return getattr(call, key, default)


class ExecutionWikiRecorder:
    """Persist crew execution content into a WikiStore SQLite plane.

    One recorder per crew: pages from every run accumulate in the same
    ``wiki.db`` (tagged by ``execution_id``), enabling cross-run research
    search.

    Args:
        storage_dir: Directory holding ``wiki.db`` (created on demand).
        crew_name: Crew name recorded in the wiki ``meta`` table.
        embedding_model: Optional embedding source for the vector search
            leg.  Accepts an async ``text -> list[float]`` callable, a
            SentenceTransformer-like object (sync ``.encode``), or a
            parrot ``EmbeddingModel`` wrapper.  BM25-only when ``None``
            or unusable.
        body_max_chars: Cap applied to stored page bodies.
        write_project_config: When ``True`` (default), write a minimal
            ``.parrot/wiki.json`` inside ``storage_dir`` so
            ``wikitoolkit ... --path <storage_dir>`` resolves the plane.
    """

    def __init__(
        self,
        storage_dir: str | Path,
        crew_name: str,
        embedding_model: Any = None,
        body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
        write_project_config: bool = True,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.crew_name = crew_name
        self.body_max_chars = body_max_chars
        self.logger = logging.getLogger(f"parrot.wiki.execution.{crew_name}")
        self._store: BaseWikiStore = create_wiki_store(
            self.storage_dir, wiki_name=f"crew:{crew_name}"
        )
        self._embedder = self._build_embedder(embedding_model)
        self._embedding_model_name = (
            type(embedding_model).__name__ if embedding_model is not None else ""
        )
        # Last agent page per execution_id — source of the `follows` edge.
        self._last_agent_page: Dict[str, str] = {}
        if write_project_config:
            self._write_project_config()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    @property
    def store(self) -> BaseWikiStore:
        """The underlying wiki retrieval-plane store."""
        return self._store

    def _write_project_config(self) -> None:
        """Write ``.parrot/wiki.json`` inside the storage dir (best-effort).

        Makes the execution wiki a self-contained wiki project so
        ``wikitoolkit query|page|related --path <storage_dir>`` works
        without extra flags.
        """
        try:
            config = WikiProjectConfig(
                wiki_name=f"crew:{self.crew_name}",
                storage_dir=".",
            )
            save_project_config(self.storage_dir, config)
        except Exception as exc:  # noqa: BLE001 — config is a convenience
            self.logger.debug("Could not write wiki project config: %s", exc)

    def _build_embedder(
        self, embedding_model: Any
    ) -> Optional[Callable[[str], Awaitable[List[float]]]]:
        """Normalise the accepted embedding sources into an async callable.

        Args:
            embedding_model: See class docstring.

        Returns:
            Async ``text -> vector`` callable, or ``None`` (BM25-only).
        """
        if embedding_model is None:
            return None

        # Async callable — use directly.
        if callable(embedding_model) and inspect.iscoroutinefunction(
            embedding_model
        ):
            return embedding_model

        # Parrot EmbeddingModel wrapper — unwrap to the raw library model.
        raw = embedding_model
        try:
            from parrot.embeddings.base import EmbeddingModel

            if isinstance(raw, EmbeddingModel):
                raw = raw.model
        except ImportError:
            pass

        encode = getattr(raw, "encode", None)
        if not callable(encode):
            self.logger.debug(
                "Embedding model %r has no usable encode(); BM25-only.",
                type(embedding_model).__name__,
            )
            return None

        async def _encode(text: str) -> List[float]:
            # Offload CPU-bound encode to a thread (same pattern as
            # VectorStoreMixin._vectorize_result_async).
            vector = await asyncio.to_thread(encode, text)
            if hasattr(vector, "tolist"):
                vector = vector.tolist()
            # SentenceTransformer.encode("text") returns a 1-D vector; a
            # list input would return 2-D — flatten defensively.
            if vector and isinstance(vector[0], (list, tuple)):
                vector = vector[0]
            return [float(v) for v in vector]

        return _encode

    # ------------------------------------------------------------------
    # Page-identity helpers
    # ------------------------------------------------------------------

    @staticmethod
    def run_page_id(execution_id: str) -> str:
        """concept_id of a run page."""
        return f"run:{execution_id}"

    @staticmethod
    def agent_page_id(execution_id: str, node_id: str) -> str:
        """concept_id of an agent-result page."""
        return f"agent:{execution_id}:{node_id}"

    @staticmethod
    def tool_page_id(execution_id: str, node_id: str, call_id: str) -> str:
        """concept_id of a tool-call page."""
        return f"tool:{execution_id}:{node_id}:{call_id}"

    @staticmethod
    def _source_id(execution_id: str) -> str:
        """source_id tag shared by every page of one run."""
        return f"exec:{execution_id}"

    # ------------------------------------------------------------------
    # Recording API (failure-tolerant — never raises into a run)
    # ------------------------------------------------------------------

    async def record_run_start(
        self,
        execution_id: str,
        method: str,
        task: Any,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tenant: Optional[str] = None,
    ) -> None:
        """Record the start of a crew run as a ``crew_run`` page.

        Args:
            execution_id: Crew-level execution id.
            method: Execution method name (e.g. ``"run_sequential"``).
            task: The initial task/prompt (any type; rendered as text).
            user_id: Optional user identifier.
            session_id: Optional session identifier.
            tenant: Optional tenant identifier.
        """
        try:
            task_text = _to_json_text(task, self.body_max_chars // 4)
            body = (
                f"# Crew Run {execution_id}\n\n"
                f"- **Crew**: {self.crew_name}\n"
                f"- **Method**: {method}\n"
                f"- **Status**: running\n"
                f"- **User**: {user_id or 'unknown'}\n"
                f"- **Session**: {session_id or 'unknown'}\n"
                f"- **Tenant**: {tenant or 'global'}\n\n"
                f"## Task\n\n{task_text}\n"
            )
            page = WikiPageRecord(
                concept_id=self.run_page_id(execution_id),
                title=f"{self.crew_name} run {execution_id} ({method})",
                category=CATEGORY_RUN,
                summary=_clip(task_text.replace("\n", " "), 400),
                body=body,
                source_id=self._source_id(execution_id),
                token_count=estimate_tokens(body),
            )
            await self._store.upsert_pages([page])
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Failed to record run start for '%s': %s", execution_id, exc
            )

    async def record_agent_result(
        self,
        execution_id: str,
        node_result: Any,
        tool_calls: Optional[List[Any]] = None,
    ) -> None:
        """Record one agent's intermediate result and its tool calls.

        Writes the ``agent_result`` page, one ``tool_result`` page per
        tool call, and the ``contains``/``follows``/``used_tool`` edges.

        Args:
            execution_id: Crew-level execution id linking pages to the run.
            node_result: The per-agent execution record (``NodeResult`` —
                anything exposing ``node_id``/``agent_id``, ``node_name``,
                ``task``, and ``to_text()``).
            tool_calls: Serialised tool-call records (dicts or ``ToolCall``
                objects with ``id``/``name``/``arguments``/``result``/
                ``error``/``execution_time``).
        """
        try:
            node_id = (
                getattr(node_result, "node_id", None)
                or getattr(node_result, "agent_id", "unknown")
            )
            node_name = (
                getattr(node_result, "node_name", None)
                or getattr(node_result, "agent_name", node_id)
            )
            task = str(getattr(node_result, "task", "") or "")
            if hasattr(node_result, "to_text"):
                body = str(node_result.to_text())
            else:
                body = _to_json_text(node_result, self.body_max_chars)
            body = _clip(body, self.body_max_chars)

            agent_cid = self.agent_page_id(execution_id, node_id)
            run_cid = self.run_page_id(execution_id)
            pages = [
                WikiPageRecord(
                    concept_id=agent_cid,
                    title=f"{node_name} — result ({execution_id})",
                    category=CATEGORY_AGENT,
                    summary=_clip(task.replace("\n", " "), 400),
                    body=body,
                    source_id=self._source_id(execution_id),
                    token_count=estimate_tokens(body),
                )
            ]
            edges: List[tuple] = [(run_cid, agent_cid, REL_CONTAINS)]
            if prev := self._last_agent_page.get(execution_id):
                if prev != agent_cid:
                    edges.append((agent_cid, prev, REL_FOLLOWS))
            self._last_agent_page[execution_id] = agent_cid

            for index, call in enumerate(tool_calls or []):
                page, edge = self._build_tool_call_page(
                    execution_id, node_id, node_name, agent_cid, index, call
                )
                pages.append(page)
                edges.append(edge)

            await self._store.upsert_pages(pages)
            await self._store.add_edges(edges)
            await self._embed_pages(pages)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Failed to record agent result for '%s': %s", execution_id, exc
            )

    def _build_tool_call_page(
        self,
        execution_id: str,
        node_id: str,
        node_name: str,
        agent_cid: str,
        index: int,
        call: Any,
    ) -> tuple:
        """Build the page + ``used_tool`` edge for one tool call."""
        call_id = str(_tool_call_field(call, "id", None) or index)
        tool_name = str(_tool_call_field(call, "name", "unknown_tool"))
        arguments = _tool_call_field(call, "arguments", {})
        result = _tool_call_field(call, "result", None)
        error = _tool_call_field(call, "error", None)
        exec_time = _tool_call_field(call, "execution_time", None)

        section_limit = self.body_max_chars // 2
        parts = [
            f"# Tool Call: {tool_name}",
            "",
            f"- **Agent**: {node_name} ({node_id})",
            f"- **Execution**: {execution_id}",
            f"- **Call id**: {call_id}",
        ]
        if exec_time is not None:
            parts.append(f"- **Execution Time**: {exec_time}")
        parts += ["", "## Arguments", "", _to_json_text(arguments, section_limit)]
        if error is not None:
            parts += ["", "## Error", "", _clip(str(error), section_limit)]
        if result is not None:
            parts += ["", "## Result", "", _to_json_text(result, section_limit)]
        body = "\n".join(parts)

        tool_cid = self.tool_page_id(execution_id, node_id, call_id)
        page = WikiPageRecord(
            concept_id=tool_cid,
            title=f"{tool_name} — tool call by {node_name} ({execution_id})",
            category=CATEGORY_TOOL,
            summary=_clip(
                f"{tool_name}({_to_json_text(arguments, 200)})".replace("\n", " "),
                400,
            ),
            body=body,
            source_id=self._source_id(execution_id),
            token_count=estimate_tokens(body),
        )
        return page, (agent_cid, tool_cid, REL_USED_TOOL)

    async def record_run_end(
        self,
        execution_id: str,
        result: Any,
        method: Optional[str] = None,
    ) -> None:
        """Record the completion of a crew run on its ``crew_run`` page.

        Args:
            execution_id: Crew-level execution id.
            result: The final result — a ``FlowResult`` (``output``,
                ``summary``, ``status``, ``total_time``) or any object
                rendered as text.
            method: Optional execution method name (kept from run start
                when omitted).
        """
        try:
            run_cid = self.run_page_id(execution_id)
            existing = await self._store.get_page(run_cid, include_body=True)

            output = getattr(result, "output", result)
            summary = str(getattr(result, "summary", "") or "")
            status = getattr(result, "status", "completed")
            status = getattr(status, "value", status)
            total_time = getattr(result, "total_time", None)

            output_text = _to_json_text(output, self.body_max_chars // 2)
            parts = [
                str(existing.get("body") or "") if existing else "",
                "\n## Final Output\n",
                output_text,
            ]
            if summary:
                parts += ["\n## Summary\n", _clip(summary, self.body_max_chars // 4)]
            parts.append(f"\n- **Final Status**: {status}")
            if total_time is not None:
                parts.append(f"- **Total Time**: {total_time:.2f}s")
            body = _clip("\n".join(parts), self.body_max_chars)

            title = (
                str(existing.get("title"))
                if existing
                else f"{self.crew_name} run {execution_id}"
                + (f" ({method})" if method else "")
            )
            page = WikiPageRecord(
                concept_id=run_cid,
                title=title,
                category=CATEGORY_RUN,
                summary=_clip(output_text.replace("\n", " "), 400),
                body=body,
                source_id=self._source_id(execution_id),
                token_count=estimate_tokens(body),
            )
            await self._store.upsert_pages([page])
            await self._embed_pages([page])
            self._last_agent_page.pop(execution_id, None)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Failed to record run end for '%s': %s", execution_id, exc
            )

    async def _embed_pages(self, pages: List[WikiPageRecord]) -> None:
        """Store embeddings for ``pages`` when an embedder is configured."""
        if self._embedder is None:
            return
        for page in pages:
            try:
                text = f"{page.title}\n{page.summary}\n{page.body}"
                vector = await self._embedder(text[: self.body_max_chars])
                if vector:
                    await self._store.upsert_embedding(
                        page.concept_id,
                        vector,
                        model=self._embedding_model_name,
                    )
            except Exception as exc:  # noqa: BLE001
                self.logger.debug(
                    "Embedding failed for page '%s': %s", page.concept_id, exc
                )

    # ------------------------------------------------------------------
    # Search / read API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        top_k: int = 10,
        category: Optional[str] = None,
        execution_id: Optional[str] = None,
        lexical_weight: float = 0.6,
        vector_weight: float = 0.4,
    ) -> List[Dict[str, Any]]:
        """Search the execution wiki (BM25 + optional embedding cosine).

        Args:
            query: Natural-language query.
            top_k: Maximum merged results.
            category: Optional exact category filter (``crew_run`` /
                ``agent_result`` / ``tool_result``).
            execution_id: Optional filter to a single run.
            lexical_weight: Weight of the BM25 leg when both legs return.
            vector_weight: Weight of the cosine leg when both legs return.

        Returns:
            Result dicts (``concept_id``, ``title``, ``category``,
            ``summary``, ``source_id``, ``token_count``, ``score`` in
            [0, 1], ``source`` = ``"lexical"``/``"vector"``), best first.
        """
        source_filter = (
            self._source_id(execution_id) if execution_id else None
        )

        lexical: List[Dict[str, Any]] = []
        try:
            rows = await self._store.search_fts(
                query, category=category, limit=top_k
            )
            lexical = self._tag(self._normalize(rows), "lexical")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Execution wiki FTS search failed: %s", exc)

        vector: List[Dict[str, Any]] = []
        if self._embedder is not None:
            try:
                embedding = await self._embedder(query)
                rows = await self._store.search_vector(embedding, limit=top_k)
                if category is not None:
                    rows = [r for r in rows if r.get("category") == category]
                vector = self._tag(self._normalize(rows), "vector")
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "Execution wiki vector search failed: %s", exc
                )

        # A lone leg gets full weight so scores stay meaningful in [0, 1].
        if lexical and not vector:
            lexical_weight = 1.0
        elif vector and not lexical:
            vector_weight = 1.0

        merged: Dict[str, Dict[str, Any]] = {}
        for group, weight in ((lexical, lexical_weight), (vector, vector_weight)):
            for row in group:
                cid = str(row.get("concept_id") or "")
                if source_filter and row.get("source_id") != source_filter:
                    continue
                row = {**row, "score": round(float(row["score"]) * weight, 4)}
                kept = merged.get(cid)
                if kept is None or row["score"] > kept["score"]:
                    merged[cid] = row
        results = sorted(
            merged.values(), key=lambda r: r["score"], reverse=True
        )
        return results[:top_k]

    @staticmethod
    def _normalize(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Min-max normalise raw store scores into [0, 1]."""
        if not rows:
            return []
        scores = [float(r.get("score") or 0.0) for r in rows]
        min_s, max_s = min(scores), max(scores)
        span = max_s - min_s
        return [
            {**row, "score": (raw - min_s) / span if span > 0 else 1.0}
            for row, raw in zip(rows, scores)
        ]

    @staticmethod
    def _tag(
        rows: List[Dict[str, Any]], source: str
    ) -> List[Dict[str, Any]]:
        """Tag each row with the search leg that produced it."""
        return [{**row, "source": source} for row in rows]

    async def get_page(
        self, concept_id: str, include_body: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Read one execution-wiki page (progressive disclosure).

        Args:
            concept_id: Page identity (``run:...``/``agent:...``/``tool:...``).
            include_body: When ``False`` the body column is omitted.

        Returns:
            Page dict or ``None`` when not found / on error.
        """
        try:
            return await self._store.get_page(
                concept_id, include_body=include_body
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("get_page('%s') failed: %s", concept_id, exc)
            return None

    async def related(
        self,
        concept_id: str,
        rel: Optional[str] = None,
        direction: str = "both",
    ) -> List[Dict[str, Any]]:
        """Follow typed edges from a page (``contains``/``follows``/``used_tool``).

        Args:
            concept_id: Seed page identity.
            rel: Optional exact relation filter.
            direction: ``"out"``, ``"in"``, or ``"both"``.

        Returns:
            Neighbour dicts (empty on error).
        """
        try:
            return await self._store.neighbors(
                concept_id, rel=rel, direction=direction
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("related('%s') failed: %s", concept_id, exc)
            return []

    async def stats(self) -> Dict[str, Any]:
        """Plane statistics (page/edge counts etc.); empty dict on error."""
        try:
            return await self._store.stats()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("stats() failed: %s", exc)
            return {}

    async def aclose(self) -> None:
        """Release the underlying store (no-op for the SQLite backend)."""
        close = getattr(self._store, "close", None)
        if callable(close):
            try:
                maybe = close()
                if inspect.isawaitable(maybe):
                    await maybe
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Failed to close execution wiki: %s", exc)
