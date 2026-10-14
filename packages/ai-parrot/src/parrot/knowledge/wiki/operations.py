"""Framework-free wiki operations shared by the framework tools and the SDK MCP transport (FEAT-540 M3).

Each ``op_*`` coroutine holds the business logic that used to live inside the matching
``AbstractTool`` ``_execute`` body in :mod:`parrot.knowledge.wiki.tools`. The tools are now thin adapters
that map an :class:`OperationResult` onto a ``ToolResult``. This module must stay free of the framework tool layer.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, date as _date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from parrot.knowledge.lint import LintOptions, LintRunner
from parrot.knowledge.lint.routing import FindingRouter
from parrot.knowledge.wiki.actor import current_actor
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS, pack_results
from parrot.knowledge.wiki.decisions.models import ADR_CATEGORY, ADR_MANAGED_PAGE
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens

if TYPE_CHECKING:
    from parrot.knowledge.wiki.project import WikiProjectConfig

logger = logging.getLogger(__name__)


class OperationResult(BaseModel):
    """Transport-neutral outcome of one wiki operation.

    Attributes:
        text: Human-readable text (the query output, or the error message when ``is_error``).
        data: Structured payload for operations that return a mapping.
        is_error: Whether the operation failed (``text`` then carries the message).
    """

    text: str = ""
    data: dict[str, Any] | None = None
    is_error: bool = False


def _scoped_store(store: BaseWikiStore, namespace: str | None) -> BaseWikiStore:
    """Narrow a (possibly federated) store to one namespace selector.

    A plain store has no namespaces, so the selector is a no-op there —
    that keeps every existing caller (and the ``AsyncMock`` stores the
    tool tests use) working untouched.

    Args:
        store: The store the tool holds.
        namespace: The ``namespace`` tool argument.

    Returns:
        The store to read from.

    Raises:
        KeyError: When a federated store does not serve ``namespace``.
    """
    if not namespace:
        return store
    from parrot.knowledge.wiki.federation import FederatedWikiStore

    if not isinstance(store, FederatedWikiStore):
        return store
    return store.scoped(namespace)


def _reject_foreign_id(store: BaseWikiStore, page_id: str) -> str | None:
    """Explain why a write cannot target ``page_id``, or ``None`` if it can.

    Writes through these tools always land on the local plane; a
    namespaced page belongs to somebody else's wiki, which is reachable
    only through the CLI's explicit ``--ns`` write path (FEAT-450, U2).
    Detecting that up front keeps the tools returning structured errors
    instead of letting the store's ``ValueError`` escape mid-write.

    Args:
        store: The store the tool holds.
        page_id: The page id supplied by the caller.

    Returns:
        An error message, or ``None`` when the id is local.
    """
    from parrot.knowledge.wiki.context import split_namespaced_id

    namespace, _local = split_namespaced_id(page_id)
    if namespace is None:
        return None
    if namespace not in getattr(store, "namespaces", {}):
        return f"Unknown namespace {namespace!r} in page id {page_id!r}."
    return (
        f"Page {page_id!r} belongs to namespace {namespace!r}, which is "
        "read-only here. Writes to a namespace go through the CLI: "
        f"`wikitoolkit <command> --ns {namespace}`."
    )


def _reject_managed_page(page: dict[str, Any] | None, page_id: str) -> str | None:
    """Explain why a generic write cannot target ``page_id``, or ``None``.

    ADR pages (FEAT-578) hold a canonical JSON envelope that IS the decision
    record, including its audit history. Appending prose to that body would
    make the record undecodable and silently destroy review history, so the
    generic authoring surfaces refuse them; edits go through the typed
    review surface (``wikitoolkit adr review``).

    Args:
        page: The stored row, or ``None`` when the page does not exist yet.
        page_id: The id the caller asked to write.

    Returns:
        An error message, or ``None`` when the write may proceed.
    """
    if page is not None:
        if page.get("category") == ADR_CATEGORY:
            return (
                f"Page {page_id!r} is a managed ADR record ({ADR_MANAGED_PAGE}); generic "
                "note/update writes are refused to protect its review history. Edit it "
                "through the typed review surface (`wikitoolkit adr review`)."
            )
        return None
    from parrot.knowledge.wiki.context import split_namespaced_id

    _namespace, local = split_namespaced_id(page_id)
    if local.startswith("adr:"):
        return f"Page {page_id!r} would be a managed ADR record ({ADR_MANAGED_PAGE}); generic writes are refused."
    return None


_LEDGER_KIND_PREFIXES = ("issue:", "task:", "spec:", "insight:")


def _qualify_ledger_target(target: str) -> str:
    """Foreign-qualify a provenance target that names a ledger kind.

    Ledger kinds (``issue:``, ``task:``, ``spec:``, ``insight:``) live in
    the ledger's overlay namespace (FEAT-566), not this ``wiki.db`` plane —
    an edge pointing at one must carry the ``ledger::`` qualifier so
    :meth:`~parrot.knowledge.wiki.federation.FederatedWikiStore._assert_local_or_foreign_destination`
    stores it verbatim instead of mistaking it for a local page id.
    Already-qualified ids (containing ``::``) and code-plane targets
    (``sym:``, ``file:``, ...) pass through unchanged.

    Args:
        target: Raw provenance target, e.g. ``"task:TASK-3200"``.

    Returns:
        The target, foreign-qualified when it names a ledger kind.
    """
    if "::" in target:
        return target
    if target.startswith(_LEDGER_KIND_PREFIXES):
        return f"ledger::{target}"
    return target


def _unknown_namespace_error(store: BaseWikiStore, namespace: str) -> str:
    """Message for a ``namespace`` argument the store does not serve."""
    known = ", ".join(sorted(getattr(store, "namespaces", {}))) or "(none)"
    return f"Unknown namespace {namespace!r}. Known: {known} " "(plus 'all', 'local')."


#: search_fts() over-fetch multiplier for wiki_query (FEAT-498): 3x
#: search_fts's own default limit (10), so filtering out sym: stubs by
#: default still leaves a full page of non-symbol results.
_QUERY_FETCH_LIMIT = 30

#: Shared description of the optional ``namespace`` argument (FEAT-450).
_NAMESPACE_DESC = (
    "Federated namespace to read: a namespace name, 'all' to broadcast, "
    "'local' for this repo's own wiki. Omit for the default routing "
    "(broadcast when namespaces are configured)."
)


class WikiQueryInput(BaseModel):
    question: str = Field(..., description="Search question for the knowledge graph")
    budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, description="Token budget for results")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)
    include_symbols: bool = Field(
        default=False,
        description=(
            "Include sym: (function/class/method) stubs in results "
            "(FEAT-498). Off by default — use wiki_symbol_lookup for "
            "symbol-specific search; set True to see symbols mixed in "
            "with files/concepts here."
        ),
    )


class WikiPageInput(BaseModel):
    page_id: str = Field(
        ...,
        description=("Page ID from wiki_query results; may carry a namespace " "prefix (ns::file:a.py)"),
    )
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class WikiRelatedInput(BaseModel):
    page_id: str = Field(
        ...,
        description=("Page ID to find related pages for; may carry a namespace " "prefix (ns::dir:pkg)"),
    )
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class WikiRememberInput(BaseModel):
    fact: str = Field(..., description="Knowledge to save")
    category: str = Field(default="note", description="note|decision|lesson|concept")
    title: str | None = Field(default=None, description="Short title")
    link_page_id: str | None = Field(default=None, description="Page to link to")
    rel: str | None = Field(default="references", description="Relation type")
    derived_from: str | None = Field(default=None, description="Originating task, review, or spec id")
    about: list[str] | None = Field(default=None, description="Target symbol or file ids")


class WikiNoteInput(BaseModel):
    page_id: str = Field(..., description="Page to append note to")
    text: str = Field(..., description="Note text")


class VaultIngestInput(BaseModel):
    vault_path: str | None = Field(
        default=None,
        description=(
            "Obsidian vault directory (absolute or project-relative). "
            "Omit to use the project's configured/auto-detected vault."
        ),
    )
    force: bool = Field(
        default=False,
        description="Re-ingest every note, ignoring staleness tracking.",
    )


class WikiStatusInput(BaseModel):
    pass


class WikiLintInput(BaseModel):
    """Arguments for wiki_lint."""

    rules: list[str] | None = Field(default=None, description="Rule ids or packs to run (default: all deterministic).")
    skip: list[str] = Field(default_factory=list, description="Rule ids to skip.")
    fix: bool = Field(default=False, description="Apply safe, idempotent fixes (never deletes).")
    llm: bool = Field(default=False, description="Run the opt-in LLM contradiction pass.")


class _StorageDirConfig:
    """Minimal config exposing the absolute wiki storage dir to the lint runner."""

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir
        self.wiki_name = ""


class WikiStandupInput(BaseModel):
    """Explicit brief options; persistence and model calls are opt-in over MCP."""

    period: Literal["day", "week", "month"] = Field(default="day", description="Brief period.")
    date: str | None = Field(default=None, description="Anchor date (YYYY-MM-DD); default today.")
    team: bool = Field(default=False, description="Include team items, not only yours.")
    horizon_days: int | None = Field(default=None, description="Meeting horizon in days (1-90).")
    language: Literal["en", "es"] | None = Field(default=None, description="Brief language.")
    store: bool = Field(default=False, description="Persist the brief as a wiki page on the local plane.")
    write_file: bool = Field(default=False, description="Also write the brief Markdown file.")
    use_llm: bool = Field(default=False, description="Allow a model call to summarise the plate.")



def _error(message: str) -> OperationResult:
    """Build a failed :class:`OperationResult` carrying ``message``."""
    return OperationResult(text=message, is_error=True)


async def op_query(store: BaseWikiStore, params: WikiQueryInput, **context: Any) -> OperationResult:
    """wiki_query — ranked page stubs for ``params.question``.

    Args:
        store: The wiki store (possibly federated).
        params: Validated query arguments.
        **context: Unused; accepted for a uniform operation signature.

    Returns:
        An :class:`OperationResult` whose ``text`` is the packed result text, or the
        unknown-namespace message with ``is_error`` unset (the tool returned it as plain text).
    """
    try:
        scoped = _scoped_store(store, params.namespace)
    except KeyError:
        return OperationResult(text=_unknown_namespace_error(store, str(params.namespace)))
    # FEAT-498: sym: pages share the pages_fts index, so a plain
    # search_fts() would mix them into every wiki_query result.
    # Over-fetch (limit*3) to compensate for the ones dropped, so a
    # question with few non-symbol hits doesn't come back thin.
    results = await scoped.search_fts(params.question, limit=_QUERY_FETCH_LIMIT)
    if not params.include_symbols:
        results = [r for r in results if r.get("category") != "symbol"]
    packed = pack_results(results, budget_tokens=params.budget_tokens)
    return OperationResult(text=packed.text)


async def op_page(store: BaseWikiStore, params: WikiPageInput, **context: Any) -> OperationResult:
    """wiki_page — read one full page by id.

    Args:
        store: The wiki store (possibly federated).
        params: Validated page arguments.
        **context: Unused.

    Returns:
        ``data`` is the page mapping; an error result when the namespace or page is unknown.
    """
    try:
        scoped = _scoped_store(store, params.namespace)
    except KeyError:
        return _error(_unknown_namespace_error(store, str(params.namespace)))
    page = await scoped.get_page(params.page_id, include_body=True)
    if page is None:
        return _error(f"Page not found: {params.page_id}")
    return OperationResult(text="", data=page)


async def op_related(store: BaseWikiStore, params: WikiRelatedInput, **context: Any) -> OperationResult:
    """wiki_related — neighbours of a page along typed edges.

    Args:
        store: The wiki store (possibly federated).
        params: Validated related arguments.
        **context: Unused.

    Returns:
        ``data`` is ``{"neighbors": [...]}``; an error result for an unknown namespace.
    """
    try:
        scoped = _scoped_store(store, params.namespace)
    except KeyError:
        return _error(_unknown_namespace_error(store, str(params.namespace)))
    neighbors = await scoped.neighbors(params.page_id)
    # Wrapped under a key (not a bare list) so the adapter's JSON
    # encoding path (dict → json.dumps) applies to this result too.
    return OperationResult(text="", data={"neighbors": neighbors})


async def op_remember(store: BaseWikiStore, params: WikiRememberInput, **context: Any) -> OperationResult:
    """wiki_remember — save durable knowledge as a ``mem-`` page plus provenance edges.

    Args:
        store: The wiki store.
        params: Validated remember arguments.
        **context: ``storage_dir`` (``Path | None``) enabling the audit-trail log.

    Returns:
        ``data`` carries ``page_id``, ``title``, ``category`` and ``linked``; an error result
        when the link target is foreign or the id collides with a managed ADR page.
    """
    storage_dir: Path | None = context.get("storage_dir")
    # Validate the link target BEFORE the first write: a namespaced
    # id would otherwise fail at add_edges, leaving the memory page
    # written and the call reported as an error.
    if params.link_page_id:
        refusal = _reject_foreign_id(store, params.link_page_id)
        if refusal:
            return _error(refusal)

    fact = params.fact
    category = params.category
    # Deterministic id from title+category (mirrors cli.py:remember —
    # re-remembering the same thing updates rather than duplicates).
    resolved_title = (params.title or fact.strip().splitlines()[0][:80]).strip()
    page_id = "mem-" + hashlib.sha1(f"{resolved_title}::{category}".encode()).hexdigest()[:12]

    # A deterministic id could in principle collide with a page that
    # already carries the managed ADR category — guard the same way
    # note does, rather than trusting the "mem-" prefix.
    existing = await store.get_page(page_id, include_body=False)
    managed = _reject_managed_page(existing, page_id)
    if managed:
        return _error(managed)

    await store.upsert_pages(
        [
            WikiPageRecord(
                concept_id=page_id,
                node_id=page_id,
                title=resolved_title,
                category=category,
                summary=fact[:300],
                body=fact,
                token_count=estimate_tokens(fact),
                origin="memory",
                asserted_by=current_actor(),
            )
        ]
    )

    edges = []
    linked = False
    if params.link_page_id:
        edges.append((page_id, params.link_page_id, params.rel or "references", "asserted"))
        linked = True

    # Add provenance edges. A target naming a ledger kind (task:, spec:,
    # issue:, insight:) is foreign to this wiki.db plane and must be
    # qualified so `_assert_local_or_foreign_destination` (federation.py)
    # stores it verbatim instead of treating it as a local reference;
    # code-plane targets (sym:, file:, ...) stay unqualified.
    if params.derived_from:
        edges.append((page_id, _qualify_ledger_target(params.derived_from), "derived-from", "asserted"))

    for target in params.about or []:
        edges.append((page_id, _qualify_ledger_target(target), "about", "asserted"))

    if edges:
        await store.add_edges(edges)

    if storage_dir is not None:
        # The store write above already succeeded — a failure logging
        # to the audit trail must not turn a successful remember into
        # a reported tool error (this call is otherwise unguarded, same
        # as cli.py's remember command).
        try:
            WikiBookkeeper().log_operation(
                storage_dir,
                "REMEMBER",
                f"page_id: {page_id}, title: {resolved_title!r}, " f"category: {category}, by: {current_actor()}",
            )
        except OSError as exc:
            logger.warning("Failed to log REMEMBER to wiki audit trail: %s", exc)

    return OperationResult(
        text="",
        data={
            "page_id": page_id,
            "title": resolved_title,
            "category": category,
            "linked": linked,
        },
    )


async def op_note(store: BaseWikiStore, params: WikiNoteInput, **context: Any) -> OperationResult:
    """wiki_note — append a dated note to an existing page.

    Args:
        store: The wiki store.
        params: Validated note arguments.
        **context: ``storage_dir`` (``Path | None``) enabling the audit-trail log.

    Returns:
        ``data`` is ``{"page_id", "status": "noted"}``; an error result for a managed, missing
        or foreign page.
    """
    storage_dir: Path | None = context.get("storage_dir")
    page_id = params.page_id
    # Read-modify-write pattern (mirrors cli.py:1741-1790) — there is
    # no store.add_note(); notes are appended to the body in-process.
    page = await store.get_page(page_id, include_body=True)
    # Checked BEFORE the not-found branch: a nonexistent "adr:..." id
    # must also be refused, closing the create-then-corrupt path — the
    # category check above only protects a page that already exists.
    managed = _reject_managed_page(page, page_id)
    if managed:
        return _error(managed)
    if page is None:
        return _error(f"Page not found: {page_id}")
    # A federated read returns the page with its id QUALIFIED; writing
    # that straight back would be a write into a foreign namespace.
    refusal = _reject_foreign_id(store, str(page["concept_id"]))
    if refusal:
        return _error(refusal)

    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    body = str(page.get("body") or "")
    body += f"\n\n> **Note ({stamp}, {current_actor()}):** {params.text}"

    await store.upsert_pages(
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
                asserted_by=current_actor(),
            )
        ]
    )

    if storage_dir is not None:
        # Same rationale as op_remember — an audit-log failure
        # must not mask the note that was already saved successfully.
        try:
            WikiBookkeeper().log_operation(
                storage_dir,
                "NOTE",
                f"page_id: {page['concept_id']}, by: {current_actor()}",
            )
        except OSError as exc:
            logger.warning("Failed to log NOTE to wiki audit trail: %s", exc)

    return OperationResult(text="", data={"page_id": page["concept_id"], "status": "noted"})


async def op_status(store: BaseWikiStore, params: WikiStatusInput | None = None, **context: Any) -> OperationResult:
    """wiki_status — knowledge graph health statistics.

    Args:
        store: The wiki store.
        params: Unused (the tool takes no arguments).
        **context: Unused.

    Returns:
        ``data`` is the store ``stats()`` mapping.
    """
    stats = await store.stats()
    return OperationResult(text="", data=stats)


async def op_lint(store: BaseWikiStore, params: WikiLintInput, **context: Any) -> OperationResult:
    """wiki_lint — run the lint runner and return a compact summary.

    Args:
        store: The wiki store.
        params: Validated lint arguments.
        **context: ``storage_dir`` (``Path | None``) locating the wiki storage and report dir.

    Returns:
        ``data`` carries ``counts``, ``fixed``, ``top`` and ``report_dir``.
    """
    storage_dir: Path | None = context.get("storage_dir")
    report_dir = storage_dir / "lint" if storage_dir is not None else None
    report = await LintRunner(
        store,
        root=storage_dir.parent if storage_dir is not None else None,
        config=_StorageDirConfig(storage_dir) if storage_dir is not None else None,
        router=FindingRouter(store, report_dir=report_dir),
    ).run(
        LintOptions(
            rules=params.rules, skip=params.skip or [], fix=params.fix, llm=params.llm, report_dir=report_dir
        )
    )
    return OperationResult(
        text="",
        data={
            "counts": report.counts,
            "fixed": len(report.fixed),
            "top": [finding.model_dump() for finding in report.findings[:20]],
            "report_dir": str(report_dir) if report_dir is not None else None,
        },
    )


async def op_standup(store: BaseWikiStore, params: dict[str, Any], **context: Any) -> OperationResult:
    """wiki_standup — render a brief; writes only when explicitly requested.

    Args:
        store: The wiki store (read through only for read-only runs).
        params: Raw tool arguments; validated into :class:`WikiStandupInput` here so invalid
            input becomes a structured error.
        **context: ``root`` (``Path``) and ``config`` (:class:`WikiProjectConfig`).

    Returns:
        ``data`` carries ``markdown``, ``brief_id``, ``written_page``, ``written_file`` and
        ``diagnostics``; an error result for invalid input or a store/pipeline failure.
    """
    from parrot.knowledge.wiki.standup.pipeline import StandupOptions, StandupStoreError, run
    from parrot.knowledge.wiki.project import WikiEffectiveConfig, resolve_wiki_env
    from parrot.knowledge.wiki.standup.render import render_markdown

    root: Path = context["root"]
    config: WikiProjectConfig = context["config"]
    try:
        parsed = WikiStandupInput(**params)
        anchor = _date.fromisoformat(parsed.date) if parsed.date else None
        horizon = parsed.horizon_days
        if horizon is not None and not 1 <= horizon <= 90:
            raise ValueError("horizon_days must be between 1 and 90")
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        return _error(f"Invalid wiki_standup input: {exc}")

    writing = parsed.store or parsed.write_file
    options = StandupOptions(
        period=parsed.period,
        anchor=anchor,
        horizon_days=horizon,
        team=parsed.team,
        language=parsed.language,
        use_llm=parsed.use_llm,
        write_page=parsed.store,
        write_file=parsed.write_file,
    )
    # Writes must land on the true local plane resolved from root/config, never on a
    # (possibly federated / namespace-scoped) facade; a read-only run reads through the given store.
    try:
        effective = WikiEffectiveConfig(config=config, env=resolve_wiki_env())
        doc = await run(root, options, store=None if writing else store, effective=effective)
    except StandupStoreError as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001 -- surfaced as a structured tool error
        logger.warning("wiki_standup failed: %s", exc)
        return _error(str(exc))
    return OperationResult(
        text="",
        data={
            "markdown": render_markdown(doc, doc.language),
            "brief_id": doc.window.brief_id,
            "written_page": doc.written_page,
            "written_file": doc.written_file,
            "diagnostics": list(doc.diagnostics),
        },
    )
