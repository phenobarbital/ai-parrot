---
id: F002
query_id: Q014
type: read
intent: "Read the ledger index: table DDL, reducers, migration/versioning pattern a usage plane must follow."
executed_at: 2026-10-30T22:38:40Z
duration_ms: 420
parent_id: null
depth: 0
lane: codebase
merged_from: ['FC-002']
---

# F002 — The ledger index has no per-plane tables: it reduces events into wiki `pages` rows with JSON-in-body

## Summary

`LedgerIndex` does **not** own any domain tables. It reduces events into
`WikiPageRecord` rows written to the shared wiki `pages` table with
`category="issue"`, encoding the whole issue state as a one-line JSON object
inside an HTML comment in the `body` column (`_STATE_PREFIX = "<!--ledger-state "`,
index.py:43-44; `_write_issue`, index.py:138-161). The **only** DDL in the entire
ledger package is the two-column `ledger_state` key/value cursor table
(store.py:67-72) — confirmed by a package-wide grep that returns exactly one
`CREATE TABLE` and zero `CREATE INDEX`. There is therefore **no schema-migration
pattern for a plane to follow**: the source document's premise that `ledger.db`
"indexes a plane" with its own tables, and that a usage plane would add "index
tables in ledger.db", describes a facility that does not exist today.
`apply_event` dispatches on six `issue.*` kinds only and **silently ignores
unknown kinds** (index.py:114-128) — so adding `usage.*` to the `Literal` without
a reducer branch would be accepted by the log and invisible to the index.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py`
  lines: 65-73
  symbol: `LedgerStore.ledger_transaction`
  excerpt: |
    async with self._write(operation) as conn:
        # Create ledger_state table on first use if it doesn't exist
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ledger_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        yield conn

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py`
  lines: 107-128
  symbol: `LedgerIndex.apply_event`
  excerpt: |
    if event.kind == "issue.opened":
        await self._apply_issue_opened(event, conn)
    ...
    # task.*, spec.*, insight.* reduction is out of this task's scope
    # (Modules 7/8/12); unknown kinds are ignored rather than raising so
    # replay never breaks on a future event kind it doesn't own yet.

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py`
  lines: 146-161
  symbol: `LedgerIndex._write_issue`
  excerpt: |
    page = WikiPageRecord(
        concept_id=issue_id,
        title=state.get("title", ""),
        category="issue",
        summary=summary,
        body=_encode_issue_body(state),
        ...
    )
    await self.store.upsert_pages_in(conn, [page])

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py`
  lines: 536-549
  symbol: `LedgerIndex.compact`
  excerpt: |
    async def compact(self, older_than_days: int = 30) -> int:
        """Fold closed/superseded issues older than ``older_than_days`` into summary pages.

        Never rewrites or truncates ``events.jsonl`` — compaction only
        shrinks the materialized index's ``body`` payload for old, resolved
        issues; the durable log remains the full source of truth.
        """

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py`
  lines: 552-563
  symbol: `LedgerIndex.compact`
  excerpt: |
    async with conn.execute("SELECT concept_id, body, updated_at FROM pages WHERE category = 'issue'") as cur:
        rows = await cur.fetchall()
    for concept_id, body, updated_at in rows:
        state = _decode_issue_body(body)
        if not state or state.get("status") not in ("closed", "superseded"):
            continue

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py`
  lines: 256-265
  symbol: `LedgerIndex._write_cursor`
  excerpt: |
    await conn.execute(
        "INSERT OR REPLACE INTO ledger_state (key, value) VALUES ('cursor_offset', ?)",
        (str(line_start),),
    )

## Notes

- **The existing `compact()` cannot be "extended" to roll usage rows into totals.** It
  is hard-scoped to `category = 'issue'` and to `status in ('closed','superseded')`, and
  it only blanks the `body` text. Per-attempt rollup of usage rows is new code, not a
  parameter.
- **`compact()` never truncates `events.jsonl`.** Combined with per-request usage events,
  the shared append-only log grows without bound and is replayed from a byte cursor on
  every `sync()` (index.py:267-295). One `rebuild()` (index.py:357) re-reads the whole log.
  This is a volume constraint the source does not account for.
- `LedgerIndex` imports only `Issue*Payload` models (index.py:21-28) — the reducer's
  surface is issue-shaped end to end.
- [cross-lane: type=git_log, intent=did any commit ever add a non-issue reducer branch or a second ledger table?]
