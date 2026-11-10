---
id: F014
query_id: Q001, Q002
type: wiki_query
intent: "Orient: locate CrewRedis and crew-definition persistence in the knowledge graph."
executed_at: 2026-11-09T17:13:05Z
duration_ms: 650
parent_id: null
depth: 1
merged_from: [FW-001, FW-004]
---

# F014 — Crew-definition persistence is a single Redis module plus two READMEs and one example

## Summary

[FW-001] `wikitoolkit query "CrewRedis crew definition persistence"` ranks only Redis-backed artefacts: the module
`redis_persistence.py`, two READMEs in the same directory, an example script and one test pinning legacy
payload compatibility. No Postgres (or any other) store for crew *definitions* appears in the top 19 results.
BotManager's `enable_crews` flag (FEAT-042, TASK-283/288) is the only gate around it.

[FW-004] `wiki_decisions_for_symbol("CrewRedis")` returned `status: empty` — no documented decisions and no inferred
candidates. Nothing in the decision plane fixes Redis as the required store for crew definitions, so a
Postgres backend does not supersede a recorded decision; the proposal would be the first one.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  symbol: `CrewRedis`
  lines: 17-17
  excerpt: |
    wiki page file:…/redis_persistence.py (score=27.11) — "Redis Persistence for AgentsCrew Definitions."

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/README_REDIS_PERSISTENCE.md`
  excerpt: |
    wiki page score=34.76 — "Redis Persistence for AgentsCrew"

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md`
  excerpt: |
    wiki page score=27.91 — "AgentsCrew Redis Persistence - Integrated into BotManager"

- path: `examples/crew/redis_persistence_example.py`
  excerpt: |
    wiki page score=29.64 — "Example: Redis Persistence for AgentsCrew"

- path: `packages/ai-parrot-server/tests/unit/test_crew_redis_legacy_payloads.py`
  excerpt: |
    wiki page score=28.19 — "``CrewRedis`` must keep already-stored crews loadable."

- path: `packages/ai-parrot/tests/test_botmanager_flags.py`
  excerpt: |
    wiki page score=21.00 — "Unit tests for BotManager initialization flags (FEAT-042)."

- path: `sdd/specs/decoupling-db-bots-botmanager.spec.md`
  excerpt: |
    wiki page score=16.96 — "BotManager Initialization Flags Decoupling"

## Notes

[FW-001] Both READMEs and the example are documentation a new backend would have to update.
[cross-lane: type=read, intent=read README_REDIS_PERSISTENCE.md / README_BOTMANAGER_PERSISTENCE.md (Q015)]

[FW-004] A spec for this feature should add a Decisions block (sym: targets) so the choice is recorded.
