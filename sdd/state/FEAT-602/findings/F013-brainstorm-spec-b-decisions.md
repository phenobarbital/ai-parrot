---
id: F013
query_id: Q014
type: grep
intent: Auto-finance brainstorm: the deferred Spec B / hooba-service-toolkit decisions.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F013 — The brainstorm already fixed Spec B's shape: `parrot_tools/hooba/` HoobaServiceToolkit over BusinessAutomationToolkit, private plans_dir, CLI HITL channel, window 0

## Summary

`sdd/proposals/auto-finance-agent.brainstorm.md`: Spec B = `hooba-service-toolkit` on the BusinessAutomationToolkit operations/plans model, `plans_dir` → private Hooba plans seeded from the hooba_agent assets (OQ2), SUBMIT confirms via ConfirmationGuard before the browser opens with `confirm_window_seconds=0`, dedicated HumanChannel, default CLI channel (OQ6), wiring copied from `agentd/service.py:385-405`. Impact table: `packages/ai-parrot-tools/src/parrot_tools/hooba/` **new**, TOOL_REGISTRY entries, `examples/agents/finance/`. Open item still unchecked: "Locate and share the path of the private hooba_agent assets" — resolved by F007. The brainstorm predates the discovery that Hooba has a public OpenAPI (it states "Hooba no cuenta con API de ningún tipo", FEAT-453 proposal line 45).

## Citations


- path: `sdd/proposals/auto-finance-agent.brainstorm.md`
  lines: 351-358
  symbol: `Spec B decision OQ7`
  excerpt: |
    HoobaServiceToolkit reuses the **BusinessAutomationToolkit operations/plans model**, pointing plans_dir at the user's private Hooba plan directory ... confirm_window_seconds=0 ... default channel: CLI

- path: `sdd/proposals/auto-finance-agent.brainstorm.md`
  lines: 397-401, 415
  symbol: `Impact table`
  excerpt: |
    packages/ai-parrot-tools/src/parrot_tools/hooba/ | new | HoobaServiceToolkit (Spec B) over BusinessAutomationToolkit; private plans_dir stays out-of-repo

- path: `sdd/proposals/auto-finance-agent.brainstorm.md`
  lines: 591-598
  symbol: `resolved/open items`
  excerpt: |
    [x] Private hooba_agent.py to seed the Hooba plans — yes, a private version exists ... [ ] Locate and share the path of the private hooba_agent assets

- path: `sdd/proposals/web-automation-infra.proposal.md`
  lines: 44-48
  symbol: `origin quote`
  excerpt: |
    Hooba no cuenta con API de ningún tipo, así que la automatización ... depende de interacción en browser
