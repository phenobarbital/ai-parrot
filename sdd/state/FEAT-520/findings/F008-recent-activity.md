# F008 — Recent activity: schema v2 symbols just landed; commit protocol on both backends; no in-flight postgres work
**Query**: Q013 | **Confidence**: high

- wiki/ last 8 weeks: dominated by `ast-grep-for-wikitoolkit` (TASK-2742..2751) — store schema v2 (`content_hash`, `symbols` table, symbol methods on every backend, b0db0f181), sym: pages, StructuralService. A new wiki backend must account for the symbol surface (or gracefully skip like Arango).
- graphindex/ last 8 weeks: `b312160ef` ArangoDB implementation of the graph commit protocol; PageRank centrality fix; Obsidian loader bridge (FEAT-392).
- No branch/commit references a Postgres graphindex/wiki backend — greenfield, no collision.
