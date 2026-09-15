---
id: F004
query_id: Q004
type: wiki_query
intent: Orient: A2UI action/submit/userAction handling
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F004 — A2UI action / submit routing landscape (wiki)

## Summary

Action handling exists on three paths: MS Teams native Adaptive Cards submit routing (`a2ui_action`, TASK-2545), the deep-link resume helper `integrations/a2ui_resume.py`, and the `A2UIRuntime.dispatch` runtime (tests `runtime/test_dispatch.py`, TASK-2569). `build_form()` in `catalog/parrot/form.py` is the only existing form composition helper.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/a2ui_resume.py`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/a2ui_resume.py
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py`
  wiki_page_id: file:packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py
- path: `packages/ai-parrot/tests/outputs/a2ui/runtime/test_dispatch.py`
  wiki_page_id: file:packages/ai-parrot/tests/outputs/a2ui/runtime/test_dispatch.py
- path: `sdd/tasks/completed/TASK-2545-adaptive-cards-native-inputs-teams-submit.md`
  wiki_page_id: file:sdd/tasks/completed/TASK-2545-adaptive-cards-native-inputs-teams-submit.md
