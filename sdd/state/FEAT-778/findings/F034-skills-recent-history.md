---
id: F034
query_id: Q063
type: git_log
intent: "Recent activity on skills (bundle loader, tenancy)."
executed_at: 2026-10-30T16:41:30Z
duration_ms: 350
parent_id: null
depth: 0
merged_from: [FG-004-skills-recent-history]
---

# F034 — skills/: 15 commits in 90 days; FEAT-707 per-tenant skills (2026-10-19/20) is the freshest directory-bundle + shadowing precedent

## Summary

15 commits, 2026-10-19 → 2026-10-28, all Jesus Lara / Jesus. Dominant theme FEAT-707 per-tenant skills (TASK-4499/4501/4503/4504/4507 + review fixes): `SkillRegistryMixin` consumer wiring (providers, prompt layers, active skill, learned refresh — 54b5c1b7f2 touched only `skills/mixin.py` +120 lines and a 206-line test), tenant views shadowing the global tree, hardening of tenant layers (toolless tenant layers, empty tenant id, `_tenant_views` tolerance). Later: TASK-4795/4796 followup-suggestion-chips added a "request-local turn skill"; TASK-4544 telemetry fan-out and TASK-4759 a2ui routing touched skills tangentially. The skills subsystem is the most recent, most complete analogue of "directory bundle + manifest + prompt layer + workspace-over-package precedence".

## Citations

- path: `packages/ai-parrot/src/parrot/skills/mixin.py`
  lines: n/a
  symbol: `SkillRegistryMixin`
  excerpt: |
    54b5c1b7f2 2026-10-19 Jesus Lara feat(per-tenant-skills): TASK-4503 — SkillRegistryMixin consumer wiring (providers, prompt layers, active skill, learned refresh)
     packages/ai-parrot/src/parrot/skills/mixin.py | 120 ++++++++++--
     .../tests/unit/test_skill_tenant_wiring.py    | 206 +++++++++++++++++++++

- path: `packages/ai-parrot/src/parrot/skills/tenancy.py`
  lines: n/a
  symbol: tenant views
  excerpt: |
    22eb900e1c 2026-10-20 Jesus Lara feat(per-tenant-skills): TASK-4507 — tenant skill hardening (issue:8ea16e60de56)
     skills/mixin.py +18/-, skills/prompt.py +37/-, skills/tenancy.py +15, bots/prompts/layers.py (literal flag), bots/base.py
    480a9094c6 2026-10-20 fix(per-tenant-skills): review fixes — toolless tenant layers, empty tenant id
    11ae940e65 2026-10-20 fix(skills): tolerate missing _tenant_views in _configure_skill_file_registry

- path: `packages/ai-parrot/src/parrot/skills/`
  lines: n/a
  symbol: commits
  excerpt: |
    846922b73c 2026-10-28 feat(followup-suggestion-chips): TASK-4795 — request-local turn skill
    c9a8309410 2026-10-28 feat(followup-suggestion-chips): TASK-4796
    bee4b82582 2026-10-22 feat(parrot-telemetry-event-fanout): TASK-4544
    711408edfc 2026-10-20 feat(per-tenant-skills): TASK-4504; 55535402f0 2026-10-19 TASK-4501; 7577c5376e 2026-10-19 TASK-4499

## Notes

- FEAT-707 solved the exact "workspace shadows package by name" question for skills (tenant tree shadows global `skills/`, `global_only` cannot be shadowed). The expert bundle location question (U: `experts/` in package vs `.parrot/experts/`) has a direct precedent.
- Skill prompt text is injected as `literal` layers (untrusted authored text). A persona layer should follow the same rule.
- [cross-lane: type=read, intent=skills/tenancy.py + skills/prompt.py — how tenant views shadow global skills and how skill layers are built]
