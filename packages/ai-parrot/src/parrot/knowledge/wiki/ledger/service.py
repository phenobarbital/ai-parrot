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
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.ledger.events import (
    IssueKind,
    IssueOpenedPayload,
    LedgerEvent,
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
from parrot.knowledge.wiki.store import WikiStoreBusy, estimate_tokens

logger = logging.getLogger(__name__)


def _write_snapshot_if_changed(dest: Path, new_content: str) -> bool:
    """Blocking half of :meth:`LedgerService.export_snapshot` — run via ``asyncio.to_thread``."""
    old_content = dest.read_text(encoding="utf-8") if dest.exists() else None
    if old_content == new_content:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(new_content, encoding="utf-8")
    return True


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
        """Return unclaimed, open issues (optionally filtered by ``kind``)."""
        await self._sync_best_effort()
        issues = await self._all_issues()
        return [
            _issue_dict(issue_id, state)
            for issue_id, state in issues
            if state.get("status") == "open" and (kind is None or state.get("kind") == kind)
        ]

    async def claim(self, issue_id: str, actor: str) -> bool:
        """Delegate to :meth:`LedgerIndex.claim_issue`."""
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

    async def close_issue(self, issue_id: str, reason: str, actor: str) -> bool:
        """Close an issue with a reason."""
        event = LedgerEvent(
            kind="issue.closed",
            subject=issue_id,
            actor=actor,
            payload={"reason": reason, "closed_by": actor},
        )
        await asyncio.to_thread(self.log.append, event)
        await self._sync_best_effort()
        return True

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

    async def export_snapshot(self, dest: Path) -> bool:
        """Write ``sdd/ledger/issues.jsonl`` deterministically.

        One JSON object per issue with status ``open``, ``claimed``, or
        closed/superseded but not yet compacted — keys sorted, rows sorted
        by ``issue_id``, no volatile fields, so regenerating from the same
        ledger state is byte-identical. Insights are excluded.

        Args:
            dest: Destination path (created, with parents, if missing).

        Returns:
            ``True`` if the written content differs from what was already
            on disk (or the file did not exist yet).
        """
        await self._sync_best_effort()
        issues = await self._all_issues()

        rows = [
            _issue_dict(issue_id, state)
            for issue_id, state in issues
            if state.get("status") in ("open", "claimed") or not state.get("compacted", False)
        ]
        rows.sort(key=lambda row: row["issue_id"])
        new_content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)

        return await asyncio.to_thread(_write_snapshot_if_changed, dest, new_content)

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
            "sqlite": await self.store.sqlite_settings(),
        }
