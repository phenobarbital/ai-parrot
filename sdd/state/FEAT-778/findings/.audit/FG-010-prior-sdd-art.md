---
id: FG-010
query_id: Q068-spare
type: git_log
intent: "Prior SDD art (specs/proposals) about skills, personas, experts, identity, knowledge, ADRs — avoid duplicating an open spec."
executed_at: 2026-10-30T16:41:30Z
duration_ms: 300
parent_id: null
depth: 0
---

# FG-010 — Prior SDD art: the source proposal is ALREADY committed on dev (2f8d4c397, 2026-10-30); related specs FEAT-707 per-tenant-skills, FEAT-760 adr-prefixed-aliases, promptbuilder-identity-capability

## Summary

Filtered 180-day log over `sdd/specs` + `sdd/proposals` (20 hits). Most important: commit `2f8d4c397` "delegated auth + domain experts" (2026-10-30, Jesus Lara) committed `sdd/proposals/domain-experts.proposal.md` (302 lines, the research source) together with the FEAT-773 spec status flip — so the source file is tracked on dev, and the enriched proposal will be a modification, not an addition. Related, already-approved work: FEAT-707 per-tenant-skills (brainstorm → spec → approved, 2026-10-19), FEAT-760 adr-prefixed-aliases (spec + rev 0.2, 2026-10-27), decisions-cli-fixes (2026-10-15), bookstore-reindex-identity hotfix spec (2026-09-30). No spec or proposal in the window is titled around experts/personas/domain agents other than the source itself.

## Citations

- path: `sdd/proposals/domain-experts.proposal.md`
  lines: 1-302
  symbol: (source document)
  excerpt: |
    2f8d4c397 2026-10-30 Jesus Lara delegated auth + domain experts
     sdd/proposals/domain-experts.proposal.md     | 302 +++++++++++++++++++++++++++
     sdd/specs/delegated-auth-connections.spec.md |   2 +-

- path: `sdd/specs/per-tenant-skills.spec.md`
  lines: n/a
  symbol: FEAT-707
  excerpt: |
    93b1ddc4e 2026-10-19 sdd: approve spec for FEAT-707 — per-tenant-skills
    228f65387 2026-10-19 sdd: add spec for FEAT-707 — per-tenant-skills
    c588e1ec3 2026-10-19 sdd: accept brainstorm for per-tenant-skills

- path: `sdd/specs/adr-prefixed-aliases.spec.md`
  lines: n/a
  symbol: FEAT-760
  excerpt: |
    7ea2e0c53 2026-10-27 sdd: FEAT-760 spec rev 0.2 — resolve Q1/Q2/Q3 for adr-prefixed-aliases
    64033ece1 2026-10-27 sdd: add spec for FEAT-760 — adr-prefixed-aliases

- path: `sdd/specs/`
  lines: n/a
  symbol: other hits
  excerpt: |
    526d45c8e 2026-10-15 sdd: spec and tasks for decisions-cli-fixes
    c78f0f06f 2026-09-30 sdd: approve spec for bookstore-reindex-identity
    d3bfed498 2026-10-23 sdd: approve FEAT-735 and resolve Q1/Q2 — Identity Vault owns, Redis caches  (auth identity, unrelated)

## Notes

- Parent action item: `git status` in the parent showed the proposal as untracked at session start; it is now committed by a parallel session (2f8d4c397). "Rewrite in place" therefore modifies a tracked file — stage it with `git add sdd/proposals/domain-experts.proposal.md` as usual, no collision.
- The spec paths above (`per-tenant-skills.spec.md`, `adr-prefixed-aliases.spec.md`) are inferred from commit messages, not from a file listing — verify before citing as paths.
- [cross-lane: type=wiki_page, intent=file:sdd/specs/promptbuilder-identity-capability.spec.md (already Q002) and sdd/specs/per-tenant-skills.spec.md — shadowing rules to reuse for experts]
