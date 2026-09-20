"""LedgerIndex — materialized query view over ``events.jsonl`` backed by ``LedgerStore``.

Reduces durable ledger events into ``WikiPageRecord`` rows and edges (spec §3
Module 5), persists a sync cursor so ``sync()`` resumes from the tail instead
of rescanning the whole log, and implements the one atomic writer-side
guarantee the ledger needs: "first claim in log order wins".

All SQLite transaction/busy-timeout handling is delegated to
:class:`~parrot.knowledge.wiki.ledger.store.LedgerStore` (FEAT-557 policy);
this module never issues ``BEGIN``/``COMMIT``/``ROLLBACK`` itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from parrot.knowledge.wiki.ledger.events import (
    IssueAcknowledgedPayload,
    IssueClaimedPayload,
    IssueClosedPayload,
    IssueOpenedPayload,
    IssueUnclaimedPayload,
    LedgerEvent,
)
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.store import WikiPageRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

    from parrot.knowledge.wiki.ledger.store import LedgerStore

logger = logging.getLogger(__name__)

# An issue page's ``body`` column carries a machine-readable state header —
# a single-line JSON object wrapped in an HTML comment — followed by a
# human-readable rendering. Reading and writing always go through the same
# encode/decode pair below so the two representations can never drift apart.
_STATE_PREFIX = "<!--ledger-state "
_STATE_SUFFIX = "-->"


def _encode_issue_body(state: dict[str, Any]) -> str:
    """Serialize issue ``state`` into the page ``body`` column.

    Args:
        state: Full issue state dict (title, status, kind, severity, …).

    Returns:
        A body string carrying the JSON state header plus a human-readable
        rendering of the title and free-text body.
    """
    header = f"{_STATE_PREFIX}{json.dumps(state, sort_keys=True)}{_STATE_SUFFIX}"
    human = f"# {state.get('title', '')}\n\n{state.get('body', '')}"
    return f"{header}\n\n{human}"


def _decode_issue_body(body: str | None) -> dict[str, Any] | None:
    """Parse the JSON state header out of a ``body`` column value.

    Args:
        body: Raw ``pages.body`` value, or ``None``.

    Returns:
        The decoded state dict, or ``None`` when ``body`` does not carry a
        recognizable ledger state header (missing page, corrupt row, …).
    """
    if not body or not body.startswith(_STATE_PREFIX):
        return None
    end = body.find(_STATE_SUFFIX)
    if end == -1:
        return None
    raw = body[len(_STATE_PREFIX) : end].strip()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Malformed ledger issue state header, treating page as absent.")
        return None
    return decoded if isinstance(decoded, dict) else None


class LedgerIndex:
    """Materialized query view over the event log backed by ``LedgerStore``."""

    def __init__(self, store: "LedgerStore", log: LedgerLog) -> None:
        """Initialize the index with its underlying wiki store and event log.

        Args:
            store: ``LedgerStore`` instance opened against ``ledger.db``.
            log: ``LedgerLog`` instance opened against ``events.jsonl``.
        """
        self.store = store
        self.log = log

    # ------------------------------------------------------------------
    # Reducer
    # ------------------------------------------------------------------

    async def apply_event(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:
        """Apply one event's reduction rule inside an existing connection/transaction.

        Args:
            event: Event to reduce.
            conn: Connection inside an open ``LedgerStore`` write transaction.
        """
        if event.kind == "issue.opened":
            await self._apply_issue_opened(event, conn)
        elif event.kind == "issue.claimed":
            await self._apply_issue_claimed(event, conn)
        elif event.kind == "issue.acknowledged":
            await self._apply_issue_acknowledged(event, conn)
        elif event.kind == "issue.closed":
            await self._apply_issue_closed(event, conn)
        elif event.kind == "issue.superseded":
            await self._apply_issue_superseded(event, conn)
        elif event.kind == "issue.unclaimed":
            await self._apply_issue_unclaimed(event, conn)
        # task.*, spec.*, insight.* reduction is out of this task's scope
        # (Modules 7/8/12); unknown kinds are ignored rather than raising so
        # replay never breaks on a future event kind it doesn't own yet.

    async def _read_issue(self, conn: "aiosqlite.Connection", issue_id: str) -> dict[str, Any] | None:
        """Read and decode an issue's current state, if the page exists."""
        async with conn.execute("SELECT body FROM pages WHERE concept_id = ?", (issue_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return _decode_issue_body(row[0])

    async def _write_issue(
        self,
        conn: "aiosqlite.Connection",
        issue_id: str,
        state: dict[str, Any],
        actor: str,
        ts: str,
    ) -> None:
        """Upsert an issue page from its full state dict."""
        body_text = state.get("body", "") or ""
        summary = body_text[:200] + ("..." if len(body_text) > 200 else "")
        page = WikiPageRecord(
            concept_id=issue_id,
            title=state.get("title", ""),
            category="issue",
            summary=summary,
            body=_encode_issue_body(state),
            source_id=None,
            token_count=0,
            origin="ledger",
            asserted_by=actor,
            updated_at=ts,
        )
        await self.store.upsert_pages_in(conn, [page])

    async def _apply_issue_opened(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:
        """Create a new issue page, or fold a duplicate open into an edge only."""
        payload = IssueOpenedPayload(**event.payload)
        issue_id = event.subject

        existing = await self._read_issue(conn, issue_id)
        if existing is not None:
            # Dedup (compute_issue_id collision): no-op except the edge.
            await self.store.add_edges_in(conn, [(issue_id, payload.discovered_from, "discovered-from", "asserted")])
            return

        state: dict[str, Any] = {
            "title": payload.title,
            "body": payload.body,
            "kind": payload.kind,
            "severity": payload.severity,
            "status": "open",
            "acknowledged": False,
            "discovered_from": payload.discovered_from,
            "about": list(payload.about),
            "claimed_by": None,
            "closed_by": None,
            "closed_reason": None,
            "resolved_by": None,
        }
        await self._write_issue(conn, issue_id, state, event.actor, event.ts)

        edges = [(issue_id, payload.discovered_from, "discovered-from", "asserted")]
        for target in payload.about:
            edges.append((issue_id, target, "about", "asserted"))
        await self.store.add_edges_in(conn, edges)

    async def _apply_issue_claimed(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:
        """Claim an open issue; a non-open issue makes this a no-op (first claim wins)."""
        payload = IssueClaimedPayload(**event.payload)
        state = await self._read_issue(conn, event.subject)
        if state is None or state.get("status") != "open":
            return
        state["status"] = "claimed"
        state["claimed_by"] = payload.claimed_by
        await self._write_issue(conn, event.subject, state, event.actor, event.ts)
        await self.store.add_edges_in(conn, [(event.subject, payload.claimed_by, "claimed-by", "asserted")])

    async def _apply_issue_acknowledged(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:
        """Set ``acknowledged=True`` without changing status; ignored once closed/superseded."""
        payload = IssueAcknowledgedPayload(**event.payload)
        state = await self._read_issue(conn, event.subject)
        if state is None or state.get("status") in ("closed", "superseded"):
            return
        state["acknowledged"] = True
        await self._write_issue(conn, event.subject, state, event.actor, event.ts)
        await self.store.add_edges_in(conn, [(event.subject, payload.acknowledged_by, "acknowledged-by", "asserted")])

    async def _apply_issue_closed(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:
        """Close an issue, recording the resolver and reason."""
        payload = IssueClosedPayload(**event.payload)
        state = await self._read_issue(conn, event.subject)
        if state is None:
            return
        state["status"] = "closed"
        state["closed_by"] = payload.closed_by
        state["closed_reason"] = payload.reason
        state["resolved_by"] = payload.resolved_by
        await self._write_issue(conn, event.subject, state, event.actor, event.ts)

    async def _apply_issue_superseded(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:
        """Mark an issue superseded."""
        state = await self._read_issue(conn, event.subject)
        if state is None:
            return
        state["status"] = "superseded"
        await self._write_issue(conn, event.subject, state, event.actor, event.ts)

    async def _apply_issue_unclaimed(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:
        """Revert ``claimed -> open`` and clear ``claimed_by``; any other status is a no-op.

        Reverse of :meth:`_apply_issue_claimed` (FEAT-572 Module 2): a page that is
        ``open``, ``closed``, ``superseded`` or missing is left untouched.
        """
        payload = IssueUnclaimedPayload(**event.payload)
        state = await self._read_issue(conn, event.subject)
        if state is None or state.get("status") != "claimed":
            return
        state["status"] = "open"
        state["claimed_by"] = None
        await self._write_issue(conn, event.subject, state, event.actor, event.ts)
        await self.store.add_edges_in(conn, [(event.subject, payload.unclaimed_by, "unclaimed-by", "asserted")])

    # ------------------------------------------------------------------
    # Cursor / replay
    # ------------------------------------------------------------------

    @staticmethod
    async def _write_cursor(conn: "aiosqlite.Connection", line_start: int, event_id: str) -> None:
        """Persist ``(offset, last_event_id)`` — offset is the START of ``event_id``'s own line."""
        await conn.execute(
            "INSERT OR REPLACE INTO ledger_state (key, value) VALUES ('cursor_offset', ?)",
            (str(line_start),),
        )
        await conn.execute(
            "INSERT OR REPLACE INTO ledger_state (key, value) VALUES ('last_event_id', ?)",
            (event_id,),
        )

    async def sync(self, conn: "aiosqlite.Connection | None" = None) -> int:
        """Apply events after the persisted cursor up to the log tip; advance the cursor.

        Args:
            conn: An already-open write connection (reused by ``claim_issue``);
                when ``None``, a dedicated ``ledger.sync`` transaction is opened.

        Returns:
            Number of events applied.
        """
        if conn is not None:
            applied, _offset, _event_id = await self._sync_locked(conn)
            return applied
        async with self.store.ledger_transaction("ledger.sync") as new_conn:
            applied, _offset, _event_id = await self._sync_locked(new_conn)
            return applied

    async def _sync_locked(self, conn: "aiosqlite.Connection") -> tuple[int, int, str | None]:
        """Read the persisted cursor and apply forward from it to the log tip.

        Returns:
            ``(applied_count, cursor_offset, cursor_event_id)`` reflecting
            where replay stopped — always the current tip, whether or not
            anything was actually applied (unchanged cursor when nothing
            new was found). The cursor is already persisted for this
            connection's transaction when ``applied_count > 0``.
        """
        offset, last_event_id = await self.store.read_cursor()
        return await self._apply_from(conn, offset, last_event_id)

    async def _apply_from(
        self, conn: "aiosqlite.Connection", offset: int, last_event_id: str | None
    ) -> tuple[int, int, str | None]:
        """Validate ``(offset, last_event_id)`` against the log, then apply forward to the tip.

        Never re-reads the cursor from storage — callers (like
        :meth:`claim_issue`) that need to continue a scan from a position
        established earlier IN THE SAME transaction pass it in directly,
        since ``read_cursor()`` uses a separate connection that cannot see
        this transaction's own uncommitted cursor advance.

        Returns:
            ``(applied_count, cursor_offset, cursor_event_id)``. The
            cursor is persisted (via ``_write_cursor``) only when
            ``applied_count > 0``; callers doing a second, chained pass
            (``claim_issue``) persist the final combined result themselves.
        """
        # `LedgerLog.iter_events` does blocking file I/O (plain `open()` +
        # `readline()`) — reading it off-thread keeps this coroutine from
        # blocking the event loop other concurrent agent sessions share
        # (e.g. via the MCP server). The whole tail is materialized in one
        # thread hop rather than per-line, since the loop below interleaves
        # each event with `await self.apply_event(...)` (async DB work) and
        # can't run inside the same thread-pool call.
        events_list: list[tuple[LedgerEvent, int]] = await asyncio.to_thread(
            lambda: list(self.log.iter_events(from_offset=offset))
        )
        events = iter(events_list)

        if last_event_id is not None:
            try:
                first_event, _first_line_start = next(events)
            except StopIteration:
                first_event = None
            if first_event is None or first_event.event_id != last_event_id:
                # The event the cursor points at is gone or changed — the log
                # is no longer contiguous with what we last saw. Full rebuild.
                # `_rebuild_locked` returns its own resulting cursor directly
                # rather than this reading it back via `read_cursor()`, which
                # uses a separate connection and cannot see `conn`'s own
                # still-uncommitted write.
                return await self._rebuild_locked_with_cursor(conn)
            # first_event matches what we last applied; it is not reapplied.
        elif offset != 0:
            # A stored offset without a last_event_id is not a valid cursor.
            return await self._rebuild_locked_with_cursor(conn)

        applied = 0
        cursor_line_start = offset
        cursor_event_id = last_event_id
        for event, line_start in events:
            await self.apply_event(event, conn)
            applied += 1
            cursor_line_start = line_start
            cursor_event_id = event.event_id

        if applied:
            await self._write_cursor(conn, cursor_line_start, cursor_event_id)
        return applied, cursor_line_start, cursor_event_id

    async def rebuild(self) -> int:
        """Wipe pages/edges/ledger_state and replay the entire event log from offset 0.

        Returns:
            Number of events applied.
        """
        async with self.store.ledger_transaction("ledger.rebuild") as conn:
            return await self._rebuild_locked(conn)

    async def _rebuild_locked(self, conn: "aiosqlite.Connection") -> int:
        """Do the actual rebuild work inside an already-open write transaction."""
        applied, _offset, _event_id = await self._rebuild_locked_with_cursor(conn)
        return applied

    async def _rebuild_locked_with_cursor(self, conn: "aiosqlite.Connection") -> tuple[int, int, str | None]:
        """Do the rebuild work and return the resulting cursor directly.

        Used by :meth:`_apply_from` so a caller chaining a second pass in
        the same transaction (``claim_issue``) never has to read the
        cursor back through a separate connection, which cannot see this
        transaction's own still-uncommitted write.
        """
        await conn.execute("DELETE FROM pages")
        await conn.execute("DELETE FROM edges")
        await conn.execute("DELETE FROM ledger_state")

        # See `_apply_from`'s comment: materialize off-thread, then apply
        # in-loop so each event can still `await` its DB write.
        events_list: list[tuple[LedgerEvent, int]] = await asyncio.to_thread(
            lambda: list(self.log.iter_events(from_offset=0))
        )

        applied = 0
        cursor_line_start = 0
        cursor_event_id: str | None = None
        for event, line_start in events_list:
            await self.apply_event(event, conn)
            applied += 1
            cursor_line_start = line_start
            cursor_event_id = event.event_id

        if applied:
            await self._write_cursor(conn, cursor_line_start, cursor_event_id)
        return applied, cursor_line_start, cursor_event_id

    # ------------------------------------------------------------------
    # Atomic claim
    # ------------------------------------------------------------------

    async def claim_issue(self, issue_id: str, claimed_by: str) -> bool:
        """Atomically claim an open issue.

        Runs entirely under one ``store.ledger_transaction("ledger.claim")``:

        1. ``sync(conn)`` — catch up with events other writers appended
           since our last read.
        2. Check ``status == "open"`` — otherwise return ``False`` without
           appending anything (first claim in log order wins).
        3. Append ``issue.claimed`` to the log.
        4. Apply forward from where step 1 stopped, all the way to
           whatever is now the log tip, and advance the cursor to that —
           never to just this event's own reported offset (see note below)
           — then commit.

        A ``WikiStoreBusy`` raised while acquiring the transaction propagates
        unchanged and unwinds before step 3 — a busy claim appends nothing.

        Step 4 deliberately does not trust ``LedgerLog.append()``'s own
        returned offset as the new cursor position. That offset is computed
        via a separate ``lseek`` then ``write``, which is not atomic across
        processes — a concurrent writer's own append can land in between,
        so this event's *reported* offset can be earlier than another
        event's *actual* file position. Setting the cursor from a single
        event's self-reported offset could then jump the cursor past that
        concurrent event without ever applying it. Re-scanning forward from
        step 1's stopping point to the tip instead means "the tip" is
        whatever is physically in the file when we look, including any
        such concurrent append — nothing is skipped.

        Args:
            issue_id: Issue to claim, e.g. ``issue:3f8a1c9e``.
            claimed_by: Claimant identifier, e.g. ``task:TASK-3205``.

        Returns:
            ``True`` if this call claimed the issue, ``False`` if it was
            already claimed or closed/superseded.
        """
        async with self.store.ledger_transaction("ledger.claim") as conn:
            _applied, offset, last_event_id = await self._sync_locked(conn)

            state = await self._read_issue(conn, issue_id)
            if state is None or state.get("status") != "open":
                return False

            event = LedgerEvent(
                kind="issue.claimed",
                subject=issue_id,
                actor=claimed_by,
                payload={"claimed_by": claimed_by},
            )
            # LedgerLog.append() is a blocking syscall sequence
            # (open/lseek/write/fsync) — off-thread so it never blocks the
            # event loop while this transaction is held open.
            await asyncio.to_thread(self.log.append, event)
            await self._apply_from(conn, offset, last_event_id)
            return True

    # ------------------------------------------------------------------
    # Compaction (index-only; never rewrites events.jsonl)
    # ------------------------------------------------------------------

    async def compact(self, older_than_days: int = 30) -> int:
        """Fold closed/superseded issues older than ``older_than_days`` into summary pages.

        Never rewrites or truncates ``events.jsonl`` — compaction only
        shrinks the materialized index's ``body`` payload for old, resolved
        issues; the durable log remains the full source of truth.

        Args:
            older_than_days: Age threshold, compared against the issue
                page's ``updated_at``.

        Returns:
            Number of issue pages folded.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        folded = 0
        async with self.store.ledger_transaction("ledger.compact") as conn:
            async with conn.execute("SELECT concept_id, body, updated_at FROM pages WHERE category = 'issue'") as cur:
                rows = await cur.fetchall()

            for concept_id, body, updated_at in rows:
                state = _decode_issue_body(body)
                if not state or state.get("status") not in ("closed", "superseded"):
                    continue
                if state.get("compacted"):
                    continue
                if not updated_at or updated_at >= cutoff:
                    continue

                compact_state = {
                    "title": state.get("title", ""),
                    "body": "",
                    "status": state.get("status"),
                    "kind": state.get("kind"),
                    "severity": state.get("severity"),
                    "acknowledged": state.get("acknowledged", False),
                    "discovered_from": state.get("discovered_from"),
                    "about": state.get("about", []),
                    "claimed_by": state.get("claimed_by"),
                    "closed_by": state.get("closed_by"),
                    "closed_reason": state.get("closed_reason"),
                    "resolved_by": state.get("resolved_by"),
                    "compacted": True,
                }
                await self._write_issue(conn, concept_id, compact_state, "agent:ledger-compact", updated_at)
                folded += 1

        return folded
