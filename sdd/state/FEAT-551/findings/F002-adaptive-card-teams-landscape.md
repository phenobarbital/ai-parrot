---
id: F002
query_id: Q002
type: wiki_query
intent: Locate Adaptive Card / MS Teams rendering code
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F002 — Adaptive Card / Teams code landscape (wiki)

## Summary
wiki_query surfaced an EXISTING `AdaptiveCardRenderer` for FormSchema (`renderers/adaptive_card.py`, score 29.08, from TASK-524), the Teams wrapper (`msteams/wrapper.py`), TASK-2545 (Adaptive Cards native inputs + `Action.Submit{a2ui_action}` + Teams routing), and the msagentsdk semantic-cards doc. The feature is therefore an extension of shipped code, not greenfield.

## Citations
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  symbol: `AdaptiveCardRenderer` (wiki score 29.08)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  symbol: MS Teams Agent Wrapper (score 29.28)
- path: `sdd/tasks/completed/TASK-2545-adaptive-cards-native-inputs-teams-submit.md`
  symbol: TASK-2545 (score 29.55)
- path: `sdd/tasks/completed/TASK-524-adaptive-card-renderer.md`
  symbol: TASK-524 (score 36.20)
- path: `docs/integrations/msagentsdk-semantic-cards.md`
  symbol: FEAT-303 semantic cards doc (score 28.93)
