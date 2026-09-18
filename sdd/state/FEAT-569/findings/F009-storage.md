---
id: F009
query_id: Q009
type: read
intent: Shared-root and durable logging primitives exist
executed_at: 2026-09-17T21:50:09.640444+00:00
duration_ms: null
parent_id: null
depth: 1
---

# F009 — Shared-root and durable logging primitives exist

## Summary

find_shared_root resolves linked worktrees to the common repository root. LedgerLog bounds records to 4096 bytes, writes once under O_APPEND, checks for short writes and fsyncs; its offset is explicitly best-effort under concurrency. These are useful patterns, not a transaction spanning log and memory state. aiosqlite is already a declared core dependency. No fsrs match appeared in the searched workspace pyproject files; adding an optimizer remains a separate dependency decision.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 1184-1222
  symbol: `find_shared_root`
  excerpt: |
    def find_shared_root(start: Path | None = None) -> Path | None:
        """Find the shared root directory for parrot state, tolerating failures.

        Walks upward from start to find the Git root, then resolves to the

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py`
  lines: 20-81
  symbol: `LedgerLog.append`
  excerpt: |

        def append(self, event: LedgerEvent) -> tuple[str, int]:
            """Append a single event to the log atomically and durably.


- path: `packages/ai-parrot/pyproject.toml`
  lines: 180-193
  symbol: `core dependencies`
  excerpt: |
        # Episodic memory default backend (FAISS) — required whenever an agent
        # enables episodic memory without an explicit pgvector DSN.
        "faiss-cpu>=1.9.0",
        "navigator-eventbus>=0.2.1",

## Notes

Read-only inspection at dev HEAD 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c. Proposed changes are inferences, not existing APIs. Range excerpts are locators; the summary uses the inspected surrounding range.
