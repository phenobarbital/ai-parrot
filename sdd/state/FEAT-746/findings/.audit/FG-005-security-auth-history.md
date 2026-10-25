---
id: FG-005
query_id: Q055
type: git_log
intent: "Recent history: security + auth (PBAC, tokens)."
executed_at: 2026-10-25T22:41:57Z
duration_ms: 350
parent_id: null
depth: 0
---

# FG-005 — security/auth history: very active (vault token sync, Teams user-auth lane, PBAC scope enforcement, OAuth 3LO); no capability tokens

## Summary

20+ commits in 120 days on `parrot/security/` + `parrot/auth/`. Themes: Identity Vault / Token Service propagation (FEAT-735, 10-23), MS Teams user-auth lane with a fail-closed gate and single-use approval token (10-23, 10-02), PBAC declaration fix (10-14) and "scope enforcement in core; gates moved out of abstract/confirmation" (TASK-3989, 10-02), prompt-injection ThreatLevel ordering (10-22), Jira 3LO OAuth helpers (10-16). All tokens seen are OAuth/bearer/approval tokens; nothing in history mentions Biscuit, macaroons or attenuated delegation — consistent with the brainstorm's VERIFY line that attenuation is not implemented.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/`
  commit: `e8f043d0f5` 2026-10-23 Jesus Lara — feat(services-vault-token-sync-tech-debt): TASK-4668 — propagate a refreshed Jira grant to the Identity Vault
- path: `packages/ai-parrot/src/parrot/security/`
  commit: `0ee1f6a371` 2026-10-23 Jesus — fix(msteams-user-auth-lane): TASK-4660 TASK-4661 TASK-4663 review fixes — fail-closed gate, exchange hardening, Token Service user id
- path: `packages/ai-parrot/src/parrot/security/`
  commit: `94a516c3e2` 2026-10-22 Jesus Lara — feat(builtin-prompt-injection-fixes): TASK-4563 — total ordering for ThreatLevel
- path: `packages/ai-parrot/src/parrot/security/`
  commit: `51885b4bea` 2026-10-14 Jesus Lara — fix pbac declaration
- path: `packages/ai-parrot/src/parrot/security/`
  commit: `fd65a553e3` 2026-10-02 revbot — feat(agentstudio-host-toolkits): TASK-3989 — scope enforcement in core; gates moved out of abstract/confirmation; resolver rule 5 lifted
- path: `packages/ai-parrot/src/parrot/security/`
  commit: `def3eaf95a` 2026-10-02 revbot — fix(agentstudio-host-toolkits): the approval token is single-use
- path: `packages/ai-parrot/src/parrot/auth/`
  commit: `4b2d17b0a2` 2026-10-16 Jesus — feat(jiratoolkit-upgrades): TASK-4418 — extract 3LO OAuth helpers

## Notes

TASK-3989 "scope enforcement in core; gates moved out of abstract/confirmation" is the most relevant commit for D11 (policy enforced at tool execution): there is already a scope/approval gate in core tool execution. [cross-lane: type=read, intent=read the scope-enforcement gate introduced by TASK-3989 in parrot/security or parrot/tools to see what it keys on]
