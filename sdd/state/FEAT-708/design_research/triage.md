# Design Research Triage — sdd-proposal-parallel-research

Model: gpt-5.6-luna | Status: completed

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Parent sole state writer (architecture) | CONFIRM | Forks write only finding files; parent aggregates counters and transitions phases — prevents concurrent state.json corruption | §2 Overview, §7 Patterns |
| S2 | Explicit lane state + idempotent resume (risk) | CONFIRM | Per-lane status with query IDs needed for safe partial-lane retry on resume | §2 Overview, §3 M4 |
| S3 | Global deadline + quota semantics (architecture) | CONFIRM | Integer rounding, reserved merge window (~15% of wall_seconds) under single global deadline | §2 Overview, §3 M2 |
| S4 | Partition dependency-safe queries (architecture) | CONFIRM | Wiki chains (wiki_query → wiki_page by ID) must stay in same lane; cross-lane follow-ups recorded as notes, not dropped | §2 Overview, §3 M1 |
| S5 | Lane findings out of Phase 3 input (api) | CONFIRM | Already in brainstorm: lane originals to findings/.audit/, canonical F001+ only in findings/ | §2 Overview, §3 M3 |
| S6 | Dedup by citation identity not file path (alternative) | CONFIRM | Upgrades brainstorm's file-path-only dedup to (path, symbol, line_range) — preserves distinct symbols | §2 Overview, §3 M3 |
| S7 | Capability probe for Agent dispatch (risk) | CONFIRM | Try Agent tool dispatch + catch unavailability error vs static probe; one failed lane retried sequentially | §3 M1, §7 Patterns |
| S8 | Update .agent/workflows twin (risk) | CONFIRM | .agent/workflows/sdd-proposal.md verified to exist — must stay in sync | §3 M5 |
| S9 | Test orchestration invariants (testing) | CONFIRM | Tests for partitioning, quota accounting, resume, dedup, fallback | §4 Test Specification |
| S10 | Minimal lane brief, no raw source (risk) | CONFIRM | Fork prompt carries query list + budget only, not raw user/Jira content | §7 Known Risks |
| S11 | Keep custom budget sequential (api) | CONFIRM | Avoids new per-lane custom semantics; custom profile always runs sequential | §3 M2 |

Summary: **11** confirmed · **0** rejected · **0** escalated.
