---
id: FC-022
query_id: Q037
type: read
intent: "Read the hitl-escalation-tier spec header: the escalation model a verdict agent could reuse for ESCALATE_HITL."
executed_at: 2026-11-07T01:26:34Z
duration_ms: 1200
parent_id: null
depth: 0
---

# FC-022 — FEAT-194 (approved): multi-tier HITL escalation with per-tier channels, timeouts, severity gating and hitl.tier.* telemetry events

## Summary

`sdd/specs/hitl-escalation-tier.spec.md` (FEAT-194, approved; brainstorm `sdd/proposals/hitl-escalation-tier.brainstorm.md`; companion `documentation/hitl_tiered_escalation_example.md`) describes the tiered escalation implemented in FC-014: the manager advances tiers on `TimeoutAction.ESCALATE` (`manager._escalate_to_next_tier`), tracks `HumanInteraction.current_tier_level`, selects a starting tier by severity (`_select_starting_tier(policy, severity)`), skips off-hours tiers, renders reject buttons in `TelegramHumanChannel`, and emits `hitl.tier.entered`, `hitl.tier.advanced`, `hitl.tier.action_executed`, `hitl.tier.action_failed` events. This is a server-side, async, channel-driven model (Telegram, Web); an escrow ESCALATE_HITL in a host CLI context would either run the manager in-process (needs channel config) or fall back to a notification + `/sdd-escrow approve|reject` ledger write.

## Citations

- path: `sdd/specs/hitl-escalation-tier.spec.md`
  lines: 7-12
  symbol: null
  excerpt: |
    # Feature Specification: HITL Multi-Tier Escalation Policy (per-policy_id registry + gap completion)
    **Feature ID**: FEAT-194
    **Status**: approved

- path: `sdd/specs/hitl-escalation-tier.spec.md`
  lines: 46-51
  symbol: null
  excerpt: |
      `manager._escalate_to_next_tier` advances on `TimeoutAction.ESCALATE`.
      `HumanInteraction.current_tier_level` runtime fields.

- path: `sdd/specs/hitl-escalation-tier.spec.md`
  lines: 76-80
  symbol: null
  excerpt: |
        + optional per-tier `min_severity` mapping in `EscalationTier`.
        `_select_starting_tier(policy, severity)` picks the starting tier.
        (tz + days + hours window). Off-hours tiers are skipped at

- path: `sdd/specs/hitl-escalation-tier.spec.md`
  lines: 95-100
  symbol: null
  excerpt: |
    - Emit structured tier-transition events on the existing
      `hitl.tier.entered`, `hitl.tier.advanced`,
      `hitl.tier.action_executed`, `hitl.tier.action_failed`,

## Notes

- Only lines 1-100 read (header, goals). Implementation status of each goal not verified here.
