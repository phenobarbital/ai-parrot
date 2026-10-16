"""LedgerService — application facade for the SDD work ledger (spec §3 Module 6).

Coordinates :class:`~parrot.knowledge.wiki.ledger.log.LedgerLog`,
:class:`~parrot.knowledge.wiki.ledger.index.LedgerIndex`, and
:class:`~parrot.knowledge.wiki.ledger.store.LedgerStore` behind the single API
surface SDD commands, MCP tools, and CLI subcommands (Modules 8/9/12) call
into. Never issues SQLite connections or transactions of its own — reads go
through ``LedgerStore._read()`` (the same protected-but-in-package pattern
``LedgerIndex`` uses internally), writes go through ``LedgerIndex``/``LedgerLog``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Collection, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from parrot.knowledge.wiki.ledger.events import (
    IssueKind,
    IssueSeverity,
    IssueOpenedPayload,
    LedgerEvent,
    SEVERITY_ORDER,
    compute_issue_id,
)
from parrot.knowledge.wiki.ledger.index import LedgerIndex, _decode_issue_body
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.project import (
    find_shared_root,
    load_effective_config,
    sqlite_policy_from_config,
)
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy, estimate_tokens

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from parrot.knowledge.wiki.ledger.shared_log import SharedLogExportReport, SharedLogImportReport, SharedLogRotateReport


def _write_snapshot_if_changed(dest: Path, new_content: str) -> bool:
    """Blocking half of :meth:`LedgerService.export_snapshot` — run via ``asyncio.to_thread``."""
    old_content = dest.read_text(encoding="utf-8") if dest.exists() else None
    if old_content == new_content:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(new_content, encoding="utf-8")
    return True


def _read_snapshot_rows(dest: Path) -> list[dict[str, Any]]:
    """Blocking half of the reconciliation pre-pass — run via ``asyncio.to_thread``.

    Returns the JSON rows already in ``dest`` (``[]`` when the file is missing). A line that
    is not a JSON object carrying a string ``issue_id`` is logged at WARNING with its 1-based
    line number and skipped — it is not a valid issue row and cannot be reconciled.
    """
    if not dest.exists():
        return []
    rows: list[dict[str, Any]] = []
    skipped: list[int] = []
    with dest.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped.append(lineno)
                continue
            if not isinstance(row, dict) or not isinstance(row.get("issue_id"), str):
                skipped.append(lineno)
                continue
            rows.append(row)
    if skipped:
        logger.warning("Ledger snapshot %s: skipped %d malformed line(s) at %s", dest, len(skipped), skipped)
    return rows


def _scan_log_for_audit(log: LedgerLog, cursor_offset: int) -> tuple[dict[str, int], int, int, int]:
    """Blocking half of :meth:`LedgerService.audit` — run via ``asyncio.to_thread``.

    One pass over ``events.jsonl`` computes everything the audit report
    needs from the log: per-kind counts, the total event count, the
    number of events at-or-before ``cursor_offset`` (the replay lag
    estimate), and the file's byte size.

    Returns:
        ``(event_counts, total_events, applied_count, log_size_bytes)``.
    """
    event_counts: dict[str, int] = {}
    total_events = 0
    applied_count = 0
    still_applied = True
    for event, line_start in log.iter_events(from_offset=0):
        event_counts[event.kind] = event_counts.get(event.kind, 0) + 1
        total_events += 1
        if still_applied:
            if line_start > cursor_offset:
                still_applied = False
            else:
                applied_count += 1

    log_path = Path(log.path)
    log_size = log_path.stat().st_size if log_path.exists() else 0
    return event_counts, total_events, applied_count, log_size


def normalize_issue_id(raw: str) -> str:
    """Return ``raw`` prefixed with ``issue:`` unless it already is; strips whitespace.

    Args:
        raw: An issue id as typed by a user or agent (``a9514c9232ad`` or ``issue:a9514c9232ad``).

    Returns:
        The canonical ``issue:<hex>`` id.
    """
    value = raw.strip()
    return value if value.startswith("issue:") else f"issue:{value}"


def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """Project a decoded issue state into the public dict shape callers see."""
    return {
        "issue_id": issue_id,
        "title": state.get("title", ""),
        "status": state.get("status"),
        "kind": state.get("kind"),
        "severity": state.get("severity"),
        "acknowledged": bool(state.get("acknowledged", False)),
        "discovered_from": state.get("discovered_from"),
        "about": list(state.get("about", []) or []),
        "claimed_by": state.get("claimed_by"),
        "closed_by": state.get("closed_by"),
        "closed_reason": state.get("closed_reason"),
        "resolved_by": state.get("resolved_by"),
    }


class LedgerService:
    """High-level, application-facing service coordinating the SDD work ledger."""

    def __init__(self, index: LedgerIndex, store: LedgerStore, log: LedgerLog, shared_root: Path) -> None:
        """Initialize the service from already-constructed collaborators.

        Args:
            index: Materialized query view over the event log.
            store: Ledger's ``SQLiteWikiStore`` specialisation.
            log: Append-only event log.
            shared_root: Main checkout root this ledger is shared across.
        """
        self.index = index
        self.store = store
        self.log = log
        self.shared_root = shared_root

    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService":
        """Initialize a service pointing at ``find_shared_root(root)``.

        Opens ``LedgerStore(<shared>/.parrot/ledger/ledger.db,
        sqlite_policy=sqlite_policy_from_config(config))`` using the shared
        root's ``WikiProjectConfig`` (spec §3 Module 2 §2.1) — no
        ledger-specific SQLite settings are ever introduced here.

        Args:
            root: Starting directory to resolve the shared root from
                (defaults to CWD); works from inside a linked worktree.

        Returns:
            A ready-to-use ``LedgerService``.
        """
        shared_root = find_shared_root(root) or (root or Path.cwd()).resolve()
        # Consumers must go through load_effective_config (env-overlay
        # merge), never the raw load_project_config directly — enforced
        # project-wide by test_env_call_sites.py's call-site guard.
        config = load_effective_config(shared_root).config
        ledger_dir = config.ledger_path(shared_root)
        ledger_dir.mkdir(parents=True, exist_ok=True)

        policy = sqlite_policy_from_config(config)
        store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=policy)
        log = LedgerLog(str(ledger_dir / "events.jsonl"))
        index = LedgerIndex(store, log)
        return cls(index, store, log, shared_root)

    @classmethod
    def from_dir(cls, ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy | None = None) -> "LedgerService":
        """Open (creating if needed) a ledger at an explicit directory — no git root required (FEAT-569).

        Used by ``wikitoolkit serve``: the server host has no checkout, so the
        ledger location is configuration, not discovery. ``shared_root`` is
        derived as ``ledger_dir.parent.parent`` (mirroring ``<root>/.parrot/ledger``);
        :meth:`merge_blockers` therefore finds no per-spec index there and
        returns ``[]`` — the merge gate keeps running on the shared checkout.

        Args:
            ledger_dir: Directory holding ``ledger.db`` and ``events.jsonl``.
            sqlite_policy: Connection policy for the ledger's SQLite plane.

        Returns:
            A ready-to-use ``LedgerService``.
        """
        ledger_dir = ledger_dir.resolve()
        ledger_dir.mkdir(parents=True, exist_ok=True)
        store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=sqlite_policy)
        log = LedgerLog(str(ledger_dir / "events.jsonl"))
        index = LedgerIndex(store, log)
        return cls(index, store, log, ledger_dir.parent.parent)

    async def _sync_best_effort(self) -> None:
        """Sync the index, tolerating a busy writer lock (reads use a stale index instead)."""
        try:
            await self.index.sync()
        except WikiStoreBusy:
            logger.warning("Ledger index sync skipped: writer lock busy; reads may be stale.")

    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]:
        """Return ``(issue_id, state)`` for every decodable issue page."""
        async with self.store._read() as conn:
            async with conn.execute("SELECT concept_id, body FROM pages WHERE category = 'issue'") as cur:
                rows = await cur.fetchall()
        result = []
        for concept_id, body in rows:
            state = _decode_issue_body(body)
            if state is not None:
                result.append((concept_id, state))
        return result

    # ------------------------------------------------------------------
    # Public API (spec §2)
    # ------------------------------------------------------------------

    async def open_issue(
        self,
        title: str,
        body: str,
        kind: IssueKind = "bug",
        severity: str = "minor",
        discovered_from: str = "",
        about: list[str] | None = None,
        actor: str = "agent:sdd",
    ) -> str:
        """Record a new issue in the log and (best-effort) the index.

        Per Module 2 §2.2, the event is appended BEFORE the index write is
        attempted: a busy index is a soft success — the issue is durable and
        will be materialized by the next ``sync()``.

        Returns:
            The deterministic ``issue:<hash>`` id.
        """
        issue_id = compute_issue_id(kind, title, discovered_from)
        payload = IssueOpenedPayload(
            title=title,
            body=body,
            kind=kind,
            severity=severity,
            discovered_from=discovered_from,
            about=about or [],
        )
        event = LedgerEvent(kind="issue.opened", subject=issue_id, actor=actor, payload=payload.model_dump())
        await asyncio.to_thread(self.log.append, event)
        await self._sync_best_effort()
        return issue_id

    async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]:
        """Return unclaimed, open issues sorted by ``(SEVERITY_ORDER, issue_id)``.

        The filter predicate is unchanged; only the ordering is new (FEAT-572 S6).
        ``ledger ready``, ``/sdd-next`` and the MCP ``ledger_ready`` tool inherit it.
        """
        await self._sync_best_effort()
        issues = await self._all_issues()
        rows = [
            _issue_dict(issue_id, state)
            for issue_id, state in issues
            if state.get("status") == "open" and (kind is None or state.get("kind") == kind)
        ]
        rows.sort(key=lambda row: (SEVERITY_ORDER.get(row["severity"], len(SEVERITY_ORDER)), row["issue_id"]))
        return rows

    async def active_issues(self) -> list[dict[str, Any]]:
        """Return every ``open`` or ``claimed`` issue (used for dedupe by lint routing)."""
        await self._sync_best_effort()
        issues = await self._all_issues()
        return [
            _issue_dict(issue_id, state) for issue_id, state in issues if state.get("status") in ("open", "claimed")
        ]

    async def list_issues(
        self,
        statuses: Sequence[str] = ("open", "claimed"),
        *,
        kind: IssueKind | None = None,
        severity: IssueSeverity | None = None,
        about_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        """List issues by status, optional kind and about-path prefix, severity first.

        Args:
            statuses: Issue statuses to include (default open and claimed).
            kind: Restrict to one issue kind when given.
            severity: Restrict to one severity when given.
            about_prefix: Keep issues having any ``about`` entry starting with this prefix.

        Returns:
            Public issue dicts (including ``claimed_by``) sorted by ``(SEVERITY_ORDER, issue_id)``.
        """
        await self._sync_best_effort()
        wanted = set(statuses)
        rows = []
        for issue_id, state in await self._all_issues():
            if state.get("status") not in wanted:
                continue
            if kind is not None and state.get("kind") != kind:
                continue
            if severity is not None and state.get("severity") != severity:
                continue
            row = _issue_dict(issue_id, state)
            if about_prefix is not None and not any(str(a).startswith(about_prefix) for a in row["about"]):
                continue
            rows.append(row)
        rows.sort(key=lambda row: (SEVERITY_ORDER.get(row["severity"], len(SEVERITY_ORDER)), row["issue_id"]))
        return rows

    async def get_issue(self, issue_id: str) -> dict[str, Any] | None:
        """Return one issue's public dict plus its ``body``; ``None`` when unknown.

        Args:
            issue_id: Issue id, with or without the ``issue:`` prefix.

        Returns:
            The :func:`_issue_dict` shape with an added ``"body"`` key, or ``None``.
        """
        await self._sync_best_effort()
        canonical = normalize_issue_id(issue_id)
        state = await self._issue_state(canonical)
        if state is None:
            return None
        row = _issue_dict(canonical, state)
        row["body"] = state.get("body", "")
        return row

    async def issue_history(self, issue_id: str) -> list[dict[str, Any]]:
        """Return the events whose ``subject`` is this issue, in log order.

        Args:
            issue_id: Issue id, with or without the ``issue:`` prefix.

        Returns:
            ``{"event_id", "kind", "actor", "ts", "payload"}`` dicts; ``[]`` for an unknown id.
        """
        canonical = normalize_issue_id(issue_id)

        def _scan() -> list[dict[str, Any]]:
            return [
                {
                    "event_id": event.event_id,
                    "kind": event.kind,
                    "actor": event.actor,
                    "ts": event.ts,
                    "payload": dict(event.payload),
                }
                for event, _offset in self.log.iter_events()
                if event.subject == canonical
            ]

        return await asyncio.to_thread(_scan)

    async def claim(self, issue_id: str, actor: str) -> bool:
        """Import the committed shared log first (FEAT-694 G8), then :meth:`LedgerIndex.claim_issue`."""
        from parrot.knowledge.wiki.ledger.shared_log import SHARED_LOG_REL_PATH

        if (self.shared_root / SHARED_LOG_REL_PATH).exists():
            try:
                await self.import_shared_log()
            except WikiStoreBusy:
                pass
            except Exception:  # noqa: BLE001 -- a broken checkout must never block a claim (AC15)
                logger.warning("Shared ledger log import before claim failed; claiming anyway.", exc_info=True)
        return await self.index.claim_issue(issue_id, actor)

    async def acknowledge(self, issue_id: str, reason: str, actor: str) -> bool:
        """Record ``issue.acknowledged``. Rejects non-human actors.

        Returns:
            ``False`` without appending anything when ``actor`` does not
            start with ``"human:"`` — acknowledging a critical is a human
            decision (Module 8).
        """
        if not actor.startswith("human:"):
            logger.warning("Refusing issue.acknowledged from non-human actor %r", actor)
            return False

        event = LedgerEvent(
            kind="issue.acknowledged",
            subject=issue_id,
            actor=actor,
            payload={"acknowledged_by": actor, "reason": reason},
        )
        await asyncio.to_thread(self.log.append, event)
        await self._sync_best_effort()
        return True

    async def _issue_state(self, issue_id: str) -> dict[str, Any] | None:
        """Read one issue's decoded state (``None`` when no page exists); reads via ``store._read()`` like ``_all_issues``."""
        async with self.store._read() as conn:
            async with conn.execute("SELECT body FROM pages WHERE concept_id = ?", (issue_id,)) as cur:
                row = await cur.fetchone()
        return _decode_issue_body(row[0]) if row else None

    async def close_issue(self, issue_id: str, reason: str, actor: str, resolved_by: str | None = None) -> bool:
        """Delegate to :meth:`LedgerIndex.close_issue` (atomic transaction)."""
        return await self.index.close_issue(issue_id, actor, reason, resolved_by)

    async def unclaim(self, issue_id: str, reason: str, actor: str) -> bool:
        """Delegate to :meth:`LedgerIndex.unclaim_issue` (atomic transaction)."""
        return await self.index.unclaim_issue(issue_id, actor, reason)

    async def get_context(self, file_paths: list[str], max_tokens: int = 3000) -> str:
        """Return a token-budgeted rendering of open issues touching ``file_paths``.

        Args:
            file_paths: Symbol/file ids or plain paths to scope the search to.
            max_tokens: Soft budget; lines are appended while under budget.

        Returns:
            A newline-joined, human-readable context block (empty string
            when nothing matches).
        """
        if not file_paths:
            return ""
        await self._sync_best_effort()
        issues = await self._all_issues()

        lines: list[str] = []
        budget_used = 0
        for issue_id, state in issues:
            if state.get("status") not in ("open", "claimed"):
                continue
            about = state.get("about", []) or []
            if not any(any(target in scope or scope in target for target in file_paths) for scope in about):
                continue
            line = f"- [{state.get('severity')}] {issue_id} {state.get('title', '')} ({state.get('status')})"
            cost = estimate_tokens(line)
            if lines and budget_used + cost > max_tokens:
                break
            lines.append(line)
            budget_used += cost

        return "\n".join(lines)

    async def merge_blockers(self, feature_id: str) -> list[dict[str, Any]]:
        """Return open/claimed, unacknowledged, critical issues discovered by ``feature_id``.

        Scopes to ``spec:<feature_id>``, ``task:<TASK-NNN>``, and
        ``review:<TASK-NNN>`` for every task owned by ``feature_id``'s
        per-spec index — critical issues discovered by OTHER features never
        block this feature's merge.

        Args:
            feature_id: e.g. ``"FEAT-566"``.

        Returns:
            Matching issue dicts (empty when the feature's index cannot be
            found, or nothing blocks it).
        """
        task_ids = await asyncio.to_thread(self._feature_task_ids, feature_id)
        valid_sources = {f"spec:{feature_id}"}
        valid_sources.update(f"task:{tid}" for tid in task_ids)
        valid_sources.update(f"review:{tid}" for tid in task_ids)

        await self._sync_best_effort()
        issues = await self._all_issues()
        return [
            _issue_dict(issue_id, state)
            for issue_id, state in issues
            if state.get("severity") == "critical"
            and not state.get("acknowledged", False)
            and state.get("status") in ("open", "claimed")
            and state.get("discovered_from") in valid_sources
        ]

    def _feature_task_ids(self, feature_id: str) -> list[str]:
        """Read the feature's per-spec index (shared checkout only) and return its task ids."""
        index_dir = self.shared_root / "sdd" / "tasks" / "index"
        if not index_dir.exists():
            return []
        for index_path in index_dir.glob("*.json"):
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("feature_id") == feature_id:
                return [task.get("id") for task in data.get("tasks", []) if task.get("id")]
        return []

    def _feature_index_status_sync(self, wanted: set[str]) -> dict[str, str | None]:
        """Blocking half of :meth:`feature_index_status` — one ``glob`` over the index directory."""
        index_dir = self.shared_root / "sdd" / "tasks" / "index"
        result: dict[str, str | None] = {}
        if not wanted or not index_dir.exists():
            return result
        for index_path in index_dir.glob("*.json"):
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            feature_id = data.get("feature_id")
            if feature_id in wanted:
                result[feature_id] = data.get("completed_at")
        return result

    async def feature_index_status(self, feature_ids: Collection[str]) -> dict[str, str | None]:
        """Map each ``FEAT-<NNN>`` to its per-spec index ``completed_at`` (``None`` = still open).

        A feature with no index file is ABSENT from the result — the caller distinguishes
        "open" (present, ``None``) from "unknown" (absent). Scans the directory once.
        """
        return await asyncio.to_thread(self._feature_index_status_sync, set(feature_ids))

    async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool:
        """Write ``sdd/ledger/issues.jsonl`` deterministically, reconciling against ``dest``.

        One JSON object per issue with status ``open``, ``claimed``, or closed/superseded but
        not yet compacted — keys sorted, rows sorted by ``issue_id``, no volatile fields, so
        regenerating from the same ledger state and the same ``dest`` is byte-identical.
        Insights are excluded.

        Local state is authoritative for every issue this ledger has recorded. With
        ``reconcile=True`` (default) every row already in ``dest`` whose ``issue_id`` is
        unknown to this ledger is carried forward unchanged, so an export from a machine whose
        event log is behind never drops another machine's issues (FEAT-671).
        ``reconcile=False`` rebuilds the snapshot from the local view only — destructive,
        explicit opt-in.

        Args:
            dest: Destination path (created, with parents, if missing).
            reconcile: Carry forward rows for issues unknown to this ledger.

        Returns:
            ``True`` if the written content differs from what was already on disk (or the
            file did not exist yet).
        """
        await self._sync_best_effort()
        issues = await self._all_issues()

        rows = [
            _issue_dict(issue_id, state)
            for issue_id, state in issues
            if state.get("status") in ("open", "claimed") or not state.get("compacted", False)
        ]
        if reconcile:
            known = {issue_id for issue_id, _ in issues}
            existing = await asyncio.to_thread(_read_snapshot_rows, dest)
            carried = [row for row in existing if row["issue_id"] not in known]
            if carried:
                logger.info(
                    "Ledger snapshot %s: carried forward %d issue(s) unknown to this ledger", dest, len(carried)
                )
            rows.extend(carried)
        rows.sort(key=lambda row: row["issue_id"])
        new_content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)

        return await asyncio.to_thread(_write_snapshot_if_changed, dest, new_content)

    async def export_shared_log(self, repo_root: Path | None = None) -> "SharedLogExportReport":
        """Append this machine's shareable events to the committed shared log.

        Args:
            repo_root: Checkout containing the shared ``sdd/ledger`` directory.

        Returns:
            The append-only export report.
        """
        from parrot.knowledge.wiki.ledger.shared_log import export_events

        return await asyncio.to_thread(export_events, self.log, repo_root or self.shared_root)

    async def import_shared_log(self, repo_root: Path | None = None, *, force: bool = False) -> "SharedLogImportReport":
        """Append unknown committed events, incrementally sync, and report claim conflicts.

        Args:
            repo_root: Checkout containing the shared ``sdd/ledger`` directory.
            force: Whether to bypass the digest-marker fast path.

        Returns:
            Import details, including a soft index-busy result when applicable.
        """
        from parrot.knowledge.wiki.ledger.shared_log import MARKER_FILENAME, ClaimConflict, import_events

        marker = Path(self.log.path).parent / MARKER_FILENAME
        report, claimed = await asyncio.to_thread(
            import_events, self.log, repo_root or self.shared_root, marker, force=force
        )
        if report.fast_path or report.added == 0:
            return report

        try:
            report.synced_events = await self.index.sync()
        except WikiStoreBusy:
            logger.warning("Ledger index sync skipped: writer lock busy; imported events remain durable.")
            report.index_busy = True
            report.synced_events = 0
            return report

        issues = dict(await self._all_issues())
        for event in claimed:
            state = issues.get(event.subject)
            foreign_claimed_by = event.payload.get("claimed_by")
            if state is not None and state.get("status") == "claimed" and state.get("claimed_by") != foreign_claimed_by:
                report.claim_conflicts.append(
                    ClaimConflict(
                        issue_id=event.subject,
                        local_claimed_by=state["claimed_by"],
                        foreign_claimed_by=foreign_claimed_by,
                        foreign_event_id=event.event_id,
                    )
                )
        return report

    async def rotate_shared_log(
        self, repo_root: Path | None = None, *, older_than_days: int = 30, now: datetime | None = None
    ) -> SharedLogRotateReport:
        """Rotate the committed log (``/sdd-done`` 9.1 only). Never touches the local log or index."""
        from parrot.knowledge.wiki.ledger.shared_log import rotate_events

        return await asyncio.to_thread(
            rotate_events, repo_root or self.shared_root, older_than_days=older_than_days, now=now
        )

    async def compact(self, older_than_days: int = 30) -> int:
        """Delegate to :meth:`LedgerIndex.compact`."""
        return await self.index.compact(older_than_days)

    async def audit(self) -> dict[str, Any]:
        """Return log size, per-kind event counts, cursor lag, broken edges, and SQLite settings."""
        offset, last_event_id = await self.store.read_cursor()

        event_counts, total_events, applied_count, log_size = await asyncio.to_thread(
            _scan_log_for_audit, self.log, offset
        )
        lag = 0 if last_event_id is None and offset == 0 else max(0, total_events - applied_count)
        if log_size > 50 * 1024 * 1024:
            logger.warning("events.jsonl is over 50 MiB (%d bytes); consider `ledger compact`.", log_size)

        async with self.store._read() as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM edges WHERE dst NOT IN (SELECT concept_id FROM pages)"
                " AND dst NOT LIKE 'sym:%' AND dst NOT LIKE 'file:%'"
            ) as cur:
                broken_row = await cur.fetchone()
        broken_edges = broken_row[0] if broken_row else 0

        return {
            "log_size_bytes": log_size,
            "event_counts": event_counts,
            "total_events": total_events,
            "cursor_offset": offset,
            "cursor_lag_events": lag,
            "broken_edges": broken_edges,
            "shared_log": await asyncio.to_thread(self._shared_log_audit),
            "sqlite": await self.store.sqlite_settings(),
        }

    def _shared_log_audit(self) -> dict[str, Any]:
        """Blocking: compare the local log with the committed logical shared log."""
        from parrot.knowledge.wiki.ledger.shared_log import (
            MARKER_FILENAME,
            SHARED_LOG_REL_PATH,
            digest_files,
            is_shareable,
            read_raw_events,
            read_shared_event_ids,
            shared_log_files,
        )

        files = shared_log_files(self.shared_root)
        committed = read_shared_event_ids(files)
        local_events = read_raw_events(Path(self.log.path))
        local = {event.event_id for _, event in local_events if is_shareable(event)}
        all_local_ids = {event.event_id for _, event in local_events}
        marker = Path(self.log.path).parent / MARKER_FILENAME
        if not marker.exists():
            marker_state = "missing"
        elif marker.read_text(encoding="utf-8") == digest_files(files):
            marker_state = "ok"
        else:
            marker_state = "stale"
        return {
            "path": str(self.shared_root / SHARED_LOG_REL_PATH),
            "exists": (self.shared_root / SHARED_LOG_REL_PATH).exists(),
            "local_only_events": len(local - committed),
            "committed_unknown_events": len(committed - all_local_ids),
            "marker": marker_state,
        }
