---
id: F030
query_id: Q046
type: git_log
intent: "History of parrot.human — is the HITL approval surface active or dormant?"
executed_at: 2026-11-07T01:19:11Z
duration_ms: 600
parent_id: null
depth: 0
merged_from: [FG-005]
---

# F030 — parrot.human: 7 commits, all 2026-05-28 → 2026-06-01; dormant for 5 months

## Summary

`packages/ai-parrot-integrations/src/parrot/human/` has 7 commits in the 180-day window, all clustered in four days (2026-05-28..06-01): the satellite scaffold (`7b57cd410c`), Human Channels extraction + `ChannelRegistry` (`2f43d7154a`), the Teams HITL channel (`eac3decef6`, `b4945da8e1`, review fixes `e58d308ff6`) and Telegram voice-note HITL (`bcecdae2a5`, `fc6448af80`). Nothing since. The HITL approval transport exists (Teams + Telegram channels behind a registry) but has not been touched in five months — a v1 escrow should treat it as available-but-unverified and keep the host-side `/sdd-escrow approve|reject` fallback.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/human/`
  symbol: `2f43d7154a`
  excerpt: |
    2f43d7154a 2026-05-28 Jesus feat(ai-parrot-integrations): TASK-1352 — Human Channels Extraction + ChannelRegistry
    7b57cd410c 2026-05-28 Jesus feat(ai-parrot-integrations): TASK-1344 — Satellite Package Scaffold
- path: `packages/ai-parrot-integrations/src/parrot/human/`
  symbol: `eac3decef6`
  excerpt: |
    eac3decef6 2026-05-29 Jesus Lara feat(hitl-teams-channel): TASK-005 — TeamsHumanChannel assembly + inbound demux + registry
    b4945da8e1 2026-05-29 Jesus Lara feat(hitl-teams-channel): TASK-006 — setup_teams_hitl boot helper, per-agent override & docs
    e58d308ff6 2026-05-29 Jesus Lara fix(hitl-teams-channel): address code review issues (security, race condition, resource cleanup)
- path: `packages/ai-parrot-integrations/src/parrot/human/`
  symbol: `fc6448af80`
  excerpt: |
    bcecdae2a5 2026-05-30 Claude fix(telegram-hitl): add voice-note support for HITL free-text interactions
    fc6448af80 2026-06-01 Jesus fix(telegram-hitl): harden voice-note HITL handler from code review

## Notes

- Symbols named in commit messages: `ChannelRegistry`, `TeamsHumanChannel`, `setup_teams_hitl`. [cross-lane: type=grep, intent=confirm these symbols still exist under parrot/human and what an approval request/decision round-trip looks like]
