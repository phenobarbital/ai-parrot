"""Shared deterministic brief orchestration for CLI and MCP."""

import asyncio
import importlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from parrot.knowledge.wiki.entities import STATUS_BY_TYPE
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle, resolve_namespaces
from parrot.knowledge.wiki.identity import authoring_identity
from parrot.knowledge.wiki.jira_sync import load_sync_state, resolve_issues_dir
from parrot.knowledge.wiki.project import (
    StandupConfig,
    WikiEffectiveConfig,
    WikiProjectConfig,
    load_effective_config,
    parrot_home,
    resolve_vault_dir,
    sqlite_policy_from_config,
)
from parrot.knowledge.wiki.standup import identity as identity_module
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.delta import diff, previous_brief
from parrot.knowledge.wiki.standup.grouping import group_items
from parrot.knowledge.wiki.standup.identity import StandupIdentity, resolve_identity
from parrot.knowledge.wiki.standup.models import BriefDocument, BriefItem, HygieneReport, Period, PeriodWindow
from parrot.knowledge.wiki.standup.periods import window as compute_window
from parrot.knowledge.wiki.standup.render import render_markdown
from parrot.knowledge.wiki.standup.writer import write
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, create_wiki_store

logger = logging.getLogger(__name__)

_COLLECTOR_MODULES = ("entities", "jira", "ledger", "tasks", "decisions", "memories")
_LINT_TIME_KEYS = ("generated_at", "timestamp", "created_at", "finished_at")


class StandupOptions(BaseModel):
    """Explicit run options; callers control every persistence side effect."""

    period: Period = "day"
    anchor: date | None = None
    horizon_days: int | None = None
    team: bool = False
    me: str | None = None
    language: Literal["en", "es"] | None = None
    use_llm: bool = True
    write_page: bool = True
    write_file: bool = True
    out_dir: Path | None = None
    namespaces: str | None = None
    now: datetime | None = None


class StandupStoreError(RuntimeError):
    """Raised when the local wiki plane cannot be opened; the message says how to fix it."""


def _effective_cfg(base: StandupConfig, options: StandupOptions) -> StandupConfig:
    """Return a validated per-run copy so overrides never mutate shared config."""
    data = base.model_dump()
    if options.horizon_days is not None:
        data["horizon_days"] = options.horizon_days
    if options.language is not None:
        data["default_language"] = options.language
    return StandupConfig.model_validate(data)


def _resolve_anchor(options: StandupOptions, cfg: StandupConfig) -> date:
    """Resolve the anchor date: explicit date, else the clock in the configured timezone."""
    if options.anchor is not None:
        return options.anchor
    tz = ZoneInfo(cfg.timezone) if cfg.timezone else None
    now = options.now or datetime.now(tz)
    if now.tzinfo is None:
        return now.date()
    return now.astimezone(tz).date()


async def _close(target: object) -> None:
    """Best-effort close of an owned store; never raises."""
    closer: Callable[[], Awaitable[None] | None] | None = getattr(target, "close", None)
    if closer is None:
        return
    try:
        result = closer()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # noqa: BLE001 -- cleanup must not mask the brief
        logger.debug("Closing %s failed (%s)", type(target).__name__, type(exc).__name__)


async def _open_local(root: Path, config: WikiProjectConfig, *, writable: bool) -> BaseWikiStore:
    """Open the local plane; a read-only run never creates or migrates it."""
    storage = config.storage_path(root)
    try:
        if config.backend == "sqlite":
            if not writable:
                if not config.db_path(root).exists():
                    raise StandupStoreError(f"Wiki not built yet for {root}. Run `wikitoolkit build` first.")
                return SQLiteWikiStore(
                    config.db_path(root),
                    wiki_name=config.wiki_name,
                    sqlite_policy=sqlite_policy_from_config(config),
                    read_only=True,
                )
            storage.mkdir(parents=True, exist_ok=True)
            return create_wiki_store(
                storage,
                wiki_name=config.wiki_name,
                backend="sqlite",
                sqlite_policy=sqlite_policy_from_config(config),
            )
        if config.backend == "arangodb":
            from parrot.knowledge.wiki.project import resolve_arango_params

            return create_wiki_store(
                storage,
                wiki_name=config.wiki_name,
                backend="arangodb",
                arango_params=resolve_arango_params(config),
                database=config.arango_database or "",
                text_analyzer=config.arango_text_analyzer,
            )
        return create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)
    except StandupStoreError:
        raise
    except Exception as exc:  # noqa: BLE001 -- surfaced as one actionable error
        raise StandupStoreError(
            f"Could not open the {config.backend} wiki plane at {storage}: {exc}. "
            "Check the storage settings in .parrot/wiki.json or run `wikitoolkit build`."
        ) from exc


def _readonly_identity(cfg: StandupConfig, explicit: str | None) -> StandupIdentity:
    """Resolve identity from config and an existing cache only: no cache write, no live probe."""
    identity = StandupIdentity(
        wiki=cfg.me.wiki or explicit or authoring_identity(None),
        jira_account_id=cfg.me.jira_account_id,
        jira_display_name=cfg.me.jira_display_name,
        aliases=list(cfg.me.aliases),
    )
    if identity.jira_account_id:
        return identity
    cached = identity_module._read_cache(identity_module._cache_path())
    if cached is not None:
        identity.jira_account_id = cached[0]
        identity.jira_display_name = identity.jira_display_name or cached[1]
    return identity


def _selected(namespaces: str | None) -> set[str] | None:
    """Translate the ``--ns`` selector into a resolver ``only`` set (``None`` means all)."""
    if namespaces is None or namespaces.strip() in ("", "all"):
        return None
    return {part.strip() for part in namespaces.split(",") if part.strip()} - {"local"}


async def _collect_source(name: str, ctx: CollectContext) -> tuple[list[BriefItem], CollectContext]:
    """Run one collector in its own context so concurrent diagnostics stay ordered."""
    try:
        module = importlib.import_module(f"parrot.knowledge.wiki.standup.collectors.{name}")
        return list(await module.collect(ctx)), ctx
    except Exception as exc:  # noqa: BLE001 -- a source never fails the brief
        ctx.diagnostics.append(f"{name}: {exc}")
        return [], ctx


def _date_of(value: object) -> date | None:
    """Parse an ISO date or datetime string."""
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _lint_timestamp(storage: Path) -> str | None:
    """Read the FEAT-625 lint report timestamp when the file exists; never run lint."""
    path = storage / "lint" / "report.json"
    try:
        stat = path.stat()
    except OSError:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if isinstance(payload, dict):
        for key in _LINT_TIME_KEYS:
            if isinstance(payload.get(key), str) and payload[key]:
                return str(payload[key])
    return datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")


def _jira_watermark() -> str | None:
    """Return the newest Jira scope watermark from the sync state, if any."""
    state = load_sync_state(resolve_issues_dir())
    marks = [scope.last_watermark for scope in state.scopes.values() if scope.last_watermark]
    return max(marks) if marks else None


async def _hygiene(
    items: list[BriefItem],
    unmapped: dict[str, int],
    cfg: StandupConfig,
    read_store: BaseWikiStore,
    storage: Path,
    diagnostics: list[str],
) -> HygieneReport:
    """Count source health from the collected items and existing state."""
    report = HygieneReport(
        ledger_blockers=sum(1 for item in items if item.source == "ledger" and item.status == "blocked"),
        proposed_decisions_older_than=sum(
            1
            for item in items
            if item.source == "decision"
            and item.status == "proposed"
            and item.age_days is not None
            and item.age_days > cfg.stale_decision_days
        ),
        stale_tickets=sum(
            1
            for item in items
            if item.source == "jira"
            and item.status != "closed"
            and item.age_days is not None
            and item.age_days > cfg.stale_ticket_days
        ),
        unmapped_statuses=dict(sorted(unmapped.items())),
    )
    try:
        report.jira_watermark = await asyncio.to_thread(_jira_watermark)
    except Exception as exc:  # noqa: BLE001 -- hygiene is informational
        diagnostics.append(f"hygiene:jira-watermark: {exc}")
    try:
        stats = await read_store.stats()
        pages = stats.get("attrs_pages")
        report.attrs_indexed = int(pages) if pages is not None else None
    except Exception as exc:  # noqa: BLE001
        diagnostics.append(f"hygiene:attrs: {exc}")
    report.last_lint = await asyncio.to_thread(_lint_timestamp, storage)
    return report


async def _daily_sources(read_store: BaseWikiStore, win: PeriodWindow, diagnostics: list[str]) -> list[str]:
    """List the daily source briefs that fall inside a week/month window."""
    try:
        rows = await read_store.list_by_attrs(
            {"period": "day"},
            date_key="date",
            since=win.start.isoformat(),
            until=win.end.isoformat(),
            limit=500,
        )
    except Exception as exc:  # noqa: BLE001
        diagnostics.append(f"sources: {exc}")
        return []
    return sorted(str(row["concept_id"]) for row in rows if str(row.get("concept_id", "")).startswith("brief:daily:"))


async def _closed_items(ids: list[str], read_store: BaseWikiStore) -> list[BriefItem]:
    """Describe IDs that disappeared since the previous brief, enriching titles when resolvable."""
    items: list[BriefItem] = []
    valid_kinds = set(STATUS_BY_TYPE)
    for item_id in ids:
        title, kind = item_id, "deliverable"
        try:
            page = await read_store.get_page(item_id, include_body=False)
        except Exception:  # noqa: BLE001 -- title enrichment is best-effort
            page = None
        if page:
            title = str(page.get("title") or item_id)
            attr_type = (page.get("attrs") or {}).get("type")
            if attr_type in valid_kinds:
                kind = attr_type
        items.append(BriefItem(id=item_id, kind=kind, title=title, status="closed", source="delta"))  # type: ignore[arg-type]
    return items


async def _synthesize(
    items: list[BriefItem], options: StandupOptions, cfg: StandupConfig, language: str, period: Period
) -> tuple[list[str], str]:
    """Return plate bullets and the Hygiene model outcome; failure degrades to fallback bullets."""
    from parrot.knowledge.wiki.standup.llm import fallback_bullets, project_items, summarize

    fallback = fallback_bullets(items, language=language)
    if not options.use_llm:
        return fallback, "skipped: disabled"
    from parrot.knowledge.wiki.llm_resolve import resolve_optional_llm

    try:
        adapter = await asyncio.to_thread(resolve_optional_llm, [cfg.llm_env], purpose="standup brief", logger=logger)
    except Exception as exc:  # noqa: BLE001
        return fallback, f"failed: {type(exc).__name__}"
    if adapter is None:
        return fallback, "skipped: no model"
    bullets = await summarize(
        project_items(items, period=period, language=language), language=language, adapter=adapter
    )
    if bullets is None:
        return fallback, "failed: synthesis unavailable"
    return bullets, "ok"


async def run(
    root: Path,
    options: StandupOptions,
    *,
    store: BaseWikiStore | None = None,
    effective: WikiEffectiveConfig | None = None,
) -> BriefDocument:
    """Collect, group, diff, synthesize, render and optionally persist a brief.

    Args:
        root: Project root.
        options: Explicit run options; both write flags false makes the run side-effect free.
        store: Optional caller-owned store; it is never closed and is the only write target.
        effective: Optional pre-resolved effective config.

    Returns:
        The assembled document with source diagnostics and independent write receipts.

    Raises:
        StandupStoreError: The local plane could not be opened (actionable message).
    """
    effective = effective or load_effective_config(root)
    config = effective.config
    cfg = _effective_cfg(config.standup, options)
    language = cfg.default_language
    writing = options.write_page or options.write_file
    diagnostics: list[str] = []

    owned: list[object] = []
    try:
        if store is None:
            local = await _open_local(root, config, writable=writing)
            owned.append(local)
            write_store: BaseWikiStore = local
        elif isinstance(store, FederatedWikiStore):
            write_store = store._origin_local or store.local
            local = store
        else:
            write_store = local = store

        read_store: BaseWikiStore = local
        only = _selected(options.namespaces)
        if not isinstance(store, FederatedWikiStore) and (only is None or only):
            try:
                handles: list[NamespaceHandle]
                handles, skipped = await resolve_namespaces(root, config, only=only)
            except Exception as exc:  # noqa: BLE001 -- namespaces are optional
                handles, skipped = [], []
                diagnostics.append(f"namespaces: {exc}")
            owned.extend(handle.store for handle in handles)
            diagnostics.extend(f"namespace {skip.name}: {skip.reason} ({skip.detail})" for skip in skipped)
            if handles or skipped:
                read_store = FederatedWikiStore(local, config.wiki_name, handles, skipped)

        identity = (
            await resolve_identity(cfg, explicit=options.me, root=root)
            if writing
            else _readonly_identity(cfg, options.me)
        )
        win = compute_window(options.period, _resolve_anchor(options, cfg), cfg)

        contexts = [
            CollectContext(root=root, store=read_store, cfg=cfg, window=win, identity=identity, team=options.team)
            for _ in _COLLECTOR_MODULES
        ]
        results = await asyncio.gather(
            *(_collect_source(n, c) for n, c in zip(_COLLECTOR_MODULES, contexts, strict=True))
        )

        merged: dict[str, BriefItem] = {}
        unmapped: dict[str, int] = {}
        for items, ctx in results:
            diagnostics.extend(ctx.diagnostics)
            for key, count in ctx.unmapped_statuses.items():
                unmapped[key] = unmapped.get(key, 0) + count
            for item in items:
                merged.setdefault(item.id, item)
        all_items = [merged[key] for key in sorted(merged)]

        group_ctx = CollectContext(
            root=root, store=read_store, cfg=cfg, window=win, identity=identity, team=options.team
        )
        projects, internal = await group_items(all_items, group_ctx)
        diagnostics.extend(group_ctx.diagnostics)

        item_ids = sorted(merged)
        previous = None
        try:
            previous = await previous_brief(write_store, win)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(f"delta: {exc}")
        new_ids, absent_ids = diff(item_ids, previous)
        delta_new = [merged[item_id] for item_id in new_ids if item_id in merged]
        delta_closed = await _closed_items(absent_ids, read_store)

        sources = await _daily_sources(read_store, win, diagnostics) if options.period != "day" else []
        bullets, llm_state = await _synthesize(all_items, options, cfg, language, options.period)
        storage = config.storage_path(root)
        hygiene = await _hygiene(all_items, unmapped, cfg, read_store, storage, diagnostics)
        hygiene.llm = llm_state

        doc = BriefDocument(
            window=win,
            identity=identity,
            team=options.team,
            language=language,
            on_your_plate=bullets,
            projects=projects,
            internal=internal,
            delta_new=delta_new,
            delta_closed=delta_closed,
            previous_brief_id=str(previous["concept_id"]) if previous else None,
            sources=sources,
            hygiene=hygiene,
            item_ids=item_ids,
            diagnostics=diagnostics,
        )

        if writing:
            out_dir = options.out_dir or (Path(cfg.out_dir) if cfg.out_dir else parrot_home() / "wikis" / "briefs")
            if not out_dir.is_absolute():
                out_dir = root / out_dir
            result = await write(
                doc,
                render_markdown(doc, language),
                store=write_store,
                storage_dir=storage,
                out_dir=out_dir,
                write_page=options.write_page,
                write_file=options.write_file,
                vault_dir=resolve_vault_dir(root, config),
            )
            doc.written_page = result.written_page
            doc.written_file = result.written_file
            doc.diagnostics.extend(result.diagnostics)
        return doc
    finally:
        for resource in reversed(owned):
            await _close(resource)
