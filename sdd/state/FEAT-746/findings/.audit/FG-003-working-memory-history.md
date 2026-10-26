---
id: FG-003
query_id: Q053
type: git_log
intent: "Recent history: WorkingMemory toolkit."
executed_at: 2026-10-25T22:40:29Z
duration_ms: 400
parent_id: null
depth: 0
---

# FG-003 — WorkingMemory toolkit: large rebuild in Sep 2026 (durable journal, artifact blob I/O, bounded recall)

## Summary

~25 commits on `parrot/tools/working_memory/` in 120 days, almost all on 2026-09-08/09 as the "workingmemory-toolkit" feature (TASK-2977…3004): awaited catalog API with shared entry descriptors, atomic in-memory journal + projections, durable task journal with reducer projections, PostgreSQL migrations + transaction coordinator, **bounded immutable artifact blob I/O (TASK-2996)**, deterministic bounded recall selection, bounded recall reads/cache/omission probes, durable aliases/versions/evidence pins, retention decisions and sweeping, fenced call ownership + crash reconciliation, durable backend lifecycle. One later touch (plan-then-execute-hardening, 09-22). The toolkit is recent, large, and already has entry descriptors, an artifact blob layer and bounded reads — the natural landing zone for handle + descriptor + provenance (D5).

## Citations

- path: `packages/ai-parrot/src/parrot/tools/working_memory/`
  commit: `4eb5769181` 2026-09-22 Jesus — feat(plan-then-execute-hardening): TASK-3592 — engine-committed coder deliverable
- path: `packages/ai-parrot/src/parrot/tools/working_memory/`
  commit: `ec59fa5707` 2026-09-09 Jesus Lara — feat(workingmemory-toolkit): TASK-3003 — wire durable backend lifecycle and retention scheduling
- path: `packages/ai-parrot/src/parrot/tools/working_memory/`
  commit: `da893d6539` 2026-09-08 Jesus Lara — feat(workingmemory-toolkit): TASK-2985 — Route enabled working-memory operations and cap raw reads
- path: `packages/ai-parrot/src/parrot/tools/working_memory/`
  commit: `2946468743` 2026-09-08 Jesus Lara — feat(workingmemory-toolkit): TASK-2988 — Add bounded recall reads, cache and omission probes
- path: `packages/ai-parrot/src/parrot/tools/working_memory/`
  commit: `44a512e33a` 2026-09-08 Jesus Lara — feat(workingmemory-toolkit): TASK-2996 — Implement bounded immutable artifact blob I/O
- path: `packages/ai-parrot/src/parrot/tools/working_memory/`
  commit: `29901b2605` 2026-09-08 Jesus Lara — feat(workingmemory-toolkit): TASK-2994 — Define PostgreSQL migrations and shared transaction coordinator
- path: `packages/ai-parrot/src/parrot/tools/working_memory/`
  commit: `28bc9a8c34` 2026-09-08 Jesus Lara — feat(workingmemory-toolkit): TASK-2977 — Add awaited catalog API and shared entry descriptors
- path: `packages/ai-parrot/src/parrot/tools/working_memory/`
  commit: `a2381e729f` 2026-09-08 Jesus Lara — feat(workingmemory-toolkit): TASK-2997 — Implement atomic durable aliases, versions and evidence pins

## Notes

The brainstorm's VERIFY line "WorkingMemory holds values; no handle + descriptor + provenance structure, no blob store abstraction" is partly contradicted by history: TASK-2996 "bounded immutable artifact blob I/O" and TASK-2977 "shared entry descriptors" exist. [cross-lane: type=read, intent=read the working_memory artifact blob I/O module (TASK-2996) and entry descriptor model (TASK-2977) to compare with the handle/descriptor/provenance triple]
