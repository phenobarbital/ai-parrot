"""HTTP handler to manage an agent's knowledge index (PageIndex / GraphIndex).

This handler exposes a REST surface to upload, edit, delete and query the
documents that feed an agent's **PageIndex** (hierarchical, vectorless ToC
tree) and/or **GraphIndex** (knowledge graph), and to test the agent's LLM via
``ask_stream`` over HTTP chunked transfer encoding.

Routes (registered in ``manager/manager.py``)::

    GET    /api/v1/agents/knowledge/{agent_id}            -> index status / list trees
    GET    /api/v1/agents/knowledge/{agent_id}/search     -> query the index (JSON)
    GET    /api/v1/agents/knowledge/{agent_id}/ask        -> ask_stream (chunked)
    PUT    /api/v1/agents/knowledge/{agent_id}            -> upload new files
    POST   /api/v1/agents/knowledge/{agent_id}            -> edit existing content
    DELETE /api/v1/agents/knowledge/{agent_id}            -> delete node / tree

Index selection: ``?index=pageindex|graphindex`` (default ``pageindex``).
Tree selection : ``?tree=<tree_name>`` (default ``pageindex``).

PageIndex supports the full file lifecycle. GraphIndex supports **query** and
**upload** (when the agent exposes a ``GraphIndexBuilder`` + ``TenantContext``);
per-file edit/delete return ``501 Not Implemented`` because the GraphIndex
toolkit has no document-level edit/delete primitives.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Tuple

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated

from parrot.models.responses import AIMessage

if TYPE_CHECKING:  # AbstractBot is used only for type hints; avoid the heavy import.
    from parrot.bots import AbstractBot


#: File extensions accepted for upload into a PageIndex tree.
_PDF_EXTS = {".pdf"}
_TEXT_EXTS = {".md", ".markdown", ".txt", ".text"}
_DOCX_EXTS = {".doc", ".docx"}


@is_authenticated()
class AgentKnowledgeHandler(BaseView):
    """Manage an agent's PageIndex / GraphIndex documents over REST."""

    _logger_name = "Parrot.AgentKnowledgeHandler"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------
    def _get_botmanager(self):
        """Return the bot manager from the application context."""
        try:
            return self.request.app["bot_manager"]
        except KeyError as exc:
            raise web.HTTPInternalServerError(
                reason="Bot manager not found in application."
            ) from exc

    async def _get_agent(self) -> AbstractBot:
        """Resolve the agent referenced by the ``{agent_id}`` path parameter."""
        bot_manager = self._get_botmanager()
        agent_id = self.request.match_info.get("agent_id")
        if not agent_id:
            raise web.HTTPBadRequest(reason="Missing agent_id in the request path.")
        agent = await bot_manager.get_bot(agent_id, request=self.request)
        if agent is None:
            raise web.HTTPNotFound(reason=f"Agent '{agent_id}' not found.")
        return agent

    def _index_kind(self) -> str:
        """Return the requested index kind (``pageindex`` or ``graphindex``)."""
        kind = (self.request.query.get("index") or "pageindex").lower()
        if kind not in ("pageindex", "graphindex"):
            raise web.HTTPBadRequest(
                reason="Invalid 'index' value. Use 'pageindex' or 'graphindex'."
            )
        return kind

    def _tree_name(self) -> str:
        """Return the target PageIndex tree name (default ``pageindex``)."""
        return self.request.query.get("tree") or "pageindex"

    def _require_pageindex(self, agent: AbstractBot):
        """Return the agent's PageIndex toolkit or raise 409."""
        if not agent.has_pageindex_tools or agent.pageindex_toolkit is None:
            raise web.HTTPConflict(
                reason=(
                    f"Agent '{agent.name}' has no PageIndex tools incorporated "
                    "(has_pageindex_tools is False)."
                )
            )
        return agent.pageindex_toolkit

    def _require_graphindex(self, agent: AbstractBot):
        """Return the agent's GraphIndex toolkit or raise 409."""
        if not agent.has_graphindex_tools or agent.graphindex_toolkit is None:
            raise web.HTTPConflict(
                reason=(
                    f"Agent '{agent.name}' has no GraphIndex tools incorporated "
                    "(has_graphindex_tools is False)."
                )
            )
        return agent.graphindex_toolkit

    # ------------------------------------------------------------------
    # GET — status / search / ask
    # ------------------------------------------------------------------
    async def get(self) -> web.StreamResponse:
        """Dispatch GET to status, ``/search`` (JSON) or ``/ask`` (chunked)."""
        action = (self.request.match_info.get("action") or "").lower()
        agent = await self._get_agent()
        if action == "ask":
            return await self._ask_stream(agent)
        if action == "search":
            return await self._search(agent)
        if action in ("", "status"):
            return await self._status(agent)
        raise web.HTTPNotFound(reason=f"Unknown knowledge action '{action}'.")

    async def _status(self, agent: AbstractBot) -> web.Response:
        """Report index capabilities and (for PageIndex) the available trees."""
        payload: dict[str, Any] = {
            "agent": agent.name,
            "has_pageindex_tools": agent.has_pageindex_tools,
            "has_graphindex_tools": agent.has_graphindex_tools,
            "trees": [],
        }
        if agent.has_pageindex_tools and agent.pageindex_toolkit is not None:
            try:
                payload["trees"] = await agent.pageindex_toolkit.list_trees()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning("Could not list PageIndex trees: %s", exc)
        return self.json_response(payload)

    async def _search(self, agent: AbstractBot) -> web.Response:
        """Query the selected index and return ranked results as JSON."""
        query = self.request.query.get("q") or self.request.query.get("query")
        if not query:
            raise web.HTTPBadRequest(reason="Missing 'q' query parameter.")
        top_k = int(self.request.query.get("top_k", 10))
        kind = self._index_kind()

        if kind == "pageindex":
            toolkit = self._require_pageindex(agent)
            tree = self._tree_name()
            if self.request.query.get("retrieve", "").lower() in ("1", "true", "yes"):
                text = await toolkit.retrieve(tree_name=tree, query=query, top_k=top_k)
                return self.json_response(
                    {"index": kind, "tree": tree, "query": query, "text": text}
                )
            results = await toolkit.search(tree_name=tree, query=query, top_k=top_k)
            return self.json_response(
                {"index": kind, "tree": tree, "query": query, "results": results}
            )

        # GraphIndex query
        toolkit = self._require_graphindex(agent)
        results = await toolkit.search_hybrid(query=query, top_k=top_k)
        return self.json_response({"index": kind, "query": query, "results": results})

    async def _ask_stream(self, agent: AbstractBot) -> web.StreamResponse:
        """Stream the agent's answer using HTTP chunked transfer encoding."""
        query = self.request.query.get("q") or self.request.query.get("query")
        if not query:
            raise web.HTTPBadRequest(reason="Missing 'q' query parameter.")
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Transfer-Encoding": "chunked",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(self.request)
        try:
            async for chunk in agent.ask_stream(question=query):
                if isinstance(chunk, AIMessage):
                    # Final metadata element — not part of the text stream.
                    continue
                if not chunk:
                    continue
                await response.write(str(chunk).encode("utf-8"))
                await response.drain()
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Error during ask_stream: %s", exc)
            await response.write(f"\n[error] {exc}".encode("utf-8"))
        finally:
            await response.write_eof()
        return response

    # ------------------------------------------------------------------
    # PUT — upload new files
    # ------------------------------------------------------------------
    async def put(self) -> web.Response:
        """Upload one or more files into the agent's index."""
        agent = await self._get_agent()
        kind = self._index_kind()
        files, _form = await self._read_uploads()

        if kind == "graphindex":
            return await self._graph_ingest(agent, files)

        toolkit = self._require_pageindex(agent)
        tree = self._tree_name()
        await self._ensure_tree(toolkit, tree)

        imported: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        try:
            for f in files:
                path = Path(f["path"])
                ext = path.suffix.lower()
                try:
                    if ext in _PDF_EXTS:
                        result = await toolkit.import_pdf(
                            tree_name=tree, pdf_path=str(path), with_summaries=True
                        )
                    elif ext in _TEXT_EXTS:
                        result = await toolkit.import_file(
                            tree_name=tree, file_path=str(path)
                        )
                    elif ext in _DOCX_EXTS:
                        markdown = self._docx_to_markdown(path)
                        result = await toolkit.insert_markdown(
                            tree_name=tree, markdown=markdown, doc_name=f["filename"]
                        )
                    else:
                        skipped.append(
                            {"filename": f["filename"], "reason": f"unsupported extension '{ext}'"}
                        )
                        continue
                    imported.append(
                        {
                            "filename": f["filename"],
                            "new_node_ids": result.get("new_node_ids"),
                            "doc_name": result.get("doc_name"),
                        }
                    )
                except Exception as exc:
                    self.logger.error("Import failed for %s: %s", f["filename"], exc)
                    skipped.append({"filename": f["filename"], "reason": str(exc)})
        finally:
            self._cleanup(files)

        return self.json_response(
            {"index": kind, "tree": tree, "imported": imported, "skipped": skipped},
            status=201,
        )

    async def _graph_ingest(self, agent: AbstractBot, files: list[dict]) -> web.Response:
        """Ingest uploaded files into the GraphIndex via the agent's builder."""
        self._require_graphindex(agent)
        builder = agent.graphindex_builder
        ctx = getattr(agent, "tenant_context", None) or getattr(
            builder, "default_context", None
        )
        if builder is None or ctx is None:
            self._cleanup(files)
            raise web.HTTPNotImplemented(
                reason=(
                    "GraphIndex upload requires the agent to expose a "
                    "GraphIndexBuilder and a TenantContext."
                )
            )
        ingested: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        try:
            for f in files:
                try:
                    result = await builder.ingest_document(uri=f["path"], ctx=ctx)
                    ingested.append(
                        {"filename": f["filename"], "result": getattr(result, "__dict__", str(result))}
                    )
                except Exception as exc:
                    self.logger.error("Graph ingest failed for %s: %s", f["filename"], exc)
                    skipped.append({"filename": f["filename"], "reason": str(exc)})
        finally:
            self._cleanup(files)
        return self.json_response(
            {"index": "graphindex", "ingested": ingested, "skipped": skipped}, status=201
        )

    # ------------------------------------------------------------------
    # POST — edit existing content
    # ------------------------------------------------------------------
    async def post(self) -> web.Response:
        """Edit existing content in the agent's index."""
        agent = await self._get_agent()
        kind = self._index_kind()
        if kind == "graphindex":
            raise web.HTTPNotImplemented(
                reason="GraphIndex per-node editing is not supported via this endpoint."
            )
        toolkit = self._require_pageindex(agent)
        try:
            body = await self.request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(reason="Expected a JSON body.") from exc

        tree = body.get("tree") or self._tree_name()
        node_id = body.get("node_id")
        if not node_id:
            raise web.HTTPBadRequest(reason="Missing 'node_id' in the body.")

        updated: dict[str, Any] = {}
        if "body" in body and body["body"] is not None:
            await toolkit.update_node_content(
                tree_name=tree, node_id=node_id, body=body["body"]
            )
            updated["content"] = True
        meta_fields = {
            k: body[k]
            for k in ("title", "summary", "categories", "metadata")
            if k in body and body[k] is not None
        }
        if meta_fields:
            await toolkit.update_node(tree_name=tree, node_id=node_id, **meta_fields)
            updated["metadata"] = list(meta_fields.keys())

        if not updated:
            raise web.HTTPBadRequest(
                reason="Nothing to update. Provide 'body' and/or metadata fields."
            )
        return self.json_response(
            {"index": kind, "tree": tree, "node_id": node_id, "updated": updated}
        )

    # ------------------------------------------------------------------
    # DELETE — remove node or whole tree
    # ------------------------------------------------------------------
    async def delete(self) -> web.Response:
        """Delete a node (``?node_id=``) or a whole tree from the index."""
        agent = await self._get_agent()
        kind = self._index_kind()
        if kind == "graphindex":
            raise web.HTTPNotImplemented(
                reason="GraphIndex document deletion is not supported via this endpoint."
            )
        toolkit = self._require_pageindex(agent)
        tree = self._tree_name()
        node_id = self.request.query.get("node_id")
        if node_id:
            result = await toolkit.delete_node(tree_name=tree, node_id=node_id)
            return self.json_response(
                {"index": kind, "tree": tree, "node_id": node_id, "deleted": result}
            )
        result = await toolkit.delete_tree(tree_name=tree)
        return self.json_response({"index": kind, "tree": tree, "deleted": result})

    # ------------------------------------------------------------------
    # Upload / conversion utilities
    # ------------------------------------------------------------------
    async def _read_uploads(self) -> Tuple[list[dict], dict]:
        """Parse a ``multipart/form-data`` request, streaming files to disk."""
        content_type = self.request.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise web.HTTPUnsupportedMediaType(
                reason="Invalid Content-Type. Use multipart/form-data."
            )
        reader = await self.request.multipart()
        temp_dir = tempfile.mkdtemp(prefix="agent_knowledge_")
        files: list[dict] = []
        form: dict[str, str] = {}
        async for part in reader:
            if part.filename:
                dest = Path(temp_dir) / Path(part.filename).name
                with dest.open("wb") as fh:
                    while True:
                        chunk = await part.read_chunk(65536)
                        if not chunk:
                            break
                        fh.write(chunk)
                files.append(
                    {
                        "filename": part.filename,
                        "path": str(dest),
                        "content_type": part.headers.get("Content-Type", ""),
                        "size": dest.stat().st_size,
                    }
                )
            elif part.name:
                form[part.name] = await part.text()
        if not files:
            raise web.HTTPBadRequest(reason="No files found in the upload.")
        return files, form

    @staticmethod
    def _docx_to_markdown(path: Path) -> str:
        """Convert a DOCX file to markdown using the MSWordLoader helper."""
        from parrot_loaders.docx import MSWordLoader  # lazy: optional dependency

        loader = MSWordLoader(str(path))
        return loader.docx_to_markdown(str(path))

    @staticmethod
    async def _ensure_tree(toolkit: Any, tree: str) -> None:
        """Create the PageIndex tree if it does not already exist."""
        existing = await toolkit.list_trees()
        if tree not in existing:
            await toolkit.create_tree(tree_name=tree, doc_name=tree)

    def _cleanup(self, files: list[dict]) -> None:
        """Best-effort removal of temporary uploaded files and their dir."""
        dirs: set[Path] = set()
        for f in files:
            try:
                p = Path(f["path"])
                dirs.add(p.parent)
                p.unlink(missing_ok=True)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Temp cleanup failed for %s: %s", f.get("path"), exc)
        for d in dirs:
            try:
                d.rmdir()
            except OSError:
                pass
