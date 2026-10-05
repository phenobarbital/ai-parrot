"""Remote-mode plumbing for the wikitoolkit CLI (FEAT-569)."""

from __future__ import annotations

import functools
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import click

from parrot.knowledge.wiki.project import WikiEffectiveConfig, WikiRemoteConfig, resolve_remote
from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError

if TYPE_CHECKING:
    from parrot.knowledge.wiki.store import BaseWikiStore
    from parrot.knowledge.wiki.sync import SyncReport
    from parrot.knowledge.wiki.tools import IngestBatchReport, SourceSlicePayload


class RemoteCliError(click.ClickException):
    """A remote failure surfaced to the shell with exit code 2."""

    exit_code = 2


def remote_or_none(path_: str | None) -> tuple[Path, WikiEffectiveConfig, WikiRemoteConfig | None]:
    """Resolve the repository configuration without opening a wiki store."""
    from parrot.knowledge.wiki.cli import _resolve_project_effective

    root, effective = _resolve_project_effective(path_)
    return root, effective, resolve_remote(effective.config)


def remote_client(remote: WikiRemoteConfig, *, by: str | None = None) -> RemoteWikiClient:
    """Build a remote client with the configured or locally derived actor."""
    from parrot.knowledge.wiki.cli import _authoring_identity

    try:
        return RemoteWikiClient(remote, actor=remote.actor or _authoring_identity(by))
    except RemoteWikiError as exc:
        raise RemoteCliError(str(exc)) from exc


async def _call(
    remote: WikiRemoteConfig,
    tool: str,
    arguments: dict[str, Any],
    *,
    by: str | None,
    text: bool,
) -> Any:
    client = remote_client(remote, by=by)
    try:
        async with client:
            if text:
                return await client.call_tool_text(tool, arguments)
            return await client.call_tool(tool, arguments)
    except RemoteWikiError as exc:
        raise RemoteCliError(str(exc)) from exc


def call_remote_text(
    remote: WikiRemoteConfig,
    tool: str,
    arguments: dict[str, Any],
    *,
    by: str | None = None,
) -> str:
    """Call a remote MCP tool and return its rendered text content."""
    from parrot.knowledge.wiki.cli import _run

    return _run(_call(remote, tool, arguments, by=by, text=True))


def call_remote(
    remote: WikiRemoteConfig,
    tool: str,
    arguments: dict[str, Any],
    *,
    by: str | None = None,
) -> dict[str, Any]:
    """Call a remote MCP tool and return its raw result envelope."""
    from parrot.knowledge.wiki.cli import _run

    return _run(_call(remote, tool, arguments, by=by, text=False))


def refuse_remote(command: str, hint: str = "") -> NoReturn:
    """Reject a local-only command while remote mode is active."""
    extra = f" — {hint}" if hint else ""
    raise click.UsageError(f"`wikitoolkit {command}` is not available in remote mode{extra}")


def remote_aware(
    *,
    proxied: bool,
    tool: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Resolve remote mode before a command body and refuse unsupported commands.

    The optional tool name is retained as command metadata for callers that
    need it; command implementations pass explicit arguments to the helpers.
    """

    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = click.get_current_context()
            ctx.ensure_object(dict)
            _root, _effective, remote = remote_or_none(kwargs.get("path_"))
            ctx.obj["remote"] = remote
            if remote is None:
                return func(*args, **kwargs)
            if kwargs.get("store_opt") or kwargs.get("backend_opt"):
                raise click.UsageError("--store/--backend cannot be combined with remote mode (remote is configured)")
            if not proxied:
                command = ctx.command_path.removeprefix("wiki ")
                refuse_remote(command)
            return func(*args, **kwargs)

        wrapper.__remote_tool__ = tool  # type: ignore[attr-defined]
        return wrapper

    return deco


def _tool_json(envelope: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON object a bulk tool returned inside its MCP content envelope.

    Raises:
        RemoteWikiError: The envelope is flagged ``isError`` (code ``tool_error``).
    """
    texts = [c.get("text", "") for c in envelope.get("content", []) if isinstance(c, dict)]
    if envelope.get("isError"):
        raise RemoteWikiError("tool_error", "\n".join(texts) or "remote tool error")
    if "structuredContent" in envelope and isinstance(envelope["structuredContent"], dict):
        return envelope["structuredContent"]
    try:
        data = json.loads(texts[0]) if texts else {}
    except ValueError as exc:
        raise RemoteWikiError("protocol", "remote tool returned a non-JSON payload") from exc
    return data if isinstance(data, dict) else {}


async def _collect_slices(store: BaseWikiStore, local_sources: dict[str, str]) -> list[SourceSlicePayload]:
    """Build one payload per ``{stable_source_id: local_source_id}`` entry.

    Pages are the local pages stamped with the local source id (the unit
    ``replace_source_slice`` replaces); edges are those whose ``src`` is one of
    those pages (outgoing edges belong to the slice, incoming ones to their
    own source); symbols come from ``symbols_for`` for the owning file. The
    local, machine-specific source id is rewritten to the stable one.
    """
    from parrot.knowledge.wiki.store import WikiPageRecord
    from parrot.knowledge.wiki.tools import SourceSlicePayload

    wanted = set(local_sources.values())
    stubs_by_source: dict[str, list[str]] = {}
    for stub in await store.list_pages(limit=10_000_000):
        if stub.get("source_id") in wanted:
            stubs_by_source.setdefault(stub["source_id"], []).append(stub["concept_id"])
    edges_by_src: dict[str, list[tuple[str, str, str]]] = {}
    for edge in await store.dump_edges():
        edges_by_src.setdefault(edge["src"], []).append((edge["src"], edge["dst"], edge["rel"]))

    slices: list[SourceSlicePayload] = []
    for stable_id, local_id in local_sources.items():
        pages: list[WikiPageRecord] = []
        for concept_id in stubs_by_source.get(local_id, []):
            full = await store.get_page(concept_id, include_body=True)
            if full is None:
                continue
            record = WikiPageRecord.model_validate(full)
            record.source_id = stable_id
            pages.append(record)
        edges = [edge for page in pages for edge in edges_by_src.get(page.concept_id, [])]
        symbols = []
        if stable_id.startswith("file:"):
            for symbol in await store.symbols_for(stable_id.removeprefix("file:")):
                symbols.append(symbol.model_copy(update={"source_id": stable_id}))
        slices.append(SourceSlicePayload(source_id=stable_id, pages=pages, edges=edges, symbols=symbols))
    return slices


async def _collect_slice(store: BaseWikiStore, rel_path: str) -> SourceSlicePayload:
    """Pages, edges and symbols the local plane holds for one file (``file:<rel>``)."""
    stable_id = f"file:{rel_path}"
    page = await store.get_page(stable_id, include_body=False)
    local_id = (page or {}).get("source_id")
    from parrot.knowledge.wiki.tools import SourceSlicePayload

    if not local_id:
        return SourceSlicePayload(source_id=stable_id)
    return (await _collect_slices(store, {stable_id: local_id}))[0]


def _slice_size(payload: SourceSlicePayload) -> int:
    return len(json.dumps(payload.model_dump(mode="json")).encode())


async def push_sources(
    client: RemoteWikiClient,
    store: BaseWikiStore,
    local_sources: dict[str, str],
    *,
    deleted_source_ids: tuple[str, ...] = (),
) -> IngestBatchReport:
    """Delta-push source slices: hash oracle, chunk (200 slices / 1 MiB), one retry per chunk."""
    from parrot.knowledge.wiki.tools import (
        HASHES_MAX_IDS,
        INGEST_MAX_BYTES,
        INGEST_MAX_SLICES,
        IngestBatchReport,
    )

    # Leave headroom for the JSON-RPC envelope and deleted ids: the server limit applies to the whole request.
    chunk_budget = INGEST_MAX_BYTES - 8192
    slices = await _collect_slices(store, local_sources)
    hashed_ids = [p.concept_id for s in slices for p in s.pages if p.content_hash]
    remote_hashes: dict[str, str | None] = {}
    for i in range(0, len(hashed_ids), HASHES_MAX_IDS):
        chunk_ids = hashed_ids[i : i + HASHES_MAX_IDS]
        try:
            result = _tool_json(await client.call_tool("wiki_page_hashes", {"concept_ids": chunk_ids}))
        except RemoteWikiError as exc:
            raise RemoteCliError(str(exc)) from exc
        remote_hashes.update(result.get("hashes", {}))

    def _unchanged(s: SourceSlicePayload) -> bool:
        hashed = [p for p in s.pages if p.content_hash]
        return bool(hashed) and all(remote_hashes.get(p.concept_id) == p.content_hash for p in hashed)

    report = IngestBatchReport()
    chunks: list[list[SourceSlicePayload]] = []
    current: list[SourceSlicePayload] = []
    current_bytes = 0
    for s in slices:
        if _unchanged(s):
            continue
        size = _slice_size(s)
        if size > chunk_budget:
            report.rejected.append(s.source_id)
            continue
        if current and (len(current) >= INGEST_MAX_SLICES or current_bytes + size > chunk_budget):
            chunks.append(current)
            current, current_bytes = [], 0
        current.append(s)
        current_bytes += size
    if current:
        chunks.append(current)

    deleted = list(deleted_source_ids)
    if deleted and not chunks:
        chunks.append([])
    for index, chunk in enumerate(chunks):
        deleted_part = deleted[:INGEST_MAX_SLICES] if index == 0 else []
        if index == 0:
            deleted = deleted[INGEST_MAX_SLICES:]
        arguments = {
            "slices": [s.model_dump(mode="json") for s in chunk],
            "deleted_source_ids": deleted_part,
            "batch_id": uuid.uuid4().hex,
        }
        last_error: RemoteWikiError | None = None
        for _attempt in range(2):
            try:
                outcome = _tool_json(await client.call_tool("wiki_ingest_batch", arguments))
                last_error = None
                break
            except RemoteWikiError as exc:
                if exc.code != "tool_error":
                    raise RemoteCliError(str(exc)) from exc
                last_error = exc
        if last_error is not None:
            failed = ", ".join(s.source_id for s in chunk) or ", ".join(deleted_part)
            raise RemoteCliError(f"remote ingest failed for: {failed} ({last_error})")
        for key in (
            "slices_applied",
            "slices_deleted",
            "pages_written",
            "edges_written",
            "symbols_written",
            "symbols_dropped",
        ):
            setattr(report, key, getattr(report, key) + int(outcome.get(key, 0)))
        report.rejected.extend(outcome.get("rejected", []))
    # Remaining deletions beyond the first chunk's capacity travel in extra calls.
    while deleted:
        part, deleted = deleted[:INGEST_MAX_SLICES], deleted[INGEST_MAX_SLICES:]
        try:
            outcome = _tool_json(
                await client.call_tool(
                    "wiki_ingest_batch",
                    {"slices": [], "deleted_source_ids": part, "batch_id": uuid.uuid4().hex},
                )
            )
        except RemoteWikiError as exc:
            raise RemoteCliError(f"remote ingest failed for: {', '.join(part)} ({exc})") from exc
        report.slices_deleted += int(outcome.get("slices_deleted", 0))
    return report


async def push_slices(
    client: RemoteWikiClient,
    store: BaseWikiStore,
    rel_paths: list[str],
    *,
    deleted_rel_paths: tuple[str, ...] = (),
) -> IngestBatchReport:
    """Delta-push changed files (``file:<rel>`` slices) through ``wiki_ingest_batch``."""
    local_sources: dict[str, str] = {}
    for rel in dict.fromkeys(rel_paths):
        page = await store.get_page(f"file:{rel}", include_body=False)
        if page and page.get("source_id"):
            local_sources[f"file:{rel}"] = page["source_id"]
    return await push_sources(
        client,
        store,
        local_sources,
        deleted_source_ids=tuple(f"file:{r}" for r in deleted_rel_paths),
    )


def _run_push(
    client: RemoteWikiClient,
    store: BaseWikiStore,
    rel_paths: list[str],
    deleted: tuple[str, ...] | list[str] = (),
    *,
    local_sources: dict[str, str] | None = None,
) -> IngestBatchReport:
    """Synchronous wrapper: open the client session and push (files or explicit sources)."""
    from parrot.knowledge.wiki.cli import _run

    async def _go() -> IngestBatchReport:
        try:
            async with client:
                if local_sources is not None:
                    return await push_sources(client, store, local_sources)
                return await push_slices(client, store, rel_paths, deleted_rel_paths=tuple(deleted))
        except RemoteWikiError as exc:
            raise RemoteCliError(str(exc)) from exc

    return _run(_go())


def echo_push_report(report: IngestBatchReport, url: str) -> None:
    """Print the aggregated push summary."""
    click.echo(
        f"Pushed {report.slices_applied} slices ({report.pages_written} pages, {report.symbols_written} symbols, "
        f"{report.slices_deleted} deleted, {len(report.rejected)} rejected) to {url}"
    )


async def sync_push_remote(client: RemoteWikiClient, local: BaseWikiStore) -> dict[str, Any]:
    """Send local memory pages and their asserted edges through ``wiki_sync_push``."""
    from parrot.knowledge.wiki.store import WikiPageRecord
    from parrot.knowledge.wiki.sync import _synced_memory_pages

    pages = [WikiPageRecord.model_validate(p) for p in await _synced_memory_pages(local)]
    ids = {p.concept_id for p in pages}
    # Edges touching a memory page are always asserted (same rule as sync._sync_edges).
    edges = [
        [e["src"], e["dst"], e["rel"], "asserted"]
        for e in await local.dump_edges()
        if e["src"] in ids or e["dst"] in ids
    ]
    try:
        async with client:
            envelope = await client.call_tool(
                "wiki_sync_push",
                {"pages": [p.model_dump(mode="json") for p in pages], "edges": edges},
            )
            return _tool_json(envelope)
    except RemoteWikiError as exc:
        raise RemoteCliError(str(exc)) from exc


class _PullStaging:
    """Read-only holder of pulled records that keeps ``updated_at`` verbatim.

    ``InMemoryWikiStore.upsert_pages`` re-stamps ``updated_at`` with "now",
    which would defeat the last-writer-wins comparison in ``_sync_records``;
    this duck-typed store implements only the three reads ``_sync_records``
    performs on its source.
    """

    def __init__(self) -> None:
        self.pages: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, str]] = []

    async def list_pages(
        self, category: str | None = None, limit: int = 100, origin: list[str] | None = None
    ) -> list[dict[str, Any]]:
        return [p for p in self.pages.values() if origin is None or p.get("origin") in origin][:limit]

    async def get_page(self, concept_id: str, include_body: bool = True) -> dict[str, Any] | None:
        return self.pages.get(concept_id)

    async def dump_edges(self) -> list[dict[str, str]]:
        return list(self.edges)


async def sync_pull_remote(
    client: RemoteWikiClient,
    local: BaseWikiStore,
    *,
    wiki_name: str,
    include_own: bool,
    dry_run: bool,
) -> SyncReport:
    """Page through ``wiki_sync_pull`` into a staging holder, then merge with last-writer-wins."""
    from parrot.knowledge.wiki.sync import _sync_records, default_local_identity

    skip = None if include_own else default_local_identity()
    staging = _PullStaging()
    cursor: str | None = None
    try:
        async with client:
            while True:
                arguments: dict[str, Any] = {"skip_asserted_by": skip}
                if cursor is not None:
                    arguments["cursor"] = cursor
                data = _tool_json(await client.call_tool("wiki_sync_pull", arguments))
                for page in data.get("pages", []):
                    staging.pages[page["concept_id"]] = page
                staging.edges.extend({"src": e[0], "dst": e[1], "rel": e[2]} for e in data.get("edges", []))
                cursor = data.get("next_cursor")
                if not cursor:
                    break
    except RemoteWikiError as exc:
        raise RemoteCliError(str(exc)) from exc
    report, selected = await _sync_records(
        source=staging,  # type: ignore[arg-type]
        destination=local,
        direction="pull",
        env=wiki_name,
        dry_run=dry_run,
        skip_asserted_by=skip,
    )
    if not dry_run and selected:
        edges_to_write = [
            (e["src"], e["dst"], e["rel"], "asserted")
            for e in staging.edges
            if e["src"] in selected or e["dst"] in selected
        ]
        if edges_to_write:
            await local.add_edges(edges_to_write)
    return report
