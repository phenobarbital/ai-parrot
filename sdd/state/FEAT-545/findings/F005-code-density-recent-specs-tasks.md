---
id: F005
query_id: Q017
type: tree
intent: Measure how much code recent specs and task files already carry
executed_at: 2026-09-10T01:00:00Z
duration_ms: 300
parent_id: null
depth: 0
---

# F005 — Code density is inconsistent: specs range 0–384 fenced lines; newest task file has 1

## Summary

Counting lines inside ``` fences (awk) over the six newest specs and the newest active task: specs vary from 0 to 384 code lines (0–44 % of the document), showing that "no implementation code" is already applied unevenly and author-dependent. The newest active task file (TASK-3056, 113 lines) carries a single fenced line. So the request is not "allow code" (it already happens) but "make explained code a *required, structured* deliverable".

## Citations

- path: `sdd/specs/graphindex-core-seams.spec.md`
  lines: 1-866
  excerpt: |
    total=866 code_fence_lines=274
- path: `sdd/specs/parrot-graphindex-package.spec.md`
  lines: 1-653
  excerpt: |
    total=653 code_fence_lines=110
- path: `sdd/specs/contracts-card-ontology.spec.md`
  lines: 1-512
  excerpt: |
    total=512 code_fence_lines=0
- path: `sdd/specs/workingmemory-toolkit.spec.md`
  lines: 1-443
  excerpt: |
    total=443 code_fence_lines=24
- path: `sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md`
  lines: 1-878
  excerpt: |
    total=878 code_fence_lines=384
- path: `sdd/specs/wikitoolkit-cli-llm-fallback.spec.md`
  lines: 1-433
  excerpt: |
    total=433 code_fence_lines=83
- path: `sdd/tasks/active/TASK-3056-contracts-pilot-signoff.md`
  lines: 1-113
  excerpt: |
    lines=113 code=1  (sections: Context, Scope, Files, Codebase Contract, Implementation Notes, Acceptance Criteria, Test Specification, Agent Instructions, Completion Note)
